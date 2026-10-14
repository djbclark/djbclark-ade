---
name: tell-chief-of-staff
description: Send a message from Claude Code to the operator's cloud Grok Bot "Chief of Staff" via its inbound webhook, and understand how Chief of Staff can call back into Claude (ask_claude MCP tool). Use when the operator says "tell grok", "tell Chief of Staff", "hand this to grokbot", or when a task needs the Chief of Staff's attention or a result reported to it.
---

# Claude Code <-> Grok Bot "Chief of Staff"

Two directions, both live once the webhook is configured:

1. **Claude -> Chief of Staff (this skill).** POSTs `{"from":"claude-code","message":...}` to the
   Chief of Staff webhook using the shared Hermes sender script:

   ```bash
   ~/.hermes/skills/agent-tooling/tell-chief-of-staff/scripts/tell_chief_of_staff.py --from claude-code "message"
   echo "longer text" | ~/.hermes/skills/agent-tooling/tell-chief-of-staff/scripts/tell_chief_of_staff.py --from claude-code -
   ```

   Prints `sent (HTTP nnn)`. Fire-and-forget: the webhook returns no answer. Never print the URL/key
   (Keychain `grok-cos-webhook-url` / `-key`, account `hermes`). If it says a Keychain item is missing,
   the operator has not run `~/.hermes/skills/agent-tooling/tell-chief-of-staff/scripts/setup.sh` yet
   (interactive, hidden prompts; needs the values from Grok's "Hermes inbound" routine panel).

2. **Chief of Staff -> Claude.** Grok calls the MCP tool `ask_claude(prompt, session_id?, model?, timeout?)`
   on `https://mac.greyhound-sidemirror.ts.net:8443/claude-mcp/mcp` (bearer token, Keychain
   `claude-mcp-bearer` / account `claude-mcp`). It runs a headless, READ-ONLY Claude turn
   (Read/Grep/Glob, cwd `~/ops`, plus `~/src`; no Bash/edit/network; secrets globs denied), about 2k
   tokens and $0.01-0.03 per call. It returns the answer plus a `session_id` for follow-ups.
   Server: `~/.local/libexec/claude-mcp-bridge/claude_mcp.py`; launchd `com.djbclark.claude-mcp-bridge`
   and `com.djbclark.claude-mcp-auth`; audit log `~/.claude/logs/claude-mcp-ask.log`.

## Rules

1. Include a self-contained request: Chief of Staff has none of this session's context. When you want
   an answer, say how to give it: it can answer by calling `ask_claude` (a fresh read-only Claude) or
   by telling the operator.
2. Send only what the operator asked you to share. No secrets, tokens, or private email/health/family
   content unless the operator says so.
3. Ask the operator before sending anything that commits them to an action or spends money.
4. The ask_claude side is deliberately narrow. Widening it (editing, running commands) is the
   operator's decision; change `TOOLS`/`DENY` in `claude_mcp.py` and restart the bridge only on their say-so.
