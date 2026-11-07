---
name: tell-chief-of-staff
description: Pointer (2026-11-06) for messaging the operator's cloud Grok Bot "Chief of Staff" ("tell grok", "tell Chief of Staff", "hand this to grokbot") and for its ask_claude callback; the sender and its setup live outside this repository.
---

What it was: this skill's instructions for POSTing `{"from":"claude-code","message":...}` to the Chief of Staff webhook and for the read-only `ask_claude` MCP callback (`~/.local/libexec/claude-mcp-bridge/claude_mcp.py`); reduced to a pointer in slim-down E6 (2026-11-06; the full text is in git history).
Where the code went: the sender is Hermes's `~/.hermes/skills/agent-tooling/tell-chief-of-staff/scripts/tell_chief_of_staff.py` (its `setup.sh` stores the Keychain items); the Grok-bot channel code is re-homed to the peer-link repository (`frdminc/peer-link`, ruling E9j).
What to run instead: `~/.hermes/skills/agent-tooling/tell-chief-of-staff/scripts/tell_chief_of_staff.py --from claude-code "self-contained message"` (or `-` for stdin); it prints `sent (HTTP nnn)` and is fire-and-forget; send only what the operator asked to share, never secrets.
