# MCP servers on this machine (Claude Code)

Snapshot **2026-08-23**. Probes beat memory: re-check with `claude mcp list`
(spawns each server and health-checks it, ~10s). Config lives in two places:
user-level servers in `~/.claude.json` (`mcpServers`), per-repo servers in the
repo's `.mcp.json`.

## Roster

| Server | Transport / command | Scope | What it is |
|---|---|---|---|
| `hermes` | stdio: `hermes mcp serve` | user | The **Hermes Agent** as an MCP server — see below |
| `beeper` | HTTP: `http://127.0.0.1:23373/v0/mcp` | user | Beeper Desktop's local API — cross-network chat search/read/send. OAuth-gated; see below |
| `graft` | stdio: `graft mcp` | this repo (`.mcp.json`) | Repo context graph (`graft_find_code`, `graft_trace_calls`, …) |
| `ghost-os` | stdio: `/opt/homebrew/bin/ghost mcp` | user | macOS UI automation via accessibility tree + vision |
| `hindsight` | stdio: `node ~/.hindsight/coding-agents/dist/mcp-server.js` | user | Per-repo Hindsight coding-agent memory (the 🧠 banner) |
| `hindsight-shared` | HTTP: `http://127.0.0.1:8888/mcp/hermes-shared/` | user | Shared Hindsight bank (`hermes-shared` in the URL is the bank name) |
| claude.ai Gmail / Google Calendar / Google Drive | HTTPS (Google-hosted) | claude.ai account | Remote connectors managed on claude.ai, not in local config |

## Hermes (added 2026-08-23)

`hermes` (`~/.local/bin/hermes`) is the **Hermes Agent** — Nous Research's
agent CLI, git-installed at `~/.hermes/hermes-agent` (v0.20.5 at snapshot
time; `hermes --version`). It is also one of the Orca fleet TUIs
([model-routing.md](model-routing.md)), and clinepass is its inference
lifeline — the MCP surface below is separate from routing *to* hermes as a
worker.

Registered so every Claude Code session on the machine gets it:

```bash
claude mcp add --scope user hermes -- hermes mcp serve
```

"Always running" needs no daemon or launchd: stdio MCP servers are spawned by
Claude Code per session and die with it. Two gotchas verified live:

- Startup takes ~10s before `tools/list` answers (well inside Claude Code's
  timeout, but a too-short manual probe sees zero tools).
- `hermes mcp serve` takes no port/transport flags — stdio only.

Its 10 tools bridge Hermes's messaging gateway and approval queue:
`conversations_list/get`, `messages_read`, `messages_send`,
`attachments_fetch`, `events_poll`, `events_wait`, `channels_list`,
`permissions_list_open`, `permissions_respond` — i.e. Claude can read/send
through Hermes's connected platforms and answer Hermes's pending
exec/plugin approval prompts.

## Beeper (re-authed 2026-08-23)

Beeper Desktop serves MCP locally on port 23373. Until authorized, the server
exposes only an `authenticate` tool and `claude mcp list` shows
"! Needs authentication". The fix, run from any session:

1. Call the `authenticate` MCP tool → it returns a local OAuth URL
   (`127.0.0.1:23373/oauth/authorize?...`, redirect to
   `localhost:3118/callback`).
2. `open "<url>"` — approve in the browser/Beeper Desktop. The callback is
   local, so it completes itself; `complete_authentication` (paste-the-URL
   fallback) is only for remote sessions where the callback can't land.
3. The real tools (`search`, `search_chats`, `search_messages`,
   `list_messages`, `send_message`, `get_accounts`, reminders, archive,
   `focus_app`, `search_docs`) appear **mid-session** — no restart needed.

Verified via `get_accounts`: 11 networks bridged (Beeper/Matrix, Discord,
Facebook, Google Messages, Google Chat, Instagram, LinkedIn, Signal, Slack,
Telegram, WhatsApp).

## Graft statusline: "graft · not built" in this repo is cosmetic

The statusline segment (this repo's `.claude/settings.json` →
`.claude/helpers/graft-statusline.cjs` → `@nanonets/graft` `dist/claude/`)
renders "◤ graft · not built · run `graft build`" whenever the stats cache
reports 0 nodes. This repo is docs/markdown-only, so `graft build` parses 0
code files and legitimately produces a 0-node wiring graph — the statusline
can't distinguish "built but empty" from "never built". Nothing to automate:
in repos with a real graph, the `PostToolUse` hook already auto-syncs after
every edit (detached `sync-run.js`, the "syncing…" state). The real fix is
upstream (render empty ≠ missing); until then, ignore the segment here.
`graft ask`/`graft grep` still work — they answer from `graft/INDEX.md` and
the extract cache, not the wiring node count.
