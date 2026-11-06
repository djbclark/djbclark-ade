# djbclark-ade slim-down: plan of record, v2 (2026-11-06)

Lead: a Claude cloud session (Fable 5.1, effort high). Operator: djbclark.
Status: v2, for Codex review on the PR that carries it, then one more round
to final. v1 (same day, same file in git history) was written before the
check-ins and the research briefs; section A says what changed. Every number
carries its snapshot date; re-probe before acting.

## A. What v2 changes, and why

A1. **The repo is a toolbox for other projects, not just an environment.** The
consolidated check-in (37 agents, `docs/checkins/slim-down-checkins-2026-11-06.md`)
shows 17 agents that never edit this repo but call its tools (`relay.py`,
`acp-dispatch`, `load-watch admit`, `deadline`, the claim registry), and four
outside projects whose own AGENTS.md name `acp-dispatch --kind frontier` and
`relay.py`: tendcf, nix2cf, Plektra, paseo4herdr (report I4). v1 said "delete
acp-run and relay.py"; v2 says **replace, shim for one cycle, then delete**
(E6, E3), and lists the outside files that must change (C3; order 11 applies).

A2. **Operator rulings now in force** (report E9, lead resume note): this
work is Claude-only (only this work); the TUI retirement's unfinished waves
(3 and later, `~/.local/state/bigteam/tui-retire/PLAN.md` on the Mac) are
folded into this split (E9i); all decided TUIs are uninstalled machine-side
with state backed up first, muse retired, copilot CLI support removed in
favour of Paseo's Copilot provider, the 147 memory notes archived (E9h);
PR 269 is re-homed into frdminc/peer-link with a pointer skill left here
(E9j); lander and feeder stay booted out; J11 (answered) retires them,
plists removed in Wave 4.

A3. **Paseo moved** (research brief, 2026-11-06): 0.15.3 is current; 10
releases since 2026-10-26. New and relevant: **native resume after restart**
(0.15.0, opt-in in Host settings → Agents, sends `Resume working.`), **idle
runtime cleanup** (0.14.0, configurable), `.worktreeinclude` built in,
plugins can add tools and MCP servers to specific agents (0.14.0), usage
checks can be disabled per host (0.15.0). No plugin has been retired as "now
built in". Paseo has no native pause-at-quota; that stays a plugin job.

A4. **Research verdicts per capability** (section D): for six of nine
capabilities an existing tool or Paseo feature replaces ours; for three
(exclusive workspace claims, a cross-platform scheduler with a linger check,
a CLAUDE.md/AGENTS.md linter) nothing exists, so those stay ours, trimmed.

A5. **Retractions from v1.** (i) v1 proposed `vercel-labs/skills` as a live
sync; its local-path add is a one-time snapshot, not a link (issue #748), so
for Claude-only a symlink needs no tool. (ii) v1 proposed `git subtree split`;
`git filter-repo --paths-from-file` on a fresh clone keeps history for several
paths in one pass. (iii) v1 listed `session-finder` as plain DELETE; it is the
most shared dependency in the fleet (report I3) and gets a shim.

A6. **Changelog read directly (0.14.0 → 0.15.3, 2026-11-06), four items the
brief under-weighted:**
  - **`getpaseo/claude-code-entrypoint-env`** (0.14.0 notes): an official
    optional plugin that launches Claude sessions with
    `CLAUDE_CODE_ENTRYPOINT=Paseo`, "a community workaround for subscription
    limits draining faster" (#7976, #8164). Cheapest quota lever on the
    table; added to J6 as a default.
  - **Plugin hooks and per-agent tools** (0.14.0 #7938, #7983; 0.15.0 #8081,
    #8117): a plugin can give tools to specific agents, add MCP servers when a
    session opens, and run `worktree.create.before` / `worktree.create.after`
    before setup and agents start. That is the natural home for the trimmed
    claim registry (D9: register the claim when Paseo creates the worktree,
    refuse a second agent at `create.before`) and for an `ask` tool, instead
    of git hooks and a relay. Recorded as the D9 implementation option.
  - **Terminals survive daemon restarts, crashes and supported updates**
    (0.15.0 #7644, #8155), and interrupted agents can resume in their
    conversation (opt-in): together they retire the "quiesce before a Paseo
    restart" practice in `docs/queue.md` once verified on 0.15.x (Wave 3
    check), and they are the native half of D11.
  - **Claude settings files are no longer discarded when Paseo adds its launch
    settings** (0.15.0 #8148): PR 289's `agents/claude/settings.json.tmpl`
    rendering is safe under Paseo; the fixed skill batching for new ACP agents
    (#8387) removes one reason `skill-everywhere` existed.
  Not relevant to the split: first-run setup and project suggestions (0.15.2),
  voice defaults, mobile terminal rendering, the Windows daemon fix (0.15.1).

A7. **Round 3 (2026-11-06, after Codex on PR 295 and an Opus adversary pass,
verdict BLOCK with 3 HIGH):** session-finder internals are KEEP-imported by
`load-watch`, `context-watch`, `ade_claims.py` and `acp-dispatch` (E3 now
deletes only after an import search; `claude_identity.py` moves to `bin/`);
the inherited drain gate (rearchitecture D0.2) is restored as C7; E10 moves
behind a Mac verification and keeps `skill-everywhere` trimmed while any
non-Claude provider or the site-private root survives; the C3 per-file gate
covers every name C3 lists (self-slash, autorename, the two upstream
watchers, `session_log.py`); native resume defaults OFF (evidence F); the
rulings are restated against the narrow "this work is Claude-only" (PR 281
and 260 PARK, Codex paths stripped only when Codex retires); the merge-gate
Action must port pr-wait's marker properties 1–5 (J8 decides Codex threads);
lander/feeder get J11; the consolidated check-in report is on the branch;
labels J2a/J2b/J2c are distinct; shared files go to the serial merger; the
Mac daemon upgrade to 0.15.x is an operator step before Wave 3; fleet-watch's
home is marked unverified.

## B. Scope and constraints

B1. **In scope.** Move the non-ADE parts to `djbclark/site-djbclark` (E1);
delete what Paseo, a Paseo plugin or a maintained tool now does (E2–E10);
finish the TUI retirement (E9 of this plan, E9i of the report); shrink the
docs and the standing orders (E11); land the batch-1 PRs the rulings keep.

B2. **Constraints** (operator, 2026-11-06). Claude cloud sessions; Claude
agents only for this work (Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.1); one
long-lived branch, no PRs for the slices; prefer a Paseo feature, then a
plugin, then an existing repo (whole or copied; relicensing allowed), over our
own code; ask before copying external code, adopting a repo whole, or
installing a plugin not already running; nothing is changed on the Mac by a
cloud session (installs, launchd, Paseo settings are operator steps in each
brief); master is PR-only, so the final landing is one PR at the end (J7, answered).

B3. **Not in scope.** Dann/Eve/techno-euphora, aiuse, paseo-runner,
sudo-secretspec, the Paseo plugins in their own repos, CFEngine upstream work.
They are listed in the report as toolbox users only.

## C. Guard rails: what the split must not break (from the check-ins)

C1. **Live processes and jobs on the Mac** (report B1, B4–B7): three detached
`acp-dispatch` slices (tendcf, fork-cmdb, q10-policy) needed `acp-dispatch`
and `acp-run` until they exited (0.5–1.5 h from 2026-11-06 ~11:00; J1, answered: all three exited); `com.djbclark.load-watch` runs `bin/load-watch sample` by
absolute path from the shared checkout; `com.djbclark.deadline-sweep` runs
every 60 s; `com.djbclark.pr-policy` every 600 s from the shared checkout
(run `bin/pr-policy uninstall` before moving it, or reinstall from the new
place); `load-watch admit` is called by `bg` and `acp-dispatch`; two
`fleet-watch upstream` registrations (CFEngine, Paseo) are paused and depend
on `bin/watch`, relay.py and fleet.py; `com.djbclark.ade-lander` and
`ade-feeder` are booted out.

C2. **Symlinks into the repo** (report B8): `~/.local/bin/coding-bot`,
`~/.pi/agent/extensions/subagent → pi/extensions/subagent`, four `hand`
command links (omp, pi, zcode, opencode), every skill linked by
`skill-everywhere`, `~/.local/bin/herdr-sleeper` (may already dangle), and
herdr's own plugin registration `herdr plugin link plugins/herdr-sleeper`
(`plugins/herdr-sleeper/README.md:61`), which points into this repo.
Also the **live hook commands in the hand-maintained `~/.claude/settings.json`**
(`agents/claude/settings.json.tmpl` is not applied automatically): `prior_art_nudge.py`
on PostToolUse and UserPromptSubmit, `jev_effort_hook.py` on UserPromptSubmit,
`quota_nudge.py`; a hook pointing at a deleted file runs on every tool call
and prompt fleet-wide, so the operator edits that file as a named step before
the final merge; E2, E10 and D4 cite this paragraph. Every deletion names the links and
hook lines it breaks; the operator relinks, removes or edits.

C3. **Outside files that name our tools** (report I4; order 11: per J2b the slim lead has the merge decisions for
these five repos and asks when unsure; anything outside them is a proposal): tendcf and nix2cf AGENTS.md
(`acp-dispatch --kind frontier`, `acp-run`, `relay.py`, `route_agent`, quota
gates, `load-watch admit`, `deadline`, `session_log.py`, `cfenginewatch`);
CFEngine (`cfenginewatch`, `watch`, `fleet-watch`; I4b); Paseo upstream
(`paseowatch`; I4c); Plektra (`acp-dispatch`, `relay.py`, `autorename`,
`self-slash`; I4d); paseo4herdr (`acp-dispatch`, `relay.py`, `self-slash`; I4e);
Pi (`pi/extensions/subagent`, `hand` links, `agent_guard.py`; I4f);
sudo-secretspec, aiuse, paseo-runner (`relay.py`, `acp-dispatch`/`acp-run`
as clients; I4g); `~/ops/site-public-djbclark/home-agents.md`
item 40 (`coding-bot`); `~/.config/aiuse/config.toml` (`opencode-go`
exclusion, drop after PR 260 is decided). `session_log.py` named there is
`claude/hooks/handoff-tools/session_log.py` (the Tier 1 pointer writer,
KEEP with `session-handoff`, D3). `fleet-watch`'s home is **unverified**:
the rearchitecture C1 says `~/ops/site-private/bin`, the HELM report says
site-public, and AGENTS.md's doc table links a `bin/fleet-watch` that does
not exist here; audit (e) probes it and fixes the AGENTS.md row.

C4. **State the tools own**: ~20 active claims in `~/.local/state/ade/claims`
(retiring the claim tool must not orphan one); `~/.local/state/load-watch/watcher.json`;
deadline records; `~/.local/state/bigteam/*` job records read by `acp-dispatch
outcome` → `route_agent.py calibrate` (the rearchitecture plan keeps that
data); the stash `prwait-wip2` and the unowned items in report F.

C5. **Known bugs the split inherits**, so a slice does not "fix" them by
accident: `ade-git-guard claim ls` does not exist (the listing is
`bin/ade_claims.py list`; report I1); a `/baton` successor keeps its
predecessor's `CLAUDE_CODE_SESSION_ID`, and relay.py, fleet.py,
session-find.py and ade_claims.py still trust it (I5); adversary markers go
stale after a master merge (I8).

C7. **Drain gate (restored from the rearchitecture's D0.2; a gate before
E2, E3, E4 and E6):** `plugins/herdr-sleeper/herdr-sleeper list` and its journal
empty (no sleeping pane still holds a Claude session UUID); no `acp-dispatch`
record resumable or with a scheduled `auto-resume` launchd job
(`acp-dispatch ls`, `launchctl list | grep acp-dispatch`); every cow pasture
and linked worktree clean and pushed or explicitly abandoned by its owner
(`bin/cow-pasture ls`, `git worktree list`), or, for an item with no reporting
owner (report F4, F5, F7), waived by the operator; `relay.py --pending` empty or
each expectation retired (report I3 lists eight queued, unverified acks); the
bigteam inboxes drained; the three C1 slices exited (J1, answered). The
operator runs these on the Mac and pastes the output into `docs/slim/log.md`;
nothing in E2, E3, E4 or E6 merges before that.

C6. **Evidence to keep**: `docs/checkins/`, `docs/handoffs/`,
`docs/tui-lessons-learned.md`, `docs/checkpoint.md` F and G
(`docs/slim/evidence-paseo-recovery-F.md` holds F).

## D. Replace before build: the verdict per capability (research 2026-11-06)

| Capability | Ours today | Replacement | Verdict |
|---|---|---|---|
| D1 Agent-to-agent messages | `session-finder/relay.py` (+ hooks, 7.4k test lines) | native `paseo send <id> --behavior steer|interrupt` and `send_agent_prompt`; `omercnet/tell-agent` 2.0.1 (44 installs) for the `/tell` command; cross-host via connected hosts (0.13.0) | REPLACE, shim one cycle (E3) |
| D2 Operator inbox of questions and permissions | `helm`, `/helm-all`, PR 261's ledger | native `paseo permit`, `list_pending_permissions`; `fullstackhouse/asks` (57), `wangfh5/agent-inbox` (6, new 11-03), the operator's own `djbclark/questions-please` (5) | REPLACE (E4); the operator's plugin first |
| D3 Handoff and resume | `handoff`, `session-handoff`, `baton`, `hand`, PR 290's plugin | native resume after restart (0.15.0, opt-in), `/paseo-handoff`, `dennyferra/baton` 0.3.1 (16), `sm1ee/session-recovery` (20) | REPLACE for the live-agent case; KEEP the Tier 1 pointer file format (it is the cross-session record the operator reads); PR 290 PARKED until Wave 3 measures the native path |
| D4 Quota pause and resume, surplus | `claude-quota-guard`, `ade_gates`, `gate-profile`, `claude-fleet-governor`, PR 270 | `paseo usage --json`; `tomgrin10/session-guard` 0.5.1 (pause at quota, continue after reset), `babo-jeonguk/usage-auto-resume` (254), `kapybara-org/zerosub` 1.5.1 (560, several subscriptions) ; `aborakati/usage-monitor` (351) for display; `codexbar usage --format json` where Paseo lacks a window | REPLACE the gate enforcement with session-guard/usage-auto-resume (E7); KEEP `context-watch` and `quota_nudge.py` only if the plugins cannot nudge a running session; if `quota_nudge.py` goes, its `~/.claude/settings.json` hook line is an operator edit before the final merge (C2) |
| D5 Host load and runaway processes | `load-watch` (2.2k), `proc-cpu-watch`, `session-load-watch` | `tomgrin10/vitals` 1.0.0, `zedobaia/resources` (154), `itsjustanks/daemon` (70) show and stop; none "finds the agent behind the spike and tells it", and none is a **pre-launch admission gate** | KEEP load-watch's two interfaces: `admit` (the pre-launch gate `bg`, `acp-dispatch`, `local-review` and `deadline_wait.py` call, exit 75 when too hot; `bin/load-watch:1631-1878`) and find-and-tell, delivered by `paseo send`; delete the pane-typing delivery, `proc-cpu-watch` and `session-load-watch` (E5) |
| D6 Fan-out and slices | `bigteam`, `acp-dispatch` (5.9k), `acp-run` (5.3k) | native subagents and `paseo run --no-wait --output-schema`; `lerenn/playbooks` (approval-gated YAML pipelines), `gpambrozio/firstmate` (247), `gyuha/agent-team` (57); Claude Code workflows for the lead's own fan-out | REPLACE with a shim (E6): `acp-dispatch` becomes a thin `paseo run` wrapper keeping the exit-code contract and the outcome record for one cycle, then goes |
| D7 Skills in every agent | `skill-everywhere`, `skill-get`, `fix-skill-frontmatter.py` | Claude-only: one symlink `~/.claude/skills → <repo>/skills` (no tool); other surviving providers: `npx skills add <repo>` (MIT; a snapshot, re-run on change, vercel-labs/skills#748); `gpambrozio/skills` (902) to list and invoke; `agentskills/skills-ref validate` for lint | KEEP `skill-everywhere` trimmed while any non-Claude provider, the site-private root or the site-djbclark root survives without its own install path; delete the rest (E10) |
| D8 Scheduler for the kept jobs | launchd plists; PR 291's `ade-sched` | no existing tool refuses on missing linger or wraps `flock -n`; `gpambrozio/launchd-jobs` is macOS-only visibility; Paseo schedules run agents, not shell jobs | KEEP `ade-sched` (land PR 291); Paseo schedules replace the nightly agent jobs (`routing-recalibrate`; `skillopt-night` is deleted, J4) and run the agent that executes `context-budget-check` nightly (J3); the shell sweeps (`deadline`, `pr-policy`, `load-watch`) stay on `ade-sched` |
| D9 Exclusive workspace claims | `ade_claims.py` (2.3k), `ade-git-guard`, `libexec/` hooks | none exists; Paseo's one-worktree-per-agent makes most claims implicit; `git worktree lock` only blocks prune; since 0.15.0 a plugin can hook `worktree.create.before/after` and give tools to specific agents (A6) | KEEP, trimmed to owner + expiry + refuse-add/commit-in-foreign-workspace; fix the `claim ls` mismatch (E8); Wave 4 decides whether the trimmed registry lives in a ~100-line Paseo plugin hook instead of git hooks |
| D10 Merge gate | `pr-wait` (2.3k), `local-review` (Codex) | GitHub ruleset: required status check from a ~40-line Action that validates the adversary marker against the head; `gh pr checks --watch --required` to wait; `claude -p --json-schema` (verified on 2.1.318) for a local Claude review with a parsed verdict; `codex review` has no JSON and no per-request strength knob (brief 2026-11-06) | REPLACE (E8): the Action is the one piece of new code, and it replaces 4.6k lines |
| D11 Recovery evidence | PR 290 `ade-recovery` (3.3k TS) | native resume (0.15.0) + `session-recovery` first | PARK (R4) |
| D12 Moving dirs with history | — | `git filter-repo --paths-from-file` on a fresh clone (installed here, a40bce5) | ADOPT (E1) |
| D13 Instruction-file lint | PR 289's `instruction-lint` | no CLAUDE.md/AGENTS.md linter exists; `skills-ref validate` covers SKILL.md | KEEP instruction-lint (lands with PR 289); use skills-ref for skills |
| D14 Idle agents, sleep | `plugins/herdr-sleeper`, `docs/agent-sleep.md` | native idle cleanup (0.14.0), `sm1ee/session-janitor` (60) | DELETE (E2) |
| D15 Cross-vendor session resume | — | `cross_agent_session_resumer` v0.4.1 (maintained) | NOT NEEDED for Claude-only work; note for the surviving providers only |

## E. Slices (disjoint file sets) and dispositions, v2

Dispositions: DELETE, MOVE (site-djbclark), REPLACE (delete after the
replacement is verified live on the Mac), SHIM (replace, keep a thin
compatible wrapper for one cycle with a dated removal line), KEEP (trim),
DECIDE (J question). Every slice ends with zero references to a deleted name
outside `docs/history/` and AGENTS.md (E11 rewrites AGENTS.md; until then it
is exempt), its tests gone or green, and a "links and outside files" list for
the operator (C2, C3). **The shared files are the serial merger's**: README
rows, `docs/skills.md` rows, AGENTS.md mentions and the one changelog
fragment (`changelog.d/slim-2026-11.md`, the branch name per rule 10) are
edited by the lead at merge time from the slice's report, never by a writer.

E1. **S-move → site-djbclark** (unchanged from v1 except the tool):
unlink the five symlinked skills (`forgejo`, `hyades-docker`,
`sipb-llm-bench`, `forgejo-ci`, `sudo-secretspec`); delete the vendored
`siyuan*` (install upstream with `npx skills add zhiluop/siyuan-skills` where
wanted); move with history via `git filter-repo` on a fresh clone:
`gmail-search`, `ovhcloud-api`, `aws-rules`, `terminus-kira`, `diskfree`,
`bottom-config`, `setup-modern-cli`, `teach`, `todo`, `report`, `greptile`,
`coderabbit-feeder`, `firecrawl`, `bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`,
`bin/codium-ai`, `bin/open-clean` (PR 256, if it lands), onto a branch
`slim-intake/2026-11` of site-djbclark; each moved file passes a secrets scan
first, and site-djbclark's `skills/` is added as a `skill-everywhere` root in
the same slice so nothing disappears from the agents at landing (J2a).
`barnowl`, `book-to-kb`, `change-hermes*` and the Grok-bot skills go the same
way (J2a answered); the `tell-coding-bot` pointer skill stays here (E9j).

E2. **S-dead**: `ade-scan-state*` (+3.9k tests), `seat-name`, `jev`,
`jev-eval`, `docs/jev.md`, `claude/hooks/jev_effort_hook.py` (the operator
removes its `~/.claude/settings.json` hook line before the final merge, C2), `ralph-tui-orchestration`, `jevlike`,
`skillopt-sleep-learned`, `plugins/herdr-sleeper` (D14), `docs/agent-sleep.md`,
`vendor/` entries pointing at retired tools, the `docs/ade-everywhere-*` series
and `docs/apply-toolchain-prompt.md` → `docs/history/`. `cow-workspaces` and
`bin/cow-pasture` (Paseo worktrees + `fresh-worktrees` + built-in
`.worktreeinclude`).

E3. **S-finder: SHIM then delete.** New `relay.py` (~100 lines): resolve the
target to a Paseo agent id (`paseo ls -a -g --json`), call `paseo send`, print
`delivered` on exit 0, refuse anything that is not a Paseo agent with a
message naming the retirement date. **It keeps the flags its KEEP callers
use**: `--message-file` (`-` for stdin), `--ack` and `--wait N` (mapped to
`paseo send` + `paseo wait --timeout N`), because `bin/deadline:446-451`
sends owner notices that way and `deadline` is KEEP; `deadline` is updated in
the same slice if the mapping changes its exit codes. **The shim is installed
only after** (a) every in-repo caller is on the shim's flag set (audit (e) in
Wave 1 lists them) and (b) the C3 outside files that name `relay.py` are
migrated or the operator accepts, per file, that non-Paseo routes (herdr and
Orca panes, retired 2026-10-31) stop working for them; that is a Wave 3
gate, not a Wave 6 one. Every other route, `launch.py`, `where.py`, `nested_pty.py`, adapters,
`peer-relay`, `relay_prose_nudge.py`, and the 7.4k+1.7k+0.7k test lines go
**only after an import and path search** (`import fleet`, `claude_identity`,
`nativeid`, `session-finder` state paths) shows zero hits in KEEP code; today
it shows four: `bin/load-watch:266` (`fleet.sessions()` in the find half of
D5), `bin/context-watch:74`, `bin/ade_claims.py:434` and `bin/acp-dispatch:839`
(`claude_identity.owner_session_id()`, the fix for the C5/I5 wrong-owner
bug). Path callers that the "deleted name" rule would not flag because the
file moves rather than disappears: `skills/handoff/SKILL.md:90` and
`skills/baton/SKILL.md:90` (`python3 .../session-finder/claude_identity.py ||
echo $CLAUDE_CODE_SESSION_ID`, whose `||` would silently fall back to the
stale id), `skills/session-handoff/SKILL.md:137-148,170,185` (`fleet.py --json`,
`relay.py` by absolute path), and `bin/route_agent.py:1600` (reads the
`~/.local/state/session-finder` root for calibration records: a read-only
state path that stays, named here so the search does not count it as a hit).
So: `claude_identity.py` (and `nativeid.py` if it needs it) move to `bin/` as
KEEP in this slice, the three skills are updated in the same slice, a
forwarding stub stays at the old path for one cycle, and the W2 sweep greps
the old path; `fleet.py` stays until `load-watch`'s
attribution and `context-watch` read Paseo (`paseo ls -a -g --json`) instead,
which is part of E5, then goes. The shim and its one test ship in the final
PR and are removed in the follow-up PR after one live cycle (F, Wave 6), once
C3's outside files are updated; no slice deletes them on the branch.
Standing order 10 is rewritten: "a message is sent with `paseo send` and its
exit status read; a non-zero exit is reported, never assumed delivered".

E4. **S-seat**: `helm` and `/helm-all` REPLACE (D2); `self-slash` DELETE (its
one Paseo-era use, queuing `/compact` into the own pane, is `paseo send
--behavior steer` to self); `autorename` DELETE except a 20-line
`paseo workspace rename` helper if the operator still wants auto-titles;
**both only after the C3 per-file gate** (Plektra and paseo4herdr name them,
report I4d/I4e; AGENTS.md keeps `self-slash`'s host branches live until the
D4/D6 drain, which C7 is), migrated or waived per file;
`hand`, `btww` DELETE **for retired providers only**; for a provider J2 keeps,
their links and the linked implementation stay until that provider's own
retirement (E9 promises this; `moyf/sidechat` or `nilbus/tangent` for the
side-question case if wanted);
`paseo-new-seat`, `paseo-set-model`, `paseo-self`, `paseo-bypass-watch`:
DELETE after the audit confirms `paseo run` + `paseo agent mode`,
`PASEO_AGENT_ID`, and `j0rdsta/plan-auto` cover them (expected: all four).

E5. **S-watch**: KEEP `deadline`, `deadline_wait.py`, `wait-file`,
`pr-policy` (+ its plist), `ade-sched` (PR 291). KEEP `load-watch` trimmed
(D5), its plist path updated in the same change (C1). DELETE
`proc-cpu-watch`, `session-load-watch`, `rumination-watch`, `skills/loadwatch`;
DELETE `bin/watch`, `skills/watch`, `paseowatch`, `cfenginewatch` **after the
C3 per-file gate** (the paused fleet-watch registrations, C1, depend on
`bin/watch`; the two upstream watchers become Paseo schedules reading `fleet-watch`'s briefs,
**after the C3 per-file gate**: tendcf, nix2cf and CFEngine name them,
report I4a-c; `fleet-watch` itself is outside this repo, home unverified,
C3), and `load-watch`'s attribution plus `context-watch` are rewritten to read
`paseo ls -a -g --json` so `fleet.py` can go (E3), with a hot-path test that
runs `cmd_sample` through attribution on a synthetic sustained spike
(`bin/load-watch:1227-1233` calls it unguarded; a `ModuleNotFoundError` there
would disable the threat model's runaway-load response),
`context-budget-check` KEEP as a Paseo schedule (J3; PR 289's hook host),
`launchd/com.djbclark.{rumination-watch,session-history-update,context-budget,routing-recalibrate}.plist` (the `context-budget` plist goes with its `install`/`uninstall` subcommands, J3; the `skillopt-sleep` plist is E10's and `zcode-key-auth`'s is E9's, so each file has one deleting slice).

E6. **S-acp: SHIM then delete.** `acp-dispatch` becomes a wrapper over
`paseo run --provider <p> --model <m> --no-wait --output-schema`, keeping:
the exit-code contract (3 no report, 4 BLOCKED, 124 timeout), the report
file and `.done` record, `outcome` → `route_agent.py calibrate` records, the
`--kind frontier` admission check (`bin/agent_guard.py` and its two tests stay
with it, report B1d), **the `load-watch admit` pre-launch gate (exit 75)**, **the restricted
permission policies** (`--perm read-only` and `--perm deny`, today enforced by
`acp-run`'s per-agent tool filtering, settings stripping and tripwire: a
read-only run exposes only the six read tools and a deny run none, user
settings, MCP servers and hooks are stripped, and every other call trips. The
shim must reproduce that boundary, not approximate it: a **tool allowlist**
(the six read tools, or none), **empty MCP, settings and hooks** for the run
(the shipped Claude template allows `mcp__hermes`, through which an injected
review could send messages or approve pending requests), a **tripwire
equivalent** that aborts on any call outside the allowlist, and **boundary
tests** that prove each of the three before the shim ships; `permissionMode:
plan` plus a denylist is not equivalent. The shim **refuses the launch** when
the provider cannot be configured that way, because these modes protect
prompt-injection-sensitive reviews), **the live-agent count**
(`count_agents()` counts `acp-run` processes and releases the `load-watch
admit --max-agents` reservation only once one is countable; a `paseo run
--no-wait` child never is, so the count is ported to `paseo ls -a -g --json`
before the shim ships, with a handoff test that a burst of shim launches
still hits the 14-agent cap), and the brief footer. `acp-run` stays as the **launch interface** tendcf, nix2cf,
Plektra and paseo4herdr call (C3) until each of those files is migrated to
`paseo run` or the operator accepts the break per file; E7's registry switch
to `paseo provider ls` does not by itself allow its deletion. `acp-run` and
`tests/test_acp_run_*` (4.5k) go with the shims in the follow-up PR after one
live cycle (F, Wave 6); until then only its dead agent adapters (retired
providers, E9) are trimmed.
`acp-dispatch-wait`, the
reap plist, the launchd runner scripts and the one-shot `acp-dispatch
auto-resume RECORD` jobs (`bin/acp-dispatch:34`; a `paseo run` shim does not
run them, so the C7 drain requires none pending), `tests/test_acp_dispatch_*`
(5.4k) go in this slice; the shim gets one new test. `bigteam` DELETE (its job is the
lead's own `Agent`/`Workflow` fan-out plus `paseo run`; a one-page skill
replaces it). `dialogue`, `research`: KEEP only if they run on Claude
subagents without acp-run after a 1-hour port; else DELETE. `coding-bot`,
`tell-coding-bot`, `tell-chief-of-staff`: per E9j, a pointer skill stays,
the code moves to peer-link's repo.

E7. **S-route**: KEEP `route_agent.py` (J2: one Paseo provider per paid plan, several
plans, so routing stays), with its registry switched from
`acp-run --list` to `paseo provider ls --json` (rearchitecture C2) and the
retired providers removed from `config/routing.toml` and `docs/model-routing.md`;
`failover.py` KEEP only the model-chain half (its route half is `paseo run`);
DELETE `routing-recalibrate` (+plist; becomes a Paseo schedule if still
wanted), `go_model_policy.py` and the opencode-go rules once opencode is
retired (J2), `claude-fleet-governor`, `gate-profile` and the **Claude-quota half** of
`ade_gates.py` / `config/gates.toml` / `docs/gates.md` once
session-guard/usage-auto-resume are verified live (D4) **and after the C3
per-file gate** (tendcf and nix2cf name the quota gates, report B9b, I4a); the **frontier half**
(`load_frontier`, `FRONTIER_DEFAULTS`, `judged_pool_block`, `read_guard_state`,
the `[frontier]` table) is KEEP because the kept `route_agent.py` imports it
unconditionally (`bin/route_agent.py:122`, used at 1293-1313): either it stays
as a trimmed `ade_gates.py` or it is ported into `route_agent.py` in the same
slice. **The frontier gate also needs fresh quota state**: `read_guard_state()`
reads `~/.local/state/ade/quota-guard.json`, which `bin/claude-quota-guard
check` produces, and `judged_guard_block()` rejects state older than 30
minutes (`bin/ade_gates.py:530-537`); so the state-producing half of
`claude-quota-guard` (the launchd `check`) is KEEP until the frontier
consumers read `paseo usage --json` instead, which is part of this slice, and
the slice's test exercises `route_agent.py frontier_per_wave()` with fresh
and with stale state, not only that `route_agent.py policy` runs;
`claude-cost-whatif`; KEEP `claude-cost-mix` (small,
local). `skills/model-routing` is rewritten around Claude tiers (section G)
plus the surviving providers' rows; `effort-routing`, `fallback-chains` fold
into it. PR 270 (`quota-surplus`) PARKED: if session-guard covers "spend
before reset", DISCARD; else land on the trimmed route_agent.

E8. **S-git**: KEEP `ade_claims.py` trimmed (D9), `ade-git-guard` with a
real `claim ls` (C5), `libexec/`, `git-commit-own`, `ops-post-checkout-guard`,
`changelog-fold`. REPLACE `pr-wait` and `local-review` (D10): one Action
(`.github/workflows/adversary-marker.yml`) + a ruleset requiring it +
`gh pr checks --watch --required`; the local Claude review is `claude -p
--json-schema` with the marker as output. **The Action ports pr-wait's
marker semantics, review rule 1 properties 1–5, and pr-wait's marker tests
unchanged** (a BLOCK naming the current head counts anywhere, 7+ hex prefix
included; malformed and fetch-failed always block; the JSON is delimited by
its own braces; an APPROVE in a fenced block or with the placeholder head is
documentation): three earlier rounds found false APPROVEs and a hidden BLOCK,
so the port is judged by those tests, not by line count. Per J8 (answered 2026-11-06, the operator's explicit choice over the
fail-closed thread gate `pr-wait` enforced), unresolved Codex threads do not
gate the merge: the ruleset requires the Action and CI, not conversation
resolution; Codex findings stay visible as threads and the lead reads them
before merging. E8 does not start before J8 is answered (it is). AGENTS.md review rules 1, 9, 11 shrink to:
marker required and validated by CI; Codex per J8; local review is Claude.

E9. **S-nonclaude (TUI retirement waves 3+, E9i)**: the retirement plan is
`docs/slim/tui-retire-plan.md` (2026-11-04, wind-down 2026-11-06). Its
rulings: keep claude, codex, agy, cursor-agent, grok, omp, opencode, hermes;
retire pi (folds into omp), cline, zcode and copilot CLI (fold into
opencode), crush, venicecode, qwen-code, goose, aider, kiro-cli, devin, muse,
dsh. Its wave 3 (the six decided removals, 57 files / ~270 lines, briefs
`brief-w3-{code,skills,docs}.md` and `wave3-owned.json` on the Mac) never ran
(load gate), and its later waves (zcode/crush trials through opencode, pi→omp
ports then pi removal, cline and the `paseo-new-seat --provider cline`
default, copilot CLI, muse, machine uninstall with state backed up first, the
147 memory notes to an archive folder, the bigteam SKILL.md merge-ready line)
are this slice's list. **J2's rule (one Paseo provider per paid plan)
supersedes the keep list where they differ**: the agy TUI retires too (the
Google AI plan is reached through Paseo's `antigravity` provider), and omp and
opencode survive only if a paid plan is reachable solely through them (omp's
Claude API-credit grant, opencode's GLM/SIPB routes), settled from the aiuse
pools in the Wave 1 audit; **the Q1 machine-side uninstall of opencode, zcode
and the `glm-acp-agent` provider waits for that audit** (an irreversible step
must not break J2's own rule), and the pi→omp ports happen only if omp
survives it. Retire what the file decided (J2c supplies the file, J2 the rule; the brief needs it on a
branch, not on the Mac): for each retired provider delete its config dir
(`pi/`, `omp/`, `zcode/`, `opencode/`, `opencode-plugins/`, `opencode.json`,
`GEMINI.md`), its `agents/` template, its `bin/` helpers
(`zcode-key-auth` + plist, `agy-linux`, `codex-env-policy-apply`,
`crush-context-check`, `opencode-*`, `pi-skill-dedup`, `cursor-cloud` if
Cursor goes), its skills (`oc-go-key`, `create-hook`), its tests, its
`docs/pi-*.md`, and the retired-TUI rows everywhere. Surviving providers keep
their template and their `hand`/skills links until the next retirement.
`bin/web-get`, `web-digest*`, `firecrawl-router`: KEEP only while a
small-context provider survives; else DELETE. Machine-side uninstall (E9h Q1)
is an operator step with a backup first.

E10. **S-skills-sync** (Wave 3 or later, behind an operator check on the
Mac that every surviving target still sees every skill): `skill-everywhere`
serves two roots today (this repo and `~/ops/site-private/skills`, e.g.
`1password`, `bin/skill-everywhere:44`) and three after E1 adds
`~/ops/site-djbclark/skills` (E1 owns that one edit of `bin/skill-everywhere`
in Wave 2; E10 owns every later change to it in Wave 3) and several targets (Claude, Hermes' external dir,
`~/.agents/skills` for Pi and omp, cursor via `~/.claude/skills`, the grokbot
copy); a single symlink covers only the Claude target of the repo root. So:
KEEP `skill-everywhere` trimmed to the surviving targets until the last
non-Claude provider retires and both site-private and site-djbclark have
their own install paths (J2a);
DELETE `skill-get`, `fix-skill-frontmatter.py`, `skills-everywhere` skill;
`npx skills add` (external code; J4 yes) for the surviving non-Claude providers; `ade-update` KEEP
trimmed (pull + `skill-everywhere --check`, `bin/ade-update:24-37`); `skillopt-night`,
`skillopt_sources.py`, `skillopt-sleep`, `docs/skillopt-sleep.md` and the
`skillopt-sleep` plist DELETE (J4, answered); `ade-backup-stores` KEEP trimmed to the surviving stores
with the credential exclusions as a named exception (E9h Q4); `bm-lint`,
`graft` skill KEEP; `prior_art_nudge.py` DELETE (J4, answered; its two `~/.claude/settings.json`
hook lines are an operator edit before the final merge, C2).

E11. **S-docs** (last): README under 150 lines with a generated roster;
AGENTS.md re-based on Paseo (orders 9 and 10 reworded, the retirement box
replaced by one line and a link to `docs/history/`); `docs/queue.md` (2,079
lines) triaged into closed / carried (one line each, staying in the doc, J5)
/ done; `docs/` keeps `paseo-only-rearchitecture.md` (marked superseded
where this plan differs), `threat-model.md`, `git-guard.md`,
`orchestration-practices.md` (rewritten), `tui-lessons-learned.md`,
`scheduling.md` (PR 291), `secret-deny.md` (PR 289), `checkpoint.md`; the rest
to `docs/history/` dated. `.claude/settings.json`: merge the operator's
unattended-permission rules into the original (R1). `CHANGELOG.md` folded once
at the end. `graft build` last.

## F. Waves, v2

| Wave | Content | Width | Gate |
|---|---|---|---|
| 0 | DONE: check-ins (37 + 5), rulings R1–R8, evidence and the consolidated report on the branch. OPEN: baseline suite (running in the cloud, `docs/slim/baseline.md` when it ends; batch-1 reports note tests that fail on master in containers); land PR 289 and PR 291 on master (pytest-linux pending on both); land `gitignore-aider` (one line) by PR and reset the shared checkout's master; tag `pre-slim-2026-11-06`; `git worktree prune` on the Mac; J1, J2, J2a, J2b, J2c, J11 and J3–J10 all answered 2026-11-06 | serial | all of the above |
| 1 | Audits (a) `bin/`, (b) `skills/`, (c) `tests/` map, (d) `docs/` + queue, (e) outside dependents and links (C2, C3) ; lead writes `docs/slim/ledger.md`; **workflow** (section H, W1); operator approves the ledger once | 5 readers | ledger approved |
| 2 | E1 (unlink, uninstall-vendored, move to site-djbclark), E2 (dead), E9 (retired providers only) | 3–4 writers + reviewers | **C7 drain gate passed first**; suite green; refs zero outside AGENTS.md and README (**workflow** W2) |
| 3 | E3 shim, E4, E5, E10; **order inside the wave**: E5's attribution rewrite merges before E3 deletes `fleet.py`; **operator steps first**: upgrade the Mac daemon to 0.15.x in a quiesced window per `docs/queue.md` (evidence F records 0.14.x; an unfinished turn is lost on restart until terminal persistence is verified), install the J6 plugins, evaluate `session-recovery` with native resume OFF, then the one bounded native-resume trial (J6), then verify for one day before the REPLACE deletions merge | 3 | same; **the E3 shim merges only after the in-repo relay callers are on it and the C3 relay consumers are migrated or waived per file** |
| 4 | E6 shim and bigteam, then E7 and E8; E6 and E7 as sibling cloud sessions | 2–3 | same; the lander and feeder plists are unloaded and removed (J11, operator step); **`acp-run` is not deleted here**: C3's acp consumers are migrated or waived per file first (PRs opened and merged by the lead per J2b, asking when unsure) |
| 5 | E11; AGENTS.md and README (Opus `high`; lead at `xhigh`); **workflow** W3 | 2 | suite green; `graft build` |
| 6 | **The shims and `acp-run` ship in the final PR** (nothing on the Mac changes before the final merge, so a shim that is removed on the branch never runs live); C7 and the C1 live-process checks are **re-run as the final PR's merge gate**, output pasted into the PR; the shims and `acp-run` are removed in a **follow-up PR after one live cycle** (two weeks, or sooner when every C3 file is migrated or waived and `relay.py`/`acp-dispatch` logs show no caller); upstream filings (gaps found in Paseo: a quota-pause primitive, a workspace claim primitive, if still missing); final PR to master (J7); delete `slim/*` branches after MERGED | serial | done |

Each wave: a Sonnet research subagent re-checks Paseo and Claude Code docs
for that wave's area (both moved weekly in October); briefs; writers;
reviewers; serial merges by the lead; suite; push; `docs/slim/log.md` entry
naming every behaviour lost on purpose.

## G. Models, effort, context (confirmed against code.claude.com, 2026-11-06)

G1. **Context.** Fable 5.1 runs at 1M by default; no `[1m]` variant exists
for it (that suffix was for Opus 4.6 / Sonnet 4.6); `/context` shows the live
window; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` is the only way to shrink it.
Cloud sessions can set `/autocompact <tokens>`.

G2. **Effort.** Levels `low`–`max`; precedence `CLAUDE_CODE_EFFORT_LEVEL` >
`/effort` > `--effort` > settings > model default. Defaults: `high` on Fable
5.1 (by the page's rule; not named explicitly), `medium` on Opus 5.5, Sonnet
5.5 and Haiku 5.5, so **set subagent effort explicitly**; `CLAUDE_CODE_SUBAGENT_EFFORT`
(2.1.316) pins it for every subagent; a subagent on another model uses that
model's effort (2.1.317).

G3. **Roster** (unchanged from v1): lead Fable 5.1 `high` (`xhigh` for the
ledger synthesis and the AGENTS.md rewrite, never `max`; fallback Opus 5.5
`xhigh`); inventories Haiku 5.5 `low`; audits, research, deletion slices
Sonnet 5.5 `medium`; rewrites and reviewers Opus 5.5 `high`; `maxTurns`
caps (20 / 40 / 60 / 120 / 30); `isolation: worktree` for every writer; the
two big rewrites (E6, E7) as sibling cloud sessions. Subagent `model` on the
Agent tool takes an alias only (`sonnet`, `opus`, `haiku`, `fable`).

G4. **Worktree facts that matter**: an isolated subagent worktree is removed
automatically when unchanged (2.1.305, 2.1.311 fixes); `claude --worktree`
puts a local session in `.claude/worktrees/<name>`; Claude Code workflows
resume with completed agents cached (2.1.318 fix).

## H. Where a workflow is used (operator approves each, by size)

H1. **W1, Wave 1 ledger**: `parallel` readers per area → dedup by path → a
3-vote refute on every KEEP row ("try to refute that this must stay") → the
ledger. Width 5 + 3×KEEP rows; expected ~60 agents.
H2. **W2, reference sweep after each merge wave**: `pipeline` over deleted
names → grep finder → "load-bearing or doc-only?" judge → loop until two dry
rounds. ~20 agents per wave.
H3. **W3, docs sweep**: `pipeline` over 55 docs → classify → rewrite → a
completeness critic over README and AGENTS.md. ~70 agents.
Each run carries a `+Nk` budget directive as the hard ceiling. Ultracode stays
off (operator, 2026-11-06).

## I. Risks, v2

I1. A shim that is "temporary" becomes permanent: both shims carry a removal
date (the follow-up PR, two weeks after the final merge at the latest) and a
test that fails after it.
I8. Because every wave gate is a merge onto the branch (J7: one PR), the Mac
sees the whole change at once at the final merge: records created after Wave
0 (resumable `acp-dispatch` records, scheduled `auto-resume` jobs, sleeping
panes, dirty worktrees) are never drained by the Wave 2 gate. Mitigation:
C7 and C1 re-run as the final PR's merge gate (F, Wave 6), and the shims are
live for one cycle before their follow-up removal.
I2. An outside project breaks when the shim goes: C3 is a checklist the
operator ticks per file before Wave 6.
I3. Plugins are unsandboxed daemon code: J6 is per plugin; a Sonnet subagent
summarises each plugin's source before the operator installs it; prefer
install counts and recent updates (D-table).
I4. Native resume (0.15.0) is opt-in and new: Wave 3 evaluates
`session-recovery` with it OFF, then one bounded trial in a quiet window with
launches refused (J6); a clean trial leaves it on, a mass wake turns it off;
the result decides PR 290.
I5. The suite fails on master in containers (166 failures across 19 test
files, `docs/slim/baseline.md`, 2026-11-06; mostly git-hook, self-slash and
acp-dispatch tests that need the Mac or the `g*` wrappers): the baseline
records them so deletions are not blamed.
I6. The Mac is the only place plugins, launchd and Paseo settings change
(B2): every such step is an operator step with the exact command in the
brief, and a slice that needs it waits.
I7. Codex cloud reviews have no strength knob and the `codex-review-state`
markers are undocumented (brief 2026-11-06): the Action in E8 reads only our
own marker; Codex findings are read as threads, not as a gate (J8).

## J. Questions for the operator (answered ones kept for the record)

J1. [answered 2026-11-06: yes, all three exited] Did the three detached
`acp-dispatch` slices (tendcf s5-design, fork-cmdb, q10-policy) exit? (`ls ~/.local/state/bigteam/*/jobs/*.done`, or
`acp-dispatch ls`.) Wave 2 cannot start while they run.
J2. **Providers.** [answered 2026-11-06: **one Paseo provider per paid
monthly plan**, Paseo-native where it exists; every TUI that only duplicates a
plan retires (agy TUI, qwen-code, muse outright; zcode, opencode, Pi and omp
unless a paid plan is reachable only through them, which the Wave 1 pool
audit settles before any machine-side uninstall, E9); the Google AI plan is reached through
Paseo's `antigravity` provider (official `antigravity-acp`), not the agy TUI;
the plan list is derived from aiuse's pools and confirmed by the operator]
Which of these survive after the TUI retirement:
Pi, omp, Codex CLI, Cursor, Antigravity, Grok, zcode, opencode, Hermes,
Copilot (via Paseo), glm-acp-agent, qwen-code? `paseo provider ls` plus the
retire list is enough. [answered] this work is Claude-only; the fleet is not.
J2c. [answered 2026-11-06: pushed as branch `docs/tui-retire-plan-2` @
2c108f66, copied to `docs/slim/tui-retire-plan.md`] Push
`~/.local/state/bigteam/tui-retire/PLAN.md` to a branch so the cloud lead
can read it (E9 needs it).
J2a. [answered 2026-11-06: **everything to site-djbclark**, one destination;
the E1 slice runs a secrets scan (`git secrets`-style patterns plus a read of
each file) on every moved file and stops to ask on any hit before the push;
`book-to-kb` and `change-hermes*` included; E9j (PR 269's wrapper code to
peer-link) stands as the earlier explicit ruling and the `tell-coding-bot`
pointer skill stays here (A2, E6, R8: a pointer agents cannot see does
nothing); site-djbclark's `skills/` becomes a third `skill-everywhere` root
(the pre-2026-10-14 hub) so the moved skills keep their links in every
surviving agent; site-private keeps its own root] Homes for the E1 "probably another home"
pieces (unchanged from v1 H2a): `book-to-kb` →
site-private? `change-hermes*` → site-private? Grok-bot pieces → peer-link
repo per E9j, or `coding-bot-mailbox`? `barnowl` → the barnowl fork?
`aws-rules`, `ovhcloud-api` → public site-djbclark or private?
J2b. [answered 2026-11-06: **the slim lead gets the merge decisions** for the
C3 migration edits in tendcf, nix2cf, Plektra, paseo4herdr and site-public
(an order 11 yes for those edits), and asks the operator for input when a
replacement line is not obvious; each repo is attached with `add_repo` where
reachable from the cloud, otherwise the diff goes to the operator per file]
Outside files (C3): may the split propose edits as PRs to tendcf, nix2cf,
Plektra, paseo4herdr and site-public, or report only?
J11. [answered 2026-11-06: **retire**; the plists `com.djbclark.ade-lander`
and `ade-feeder` are unloaded and removed in Wave 4 (operator step), the
scripts stay in the state dir as history; their job is the E8 Action plus
`gh pr checks --watch --required` and Paseo schedules] Lander and feeder
(`~/.local/state/bigteam/deepseek-review-2026-10-30/`, booted out per E9k): they build on `acp-dispatch-wait`, `relay.py`, `fleet.py`,
`local-review` and `pr-wait`, all of which Waves 3–4 replace, so "decide
after the split" is decided by the split. Retire them, or port them onto
`paseo run` plus the E8 Action? Must be answered before Wave 3.
J3. [answered 2026-11-06: **keep**; a Paseo schedule runs an agent that
executes it nightly and reports (D8's "schedules run agents" is why the shell
sweeps stay on ade-sched); its launchd plist and `install`/`uninstall`
subcommands go; PR 289's hook stays wired] `context-budget-check`: keep (PR 289
hooks into it) or fold its one check into `instruction-lint`?
J4. [answered 2026-11-06: **delete all three**, with their tests, docs and
plists (E2, E10); `npx skills add` (vercel-labs/skills, MIT) may be used for
any surviving non-Claude provider] Dormant pieces: delete `jev`,
`prior_art_nudge`, `skillopt-night`?
J5. [answered 2026-11-06: **stays a doc**; carried items one line each in
`docs/queue.md`, no task plugin] `docs/queue.md`: triage into a doc, or into
`anh-chu/tasks` / `activechoon/kanban-md`?
J6. [answered 2026-11-06: **all twelve** (the eight defaults and the four
optionals) **plus `sm1ee/session-recovery` as the thirteenth**, each after a
Sonnet subagent's source summary; installed by the operator in Wave 3;
`pr-radar` then replaces pr-wait's waiting half and `session-janitor`
replaces herdr-sleeper outright; for the operator inbox **both** `asks` and
`questions-please` are installed and the one still used after a week stays,
the other goes in the follow-up PR; **native resume gets one bounded trial**:
turned on by the operator for one daemon restart in a quiet window with the
fleet idle and `load-watch admit` refusing launches, measured, and **left ON
if it behaves** (a mass-wake incident turns it off); the trial's result
decides PR 290 (J9); the trial runs with the fleet idle and launches refused,
so it cannot show the busy-fleet mass wake of report I7, and its write-up
says so]
**Plugins to install** (each is trusted daemon code; defaults in bold):
**tell-agent**, **asks** or your **questions-please**, **baton**,
**session-guard**, **usage-auto-resume**, **vitals**, **skills**, `pr-radar`,
`session-janitor`, `plan-auto`, `zerosub` (only if you run several Claude
subscriptions), and the official **`getpaseo/claude-code-entrypoint-env`**
(A6; default yes). Native "Resume agents after restart" is OFF until Wave 3's **one bounded
trial** (evidence F: best effort, no exactly-once, cannot exclude a session;
report I7: one mass wake pushed load to 394): Wave 3 evaluates
`session-recovery` with it off first, then the trial; a clean trial leaves it
on.
J7. [answered 2026-11-06: **one PR at the end of Wave 6**, gated by the E8
Action, CI and the adversary marker; the operator merges with
`--match-head-commit`; protection stays on. Reconciled with A1/I1 after the
final adversary confirm: the shims ship in that PR and a **small follow-up
PR** removes them after one live cycle (F, Wave 6, I8); the operator was told
and can override] Final landing: one PR from the
slim branch, or lift protection for a fast-forward?
J8. [answered 2026-11-06: **yes**: rule 1 stays, enforced by the E8 Action;
rule 9 becomes "read Codex threads, fix what is real, no resolution gate";
rule 11's local review is `claude -p --json-schema`; rule 10 stays] Review
rules after: marker validated by CI (E8), Codex advisory, changelog fragments
kept, local review by Claude.
J9. [answered 2026-11-06: **park** until Wave 3 measures the native path;
land only if a gap remains] PR 290 (`ade-recovery`): park until Wave 3
measures native resume (R4), or land now?
J10. [answered 2026-11-06: **a fresh cloud session**, Fable 5.1 at high,
started with the K2 prompt once PR 295 lands; this session finishes PR 295
and stops] Start the execution in this session, or in a fresh cloud session
with the prompt in section K?

## K. Starting the work

K1. **Recommendation: a fresh cloud session, Fable 5.1, effort high, on the
slim branch, with the prompt below.** This session's context is the research
and the rulings, all of which are now on disk (`docs/slim/`); carrying it
forward costs Fable-rate tokens on every turn for no decision it still
needs. A fresh session reads the plan and the rulings in two files. Use
`/clear` or a new session; there is no `/new` in cloud sessions (docs,
2026-11-06). `claude --teleport` pulls a cloud session into a terminal if the
operator ever wants it local (one-way; clean git, pushed branch).

K2. **Prompt for the new session** (paste after it opens on
`djbclark/djbclark-ade`, branch `claude/cool-hopper-61dqzq` or the branch the
final PR lands):

```
You are the slim-down lead for djbclark-ade. Read, in this order:
docs/slim/PLAN.md (the plan of record, section F is the wave table),
docs/slim/checkin-rulings.md (what to take from each paused agent and PR),
docs/checkins/slim-down-checkins-2026-11-06.md sections B, C, F and I (what
must not break), docs/slim/evidence-paseo-recovery-F.md. Then run Wave 0's
open items from PLAN.md F, verify each against the artifact (exit codes,
`git log`, `grep -rn`), and stop at the first J question that is still
unanswered, asking it as a numbered list. Models and effort per PLAN.md
section G; every subagent gets model and effort set explicitly and
`isolation: worktree` if it writes. Workflows only at the three points in
section H, each proposed to me with its agent count first. No PRs for the
slices; one branch; commit and push after every merged slice; never touch
the Mac (installs, launchd, Paseo settings are my steps: give me the exact
command). Append to docs/slim/log.md after every wave: what merged, what
was lost on purpose, what the operator must do by hand.
```

## L. Sources (read 2026-11-06)

Check-ins: `docs/checkins/*.md` (5 batch-1 reports), `slim-down-checkins-2026-11-06.md`
(37 agents, branch `checkin/7c58015b` @ 989bb57b), the ade1 lead's resume
note (`claude/ade1-9orwfa` @ 73aaa41). Paseo: github.com/getpaseo/paseo
releases and CHANGELOG (0.15.3), paseo.sh/docs {cli, orchestration,
orchestration-workflows, schedules, skills, plugins, mcp, worktrees,
agent-profiles, hub}, paseo.sh/plugins (25 plugin pages, `all?sort=new`).
Claude Code: code.claude.com/docs {model-config, sub-agents, worktrees,
agent-teams, workflows, claude-code-on-the-web, routines, sessions,
context-window, statusline, changelog 2.1.304–2.1.318}. Codex:
learn.chatgpt.com/docs {third-party/github, code-review, security-review,
developer-commands}, openai/codex#55890 (closed 2026-10-30), #7732. Tools:
vercel-labs/skills (+#748), dallay/agentsync, steipete/CodexBar, ccusage,
agentskills/skills-ref, git-filter-repo, Dicklesworthstone/cross_agent_session_resumer
v0.4.1, GitHub rulesets docs. Local checks: `claude --help` (2.1.318,
`--json-schema`), `git filter-repo --version` (a40bce5).
