# Upstream issues worth filing

Written 2026-08-23 from problems verified on this machine. **Both are now
filed** — kept here because the write-ups carry evidence and measurements the
issue text summarises:

- #1 → [NanoNets/Graft#185](https://github.com/NanoNets/Graft/issues/185)
- #2 → [vectorize-io/hindsight#3735](https://github.com/vectorize-io/hindsight/issues/3735)
  (the package `@vectorize-io/hindsight-coding-agents` lives in the
  `vectorize-io/hindsight` repo)

## 1. graft — statusline conflates "built but empty" with "not built"

**Repo:** `@nanonets/graft` (npm; installed globally at
`/opt/homebrew/lib/node_modules/@nanonets/graft`)

**Version seen:** the globally installed build as of 2026-08-23.

**What happens:** In a repo whose indexed languages yield no code symbols —
e.g. a docs/markdown-only repo — `graft build` succeeds and legitimately
reports `✓ wiring: 0 nodes (), 0 edges, 0 cards []`. The Claude Code
statusline then renders:

```
◤ graft · not built · run graft build
```

...forever, because `renderStatusline()` treats `nodeCount === 0` as
"never built" (`dist/claude/format.js:24`), and `resolveStats()` falls back to
`readWiring()` which is also empty (`dist/claude/statusline.js`).

**Why it matters:** the bar tells the user to run a command they *have already
successfully run*, and keeps telling them after every rebuild. It reads as a
broken install. `graft ask` / `graft grep` still work fine, so the message is
actively misleading.

**Correction (2026-08-23):** an earlier revision of this file claimed a
second, broader trigger — that repos with working graphs also report
"not built". **That was wrong**, and it is retracted. It came from grepping
`graft check` output for the string "not built", which matched the unrelated
*deep layer* line (`deep layer: not built (run graft build --deep …)`) — an
optional LLM-built layer, not the wiring graph. Checked properly,
`~/ops/site-djbclark` reports `graph check: OK — the wiring graph is in sync
with the code` with 502 nodes. Two lessons, both ours not graft's: grep for a
substring is not a status check, and the deep-layer line is noise unless you
are actually using `--deep`.

**Why this repo is genuinely empty**, for the record: its only code is three
JS files under `.claude/` (`workflows/graph-audit.js`, two helper `.cjs`).
Graft's walker skips dot-directories, and unlike ordinary skipped dirs this
is not overridable — `graft build --include-dir .claude` refuses with
"dot-directories are never overridable". So the 0-node graph is correct, and
the only wrong thing is the *wording* of the statusline.

**Suggested fix:** distinguish the two states. The build already knows whether
it ran, so persist that (a `builtAt` in `graft/.cache/stats.json`, or simply
the existence of the cache/stamp) and render empty-but-built differently, e.g.
`◤ graft · 0 nodes · no indexed code`. Falling back to "not built" only when
no build artifact exists at all.

**Repro:** `graft build` in any repo containing only `.md` files, then look at
the Claude Code statusline.

## 2. hindsight-coding-agents — documented config keys are a subset of what's read

**Package:** `@vectorize-io/hindsight-coding-agents` (0.3.4 on this machine)

**What happens:** the bundled `hindsight-coding-agent` skill documents a small
set of config keys for `~/.hindsight/coding-agent.json`, but the code reads
several more that are load-bearing for any non-default topology:

`optInOnly`, `optInPaths`, `retainTags`, `retainMetadata`, `bankIdTemplate`,
`resolveWorktrees`, `maxParallelRetains`, `daemonProfile`, `daemonIdleTimeout`,
`apiPort`, `embedPackagePath`, `embedVersion`

Also undocumented: `isOptedIn()` returns true for any path under `optInPaths`
**or** any `mapPathToBank` entry — a coupling that changes what a retention
allowlist actually does.

**Why it matters:** the default single-bank setup is a trap at scale. On this
machine one bank accumulated 1,756 facts across 7 unrelated projects, giving
roughly a 1-in-17 chance that a recalled memory came from the project the
agent was working in. Fixing that requires exactly the keys that aren't
documented, so users can't find the fix from the docs alone.

**Suggested fix:** document the full key set in the bundled skill, and call out
the `gitProjectName()` fallback — when `git rev-parse --git-common-dir` fails
it falls back to the directory basename, so `bankIdTemplate` silently produces
"drain banks" named after non-git parent directories (`::src`, `::tmp`, and
the home directory itself).

**Evidence:** measured on this machine and written up in
`~/ops/site-private/memory/project_hindsight_memory_restructure.md`.

## Not filed — a papercut worth knowing: `graft build` edits tracked `.gitignore`

Every `graft build` appends `/graft/` to the repo's **tracked** `.gitignore`
and drops an untracked `.ignore` file, so a repo that was clean before the
build is dirty after it. It's a helpful default, but it has a real cost:

- It leaks tool-local cache config into shared repos (including public ones).
- In a fork that tracks upstream, it puts a permanent local modification on a
  tracked file.
- **It breaks other tooling.** An uncommitted `.gitignore` blocks git branch
  checkout, which made `cow migrate --all` fail on every candidate in
  `~/.hermes/hermes-agent` (each rolled back cleanly, but nothing migrated
  until the tree was clean).

**What we do instead** — keep the tracked file pristine and put the rules in
the repo's local excludes:

```bash
git checkout -- .gitignore
printf '\n/graft/\n/.ignore\n' >> .git/info/exclude
```

Applied to `~/.hermes/hermes-agent` and all three `~/ops` repos. Re-apply
after any `graft build` in a new repo — or check `git status` afterwards,
which is the cheap habit.

A `--no-gitignore` flag (or writing to `.git/info/exclude` by default) would
remove the papercut; worth raising upstream if it recurs.

## 3. orca — CLI parity for structural reorg (filed 2026-09-26)

**Filed:** [stablyai/orca#23272](https://github.com/stablyai/orca/issues/23272)
(umbrella). Comments added to [#9632](https://github.com/stablyai/orca/issues/9632#issuecomment-5849981913)
(terminal move), [#12306](https://github.com/stablyai/orca/issues/12306#issuecomment-5849982200)
(worktree ordering, suggested `--before/--after`) and
[#8766](https://github.com/stablyai/orca/issues/8766#issuecomment-5849982407)
(project-group CLI). The full gap map vs herdr is in #23272; its body is the
source of truth.

**Still-open gaps as of 2026-09-26** (Orca 1.4.212; herdr comparison from the
installed `herdr` CLI):

1. `terminal move` across worktrees: PR #15108 open, unmerged (herdr: `pane move --tab`).
2. Move a pane/tab into a split or another tab in the same workspace (herdr: `pane move --tab --split`); #12083 and #10055 cover it as a command/shortcut only.
3. Swap panes (herdr: `pane swap`): no issue anywhere in the full corpus.
4. Resize an existing split (herdr: `pane resize`): #15771 is creation-time only; no issue for post-hoc.
5. Split ratios missing from `terminal list --include-visual-layouts` output (needed to plan a resize): no issue. Verified live on 1.4.212: a `pane-split` node has only `type`, `direction`, `first`, `second`, while `orca-data.json` stores the ratio (e.g. `0.304`). The tab-group-level split node was not tested.
6. Reorder tabs / worktrees: #20515, #12306.
7. `repo rm`: #22433. Project-group CLI: #8766. Declarative layout: #1499 / PR #1548.

**Retractions:** (1) an earlier answer said Orca had no project rename; wrong,
`orca project setup-update --display-name` renames it. (2) The umbrella's first
draft said there was no layout introspection; wrong, `orca terminal list
--include-visual-layouts --json` returns the group/tab/pane tree (split
direction, no ratios). Corrected in #23272's body and a comment. The gap
search now covers the title and body of all ~23,000 issues and PRs, not just a
partial window.

## 4. orca — evidence for #22571 "Expose worktree sleep as a CLI command" (draft comment, 2026-09-26)

**Not a new issue.** [stablyai/orca#22571](https://github.com/stablyai/orca/issues/22571)
(opened 2026-09-23) already asks for exactly this and names the runtime
methods. Add evidence as a comment instead of a duplicate:

> Adding a data point and a related ask.
>
> **Why the CLI matters beyond housekeeping scripts.** On a 16 GB Mac
> (Orca 1.4.2xx, macOS 27) I had 15 idle `claude` processes summing to
> 2.0 GB RSS with 6.5 of 8 GB swap in use. Agent hibernation was already
> on — but it can only see Orca's own terminals, and 14 of those 15 agents
> were running in another multiplexer. I ended up writing an external
> policy for that side (transcript-mtime idle clock → `/exit` → later
> `claude --resume <id>`, with Orca's hibernation eligibility rules
> re-implemented on top). A `orca worktree sleep` / `orca worktree wake`
> pair would let one such policy cover Orca worktrees too, instead of
> re-implementing hibernation outside Orca.
>
> **Smaller related ask:** expose the hibernation clock. `orca terminal
> list --json` / `worktree show --json` could carry `idleSince` (or
> `lastAgentDoneAt`) per terminal — that is what an external policy needs
> to decide *whether* to sleep. Today the only way to get it from outside
> is the agent's transcript mtime.
>
> Also: #3693 ("Auto-Sleep inactive workspaces") looks fully answered by
> the shipped Agent hibernation setting and could be closed with a link to
> the docs page.

## 5. herdr — Discussion: sleep/wake for idle resumable agents (draft, 2026-09-26)

**Repo:** `herdrdev/herdr` (Rust, Apache-2.0). Per its `CONTRIBUTING.md`
unsolicited PRs are auto-closed and feature ideas go to **GitHub
Discussions** — so this is a Discussion post, not an issue or PR.

**Not posted yet** (checked 2026-10-04; nothing by djbclark in
herdrdev/herdr discussions or issues). **The landscape moved after this
draft was written:**

- [#4724](https://github.com/herdrdev/herdr/discussions/4724) (2026-09-28,
  show-and-tell): `herdr-agent-hibernate` — a Herdr *plugin* by dalogax
  that auto-sleeps idle OpenCode/Claude/Codex panes and resumes on focus
  (`herdr plugin install dalogax/herdr-agent-hibernate`). No comments, no
  maintainer reply yet.
- [#631](https://github.com/herdrdev/herdr/discussions/631) (older idea
  thread, "Auto-hibernate idle off-screen agents"): prabhatgmp's
  `herdr-park` plugin is pointed to there, and gentoosys posted a
  correction that `pane release-agent` does not stop the agent process.
  No maintainer reply there either.

So Herdr now has a plugin system and two community plugins doing the
automatic half. **Our sleeper became a plugin too (2026-10-04,
`plugins/herdr-sleeper/` in this repo):** it adopts their good parts (SIGTERM
exit, seq-based idle clock, wake-on-focus, Enter-stub, sidebar claim) and adds
what neither has — the fail-closed journal state machine, argv replay safety,
session-live-elsewhere refusal, config validation, damaged-state quarantine.
Soaking it for a day or two before posting. **Published 2026-10-05: the
reference implementation is now the plugin repo
[djbclark/herdr-sleeper](https://github.com/djbclark/herdr-sleeper)**
(`herdr plugin install djbclark/herdr-sleeper`; Python 3.9+ stdlib-only,
77 tests, MIT), with the standalone script as the pre-plugin history. The
differentiators our post still adds: the fail-closed
eligibility rules (drafts, session forks, argv replay safety), the
`state_changed_at` timestamp ask, argv preservation in `AgentResumePlan`
(a native bug too: restart-restore drops `--dangerously-skip-permissions`
etc.), and a race-free native sleep. **Decision (2026-10-05): post as a
comment on #631 cross-linking #4724 and the plugin repo, not a cold new
Discussion — after the soak (started 2026-10-04 evening; post on/after
2026-10-06).**

**Posted 2026-10-05:** [#631 comment](https://github.com/herdrdev/herdr/discussions/631#discussioncomment-18769271), rewritten for v0.1.1 and linking [LESSONS.md](https://github.com/djbclark/herdr-sleeper/blob/main/LESSONS.md); asks re-ranked to match its "Asks for Herdr upstream". The draft below is the superseded pre-v0.1.1 version, kept for history.

**Superseded draft of the comment on
[#631](https://github.com/herdrdev/herdr/discussions/631)**:

> Adding a third data point to this thread — I ended up building this as a
> plugin too, and it has been running clean here: **[djbclark/herdr-sleeper](https://github.com/djbclark/herdr-sleeper)**
> (`herdr plugin install djbclark/herdr-sleeper`). It shares the good bones
> of #4724's `herdr-agent-hibernate` and the `herdr-park` plugin pointed to
> above (SIGTERM exit, seq-based idle clock, wake-on-focus, in-pane Enter
> stub, sidebar claim), and adds a fail-closed safety layer: a journaled
> sleep/wake state machine (records written before the exit, reconciled on
> every tick, never dropped because a pane vanished), argv-replay safety
> (refuses `--fork-session`, positional prompts, unknown-arity options),
> session-live-elsewhere refusals on wake, config validation, and
> damaged-state quarantine. Stdlib-only Python 3.9+, no launchd.
>
> Three small things that would make this native, smallest first:
>
> 1. **A timestamp on agent state.** `agent list` exposes only
>    `state_change_seq`; a `state_changed_at` (ms since epoch) on
>    `agent.list`/`agent.get`/`pane.get` would let any external policy
>    compute idle time without polling deltas.
> 2. **`herdr agent sleep <target>` / `herdr agent wake <target>`.** The
>    restore path already builds an `AgentResumePlan` from the stored
>    session ref; exposing it on demand would close the one race an
>    external tool cannot — between its final eligibility check and the
>    agent consuming the exit. One thing to carry over from the live
>    process when doing so: the original argv. `agent_resume::plan()`
>    rebuilds `["claude", "--resume", <id>]` from `(source, agent,
>    session_ref)` alone, so a pane launched with
>    `--dangerously-skip-permissions` (or `--model`, `--add-dir`, …) comes
>    back after a server restart without those flags — a native bug
>    independent of sleeping. `pane.process_info` already exposes the
>    running argv; persisting it next to the session ref would fix both.
> 3. **Optional policy:** `[session] sleep_idle_after = "12h"` (off by
>    default), with the eligibility Orca's hibernation uses.

**Version seen:** `herdr 0.7.5-preview.2026-07-29-44b3adb12552`, macOS 27.

> **Title:** Sleep/wake for idle resumable agents (a reference implementation, and three small things that would make it native)
>
> **Problem.** Every idle agent pane keeps a live model-CLI process. With
> 14 Claude panes idle for 5–6 h I measured 2.0 GB RSS of `claude` on a
> 16 GB machine already deep into swap. Orca solves this for its own
> terminals with "Agent hibernation"; Herdr has nothing equivalent.
>
> **What Herdr already has.** The two things a sleeper needs: the native
> session reference per pane (`agent_session.value`, from the official
> integration) and a way to start an agent into an existing shell pane
> with forwarded args. So I built the policy outside Herdr, on the public
> CLI: after a user-chosen idle window (`idle = "12h"`, `"90m"`, …) it
> submits `/exit`, keeps the pane, prints a wake hint into it (carrying
> the script's absolute path, so it runs as pasted without a PATH
> install), prefixes the
> label with 💤; `wake` runs `herdr agent start <name> --kind claude --pane
> <id> -- <orig argv> --resume <uuid>`. Verified round-trip: same session
> id, prior context intact. It fails closed on drafts in the composer,
> unreplayable argv (`--fork-session`, positional prompts), session forks
> (id live elsewhere), damaged state and config, and overlapping runs.
>
> Reference implementation (script, 65 tests, README — usable as-is, no
> changes to Herdr):
> https://github.com/djbclark/herdr/tree/herdr-sleeper/scripts/herdr-sleeper
>
> **What would make this native, smallest first:**
>
> 1. **A timestamp on agent state.** `agent list` exposes only
>    `state_change_seq`. A `state_changed_at` (ms since epoch) on
>    `agent.list` / `agent.get` / `pane.get` would let any external policy
>    compute idle time without reading the agent's transcript mtime —
>    which is what I do now, and it is why the script is Claude-only.
> 2. **`herdr agent sleep <target>` / `herdr agent wake <target>`.** The
>    restore path already builds an `AgentResumePlan` from the stored
>    session ref (`src/agent_resume.rs`) and `[session]
>    resume_agents_on_restore` relaunches with resume flags after a server
>    restart. Exposing that plan on demand — stop the process, keep the
>    pane and its session ref, relaunch later — would be a small surface
>    over existing machinery, work for every integration that reports
>    session refs, and close the one race an external tool cannot: the gap
>    between its last eligibility check and the agent consuming `/exit`.
>    One thing to carry over from the live process when doing so: the
>    original argv. `agent_resume::plan()` builds the restore command from
>    `(source, agent, session_ref)` alone — `["claude", "--resume", <id>]`
>    — so a pane launched as `claude --dangerously-skip-permissions` (or
>    with `--model`, `--add-dir`, …) comes back after a server restart
>    without those flags. `pane.process_info` already exposes the running
>    argv; persisting it next to the session ref would fix both restore
>    and an on-demand wake.
> 3. **Optional policy:** `[session] sleep_idle_after = "12h"` (off by
>    default), with the eligibility Orca's hibernation uses: state
>    `done`/`idle`, pane not focused, no keystrokes since, session ref
>    present, no other pane sharing the session.
>
> Sharing the script for the semantics; not asking to submit a PR.

## 6. graft — `init` bakes machine/worktree-specific absolute paths into tracked hook files (not filed — already NanoNets/Graft#309, checked 2026-10-08)

> **Already reported:** [NanoNets/Graft#309](https://github.com/NanoNets/Graft/issues/309)
> (open) describes the same root cause — `.cursor/hooks.json` with an absolute
> checkout path and `BAKED` with the generating machine's `node_modules` — and
> asks for a repo-relative `init` mode. Searched issues and the web 2026-10-08;
> no other match. What this write-up adds, usable as a comment there: the
> per-worktree consequence below (stamp lives in the ignored cache, so each new
> worktree replays init once) and that a git clean filter cannot mask it.
> **Posted 2026-10-08:** https://github.com/trailhq/Graft/issues/309#issuecomment-6073784254

**Repo:** `@nanonets/graft` (`src/claude/shim-template.ts`, `src/hosts` Cursor hooks).

**What happens:** `graft init` (and the version-stamp upkeep that replays it
at session start, `src/upkeep.ts`) writes four files meant to be committed
(`.claude/helpers/graft-hooks.cjs`, `.claude/helpers/graft-statusline.cjs`,
`.cursor/hooks/graft-hooks.cjs`, `.cursor/hooks.json`) with absolute paths
of the machine and checkout that ran it: `const BAKED = "<this install's
dist/claude>"` and, in `.cursor/hooks.json`, `node "<this worktree>/.cursor/hooks/graft-hooks.cjs"`.
The stamp lives in the untracked graph cache, so every fresh git worktree
replays init once and shows four modified files. Orca then refuses to delete
the worktree ("uncommitted or untracked changes"). Seen on a worktree whose
branch was already merged.

**Why we can't fix it locally:** a clean filter that restores the committed
paths does not help — `git status` treats a size change as modified without
running the filter. Untracking the files breaks a fresh worktree, because the
tracked `.claude/settings.json` calls the helper that upkeep itself runs from.

**Suggested fix:** emit portable content. `BAKED` is only the first
candidate in a resolution chain that already falls back to `npm root -g`, so
it can be dropped from committed shims (or init can leave a file alone when
only `BAKED` differs). `.cursor/hooks.json` could use a repo-relative command
the way `.claude/settings.json` already uses `${CLAUDE_PROJECT_DIR:-.}`;
`src/hosts/mcp-config.ts` already avoids baking a home directory into the MCP
entry for the same reason.

**Local workaround:** `git checkout -- .claude/helpers .cursor` before
deleting the worktree.

## 7. zcode-acp — `$/zcode/turnState` uses a non-ACP extension prefix; turn stats arrive as agent text (filed 2026-10-09)

Repo: william0wang/zcode-acp (npm `zcode-acp-server` 0.65.1), the bridge that
wraps `zcode app-server --stdio` as an ACP agent. Seen here with `acp-run zcode`
(ACP Python library `agent-client-protocol`), both reproduced twice with the
prompt "Reply with exactly: OK".

1. **Notification method `$/zcode/turnState`.** ACP reserves the `_` prefix for
   extension methods and notifications; the `$/` prefix is LSP's convention.
   Clients built on the ACP Python library route only `_`-prefixed names to
   `ext_notification` and raise `method_not_found` for anything else, so every
   turn logs a traceback (`ERROR:root:Unhandled error while handling
   notification method=$/zcode/turnState ... RequestError: Method not found`).
   Fix on their side: rename to `_zcode/turnState` (or `_zcode.turnState`).
   Our workaround: `tools/acp-run/acp-run` folds `$/` into `_` before routing.
2. **Per-turn stats as an `agent_message_chunk`.** After the answer, the bridge
   sends a text chunk `✓ completed · cache 6/7 messages · 3.0k cache-read tokens`
   with `messageId: "turninfo_<uuid>"`. A client that concatenates agent text
   (every headless one) returns `OK✓ completed · …` as the answer. It belongs in
   `_meta` / a usage notification, or behind an option. Our workaround: drop
   chunks whose `messageId` starts with `turninfo_`.

Evidence: `~/.local/state/acp-run/20261009-000130-zcode-5906.jsonl` (before the
workaround) and `20261009-000400-zcode-12981.jsonl` (after). Note the JSONL
holds the `turninfo_` chunk but not the `$/zcode/turnState` traceback, which
went to the client's own stderr; the prefix claim was re-verified instead
against the ACP spec (Extensibility: custom notifications start with `_`;
clients SHOULD ignore unrecognized ones) and against `agent-client-protocol`
0.12.1 (`acp/router.py` routes only `_`-prefixed names to `ext_notification`
and raises `method_not_found` for everything else).

Filed / found (2026-10-09):

1. Issue search (`gh issue list`/`gh pr list --state all`, terms `turnState`,
   `$/`, `turninfo`, `agent_message_chunk`, "method not found", `usage`,
   `cache-read`, `stats`): no prior thread on either defect. PR #54 added the
   `$/zcode/turnState` notification, PR #221 the turn-end stats line; neither
   discusses the prefix or a switch. The README's config file (`debug`,
   `session`, `autoCompact`, `goal`, `interaction`, `sandbox`, `remote`,
   `quota`) and the `ZCODE_ACP_*` table have no field that hides the line, and
   `dispatchTurnInfo` in `src/handlers/dispatch.ts` is unconditional, so it is
   a bug/feature request, not a defaults question.
2. Filed: https://github.com/william0wang/zcode-acp/issues/311 (prefix).
3. Filed: https://github.com/william0wang/zcode-acp/issues/312 (stats chunk).

## 8. ralph-orchestrator — a timed-out lifecycle hook is killed, its children keep running (draft, 2026-10-09)

**Status: draft, not filed.**

**Repo:** [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator)
(Homebrew `ralph-orchestrator`, release binary `ralph-cli`).

**Versions:** ralph v2.10.1 (latest release, 2026-06-22), aarch64-apple-darwin,
macOS 27. The code below is unchanged on `main` at `edc2b3268c9b` (2026-10-09).

**Searched first (2026-10-09, issues and PRs, open and closed):** `hook
timeout`, `timed out`, `process group`, `children`, `orphan`, `kill hook`,
`timeout_seconds`, `zombie`, `lifecycle hook`, `setsid`, `killpg`, and PRs
matching `hook executor`. None found. Nearest: #204 / PR #207 (orphaned ACP
*agent* processes, fixed), #76 (Ctrl+C race), PR #215 (lifecycle hooks v1,
which added the executor).

**Draft title:** Lifecycle hook timeout kills only the hook process; its child processes keep running after ralph exits

**Reproduction:**

1. A hook whose command runs a child that outlives the timeout, e.g.
   `command: ["bash", "./check.sh"]` with `check.sh` running `sleep 60`, and
   `timeout_seconds: 5`, `on_error: block`, on `pre.loop.complete`.
2. Run a loop that reaches `pre.loop.complete`.
3. ralph logs `disposition=Block exit_code=None timed_out=true failure=hook
   timed out`, then `Error: Lifecycle hook 'judge' blocked orchestration at
   'pre.loop.complete': hook timed out`, and exits 1. That part is as
   documented.
4. After ralph has exited, `pgrep -fl 'check.sh|sleep 60'` still lists the
   hung `bash ./check.sh` and its `sleep 60`.

**Expected:** a hook timeout ends everything the hook started.
**Actual:** only the direct child is killed. Anything it spawned is orphaned
and keeps running, holding whatever it held (here a machine-wide test slot).

**Cause (from source):** `crates/ralph-core/src/hooks/executor.rs` spawns the
hook with `Command::new(..).spawn()` and no process group, and
`terminate_for_timeout` calls `child.kill()` (SIGKILL to that one PID). A
shell or wrapper hook's children are never signalled.

**Suggested fix:** on Unix, start the hook in its own process group
(`std::os::unix::process::CommandExt::process_group(0)`) and on timeout
signal the group: `killpg(pgid, SIGTERM)`, a short grace, then
`killpg(pgid, SIGKILL)`. Windows would need a job object for the same effect.

**Our workaround:** the judge hook bounds its own test run
(`timeout -k 30 $JUDGE_TEST_TIMEOUT`, default 3300 s, below the hook's
3600 s) and refuses on exit 124/137, so a hung check ends before ralph's
timeout fires.

**Evidence:** aiuse branch `claudehelm/ralph-pilot`, commit `d7725d2`
(mutation scenario `slow` in `orchestration/mutation-test.sh`, judge bound in
`orchestration/judge.sh`, notes in `docs/orchestration/README.md`); session
report `ralph-nits-report.md` item 1d (ClaudeHelm scratchpad, 2026-10-09).

## 9. Claude Code — a long slash command sent with `herdr pane run` arrives as a collapsed paste and never runs (not filed — already anthropics/claude-code#85654, checked 2026-10-09)

**Status: draft, not filed.** No new issue: the defect is Claude Code's and
is already reported, reproduced and labelled there.

**Repos:** [anthropics/claude-code](https://github.com/anthropics/claude-code)
(where the defect is) and [herdrdev/herdr](https://github.com/herdrdev/herdr)
(the delivery path, working as designed).

**Versions:** Claude Code 2.1.295, herdr
`0.9.1-preview.2026-09-21-0ff0f27e2226`, macOS 27.

**What happened:** `bin/self-slash` sent a `/compact <focus>` of about 900
characters with `herdr pane run <pane> <text>`. Claude Code received it as
pasted content, so it went to the model as a message and `/compact` did not
run. The same path with about 330 characters (01:01) ran the command.

**Why, from both sides:**

1. herdr wraps every API text in `ESC[200~ … ESC[201~` whenever the pane app
   has enabled bracketed paste (`encode_api_text` in `src/app/api_helpers.rs`,
   pinned by the test `api_pane_send_input_brackets_text_and_enter_atomically`).
   Length does not matter there, so the 330-character send was a bracketed
   paste too.
2. Claude Code collapses a paste over about 800 characters (or more than 3
   lines) into `[Pasted text #N]`, and a collapsed paste never dispatches a
   slash command. That is exactly
   [anthropics/claude-code#85654](https://github.com/anthropics/claude-code/issues/85654)
   (open; labels `bug`, `has repro`, `regression`, `reproduced`; reproduced
   through `tmux paste-buffer -p` on 2.1.233, 2.1.252 and 2.1.263).

**Searched first (2026-10-09):** claude-code for `pasted slash`, `paste
slash`, `bracketed paste`, `paste threshold`, `slash command paste`; herdr
for `bracketed paste`, `pasted text`, `slash command`, `paste mode`, `pane
run long`. Related but different: claude-code #98126 and #60673 (desktop
app), herdr #4990 (`agent prompt` into Devin CLI leaves a collapsed paste
unsubmitted).

**Optional comment for #85654** (adds only a newer version and a multiplexer
API path; a thumbs-up does the same job unless the thread goes quiet):

> Still reproduces on 2.1.295 (macOS 27), through a terminal multiplexer's
> API rather than a human paste: `herdr pane run <pane> "/compact <~900
> chars, one line>"` sends a bracketed paste plus Enter, Claude Code
> collapses it, and the text reaches the model as a message. The same call
> with ~330 characters runs `/compact`. So any tool that drives Claude Code
> through a multiplexer (herdr, tmux `paste-buffer -p`) hits the collapse
> threshold, not just people pasting.

**Our workaround:** `bin/self-slash` refuses arguments over 300 characters
(`SELF_SLASH_MAX` overrides) and has `--dry-run` (commit `bfd7a83`). Keep the
focus text in a state file and reference it from a short command.

**Evidence:** `~/.local/state/self-slash.log` lines at 03:50:37 and 03:51:12
on 2026-10-09 (pane `w2F:p8`), the 01:01:35 line for the working short send,
and the helm-auto learnings note in the ClaudeHelm scratchpad
(`helm-auto-learnings.md`, 03:52 entry).

## 10. herdr — session refs from an ACP launcher: comment-sized addendum for herdrdev/herdr#3184 (draft, 2026-10-09)

**Status: draft, not filed.** Post only after the acp-run change below has
been tested on a live pane; until then the addendum's claim is from source,
not from a run.

**Repo:** [herdrdev/herdr](https://github.com/herdrdev/herdr). Collie
([AltanS/collie](https://github.com/AltanS/collie), 1.17.2) only shows the
symptom: `collie doctor` fails `agent-sessions` on a Claude pane that has no
stored `agent_session`.

**Versions:** herdr `0.9.1-preview.2026-09-21-0ff0f27e2226`, Collie 1.17.2,
macOS 27.

**Existing thread:** [herdrdev/herdr#3184](https://github.com/herdrdev/herdr/issues/3184)
(open). It already establishes that herdr stores a session ref only from an
official source (`herdr:pi`, `herdr:claude`, …) and silently drops one from
a custom source, with four independent reproductions through 0.9.3. Its
2026-09-24 comment also names the workaround (report as the official source)
and its cost (that opts the pane into the official native restore, which is
wrong for a different agent). Collie: searched `agent-sessions`, `doctor`,
`acp`, `agent_session`, `session`, `herdr session` (this session) plus nine
terms earlier tonight; none found.

**What our case adds:** the agent behind the launcher *is* an official one.
acp-run starts Claude Code through its ACP adapter, and the ACP `sessionId`
equals the Claude transcript uuid (checked on launch
`20261008-161855-claude-8159`). acp-run strips `HERDR_PANE_ID`/`HERDR_ENV`
from the agent with `--interactive`, so Claude's own herdr hook never
reports, and acp-run's reports under source `acp-run` are dropped. Here
reporting the session as `herdr:claude` is the true identity, and the native
restore (`claude --resume <uuid>`) is the right one. So the fix for us is in
our launcher, not in herdr.

**Draft comment for #3184:**

> One more shape of this, with a fix on the launcher side: an official agent
> started through a wrapper. We launch Claude Code through an ACP client
> that owns the pane's state reports (source `acp-run`) and keeps Claude's
> own herdr hook from reporting the same pane. The session ref it reports is
> dropped, as described here, so tools that read `agent_session` (Collie's
> history and `collie doctor`) treat the pane as sessionless. Because the
> ACP session id is the Claude transcript uuid, the launcher can report the
> session as the official agent: one `pane report-agent-session <pane>
> --source herdr:claude --agent claude --agent-session-id <uuid>
> --agent-session-path <transcript> --session-start-source startup --seq
> <ms>` after `session/new`, keeping state reports under its own source. A
> documented way for a launcher to say "this pane runs agent X, session Y"
> without taking over X's state source would cover this case and the
> pi-family harnesses above.

**Open question to settle in the live test first:** two herdr guards might
still refuse the report, an owner conflict with acp-run's state authority and
a detected-agent conflict. If they do, the comment changes to report that, and
the fallback is a Collie request for a Claude `discover(cwd)` like its muse
adapter has.

**Evidence:** `todo-close-report.md` item 2 (ClaudeHelm scratchpad,
2026-10-09); the Diagnosis section of the Collie todo note; acp-run's `Herdr`
class in `tools/acp-run/acp-run`; herdr `session_ref_from_report` in
`src/agent_resume.rs`.

## 11. CodexBar — `codexbar usage --provider alibabatokenplan` hangs with no output (draft, 2026-10-09)

**Status: draft, not filed.**

**Repo:** [steipete/CodexBar](https://github.com/steipete/CodexBar).

**Versions:** CodexBar 0.73.0 (latest release, 2026-10-07), its bundled CLI,
macOS 27, Apple silicon. Alibaba account region INTL `ap-southeast-1`.

**Searched first (2026-10-09, issues and PRs, open and closed):** `alibaba`,
`alibabatokenplan`, `token plan`, `hang`, `hangs`, `timeout`, `cookies found`,
`cookie hang`, `usage hangs`, `CLI hangs`, `never returns`, `Token Plan
timeout`, `alibaba cookie`, `devin`. None found for this hang. Related, all
closed: #1731 (`--source auto` hung on a stale web source), #474 / PR #481
(an unbounded `waitUntilExit` in a CLI probe), PR #1748 (`serve` bounds
`/usage` per provider, which the plain CLI does not get), and #2891 / #2349
(Alibaba Token Plan failures after the cookie step, same INTL region).

**Draft title:** `codexbar usage --provider alibabatokenplan` hangs indefinitely when no browser session cookie is found

**Reproduction:**

1. A Mac with no readable Alibaba Token Plan session cookie in any browser
   (earlier versions reported "No Alibaba Token Plan session cookies found in
   browsers" for this account).
2. `time codexbar usage --provider alibabatokenplan --format json`

**Expected:** a prompt error, like `--provider alibaba` on the same machine,
which fails in about 1 s.
**Actual:** no output and no exit after 60 s; the caller has to kill it. On
the same run `--provider devin` answers in about 20 s. The provider is not
enabled in CodexBar's own config, so this is the explicit CLI query.

**Impact:** any script polling every provider pays its full timeout on each
run. aiuse had to add per-provider timeouts and a hang backoff for it.

**Suggested fix:** treat "no session cookie" as a terminal error before any
network call, and put a deadline on the provider's fetch in the CLI the way
PR #1748 did for `serve`.

**Not yet known:** where it blocks. No stack was taken. A `sample` of the
hung process would settle it and should go in the issue before filing.

**Our workaround:** aiuse commit `16472cf` (per-provider
`[collectors.codexbar] provider_timeouts` and a cross-process hang backoff),
and the operator disabled the provider in aiuse on 2026-10-08 (`daf9eec`).

**Evidence:** `aiuse-bugs-report.md` item 1 (ClaudeHelm scratchpad,
2026-10-09); aiuse bead `aiuse-e9d`; aiuse `docs/collector-concurrency.md`
("Hang backoff").

## 12. Collie — `collie update --help` starts a live update instead of printing usage (filed 2026-10-09)

**Status: filed as [AltanS/collie#392](https://github.com/AltanS/collie/issues/392).**

**Repo:** [AltanS/collie](https://github.com/AltanS/collie).

**Versions:** Collie 1.17.2+3d562ae5 (the `collie` on PATH when it happened),
macOS 27, Apple silicon, bun 1.4.2, downloaded install under `~/.collie`.

**Searched first (2026-10-09, `gh search issues --repo AltanS/collie`, open and
closed):** `update --help`, `help flag`. Nothing found.

**Draft title:** `collie update --help` begins the staged update instead of showing usage

**Reproduction:**

```
collie update --help
```

Expected: usage for `update` (the flags `collie help` lists: `--check`,
`--check --local`, `--major`, `--rollback`, `--status`).

Actual: the command starts the update at once:

```
updating Collie (staged checkout: building v1.18.1 beside the running version)…
From https::https://github.com/AltanS/collie
 * [new tag]           v1.18.1    -> v1.18.1
Preparing worktree (detached HEAD cfaf95a9)
bun install v1.4.2 ...
```

Interrupting it (the output was piped through `head`, so the process got
SIGPIPE during `bun install`) left a registered-but-missing git worktree in
`~/.collie` until `git -C ~/.collie worktree prune`. The running version was
not touched, which is the staged design working as intended.

**Why it matters:** `--help` is the one flag every user tries first, and here
it is the one subcommand where trying it changes the machine (a build, then a
detached swap and restart). `collie help` is fine; it is the per-subcommand
form that bites.

**Suggested fix:** treat `-h`/`--help` (and any unknown flag) on `update` as
usage, exit 2 before `cmdUpdate` touches the checkout. The same check is worth
applying to `build`, `restart` and `uninstall`.

**Evidence:** Claude memory note
`feedback_collie_update_help_runs_the_update.md` (2026-10-09); the ClaudeHelm
session transcript for 07:4x EDT; `~/.collie/logs/stdout.log` around
2026-10-09T11:4xZ shows only the later, intended update.

## 13. Collie — after the 1.18 upgrade an unpaired phone lands on `/auth/`, a dead-end 404 with no hint to pair (filed 2026-10-09)

**Status: filed as [AltanS/collie#393](https://github.com/AltanS/collie/issues/393), stale-shell cause labelled a hypothesis.**

**Searched first** (gh, AltanS/collie, open and closed issues and PRs, 2026-10-09
19:20 EDT; terms: `auth`, `sign in`, `Sign in link`, `not paired banner`,
`device not paired`, `reverse proxy auth`, `Nothing configured here`, `pair
screen 404`). Nearest threads, none of which covers this:

- #31 (closed 2026-08-13) "An installed PWA has no reachable path to a fronting
  proxy's sign-in page" — the reason the auth banner links to `/auth/` at all.
- PR #30 (merged) "tell an access refusal apart from an outage" — the banner's
  401/403 branch.
- #2 (closed) per-device auth via an identity header; #159 (closed) pairing
  lastSeenAt ENOENT; #341 (closed) Cloudflare Access JWT. Not this.
- ADR 0086 / 1.18.0 changelog: "Unpaired browsers see the pair screen." That is
  the intended behaviour; what follows is the case where they do not.

**Seen.** Mac host, Collie 1.17.2 → 1.18.1 via `collie update` at 07:44 EDT,
phone (Android, installed PWA over `tailscale serve`) never paired on 1.17.x
(state dir had no `paired-devices.json`, only an expired `pairing-pending.json`).
After the update the phone showed "Not Paired" and a page at `/auth/` reading
"Nothing configured here — Collie reserves /auth/ for a reverse proxy sitting in
front of it … Collie itself serves nothing here". The operator did not know
pairing was the remedy; it was found by reading the changelog on the host.

**Reproduce on the host** (what the phone hit):

```
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/api/panes
403
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/auth/
404
$ collie devices list
no devices paired — Collie answers no phone or browser until one is …
```

**Where the link comes from.** `web/src/components/connection-banner.tsx`
(1.18.1): `ConnectionBanner` returns `null` when `usePairing().refused` is set
and leaves the remedy to the pairing strip on the route; the `AuthErrorBanner`
with the "Sign in" `<a href="/auth/">` is shown only for an `authError` the
pairing check did not claim. So a 1.18.1 app shell should not have offered
`/auth/` for a `device not paired` 403. The likely path (not captured on the
phone, so a hypothesis): the installed PWA was still running the 1.17.2 app
shell from its service worker precache when the bridge went to 1.18.1; that
shell's auth banner treats every 403 as a proxy refusal and offers "Sign in" →
`/auth/`, the 1.18.1 bridge answers its reserved-path 404, and nothing on that
page says "pair". 1.18.0's "Unpaired browsers see the pair screen" holds only
once the new shell is active.

**Asks**, smallest first:

1. The `/auth/` 404 page could name the other cause: "If you came here from a
   Not Paired or Sign in banner and no proxy fronts this Collie, open Settings
   and pair (`collie pair` on the host)", with a link to `/settings`.
2. When no proxy is configured (the bridge knows: no forward-auth or identity
   header settings), `/auth/` could redirect to `/settings` instead of 404.
3. The upgrade note for 1.18.0 could say that an installed PWA keeps the old
   shell until the service worker updates, and that the old shell's "Sign in"
   leads nowhere on a bridge without a proxy.

Filed as #393 (operator decision 2026-10-09 19:30 EDT). To confirm the cause on a phone that an installed 1.17.x PWA
shows "Sign in" → `/auth/` against a 1.18.x bridge; this machine's phone is now
paired (device `t2e`, 17:37 EDT) and the evidence above is host-side only.
