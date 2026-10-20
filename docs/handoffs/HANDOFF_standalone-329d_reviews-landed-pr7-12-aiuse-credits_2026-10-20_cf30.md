---
schema_version: 1
handoff_id: cf30
parent_handoff_ids: [cf8f]
lineage: deterministic
chain: [standalone-329d]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 59b7960d8339f22a98f42efb2d0a1c01163d17a5
created_at: 2026-10-20T01:57:00-04:00
writer: claude-code
---
# Handoff — the in-flight review chain landed (PRs 7, 10, 11, 12; aiuse 38, 40); Phase 0 is next from a fresh session

## The Goal
Land everything the 2026-10-19 `/steps` rounds put in flight before Phase 0 of ADE-everywhere
(parent cf8f, item 1): Codex and Cursor reviewing GitHub PRs here, the load-admit gate, the threat
model, the cursor-cloud dispatch place, Claude API credits visible to aiuse and routing, and
`route_agent.py` reading aiuse's own resolver. Ruling 4-5 (djbclark, 2026-10-19): only after these
land, write a handoff, then `/new` for Phase 0.

## Where We Are
All of it is merged; nothing of this chain is open on a branch.

- djbclark-ade (master 59b7960): PR 7 load gate (776ecda), PR 10 threat model (fa1c4c9), PR 11
  cursor-cloud place + route_agent service (d6c27da), PR 12 route_agent reads
  `aiuse --available --json` (72252da). AGENTS.md rule 9 (656b65e, 6889bb4): how to read Codex's
  result. `docs/queue.md` items 1-7 under "Follow-ups from the 2026-10-20 reviews" (59b7960).
- aiuse (main 5b0b9f9): PR 38 `set-credits` override, expiry, staleness, burn nudge; PR 40 Admin API
  `cost_report` collector `aiuse refresh-credits omp` + hourly launchd template. **Not live on this
  Mac**: Homebrew 3.7.2 is installed; a `just release 3.8.0` (PyPI + Homebrew, outward-facing) and
  the launchd install from the aiuse README are djbclark's calls.
- Every merge used `gh pr merge --squash --match-head-commit <reviewed sha> --delete-branch` on an
  adversary-approved head with Codex green on that head.
- Dirty files in this checkout are other agents' (`skills/paseo*`, `skills/graft/SKILL.md`,
  `bin/graft/`, `.agents/skills/fastino-glide/`, the untracked 32c0 handoff): leave alone.

## What We Tried
1. **Codex waiters that filtered inline comments by a hard-coded UTC timestamp** (ahead of GitHub's
   clock) missed two findings on PR 10 and two on aiuse PR 38; both PRs merged past them (fixed
   afterwards: 6cf1679, aiuse PR 40). Replaced by reading findings relative to the `@codex review`
   request comment's `created_at` (AGENTS.md rule 9).
2. **A waiter regex for `codex-review-state` without the `:v1` suffix** matched nothing on PR 12 and
   ran its full 30 min although Codex had finished in 7 min. The marker is
   `<!-- codex-review-state:v1 {"code_review":{"commit_sha":…,"status":…},"security_review":{…}} -->`,
   on the summary comment that is edited in place (rule 9, 6889bb4). Waiter: `/tmp/pr12-codex-wait.sh`
   (`PR12_HEAD=<sha>`), worth moving into `bin/` (queue candidate, not filed).
3. **aiuse PR 39 was auto-closed** when its base branch was deleted after PR 38 merged; replaying its
   commits onto main conflicted, `git rebase --onto origin/main fa61877` fixed it; the prettier pre-push
   hook needed `node_modules` symlinked into the temp worktree; reopened as PR 40.
4. **PR 12 took six adversary rounds and four Codex passes.** Round 1 BLOCK (suite spawned the real
   aiuse: `test_jev` failed on any host with aiuse). Round 2 BLOCK: the per-process memo added for a
   round-1 nit had no expiry, so a blocking dispatch read start-time quota at finalize (fail-open,
   measured usage 0.0). Codex P1 after round 3: the aiuse path read `windows[]`, not the documented
   available-row contract fields (3.7.2 only happens to attach windows, which is why two live
   comparisons matched). Round 4 BLOCK: a sibling row's windows could resurrect an omitted pool (the
   adversary retracted its round-3 approval of that fold). Codex P2s: `fresh: false` ignored; invalid
   rows dropped silently then zeroed everything; `excluded[]` pools with no snapshot row unmeasured.
   Lesson: a fix that adds a cache or a filter needs its own adversary pass; "the live numbers match"
   is not proof the contract is honoured.
5. **`bg` refuses the full test suite on this Mac** (rc=3, "full suites run on CI"); the builders ran
   `scripts/github-ci-run <ref>` (overlay branch `ci/run/<slug>`) and targeted local runs instead.
6. **`gh run list --branch <feature>` shows nothing** for those overlay runs; list without `--branch`
   and match the `ci/run/...` head branch.

## Key Decisions
1. Cloud builders and sub-agents push branches and never open PRs; the lead runs the adversary and
   opens the PR with the verdict and reviewed SHA quoted (home rule 28). Kept.
2. Merge on the exact reviewed head, by me, squash, branch deleted. Kept.
3. Fable headroom (PR 12): the aiuse path reports the row's least-applicable headroom (22 live) where
   the file read gave the sublimit window's own 44, so `FABLE_MIN_LEFT=10` switches to Opus at about
   20 % of the cap. Lead kept the contract (conservative) value; **djbclark to confirm** (queue 7e).
4. An ageless or `fresh: false` aiuse payload reads unknown, never fresh (fail-safe). Rejected: trust
   ageless payloads.
5. An excluded `fable` family caps only the Fable sublimit, not the whole Claude pool (builder's
   call, accepted: fable is a sublimit family).
6. aiuse release and the launchd credits job: not run unasked (outward-facing). Codex "Path to threat
   model file" setting: only djbclark can set it.
7. Hourly credits refresh is a launchd job, never a scheduled model prompt (home rule 13).

## Evidence & Data
- PRs: https://github.com/djbclark/djbclark-ade/pull/7 , /pull/10 , /pull/11 , /pull/12 ;
  https://github.com/djbclark/aiuse/pull/38 , /pull/40 (39 closed by GitHub).
- Adversary reports: `~/.local/state/agent-reports/4d478d78-94b8-443c-8416-f4b3686c689f/`
  (`adv-route-aiuse-report.md` holds all six PR 12 rounds; `adv-threat-model`, `adv-cursor-route`,
  `adv-load-admit-2`, `adv-aiuse-credits`); builder reports beside them.
- PR 12 local targeted run at 156ff17: 394 passed, 1 skipped (opt-in live test), 3 failed; with
  `ROUTE_AGENT_OMP_READY=0`: 397 passed. The 3 failures are pre-existing on master (queue item 6).
- Claude API credits by the collector: $89.56 left vs console $95.57 (lower bound: counts all org
  spend). Grant $200 from 2026-10-13, expires 2026-11-08.
- aiuse installed here: `~/.local/bin/aiuse -> /opt/homebrew/bin/aiuse`, 3.7.2 (tap `djbclark/aiuse`).

## Operator Feedback
- Merge PRs myself on the exact green head; builders never open PRs. Secrets only via
  `sudo-secretspec` (presence by length). No exit status through a pipe. `git commit -- <paths>`.
  Numbered lists, never restarting at 1. URLs as markdown links. `hermes-ping` on completions.
- 2026-10-19 `/steps` answers: 4-1 Bugbot off; 4-2 cursor-cloud builder; 4-3 threat model; 4-4 aiuse
  omp staleness + expiry in one Sonnet slice; 4-5 Phase 0 only after the in-flight items land, then
  handoff and `/new`.
- Use paid-for cloud agents first (memory `feedback_use_paid_cloud_agents`).

## Where We're Going
1. **NEXT: Phase 0 of ADE-everywhere as a PR set, from a fresh session** (parent cf8f item 1 is
   unchanged: read `docs/ade-everywhere-proposal.md` §8 Phase 0, §4.4, §6.1 G16, T1; one PR per
   slice, adversary verdict quoted, `acp-dispatch --kind` on Sonnet 5.5 / Codex per §11.2; nothing
   deleted in Phase 0).
2. Decisions for djbclark (also in memory `project_2026-10-20_merges_and_pending_operator_actions`):
   (a) `cd ~/src/aiuse && just release 3.8.0`, then install the launchd refresh per the aiuse README
   (`install -m 755 packaging/launchd/aiuse-credits-refresh ~/.local/bin/`, gsed the
   `@REFRESH_BIN_PATH@`/`@AIUSE_BIN_PATH@` placeholders into
   `~/Library/LaunchAgents/com.djbclark.aiuse-credits-refresh.plist`, `launchctl bootstrap gui/$(id -u) …`);
   verify with `aiuse --version` and `launchctl print gui/$(id -u)/com.djbclark.aiuse-credits-refresh`;
   (b) paste `docs/threat-model.md` into Codex's "Path to threat model file"; (c) confirm the Fable
   headroom ruling (Key Decisions 3).
3. Queue items (`docs/queue.md`, "Follow-ups from the 2026-10-20 reviews"): 1 firecrawl-router
   serve-only `--listen`; 5 endpoint variables can send keys anywhere; 6 pin `ROUTE_AGENT_OMP_READY`
   in `tests/conftest.py`; 7 PR 12 carried nits incl. `acp-dispatch aiuse_reset_time` still reading
   `latest.json`; 3 and 4 load-gate / cursor-cloud follow-ups.
4. Carried loose ends from cf8f item 3 (broken links in `home-agents.md`, stale `vendor/README.md`,
   other agents' untracked files here): unchanged.

## Detached jobs
none (no bigteam job records are owned by this session; the Codex waiters and test runs were
`run_in_background` children and are finished).

## Quick Start
```bash
cd ~/src/djbclark-ade && git pull --ff-only && git log --oneline -5
aiuse --version                       # 3.8.0 means the release landed
aiuse --available --json 2>/dev/null | jq '.age_seconds, .fresh'
bin/route_agent.py plan --json | jq .quota_source
gsed -n '/^## Follow-ups from the 2026-10-20 reviews/,/^## /p' docs/queue.md
gsed -n '/^## 8/,/^## 9/p' docs/ade-everywhere-proposal.md | ghead -80   # Phase 0
```
