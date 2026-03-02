#!/bin/bash
set -e

CCCLAW_DIR="$HOME/ccclaw"

set -a
source "$CCCLAW_DIR/.env"
set +a

# Create dirs
mkdir -p "$CCCLAW_DIR/data"/{logs,inbox}
mkdir -p "$CCCLAW_DIR/workspaces/main"

# Start main session
tmux new-session -d -s main \
  "set -a && source $CCCLAW_DIR/.env && set +a && cd $CCCLAW_DIR/workspaces/main && claude --dangerously-skip-permissions --model claude-haiku-4-5"
tmux pipe-pane -t main \
  "exec ts '[%Y-%m-%dT%H:%M:%S]' >> $CCCLAW_DIR/data/logs/main.log"

# Auto-select dark theme if first-run picker appears
sleep 3
tmux send-keys -t main Enter

# Start bridge
cd "$CCCLAW_DIR/bridge"
nohup python3 main.py >> ../data/logs/bridge.log 2>&1 &

echo "CCCLAW started."
echo "  Attach main: tmux attach -t main"
echo "  Bridge log:  tail -f $CCCLAW_DIR/data/logs/bridge.log"
