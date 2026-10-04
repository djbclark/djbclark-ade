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
automatic half. The differentiators our post still adds: the fail-closed
eligibility rules (drafts, session forks, argv replay safety), the
`state_changed_at` timestamp ask, argv preservation in `AgentResumePlan`
(a native bug too: restart-restore drops `--dangerously-skip-permissions`
etc.), and a race-free native sleep. **Posting plan should probably become
a comment on #631 cross-linking #4724 and the reference implementation,
rather than a cold new Discussion** — decide before posting.

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
