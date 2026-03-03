import asyncio
import json
import logging
import os
import re
import subprocess
import time

from db import init_db, store_message, record_outbox_message
from tmux_io import send_keys
from telegram_bot import create_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config["_base_dir"] = base_dir
    config["_db_path"] = os.path.join(base_dir, config["db_path"])
    config["_inbox_dir"] = os.path.join(base_dir, config["inbox_dir"])
    config["_data_dir"] = os.path.join(base_dir, "data")
    config["_logs_dir"] = os.path.join(base_dir, config["logs_dir"])
    return config


# In-memory counters: {"main": 0, "t01": 0, ...}
counters = {}


def ensure_session(name, config):
    """Ensure a tmux session exists for the given actor. Create if needed."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    if result.returncode == 0:
        return  # session already exists

    base_dir = config["_base_dir"]
    data_dir = os.path.join(config["_data_dir"], name)
    workspace_dir = os.path.join(base_dir, "workspaces", name)

    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(workspace_dir, exist_ok=True)

    # Write worker CLAUDE.md
    claude_md = f"""# You are worker {name}

You run in tmux session "{name}" on a VPS. You receive tasks from Main and report results back.

The project root is `$HOME/ccclaw`.

## Receiving messages

- `MSG: /path/to/file` — Read the file for the message content.

## Sending messages

Write a JSON file to your outbox directory. Example:

File: $HOME/ccclaw/data/{name}/msg_000000001.json
Content:
{{"to":"main","msg":"Your results here"}}

Rules:
- Each message is a separate .json file in `$HOME/ccclaw/data/{name}/`
- Use sequential filenames: msg_000000001.json, msg_000000002.json, ...
- Start from 1 and increment for each message you send
- The JSON must have "to" and "msg" fields
- The content must be valid JSON — do NOT escape characters like ! or ?

## Guidelines

- Complete the task you are given
- Report results back to main when done
- Stay alive for follow-up tasks
"""
    with open(os.path.join(workspace_dir, "CLAUDE.md"), "w") as f:
        f.write(claude_md)

    # Also accept trust for this workspace in Claude config
    claude_config_path = os.path.expanduser("~/.claude.json")
    try:
        with open(claude_config_path) as f:
            claude_config = json.load(f)
        projects = claude_config.get("projects", {})
        projects[workspace_dir] = projects.get(workspace_dir, {})
        projects[workspace_dir]["hasTrustDialogAccepted"] = True
        claude_config["projects"] = projects
        with open(claude_config_path, "w") as f:
            json.dump(claude_config, f, separators=(",", ":"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not update Claude config for workspace %s", workspace_dir)

    env_file = os.path.join(base_dir, ".env")
    cmd = (
        f"set -a && source {env_file} && set +a && "
        f"cd {workspace_dir} && "
        f"claude --dangerously-skip-permissions --model claude-sonnet-4-6"
    )
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-y", "50", cmd],
        check=True,
    )
    logger.info("Created tmux session '%s', waiting for Claude to boot...", name)
    time.sleep(8)


async def poll_outboxes(config, bot_app):
    """Scan data/main/ and data/t*/ for new JSON message files and route them."""
    db_path = config["_db_path"]
    data_dir = config["_data_dir"]
    bot = bot_app.bot

    # Discover all actor directories
    if not os.path.isdir(data_dir):
        return

    actor_dirs = []
    for entry in os.listdir(data_dir):
        entry_path = os.path.join(data_dir, entry)
        if os.path.isdir(entry_path) and (entry == "main" or re.match(r"^t\d+$", entry)):
            actor_dirs.append(entry)

    for actor in actor_dirs:
        actor_dir = os.path.join(data_dir, actor)

        # Initialize counter if needed
        if actor not in counters:
            # Scan existing files to find the highest number
            highest = 0
            for fname in os.listdir(actor_dir):
                m = re.match(r"^msg_(\d+)\.json$", fname)
                if m:
                    n = int(m.group(1))
                    if n > highest:
                        highest = n
            counters[actor] = highest
            # On first discovery, mark all existing files as already processed
            # so we don't re-send old messages on bridge restart
            if highest > 0:
                logger.info("Initialized counter for '%s' at %d (skipping existing)", actor, highest)
                continue

        n = counters[actor] + 1
        while True:
            filename = f"msg_{n:09d}.json"
            file_path = os.path.join(actor_dir, filename)

            if not os.path.exists(file_path):
                break

            try:
                with open(file_path) as f:
                    raw = f.read()
                # Fix invalid JSON escapes that Claude may produce
                raw = re.sub(r'\\([^"\\/bfnrtu])', r'\1', raw)
                payload = json.loads(raw)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", file_path, e)
                record_outbox_message(db_path, file_path, None)
                n += 1
                continue

            to = payload.get("to", "")
            msg = payload.get("msg", "")

            if not msg:
                record_outbox_message(db_path, file_path, None)
                n += 1
                continue

            if to == "user":
                # Send via Telegram
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT chat_id FROM messages WHERE direction='in' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                conn.close()

                if row:
                    chat_id = row["chat_id"]
                    try:
                        await bot.send_message(chat_id=chat_id, text=msg)
                        store_message(db_path, "out", chat_id, None, msg)
                        record_outbox_message(db_path, file_path, msg)
                        logger.info("[%s] -> user (Telegram): %s", actor, msg[:80])
                    except Exception as e:
                        logger.error("Failed to send Telegram message: %s", e)
                else:
                    logger.warning("No inbound messages yet, can't determine chat_id. Dropping: %s", msg[:100])

            elif to == "main" or re.match(r"^t\d+$", to):
                # Route to another tmux session
                ensure_session(to, config)
                abs_path = os.path.abspath(file_path)
                send_keys(to, f"MSG: {abs_path}")
                record_outbox_message(db_path, file_path, msg)
                logger.info("[%s] -> %s: %s", actor, to, msg[:80])

            else:
                logger.warning("Unknown 'to' target '%s' in %s", to, file_path)
                record_outbox_message(db_path, file_path, None)

            n += 1

        counters[actor] = n - 1


async def polling_loop(config, bot_app):
    """Main polling loop that runs every poll_interval_seconds."""
    interval = config.get("poll_interval_seconds", 3)
    logger.info("Starting polling loop (interval=%ds)", interval)

    while True:
        try:
            await poll_outboxes(config, bot_app)
        except Exception as e:
            logger.error("Error polling outboxes: %s", e)

        await asyncio.sleep(interval)


async def main():
    config = load_config()
    logger.info("CCCLAW Bridge starting...")

    # Init database
    init_db(config["_db_path"])
    logger.info("Database initialized at %s", config["_db_path"])

    # Create dirs
    os.makedirs(config["_inbox_dir"], exist_ok=True)
    os.makedirs(os.path.join(config["_data_dir"], "main"), exist_ok=True)
    os.makedirs(config["_logs_dir"], exist_ok=True)

    # Create Telegram bot
    bot_app = create_bot(config)

    # Start bot polling and our log polling loop concurrently
    async with bot_app:
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Telegram bot started")

        try:
            await polling_loop(config, bot_app)
        finally:
            await bot_app.updater.stop()
            await bot_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
