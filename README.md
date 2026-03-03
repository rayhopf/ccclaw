# CCCLAW

Claude Code orchestrator with Telegram bridge. Runs Claude Code instances in tmux sessions on a VPS, controlled via Telegram.

## Architecture

```
Telegram User ↔ Bridge (Python) ↔ tmux "main" (Claude Sonnet orchestrator)
                                       ↕
                                 tmux "t01..tNN" (Claude Sonnet workers)
```

- **Bridge** — Python process that polls JSON outbox files and routes messages
- **Main** — Claude Sonnet orchestrator running in tmux, receives user messages, dispatches to workers
- **Workers** — Claude Sonnet instances auto-spawned by the bridge on demand

## Message Flow

Each actor writes JSON files to its own outbox folder (`data/{name}/`). The bridge polls every 1s and routes by the `"to"` field.

```
User → Telegram → Bridge writes data/inbox/msg_NNN.txt → send-keys "MSG: path" to main
Main → writes {"to":"user","msg":"..."} to data/main/ → Bridge sends via Telegram
Main → writes {"to":"t01","msg":"..."} to data/main/ → Bridge auto-spawns t01 → send-keys to t01
t01  → writes {"to":"main","msg":"..."} to data/t01/ → Bridge → send-keys to main
```

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
2. Installs system deps (Python, tmux, git)
3. Installs nvm + Node.js + Claude Code CLI
4. Clones this repo to `~/ccclaw`
5. Writes `.env` (API key) and `config.json` (bot token, whitelist)
6. Pre-configures `~/.claude.json` to skip all onboarding prompts
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
│   ├── main.py             # Bridge: polls outboxes, routes messages, spawns workers
│   ├── telegram_bot.py     # Telegram handler
│   ├── tmux_io.py          # tmux send-keys helper
│   ├── db.py               # SQLite operations
│   ├── config.json         # Bot token, whitelist (written by deploy)
│   └── requirements.txt
├── data/
│   ├── ccclaw.db           # SQLite database
│   ├── inbox/              # Telegram messages (bridge writes here)
│   ├── main/               # Main outbox (main writes here)
│   ├── t01/                # Worker outbox (created by bridge on demand)
│   └── logs/
├── workspaces/
│   ├── main/               # Orchestrator working dir + CLAUDE.md
│   └── tNN/                # Worker working dirs (created by bridge)
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
