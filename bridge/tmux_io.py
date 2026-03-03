import subprocess
import logging
import time

logger = logging.getLogger(__name__)


def send_keys(session, text):
    """Send keys to a tmux session.

    Sends text first, then Enter after a short delay.
    Claude Code's TUI needs a moment to register the text
    before the Enter key is sent to submit.
    """
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session, text],
            check=True,
            capture_output=True,
        )
        time.sleep(0.5)
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "Enter"],
            check=True,
            capture_output=True,
        )
        logger.info("Sent keys to tmux session '%s'", session)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to send keys to '%s': %s", session, e.stderr.decode())
        raise
