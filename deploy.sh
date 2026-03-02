#!/bin/bash
set -euo pipefail

# ============================================================
# CCCLAW Bootstrap Deployer
# Usage:
#   ./deploy.sh <VPS_IP> <ROOT_PASSWORD> <USERNAME> <ANTHROPIC_API_KEY> <TELEGRAM_BOT_TOKEN> <TELEGRAM_WHITELIST>
#
# Example:
#   ./deploy.sh 203.0.113.1 'rootpass123' ccclawuser01 'sk-ant-...' '7123456:AAF...' 'myusername,friend'
#
# TELEGRAM_WHITELIST is comma-separated Telegram usernames (no @)
# ============================================================

if [ "$#" -lt 6 ]; then
    echo "Usage: $0 <VPS_IP> <ROOT_PASSWORD> <USERNAME> <ANTHROPIC_API_KEY> <TELEGRAM_BOT_TOKEN> <TELEGRAM_WHITELIST>"
    echo ""
    echo "  VPS_IP             - IP address of the VPS"
    echo "  ROOT_PASSWORD      - Root password for SSH"
    echo "  USERNAME           - Linux username to create (e.g. ccclawuser01)"
    echo "  ANTHROPIC_API_KEY  - Anthropic API key"
    echo "  TELEGRAM_BOT_TOKEN - Telegram bot token from @BotFather"
    echo "  TELEGRAM_WHITELIST - Comma-separated Telegram usernames"
    exit 1
fi

VPS_IP="$1"
ROOT_PASS="$2"
USERNAME="$3"
API_KEY="$4"
BOT_TOKEN="$5"
WHITELIST="$6"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_HOME="/home/${USERNAME}"
REMOTE_PROJECT="${REMOTE_HOME}/ccclaw"

# Check for sshpass
if ! command -v sshpass &>/dev/null; then
    echo "ERROR: sshpass is required. Install it:"
    echo "  macOS:  brew install hudochenkov/sshpass/sshpass"
    echo "  Linux:  apt install sshpass"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

ssh_root() {
    sshpass -p "$ROOT_PASS" ssh $SSH_OPTS "root@${VPS_IP}" "$@"
}

scp_root() {
    sshpass -p "$ROOT_PASS" scp $SSH_OPTS -r "$@"
}

echo "=== CCCLAW Bootstrap Deploy ==="
echo "VPS: $VPS_IP | User: $USERNAME"
echo ""

# ----------------------------------------------------------
# Step 1: Create user with sudo
# ----------------------------------------------------------
echo "[1/7] Creating user '$USERNAME' with sudo..."
ssh_root bash <<CREATEUSER
set -e
if ! id "$USERNAME" &>/dev/null; then
    adduser --disabled-password --gecos '' "$USERNAME"
    echo "${USERNAME}:${ROOT_PASS}" | chpasswd
    usermod -aG sudo "$USERNAME"
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME
    echo "User created."
else
    echo "User already exists."
fi
CREATEUSER

# ----------------------------------------------------------
# Step 2: Install system dependencies
# ----------------------------------------------------------
echo "[2/7] Installing system dependencies..."
ssh_root bash <<DEPS
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv moreutils tmux curl git >/dev/null 2>&1
echo "System deps installed."
DEPS

# ----------------------------------------------------------
# Step 3: Install nvm + Node.js + Claude Code CLI as user
# ----------------------------------------------------------
echo "[3/7] Installing Node.js and Claude Code CLI..."
ssh_root bash <<NODESETUP
set -e
su - $USERNAME <<'USERBLOCK'
set -e

# Install nvm if not present
if [ ! -d "\$HOME/.nvm" ]; then
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh 2>/dev/null | bash
fi

export NVM_DIR="\$HOME/.nvm"
[ -s "\$NVM_DIR/nvm.sh" ] && . "\$NVM_DIR/nvm.sh"

# Install latest LTS Node
nvm install --lts 2>/dev/null
nvm use --lts 2>/dev/null

# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code 2>/dev/null

echo "Node.js \$(node -v) and Claude Code CLI installed."
USERBLOCK
NODESETUP

# ----------------------------------------------------------
# Step 4: Copy project files
# ----------------------------------------------------------
echo "[4/7] Copying project files..."
ssh_root "mkdir -p ${REMOTE_PROJECT} && chown -R ${USERNAME}:${USERNAME} ${REMOTE_PROJECT}"

# Create a temp tarball of the project (excluding .git and deploy.sh itself)
TMPTAR=$(mktemp /tmp/ccclaw-XXXXXX.tar.gz)
tar -czf "$TMPTAR" -C "$SCRIPT_DIR" \
    --exclude='.git' \
    --exclude='deploy.sh' \
    --exclude='.DS_Store' \
    .

scp_root "$TMPTAR" "root@${VPS_IP}:/tmp/ccclaw-deploy.tar.gz"
rm -f "$TMPTAR"

ssh_root bash <<EXTRACT
set -e
cd ${REMOTE_PROJECT}
tar -xzf /tmp/ccclaw-deploy.tar.gz
rm -f /tmp/ccclaw-deploy.tar.gz
chown -R ${USERNAME}:${USERNAME} ${REMOTE_PROJECT}
EXTRACT

# ----------------------------------------------------------
# Step 5: Configure (API key, bot token, whitelist)
# ----------------------------------------------------------
echo "[5/7] Writing configuration..."

# Convert comma-separated whitelist to JSON array
WHITELIST_JSON=$(echo "$WHITELIST" | python3 -c "
import sys, json
names = [n.strip().lstrip('@') for n in sys.stdin.read().split(',') if n.strip()]
print(json.dumps(names))
")

ssh_root bash <<CONFIG
set -e

# Write .env
cat > ${REMOTE_PROJECT}/.env <<ENVFILE
ANTHROPIC_API_KEY=${API_KEY}
ENVFILE
chown ${USERNAME}:${USERNAME} ${REMOTE_PROJECT}/.env
chmod 600 ${REMOTE_PROJECT}/.env

# Write config.json with actual values
cat > ${REMOTE_PROJECT}/bridge/config.json <<CONFIGJSON
{
  "telegram_bot_token": "${BOT_TOKEN}",
  "whitelist_usernames": ${WHITELIST_JSON},
  "poll_interval_seconds": 30,
  "db_path": "../data/ccclaw.db",
  "inbox_dir": "../data/inbox",
  "logs_dir": "../data/logs",
  "max_workers": 10
}
CONFIGJSON

chown ${USERNAME}:${USERNAME} ${REMOTE_PROJECT}/bridge/config.json


echo "Configuration written."
CONFIG

# ----------------------------------------------------------
# Step 6: Install Python dependencies
# ----------------------------------------------------------
echo "[6/7] Installing Python dependencies..."
ssh_root bash <<PYDEPS
set -e
su - $USERNAME <<'USERBLOCK'
set -e
cd ~/ccclaw/bridge
pip3 install --break-system-packages -q -r requirements.txt 2>/dev/null || pip3 install -q -r requirements.txt
echo "Python deps installed."
USERBLOCK
PYDEPS

# ----------------------------------------------------------
# Step 7: Create directories and start
# ----------------------------------------------------------
echo "[7/7] Starting CCCLAW..."
ssh_root bash <<START
set -e
su - $USERNAME <<'USERBLOCK'
set -e
cd ~/ccclaw

# Make start.sh executable
chmod +x start.sh

# Create required directories
mkdir -p data/{logs,inbox}
mkdir -p workspaces/main

# Kill existing sessions if any
tmux kill-server 2>/dev/null || true

# Source nvm for this shell
export NVM_DIR="\$HOME/.nvm"
[ -s "\$NVM_DIR/nvm.sh" ] && . "\$NVM_DIR/nvm.sh"

# Start
bash start.sh

echo ""
echo "CCCLAW is running!"
USERBLOCK
START

echo ""
echo "=== CCCLAW Deploy Complete ==="
echo ""
echo "To attach to the orchestrator:"
echo "  ssh ${USERNAME}@${VPS_IP}"
echo "  tmux attach -t main"
echo ""
echo "To view bridge logs:"
echo "  ssh ${USERNAME}@${VPS_IP}"
echo "  tail -f ~/ccclaw/data/logs/bridge.log"
echo ""
echo "Send a Telegram message to your bot to test!"
