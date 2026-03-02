# CCCLAW

Claude Code orchestrator with Telegram bridge. Runs Claude Code instances in tmux sessions on a VPS, controlled via Telegram.

## Architecture

```
Telegram User ↔ Bridge (Python) ↔ tmux "main" (Claude Haiku orchestrator)
                                       ↕
                                 tmux "t01..tNN" (Claude Sonnet workers)
```

- **Bridge** — Python process that connects Telegram to tmux via file-based messaging
- **Main** — Claude Haiku orchestrator running in tmux, receives user messages, spawns workers
- **Workers** — Claude Sonnet instances spawned by main for subtasks

## One-liner Deploy

```bash
sshpass -p 'ROOT_PASS' ssh -o StrictHostKeyChecking=no root@VPS_IP \
  "bash <(curl -sL https://raw.githubusercontent.com/rayhopf/ccclaw/main/deploy.sh) \
    USERNAME ANTHROPIC_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_WHITELIST"
```

### Parameters

| Parameter | Description | Example |
|---|---|---|
| `USERNAME` | Linux user to create | `myccclaw01` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `7123456:AAF...` |
| `TELEGRAM_WHITELIST` | Comma-separated Telegram usernames (no @) | `alice,bob` |

### What deploy.sh does

1. Creates Linux user with sudo
2. Installs system deps (Python, moreutils, tmux, git)
3. Installs nvm + Node.js + Claude Code CLI
4. Clones this repo to `~/ccclaw`
5. Writes `.env` (API key) and `config.json` (bot token, whitelist)
6. Pre-configures `~/.claude.json` to skip onboarding prompts
7. Starts tmux main session + bridge

### Prerequisites

- VPS running Ubuntu 24.04 with root SSH access
- `sshpass` on your local machine (`brew install hudochenkov/sshpass/sshpass` on macOS)
- Telegram bot token from [@BotFather](https://t.me/BotFather)

## Directory Structure (on VPS)

```
~/ccclaw/
├── .env                    # API keys (not in git)
├── bridge/
│   ├── main.py             # Bridge entry point
│   ├── telegram_bot.py     # Telegram handler
│   ├── tmux_io.py          # tmux send-keys helper
│   ├── db.py               # SQLite operations
│   ├── config.json         # Bot token, whitelist (written by deploy)
│   └── requirements.txt
├── data/
│   ├── ccclaw.db           # SQLite database
│   ├── inbox/              # Message files
│   └── logs/               # tmux pipe-pane logs
├── workspaces/
│   ├── main/               # Orchestrator working dir
│   │   └── CLAUDE.md       # Orchestrator instructions
│   └── tNN/                # Worker working dirs
└── start.sh                # Starts tmux + bridge
```

## After Deploy

```bash
# Attach to orchestrator
ssh USERNAME@VPS_IP
tmux attach -t main

# View bridge logs
tail -f ~/ccclaw/data/logs/bridge.log
```

Send a message to your Telegram bot to test.
