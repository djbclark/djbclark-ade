# Check-in rulings (2026-11-06, batch 1 of N)

Read from `docs/checkins/` on branches `claude/ade1-9orwfa`, `checkin/01BvGHLz`,
`checkin/01BvGHLy`, `checkin/01BvGHM3`, `checkin/7c58015b`. A ruling here is the
slim-down lead's intake decision (what the slim branch takes, what it waits
for, what it leaves); closing or merging a PR is the operator's action, listed
under "Operator does".

Legend: LAND = land on master by its own PR before the slim branch rebases;
PARK = leave the branch and PR open (draft), decide in the named wave; DISCARD
= nothing taken, close the PR, keep the branch until Wave 6; TAKE = the slim
branch cherry-picks the named files.

## R1. ade1 lead, session 01BvGHLzKz, branch `claude/ade1-9orwfa`

- Commit 0cbeb70 (`.claude/settings.json` replaced wholesale, graft status
  line and allows dropped): DISCARD. The operator's unattended-permission
  rules are worth having, but merged into the file, not over it; the slim
  branch will do that in E11 from the original plus the script's additions.
- Report: taken (this file cites it). Session: STOP.
- Operator does: nothing; the branch can be deleted after Wave 6.

## R2. Issue 284, session 01BvGHLzD4, PR 289, branch `claude/issue-284-ndc-oslo-ideas`

- Ruling: FINISH-FIRST, then LAND, then STOP. The three open findings are
  real bypasses of a security hook (`claude/hooks/secret_read_gate.py`:
  symlink-then-`..`, `*** Begin Patch` wrapped Bash, rg 15.2 `sh` type
  includes `.env`); a known-bypassable deny gate does not merge. About one
  hour plus one adversary round, per the report.
- Why land rather than park: five new pieces (`instruction-lint`,
  secret-read-deny, `post-edit-check`, `/steps plan`, `ade-retro`) are policy
  layer, not harness glue; none depends on a deletion target. The slim-down
  will later strip the Codex `apply_patch` paths from the gate and
  `post-edit-check` only if and when Codex is retired (J2; "Claude-only" is
  this work, not the fleet), and (Wave 3, D8) decide whether `ade-retro` runs
  as a Paseo schedule. `instruction-lint` is useful to the E11 docs sweep
  itself.
- Dependency: `agents/claude/settings.json.tmpl` and
  `tests/test_secret_deny_repo.py` move together if `agents/` ever moves; the
  plan keeps the surviving providers' templates (E9), so no conflict.
- Operator does: tell the session to fix the three findings and refresh the
  marker; rule on the `/retro` title-trust thread; merge #289 with
  `--match-head-commit`.

## R3. Issue 279, session 01BvGHLy, PRs 291 / 293 / 292

- **PR 291** (`bin/ade-sched`, `ade_sched.py`, deadline and pr-policy install
  on Linux): LAND, then STOP. `deadline` and `pr-policy` are KEEP (E5, E8);
  Paseo schedules start agents, not a 60-second shell sweep, so a scheduler
  for the kept launchd jobs is not covered by Paseo. Needs a fresh adversary
  confirm on 6d9a647 plus CI and Codex on that head (30–60 min). Merge it
  first: #293 is stacked on its branch (never delete `-1-sched` before GitHub
  retargets #293).
- **PR 293** (load-watch, proc-cpu-watch, context-budget-check,
  claude-quota-guard through ade-sched): PARK until Wave 3 (E5) and Wave 4
  (E7) decide those four tools. Every file it touches is a REPLACE or DECIDE
  target. If load-watch survives trimmed, cherry-pick its ade-sched install
  hunk then; the rest goes with the tools.
- **PR 292** (exit-69 guards in acp-dispatch, codium-ai, app-tamer-ab,
  paseo-set-model; coding-bot clipboard; skill-everywhere root): DISCARD.
  acp-dispatch (E6), codium-ai and app-tamer-ab (E1), paseo-set-model (E4),
  coding-bot (J2a) and skill-everywhere (E10) are all deletion or replacement
  targets; porting them to Linux is work the slim-down undoes. Nothing to
  cherry-pick.
- Combined branch `claude/issue-279-linux-ports`: superseded; keep until
  Wave 6.
- Operator does: re-run the confirm and merge #291; mark #293 draft; close
  #292 with a comment pointing here.

## R4. Issue 278, session 01BvGHM3, PR 290, branch `claude/issue-278-checkpointing`

- Ruling: PARK (draft) until Wave 3, where D3/D11 evaluate native Paseo resume
  and `sm1ee/session-recovery` on the Mac. Reason: the operator's own route
  order (2026-11-05: native resume, then the session-recovery plugin, then a
  new passive plugin) was not exhausted; the plugin was built as the interim
  third step before the first two were tried live, and it is 3.3k lines of
  TypeScript plus 270 tests that are installed nowhere. That is the pattern
  the slim-down exists to stop. Nothing is lost by parking: it is all on the
  branch and in the PR, with a stale marker that will need refreshing anyway.
- TAKE now: `docs/checkpoint.md` section F (the inventory of what Paseo
  provides natively, 2026-11-04) is exactly the input Wave 3 needs; the slim
  branch cherry-picks that section into `docs/slim/` as evidence, with its
  date.
- If Wave 3 finds the gap is real (native resume plus the plugin cannot say
  "this turn was interrupted mid-write"), land #290 then, refreshed.
- Operator does: mark #290 draft; this is also plan question J9 of PLAN.md,
  answer it if you disagree.

## R5. HELM LEAD, Paseo agent 7c58015b (omp, Opus 5.5), PRs 261 / 270 / 294

- **PR 261** (relay question ledger in `relay.py`, 1.7k lines): DISCARD.
  `session-finder/relay.py` is a REPLACE target (E3); the durable ledger of
  operator questions is what `fullstackhouse/asks` and native `paseo permit`
  provide (D2 row 2). Loss: three repair rounds of slice work, all on the
  branch.
- **PR 270** (`bin/quota-surplus`, "use it or lose it" watchdog on
  `route_agent.py` and `aiuse`): PARK until J2 and D4. `route_agent.py` is
  KEEP (E7), so the PR can land on the trimmed router if `session-guard` /
  `usage-auto-resume` do not already cover "spend before reset"; if they do,
  DISCARD. local-review was clean.
- **PR 294** (`skills/helm/lead.md` stagger rule, 7 lines): DISCARD with
  helm (E4). If the operator wants the rule kept, it is one sentence in the
  rewritten `docs/orchestration-practices.md` (E11).
- `skills/helm/lead.md`, `/watch lead`: go with helm and watch (E4, E5).
- Out-of-repo footprint (site-public `home-agents.md`, site-private memory,
  aiuse 3.13.1, one-offs `oc-go-key-idle`): not this repo's; noted.
- Running: `stop-broadcast.py` ends by itself. Agent: STOP after it ends.
- Operator does: close #261 and #294; mark #270 draft; after Wave 6,
  `git worktree prune` on the Mac (`git worktree list` has 89 entries,
  2026-11-06, most of them stale).

## R6. Still outstanding (batch 2)

The HELM LEAD report names `acp-dispatch-wait` processes under `tui-retire/`,
`tendcf-*` and `fork-cmdb-*` that belong to other sessions, and the Paseo and
herdr agents its stop-broadcast reached. No check-in from any of them yet.
Wave 1 does not start until they report or the operator declares them
stopped.

## R7. What the slim branch takes from batch 1

- `docs/checkpoint.md` section F (from PR 290's branch), into `docs/slim/`
  as Wave 3 evidence.
- The five check-in reports themselves, merged into `docs/checkins/` on the
  slim branch so the record is in one place.
- Nothing else until #289 and #291 land on master, after which the slim
  branch rebases on master and inherits them.

## R8. Open PRs no check-in covers (live list 2026-11-06; provisional, the owner may still report)

| PR | Branch | Touches | Provisional |
|---|---|---|---|
| 194 | `finder-consent-agents-cleanup` | AGENTS.md: drop date annotations and incident narratives | DISCARD; E11 rewrites AGENTS.md wholesale, and this would conflict with every slice |
| 208 | `astra-readonly` | acp-run / acp-dispatch read-only advise slices | DISCARD (E6 deletes both) |
| 227 | `bottom-config-uncapped-command` | bottom-config doc | DISCARD here; E1 moves `bottom-config` to site-djbclark, re-apply the one hunk there if still wanted |
| 231 | `mds-client-probe` | load-watch mds probe | PARK with #293 (E5) |
| 254 | `habits-gate-subshell` | `bash_habits_gate` parsing fix | LAND if small and green (a Claude hook, KEEP), else PARK to Wave 5 |
| 256 | `open-clean-env` | `bin/open-clean`, launch apps without the agent env | PARK; a Mac-only utility, decide in E1/E2 audit (likely MOVE to site-djbclark) |
| 260 | `route-repo-scope` | route_agent per-repo pools (opencode-go) | PARK: `route_agent.py` is KEEP (E7); land after the registry switch if opencode survives J2, else drop the opencode-go rules and land the rest |
| 269 | `coding-bot-peer-link` | coding-bot over peer-link | TRANSFER, then close: the operator ruled (consolidated report E9j) that the wrapper is re-homed into frdminc/peer-link with one repair round there, `~/.local/bin/coding-bot` and home-agents.md item 40 repointed, and a short `tell-coding-bot` pointer skill kept here; the slim branch takes nothing from the PR but keeps the branch and worktree `~/src/djbclark-ade-cb-pl-wt` until the transfer lands (superseded the earlier DISCARD, 2026-11-06, Codex P2 on PR 295) |
| 281 | `fix/opencode-bridge-econnrefused-guard` | opencode-plugin-guard | PARK per the operator's E9c answer ("wait until after the split; its fate follows whether opencode support survives"), not DISCARD |

Operator does: nothing yet; J2 is answered by rule; each row's provider condition is settled by the Wave 1 pool audit. If an owner reports, its ruling supersedes this row.
