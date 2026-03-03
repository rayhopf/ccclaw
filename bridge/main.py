import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
import subprocess
import sys

from db import init_db, store_message, get_next_inbox_id, get_processed_hashes, add_processed_hash, get_pane_snapshot, set_pane_snapshot
from tmux_io import send_keys
from telegram_bot import create_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MARKER_PATTERN = re.compile(
    r"CCCLAW_MSG_START\s*\n(.*?)\n\s*CCCLAW_MSG_END",
    re.DOTALL,
)


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config["_base_dir"] = base_dir
    config["_db_path"] = os.path.join(base_dir, config["db_path"])
    config["_inbox_dir"] = os.path.join(base_dir, config["inbox_dir"])
    config["_logs_dir"] = os.path.join(base_dir, config["logs_dir"])
    return config


def capture_pane(session):
    """Capture the full scrollback of a tmux pane as clean text."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", "-"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except FileNotFoundError:
        return None


def list_tmux_sessions():
    """List all active tmux session names."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
    except FileNotFoundError:
        return []


def log_pane_capture(logs_dir, session, content):
    """Append a timestamped capture-pane snapshot to the session's log file."""
    log_path = os.path.join(logs_dir, f"{session}.log")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(logs_dir, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"\n--- capture-pane [{timestamp}] ---\n")
        f.write(content)


def parse_outbound_messages(content):
    """Extract CCCLAW_MSG messages from pane content."""
    messages = []
    for match in MARKER_PATTERN.finditer(content):
        try:
            payload = json.loads(match.group(1).strip())
            messages.append(payload)
        except json.JSONDecodeError:
            logger.warning("Failed to parse message JSON: %s", match.group(1)[:200])
    return messages


async def poll_main_pane(config, bot_app):
    """Capture main pane and send any new outbound messages to Telegram."""
    db_path = config["_db_path"]
    bot = bot_app.bot

    content = capture_pane("main")
    if not content:
        return

    log_pane_capture(config["_logs_dir"], "main", content)

    messages = parse_outbound_messages(content)
    if not messages:
        return

    # Get already-processed message hashes to avoid duplicates
    processed = get_processed_hashes(db_path)

    for msg in messages:
        text = msg.get("msg", "")
        if not text:
            continue

        msg_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if msg_hash in processed:
            continue

        # Find chat_id from most recent inbound message
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
                await bot.send_message(chat_id=chat_id, text=text)
                store_message(db_path, "out", chat_id, None, text)
                add_processed_hash(db_path, msg_hash)
                logger.info("Sent outbound message to chat %s", chat_id)
            except Exception as e:
                logger.error("Failed to send Telegram message: %s", e)
        else:
            logger.warning("No inbound messages yet, can't determine chat_id. Dropping: %s", text[:100])


async def poll_worker_panes(config):
    """Capture worker panes and relay new content to main."""
    db_path = config["_db_path"]
    inbox_dir = config["_inbox_dir"]

    sessions = list_tmux_sessions()
    worker_sessions = [s for s in sessions if re.match(r"^t\d+$", s)]

    for worker_name in worker_sessions:
        content = capture_pane(worker_name)
        if not content or not content.strip():
            continue

        log_pane_capture(config["_logs_dir"], worker_name, content)

        # Compare with last snapshot to detect new content
        prev = get_pane_snapshot(db_path, worker_name)
        if content == prev:
            continue

        set_pane_snapshot(db_path, worker_name, content)

        # Find the new portion (content after the previous snapshot)
        if prev and content.startswith(prev.rstrip()):
            new_content = content[len(prev.rstrip()):]
        else:
            new_content = content

        if not new_content.strip():
            continue

        # Write new content to inbox file
        next_id = get_next_inbox_id(db_path, worker_name)
        filename = f"{worker_name}_{next_id:09d}.txt"
        file_path = os.path.join(inbox_dir, filename)
        abs_file_path = os.path.abspath(file_path)

        os.makedirs(inbox_dir, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(new_content)

        send_keys("main", f"WORKER_UPDATE {worker_name}: {abs_file_path}")
        logger.info("Relayed worker %s output to main (%s)", worker_name, filename)


async def polling_loop(config, bot_app):
    """Main polling loop that runs every poll_interval_seconds."""
    interval = config.get("poll_interval_seconds", 30)
    logger.info("Starting polling loop (interval=%ds)", interval)

    while True:
        try:
            await poll_main_pane(config, bot_app)
        except Exception as e:
            logger.error("Error polling main pane: %s", e)

        try:
            await poll_worker_panes(config)
        except Exception as e:
            logger.error("Error polling worker panes: %s", e)

        await asyncio.sleep(interval)


async def main():
    config = load_config()
    logger.info("CCCLAW Bridge starting...")

    # Init database
    init_db(config["_db_path"])
    logger.info("Database initialized at %s", config["_db_path"])

    # Create dirs
    os.makedirs(config["_inbox_dir"], exist_ok=True)
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
