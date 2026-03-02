# TODO — Known Issues from Deploy Testing

## Claude Code Interactive Prompts

Claude Code has multiple first-run interactive prompts that block the tmux session from becoming usable. We've fixed some but not all.

### Fixed
- **Theme picker** — Solved by pre-setting `hasCompletedOnboarding: true` in `~/.claude.json`
- **Trust folder dialog** — Solved by pre-setting `projects[path].hasTrustDialogAccepted: true` in `~/.claude.json`

### Not Yet Fixed
- **"Detected a custom API key" prompt** — Claude Code asks "Do you want to use this API key?" when it detects `ANTHROPIC_API_KEY` in the environment. Default selection is "No (recommended)". Need to find the config key to auto-accept, or find another way to bypass. This blocks the main session from starting.
- **Possible other prompts** — There may be additional first-run prompts we haven't encountered yet. Need a complete first-run walkthrough to identify all of them.

## Config Path Bug (Fixed)

- `config.json` had paths like `"../data/inbox"` which resolved incorrectly because `main.py` uses `os.path.dirname(__file__)/..` as base_dir. Fixed to `"data/inbox"` (relative to project root).

## deploy.sh Needs Update

- The `~/.claude.json` pre-configuration (step before step 5) needs to include the API key acceptance key once we find it
- The pre-config currently only sets `theme`, `hasCompletedOnboarding`, and `hasTrustDialogAccepted`
- Need to also write the `projects` dict with the correct project path for trust

## Minor

- `/start` command from Telegram is silently ignored because `telegram_bot.py` uses `filters.TEXT & ~filters.COMMAND`. Consider handling `/start` as a welcome message, or accept commands too.
