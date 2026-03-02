import asyncio
import glob
import json
import logging
import os
import re
import sys
import time

from db import init_db, store_message, get_next_inbox_id, get_byte_offset, update_byte_offset
from tmux_io import send_keys
from telegram_bot import create_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MARKER_PATTERN = re.compile(
    r"<<<CC_OUT_START>>>\s*\n(.*?)\n\s*<<<CC_OUT_END>>>",
    re.DOTALL,
)

# Strip timestamp prefix added by `ts`, e.g. "[2026-03-02T14:23:05] "
TS_PREFIX = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]\s?", re.MULTILINE)


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


def read_new_content(log_path, db_path):
    """Read new content from a log file since last offset."""
    if not os.path.exists(log_path):
        return ""
    offset = get_byte_offset(db_path, log_path)
    file_size = os.path.getsize(log_path)
    if file_size <= offset:
        return ""
    with open(log_path, "rb") as f:
        f.seek(offset)
        data = f.read()
    update_byte_offset(db_path, log_path, file_size)
    return data.decode("utf-8", errors="replace")


def strip_timestamps(text):
    """Remove ts-added timestamp prefixes from log lines."""
    return TS_PREFIX.sub("", text)


def parse_outbound_messages(content):
    """Extract CC_OUT messages from log content."""
    clean = strip_timestamps(content)
    messages = []
    for match in MARKER_PATTERN.finditer(clean):
        try:
            payload = json.loads(match.group(1).strip())
            messages.append(payload)
        except json.JSONDecodeError:
            logger.warning("Failed to parse CC_OUT JSON: %s", match.group(1)[:200])
    return messages


async def poll_main_log(config, bot_app):
    """Poll main.log for outbound messages to Telegram."""
    db_path = config["_db_path"]
    main_log = os.path.join(config["_logs_dir"], "main.log")
    # We need the bot to send messages; get it from the app
    bot = bot_app.bot

    # Determine chat_id from whitelist (first whitelisted user's chat)
    # We'll store it when we receive the first inbound message
    # For now, read from DB
    pass

    content = read_new_content(main_log, db_path)
    if not content:
        return

    messages = parse_outbound_messages(content)
    for msg in messages:
        text = msg.get("msg", "")
        if not text:
            continue

        # Find the chat_id to reply to from the most recent inbound message
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
                logger.info("Sent outbound message to chat %s", chat_id)
            except Exception as e:
                logger.error("Failed to send Telegram message: %s", e)
        else:
            logger.warning("No inbound messages yet, can't determine chat_id. Dropping: %s", text[:100])


async def poll_worker_logs(config):
    """Poll worker t*.log files and relay new content to main."""
    db_path = config["_db_path"]
    logs_dir = config["_logs_dir"]
    inbox_dir = config["_inbox_dir"]

    pattern = os.path.join(logs_dir, "t*.log")
    for log_path in glob.glob(pattern):
        basename = os.path.basename(log_path)
        worker_name = basename.replace(".log", "")  # e.g. "t01"

        content = read_new_content(log_path, db_path)
        if not content:
            continue

        # Write content to inbox file
        next_id = get_next_inbox_id(db_path, worker_name)
        filename = f"{worker_name}_{next_id:09d}.txt"
        file_path = os.path.join(inbox_dir, filename)
        abs_file_path = os.path.abspath(file_path)

        os.makedirs(inbox_dir, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)

        # Notify main session
        send_keys("main", f"WORKER_UPDATE {worker_name}: {abs_file_path}")
        logger.info("Relayed worker %s output to main (%s)", worker_name, filename)


async def polling_loop(config, bot_app):
    """Main polling loop that runs every poll_interval_seconds."""
    interval = config.get("poll_interval_seconds", 30)
    logger.info("Starting polling loop (interval=%ds)", interval)

    while True:
        try:
            await poll_main_log(config, bot_app)
        except Exception as e:
            logger.error("Error polling main log: %s", e)

        try:
            await poll_worker_logs(config)
        except Exception as e:
            logger.error("Error polling worker logs: %s", e)

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
