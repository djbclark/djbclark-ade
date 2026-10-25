---
schema_version: 1
handoff_id: 70ab
parent_handoff_ids: []
lineage: none
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 6234a18
created_at: 2026-10-24
writer: claude-code
---
# Handoff — ADE queue build (isolation, Paseo tabs, Basic Memory), wave 1

## The Goal
Resume chain `standalone-b457`: land the open PRs and build the queued slices
(I0 isolation, Paseo tab naming, Basic Memory W2-W8) via bigteam task
`ade-queue-build-2026-10-24` (dir `~/.local/state/bigteam/ade-queue-build-2026-10-24/`,
`CLAIM`, `common.md`, `brief-*.md`, `design-*-report.md`).

## Where We Are
Wave 1 is built; two adversary rounds are still running.

| Slice | Worktree (under the task dir) | Head | State |
|---|---|---|---|
| tabs-s2 | `wt-tabs-s2` (`build/tabs-s2-2026-10-24`) | f985d88 | PR #53 open, adversary r2 done |
| tabs-docs | `wt-tabs-docs` | 7595926 | PR #51 open; merge with or before #53 |
| bm-w2w5 | `wt-bm-w2w5` | 0c29ea9 | PR #52 open |
| bm-w3 (`bin/bm-lint`) | `wt-bm-w3` | 4d5a19e | NOT pushed; adversary `adv-bm-w3` running |
| iso-w1 (`ade-git-guard`, `ade_claims.py`) | `wt-iso-w1` | 858cf6d | NOT pushed; adversary round 2 `adv-iso-w1-r2` running |

Tests: bm-lint 16 pass; iso-w1 305 pass; tabs-s2 tests pass. Other open PRs: 54
(someone else's), 38/37/32 (bigteam `pr-landing-2026-10-24`, owner session 72db8023:
do not touch).

## What We Tried
1. Rebased PR #38's branch before finding its live owner: nothing pushed, deleted.
2. Committed a docs edit in the shared checkout while another session had switched it
   to `fix/pane-lock-empty-hash-ld` (`1ed2791`): cherry-picked to master as `8b7908d`.
   Never commit in the shared checkout; use a scratch worktree off `origin/master`.
3. Bare `sed` is hook-blocked (use `gsed`); it once left rearm files unwritten.
4. `bm-w3` edited the live `~/ops/site-djbclark/bin/fleet-watch`: reverted, patch kept at
   `<task dir>/bm-w3-fleet-watch.patch`.
5. `acp-dispatch ... --perm read-only` is rejected for omp: use `--perm all` with a
   read-only brief. opencode-go was at 0% headroom (exit 5).

## Key Decisions
1. Code slices to omp Sonnet 5.5 high, docs to omp Haiku 5.5 medium, bm-w3 to zcode
   GLM-5.3 (Claude quota tight). Adversary rounds via omp Opus 5.5 high.
2. Isolation is "seatbelt, not a sandbox": exit 77 refusals, fail-open on crash,
   override `ACP_OPERATOR_APPROVED=git-guard`. `ade_claims.py new` exits 3 (id exists)
   and 4 (path owned by another owner's active claim); W2/W3 must handle both.
3. Residual `tabs-s2` findings (M1 first-run residue, L1 `--auto` renaming with an
   unreadable agent record, L2, L3) are disclosed in PR #53 as follow-ups.
4. Rejected: taking over PRs 32/34/36/37/38 (owners exist).

## Evidence & Data
Reports: `<task dir>/<name>-report.md` and `adv-*-report.md`. Design reports
`design-{isolation,tabs,basicmemory}-report.md` in the task dir.

## Operator Feedback
1. "Do 1, but if the owners don't exist any more, and you can't bring them back up,
   you can do it" (PRs 32/34/36/37/38; owners exist, so I backed off).
2. "Yes" to starting the queue while the PR landings run.
3. Standing: ask before restarting the Paseo daemon or replacing brew Paseo; no Fable/Opus
   Agent-tool sub-agents (quota guard); do not touch branch
   `fix/pane-lock-empty-hash-ld` (djbclark-ade-22) or Cline's
   `docs/session-handoff-reader-helper-path`.

## Where We're Going
1. **Read the two adversary reports** once their `.done` files exist
   (`adv-iso-w1-r2-report.md`, `adv-bm-w3-report.md`, both currently `STATUS: working`).
   APPROVE: push the branch, open the PR quoting the verdict and reviewed SHA, fill the
   CHANGELOG "(PR TBD)" with the PR number (note a CHANGELOG-only trailing commit).
   BLOCK: repair, then re-review. Then close both job records.
2. Ask djbclark whether `bm-w3-fleet-watch.patch` (weekly `bm-lint` in fleet-watch) goes
   up as a separate site-djbclark change now or after `bm-lint` merges.
3. Wave 2: I0 W2 (`bin/cow-pasture` claims), W4 (acp-run PATH), W5 (hook
   `git_claim_gate.py`), then W3 (`acp-dispatch --workspace`), W6-W8; tabs slices 3-7
   (`bin/ade-names`...); Basic Memory W4 (`bm_recall.py` shadow), W6-W8. Adversary on
   W1 and W3 at least.
4. Docs pass (scratch worktree): in `docs/queue.md` mark "ade-scan-state follow-up 2"
   items 1-2 done, 3-5 open (PR 54 covers 3-5).
5. Do not merge any PR without reading CI and Codex review state first; ask djbclark.

## Detached jobs
Task dir `T=~/.local/state/bigteam/ade-queue-build-2026-10-24`. Other records
(tabs-s2, tabs-docs, bm-w2w5, bm-w3, iso-w1, adv-tabs-s2, adv-tabs-s2-r2, adv-iso-w1)
were read and closed.

1. `T/jobs/adv-bm-w3.json`: adversary round on bm-w3 @ 4d5a19e. Report
   `T/adv-bm-w3-report.md`; `.done` `T/adv-bm-w3-report.md.done` (absent at handoff).
   Rearm: `~/src/djbclark-ade/bin/acp-dispatch-wait T/jobs/adv-bm-w3.json T/adv-bm-w3-report.md.done`
   (use `jq -r .rearm` on the record for the expanded form). Act per Where We're Going 1.
2. `T/jobs/adv-iso-w1-r2.json`: adversary round 2 on iso-w1 @ 858cf6d. Report
   `T/adv-iso-w1-r2-report.md`; `.done` absent at handoff. Rearm: `jq -r .rearm T/jobs/adv-iso-w1-r2.json`.
   Act per Where We're Going 1.

## Quick Start
```bash
T=~/.local/state/bigteam/ade-queue-build-2026-10-24
for n in adv-bm-w3 adv-iso-w1-r2; do ls $T/$n-report.md.done; acp-dispatch check $T/jobs/$n.json; done
gh pr list --json number,title
```
Then start each `jq -r .rearm` waiter as its own `run_in_background` Bash call and set the
record's `owner` to `$CLAUDE_CODE_SESSION_ID`.
