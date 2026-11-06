# Resume state: issue #279 / PR #291 (01BvGHLy, cancelled 2026-11-06 ~16:25 UTC)

Snapshot taken at cancel time. Re-read live state before acting on any of it.

## PR #291: claude/issue-279-linux-ports-1-sched → master
- **Head**: `e95816ebf83b36d388243d142839134dba79b4f8`. Mergeable: yes. `mergeable_state` read `unstable` only because CI was still running.
- **Commits since the last check-in (6d9a647)**:
  - 391c698: a Day+Weekday calendar entry renders two `OnCalendar=` lines (Codex P2). Cron runs do `mkdir -p ~/.local/state/ade` before `flock -n` (adversary C1).
  - e95816e: docs/scheduling.md updated to match (fixes the adversary's BLOCK on 391c698).
- **Checks on e95816e at cancel time**:
  - `pytest-linux`: **in progress** (not finished).
  - `context-policy`: success.
  - `pytest`: skipped (macOS leg, dispatch-only).
  - Cursor Approval Agent: success.
  - Cursor Security Agent: success.
- **Codex (GitHub) on e95816e**: code review completed, no findings ("Didn't find any major issues"). Security review completed, no issues. Marker: `has_unresolved_findings: false`.
- **Review threads**: 0 unresolved. All 6 Codex threads on earlier heads were fixed and resolved.
- **Adversary marker in the PR body**: `<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"e95816ebf83b36d388243d142839134dba79b4f8"} -->`. This matches the current head.
- **Local Codex (`bin/local-review`)**: not run. The cloud container has no `codex` binary.
- **Master**: has moved to da6b2e7 (#288, docs only) since #291's last master merge (7626c1b). The PR is still mergeable with no conflict.

## Remaining before merge-ready
1. `pytest-linux` must finish green on e95816e. If it fails, root-cause it. Several tests also fail on master in a cloud container but pass on the CI runner, so compare against master first.
2. Nothing else is open. Codex is clean, the adversary marker is current, and there are no threads.
3. If anything is pushed, the head moves and all of these must be redone: the adversary confirm, the marker refresh, `@codex review`, and CI.
4. The lead merges with `gh pr merge 291 --squash --match-head-commit e95816ebf83b36d388243d142839134dba79b4f8`. Remove the branch only after `gh pr view 291 --json state` reads MERGED, and not before #293 is dealt with (see below).

## #293 (claude/issue-279-linux-ports-2-monitors): DRAFT, stacked
- Head `58c5d9e`. Base `claude/issue-279-linux-ports-1-sched`.
- The operator ruled it draft: do no work on it.
- It does not have #291's last two commits (391c698, e95816e).
- If #291 merges and its branch is deleted, GitHub closes #293. Retarget #293 to master first, or keep the -1 branch.

## #292 (claude/issue-279-linux-ports-3-guards): CLOSED
- Head `e232f88`, closed by the operator's slim-down ruling. Nothing to do.

## Commands to resume
```sh
git fetch origin
gh api repos/djbclark/djbclark-ade/commits/e95816ebf83b36d388243d142839134dba79b4f8/check-runs --jq '.check_runs[]|"\(.name): \(.status) \(.conclusion)"'
gh api repos/djbclark/djbclark-ade/pulls/291 --jq '"head=\(.head.sha) mergeable=\(.mergeable) state=\(.mergeable_state)"'
gh api repos/djbclark/djbclark-ade/pulls/291/ccr/review_threads --jq '[.[]|select(.resolved==false)]|length'
gh api repos/djbclark/djbclark-ade/pulls/291 --jq .body | grep -o 'adversary-verdict:v1 {[^}]*}'
# or: bin/pr-wait 291   (aggregates CI + Codex for the exact head)
# then the lead: gh pr merge 291 --squash --match-head-commit e95816ebf83b36d388243d142839134dba79b4f8
```
Worktrees used in the cancelled session (cloud scratchpad, gone with the container): wt1 (-1-sched), wt2m (-2-monitors), wt3 (-3-guards), wtcheckin (checkin/01BvGHLy). All were clean and pushed at cancel time.
