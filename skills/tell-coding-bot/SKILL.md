---
name: tell-coding-bot
description: Pointer (2026-11-06) for talking to the operator's cloud Grok Bot "Coding" ("tell the Coding bot", "ask Coding", "hand this to the Coding bot", a task that needs a real browser session); the coding-bot code now lives in the peer-link repository.
---

What it was: `coding-bot`, the one entry point any project used to push a task to the Grok Bot "Coding" (webhook `ask`/`send`/`wait`, a clipboard `prompt` fallback, `deliver` for the reply), from `bin/coding-bot` here until slim-down E6 (2026-11-06; the last copy is in this repository's git history).
Where the code went: the peer-link repository (`frdminc/peer-link`, re-homed with PR 269's wrapper per ruling E9j); the operator repoints `~/.local/bin/coding-bot` there.
What to run instead: `coding-bot --help` from that install (same subcommands); until it is linked, put a self-contained prompt on the clipboard for the operator to paste into the Coding bot, and never claim it was sent.
