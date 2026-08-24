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

### The reverse direction: Hermes → Claude already exists (don't add MCP for it)

Hermes reaching Claude needs no new wiring — it already carries a full
delegation stack (verified live 2026-08-23):

- `delegate_task` + the `intelligent-delegation` Hermes skill route
  token-heavy research/reasoning to Claude Code with leaf-role recursion
  prevention and ≤8k-token context injection.
- The `headless-agent-orchestration` Hermes skill defines a complete Claude
  worker protocol on `claude-sub` (`~/.local/bin/claude-sub` — refuses
  API-key billing, verifies claude.ai OAuth; `--check` passes) and
  `agent-coord run` (workspace claims, stdin prompts, stream-json
  supervision, `--resume` on max-turns). Smoke-tested end-to-end:
  `claude-sub "<prompt>" -p --model haiku` → correct reply, ~39s
  (mostly CLI startup).

So the two agents are bidirectional: **Hermes → Claude** via headless
delegation, **Claude → Hermes** via the MCP bridge above (including
`permissions_respond` — Claude can answer Hermes's approval queue — and
`events_wait` for long-poll coordination).

### Keeping Hermes current — fixed 2026-08-23, was silently broken

Hermes's external memory provider is Hindsight (`provider: hindsight` in
`~/.hermes/config.yaml`), and it is now genuinely automatic: retain a fact to
`hermes-shared` and Hermes finds it. That was **not** true earlier the same
day, and the failure was invisible.

**The bug.** The provider's own config lives at
`~/.hermes/hindsight/config.json` — separate from `config.yaml` — and read:

```json
"bank_id": "hermes",
"bank_id_template": "hermes-{profile}-{workspace}"
```

The template wins, so Hermes was reading a per-workspace bank
(`hermes-default-hermes`), never `hermes-shared`. Facts retained to the
shared bank were committed and recallable through the API, yet Hermes
answered "not in memory" — and when asked about `cow`, confidently described
**`cowsay`** instead. That is the failure mode to watch for: not an error,
just a confident wrong answer sourced from general knowledge.

**The fix**: point both keys at the shared bank (backup at
`config.json.bak-2026-08-23`):

```json
"bank_id": "hermes-shared",
"bank_id_template": "hermes-shared"
```

`auto_recall` was already `true`, so no restart or further wiring was needed.
Verified: Hermes's own recall now returns the CoW benchmark, the cow install
gotcha, the migration numbers, and the full S1 backfill figures.

**Consequence to know about:** during the bank restructure earlier that day,
`hermes-default-hermes` was deleted as an apparently-dead stray bank. It was
in fact Hermes's live bank under the old template — 1 document, 5 facts,
which is small only because `auto_retain` is `false`. Deleting it was a
mistake; the lesson is that a bank matching an agent's `bank_id_template` is
never "stray", and provider config must be read before any bank cleanup.

**Practice:** retain cross-project facts to `hermes-shared` and Hermes gets
them. For things Hermes must know even if recall misses — policy, standing
rules — also append a `§` block to `~/.hermes/memories/MEMORY.md`, which is
injected directly rather than retrieved. Per-repo banks
(`coding-agent::<repo>`) remain invisible to Hermes by design.

Hermes was **taught all of this** on 2026-08-23, in three layers: a new
local Hermes skill `autonomous-ai-agents/claude-collaboration` (vendored
copy: [vendor/hermes/claude-collaboration.SKILL.md](../vendor/hermes/claude-collaboration.SKILL.md))
that tells Hermes to proactively *offer* Claude delegation when it detects a
task is hard for it (deep reasoning, subtle debugging, judgment — once per
task, quota-aware, without overriding its no-bulk-farming rule); a `§` block
in its built-in `~/.hermes/memories/MEMORY.md`; and a retained memory in the
shared Hindsight bank (`hermes-shared`), which is Hermes's active external
memory provider — that shared bank is the durable Claude↔Hermes fact channel. Deliberately NOT done:
registering `claude mcp serve` inside Hermes — it would only duplicate
tools Hermes already has (file/bash), a live probe showed it idling in
nested contexts, and Hermes's own skills forbid recursive coordinator
loops.

### Messaging: use Hermes (operator decision, 2026-08-23)

**Default to `hermes` for all messaging.** Beeper Desktop is often not
running, and the operator uses it only occasionally — so it is not a
dependable path for an agent. Reach for it only when the operator explicitly
asks, or when you need cross-network *search* that Hermes cannot do and you
have confirmed Beeper is up (`claude mcp list` shows it Connected, not
"Needs authentication").

Hermes covers the agent-facing cases: `messages_send` / `channels_list` to
send, `conversations_list` / `messages_read` to read, `events_wait` to react
to inbound traffic, and `permissions_list_open` / `permissions_respond` to
clear its approval queue — none of which Beeper can do.

Email is separate from both: local FTS5 index for search (below), claude.ai
Gmail connector to act.

### Not on the MCP bridge: the local Gmail index

Hermes also built a high-speed local Gmail search (FTS5 SQLite index of the
complete mailbox at `~/.hermes/gmail_index_v2.db`, ~100ms queries, kept fresh
by a Hermes cron job every 5m). It is **not** exposed through `hermes mcp
serve` — access is the plain CLI, documented in the
[gmail-search skill](../skills/gmail-search/SKILL.md) (deployed at
`~/.claude/skills/gmail-search/`).

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


## Hindsight is automatic in Hermes (2026-08-24)

`~/.hermes/hindsight/config.json` now sets **`auto_recall: true` and
`auto_retain: true`** against bank `hermes-shared`, retaining every 10 turns
asynchronously. Hermes reads and writes shared memory with no manual step.

**The manual review-before-promote pipeline is retired.** It was a
propose/promote candidate ledger gated on operator review, and the ledger is
the evidence it failed: nothing captured after **2026-08-11**, with two
candidates sitting `pending` for 13 days (both rescued into `hermes-shared`
before removal). A review gate whose reviewer does not review is a queue that
never drains — the same objection that ruled out Link.

Removed: the `Hindsight retention 30-day promotion gate` and
`Hindsight pilot inactivity nudge` cron jobs, the `hindsight-retention-pilot`
Hermes plugin, and its skill. `~/.hindsight/bin/hindsight_memory_z.py` (the
`/z` propose/promote CLI) is now redundant and left in place, unused. The
`candidates` table stays in `candidates.sqlite3` — it is Phase A history, and
that database is also S1's home, so it must not be dropped.

**One hazard found while removing this.** The
`Hindsight shared-bank policy watchdog` did not merely alert on mission
drift — it **overwrote** the bank mission with a hardcoded string via
`hindsight bank update`. It ran after the mission was deliberately rewritten
earlier the same day and silently reverted it; the change was only noticed
because a later read showed the old text. Job and script retired, mission
restored. The general lesson: a watchdog that auto-corrects instead of
reporting will fight intentional change and lose work quietly.
