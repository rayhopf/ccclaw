import subprocess
import logging

logger = logging.getLogger(__name__)


def send_keys(session, text):
    """Send keys to a tmux session."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session, text, "Enter"],
            check=True,
            capture_output=True,
        )
        logger.info("Sent keys to tmux session '%s'", session)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to send keys to '%s': %s", session, e.stderr.decode())
        raise
