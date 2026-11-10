# Upstream issues worth filing

Evidence write-ups for third-party defects, started 2026-08-23. **Hygiene pass
2026-11-09** (queue Carried #28 tidy): every draft below has a **Status** of
`ready-to-file`, `blocked`, or `already-filed` (URL when known). **Do not open
live issues or comments against third parties without the operator's yes**
(Carried #28; order 11 for anything outside this repo). Re-probe before filing:
URLs and open/closed state below were checked 2026-11-09.

ADE framing that ages several drafts (slim-down / Wave 6 / Pi, 2026-11-07/08):
Paseo is the only harness; herdr and Orca left this repo on 2026-10-31; Wave 6
removes `tools/acp-run` after one live cycle; Pi is the third-party client path
(omp/OpenCode/Crush archived, never fallbacks). Graft's public GitHub home is
now [trailhq/Trail-Code](https://github.com/trailhq/Trail-Code) (older
NanoNets/Graft issue URLs redirect there).

## Status ledger (2026-11-09)

| Id | Topic | Status | URL / note |
|---|---|---|---|
| 1 | graft statusline empty-but-built | already-filed (fixed) | [Trail-Code#185](https://github.com/trailhq/Trail-Code/issues/185) CLOSED; verified fixed 2026-10-24 |
| 2 | hindsight undocumented config keys | already-filed (fixed) | [hindsight#3735](https://github.com/vectorize-io/hindsight/issues/3735) CLOSED |
| — | graft `build` edits tracked `.gitignore` | ready-to-file | residual only: no switch for `ensureBuildConfigIgnored` (`/.graft/`); main case has `GRAFT_NO_GITIGNORE=1` / `--no-gitignore` |
| 3 | orca CLI structural-reorg parity | already-filed | [orca#23272](https://github.com/stablyai/orca/issues/23272) OPEN; **historical for ADE** (Orca left 2026-10-31) |
| 4 | orca worktree sleep CLI evidence comment | blocked | target [orca#22571](https://github.com/stablyai/orca/issues/22571) OPEN; ADE no longer uses Orca — do not post unless operator wants it for upstream goodwill |
| 5 | herdr idle sleep/wake Discussion | already-filed | [herdr#631 comment](https://github.com/herdrdev/herdr/discussions/631#discussioncomment-18769271); herdr left ADE 2026-10-31 |
| 6 | graft `init` bakes absolute paths | already-filed | [Trail-Code#309](https://github.com/trailhq/Trail-Code/issues/309) OPEN; comment posted 2026-10-08 |
| 7 | zcode-acp `$/` turnState + stats chunk | already-filed (fixed) | [#311](https://github.com/william0wang/zcode-acp/issues/311) [#312](https://github.com/william0wang/zcode-acp/issues/312) CLOSED; zcode retired E9 |
| 8 | ralph-orchestrator hook timeout orphans children | ready-to-file | draft complete; no duplicate found 2026-10-09 / recheck 2026-11-09 |
| 9 | Claude Code collapsed paste drops slash cmds | already-filed | [claude-code#85654](https://github.com/anthropics/claude-code/issues/85654) OPEN; herdr/`self-slash` delivery path gone here |
| 10 | herdr ACP launcher session-ref addendum | blocked (moot) | [herdr#3184](https://github.com/herdrdev/herdr/issues/3184); herdr + acp-run Wave 6 — will not happen |
| 11 | CodexBar alibabatokenplan hang | blocked | needs a `sample` of the hung process before filing |
| 12 | Collie `update --help` runs update | already-filed (fixed) | [collie#392](https://github.com/AltanS/collie/issues/392) CLOSED |
| 13 | Collie unpaired phone → `/auth/` 404 | already-filed (fixed) | [collie#393](https://github.com/AltanS/collie/issues/393) CLOSED |
| 12b | Claude Code post-compact hook dumps full command | already-filed | [claude-code#101139](https://github.com/anthropics/claude-code/issues/101139) OPEN |
| 14 | SkillOpt `max_tokens_per_night` never enforced | already-filed (fixed) | [SkillOpt#313](https://github.com/microsoft/SkillOpt/issues/313) CLOSED |
| 15 | SkillOpt harvest checkpoint not per-source | already-filed | [SkillOpt#312](https://github.com/microsoft/SkillOpt/issues/312) OPEN; local night cycle gone E10 |
| 16 | SkillOpt pluggable sources/backends | already-filed | [SkillOpt#314](https://github.com/microsoft/SkillOpt/issues/314) OPEN; local adapters gone E10 |
| — | Fastino GLiDE `model` echo / empty `state` | blocked | operator decides; no public issues channel found |
| — | siyuan-skills SiYuan 3.8 + optional `api_token` | already-filed | [siyuan-skills#3](https://github.com/zhiluop/siyuan-skills/issues/3) OPEN |
| — | graft per-prompt pack has no opt-out | already-filed | [Trail-Code#497 comment](https://github.com/trailhq/Trail-Code/issues/497#issuecomment-6257408007) |
| — | Claude Code `deniedMcpServers` as "enterprise policy" | already-filed | [claude-code#103330](https://github.com/anthropics/claude-code/issues/103330) OPEN |
| — | Paseo self-send of root-only slash cmds | ready-to-file | still relevant to handoff (`env -u PASEO_AGENT_ID`); `self-slash` gone E4 |
| P1 | paseo-continuity `@getpaseo/client` build | already-filed | [paseo-continuity#2](https://github.com/keefeere/paseo-continuity/issues/2) OPEN |
| P2 | agents-dash-list `@getpaseo/client` build | already-filed | [paseo-plugins#13](https://github.com/panrafal/paseo-plugins/issues/13) OPEN |
| P3 | fresh-worktrees Paseo `^0.11.0` pin | already-filed (fixed) | [paseo-plugins#361](https://github.com/omercnet/paseo-plugins/issues/361) CLOSED |
| P4 | paseo-telegram `<0.12.0` pin | already-filed | [paseo-telegram#1](https://github.com/Daaaaave/paseo-telegram/issues/1) OPEN; also Carried #18 |
| 17 | Paseo CLI `agent model` in-place switch | ready-to-file | Carried #9; no CLI issue found 2026-11-09; related [#7592](https://github.com/getpaseo/paseo/issues/7592) CLOSED |
| 10b | Paseo startup skill sync through symlink | already-filed | [paseo#7700](https://github.com/getpaseo/paseo/issues/7700) OPEN (+ PRs #7817, #8542; #8572) |
| 18 | zcode-acp disallowed-tools ignored in app-server | already-filed (fixed) | [zcode-acp#340](https://github.com/william0wang/zcode-acp/issues/340) CLOSED; zcode retired E9 |
| 19 | Paseo CLI terminal rename + events stream | ready-to-file | operator decides split; inspect workspace id was #7592 (CLOSED) |

Unfiled and actionable without more evidence: **8**, **17**, **19**, the Paseo
self-send slash draft, and the residual graft `/.graft/` gitignore gap. Blocked
on operator/channel/evidence: **4**, **10**, **11**, Fastino.

## 1. graft — statusline conflates "built but empty" with "not built"

**Status: already-filed (fixed)** — [Trail-Code#185](https://github.com/trailhq/Trail-Code/issues/185)
(CLOSED; was NanoNets/Graft#185). Verified fixed 2026-10-24: installed 0.25.0
and `origin/main` both render `graft · 0 nodes / 0 edges · ✓ synced` for a
built-but-empty docs-only repo — `resolveStats` in `src/claude/statusline.ts`
falls back to `wiring.json`, and "not built" shows only when the artifact is
missing. Checked in a `fix/statusline-empty-built` worktree; no edits needed.

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

**Status: already-filed (fixed)** — [hindsight#3735](https://github.com/vectorize-io/hindsight/issues/3735) (CLOSED).

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

**Status: ready-to-file** (residual only, 2026-11-09). The main `.gitignore`
edit already has `GRAFT_NO_GITIGNORE=1` / `graft build --no-gitignore` (see
root-cause fix below). What remains to raise upstream: no opt-out for
`ensureBuildConfigIgnored` writing `/.graft/`. Local ADE workaround still
applies; filing waits for operator yes.

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

**Root-cause fix (2026-10-16):** the exclude entry is not enough, because
`ensureGitignored` only looks at the tracked `.gitignore`. The writer in Claude
Code sessions is the `Stop` hook (`~/.claude/helpers/graft-hooks.cjs stop` runs
`graft build` inside a hook child; no wrapper on PATH sees it). The off switch
is `GRAFT_NO_GITIGNORE=1` (same as `graft build --no-gitignore`), and the
`env` block of `~/.claude/settings.json` is the one place that reaches hooks,
the stdio MCP server and the Bash tool alike. `bin/claude-settings-env` sets it
(idempotent, `--check` to audit; test: `tests/test_claude_settings_env.py`).
The 2026-10-10 note about setting it "on MCP defs + hooks" never persisted
there. Verified in a scratch repo: `env -u GRAFT_NO_GITIGNORE graft build`
modifies `.gitignore`; with the variable set it does not. The variable does not
cover `ensureBuildConfigIgnored` (`/.graft/`, written when a persisted build
option is saved): that one has no switch in 0.23.0.

## 3. orca — CLI parity for structural reorg (filed 2026-09-26)

**Status: already-filed** — [stablyai/orca#23272](https://github.com/stablyai/orca/issues/23272)
(OPEN as of 2026-11-09). **Historical for ADE:** Orca left this repo
2026-10-31 (Paseo-only); keep the write-up for the filed umbrella, do not
chase parity work here.

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

**Status: blocked** (2026-11-09). Target
[stablyai/orca#22571](https://github.com/stablyai/orca/issues/22571) is still
OPEN, but ADE retired Orca on 2026-10-31; posting the evidence comment is
optional goodwill only — wait for operator yes.

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

**Status: already-filed** — posted 2026-10-05 as a
[#631 comment](https://github.com/herdrdev/herdr/discussions/631#discussioncomment-18769271).
**Historical for ADE:** herdr left this repo 2026-10-31 (Paseo-only).

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

**Status: already-filed** — [Trail-Code#309](https://github.com/trailhq/Trail-Code/issues/309)
(OPEN as of 2026-11-09; was NanoNets/Graft#309). Comment posted 2026-10-08.

> **Already reported:** [Trail-Code#309](https://github.com/trailhq/Trail-Code/issues/309)
> (was [NanoNets/Graft#309](https://github.com/NanoNets/Graft/issues/309))
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

**Status: already-filed (fixed)** — [#311](https://github.com/william0wang/zcode-acp/issues/311)
and [#312](https://github.com/william0wang/zcode-acp/issues/312) CLOSED.
**Stale for ADE (Wave 6 / E9):** zcode was retired 2026-11-06; acp-run itself
goes in Wave 6, so nothing here still consumes the bridge.

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
   `_meta` / a usage notification, or behind an option. Our workaround was to drop chunks whose `messageId` starts with `turninfo_` (gone with the zcode adapter, slim-down E9, 2026-11-06).

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
4. **Both fixed upstream, 2026-10-10** (rechecked 2026-10-11): #311 closed by
   0.66.0 ("dual-emit turnState under the ACP-reserved _zcode name", 9b86e51);
   #312 closed by 0.67.0's opt-out (#313, 690172a): config
   `session.showCompletionStatus: false` or env
   `ZCODE_ACP_SHOW_COMPLETION_STATUS=0` omits the successful-turn status line.
   zcode was retired 2026-11-06 (E9; its acp-run adapter, the turninfo filter and `zcode-denylist-shim.cjs` deleted) and acp-run itself goes in Wave 6, so nothing is left to switch.

## 8. ralph-orchestrator — a timed-out lifecycle hook is killed, its children keep running (draft, 2026-10-09)

**Status: ready-to-file** (2026-11-09). Draft complete; no duplicate found on
2026-10-09 or a light recheck 2026-11-09. Filing waits for operator yes.

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

**Status: already-filed** — [claude-code#85654](https://github.com/anthropics/claude-code/issues/85654)
(OPEN as of 2026-11-09). No new issue. **ADE delivery path gone:** herdr
retired 2026-10-31 and `bin/self-slash` deleted E4 (2026-11-06); optional
evidence comment still valid if the thread goes quiet.

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

**Our workaround was** `bin/self-slash` refusing arguments over 300 characters (`SELF_SLASH_MAX`) with a `--dry-run` (commit `bfd7a83`); it was deleted 2026-11-06 (slim-down E4), and herdr was retired 2026-10-31, so this delivery path no longer exists here. Keep the
focus text in a state file and reference it from a short command.

**Evidence:** `~/.local/state/self-slash.log` lines at 03:50:37 and 03:51:12
on 2026-10-09 (pane `w2F:p8`), the 01:01:35 line for the working short send,
and the helm-auto learnings note in the ClaudeHelm scratchpad
(`helm-auto-learnings.md`, 03:52 entry).

## 10. herdr — session refs from an ACP launcher: comment-sized addendum for herdrdev/herdr#3184 (draft, 2026-10-09)

**Status: blocked (moot)** (2026-11-07, restated 2026-11-09): herdr was retired
2026-10-31 and acp-run is a one-cycle shim removed in Wave 6, so the live-pane
test and the launcher-side fix below will not happen. Do not file.

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

**Status: blocked** (2026-11-09). Draft is otherwise ready, but the write-up
still lacks a stack/`sample` of the hung process ("Not yet known: where it
blocks"). No duplicate found on a light recheck 2026-11-09. Do not file until
that evidence exists (and operator yes).

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

**Status: already-filed (fixed)** — [AltanS/collie#392](https://github.com/AltanS/collie/issues/392) (CLOSED as of 2026-11-09).

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

**Status: already-filed (fixed)** — [AltanS/collie#393](https://github.com/AltanS/collie/issues/393)
(CLOSED as of 2026-11-09); stale-shell cause labelled a hypothesis in the filing.

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

## 12b. Claude Code — post-compact hook lines print the full hook command into context (filed 2026-10-10: anthropics/claude-code#101139)

**Status: already-filed** — [claude-code#101139](https://github.com/anthropics/claude-code/issues/101139)
(OPEN as of 2026-11-09). (Renumbered 12→12b in the ledger to avoid the
duplicate "12" with Collie `update --help`.)

Found because Orca's ~3 KB `PostCompact` wrapper shows after every `/compact`
(Orca side: stablyai/orca#25209 / PR #25211; Orca left ADE 2026-10-31 — the
Claude Code defect remains). Filed text:

### What happens

After every `/compact`, Claude Code prints one line per `PreCompact` / `PostCompact` hook:

```
PreCompact [<full command>] completed successfully
PostCompact [<full command>] completed successfully: <output>
```

The bracketed part is the hook's **entire `command` string**. The same text is also stored in the transcript as `local-command-stdout`, so the model reads it as context right after the compaction that was meant to free context.

This gets expensive when the command is long. Orca (stablyai/orca) registers a ~3 KB portable shell wrapper for `PostCompact`, with Windows Git Bash, PowerShell, missing-`HOME` and missing-script branches, so every `/compact` puts about 1k tokens of shell code back into context. Orca is shortening its own command (stablyai/orca#25209, PR #25211), but any tool that installs a long hook command hits the same problem.

### Repro

1. Add a `PostCompact` hook whose `command` is long (several hundred characters or more).
2. Run `/compact`.
3. The full command is printed after compaction, and the next turn's context contains it.

Observed on Claude Code 2.1.296, macOS. The display name comes from the function that renders a hook (`type === "command"` → `command`, joined with `args`). It never uses the hook's `statusMessage`, although `statusMessage` is already accepted and shown in the spinner while the hook runs.

### Request

1. In the post-compact lines, show `statusMessage` when the hook has one, and otherwise truncate the command (for example to its first ~80 characters plus `…`).
2. Optionally, leave successful hook lines with empty or `{}` output out of the model-visible context entirely. They carry no information for the model.

### Searched first

I searched anthropics/claude-code issues for "PostCompact", "PreCompact completed successfully", "hook command shown transcript" and "alwaysLoad". The nearest threads are #89622 (PostCompact stdin JSON escaping), #91910 (compact hooks firing for sub-agent compaction) and #101070 (an "idle" trigger value). None covers how the hook is displayed or what it costs in context.

## 14. SkillOpt — `max_tokens_per_night` is documented and defaulted but never enforced (filed 2026-10-12: microsoft/SkillOpt#313)

**Status: already-filed (fixed)** — [SkillOpt#313](https://github.com/microsoft/SkillOpt/issues/313)
(CLOSED as of 2026-11-09). Local nightly SkillOpt cycle deleted E10 (2026-11-07).

**Repo:** microsoft/SkillOpt, `skillopt_sleep`, main at
343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c (installed with `uv tool install`).

### What happens

`skillopt_sleep/config.py` defines `"max_tokens_per_night": 400_000` under
"budgets", and `skillopt_sleep/budget.py` has a `Budget` controller that
"stops cleanly when exhausted". Nothing connects them: `rg max_tokens_per_night`
over the package finds only the default, and `Budget(` is never constructed.
A night's spend is bounded only by `max_tasks_per_night`, `edit_budget` and
the number of fan-out skill groups.

### Request

1. Wire `max_tokens_per_night` into the cycle through `Budget` (stop before
   the next model call once spent, and say so in `report.md`), or
2. remove the key from `DEFAULTS` and the docs so users do not rely on it.

### Searched first

Issues and PRs for "max_tokens_per_night", "budget", "token budget": only
unrelated threads (155, 130, 132), plus one line in the closed multi-topic
Codex feedback issue #57 (closed as completed for its other points). Re-searched
before filing (open and closed, issues and PRs, 12 terms); filed as
https://github.com/microsoft/SkillOpt/issues/313, citing #57.

## 15. SkillOpt — the harvest checkpoint is keyed by project, not by (project, source) (filed 2026-10-12: microsoft/SkillOpt#312)

**Status: already-filed** — [SkillOpt#312](https://github.com/microsoft/SkillOpt/issues/312)
(OPEN as of 2026-11-09). Local `bin/skillopt-night` workaround deleted E10.

**Repo:** microsoft/SkillOpt, main at 343db229.

### What happens

`cycle.py` reads `state.last_harvest_for(project)` and writes
`state.set_last_harvest(project, started)` after every stateful run, whatever
`transcript_source` was. Running one night per source for the same project
(`--source claude`, then `--source codex`, ...) therefore gives every source
after the first a window starting at the first run's start time: their older
unseen sessions are skipped forever. Each source is also a separate store with
its own timestamps, so one shared cursor cannot be right for all of them.

### Repro

1. `skillopt-sleep run --project P --scope all --source claude --backend mock`
2. `skillopt-sleep run --project P --scope all --source codex --backend mock`:
   `harvest done: sessions=` counts only Codex sessions that ended after step 1
   started, although none were ever harvested.

### Request

Key `last_harvest` by `f"{project}::{source}"` (reading the bare project key as
a fallback for existing state), or accept several `--source` values in one run.
Workaround here was `bin/skillopt-night` swapping a per-source cursor into `state.json` before each run (deleted 2026-11-07 with the nightly SkillOpt cycle, slim-down E10).

### Searched first

Issues and PRs for "checkpoint", "last_harvest", "per-source", "source": none
covers it. Re-searched before filing (adding "harvest checkpoint", "multiple
sources", "since_iso", "per source"): none. Filed with a measured mock
repro in isolated state (codex dry-run 60 sessions, a cursor run, the same
dry-run 0) as https://github.com/microsoft/SkillOpt/issues/312.
Evidence comments, 2026-10-12, both threads subscribed:
https://github.com/microsoft/SkillOpt/pull/282#issuecomment-6132512292 (Codex
CLI rollout layout, our shim) and
https://github.com/microsoft/SkillOpt/issues/286#issuecomment-6132512856
(replay provenance applies to CLI rollouts too).

## 16. SkillOpt — make transcript sources and backends pluggable (filed 2026-10-12: microsoft/SkillOpt#314)

**Status: already-filed** — [SkillOpt#314](https://github.com/microsoft/SkillOpt/issues/314)
(OPEN as of 2026-11-09). Local adapters (`bin/skillopt_sources.py`,
`bin/skillopt-night`) deleted E10; Pi-only path does not restore them.

**Repo:** microsoft/SkillOpt, `skillopt_sleep`, main at 343db229.

### Proposed issue text

> **Title:** skillopt-sleep: pluggable transcript sources and backends (entry points)
>
> `harvest_sources.harvest_for_config` and `backend.get_backend` are fixed
> if-chains. Every new harness needs a PR to core (open: #225/#266 DeepSeek
> Harness, #97 VS Code Copilot, #282 Codex CLI rollouts), and `get_backend`
> silently returns `MockBackend` for an unknown name, so a typo or an
> out-of-tree backend produces a 0.0 -> 0.0 night instead of an error.
>
> Proposal:
>
> 1. Two entry-point groups, `skillopt_sleep.sources` (name ->
>    `harvest(cfg, *, since_iso, limit, scope, invoked_project) -> list[SessionDigest]`)
>    and `skillopt_sleep.backends` (name -> `factory(cfg) -> Backend`), consulted
>    after the built-ins. `--source` and `--backend` accept any registered name.
> 2. A `--source-module pkg.mod:func` / `--backend-module pkg.mod:Class` escape
>    hatch for unpackaged adapters.
> 3. `get_backend` raises on an unknown name instead of returning mock.
> 4. Key the harvest checkpoint by `(project, source)` (see the per-source
>    checkpoint report) so several sources can run per project per night.
> 5. Export `_is_headless_replay`, `_is_agent_session`, `_is_meta_prompt`,
>    `_detect_feedback` and `redact_secrets` as a small public helper API so
>    external sources apply the same filters and redaction.
>
> Context: on one machine we run nightly cycles over claude, codex, cursor,
> opencode and copilot_cli natively, plus three out-of-tree adapters (zcode, an
> OpenCode fork whose DB lacks the `agent`/`metadata` columns; Antigravity, whose
> per-conversation SQLite stores protobuf steps; Crush's per-project
> `crush.db`). Today they reach the engine only by pre-writing `digests.json`
> into the handoff dir, and every model call goes through the handoff backend
> because no external backend can be registered.

### Searched first (2026-10-12)

Issues and PRs for "pluggable", "plugin source", "entry point", "custom
transcript", "transcript source", "custom backend", "backend registry",
"get_backend": no proposal for either. Open PRs that add one source or backend
each: [#153](https://github.com/microsoft/SkillOpt/pull/153) (Antigravity
harvest, reads only `~/.gemini/antigravity/conversations`; our adapter also
reads the `antigravity-cli` and `antigravity-acp` dirs) and
[#114](https://github.com/microsoft/SkillOpt/pull/114) (Hermes Agent as backend
and source; found by the 2026-10-12 re-search on "since_iso"). Related single-source work:
[#225](https://github.com/microsoft/SkillOpt/issues/225) /
[#266](https://github.com/microsoft/SkillOpt/pull/266) (DeepSeek Harness),
[#97](https://github.com/microsoft/SkillOpt/issues/97) (VS Code Copilot),
[#282](https://github.com/microsoft/SkillOpt/pull/282) (Codex CLI rollouts),
[#286](https://github.com/microsoft/SkillOpt/issues/286) /
[#287](https://github.com/microsoft/SkillOpt/pull/287) (exclude Codex replay
sessions), [#247](https://github.com/microsoft/SkillOpt/issues/247) /
[#280](https://github.com/microsoft/SkillOpt/pull/280) (`revert`).
Here: bin/skillopt_sources.py and bin/skillopt-night were the working adapters the PR would generalise (both deleted 2026-11-07, E10; they are at tag `pre-slim-2026-11-06`). Operator approved filing; re-searched first
(adding "entry_points", "external harvester", "third-party source", "register
source"; PR #153's "seam" is one more if-branch, not a registry). Filed with an
offer to send the PR: https://github.com/microsoft/SkillOpt/issues/314.

## Fastino GLiDE: response `model` is `glide_v2`, docs say `glide` (not filed)

**Status: blocked** (2026-11-09). Still not filed: no public issues repo found;
channel unknown (support or Discord). Operator decides whether/where to file.
Local skill: `.claude/skills/fastino-glide` (still in-tree).

**Seen:** 2026-10-11/12 on `POST https://api.fastino.ai/v1/systemone` with `"model": "fastino/glide"`.

1. The response `model` field is `glide_v2` on every call (noul, choice and score). The contract page
   (https://docs.fastino.ai/inference/systemone, "Expect model: \"glide\" in the response") and
   the agent skill (https://docs.fastino.ai/.well-known/agent-skills/fastino-glide/SKILL.md, "model
   echoes back with the `fastino/` prefix stripped") both say `glide`. Anything that asserts the
   documented echo, as the TypeSafe-migration prompt tells you to, fails.
2. An empty `state` (`""`) with a valid question returned 200 with a probability, though the docs
   describe `state` as required and non-empty for the migration.

**Searched first (2026-10-12):** web search "Fastino GLiDE systemone response model glide_v2 docs
mismatch issue" and Firecrawl's developer index (GitHub issues/PRs) for "fastino GLiDE systemone
state required empty github issue". Found no issue or thread about either point. Nearest results:
the docs pages themselves, a press release, benchlm.ai and marktechpost write-ups, and a LiteLLM PR
(berriai/litellm#45846) adding a `systemone` call type, which does not mention the model field.
Fastino has no public docs repo that turned up, so the channel is unknown (support or Discord).
**Not filed:** operator decides.

## 3. zhiluop/siyuan-skills — `import_article.py` breaks on SiYuan 3.8 and without an `api_token`

**Status: already-filed** — [siyuan-skills#3](https://github.com/zhiluop/siyuan-skills/issues/3)
(OPEN as of 2026-11-09).

**Repo:** https://github.com/zhiluop/siyuan-skills (commit 2984f56, 2026-04-28).
**Seen against:** SiYuan 3.8.6 (kernel), 2026-10-12, a live create-and-delete test.

**1. Crash on `ensure_notebook_exists`.** `/api/notebook/lsNotebooks` returns
`{"notebooks": [...]}` in 3.8.6. `_request` hands back that dict and the loop
`for nb in notebooks: nb.get('name')` iterates its keys: `AttributeError: 'str'
object has no attribute 'get'` (`import_article.py` line 103). Fix: unwrap
`notebooks.get('notebooks')` when it is a dict (kept as a local patch here).

**2. `KeyError: 'api_token'`.** `_request` and `verify_document` index
`self.config['api_token']` (lines 57 and 149) although `insert_image.py` uses
`config.get("api_token", "")`. A kernel with no access auth code needs no token, so
the config key should be optional. Workaround: `"api_token": ""` in `siyuan.json`.

**Minor:** `verify_document` right after `create_document` returns 0 because the SQL
index lags by seconds; a short retry would make it meaningful.

**Searched first (2026-10-12):** `gh issue list -R zhiluop/siyuan-skills --state all
--search` for `lsNotebooks`, `api_token`, `notebooks`, `KeyError`, `3.8`, and the PR
list. Found one unrelated closed question ("docker的siyuan如何配置？") and one open PR
(#2, English README). Nothing on either defect. **Filed 2026-10-12:**
[zhiluop/siyuan-skills#3](https://github.com/zhiluop/siyuan-skills/issues/3).

## graft — the per-prompt pack has no opt-out, and `graft init` re-adds it (posted 2026-10-18: https://github.com/trailhq/Trail-Code/issues/497#issuecomment-6257408007)

**Status: already-filed** — comment on
[Trail-Code#497](https://github.com/trailhq/Trail-Code/issues/497#issuecomment-6257408007)
(parent OPEN as of 2026-11-09).

**Where:** a comment on https://github.com/trailhq/Trail-Code/issues/497 ("graft init wires Claude Code hooks
at user and project level, so every hook runs twice"). Searched 2026-10-18 in `trailhq/Trail-Code`:
"prompt hook", "UserPromptSubmit", "init hooks settings", "project settings.json". Nearest threads:
#628 (opt-outs for credit/speed lines and the Stop-hook prompt), #500 (prompt hook fires on
`<task-notification>` prompts), #635 (prompt-hook child outlives its timeout). None asks for an opt-out of
the per-prompt pack itself.

**Draft:**

> One more consequence of the project-level wiring: the `UserPromptSubmit` `graft-hooks.cjs prompt` hook
> has no opt-out, so removing it doesn't stick. We removed it from `~/.claude/settings.json` on
> 2026-10-10 and again on 2026-10-18. Both times a later `graft init` (also `reconcileWiring()` after a
> version bump) wrote it back. The second time it came back in the project's `.claude/settings.json`,
> where it bypasses any wrapper the user puts around the user-level hooks.
>
> What it costs: on our sample prompt the pack injected ~120 tokens of `additionalContext`, and two of its
> three hits were unrelated to the prompt. That text stays in the conversation history and is re-read
> on every later request. Over a week of Claude Code transcripts on this machine, the fixed per-session
> preamble was ~17% of list-price cost, so per-prompt injections add up.
>
> Request: an opt-out that `init` and upkeep respect, e.g. `GRAFT_PROMPT_HOOK=0` or a `hooks.prompt:
> false` config key, with `init` not writing the prompt hook when it is set. Writing hooks at one level
> only, as #497 asks, would also stop the project copy from bypassing user-level wrappers.
>
> Workaround we run: a wrapper that exits 0 on the `prompt` event, plus a session-start step that strips
> `graft-hooks.cjs` entries from a project's `.claude/settings.json` when the user level already has
> them.

**Status:** posted 2026-10-18 with djbclark's yes: https://github.com/trailhq/Trail-Code/issues/497#issuecomment-6257408007

## Claude Code — user-level `deniedMcpServers` reported as "enterprise policy" (filed 2026-10-18: https://github.com/anthropics/claude-code/issues/103330)

**Status: already-filed** — [claude-code#103330](https://github.com/anthropics/claude-code/issues/103330)
(OPEN as of 2026-11-09).

Searched 2026-10-18 in `anthropics/claude-code` for "blocked by enterprise policy", "deniedMcpServers
enterprise policy" and "deniedMcpServers user settings". Nearest threads: #96408 (remote managed
`allowedMcpServers` not enforced when the fetch is slow) and #94803 (plugin MCP servers ignored under
`allowManagedMcpServersOnly`), both about real managed policy, plus #20412 (closed; claude.ai servers
auto-injected). None covers the label.

**Draft title:** `deniedMcpServers` in user settings is reported as "blocked by enterprise policy"

> **Version:** 2.1.303, macOS. No managed settings and no organization MCP policy.
>
> **Steps:** add `"deniedMcpServers": [{"serverName": "claude.ai Firecrawl"}]` to `~/.claude/settings.json`,
> then run `claude -p "/context"`, or start a session.
>
> **Observed:** stderr prints `Warning: claude.ai MCP servers blocked by enterprise policy: claude.ai
> Firecrawl, ...`. Mid-session, the system context tells the model the servers are "blocked by the
> organization's managed policy ... an administrator manages this setting", and tells it to say so to the
> user.
>
> **Expected:** the message names the source the deny came from: "denied in your user settings
> (`~/.claude/settings.json` deniedMcpServers)". "Enterprise" or "managed policy" should only appear
> when the entry comes from managed settings.
>
> **Why it matters:** the user configured this themselves, but the model is told to send them to an
> administrator. An agent auditing the setup on this machine took the user's own deny list for an org
> policy until it checked the settings files.

**Status:** filed 2026-10-18 with djbclark's yes: https://github.com/anthropics/claude-code/issues/103330

## Paseo — a self-send of a root-only slash command is enveloped and reaches Claude as text (not filed, 2026-10-19)

**Status: ready-to-file** (2026-11-09). Still relevant under Paseo-only / handoff
(`skills/handoff` starts successors with `env -u PASEO_AGENT_ID …`); `bin/self-slash`
is gone (E4) but the daemon behaviour is not. No duplicate found on a light
recheck 2026-11-09. Filing waits for operator yes.

**Repo:** getpaseo/paseo. **Version seen:** Paseo 0.12.0 (desktop, 2026-10-19), Claude provider.

**What happens:** from inside a Claude agent (`PASEO_AGENT_ID` set), `paseo send <own id> "/compact"`
is delivered as agent-originated text: the timeline shows `[Message received] <agent title>` then
`/compact`, and the model answers "I can't run /compact". The same send with `PASEO_AGENT_ID` unset
runs the built-in (`[User] /compact` → `[Compacted]`, a `compact_boundary` record in the Claude
session file). `/clear` behaves the same way and rebinds the agent to a fresh Claude session.

**Expected:** `resolveSlashCommandInvocation` treats clear/compact/context/usage as root-only
built-ins; a send from an agent should either run them out of band (PR #7072, merged as #7169 on
2026-10-16, says it restores exactly that for agent-to-agent sends) or refuse, never hand them to the
model as prose. A self-send was the case `bin/self-slash` needed, so it stripped `PASEO_AGENT_ID` first (deleted 2026-11-06, E4; successors now start with `env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD paseo run …`, `skills/handoff`).

**Evidence:** scratch Haiku agent fe96fd29, timeline and `~/.claude/projects/.../585afa3c-*.jsonl`
(one `compact_boundary`); `bin/self-slash` Paseo backend, verified the same day.

## Paseo plugins that fail to install on Paseo 0.12.0 (four filed 2026-10-19)

**Status (group):** all four **already-filed** (rechecked 2026-11-09: P1 OPEN, P2 OPEN,
P3 CLOSED, P4 OPEN). P4 also blocks Carried #18 (Telegram as phone surface).

Found in the 2026-10-19 plugin trial (`/tmp/paseo-install.log`, `/tmp/paseo-install2.log`; see also commit 7e92320). Daemon and desktop 0.12.0, macOS; installed with `paseo plugin add <registry id>` and
`paseo plugin install <npm:|git: source>`. Existing issues searched first (each plugin repo, open and closed, with
"0.12", "requires Paseo", "@getpaseo/client"; and `getpaseo/paseo` for "@getpaseo/client", "0.12.0 plugin requires",
"Could not resolve type dependency", "plugin install"): none on any of the four. The two build failures declare
`@getpaseo/client` only under `devDependencies` and have no `build` step, which getpaseo/paseo#5405 and #4957 (both
closed) call deliberate and answer with `"build": [["npm", "ci"]]`; so they went to the plugin repos, not to
getpaseo/paseo (#7145 and #6257 are open but about other packages' type imports).

### 1. keefeere/paseo-continuity — `@getpaseo/client` unresolved in `server/failover.ts` (filed 2026-10-19: https://github.com/keefeere/paseo-continuity/issues/2)

**Status: already-filed** — https://github.com/keefeere/paseo-continuity/issues/2 (OPEN as of 2026-11-09).

**Draft title:** Install fails on Paseo 0.12.0: Could not resolve type dependency "@getpaseo/client" (server/failover.ts)

> **Versions:** registry `keefeere/continuity` and npm `paseo-continuity` 0.2.1; `paseo-plugin.json` requires `>=0.10.1`.
> **Commands:** `paseo plugin add keefeere/continuity`; `paseo plugin install npm:paseo-continuity`.
>
> ```
> Error: Request failed: Build failed with 1 error:
> .../esbuild/lib/main.js:1267:21: ERROR: [plugin: paseo-plugin-server-runtime-boundary] Could not resolve type dependency "@getpaseo/client" imported by /Users/djbclark/.paseo/plugins/paseo-continuity/<id>/node_modules/paseo-continuity/server/failover.ts requestType=plugin.source.install.
> ```
>
> `server/failover.ts:1` is `import type { PaseoApi } from "@getpaseo/client";`; `package.json` has the package (0.10.1) only in
> `devDependencies`; `paseo-plugin.json` has no `build`. See getpaseo/paseo#5405 and #4957.

**Status:** filed 2026-10-19: https://github.com/keefeere/paseo-continuity/issues/2

### 2. panrafal/paseo-plugins — agents-dash-list: `@getpaseo/client` unresolved in `client/dash-surface.tsx` (filed 2026-10-19: https://github.com/panrafal/paseo-plugins/issues/13)

**Status: already-filed** — https://github.com/panrafal/paseo-plugins/issues/13 (OPEN as of 2026-11-09).

**Draft title:** agents-dash-list: install fails on Paseo 0.12.0: Could not resolve type dependency "@getpaseo/client" (client/dash-surface.tsx)

> **Versions:** git source (registry `panrafal/agents-dash-list`, no npm artifact), plugin 0.1.0 on `main`;
> `paseo-plugin.json` requires `>=0.7.2-0`.
> **Commands:** `paseo plugin add panrafal/agents-dash-list`; `paseo plugin install git:panrafal/paseo-plugins:agents-dash-list`.
>
> ```
> Error: Request failed: Build failed with 1 error:
> .../esbuild/lib/main.js:1267:21: ERROR: [plugin: paseo-plugin-client-runtime-boundary] Could not resolve type dependency "@getpaseo/client" imported by /Users/djbclark/.paseo/plugins/agents-dash-list/<id>/checkout/agents-dash-list/client/dash-surface.tsx requestType=plugin.source.install.
> ```
>
> `client/dash-surface.tsx:1` imports types from `@getpaseo/client`; `package.json` has it (`^0.7.1`) only in
> `devDependencies`; `paseo-plugin.json` has no `build`. See getpaseo/paseo#5405 and #4957.

**Status:** filed 2026-10-19: https://github.com/panrafal/paseo-plugins/issues/13 (this repo's #7 is a similar
"chat-resume build fails on paseo 0.9", a different plugin; not linked).

### 3. omercnet/paseo-plugins — fresh-worktrees stable 3.0.0 pinned `^0.11.0` (filed 2026-10-19: https://github.com/omercnet/paseo-plugins/issues/361)

**Status: already-filed (fixed)** — https://github.com/omercnet/paseo-plugins/issues/361 (CLOSED as of 2026-11-09).

**Draft title:** fresh-worktrees: stable 3.0.0 and registry install refused on Paseo 0.12.0 (requires ^0.11.0); next tag already allows ^0.12.0

> **Versions:** registry `omercnet/fresh-worktrees` and npm `@omercnet/paseo-fresh-worktrees` `latest` 3.0.0
> (2026-10-11), `requirements.paseo` `^0.11.0`. `next` 3.0.0-next.266.1 (2026-10-18) and `main` (7dbbe2a1) say
> `^0.11.0 || ^0.12.0`.
> **Commands:** `paseo plugin add omercnet/fresh-worktrees`; `paseo plugin install npm:@omercnet/paseo-fresh-worktrees`.
>
> ```
> Error: Request failed: Plugin "fresh-worktrees" requires Paseo ^0.11.0. Your daemon is 0.12.0. Use a compatible plugin version or update the daemon. requestType=plugin.source.install.request code=handler_error
> ```
>
> **Request:** publish a stable release with the `^0.12.0` range. A workaround until then:
> `paseo plugin install npm:@omercnet/paseo-fresh-worktrees@next` (not tried).

**Status:** filed 2026-10-19: https://github.com/omercnet/paseo-plugins/issues/361

### 4. Daaaaave/paseo-telegram — pinned `>=0.11.2 <0.12.0` (filed 2026-10-19: https://github.com/Daaaaave/paseo-telegram/issues/1)

**Status: already-filed** — https://github.com/Daaaaave/paseo-telegram/issues/1
(OPEN as of 2026-11-09). Also Carried #18 (phone surface blocked on a compatible release).

**Draft title:** Install refused on Paseo 0.12.0: requires >=0.11.2 <0.12.0

> **Versions:** registry `daaaaave/telegram` and npm `paseo-telegram` 0.2.0; `main` (pushed 2026-10-18) has the same range
> and pins `@getpaseo/client`/`@getpaseo/plugin` 0.11.2.
> **Command:** `paseo plugin add daaaaave/telegram`.
>
> ```
> Error: Request failed: Plugin "telegram" requires Paseo >=0.11.2 <0.12.0. Your daemon is 0.12.0. Use a compatible plugin version or update the daemon. requestType=plugin.source.install.request code=handler_error
> ```
>
> **Request:** a release declaring Paseo 0.12.x support, or a note on whether 0.12 is expected to work.

**Status:** filed 2026-10-19: https://github.com/Daaaaave/paseo-telegram/issues/1
(**Re-probe 2026-11-10:** npm `paseo-telegram` **0.2.3** sets `requirements.paseo` to `*` — the install-time
version gate that blocked 0.2.0 is gone in the published package. Issue #1 remains OPEN with no comments.
`@getpaseo/client` is still pinned at 0.11.2 in the package; live install / `hermes-ping` re-point wait for
operator yes. See `docs/history/paseo-telegram-reprobe-2026-11-10.md`.)

## 17. Paseo — CLI: change an existing agent's model (`paseo agent model <id> <provider/model>`) (filed 2026-11-09)

**Status: ready-to-file** (2026-11-09). Still the ask behind Carried #9
(`bin/paseo-set-model` / `route_agent.py substrate --apply`). Light duplicate
search 2026-11-09 found no CLI issue for in-place `agent model`. Related
[#7592](https://github.com/getpaseo/paseo/issues/7592) (inspect omits workspace
id) is **CLOSED** (2026-10-23) — drop that half from any new filing. Filing
waits for operator yes.

**Repo:** getpaseo/paseo, Paseo 0.12.0 (`/Applications/Paseo.app`, bundle read with `rg -a`; no live call made).

**Status:** filed 2026-11-09: https://github.com/getpaseo/paseo/issues/9245. Duplicate-searched 2026-11-09 on `getpaseo/paseo` (`paseo agent model`, `agent model`, `in-place model`, `agent update --model`, `feat(cli) model`, open `CLI` / `model` lists): no prior open issue asked for a CLI to change an existing agent's model in place. Cloud Agent `gh` could `issue create` on that repo (edit/close remain denied); accidental probe https://github.com/getpaseo/paseo/issues/9244 (title `test`) should be closed by the operator. Tracked here as **Carried #9** in `docs/queue.md` (do not edit that file from this PR; #358 owns queue edits).

### What happens

The daemon can switch a running agent's model (issues #1735, #5279 and #4725 describe switching it mid-session
from the UI), but no CLI command reaches it. The wiring is all there:

1. WebSocket request `set_agent_model_request {agentId, modelId: string | null, requestId}`
   (`SetAgentModelRequestMessageSchema`), answered by `set_agent_model_response`;
2. the daemon client method `setAgentModel(agentId, modelId)`;
3. `agentConfigSession.handleSetAgentModelRequest` calling `operations.setModel(agentId, modelId)`, which
   calls the provider session's `setModel` (for Claude, the SDK control request `set_model`), then updates
   `agent.config.model` and `runtimeInfo.model` and persists.

The CLI has the same shape for mode and thinking and nothing for model: `paseo agent mode <id> [mode]` calls
`client.setAgentMode`; `paseo agent update <id>` takes `--name`, `--thinking <id>` and `--label`, not `--model`;
`paseo agent send --provider/--model` and `paseo schedule update --model` describe a *new-agent target*, not an
existing agent. `paseo run` always creates a new agent.

Use case (djbclark's ade, 2026-10-23): an orchestrating session on an expensive model (Fable) must downshift to
Opus 5.5 high at a handoff boundary **without losing its session**: its Paseo agent id, name, labels,
subagent links and timeline. Today the only CLI route is a new top-level agent plus an archive of the old
one (`paseo run ... --workspace <id>` run with `PASEO_AGENT_ID` unset, then `paseo agent archive`), which
drops the agent identity and its subagent children.

### Request

1. `paseo agent model <id> [model]` (and `--list`, like `agent mode --list`, from `paseo provider models <provider>`
   filtered to the agent's provider), calling `client.setAgentModel`; `provider/model` accepted when the provider
   equals the agent's (a cross-provider switch is refused with a clear error, as the daemon's `setModel` is per
   session); or, smaller, `paseo agent update <id> --model <id>`, beside the existing `--thinking`.
2. Related, same area: `paseo agent inspect` omits the workspace id (#7592), which `paseo run --workspace` needs from
   inside an agent; and `paseo run` passes the calling agent's id to the daemon whenever `PASEO_AGENT_ID` is set,
   even with `--workspace`, so the new agent is a subagent (the caller has to `env -u PASEO_AGENT_ID`).

**ade-side workaround (2026-10-23):** `bin/paseo-set-model` (`set <agent> <model>`, `list --json`) calls the daemon's
`set_agent_model_request` through the bundled CLI's own client, run in Paseo's Electron node; it keeps the agent id and is
what the fleet governor (deleted 2026-11-07, slim-down E7) used to move live agents between models.

### Searched first

`gh issue list --repo getpaseo/paseo --state all --limit 50 --search` for "model", "switch model", "change model" and
"set model" (4 searches, 125 distinct issues, 2026-10-23), then "agent model", "cli model" and "paseo agent update":
no issue asks for a CLI to change an existing agent's model. Related, none a duplicate: #5561 (a provider-side model
switch is lost on reload: `config.model` stays at the creation-time value), #1735 and #5279 (thinking options and
features stale after a mid-session model switch in the UI), #4725 (closed: resuming a Codex session keeps the
previous model), #7053 and #7139 (an ACP agent stays on the provider default when the model cannot be applied),
#7592 (inspect omits the workspace id), #5705 (daemon-spawned Claude agents run the SDK-bundled Claude Code 2.1.258,
so `claude-opus-5-5` fails with a 400 version gate: relevant to anyone downshifting to Opus 5.5 through a new agent).

### Effort estimates (2026-10-23)

1. **`paseo agent model` in Paseo**: about 2 to 3 hours for someone who knows the repo, 4 to 6 for a first
   contribution. A new `packages/cli/src/commands/agent/model.ts` is a copy of `mode.ts` (~70 lines: fetch the
   agent, check the provider, `setAgentModel`, a result schema, the `--list` branch), a two-line registration in
   `agent/index.ts`, a CLI test through the existing isolated-daemon harness (set the model, `inspect` shows it,
   unknown model and cross-provider errors), and CLI docs. No daemon, protocol or UI change: the RPC exists. The
   open question is whether `setModel` on a *running* turn should be refused or queued (the UI picker's current
   behaviour decides it).
2. **The ade-side workaround** (`bin/self-slash --finish --successor`, handoff Step 9, the context hook, 24 tests):
   built in about 15 minutes of wall-clock agent time on 2026-10-23, research of the Paseo CLI source included. It existed only because the CLI lacks this command (deleted 2026-11-06, E4, with its tests and the self-slash code in `context_size_nudge.py`; the handoff skill's `paseo run` successor is what remains), and it still cannot keep the agent id, labels or subagent links.

## 10b. Paseo — the start-up skill sync writes through a symlinked skill directory (filed 2026-10-23)

**Status: already-filed** — https://github.com/getpaseo/paseo/issues/7700
(OPEN as of 2026-11-09). (Renumbered 10→10b in the ledger to avoid the
duplicate "10" with the herdr ACP addendum.)

**Filed:** https://github.com/getpaseo/paseo/issues/7700 (searched first: nothing on this; #4823 and #5440 are
about duplicate Codex entries and non-default homes).

`orchestrationSkills.autoUpdate()` runs at every daemon start and syncs the six bundled skills into
`~/.claude/skills/<n>` and `~/.agents/skills/<n>`. `assertManagedPathsStayInsideSkill` lstat-checks every segment
below the skill dir but never the skill dir itself, so a symlinked skill dir is written through into the user's own
checkout; `syncDirectoryFiles` also updates without comparing the on-disk hash with the manifest (deletes do).
Reproduced with the shipped 0.13.0-beta.1 `syncSkills` in a throwaway directory. Our workaround from 2026-11-02 was the `ade-` prefix on the vendored skills; the six `skills/ade-paseo*` were deleted 2026-11-06 (Wave 3b, R2-2) and Paseo's own shipped skills replace them through the skill-selection switch (docs/skill-everywhere.md section 3a, operator batch); the empty skill selection alone did not hold.
Addendum 2026-10-24: the setting is per daemon home, while every daemon syncs into the one real `~/.agents/skills`
and `~/.claude/skills`. A second daemon with another home (Paseo's own `scripts/dev-daemon.sh`, home
`.dev/paseo-home`, no selection) rewrote the symlinked skills at 09:26:49 and 10:05:46 EDT. Suggest to upstream: the
sync skips a skill dir that is a symlink, or dev homes default to no skill sync. Posted on #7700 2026-10-24: https://github.com/getpaseo/paseo/issues/7700#issuecomment-6386655547.
Draft PR opened 2026-10-24 (refs #7700, not closes): https://github.com/getpaseo/paseo/pull/7817, branch `fix/dev-home-skill-selection` on the fork, one commit b2836f723 (`scripts/dev-home.sh` seeds the skill selection in dev homes, new `scripts/dev-home.test.mjs`: 3 of 4 tests fail on upstream main, all pass on the fix). macOS arm64 only; the end-to-end dev-daemon run was posted as a PR comment and the PR was marked ready for review on djbclark's instruction (2026-10-24, reported by the workspace-colors session).
Addendum 2026-11-02: overwritten again 2026-11-01 21:33:38 by the installed Paseo 0.15.0-beta.1 bundle (manifest
`SKILL.md` hash `f52ce024…` equals the app's bundled `paseo-advisor/SKILL.md`). Fable consult (`frontier`,
2026-11-02): the smallest fix that keeps upstream's linked-update test is to let startup maintenance
(`autoUpdateInstalledSkills`) skip skill dirs that link outside Paseo's own skill roots, leaving explicit
install/update/save unchanged. Sent as https://github.com/getpaseo/paseo/pull/8542 (fork branch
`fix/startup-skill-sync-skips-linked-checkouts`, refs #7700; regression test fails on main, passes on the fix;
evidence comment https://github.com/getpaseo/paseo/issues/7700#issuecomment-6569914366). Its QA notes that
`controller.test.ts` "renames an untouched staged deletion back with its inode and mode" fails on upstream main under
Node 26 (`livePaths.map(lstat)` passes the index as options); upstream CI uses Node 22. Filed 2026-11-02:
https://github.com/getpaseo/paseo/issues/8572.


## 18. zcode-acp — `ZCODE_DISALLOWED_TOOLS` / `--disallowed-tools` never reaches the backend session (filed 2026-10-25: https://github.com/william0wang/zcode-acp/issues/340)

**Status: already-filed (fixed)** — [zcode-acp#340](https://github.com/william0wang/zcode-acp/issues/340)
(CLOSED as of 2026-11-09). **Stale for ADE (E9 / Wave 6):** zcode retired
2026-11-06; the `zcode-denylist-shim.cjs` workaround and acp-run adapter are
gone / going with Wave 6.

Repo: william0wang/zcode-acp (npm `zcode-acp-server`), wrapping `zcode app-server --stdio` (zcode-app-cli
`vendor/zcode.cjs`). `backendArgs()` (`dist/backend/resolve.js`) passes the merged `ZCODE_DISALLOWED_TOOLS` and the
default `Cron*` list to the backend as `--disallowed-tools`, but the backend's protocol-server path (`app-server`)
does not read that flag: it is parsed for the one-shot prompt/TUI path only, and `session/create` in
`dist/handlers/session.js` (`createParams`: workspace, mode, mcpServers, workflow flag) carries no `toolDenylist`.
Both the backend's `session/create` and `session/resume` schemas accept `toolDenylist` and `toolAllowlist`
(`session/send` accepts only `toolDenylist`). Observed 2026-10-24 with `ZCODE_DISALLOWED_TOOLS="Bash Write Edit ..."`
and `ZCODE_ACP_MODE=plan`: asked for its tool list the model named Bash, Edit, Write and the default-disallowed
CronCreate/List/Update/Delete, and ran `ls` through Bash without a permission request (plan mode lets read-only shell
through). Also `permission.disallowedTools` in the CLI settings file is only a permission rule, not a registry
removal. Suggest: send `toolDenylist` (and `toolAllowlist`) from the env in `session/create` and `session/resume`.
Our workaround: `tools/acp-run/zcode-denylist-shim.cjs`, a stdio shim started as `ZCODE_BIN` that adds both fields.
Duplicate-searched 2026-10-25: no existing report; #192 (closed) is the related `Cron*` default that relies on the same flag.

## 19. Paseo — CLI: rename a terminal tab, stream UI renames, and inspect's workspace id (draft, not filed, 2026-10-24)

**Status: ready-to-file** (2026-11-09), with a trim: request (3) was
[#7592](https://github.com/getpaseo/paseo/issues/7592) and is **CLOSED**
(2026-10-23) — file only terminal rename and/or events stream (operator
decides the split). Light duplicate search 2026-11-09 found no CLI
`terminal rename` / events-stream issue. Filing waits for operator yes.

**Repo:** getpaseo/paseo. Checked against the local app bundle `/Applications/Paseo.app` with `rg -a` (no live daemon call; app version not read here, item 17 cites 0.12.0).

### What happens

1. A terminal tab cannot be renamed from the CLI. `paseo terminal create --name` sets the name at creation only. The app bundle already contains the daemon RPC: `terminal.rename.request` and `terminal.rename.response` appear in `Contents/Resources/app.asar` and in the web bundle, so only the CLI route is missing.
2. A tool cannot observe a UI rename without polling. The bundle's client handles `agent_update`, `workspace_update` and `terminals_changed` messages; no CLI command streams them.
3. `paseo agent inspect --json` omits the workspace id. This is already #7592 (see item 17); it is listed here only because the same tool needs it.

### Request

1. `paseo terminal rename <id> <title>`, calling `terminal.rename.request`.
2. An event stream command, `paseo events --json`, printing `agent_update`, `workspace_update` and `terminals_changed` as JSON lines, so a tool can see UI renames without polling.
3. `paseo agent inspect --json` prints `workspaceId` (#7592).

### Why it matters here

The ade autorename design (2026-10-24, `skills/autorename`, design section 3.7) names Paseo agent tabs `<name>-pt`, and terminal tabs only at creation. A later UI rename of a terminal tab can then neither be set back nor seen by the tool.

### Searched first (2026-10-24)

`gh issue list --repo getpaseo/paseo --state all --search` for "terminal rename" and "events stream workspace": no issue titled as a CLI terminal rename or an event stream. Related, not duplicates: #4521 (closed: terminal tab labels fall back to "Terminal") and #7592 (inspect omits the workspace id; item 17).

### Unverified

Whether a `paseo events` command already exists in the CLI: the name comes from the ade design (2026-10-24), and this draft did not run the CLI to check. The `terminal.rename.request` RPC was seen only in the app bundle, not exercised.

### Ask

djbclark decides whether to file. Suggested split: the terminal rename and the
event stream as separate issues. The inspect workspace id was #7592 and is
closed (2026-10-23) — do not re-file it.
