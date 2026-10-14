# Queue — accepted, not started

Work the operator has explicitly queued. Newest first. Items leave this file
when they ship (into the relevant doc) or when they're dropped (say why).

## self-slash cannot drive omp (found 2026-10-13, needs an operator decision)

`bin/self-slash "/quit"` from an omp session in herdr pane w34:p2 queued, waited, and gave
up: `~/.local/state/self-slash.log` 14:23:03-14:24:03 "no input prompt on screen yet" x9,
then "gave up, no empty input prompt seen". Cause: it looks for Claude's `❯` (or
cursor's `→`) input marker, and omp draws a boxed composer (`composer.shape: box` in
`~/.omp/agent/config.yml`). herdr does identify the pane (`herdr pane get` →
`.result.pane.agent` = `"omp"`; an earlier "agent: null" read the wrong JSON path), so
self-slash can branch on it the way it does for cursor. So `/quit` and `/compact` via
self-slash, and `/loose` Rule 4's quit, do not work in omp yet. **Decide:** teach
self-slash omp's composer (screen scraping, breaks if the composer shape changes), or
add a command channel to the omp bridge extension (`skills/autorename/omp-bridge.ts`),
if omp's extension API can run a slash command or end a session.

## Ralph on OpenCode v2: postponed (operator, 2026-10-13)

**Postponed by the operator ("postpone all ralph work"); do nothing until raised.**
State when parked: the opencode-ralph-tui wrappers (`vendor/gate-scripts/`, live copies in
`~/.local/bin/`) were pointed at v2 in `bea2e9d`, then switched back to v1
(`~/.opencode/bin/opencode`, 1.18.32) in `d3de341` at the operator's request, so Ralph runs
v1 while parked even though plain `opencode` is v2. Findings, from the v2 trial, none acted on:
1. `bun ~/src/vendor/ralph-tui/dist/cli.js doctor --agent opencode-go` detects v2 2.0.27 but
   fails the preflight with exit 130. Running the same args by hand (`opencode-ralph-tui run
   --format json "<prompt>"`) gives v2 JSON events and then `provider.quota` 402 "Insufficient
   account funds": the agent sets `provider = "opencode-go"` but no `model`, so no `--model`
   is passed and v2 falls back to its default model. Untested: an explicit opencode-go model.
2. ralph-tui's opencode plugin (`src/plugins/agents/builtin/opencode.ts` ~414-455) passes
   `--variant`, which v2's `run` lacks (v2 takes `--model provider/model#variant`), and its
   JSON parser was written for v1 events; neither is checked against v2.
3. `ralph` on PATH (`/opt/homebrew/bin/ralph`, 2.10.1) is Homebrew's ralph-orchestrator
   (mikeyobrien), a different project from ralph-tui, which still runs from the fork via
   `bun ~/src/vendor/ralph-tui/dist/cli.js`. Decide which one "Ralph" means before resuming.

## Resurface 2026-10-14 (operator, 2026-10-13): first real SkillOpt-Sleep night, backends, -C repos

**Queued 2026-10-13 by the operator: "resurface tomorrow".** Any session that opens
this repo on or after 2026-10-14 raises these three first, one `/steps` prompt each:
1. **Read the first night on the new chain** (03:30 on 2026-10-14): `nights.jsonl` and
   `attempts.jsonl` in `~/.local/state/skillopt-sleep/`, `skillopt-sleep status`. Did the
   per-prompt retries, the stripped opencode/agy startup, the direct SIPB entries and the
   lowered floors (0 for opencode-go/agy/zcode, 5 for claude) get sources through? Did crush
   and the new Hermes/grok/muse/cline/acp-dispatch adapters run? Measure prompts and tokens
   per source. Token capture landed 2026-10-13: attempts.jsonl attempt rows and
   nights.jsonl rows carry `tokens` (backend-reported counts, never estimates; see
   docs/failover.md). opencode, claude and direct sipb report counts; agy and crush are
   unmetered (`tokens: null`, only the prompt count); zcode and hermes are unmetered
   until a log shows `result.usage`. Still to do: read the first night's rows.
2. **Denied backends** (`hermes`, `cursor`, `cline`, `clinepass`, `opus`, `fable` in
   `failover.DENY`; `muse`, `pi`, `grok`, `codex`, `copilot` in night.json/skillopt-night):
   the operator kept them denied on 2026-10-13 ("revisit after tonight"). With the night's real
   counts, decide whether Hermes or codex joins as a late chain entry. `aiuse --available`
   shows only opencode-go, claude (default and Fable) and antigravity/gemini; codex, cursor,
   copilot, grok, pi and muse have no window.
3. **The `-C` strip gap** in the next entry: the operator chose to note it and do no work on
   2026-10-13; raise it again.

## Crush under `--perm deny`: adversary findings 1-4 (queued 2026-10-13, not fixed)

**Queued after the review of 71ac081 (scratchpad adv3-report.md). Since the same day
the SkillOpt night runs its chain with `perm: all` (operator decision), so none of
these affects the night; they matter for `--perm deny` runs of crush (acp-dispatch
read-only reviews).** (1) An untrusted `-C` repo's project `crushrc` runs as shell at crush
startup and its files can leak; acp-run only warns (acp-run ~828-835). (2) MCP tools are not
covered by `disabled_tools`, so the logged `"tools": "none"` can be false (~825). (3) The
shadow-bypass scanner for the user's crushrc is a denylist and misses real bypasses (~746-749,
859). (4) The 29-name tool snapshot fails open after a crush upgrade (~726-737). Notes 5-8 (git
boundary, literal keys copied from a user crush.json, `/toggle_yolo` as a prompt, crush deny
sessions' DB deleted with the temp dir) are in the report. **Decide:** harden deny-mode crush
or leave crush out of deny-mode reviews.

## acp-run --perm deny: what the user-config strip still lets through

**Queued 2026-10-13 (adversary review of the deny strip, finding 5). Needs an
operator decision.** Since 2026-10-13 a non-interactive `--perm deny` run starts
opencode and agy without the user's global plugins, MCP servers and hooks
(tools/acp-run/README.md). Still loaded: agy's workspace `.agents/` plugins
(skills, hooks, MCP) in the `-C` dir, and opencode's skills from
`~/.claude/skills` and `~/.agents/skills` (opencode 2.0.27 has no switch for
them). Plugin hooks run code without any tool permission request, so deny and
the exit-77 tripwire cannot see them. Not a regression (the old behaviour
loaded everything), and failover runs in an empty temp dir. **Decide:** should
`--perm deny` against an untrusted `-C` repo (an acp-dispatch read-only review
of someone else's code) refuse, copy the repo without `.agents/`, or shadow
agy's workspace roots, and is opencode's skill loading acceptable?

## acp-run: classify quota and outage failures at the source

**Queued 2026-10-12 (operator, from the acp-dispatch pool-guard work, 4bbf180).
Not started; a cleanup, not urgent.** `acp-run` files zcode's
`1310 [Weekly/Monthly Limit Exhausted. Your limit will reset at <time>]` as a
plain failure and opencode-go's `ServiceUnavailableError` as `fail=transient`,
so `acp-dispatch`'s `failure_class()` re-parses stderr to find quota and outage.
Move that into acp-run: emit `fail=quota` with the reset time for 1310 (and
the other limit phrasings in `failure_class`'s `quota_terms`), and a stable
`fail=outage` for service-unavailable / 5xx / connection failures. Then shrink
`failure_class` to trust acp-run's class. Check first that no live run owns
`tools/acp-run/acp-run` (it was owned by the sipb-bench run on 2026-10-12).

## SkillOpt-Sleep phase 2: pluggable transcript sources and backends

**Queued 2026-10-12 (operator asked for SkillOpt across all agent runs).
Partly done the same day:** zcode, agy and crush adapters ship in
`bin/skillopt_sources.py` (docs/skillopt-sleep.md section 7). Remaining: (1) the
upstream PR offered in microsoft/SkillOpt#314 (entry points for sources and
backends, unknown backend raises, public helpers; per-source checkpoint is
#312), once upstream answers; (2) adapters for Hermes, grok, muse,
cline and acp-dispatch job reports, each with the replay-session filter; (3)
add them to `bin/skillopt-night`'s source loop. Drop the runner's codex shim
when upstream PR 282 merges.

## Research checker: namespace-aware citations across runs

**Queued 2026-10-10 (operator, hiwymi `/loose`). Not started.** Research runs
in one project reuse evidence ids (`E0949` is one row in
`hiwymi/research/ai-heaven/evidence.jsonl` and a different row in
`research/soul-md-autonomy/`). `skills/research/scripts/research_check.py
claims` only checks that a cited id exists in the run's own ledger, so a
finding from another run cited as a bare id passes while pointing at the wrong
source. GPT-6 Astra proposed the fix in the ai-heaven spec dialogue (turn 20,
amendment A8); Grok 4.7 accepted it as rule R-src-5 but did not claim a checker
run (`spec/ai-heaven/notes/grok-phase4-verdicts.md`, Phase 5 rulings, A-8).
Build: a `research_check.py` subcommand (or a spec-side checker) that (1)
resolves every relative link into another run's report by file **and**
fragment, (2) lists every superscript id that also exists in a sibling run's
ledger and shows the cited row's title beside the sentence for review, and (3)
flags any sentence that names another run's report and carries a local
superscript. Lead's hand check of the phase-5 spec (a28fa05, 2026-10-10): no
links into other runs; 5 of 48 cited ids also exist in the soul-md ledger and
all 5 resolve to the intended ai-heaven rows; nothing to fix. Drop this item
when the subcommand ships and the research skill's SKILL.md names it.

## Watch Orca upstream for structural-reorg verbs

**Queued 2026-09-26. Watcher built; waiting on upstream.** We filed
[stablyai/orca#23272](https://github.com/stablyai/orca/issues/23272) (CLI
parity with herdr for move/swap/resize/reorder) and commented on #9632, #12306
and #8766. Run `bin/orca-reorg-watch` periodically (exit 10 = something moved:
an issue/PR changed state or comment count, or the installed `orca` gained a
verb). When it fires: read the change, re-probe `orca terminal --help`, update
`skills/reorg-orca/SKILL.md` §3/§4 (move gaps from "cannot" to "can"), and
refresh the gap list in [upstream-issues.md](upstream-issues.md) §3. Gate to
watch first: PR #15108 (`orca terminal move`). Drop this item when the verbs
in the skill's §4 table have shipped or upstream declines them.

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

**Status 2026-09-20 — proactive use built, Orca half-verified.** The
"automatic cow for all repos" the operator remembered did not exist: nothing
in hooks, settings, cron, LaunchAgents or the ops repos invoked cow. Now:

- `bin/cow-pasture` (this repo) + `skills/cow-workspaces` (live copy in
  `~/.claude/skills/`) are the mechanism: `cow-pasture create <name> --source
  <repo> [--orca]`. Nothing runs unprompted; turning it off = delete the skill.
- **Secrets, verified:** `cow create` copies gitignored `.env` (and its `uchg`
  flag) into the pasture — tested on a throwaway repo and on `~/src/aiuse`.
  The wrapper scrubs gitignored secret-like files by default.
- **Scope decided:** primary checkouts under `~/src`, `~/orca/projects`,
  `~/.hermes`; never `~/ops/*` (wrapper refuses). Linked worktrees
  (`core-*`, `libntech-*`, `ss-*`, `ralph-tui-*-plugin`) are ineligible.
- **Orca:** `orca repo add --path` makes `worker-start --worktree path:` resolve
  (verified: worktree reused, terminal created). The dispatch then stalled at
  `agent_readiness` because **Claude Code's folder-trust dialog fires in any
  new directory** and Orca has no Claude trust preset (it has Codex/Cursor/
  Copilot ones). Operator decision pending on the mechanism; end-to-end
  `worker_done` not yet observed. See `docs/orca-integration.md`.
- "Compact into cow" = reclaim disk by migrating (operator, 2026-09-20);
  the dirty Hermes worktrees stay un-migrated until their changes are
  committed or discarded (no `--force`).

Still to do: finish the Orca end-to-end test once the trust mechanism is
chosen; teach Hermes's `headless-agent-orchestration` skill to call
`cow-pasture` instead of bare `cow create`; `cow gc --merged` pass on the
Hermes pastures with the operator's go.

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

**Migration attempted 2026-08-23 and BLOCKED — cow cannot do it.** These are
worktrees of bare stores under `~/src/ops-worktrees/.store/*.git`, and cow
refuses both ends: from a worktree it errors *"is a git worktree, not a
primary repository"*, and from the bare store *"No VCS found at source"*
(also via `cow create --source`). There is no primary working checkout in
that layout for cow to clone, so `cow migrate` is not a path here. Nothing
was moved or deleted.

**Safety net in place** (`~/ops-worktrees-preserved-2026-08-23/`, 1.3MB,
durable — not in `/tmp`): per workspace, the branch name, `git diff HEAD` as
a patch, `status.txt`, the unmerged-commit list, and a `format-patch` series.
**9 of 10 uncommitted patches verified applicable** via
`git apply --check --reverse`; the tenth had no diff, only an unmerged commit
(exported). A full CoW copy also exists in the session scratchpad, but that
lives under `/private/tmp` and should not be relied on.

**Recommended endgame** (operator decision — do not bulk-delete unasked):
the worktree regime is retired, so the goal is not to move these into cow but
to *land or archive* the outstanding work and reclaim 492MB. Per workspace:
apply the patch onto the matching repo in `~/ops`, commit and push, then drop
the workspace. `secretspec-drift-hardening` is the one that needs real review
rather than a mechanical replay.

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

## Completed 2026-08-23 (kept briefly for reference)

- **`~/src/ops-worktrees/` retired and deleted** (491MB reclaimed). Before
  deleting, every branch was verified present on a remote and all
  uncommitted + untracked work preserved *in git*, not as loose patches:
  `feature/agent-communication-harness` (a 14.6KB untracked
  `agent_communicate.py` that `git diff HEAD` had missed entirely),
  `feature/secretspec-drift-hardening` across all three repos (18 untracked
  files — the sudo-secretspec broker, installer, drift-check, audit lib and 8
  test files, **none of which existed in master**), and three unpushed
  branches now on origin. The *tracked* edits in secretspec-drift-hardening
  were confirmed superseded — they modify files the merged PRs deleted — and
  were discarded deliberately. Backups deleted afterwards.
- **Upstream issues filed**: [NanoNets/Graft#185](https://github.com/NanoNets/Graft/issues/185)
  (statusline says "not built" for a built-but-empty graph) and
  [vectorize-io/hindsight#3735](https://github.com/vectorize-io/hindsight/issues/3735)
  (config keys read but undocumented).
- **Stray banks removed**: `hermes-telegram` and `herdr-shared`, both last
  written 2026-08-11 and holding only retention-pilot `candidate-*` docs, with
  no live config referencing them. Exported to `~/hindsight-backups/` first —
  the discipline the earlier `hermes-default-hermes` mistake earned. Bank
  topology is now exactly 11 per-repo banks plus `hermes-shared`.
- **cow rolled into the agent stack**: Hermes's `headless-agent-orchestration`
  skill now says to use `cow create --print-path` for worker workspaces,
  with the two rules that bit us (source tree must be clean; a pasture carries
  `.env`). The Orca composition (`--worktree path:$(cow create … --print-path)`)
  is documented in [orca-integration.md](orca-integration.md) but **not yet
  exercised in a live dispatch**.
- **S1 Hermes event sink** built and backfilled (`bin/hindsight_s1_hermes.py`,
  13 tests).

## Ingest web-interface AI conversations into the memory system

**Queued 2026-08-23. Not started.**

Conversations held through AI *web* interfaces — especially Gemini and Grok —
are currently invisible to the memory system. S1 ingests Claude Code
transcripts and Hermes's `state.db`; anything typed into a browser is lost to
it. That is a real hole: web sessions are where a lot of exploratory thinking
happens, and they are exactly the "disjoint conversations with no repo" shape.

Scope both directions:

- **Backfill** what already exists in those accounts.
- **Ongoing capture** so future web conversations flow in without ceremony.

### VESTI assessed 2026-08-23 — right tool for most of it, one real gap

[abraxas914/vesti](https://github.com/abraxas914/vesti) (心迹, TypeScript,
public, local checkout at `~/src/vesti`, also an Orca project) describes
itself as a *"local-first AI conversation memory hub to capture, search,
summarize, and export chats across major AI platforms"* — which is exactly
this problem, already built.

**What it covers.** A Chrome extension silently captures conversations on
**ChatGPT, Claude, Gemini, DeepSeek, Qwen and Doubao**, extracting full
multi-turn content with timestamps and platform metadata, deduplicating, and
persisting to local IndexedDB. No manual export step, no tagging.

**The gap: Grok is not supported.** The platform list above is exhaustive, so
half of what was asked for needs a new capture adapter. That is the honest
cost of choosing VESTI — everything else it gives us free.

**How the integration would work.** The extension exposes a clean
`StorageApi` contract (`packages/vesti-ui/src/types.ts:412`) —
`getConversations`, `getMessages`, `getTopics` — and supports
`ExportFormat = "json" | "txt" | "md"`. So the data is reachable; the only
question is transport out of IndexedDB, which a browser extension cannot
write to arbitrary paths from. Options, cheapest first:

1. **Manual JSON export → S1 adapter.** Fine for the *backfill* half. A
   `vesti` producer adapter is the same shape as the Claude and Hermes ones
   (~150 lines): one S1 event per message, `source_locator` = conversation +
   message id, resuming by id.
2. **A localhost receiver.** Implement an alternate `StorageApi` backend, or
   a small mirror hook, that POSTs each captured conversation to a tiny local
   endpoint which appends to a file S1 tails. This is the clean answer for
   *ongoing* capture and keeps the extension's local-first property.
3. **Read the extension's IndexedDB from the Chrome profile directly.**
   Works without touching VESTI, but couples us to LevelDB internals and
   breaks whenever the schema moves. Fallback only.

**Recommendation:** option 1 to backfill, option 2 for ongoing, and treat
Grok as separate work — likely its own capture adapter in VESTI (upstreamable)
rather than a bespoke scraper here.

Still worth comparing for the backfill: each vendor's official export (Google
Takeout for Gemini, X/Grok export) is bulk one-shot — useless for ongoing
capture, but it needs no extension and no browser session.

Where it lands: **S1** is the right home for the raw conversations (it already
holds 448k events and is producer-agnostic — a `gemini` / `grok` adapter is
the same shape as the Claude and Hermes ones). Curated takeaways belong
wherever curated memory ends up, not in the transcript store.

Watch for: exports are bulk one-shot (fine for backfill, useless for ongoing),
and anything scraping a logged-in session needs care with credentials and
terms of service.

## Token-cost hygiene (from video analysis, 2026-08-24)

Analysed <https://youtu.be/V0XbuApxlhg> ("You're Paying Anthropic 20x MORE
Than You Need To") against
[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs).
Transcript pulled with `yt-dlp --write-auto-subs` — a YouTube page fetch
returns only the title.

**Its central claim holds and the docs confirm it:** the full conversation is
re-sent on every request, prompt caching re-reads that history at the cached
rate, and the cache lifetime is **one hour on a subscription** (five minutes
on usage credits or API keys). A one-line question in an all-day session
still draws usage for the whole conversation.

**One claim is unverified.** The video lists actions that supposedly reset the
cache outright — switching model, changing effort, fast mode, connecting an
MCP server, plugins, denying a tool, upgrading Claude Code. **None of that
appears in the docs**, which describe cache misses purely in time terms. Do
not repeat it as fact; it matters because it would make mid-session
`/model` switching costly, which is advice we give.

Actionable here, in order of expected value:

1. **Run `/usage` and `/context`.** `/usage` attributes recent usage to
   individual skills, subagents, plugins and MCP servers. That measures our
   31 skills and 7 MCP servers instead of guessing at them, and flags
   behaviours (long context, cache misses) accounting for >10% of usage.
2. **Run `/insights`.** Not previously known here: it analyses recent
   sessions and writes `~/.claude/usage-data/report.html` covering friction
   points — misunderstood requests, buggy code — rather than token counts.
3. **Keep instruction files lean.** Docs say aim for **under 200 lines** and
   move specialised instructions into skills, which load on demand.
   `djbclark-ade/AGENTS.md` is **180 lines** and grew substantially on
   2026-08-23; `site-private/home-agents.md` is 135. Both load in an ops
   session. Trim before adding more.
4. **Consider `ENABLE_PROMPT_CACHING_1H=1`** — preserves the one-hour cache
   lifetime while drawing on usage credits. Currently unset.
5. **Prefer `/clear` over `/compact`** between unrelated tasks: clearing
   costs nothing, while compaction reads the conversation it summarises and
   is itself a large request.

**Good news the video implies otherwise about:** MCP tool definitions are
*deferred by default* — only names and server instructions enter context
until a tool is used — so our seven servers cost far less than the video's
framing suggests. Verify with `/context` rather than pruning on instinct.

**Also worth knowing:** agent teams use roughly **7x** the tokens of a normal
session, and scheduled tasks send full context on every fire even while the
session is idle.

Not adopted: the output-token scaffolds (ponytail, caveman, "be brief" one
liners). The video rates them least effective, and output tokens are the
smaller half of the problem.

## Review the Copilot subscription ($29/mo)

**Queued 2026-08-24. After the current loose ends.** Corrected from an
inferred $10 — it is the **$29/month** tier, which makes it the third most
expensive plan on the fleet after claude ($100) and grok ($30).

What makes it worth a deliberate look rather than a reflex cut:

- Its measured peak draw is ~30%, so it is genuinely used, unlike the
  never-drawn plans.
- But it is **`access: forbidden`** for everything except GitHub's own
  clients — it cannot be routed to by Hermes or used as a general model
  provider, so it contributes nothing to the shared pool.
- The question is therefore narrow: is GitHub-native PR review and repo Q&A
  worth $29/mo *on its own*, given `gh` CLI plus any routable model can do
  much of the same work at no marginal cost?

Do this once the plan ranking has ~14 days of history, so the utilisation
figure means something.

## Monthly plans that work with Hermes — researched 2026-08-24

**Short answer: ClinePass is unusual, and that is why it works.** The
industry pattern is that a flat monthly subscription buys access through the
vendor's *own clients*, while programmatic access is a separate pay-per-token
API. ClinePass is a flat-rate **API-key bundle**, which is exactly what an
agent like Hermes needs.

Checked:

| Plan | Monthly? | Usable by Hermes? |
|---|---|---|
| **ClinePass** ~$9.99 | yes | **Yes** — flat-rate API key bundle. Currently our only paid Hermes pool |
| **z.ai GLM Coding** $18 / $72 / $160 | yes | **No, as written.** Ships an OpenAI- *and* Anthropic-compatible endpoint (the only drop-in Claude Code replacement besides Anthropic), but the plan is explicitly *"limited to officially supported coding tools and is not a general API subscription"*. Hermes is not one of the 20+ supported tools |
| **Kimi / Moonshot** $19 Moderato, $99 Allegro | yes | **No** — consumer plans cover chat plus Kimi Code credits; the Moonshot API is separate pay-per-token (~$0.60–0.95/M in) |
| Google AI Pro $19.99 | yes | **No** — chat interface only, API bills separately |
| ChatGPT Plus $20 | yes | Tolerated but not committed; reserved for coding anyway |
| GitHub Copilot $29 | yes | **Forbidden** for third-party clients |

**Implication.** There is no obvious second flat-rate pool to add. The
realistic ways to widen Hermes's supply are: a second ClinePass-style bundle
if one appears, pay-per-token API credit (openrouter/deepseek — the retired
prepaid tier), or **upgrading the z.ai plan only if their terms change**.
Worth re-checking periodically; this category moved fast in 2026.

Also noted for the plan review: z.ai's tiers are **Lite $18 / Pro $72 /
Max $160**, so there is headroom to buy more of a pool we already use — via
the zcode TUI, not Hermes.

## Also outstanding (raised, not formally queued)

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
- **Type `skills/session-finder/launch.py`** (decided 2026-10-09: leave for
  now): basedpyright with default rules reports 52 pre-existing errors there
  (untyped launch-record dicts, Optional access in the helm-reply path); the
  tests pass and both test files are clean. A separate typing pass, not a
  blocker.
- **`cow-pasture remove A B --force` ignores `--force` with several names**
  (seen 2026-10-09): the first dirty pasture prints "Not a TTY — defaulting
  to no" and nothing is removed; one name per call works. Fix the flag
  handling in `bin/cow-pasture`.
- **Herdr-only ADE capabilities, Orca parity gaps** (surveyed 2026-10-09,
  after `bin/self-slash` gained its Orca backend). Refuse in Orca:
  autorename's `relocate-pane.sh`, `launch.py start_tui` (zcode/muse).
  (`/orc`, `/orc-meta` + `orc_watchdog.py` and herdr-orchestration were
  retired 2026-10-09 instead.) Silent skips:
  autorename placement (`herdr_place.py`), the herdr SessionStart hook
  (Orca's own hook covers it). Degraded: `launch.py close` leaves Orca
  terminals open; acp-run reports agent state only to herdr; helm/fleet mark
  non-Claude Orca TUIs `unknown` (tidy.py's Orca status merge could be
  reused); bigteam Step 0 and session-finder rung d describe only herdr;
  `where.py` uses a possibly stale `$ORCA_TERMINAL_HANDLE`. Easy wins:
  `orca terminal close/rename/create --command/send`. No Orca equivalent:
  moving a terminal between worktrees, reporting agent state into an Orca
  terminal. herdr-sleeper needs no port (Orca Agent hibernation).
  **Done 2026-10-09 (easy wins):** `launch.py close` now closes the Orca
  terminal a launch was hosted in (`orca terminal close --terminal`, skipped
  for the caller's own terminal and for handles Orca no longer lists; test
  `tests/test_launch_orca_close.py`; verified live 2026-10-10, which found and fixed a
  `terminal create` handle-parse bug and failed starts and closes leaving their claim blocking the repo); autorename needs no Orca step (Orca's
  terminal title already follows the session's `custom-title` record; noted in
  its SKILL.md); bigteam Step 0 and session-finder rung d now give the Orca
  commands. **Still queued:** `launch.py start_tui`, acp-run agent-state reporting into Orca,
  helm/fleet `unknown` status for non-Claude Orca TUIs, `where.py` stale
  handle, `terminal create --command/send` as a herdr-pane substitute.

## Re-check Context7 use (on or after 2026-10-24)

Added to Claude Code 2026-10-09; kept on 2026-10-10 (~0.2k tokens/session) while
Claude Docs and other connectors were cut (docs/disabled-skills.md). Count
`mcp__claude_ai_Context7__` calls in `~/.claude/projects/*/*.jsonl` since
2026-10-10; if still ~0, ask djbclark whether to block it too. Firecrawl
(~5.6k/session, ~250 calls/week) is the costly one; see the same doc.


## Orca's short PostCompact hook (watch stablyai/orca#25211)

Orca adds a ~3 KB shell wrapper as Claude Code's `PostCompact` hook. Claude Code
prints it after every `/compact` and keeps it in context (~1k tokens). Orca rewrites
`~/.claude/settings.json` on each start, so a local edit does not stick. Upstream:
issue stablyai/orca#25209 (we +1'd and commented, 2026-10-10) and fix PR #25211.
The fork carries the fix as branch `djbclark/short-postcompact-hook` (upstream
`main` + the PR commit, rebased 2026-10-10, **not built**). Build it only if
djbclark asks; once a release ships #25211, delete that branch.

## Review the Jev-vs-GLiDE dual review (ends by 2026-10-23)

**Started 2026-10-11 (operator).** The Jev-only prompt-effort review was closed the
same day; see `docs/jev.md` "Dual review". Jev and GLiDE answer the same prompt-effort
(hook) and agent-choice (`route_agent.py --brief`) questions side by side for at most 12
days; the window closes itself (mode goes off). On 2026-10-23 run
`bin/jev report --review dual-1 --json` and `bin/jev disagreements --site
agent-choice --between`, label disagreements, then ask djbclark per backend: act, keep
shadow, or off. A self-removing launchd job (`com.djbclark.jev-remind-2026-10-23`)
pings Hermes that morning.

## Why the `sed` edit failed twice (queued 2026-10-14, operator) — DONE 2026-10-14

Cause: macOS BSD `/usr/bin/sed` rejects `1{/^$/d}` (`extra characters at the end of d command`; BSD needs
`1{/^$/d;}`), and the redirect still created an empty `body.md`, which `gh issue create --body-file` filed
(libkrun#926). GNU sed is installed as `gsed`. Fixed in `~/CLAUDE.md` item 33 (`home-agents.md`, site-djbclark
`0e3fbf4`; `cursor/home-agents.mdc` likewise): never feed a `--body-file` from a pipeline, check `[ -s f ]`
first, use `gsed`. Memory: `feedback_exit_status_through_pipe.md` (site-private `e5c12bd`). The forgejo skill
scripts have no `--body-file` use, so they needed no guard.

## Flaky MockWebServer tests on the SIPB runner — DONE 2026-10-14

Root causes found with a Python churn repro, a standalone okhttp 4.11 MockWebServer loop (`java-churn/`) and C probes
(`duplex-probe.c`, `reuse-probe.c`, `dup-bind-probe.py`), each checked against a normal Linux kernel (Ubuntu 24.04
container): (1) the shim's port seed repeated within a second, so consecutive servers got the same port, and
libkrun TSI keeps a listener closed during a blocked `accept()` alive (libkrun#929); (2) a blocked `recv()` blocks
`send()` on the same socket, which stalled WebSocket clients (libkrun#819/#926); (3) TSI sockets always have
`SO_REUSEPORT` (libkrun#860), so duplicate listens succeed. Fixed in `loopback-port-shim.c` (new seed plus ring of
recent ports; wait in `poll()` before blocking reads and accepts). The full Plektra suite (1,417 tests) now fails only
`CornerButtonThemeTest` (also fails on GitHub Actions and a laptop), in runs 229 and 230 in a row, 3 m 4 s test step.
Tickets updated: libkrun#926 (retitled, comment), #819, #860, new #929; SIPB/hyades#2 comment 25. Wrong turns, kept
because they cost time: a Python keep-alive repro that was negative (and had its own acceptor bug), `SO_RCVTIMEO` is not
honoured under TSI (use `poll`), and `forgejo-api --help` was run once by mistake (posted nothing).
The 3-of-20 `reuse-probe` failures with the shim were stale listeners leaked by earlier no-shim runs on the same fixed port
(each swallows one connection, then they are gone within 60 s); on a clean port the shim gives 60 of 60 at gaps of 0 to
50 ms (runs 235, 236; libkrun#929 corrected). Open: check libkrun#926,
#929, #819, #860 and SIPB/hyades#2 for replies; `CornerButtonThemeTest` is an upstream Plektra issue.

## Make the loopback shim available by default on forgejo.mit.edu, then ask SIPB (queued 2026-10-14, operator)

**Start only after the shim works perfectly**: the `reuse-probe` residue is explained (done 2026-10-14: stale listeners leaked by earlier
rounds, not the shim), and a few more full-suite runs stay clean (two so far, runs 229 and 230).

1. Look into how the shim (`skills/forgejo/examples/plektra/loopback-port-shim.c`) could always be used by
   forgejo.mit.edu jobs, where appropriate: for example baked into the runner image or the `ubuntu` label's base
   image, loaded through `/etc/ld.so.preload` by the runner or a container entrypoint, or a shared setup action; and
   when it is not appropriate (jobs that never use loopback, jobs that bring their own network setup, anything that
   relies on `shutdown()` or blocking-read semantics). Check what SIPB controls (image, runner config) versus what a
   job can do (the derived workflow builds it with `gcc` in about 1 s today, needing `gcc libc6-dev` installed first),
   and whether a precompiled shim would do (musl/glibc, arm64/x86_64).
2. Then open a ticket on SIPB/hyades with that request and links to all the shim code and evidence: the shim, the
   probes (`duplex-probe.c`, `reuse-probe.c`, `dup-bind-probe.py`, `java-churn/`), `skills/forgejo/SKILL.md` item 5,
   the numbers (suite 7 failures to 1; 800 MockWebServer iterations in 1 s instead of 150 s), and the libkrun tickets
   (#818, #819, #860, #926, #929). Link it from SIPB/hyades#2. Show the draft to djbclark before filing, and state
   plainly that the real fix belongs in libkrun's TSI driver.

**Progress 2026-10-14.** Step 1 is done: `skills/forgejo/examples/plektra/shim-by-default.md` (how jobs run, the six ways to
get the shim into jobs, why not global yet, alternative job images with measured pull times). Step 2 is FILED (2026-10-14, djbclark approved
the draft): https://forgejo.mit.edu/SIPB/hyades/issues/3, linked from SIPB/hyades#2 (comment 28); text in
`skills/forgejo/examples/plektra/sipb-hyades-shim-request-draft.md`. Verified along
the way: the shim builds and works identically on the ubuntu, alpine and rocky labels (run 238); job-level `container:`
works on the runner (run 239; `ghcr.io/cirruslabs/android-sdk:36` pulled in 47 s and already has SDK 36, but JDK 21 and no
`node`); curl -L download speed 79 to 102 MB/s and `mount -o remount,dax` does nothing (run 237, SIPB/hyades#2 comment 26).

3. **Make the forgejo skill cover all of this** (added 2026-10-14, operator: "Make a forgejo skill, and include proper use
   of shim and image selection in it, as well as anything else useful we have discovered"; the request said "forgego",
   read as forgejo). A `forgejo` skill already exists (`skills/forgejo/SKILL.md`: API, tokens, tea/fj, git, some CI
   notes); extend and reorganise it, or split a CI half into its own skill if SKILL.md gets too long, decided when doing
   it (a new skill goes in `skills/<name>/` here, `docs/skills.md`). Include at least: (a) when and how to use the shim
   (opt-in snippet, the three TSI behaviours in one paragraph, what it does not cover: Go and static binaries; `SO_RCVTIMEO`
   is not honoured under TSI, so use `poll`); (b) image selection: stock labels and what they lack, job-level `container:`
   overrides, images are never re-pulled (pin by digest), `actions/checkout` needs `node` in the image, measured pull
   times, our own image if built; (c) how to run and read probe workflows (`push-probe.sh`, waiting on a run, reading a
   job log by API, `exit 124` meaning, line-buffer output, use a fresh port per run because stale listeners drain over about
   a minute); (d) runner facts (capacity 4, one krun microVM per job, shared host loopback, labels to images, resources);
   (e) ticket etiquette learned (search before filing, wait for testing, label AI preparation, correct yourself in the
   ticket, `forgejo-api` never `--help`, `--body-file` guard); (f) the suite results and what still fails
   (`CornerButtonThemeTest`); (g) the SIPB and libkrun ticket map. Keep SKILL.md under about 200 lines and push detail
   into `examples/plektra/*.md`.

4. **Build our own CI image: DONE 2026-10-14** (operator said yes; hosted on public ghcr.io, built by GitHub Actions for amd64).
   `ghcr.io/djbclark/ci-image-plektra` (repo github.com/djbclark/ci-image-plektra, local `~/src/ci-image-plektra`):
   `FROM ghcr.io/cirruslabs/android-sdk:36` + JDK 17 + node 18 + `/usr/local/lib/portshim.so` (source pinned by commit
   `SHIM_SHA`). Run 240 on the runner: `actions/checkout` works, the shim fixes the duplex stall and 20 of 20 reuse rounds.
   `DERIVE_IMAGE=ghcr.io/...@sha256:<digest> push-bench.sh asis BRANCH` runs the full suite on it (run 241). Remaining: bump
   the digest when the Dockerfile changes; ask SIPB (in #3) whether they prefer to host the image themselves.
5. **forgejo skill: DONE 2026-10-14** as the new `skills/forgejo-ci/` (CI half split out of `skills/forgejo`; evidence in
   `skills/forgejo-ci/runner-notes.md`), linked into every TUI with `skill-everywhere`, rows in README and `docs/skills.md`.
