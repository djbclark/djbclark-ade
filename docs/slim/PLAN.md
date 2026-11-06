# djbclark-ade slim-down: plan of record (draft, 2026-11-06)

Lead: a Claude cloud session. Operator: djbclark. Status: DRAFT until the
operator answers the questions in section H and the check-in (section B) is
complete. Every number below carries its snapshot date; re-probe before acting.

## A. What this plan does, and the second look

A1. **Goal.** Turn djbclark-ade from a 123k-line Python repo (49.7k in `bin/`,
20.8k in `skills/`, 88.6k in `tests/`, 26k lines of docs, 65 skills, 76 `bin/`
tools, 55 docs; counted 2026-11-06) into a small policy layer on top of Paseo,
with everything that is not an agentic-development-environment concern moved to
its own repo, and everything Paseo (or a Paseo plugin, or an existing
open-source tool) already does deleted.

A2. **Constraints the operator set (2026-11-06).** All work in Claude cloud
sessions; Claude agents only (Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.1); no
pull requests for the work itself, one long-lived worktree branch; web
searches for best practice before each wave; prefer an existing Paseo feature
or plugin, then an existing repo (whole or copied code; relicensing is on the
table), over our own code; any additional software may be installed; the
operator is asked before (a) code is copied from an external project, (b) an
external repo is adopted whole, (c) a Paseo plugin not already installed is
used. Master is PR-only by branch protection (2026-10-31), so the FINAL landing
is one PR or the operator lifts protection for one fast-forward (H7).

A3. **Second look: what the first pass (2026-11-06, Sonnet) got wrong.**
  - It read "50 commits, all 2026-11-01..06" off a **shallow clone** and
    called it the repo's cadence. Retracted: `.git/shallow` exists; the count
    says nothing.
  - It re-derived dispositions that `docs/paseo-only-rearchitecture.md` C1
    already records (acp-run REPLACE in D5, acp-dispatch and bigteam REWRITE,
    helm REPLACE, cow-workspaces RETIRE, session-finder D4/D6, watchers KEEP
    minus pane typing). This plan **inherits C1** and goes further only where
    A2 changes the answer: with Claude-only agents and Paseo plugins now
    covering relay, helm, baton, quota gates and host monitoring, several
    "REWRITE" rows become "DELETE".
  - It did not weigh the tests. ~30k of the 88.6k test lines cover retiring
    targets (relay 7.4k, acp_dispatch 5.4k, acp_run 4.5k, ade_scan 3.9k,
    fleet 1.7k, self_slash 1.4k, launch 0.7k, bigteam 0.7k; 2026-11-06). Every
    deletion carries its tests, so the suite shrinks by a third and CI gets
    faster, which is itself a reason to delete rather than keep "just in case".
  - It did not check the Paseo plugin registry. Section D does.

A4. **What stays true from the first pass.** No single external repo replaces
djbclark-ade: the orchestrators (Orca, Conductor, Claude Squad, Emdash,
Nimbalyst, OpenHands Agent Canvas, Composio Agent Orchestrator) are all at
Paseo's layer, and switching would redo the migration just finished. The
residual value here is the **policy layer**: which model gets which work, one
writer per workspace, what a merge needs, and the operator's standing orders.
That layer should fit in a few hundred lines plus docs.

## B. Wave 0: freeze, check-in, baseline (serial; the gate for everything else)

B1. **Check-in.** `docs/slim/CHECKIN-PROMPT.md` goes to every running agent.
Done when every agent has replied `CHECKIN DONE` and pushed a
`docs/checkins/2026-11-06-*.md` on a branch. The lead then reads every report
(`git fetch --all --prune; git log --all -- docs/checkins/`) and rules per
agent: discard, land-then-stop, finish-first, or continue. Rule of thumb: work
that builds on a section-E "DELETE" target is discarded unless it is a day from
done; a finished branch that only touches a KEEP target is merged into the
slim branch first so it is not lost.

B2. **Freeze.** No new `docs/queue.md` entries, no new skills or `bin/` tools,
until Wave 6. The operator tells the other agents (B1 rulings) and stops the
nightly launchd jobs that edit the repo (`skillopt-night`,
`routing-recalibrate`) for the duration.

B3. **Branch.** One branch, `slim/2026-11` (or the session's designated
branch), from `origin/master`, in its own worktree. Tag the base
`pre-slim-2026-11-06` so every diff and every "what did we lose" question has a
fixed anchor. `git fetch --unshallow` in the cloud clone before any history
work.

B4. **Baseline.** Run the suite the way CI does
(`uv run --with pytest --with pyyaml --with 'agent-client-protocol>=0.9,<1.0' python -m pytest tests/ -q > out.log 2>&1; echo rc=$? > out.rc`),
record the pass/fail list in `docs/slim/baseline.md`, and record the reference
graph: for every `bin/` tool and skill, which files name it (the lead already
has a first cut: acp-dispatch 53 files, acp-run 45, deadline 45, relay.py 25,
route_agent.py 19, fleet.py 18, skill-everywhere 17, helm.py 8, seat-name 0).

B5. **Answers.** Section H's questions, at least H1 and H2, are answered before
Wave 2 starts; Wave 1 can run on either answer.

## C. Models, effort, context, and how work is parallelised

C1. **Primary orchestrator: Claude Fable 5.1, effort `high`, 1M context, one
Claude cloud session.** Reasons: the orchestrator's token volume is small (it
reads summaries, writes briefs, merges, decides) while its decisions are the
expensive-to-get-wrong part; the work is long-horizon and cross-cutting;
Fable 5.1 at `high` is documented to match or beat prior models at `xhigh`.
Raise to `xhigh` for exactly two steps: the ledger synthesis (Wave 1 end) and
the AGENTS.md/README rewrite (Wave 5). Never `max`. Fallback if Fable quota
bites: Opus 5.5 at `xhigh` (its default is `medium`, so set it). Keep the
orchestrator's context light: it never reads whole files, only subagent
reports and diffs; the baseline and the ledger live on disk.

C2. **Subagent roster** (Claude Code `Agent` tool; set `model` and `effort`
explicitly on every spawn, since a subagent otherwise inherits the lead's
Fable at Fable prices):

| Role | Model / effort | Isolation | Returns |
|---|---|---|---|
| Inventory and reference-graph scans (grep-heavy, no judgment) | Haiku 5.5, `low` | none (read-only) | tables of file:line hits |
| Audits per area (read code and tests, propose disposition with evidence) | Sonnet 5.5, `medium` | none (read-only) | `docs/slim/audit-<area>.md` |
| Web research (best practice, Paseo features/plugins, candidate repos, licences) | Sonnet 5.5, `medium`, web tools | none | a sourced brief with dates |
| Deletion slices (remove tool + tests + doc rows, fix references, run tests) | Sonnet 5.5, `medium` | `worktree` | branch + report (files, refs left, test rc) |
| Rewrite slices (bigteam onto `paseo run`, route_agent trim, watchers off pane-typing) | Opus 5.5, `high` | `worktree` or sibling cloud session | branch + report |
| Reviewer per write slice (fresh context, diff only, no edits) | Opus 5.5, `high` | none | APPROVE/BLOCK with file:line findings |
| Normative doc rewrite (AGENTS.md, README, docs/skills.md) | Opus 5.5, `high` | `worktree` | branch |
| History moves and link fixes in docs | Sonnet 5.5, `medium` | `worktree` | branch |

Every write-slice brief carries: the exact file list it owns, the rule that
nothing else is touched, the tests it must delete or run, the doc rows it must
update (README roster, `docs/skills.md`, the tool's SKILL.md or doc), the
commit message, and the report format. A slice longer than about an hour of
agent time, or one that must run the whole suite repeatedly (S1, S7), runs as a
**sibling cloud session** (`create_session`) on the same branch family instead
of an in-process subagent, so it has its own container and does not contend
for the lead's disk or CPU.

C3. **Parallel width.** 3 to 5 writers at once, each on a disjoint file set
(section E), each on its own branch `slim/<slice>` off `slim/2026-11`; one
reviewer per writer, started when the writer reports. The lead merges reviewed
slices into `slim/2026-11` serially (`git merge --no-ff`), runs the suite once
per wave, pushes after each merge (standing order 2). Writers never merge.
Slices that touch the same file (for example README.md) are serialised: the
writer edits only its own rows, and the lead resolves the rest at merge.

C4. **Budget guards.** `maxTurns` on every subagent (inventory 20, audit 40,
deletion 60, rewrite 120, review 30). A subagent that reports "needs a
decision" stops and returns; it does not guess. The lead spends `xhigh` only
where C1 says. Expect most tokens in Wave 1 (reading) and Wave 4 (the acp and
routing rewrites); Waves 2 and 3 are mechanical.

C5. **Best-practice sources consulted (2026-11-06).** Claude Code subagent
guidance: give each subagent its own model and effort, keep system prompts
tight and put procedure in a skill, investigation in subagents and
approval-gated edits in the parent, cap nesting, one writer per file set,
orchestrator high and workers low. Parallel-agent write partitioning: one
writer per worktree, reporters read-only. Each wave starts with one Sonnet
research subagent re-checking these against the current Claude Code docs
(`code.claude.com/docs`) and the Paseo docs, because both move monthly.

## D. Replace-before-build: what Paseo and the ecosystem already do

D1. **Paseo native (docs read 2026-11-06).** Worktree workspaces
(`paseo workspace create --isolation worktree`, PR checkout, `--base`),
subagent trees across providers, `paseo send <id>` (steer or interrupt),
`paseo wait`, `--output-schema` for scripted loops, `paseo usage` (account
quotas, JSON), `paseo permit`, agent profiles with "when to use" notes,
schedules and heartbeats, `paseo provider diagnostic`, remote hosts, Hub
triggers (GitHub/Slack/Discord to agent), the bundled skills `/paseo-handoff`,
`/paseo-committee`, `/paseo-advisor` (`npx skills add getpaseo/paseo`).

D2. **Paseo plugins that map onto our tools** (registry read 2026-11-06;
install counts are the registry's; every plugin is trusted unsandboxed code,
so each is an H3 question, not a decision):

| Ours | Candidate plugin(s) | Note |
|---|---|---|
| `session-finder/relay.py`, `peer-relay`, relay hooks | `omercnet/tell-agent`, `vokturz/peer-agents`, `jtsang4/mesh` (cross-host), `maxwell-01/cross-daemon` | plus native `paseo send`; the "verified delivery" rule (order 10) becomes "read `paseo send`'s exit status" |
| `helm`, `/helm-all` | `fullstackhouse/asks` (decisions and approvals in one list), `omercnet/agent-monitor` (triage roster), `wangfh5/agent-inbox` | plus native `paseo permit ls` |
| `baton`, `handoff`, `session-handoff`, `hand` | `dennyferra/baton` (writes a handoff when an agent idles, continues in a fresh agent), native `/paseo-handoff` | keep only the Tier 1 pointer format if the plugin's document is enough |
| `btww` | `moyf/sidechat`, `nilbus/tangent`, `casonmo/bytheway` | |
| `claude-quota-guard`, `gate-profile`, `ade_gates`, `claude-fleet-governor`, `oc-go-key`, `failover.py` (quota half) | `aborakati/usage-monitor`, `tomgrin10/session-guard` (pause at quota, resume after reset), `babo-jeonguk/usage-auto-resume`, `keefeere/continuity` (fallback provider), `kapybara-org/zerosub` (several Claude subscriptions, auto-switch), `duegin/stats` | plus native `paseo usage` |
| `load-watch`, `proc-cpu-watch`, `session-load-watch`, `context-watch` | `a31521424/host-monitor`, `zedobaia/resources`, `tomgrin10/vitals` (per-agent memory and process trees), `itsjustanks/daemon` (stop runaway jobs), `nguyenvanduocit/agent-processes`, `duyiliu/agent-cli-monitor` | load-watch's "find the agent behind the spike and tell it" has no exact plugin; keep a thin version if the plugins only show |
| `rumination-watch`, `docs/checkpoint.md` (planned recovery) | `37chengshan/goal-mode`, `sm1ee/session-recovery`, native heartbeats | |
| `bigteam`, `acp-dispatch` fan-out | `gpambrozio/firstmate`, `gyuha/agent-team`, `lerenn/playbooks` (YAML pipelines with approval gates), `omercnet/agent-crew`, `duongvm57/slp` | native subagents + `paseo run --no-wait` cover the Claude-only case without a plugin |
| `cow-workspaces`, worktree hygiene, `seat-name` | `omercnet/fresh-worktrees` (already running), `zedobaia/auto-fetch`, `maplumex/archive-branch-cleanup`, `cprecioso/worktreeinclude` | |
| `pr-wait` (the waiting half), `paseowatch`, `cfenginewatch` | `omercnet/pr-radar`, `tomgrin10/follow-up`, `andrioid/attention-span`, `alysnnix/github-integration` | the adversary-marker and local-review halves of pr-wait have no plugin; see E8 |
| launchd jobs in `launchd/`, `config/launchd/` | `gpambrozio/launchd-jobs`, native schedules | |
| `skill-everywhere` | `gpambrozio/skills` (lists and invokes; does NOT sync), `vercel-labs/skills` CLI (MIT; `npx skills add`, 75+ agents), `agentsync` (Rust, symlink-based) | H4 |
| `paseo-bypass-watch` | `j0rdsta/plan-auto` | |
| `herdr-sleeper` remnants, idle cleanup | `sm1ee/session-janitor`; Paseo 0.14 has built-in idle runtime cleanup | |
| `docs/queue.md` (2,079 lines) | `anh-chu/tasks`, `activechoon/kanban-md`, `denny64/github-kanban` | optional; a Markdown board beats a 2k-line doc only if the operator will use it |

D3. **Existing repos to adopt or copy** (each an H5 question): `vercel-labs/skills`
(MIT) for skill install/sync; `ccusage` (MIT) and CodexBar's bundled CLI for
quota reading if any non-Claude vendor stays (H1); `Dicklesworthstone/cross_agent_session_resumer`
only if cross-vendor resume stays a need (H1). Composio's Agent Orchestrator is
a Paseo competitor, not a complement: no.

D4. **Gaps to file upstream, not build** (standing order 8): anything Paseo
lacks that the ledger marks KEEP-for-lack-of-alternative (candidates: exclusive
workspace claims across agents, a merge gate that reads a machine-readable
review verdict) gets an issue on `getpaseo/paseo` or the plugin's repo first,
with our code offered as the patch.

## E. Slices (disjoint file sets) and their dispositions

Dispositions: DELETE (with tests and doc rows), MOVE (to the new repo, H2),
REPLACE (delete after the replacement is verified live), KEEP (trim only),
DECIDE (H question). Every slice ends with: zero references to a deleted name
outside `docs/history/` (`grep -rn`), its tests gone or green, its README and
`docs/skills.md` rows gone, a `changelog.d/slim-2026-11.md` line.

E1. **S-move: non-ADE skills → new repo.** MOVE: `siyuan`, `siyuan-*` (3),
`gmail-search`, `barnowl`, `book-to-kb`, `ovhcloud-api`, `aws-rules`,
`hyades-docker`, `forgejo`, `forgejo-ci`, `terminus-kira`, `diskfree`,
`bottom-config`, `setup-modern-cli`, `teach`, `todo`, `report`,
`sipb-llm-bench`, `firecrawl`, `greptile`, `coderabbit-feeder`, `bench/`,
`tests/test_barnowl_skill.py`, `bin/app-tamer-ab`, `bin/heavy-shim`,
`bin/codium-ai`, `bin/change-hermes*` (Hermes box admin). Method: `git subtree
split` or `git filter-repo` per path so history travels; the new repo is MIT
too. Independent of every other slice; runs first.

E2. **S-dead: Phase-0 and zero-reference tools.** DELETE: `bin/ade-scan-state`,
`bin/ade-scan-state-doc` (+3.9k test lines; the 2026-10-20 scan is history),
`bin/seat-name` (0 references), `bin/jev`, `bin/jev-eval`, `docs/jev.md`
(shadow since 2026-10-11; H6 asks), `skills/ralph-tui-orchestration` (dormant
since 2026-08-23), `skills/jevlike`, `skills/skillopt-sleep-learned`,
`vendor/` snapshots that point at retired tools, `plugins/herdr-sleeper`
(after the D0.2 drain in the rearchitecture plan; H6), the
`docs/ade-everywhere-*` series and `docs/apply-toolchain-prompt.md` (1,760
lines) → `docs/history/`.

E3. **S-finder: session-finder and relay.** REPLACE with `paseo send` +
`paseo ls` + one plugin from D2 row 1. DELETE `skills/session-finder/`
(10.8k lines), `skills/peer-relay`, `claude/hooks/relay_prose_nudge.py`,
`claude/commands/session-finder-all`, tests `test_relay_*`, `test_fleet_*`,
`test_launch_*`, `test_nested_pty`, `test_prompt_line`, `test_session_relay`,
`test_session_history_adapters`. Rewrite standing order 10 to "a message is
sent with `paseo send` and its exit status is read". 25 files reference
`relay.py`, 18 `fleet.py`: the audit lists them; most are docs.

E4. **S-seat: helm, self-slash, autorename, paseo-* helpers.** REPLACE `helm`
(839 lines + `/helm-all`) with `paseo permit ls` and a D2 row 2 plugin.
DELETE `bin/self-slash` (1.5k; queued slash commands into a TUI pane, a herdr
idea), `skills/autorename` (2.2k; herdr half retired, Paseo tab rename is
`paseo workspace rename`), `skills/hand`, `skills/btww`, `claude/commands/`
wrappers for them. KEEP, after checking against native Paseo: `paseo-new-seat`
(vs `paseo run` + `paseo agent mode <id> bypass`), `paseo-set-model` (vs the
app), `paseo-self` (vs `PASEO_AGENT_ID`), `paseo-bypass-watch` (vs
`j0rdsta/plan-auto`). Expected result: all four go.

E5. **S-watch: watchers and launchd.** KEEP `deadline`, `deadline_wait.py`,
`wait-file`, `bg`-adjacent gates (rearchitecture C1 says KEEP). REPLACE
`load-watch` (2.2k) and `proc-cpu-watch` with a D2 row 6 plugin if the plugin
can name the agent; else trim to the "find and tell" core and deliver via
`paseo send`. DELETE `rumination-watch` (2.2k) in favour of goal-mode or
heartbeats, `bin/watch` + `skills/watch`, `skills/loadwatch`,
`skills/paseowatch`, `skills/cfenginewatch` (watcher roles become Paseo
schedules or PR-radar), `launchd/com.djbclark.{rumination-watch,session-history-update,context-budget,routing-recalibrate}.plist`.
`bin/pr-policy` and its plist KEEP (a security control, 2026-11-04).

E6. **S-acp: the ACP layer and its consumers.** After E3–E5. REPLACE
`tools/acp-run` (5.3k) and `bin/acp-dispatch` (5.9k) + `acp-dispatch-wait`,
the reap plist, `docs/dispatch-footer.md`, tests `test_acp_*` (10k lines)
with `paseo run --provider claude --output-schema` and native subagents.
`skills/bigteam`: DELETE (its job is the Claude `Agent`/`Workflow` fan-out
plus `paseo run`; a 1-page skill replaces it). `skills/dialogue` (1.7k) and
`skills/research` (0.6k): KEEP only if they run on Claude subagents without
acp-run; else DELETE. `bin/coding-bot`, `skills/tell-coding-bot`,
`skills/tell-chief-of-staff` (Grok bots): DECIDE under H1. `agents/`
templates: keep the Claude one, MOVE or DELETE the others under H1.

E7. **S-route: routing, quota, cost.** Under H1 = Claude-only: REPLACE
`route_agent.py` (2.8k), `failover.py` (1.4k), `routing-recalibrate`,
`go_model_policy.py`, `agent_guard.py`, `skills/model-routing`,
`skills/effort-routing`, `skills/fallback-chains`, `docs/model-routing.md`,
`docs/model-tiers-design.md`, `config/routing.toml` with ONE skill,
`skills/claude-tiers`: Haiku/Sonnet/Opus/Fable × effort, when each, with the
C2 table as its core; quota gates (`claude-quota-guard`, `ade_gates.py`,
`gate-profile`, `claude-fleet-governor`, `config/gates.toml`, `docs/gates.md`)
REPLACE with `paseo usage` + a D2 row 5 plugin, keeping `context-watch` and
`claude/hooks/quota_nudge.py` only if the plugin cannot nudge a running
session. `claude-cost-mix`, `claude-cost-whatif`: KEEP (small, local,
transcript-based) or REPLACE with `ccusage` (H5). Under H1 = multi-vendor:
KEEP `route_agent.py` but its registry becomes `paseo provider ls` (C2 map in
the rearchitecture plan), and `failover.py` keeps only the model-chain half.

E8. **S-git: claims, guard, merge gate.** KEEP `bin/ade_claims.py`,
`bin/ade-git-guard`, `libexec/`, `docs/git-guard.md`, `git-commit-own`,
`ops-post-checkout-guard`, `changelog-fold`, `pr-policy`. `pr-wait` (2.3k):
split; the CI-and-Codex waiting half is REPLACED by `gh pr checks --watch`
plus a D2 row 9 plugin, the adversary-marker reader KEEPS only if the review
rules keep the marker (H8). `local-review` (Codex): DELETE under H1 =
Claude-only; its replacement is a Claude reviewer subagent (C2 row 6) whose
verdict is the marker. AGENTS.md review rules 1, 9, 11 shrink accordingly.

E9. **S-nonclaude: other TUIs' support.** Under H1 = Claude-only: MOVE to the
new repo or DELETE `pi/`, `docs/pi-*.md`, `bin/pi-skill-dedup`, `opencode/`,
`opencode-plugins/`, `opencode.json`, `bin/opencode-*`, `omp/`, `zcode/`,
`bin/zcode-key-auth` + plist, `bin/agy-linux`, `bin/codex-env-policy-apply`,
`bin/crush-context-check`, `bin/cursor-cloud`, `skills/oc-go-key`,
`skills/create-hook`, `GEMINI.md`, `tests/test_{pi_,omp_,opencode_,zcode_,codex_,crush_,cursor_,go_}*`,
`bin/web-get`, `web-digest`, `web-digest-mcp`, `firecrawl-router` (built for
small-context, non-Claude agents; Claude has WebSearch/WebFetch; `firecrawl`
skill moves in E1). Under multi-vendor: KEEP, but every file gets a "used by
<vendor>, last verified <date>" line and the unverified ones go.

E10. **S-skills-sync and updates.** REPLACE `skill-everywhere`, `skill-get`,
`fix-skill-frontmatter.py`, `skills-everywhere` skill with `npx skills add`
(H4); KEEP `ade-update` trimmed (it also relinks). `skillopt-night`,
`skillopt_sources.py`, `skills/skillopt-sleep`, `docs/skillopt-sleep.md`
(nightly skill-edit cycle, 2k lines): DECIDE (H6); if kept it runs as a Paseo
schedule, not launchd. `ade-backup-stores` (1.9k): KEEP, trimmed to the Claude
and Paseo stores under H1. `bm-lint`, `graft` skill, `claude/hooks/prior_art_nudge.py`
(shadow telemetry): KEEP small, or DELETE the hook if its D2 slice never read
its data (H6). `cow-workspaces` + `bin/cow-pasture`: DELETE (C1 says RETIRE;
Paseo worktrees + fresh-worktrees).

E11. **S-docs: the sweep (last).** README.md rewritten around the remaining
pieces (target: under 150 lines; the roster becomes a generated table); AGENTS.md
standing orders re-based on Paseo (orders 9 and 10 reworded, the retirement box
replaced by one line and a link to history); `docs/queue.md` triaged: every
entry is closed (moot after the slice), carried (still real, one line), or
moved to a Paseo task plugin (D2 last row, if H3 says yes); `docs/` keeps
`paseo-only-rearchitecture.md` (marked superseded by this plan where they
differ), `threat-model.md`, `git-guard.md`, `orchestration-practices.md`
(rewritten), `tui-lessons-learned.md`; the rest moves to `docs/history/` with
its date. `CHANGELOG.md` folded once by the lead at the end (review rule 10).
`graft build` runs last.

## F. Waves (what runs in parallel with what)

| Wave | Content | Width | Gate to next |
|---|---|---|---|
| 0 | B1–B5 | serial | all agents `CHECKIN DONE`; H1, H2 answered |
| 1 | audits: (a) `bin/`, (b) `skills/`, (c) `tests/` map, (d) `docs/`+queue, (e) Paseo plugins + repos + licences (web); lead synthesises `docs/slim/ledger.md`; operator approves the ledger once | 5 readers, no writers | ledger approved |
| 2 | E1 (move), E2 (dead), E10 (sync), E9-under-H1 | 3–4 writers + reviewers | suite green, refs zero |
| 3 | E3 (finder), E4 (seat), E5 (watch) | 3 writers + reviewers | same; plugins from H3 installed and verified live on the Mac by the operator before the REPLACE deletions merge |
| 4 | E6 (acp), then E7 (route) and E8 (git); E6 and E7 as sibling cloud sessions | 2–3 | same |
| 5 | E11 docs; AGENTS.md and README (Opus `high`, lead at `xhigh`) | 2 | suite green; `graft build` |
| 6 | upstream filings (D4), final PR to master or H7, remove `slim/*` branches after `MERGED` | serial | done |

Each wave: the lead (1) spawns a Sonnet research subagent for that wave's
best-practice and Paseo re-check, (2) writes the briefs, (3) spawns writers,
(4) spawns a reviewer per report, (5) merges, (6) runs the suite, (7) pushes,
(8) appends to `docs/slim/log.md` (what merged, what was lost on purpose).
Verification is against the artifact (`grep -rn`, exit codes, `git log`),
never a summary.

## G. Risks

G1. A deletion removes a control the operator relies on without noticing
(quota gates, load guard, pr-policy). Mitigation: REPLACE rows merge only after
the replacement is observed working on the Mac for one day (wave gate in F,
Wave 3), and `docs/slim/log.md` names every lost behaviour.

G2. Another agent's in-flight branch collides. Mitigation: Wave 0.

G3. Plugins are unsandboxed daemon-side code from strangers. Mitigation: H3
asks per plugin; prefer the ones with the most installs and a readable source;
read the source before `paseo plugin add` (a Sonnet subagent can summarise it).

G4. Order 11 (ask before changing code outside djbclark-ade) applies to
`~/.local/bin` links, `~/.claude` settings, launchd jobs and Paseo settings:
every such change is a request to the operator, listed in the slice report,
never done by a subagent.

G5. The cloud clone is shallow and cannot see the Mac: history-dependent
steps (`git subtree split`, lessons) need `git fetch --unshallow`; anything
that needs the Mac (plugin install, launchd, `paseo` daemon) is an operator
step in the brief.

## H. Questions for the operator (answer before Wave 2; each changes the ledger)

H1. **Claude-only going forward, or only for this clean-up?** If Claude-only
in general, E7 collapses to one skill and E9 deletes the other TUIs' support
(roughly 15k lines of code and tests, plus `agents/` templates). If other
vendors stay for routing, E7 and E9 keep their multi-vendor shape and only lose
the unverified parts. The first pass assumed the former; say which.

H2. **Name and home of the new repo for E1** (suggested: `djbclark/djbclark-skills`,
MIT, same `skills/<name>/SKILL.md` layout, installed with `npx skills add`), and
whether the Hermes-box admin tools (`change-hermes*`) go there or to `~/ops`.

H3. **Which Paseo plugins may be installed** (D2; each is trusted daemon code):
the lead's shortlist, by install count and fit, is `omercnet/tell-agent`,
`fullstackhouse/asks`, `dennyferra/baton`, `aborakati/usage-monitor`,
`tomgrin10/session-guard`, `tomgrin10/vitals`, `gpambrozio/skills`,
`omercnet/pr-radar`, `sm1ee/session-recovery`. Yes to all, a subset, or "read
the source and come back per plugin".

H4. **Skill sync:** adopt `vercel-labs/skills` (`npx skills add
djbclark/djbclark-ade`) and delete `skill-everywhere`? The alternative is
`agentsync` (symlinks, closer to what `skill-everywhere` does).

H5. **Copying code or adopting whole:** none is strictly needed; the only
candidates are `ccusage` (quota and cost reading, MIT) and
`cross_agent_session_resumer` (only under multi-vendor). Default: adopt neither;
use `paseo usage`.

H6. **Dormant or shadow pieces** with no verified reader: `jev` (shadow since
2026-10-11), `skillopt-night` (nightly skill edits), `prior_art_nudge` (shadow
telemetry), `herdr-sleeper` (waiting on the D0.2 drain), `ade-backup-stores`.
Default: DELETE jev and prior_art_nudge, keep skillopt as a Paseo schedule
only if you still read its output, keep ade-backup-stores.

H7. **Final landing:** one PR from `slim/2026-11` to master at the end (branch
protection), or you lift protection for one fast-forward? The PR route also
keeps the adversary marker and a Claude local review as the gate.

H8. **Review rules after the slim-down:** keep the machine-readable adversary
marker (rule 1) with a Claude reviewer writing it, drop the Codex rules (9, 11)
entirely, keep changelog fragments (10)? The lead's recommendation is exactly
that.

## I. Sources (read 2026-11-06)

paseo.sh/docs (getting started, cli, orchestration, orchestration-workflows,
skills, plugins), paseo.sh/plugins (featured, orchestration, git,
daemon-management, gpambrozio/skills), github.com/getpaseo/paseo README,
github.com/andyrewlee/awesome-agent-orchestrators, news.ycombinator.com
item 49233448 (OpenChamber thread), the Claude Code subagent guides
(hidekazu-konishi.com, promptessor.com, totalum.app, heeki.medium.com) and
aiarch.dev "Parallel AI agents on one repo", vercel-labs/skills (MIT),
ccusage.com, github.com/steipete/CodexBar, this repo's
`docs/paseo-only-rearchitecture.md` C1 table and `README.md`.
