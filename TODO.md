# TODO — Known Issues from Deploy Testing

## Claude Code Interactive Prompts

Claude Code has multiple first-run interactive prompts that block the tmux session from becoming usable. **All prompts are now solved.**

### Fixed (All)
- **Theme picker** — Solved by pre-setting `hasCompletedOnboarding: true` in `~/.claude.json`
- **Login method selector** — Part of the onboarding flow. Also skipped by `hasCompletedOnboarding: true`
- **Security notes screen** — Part of the onboarding flow. Also skipped by `hasCompletedOnboarding: true`
- **"Detected a custom API key" prompt** — Solved by pre-setting `customApiKeyResponses.approved` with the **last 20 characters** of the API key (found by reading Claude Code source: `function mV(A){return A.slice(-20)}`)
- **Trust folder dialog** — Solved by pre-setting `projects[path].hasTrustDialogAccepted: true` in `~/.claude.json`

### Complete ~/.claude.json Template

The following config bypasses ALL first-run prompts when `ANTHROPIC_API_KEY` is set in the environment:

```json
{
  "theme": "dark",
  "hasCompletedOnboarding": true,
  "customApiKeyResponses": {
    "approved": ["<LAST 20 CHARS OF API KEY>"]
  },
  "projects": {
    "<PROJECT_PATH>": {
      "hasTrustDialogAccepted": true
    }
  }
}
```

To compute the truncated key: `echo "$ANTHROPIC_API_KEY" | tail -c 21` or `key[-20:]` in Python.

### Full Onboarding Sequence (for reference)

When `hasCompletedOnboarding` is NOT set, the onboarding flow shows these steps in order:
1. **Preflight / login method** (only if OAuth is enabled, i.e. no API key)
2. **Theme picker**
3. **OAuth login** (only if OAuth is enabled)
4. **API key approval** (only if `ANTHROPIC_API_KEY` is set and key is not yet approved)
5. **Security notes**
6. **Terminal setup** (only on supported terminals)

After onboarding, the **trust dialog** is shown separately (outside onboarding) for each new project directory.

## Config Path Bug (Fixed)

- `config.json` had paths like `"../data/inbox"` which resolved incorrectly because `main.py` uses `os.path.dirname(__file__)/..` as base_dir. Fixed to `"data/inbox"` (relative to project root).

## deploy.sh Needs Update

- The `~/.claude.json` pre-configuration now has the complete template (see above)
- Need to compute the truncated API key dynamically in deploy.sh: `echo "$ANTHROPIC_API_KEY" | tail -c 21`

## Minor

- `/start` command from Telegram is silently ignored because `telegram_bot.py` uses `filters.TEXT & ~filters.COMMAND`. Consider handling `/start` as a welcome message, or accept commands too.
