#!/bin/bash
set -e

CCCLAW_DIR="$HOME/ccclaw"

set -a
source "$CCCLAW_DIR/.env"
set +a

# Create dirs
mkdir -p "$CCCLAW_DIR/data"/{logs,inbox,main}
mkdir -p "$CCCLAW_DIR/workspaces/main"

# Start main session
tmux new-session -d -s main \
  "set -a && source $CCCLAW_DIR/.env && set +a && cd $CCCLAW_DIR/workspaces/main && claude --dangerously-skip-permissions --model claude-sonnet-4-6"

# Start bridge
cd "$CCCLAW_DIR/bridge"
nohup python3 main.py >> ../data/logs/bridge.log 2>&1 &

echo "CCCLAW started."
echo "  Attach main: tmux attach -t main"
echo "  Bridge log:  tail -f $CCCLAW_DIR/data/logs/bridge.log"
