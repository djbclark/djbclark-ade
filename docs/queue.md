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
the crush TUI, not Hermes.

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
