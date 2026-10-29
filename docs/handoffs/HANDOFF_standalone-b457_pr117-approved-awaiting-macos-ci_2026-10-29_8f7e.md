---
schema_version: 1
handoff_id: 8f7e
parent_handoff_ids: [7283]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: c10d2eb9904949669e52f53e1a3b95985789ac24
created_at: 2026-10-29T12:00:00-04:00
writer: claude-code
---
# Handoff — PR 117 approved, awaiting macOS CI, then merge and register

## The Goal
Land PR 117 (nudge log plus PostToolUse support in `claude/hooks/context_size_nudge.py`), then register the PostToolUse hook in `~/.claude/settings.json` with the B4 wording fix.

## Where We Are
1. PR 117 head is `e8fa5a4ebded9966e5b3b3b14cf903e4a6cd6193` (worktree `~/src/djbclark-ade-nudge-wt`, branch `feat/nudge-log-posttooluse`). Adversary round 3 (omp Opus 5.5 high) APPROVE at that head; marker is in the PR body.
2. CI: `context-policy` pass, `pytest-linux` pass. macOS `pytest` was still pending after about 3 h (runs "Tests" queued/in_progress). Not merged.
3. djbclark said "Yes" to a squash merge pinned to `e8fa5a4` once CI is green, and "Yes, after merge" to registering PostToolUse.
4. Quota-guard is `critical` until 2026-10-30T09:59:59Z (weekly 13% left): no new Claude work, so this handoff is document-only (Step 9 skipped on purpose).
5. The worktree's `.claude/settings.json` and `.cursor/hooks.json` are graft-injected uncommitted edits: never stage them. The four modified `skills/paseo*/SKILL.md` in the main checkout belong to another session.

## What We Tried
1. Round 1 BLOCK (false cadence text, unlocked read-modify-write, window recount) repaired in 06347c7. Round 2 APPROVE with B1-B3 (boundary test, lock `O_NOFOLLOW`, orphan tmp sweep) closed in e8fa5a4 by a codex gpt-6.1-sol slice; mutants killed.
2. `gh pr checks --watch` hits the background time limit (30 min, then 2 h); it is a poor waiter for a stuck macOS job.
3. `acp-dispatch omp --perm read-only` is refused; use `--perm all` with a read-only brief.

## Key Decisions
1. djbclark chose to close B1-B3 before merging (a new commit plus round 3) rather than merge 06347c7 as is.
2. Registration is a separate follow-up after the merge, not part of PR 117.

## Decisions
- [ruling] "3. Add B1–B3 fixes first" (djbclark, 2026-10-29)
- [ruling] "Yes" to merging PR 117 pinned to e8fa5a4 once CI is green (djbclark, 2026-10-29)
- [ruling] "1. Yes, after merge" to registering PostToolUse in ~/.claude/settings.json (djbclark, 2026-10-29)
- [decision] registration PR also rewrites the "runs only when a prompt is submitted" sentence (:575) and derives the 20 s from `POST_TOOL_CHECK_SECONDS`; rejected: leaving the text; because it becomes false once PostToolUse runs.

## Relations
- continues [[HANDOFF_standalone-b457_uutils-merged-nudge-pr117-in-review_2026-10-29_7283]]
- decided_in [[HANDOFF_standalone-b457_pr117-approved-awaiting-macos-ci_2026-10-29_8f7e]]

## Evidence & Data
1. Reports: `~/.local/state/bigteam/adhoc-2026-10-28/adv-pr117-r2-report.md`; `~/.local/state/bigteam/adhoc-2026-10-29/{fix-pr117-b123,adv-pr117-r3}-report.md`.
2. Slice tests: 128 passed targeted; legacy suite 224 passed, 20 failed, all `self-slash` dry runs rejected by inherited `ACP_RUN_AGENT=1` (not yet confirmed outside dispatch).
3. Round 3 low findings, non-blocking: sweep name filter half pinned, a date-dependent test, doc glob nit, one unremovable orphan stops a sweep, sweep window is not rotating.

## Operator Feedback
Standing: ask before merging (given for 117); fix known gaps without asking.

## Where We're Going
1. Check `gh pr checks 117` and `gh pr view 117 --json headRefOid`. If the head is still `e8fa5a4` and `pytest` (macOS) passes, run `gh pr merge 117 --squash --match-head-commit e8fa5a4ebded9966e5b3b3b14cf903e4a6cd6193`. If the macOS job is still stuck, find out why (`gh run list --branch feat/nudge-log-posttooluse`), rerun, or ask djbclark; do not merge past a pending check.
2. After the merge: remove the worktree `~/src/djbclark-ade-nudge-wt` (leave graft's two dirty files out; they are disposable), fast-forward `~/src/djbclark-ade`.
3. Registration PR in a new claimed worktree: add the PostToolUse entry to `~/.claude/settings.json`, fix the B4 sentence and the hard-coded 20 s, then verify live and ping with `hermes-ping`.
4. Optional, carried: B6 (`ACP_RUN_AGENT` ignored) decision; check whether the 20 self-slash test failures occur outside dispatch.
5. Resume Claude-heavy work only after 2026-10-30T09:59:59Z; otherwise route to codex or omp.

## Detached jobs
none (fix-pr117-b123 and adv-pr117-r3 are closed; no open record owned by this session).

## Quick Start
    cd ~/src/djbclark-ade-nudge-wt && git status -s && gh pr checks 117
    cat ~/.local/state/ade/quota-guard.json
