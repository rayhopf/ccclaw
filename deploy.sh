#!/bin/bash
set -euo pipefail

# ============================================================
# CCCLAW Bootstrap Deployer — runs ON the VPS as root
#
# One-liner from your local machine:
#   sshpass -p 'ROOT_PASS' ssh -o StrictHostKeyChecking=no root@VPS_IP \
#     "bash <(curl -sL https://raw.githubusercontent.com/rayhopf/ccclaw/main/deploy.sh) \
#       USERNAME ANTHROPIC_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_WHITELIST"
#
# Example:
#   sshpass -p 'N8X...' ssh root@203.0.113.1 \
#     "bash <(curl -sL https://raw.githubusercontent.com/rayhopf/ccclaw/main/deploy.sh) \
#       myccclaw01 sk-ant-... 7123456:AAF... myuser,friend"
# ============================================================

REPO_URL="https://github.com/rayhopf/ccclaw.git"

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <USERNAME> <ANTHROPIC_API_KEY> <TELEGRAM_BOT_TOKEN> <TELEGRAM_WHITELIST>"
    echo ""
    echo "  USERNAME           - Linux username to create (e.g. myccclaw01)"
    echo "  ANTHROPIC_API_KEY  - Anthropic API key"
    echo "  TELEGRAM_BOT_TOKEN - Telegram bot token from @BotFather"
    echo "  TELEGRAM_WHITELIST - Comma-separated Telegram usernames (no @)"
    echo ""
    echo "This script must run on the VPS as root."
    exit 1
fi

USERNAME="$1"
API_KEY="$2"
BOT_TOKEN="$3"
WHITELIST="$4"

USER_HOME="/home/${USERNAME}"
PROJECT_DIR="${USER_HOME}/ccclaw"

echo "=== CCCLAW Bootstrap Deploy ==="
echo "User: $USERNAME"
echo ""

# ----------------------------------------------------------
# Step 1: Create user with sudo
# ----------------------------------------------------------
echo "[1/6] Creating user '$USERNAME' with sudo..."
if ! id "$USERNAME" &>/dev/null; then
    adduser --disabled-password --gecos '' "$USERNAME"
    usermod -aG sudo "$USERNAME"
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME
    echo "User created."
else
    echo "User already exists."
fi

# ----------------------------------------------------------
# Step 2: Install system dependencies
# ----------------------------------------------------------
echo "[2/6] Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv moreutils tmux curl git >/dev/null 2>&1
echo "System deps installed."

# ----------------------------------------------------------
# Step 3: Install nvm + Node.js + Claude Code CLI as user
# ----------------------------------------------------------
echo "[3/6] Installing Node.js and Claude Code CLI..."
su - "$USERNAME" bash -c '
set -e
if [ ! -d "$HOME/.nvm" ]; then
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh 2>/dev/null | bash
fi
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install --lts 2>/dev/null
nvm use --lts 2>/dev/null
npm install -g @anthropic-ai/claude-code 2>/dev/null
echo "Node.js $(node -v) and Claude Code CLI installed."
'

# ----------------------------------------------------------
# Step 4: Clone repo as user
# ----------------------------------------------------------
echo "[4/6] Cloning repo..."
if [ -d "$PROJECT_DIR/.git" ]; then
    su - "$USERNAME" bash -c "cd $PROJECT_DIR && git pull"
    echo "Repo updated."
else
    rm -rf "$PROJECT_DIR"
    su - "$USERNAME" bash -c "git clone $REPO_URL $PROJECT_DIR"
    echo "Repo cloned."
fi

# Pre-configure Claude Code to skip first-run interactive theme picker
su - "$USERNAME" bash -c '
python3 -c "
import json, os
p = os.path.expanduser(\"~/.claude.json\")
d = {}
if os.path.exists(p):
    with open(p) as f: d = json.load(f)
d[\"theme\"] = \"dark\"
with open(p, \"w\") as f: json.dump(d, f, indent=2)
"
'

# ----------------------------------------------------------
# Step 5: Write configuration
# ----------------------------------------------------------
echo "[5/6] Writing configuration..."

# Build whitelist JSON array
WHITELIST_JSON=$(python3 -c "
import sys, json
names = [n.strip().lstrip('@') for n in '$WHITELIST'.split(',') if n.strip()]
print(json.dumps(names))
")

# Write .env
cat > "$PROJECT_DIR/.env" <<ENVFILE
ANTHROPIC_API_KEY=$API_KEY
ENVFILE
chown "$USERNAME:$USERNAME" "$PROJECT_DIR/.env"
chmod 600 "$PROJECT_DIR/.env"

# Write config.json
cat > "$PROJECT_DIR/bridge/config.json" <<CONFIGJSON
{
  "telegram_bot_token": "$BOT_TOKEN",
  "whitelist_usernames": $WHITELIST_JSON,
  "poll_interval_seconds": 30,
  "db_path": "data/ccclaw.db",
  "inbox_dir": "data/inbox",
  "logs_dir": "data/logs",
  "max_workers": 10
}
CONFIGJSON
chown "$USERNAME:$USERNAME" "$PROJECT_DIR/bridge/config.json"

# Install Python deps
su - "$USERNAME" bash -c '
cd ~/ccclaw/bridge
pip3 install --break-system-packages -q -r requirements.txt 2>/dev/null || pip3 install -q -r requirements.txt
'
echo "Configuration written."

# ----------------------------------------------------------
# Step 6: Start CCCLAW
# ----------------------------------------------------------
echo "[6/6] Starting CCCLAW..."
su - "$USERNAME" bash -c '
cd ~/ccclaw
chmod +x start.sh
mkdir -p data/{logs,inbox}
mkdir -p workspaces/main

tmux kill-server 2>/dev/null || true

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

bash start.sh
'

echo ""
echo "=== CCCLAW Deploy Complete ==="
echo ""
echo "  Attach main:  su - $USERNAME -c 'tmux attach -t main'"
echo "  Bridge log:   tail -f $PROJECT_DIR/data/logs/bridge.log"
echo ""
echo "Send a Telegram message to your bot to test!"
