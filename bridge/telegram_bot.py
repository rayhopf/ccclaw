import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from db import store_message, get_next_inbox_id
from tmux_io import send_keys

logger = logging.getLogger(__name__)


def create_bot(config):
    token = config["telegram_bot_token"]
    whitelist = set(config["whitelist_usernames"])
    db_path = config["_db_path"]
    inbox_dir = config["_inbox_dir"]
    base_dir = config["_base_dir"]

    app = ApplicationBuilder().token(token).build()

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        username = update.effective_user.username
        if username not in whitelist:
            logger.warning("Rejected message from non-whitelisted user: %s", username)
            return

        chat_id = update.effective_chat.id
        text = update.message.text or ""

        # Get next inbox ID and write file
        next_id = get_next_inbox_id(db_path, "msg")
        filename = f"msg_{next_id:09d}.txt"
        file_path = os.path.join(inbox_dir, filename)
        abs_file_path = os.path.abspath(file_path)

        os.makedirs(inbox_dir, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(text)

        # Store in DB
        store_message(db_path, "in", chat_id, username, text, abs_file_path)

        # Send to main tmux session
        send_keys("main", f"MSG: {abs_file_path}")

        logger.info("Received message from %s, wrote to %s", username, filename)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
