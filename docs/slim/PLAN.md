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
(E9j); lander and feeder stay booted out until the split ends (E9k).

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
brief); master is PR-only, so the final landing is one PR or a lifted
protection (J7).

B3. **Not in scope.** Dann/Eve/techno-euphora, aiuse, paseo-runner,
sudo-secretspec, the Paseo plugins in their own repos, CFEngine upstream work.
They are listed in the report as toolbox users only.

## C. Guard rails: what the split must not break (from the check-ins)

C1. **Live processes and jobs on the Mac** (report B1, B4–B7): three detached
`acp-dispatch` slices (tendcf, fork-cmdb, q10-policy) needed `acp-dispatch`
and `acp-run` until they exited (0.5–1.5 h from 2026-11-06 ~11:00; J1 asks
for confirmation); `com.djbclark.load-watch` runs `bin/load-watch sample` by
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
`skill-everywhere`, `~/.local/bin/herdr-sleeper` (may already dangle).
Every deletion names the links it breaks; the operator relinks or removes.

C3. **Outside files that name our tools** (report I4; order 11: these are
proposals until the operator says yes per file): tendcf and nix2cf AGENTS.md
(`acp-dispatch --kind frontier`, `acp-run`, `relay.py`, `route_agent`, quota
gates, `load-watch admit`, `deadline`, `session_log.py`, `cfenginewatch`);
Plektra (`acp-dispatch`, `relay.py`, `autorename`, `self-slash`); paseo4herdr
(`acp-dispatch`, `relay.py`, `self-slash`); `~/ops/site-public-djbclark/home-agents.md`
item 40 (`coding-bot`); `~/.config/aiuse/config.toml` (`opencode-go`
exclusion, drop after PR 260 is decided).

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

C6. **Evidence to keep**: `docs/checkins/`, `docs/handoffs/`,
`docs/tui-lessons-learned.md`, `docs/checkpoint.md` F and G
(`docs/slim/evidence-paseo-recovery-F.md` holds F).

## D. Replace before build: the verdict per capability (research 2026-11-06)

| Capability | Ours today | Replacement | Verdict |
|---|---|---|---|
| D1 Agent-to-agent messages | `session-finder/relay.py` (+ hooks, 7.4k test lines) | native `paseo send <id> --behavior steer|interrupt` and `send_agent_prompt`; `omercnet/tell-agent` 2.0.1 (44 installs) for the `/tell` command; cross-host via connected hosts (0.13.0) | REPLACE, shim one cycle (E3) |
| D2 Operator inbox of questions and permissions | `helm`, `/helm-all`, PR 261's ledger | native `paseo permit`, `list_pending_permissions`; `fullstackhouse/asks` (57), `wangfh5/agent-inbox` (6, new 11-03), the operator's own `djbclark/questions-please` (5) | REPLACE (E4); the operator's plugin first |
| D3 Handoff and resume | `handoff`, `session-handoff`, `baton`, `hand`, PR 290's plugin | native resume after restart (0.15.0, opt-in), `/paseo-handoff`, `dennyferra/baton` 0.3.1 (16), `sm1ee/session-recovery` (20) | REPLACE for the live-agent case; KEEP the Tier 1 pointer file format (it is the cross-session record the operator reads); PR 290 PARKED until Wave 3 measures the native path |
| D4 Quota pause and resume, surplus | `claude-quota-guard`, `ade_gates`, `gate-profile`, `claude-fleet-governor`, PR 270 | `paseo usage --json`; `tomgrin10/session-guard` 0.5.1 (pause at quota, continue after reset), `babo-jeonguk/usage-auto-resume` (254), `kapybara-org/zerosub` 1.5.1 (560, several subscriptions) ; `aborakati/usage-monitor` (351) for display; `codexbar usage --format json` where Paseo lacks a window | REPLACE the gate enforcement with session-guard/usage-auto-resume (E7); KEEP `context-watch` and `quota_nudge.py` only if the plugins cannot nudge a running session |
| D5 Host load and runaway processes | `load-watch` (2.2k), `proc-cpu-watch`, `session-load-watch` | `tomgrin10/vitals` 1.0.0, `zedobaia/resources` (154), `itsjustanks/daemon` (70) show and stop; none "finds the agent behind the spike and tells it" | KEEP load-watch trimmed to find-and-tell, delivered by `paseo send`; delete proc-cpu-watch and session-load-watch (E5) |
| D6 Fan-out and slices | `bigteam`, `acp-dispatch` (5.9k), `acp-run` (5.3k) | native subagents and `paseo run --no-wait --output-schema`; `lerenn/playbooks` (approval-gated YAML pipelines), `gpambrozio/firstmate` (247), `gyuha/agent-team` (57); Claude Code workflows for the lead's own fan-out | REPLACE with a shim (E6): `acp-dispatch` becomes a thin `paseo run` wrapper keeping the exit-code contract and the outcome record for one cycle, then goes |
| D7 Skills in every agent | `skill-everywhere`, `skill-get`, `fix-skill-frontmatter.py` | Claude-only: one symlink `~/.claude/skills → <repo>/skills` (no tool); other surviving providers: `npx skills add <repo>` (MIT; a snapshot, re-run on change, vercel-labs/skills#748); `gpambrozio/skills` (902) to list and invoke; `agentskills/skills-ref validate` for lint | REPLACE (E10) |
| D8 Scheduler for the kept jobs | launchd plists; PR 291's `ade-sched` | no existing tool refuses on missing linger or wraps `flock -n`; `gpambrozio/launchd-jobs` is macOS-only visibility; Paseo schedules run agents, not shell jobs | KEEP `ade-sched` (land PR 291); Paseo schedules replace the nightly agent jobs (`skillopt-night`, `routing-recalibrate`) |
| D9 Exclusive workspace claims | `ade_claims.py` (2.3k), `ade-git-guard`, `libexec/` hooks | none exists; Paseo's one-worktree-per-agent makes most claims implicit; `git worktree lock` only blocks prune; since 0.15.0 a plugin can hook `worktree.create.before/after` and give tools to specific agents (A6) | KEEP, trimmed to owner + expiry + refuse-add/commit-in-foreign-workspace; fix the `claim ls` mismatch (E8); Wave 4 decides whether the trimmed registry lives in a ~100-line Paseo plugin hook instead of git hooks |
| D10 Merge gate | `pr-wait` (2.3k), `local-review` (Codex) | GitHub ruleset: required status check from a ~40-line Action that validates the adversary marker against the head, required conversation resolution; `gh pr checks --watch --required` to wait; `claude -p --json-schema` (verified on 2.1.318) for a local Claude review with a parsed verdict; `codex review` has no JSON and no per-request strength knob (brief 2026-11-06) | REPLACE (E8): the Action is the one piece of new code, and it replaces 4.6k lines |
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
outside `docs/history/`, its tests gone or green, its README and
`docs/skills.md` rows gone, a line in `changelog.d/slim-2026-11.md`, and a
"links and outside files" list for the operator (C2, C3).

E1. **S-move → site-djbclark** (unchanged from v1 except the tool):
unlink the five symlinked skills (`forgejo`, `hyades-docker`,
`sipb-llm-bench`, `forgejo-ci`, `sudo-secretspec`); delete the vendored
`siyuan*` (install upstream with `npx skills add zhiluop/siyuan-skills` where
wanted); move with history via `git filter-repo` on a fresh clone:
`gmail-search`, `ovhcloud-api`, `aws-rules`, `terminus-kira`, `diskfree`,
`bottom-config`, `setup-modern-cli`, `teach`, `todo`, `report`, `greptile`,
`coderabbit-feeder`, `firecrawl`, `bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`,
`bin/codium-ai`, `bin/open-clean` (PR 256, if it lands), onto a branch
`slim-intake/2026-11` of site-djbclark. `barnowl`, `book-to-kb`,
`change-hermes*`, the Grok-bot pieces: per J2a.

E2. **S-dead**: `ade-scan-state*` (+3.9k tests), `seat-name`, `jev`,
`jev-eval`, `docs/jev.md`, `ralph-tui-orchestration`, `jevlike`,
`skillopt-sleep-learned`, `plugins/herdr-sleeper` (D14), `docs/agent-sleep.md`,
`vendor/` entries pointing at retired tools, the `docs/ade-everywhere-*` series
and `docs/apply-toolchain-prompt.md` → `docs/history/`. `cow-workspaces` and
`bin/cow-pasture` (Paseo worktrees + `fresh-worktrees` + built-in
`.worktreeinclude`).

E3. **S-finder: SHIM then delete.** New `relay.py` = 60 lines: resolve the
target to a Paseo agent id (`paseo ls -a -g --json`), call `paseo send`, print
`delivered` on exit 0, refuse anything that is not a Paseo agent with a
message naming the retirement date. Every other route, `fleet.py`,
`launch.py`, `where.py`, `nested_pty.py`, adapters, `peer-relay`,
`relay_prose_nudge.py`, and the 7.4k+1.7k+0.7k test lines go now. The shim
and its one test go at the end of Wave 6 once C3's outside files are updated.
Standing order 10 is rewritten: "a message is sent with `paseo send` and its
exit status read; a non-zero exit is reported, never assumed delivered".

E4. **S-seat**: `helm` and `/helm-all` REPLACE (D2); `self-slash` DELETE (its
one Paseo-era use, queuing `/compact` into the own pane, is `paseo send
--behavior steer` to self); `autorename` DELETE except a 20-line
`paseo workspace rename` helper if the operator still wants auto-titles;
`hand`, `btww` DELETE (D3; `moyf/sidechat` or `nilbus/tangent` if wanted);
`paseo-new-seat`, `paseo-set-model`, `paseo-self`, `paseo-bypass-watch`:
DELETE after the audit confirms `paseo run` + `paseo agent mode`,
`PASEO_AGENT_ID`, and `j0rdsta/plan-auto` cover them (expected: all four).

E5. **S-watch**: KEEP `deadline`, `deadline_wait.py`, `wait-file`,
`pr-policy` (+ its plist), `ade-sched` (PR 291). KEEP `load-watch` trimmed
(D5), its plist path updated in the same change (C1). DELETE
`proc-cpu-watch`, `session-load-watch`, `rumination-watch`, `bin/watch`,
`skills/watch`, `skills/loadwatch`, `paseowatch`, `cfenginewatch` (the two
upstream watchers become Paseo schedules reading `fleet-watch`'s briefs;
`fleet-watch` itself lives in site-public and is not ours to delete),
`context-budget-check` (DECIDE J3: it is also PR 289's hook host),
`launchd/com.djbclark.{rumination-watch,session-history-update,context-budget,routing-recalibrate,skillopt-sleep,zcode-key-auth}.plist`.

E6. **S-acp: SHIM then delete.** `acp-dispatch` becomes a wrapper over
`paseo run --provider <p> --model <m> --no-wait --output-schema`, keeping:
the exit-code contract (3 no report, 4 BLOCKED, 124 timeout), the report
file and `.done` record, `outcome` → `route_agent.py calibrate` records, the
`--kind frontier` admission check (`bin/agent_guard.py` and its two tests stay
with it, report B1d), and the brief footer. `acp-run` is kept only as the
registry read by `route_agent.py` until E7 switches that to `paseo provider ls`,
then deleted with `tests/test_acp_run_*` (4.5k). `acp-dispatch-wait`, the
reap plist, the launchd runner scripts, `tests/test_acp_dispatch_*` (5.4k) go
in this slice; the shim gets one new test. `bigteam` DELETE (its job is the
lead's own `Agent`/`Workflow` fan-out plus `paseo run`; a one-page skill
replaces it). `dialogue`, `research`: KEEP only if they run on Claude
subagents without acp-run after a 1-hour port; else DELETE. `coding-bot`,
`tell-coding-bot`, `tell-chief-of-staff`: per E9j, a pointer skill stays,
the code moves to peer-link's repo.

E7. **S-route**: KEEP `route_agent.py` (the fleet still runs Pi, omp, Codex,
Cursor, Copilot-via-Paseo; report A3), with its registry switched from
`acp-run --list` to `paseo provider ls --json` (rearchitecture C2) and the
retired providers removed from `config/routing.toml` and `docs/model-routing.md`;
`failover.py` KEEP only the model-chain half (its route half is `paseo run`);
DELETE `routing-recalibrate` (+plist; becomes a Paseo schedule if still
wanted), `go_model_policy.py` and the opencode-go rules once opencode is
retired (J2b), `claude-fleet-governor`, `gate-profile`, `ade_gates.py`,
`config/gates.toml`, `docs/gates.md` once session-guard/usage-auto-resume are
verified live (D4), `claude-cost-whatif`; KEEP `claude-cost-mix` (small,
local). `skills/model-routing` is rewritten around Claude tiers (section G)
plus the surviving providers' rows; `effort-routing`, `fallback-chains` fold
into it. PR 270 (`quota-surplus`) PARKED: if session-guard covers "spend
before reset", DISCARD; else land on the trimmed route_agent.

E8. **S-git**: KEEP `ade_claims.py` trimmed (D9), `ade-git-guard` with a
real `claim ls` (C5), `libexec/`, `git-commit-own`, `ops-post-checkout-guard`,
`changelog-fold`. REPLACE `pr-wait` and `local-review` (D10): one Action
(`.github/workflows/adversary-marker.yml`, ~40 lines) + a ruleset requiring
it and conversation resolution + `gh pr checks --watch --required`; the
local Claude review is `claude -p --json-schema` with the marker as output.
AGENTS.md review rules 1, 9, 11 shrink to: marker required and validated by
CI; Codex is advisory, read its threads; local review is Claude.

E9. **S-nonclaude (TUI retirement waves 3+, E9i)**: retire what
`tui-retire/PLAN.md` decided (J2b supplies the list; the brief needs it on a
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

E10. **S-skills-sync**: REPLACE `skill-everywhere`, `skill-get`,
`fix-skill-frontmatter.py`, `skills-everywhere` (D7); `ade-update` KEEP
trimmed (pull + relink the one symlink); `skillopt-night`,
`skillopt_sources.py`, `skillopt-sleep` DECIDE (J4; default DELETE, its reader
was never verified); `ade-backup-stores` KEEP trimmed to the surviving stores
with the credential exclusions as a named exception (E9h Q4); `bm-lint`,
`graft` skill KEEP; `prior_art_nudge.py` DELETE (J4).

E11. **S-docs** (last): README under 150 lines with a generated roster;
AGENTS.md re-based on Paseo (orders 9 and 10 reworded, the retirement box
replaced by one line and a link to `docs/history/`); `docs/queue.md` (2,079
lines) triaged into closed / carried (one line each) / moved to a task
plugin (J5); `docs/` keeps `paseo-only-rearchitecture.md` (marked superseded
where this plan differs), `threat-model.md`, `git-guard.md`,
`orchestration-practices.md` (rewritten), `tui-lessons-learned.md`,
`scheduling.md` (PR 291), `secret-deny.md` (PR 289), `checkpoint.md`; the rest
to `docs/history/` dated. `.claude/settings.json`: merge the operator's
unattended-permission rules into the original (R1). `CHANGELOG.md` folded once
at the end. `graft build` last.

## F. Waves, v2

| Wave | Content | Width | Gate |
|---|---|---|---|
| 0 | DONE: check-ins (37 + 5), rulings R1–R8, evidence taken. OPEN: baseline suite (running in the cloud, `docs/slim/baseline.md` when it ends; batch-1 reports note tests that fail on master in containers); operator confirms C1's three slices exited (J1); land PR 289 and PR 291 on master (pytest-linux pending on both); land `gitignore-aider` (one line) by PR and reset the shared checkout's master; tag `pre-slim-2026-11-06`; `git worktree prune` on the Mac; J2 answered | serial | all of the above |
| 1 | Audits (a) `bin/`, (b) `skills/`, (c) `tests/` map, (d) `docs/` + queue, (e) outside dependents and links (C2, C3) ; lead writes `docs/slim/ledger.md`; **workflow** (section H, W1); operator approves the ledger once | 5 readers | ledger approved |
| 2 | E1, E2, E10, E9 (retired providers only) | 3–4 writers + reviewers | suite green; refs zero (**workflow** W2) |
| 3 | E3 shim, E4, E5; the operator installs the D2–D5 plugins named in J6 and turns on native resume, then verifies for one day before the REPLACE deletions merge | 3 | same |
| 4 | E6 shim and bigteam, then E7 and E8; E6 and E7 as sibling cloud sessions | 2–3 | same; C3 outside-file edits proposed to the operator |
| 5 | E11; AGENTS.md and README (Opus `high`; lead at `xhigh`); **workflow** W3 | 2 | suite green; `graft build` |
| 6 | Shims removed (E3, E6) after C3 is done; upstream filings (gaps found in Paseo: a quota-pause primitive, a workspace claim primitive, if still missing); final PR to master or J7; delete `slim/*` branches after MERGED; decide lander/feeder (E9k) | serial | done |

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
date (end of Wave 6) and a test that fails after it.
I2. An outside project breaks when the shim goes: C3 is a checklist the
operator ticks per file before Wave 6.
I3. Plugins are unsandboxed daemon code: J6 is per plugin; a Sonnet subagent
summarises each plugin's source before the operator installs it; prefer
install counts and recent updates (D-table).
I4. Native resume (0.15.0) is opt-in and new: Wave 3 turns it on and watches
for one day before PR 290 is discarded or landed.
I5. The suite fails on master in containers for 9 acp-dispatch tests plus
self-slash, wait-file and git-hook tests (missing `g*` wrappers; report
01BvGHLy): the baseline records them so deletions are not blamed.
I6. The Mac is the only place plugins, launchd and Paseo settings change
(B2): every such step is an operator step with the exact command in the
brief, and a slice that needs it waits.
I7. Codex cloud reviews have no strength knob and the `codex-review-state`
markers are undocumented (brief 2026-11-06): the Action in E8 reads only our
own marker; Codex findings are read as threads, never as a gate.

## J. Questions for the operator (answered ones kept for the record)

J1. Did the three detached `acp-dispatch` slices (tendcf s5-design,
fork-cmdb, q10-policy) exit? (`ls ~/.local/state/bigteam/*/jobs/*.done`, or
`acp-dispatch ls`.) Wave 2 cannot start while they run.
J2. **Providers.** (a) Which of these survive after the TUI retirement:
Pi, omp, Codex CLI, Cursor, Antigravity, Grok, zcode, opencode, Hermes,
Copilot (via Paseo), glm-acp-agent, qwen-code? `paseo provider ls` plus the
retire list is enough. (b) Push `~/.local/state/bigteam/tui-retire/PLAN.md`
to a branch (`docs/tui-retire-plan`) so the cloud lead can read it.
(c) [answered] this work is Claude-only.
J2a. Homes for the E1d pieces (unchanged from v1 H2a): `book-to-kb` →
site-private? `change-hermes*` → site-private? Grok-bot pieces → peer-link
repo per E9j, or `coding-bot-mailbox`? `barnowl` → the barnowl fork?
`aws-rules`, `ovhcloud-api` → public site-djbclark or private?
J2b. Outside files (C3): may the split propose edits as PRs to tendcf,
nix2cf, Plektra, paseo4herdr and site-public, or report only?
J3. `context-budget-check`: keep (PR 289 hooks into it) or fold its one
check into `instruction-lint`?
J4. Dormant pieces: delete `jev`, `prior_art_nudge`, `skillopt-night`
(default yes to all three)?
J5. `docs/queue.md`: triage into a doc, or into `anh-chu/tasks` (124
installs) / `activechoon/kanban-md`?
J6. **Plugins to install** (each is trusted daemon code; defaults in bold):
**tell-agent**, **asks** or your **questions-please**, **baton**,
**session-guard**, **usage-auto-resume**, **vitals**, **skills**, `pr-radar`,
`session-janitor`, `plan-auto`, `zerosub` (only if you run several Claude
subscriptions), and the official **`getpaseo/claude-code-entrypoint-env`**
(A6; default yes). Also: turn on **Resume agents after restart** (0.15.0).
J7. Final landing: one PR from the slim branch, or lift protection for a
fast-forward? (The PR route keeps the new Action as the gate.)
J8. Review rules after: marker validated by CI (E8), Codex advisory,
changelog fragments kept, local review by Claude. Yes?
J9. PR 290 (`ade-recovery`): park until Wave 3 measures native resume
(R4), or land now?
J10. Start the execution in this session, or in a fresh cloud session with
the prompt in section K? (Recommendation in K.)

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
