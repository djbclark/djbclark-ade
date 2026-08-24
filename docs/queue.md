# Queue — accepted, not started

Work the operator has explicitly queued. Newest first. Items leave this file
when they ship (into the relevant doc) or when they're dropped (say why).

## Quota-aware automatic cross-vendor subagent routing

**Queued 2026-08-23. Not started.** Hindsight initiative page
`kp-2e1513989ca5483ea8709dab2ce6a7f3`.

Automatically choose which vendor's agent runs a given piece of subagent work,
instead of the operator or the orchestrating session hand-picking it. Two
inputs:

1. **Ability/strength profile per service** — what each agent is actually good
   at, which is the judgment half of [model-routing.md](model-routing.md)'s
   "Which AI for which work" section, made machine-readable.
2. **Live quota headroom** — from `aiuse --json`, polled periodically. The
   operator explicitly left room for **faster methods** than polling: a cached
   snapshot with a TTL, a local daemon holding state, or a push/event signal
   if any service offers one. A full `aiuse --json` takes ~1 min, which is far
   too slow to sit in the path of a routing decision.

**Why it's worth doing** (measured 2026-08-23T23:30Z): antigravity, opencode-go,
zai, and devin were all at ~0% used while claude carried the session. That is
paid capacity expiring unused every cycle, and the only reason is that routing
is manual and the human defaults to what's familiar.

**Constraints it must respect** — the standing orders in
[AGENTS.md](../AGENTS.md): free and chronically-unused pools first for bulk;
claude/codex for judgment; **never** bulk-route to clinepass (it is the
Hindsight/hermes lifeline); prepaid tier retired until an operator top-up.

**Open design questions** (not yet decided):

- Where does the router live — a Claude Code workflow, an Orca dispatch layer,
  a standalone binary, or inside `aiuse` itself?
- Does it route *nodes within* a graph (per-subagent) or whole tasks?
- What happens on a wrong call — is there a fallback/retry ladder, and who
  notices the output was worse?
- How does ability-profiling stay honest as models change? (Snapshot dates,
  like everything else here.)
- Does it also decide **effort level**, not just vendor?

## Dynamic self-adjustment of model version and effort by token efficiency

**Queued 2026-08-23. Not started.** Sibling to the routing item above — that
one picks *which vendor* runs work; this one picks *how much thinking* the
current session spends on it.

The session should raise and lower its own model tier and effort level based
on observed **token-use efficiency** — dropping to a cheaper tier or lower
effort for mechanical stretches (file edits, doc writing, command running) and
climbing back for genuine judgment. Today this is manual (`/model`, per-agent
`model`/`effort` overrides) and therefore usually left wherever it was last
set — typically too high, which is exactly the waste this is meant to catch.

**Open questions:**

- What is the efficiency signal? Output tokens per useful action, revision/
  retry rate, tool-calls-per-turn, or something learned?
- Can a session change its *own* model mid-flight, or must this be expressed
  as dispatch to subagents at chosen tiers (which works today)?
- What prevents oscillation, and what prevents a cheap tier from silently
  degrading a task the operator cared about?
- Should it be advisory (tell the operator "this stretch is mechanical, drop
  to sonnet") before it is ever automatic? The operator's instinct on the
  Hermes side was stop-and-prompt first, automate later — same shape here.

## S1 Phase B — foundation landed, adapters next

**Started 2026-08-23.** `site-djbclark/bin/hindsight_s1.py` is in and tested;
the schema is live on `~/.hindsight/candidates.sqlite3` alongside Phase A
(14 candidate rows verified intact). What remains, in order:

1. **Claude tail/checkpoint adapter** — read `~/.claude/projects/*/*.jsonl`,
   one event per record, `source_locator` = byte range + record index,
   resuming from `ingest_checkpoint`. This is the piece that stops the
   ongoing evidence loss: Claude Code garbage-collects those transcripts,
   which already cost us attribution for 15 documents (recorded as the
   store's first `ingest_gap`).
2. **Live Hermes sink** — every committed message/tool event into S1
   idempotently, `state.db` staying source-compatible during migration.
3. **Backfill** — surviving transcripts, MEMORY/USER, candidate store,
   Hindsight export; record historical gaps rather than claiming coverage.
4. **Attachments/tool events**, then trigram/neighbor retrieval alongside the
   exact search that exists.
5. **Backup coverage check** — `snapshot` produces a consistent file via
   `VACUUM INTO`; confirm Arq picks up snapshots and CAS objects rather than
   a live WAL.

## Implement cow — DONE 2026-08-23 (first pass)

Installed (`cow 0.1.10`), configured, and in use.

- **Install:** `brew trust joeinnes/tap` first, then `brew install cow` — the
  plain `brew install cow` in the README fails, there is no homebrew-core
  formula. (Operator did the trust step.)
- **Shell integration:** `cow install` → `cowcd` function + completion in
  `~/.bashrc`.
- **MCP:** registered user-scope, `claude mcp add --scope user cow -- cow mcp`,
  verified ✔ Connected. Being stdio, it needs no daemon and survives reboots
  by construction — Claude Code spawns it per session from `~/.claude.json`,
  and the binary lives in `/opt/homebrew/bin`.
- **Retroactive migration:** `cow migrate --all` in `~/.hermes/hermes-agent`
  converted **8 worktrees** into pastures. `cow stats`: **3.7 GB on disk for
  29.2 GB of logical content.** Two worktrees with uncommitted work
  (`memory-capacity-guard-v2`, `upstream-merge`) were skipped by design —
  migrating them needs `--force` and an operator decision.

**Gotcha worth remembering:** the first migration run failed on every
candidate and rolled each one back cleanly. Cause was an uncommitted
`.gitignore` edit in the source repo (left by an earlier `graft build`),
which blocks branch checkout. Fix was to keep the tracked `.gitignore`
pristine and put graft's ignore rules in `.git/info/exclude` instead — the
right place for tool-local cache rules in a fork that tracks upstream.

Still to do: point Orca `worker-start` at cow, teach Hermes's
`headless-agent-orchestration` skill to use it.

**`~/src/ops-worktrees/` (13 dirs, 492MB) — surveyed, needs an operator
decision, do not bulk-delete.** These belong to the retired regime and sit on
their own bare store (`~/src/ops-worktrees/.store/*.git`), so `cow migrate`
from `~/ops/*` finds nothing — they would have to be migrated from the store.
Before anything is deleted or migrated, note that **10 workspaces still hold
live work**:

| workspace / repo | dirty | unmerged commits |
|---|---|---|
| `secretspec-drift-hardening/stayturgid` | 30 | 0 |
| `secretspec-drift-hardening/site-djbclark` | 24 | 0 |
| `secretspec-drift-hardening/site-private` | 7 | 0 |
| `stayturgid-2.0/stayturgid` | 1 | **4** |
| `archive-maynarddaycare-pages/site-private` | 1 | 1 |
| `cloudflare-operator-token-declaration/site-private` | 1 | 1 |
| `find-hub-integration-plan/site-private` | 1 | 1 |
| `coderabbit-feeder-workspace/Shizuku` | 0 | 1 |
| `coderabbit-feeder-workspace/RevengeQuickSwitcher` | 1 | 0 |
| `agent-communication-harness/ops-djbclark` | 2 | 0 |

`secretspec-drift-hardening` (61 uncommitted files across three repos) and
`stayturgid-2.0` (4 unmerged commits) are the ones with real work at risk.

### Original decision record

<https://github.com/joeinnes/cow> · `brew trust joeinnes/tap && brew install cow`.

### Baseline measured 2026-08-23 (step 1 partly done)

Benchmarked `cp -c -R` against `cp -R` on `~/ops/stayturgid` (677MB) on this
machine's APFS root volume. **CoW engages, and the win is space, not speed:**

| | wall clock | disk actually consumed |
|---|---|---|
| plain `cp -R` | 43.8s | 677 MB |
| CoW `cp -c -R` | 10.7s | **~10 MB** |

So ~4× faster but ~67× cheaper on disk. Note the gap with rift's marketing
claim of "<0.1s on a 10GB folder" — 10.7s for 677MB is nowhere near that, so
treat any tool's speed claim as unverified until measured here. Whatever we
adopt, the reason is space and dependency reuse.

**Two caveats found while measuring, both of which argue for a tool over the
raw baseline:**

- `cp -c -R` copies **everything**, including `.env`. An agent workspace made
  this way inherits real secrets. This is exactly what cow's/rift's
  "excludes artifacts and dependencies by default" is for — but confirm cow
  excludes *secrets*, not just `node_modules`.
- The copied `.env` carried the `uchg` (user-immutable) flag, so the test
  clone refused to delete until `chflags -R nouchg`. Any cleanup/GC path
  needs to handle immutable flags or it will strand workspaces.

Remaining for step 1:

1. **Install cow — the documented path does not work.** `brew install cow`
   fails (no such formula in homebrew-core; brew suggests `crow`/`cot`/`cog`).
   Find the real install route — a custom tap, `cargo install cow-cli`, or a
   GitHub release — and confirm the MCP server actually ships with it before
   committing to the tool.
2. Wire the agents, which is the point: `cow` ships an **MCP server** and
   Claude integration via environment variables, so start there rather than
   writing an adapter. Register it the way `hermes` was registered
   (`claude mcp add --scope user`), then teach Hermes about it — its
   `headless-agent-orchestration` skill currently creates worker workspaces
   the old way.
3. Point Orca macro-graph dispatch at it (`worker-start --worktree` is the
   highest-volume workspace creator here, so it is both the best payoff and
   the safest place for a first failure).
4. Decide what happens to `~/src/ops-worktrees/` — now that the
   worktree/PR/release regime is retired, that layout has much less reason to
   exist, and cow workspaces may replace it outright.
5. Keep the plain-git baseline (`git worktree add --no-checkout` +
   `cp -c -R`) documented as the fallback, so nothing hard-depends on a tool
   we can drop.

### Rationale — the options that were considered

Every parallel-agent workflow here creates workspaces — Orca macro-graph
dispatch (`worker-start --worktree`), Hermes's `headless-agent-orchestration`
(one isolated workspace per worker), Claude Code's own worktree isolation.
`git worktree` pays a full checkout each time and gives you none of the
untracked state (`node_modules`, build output), so every new workspace needs a
reinstall before an agent can do anything. Filesystem copy-on-write fixes both
at once. Candidates, with what actually distinguishes them:

| Option | Shape | Notes |
|---|---|---|
| **Plain git + CoW copy** | no new dependency | `git worktree add --no-checkout ../ws` then `cp -c -R . ../ws` (macOS APFS) or `cp --reflink=always -R . ../ws` (btrfs/XFS). **This is the control** — any tool has to beat it to earn its install. |
| [cow](https://github.com/joeinnes/cow) | `brew install cow` / `cargo install cow-cli` | **Explicitly built for running multiple coding agents in parallel.** APFS `clonefile`, reflinks on btrfs/XFS, falls back elsewhere. Ships an **MCP server** and Claude integration via env vars, plus create/list/remove/sync/extract and run-inside-workspace commands. The only candidate where the agent wiring already exists. |
| [rift](https://github.com/anomalyco/rift) | `npm i -g rift-snapshot` | Same CoW idea; claims <0.1s on a 10GB folder, excludes build artifacts by default, `.rift.toml` pre/post-create hooks, JS/Bun FFI. **Experimental, no agent integration** — that wiring would be ours. |
| [jj (Jujutsu)](https://github.com/jj-vcs/jj) | different VCS, Git-compatible | Not a CoW-workspace tool — a broader bet: no staging area, first-class conflicts, operation log with undo, working-copy-as-commit, and good multi-workspace ergonomics. Git-backed so existing tooling keeps working. Still pre-1.0 with breaking changes possible. Solves more than the workspace problem, and costs more to adopt. |

Background reading: [Git without the clone — durable versioned workspaces for
AI agents](https://pub.towardsai.net/git-without-the-clone-durable-versioned-workspaces-for-ai-agents-b280241fe5ca).

**Why cow won:** its MCP server means Hermes and Claude can drive it without
us writing an adapter, and it is the only candidate built explicitly for
running coding agents in parallel. Caveat carried into implementation: that
is a README claim, not yet a measurement — step 1 above exists to check it.

**`jj` remains open and separate.** It is a different and larger bet (a whole
VCS), it solves more than the workspace problem, and choosing cow does not
foreclose it. Worth its own evaluation another time.

## Also outstanding (raised, not formally queued)

- **⚠ Rotate three API keys — OpenRouter, DeepSeek, ClinePass.** Operator
  deferred this ~2 days on 2026-08-23. The bank purge is **done**, but
  rotation is what actually closes the incident: the full keys live in
  on-disk session transcripts under `~/.claude/projects/`, which the purge
  does not touch. The auto-refreshing mental model that was re-spreading the
  token has been cleared, so it is no longer getting worse.
- **Purge the Postgres LLM-request log** — 11 `refresh_mental_model` rows
  hold the token. No API endpoint exists; direct SQL against the `hindsight`
  database. Left for the same window as rotation.
- **Restart the `hindsight` MCP server** in any long-running session started
  before 2026-08-23 20:00 — it caches the bank it launched with and will keep
  writing to `hermes-shared`. New sessions are fine.
- **Confirm-then-delete two leftover banks**: `hermes-telegram` (5 docs) and
  `herdr-shared` (1 doc). Left in place because a running gateway may still
  write to them.
- **`just ops-memory-sync` is failing for site-djbclark** —
  `docs/plans/memory-architecture-v2.md` is unreleased past ops-v1.3.26.
  Needs a release cut or a revert.
- **File the two upstream issue drafts** in
  [upstream-issues.md](upstream-issues.md) — operator decision, they go to
  third-party trackers.
