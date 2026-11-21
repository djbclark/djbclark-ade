---
name: tell-coding-bot
description: Pointer (2026-11-06, updated 2026-11-21) for talking to the operator's cloud Grok Bot "Coding". NOT an ordinary delegation target: the operator ruled (2026-11-21) that ordinary coding work is taken on by the agent itself (sub-agents where appropriate), and the Coding bot is only the try-first destination for tasks that need real UI/browser interaction. The route is not working today (nothing exists at ~/.local/bin/coding-bot, not even a dangling link, checked 2026-11-21; bin/coding-bot left in slim-down E6), so never claim a task was sent.
---

What it was: `coding-bot`, the one entry point any project used to push a task to the Grok Bot "Coding" (webhook `ask`/`send`/`wait`, a clipboard `prompt` fallback, `deliver` for the reply), from `bin/coding-bot` here until slim-down E6 (2026-11-06; the last copy is in this repository's git history).
Where the code went: the peer-link repository (`frdminc/peer-link`, re-homed with PR 269's wrapper per ruling E9j); the operator repoints `~/.local/bin/coding-bot` there.
What to run instead: `coding-bot --help` from that install (same subcommands); until it is linked, put a self-contained prompt on the clipboard for the operator to paste into the Coding bot, and never claim it was sent.
