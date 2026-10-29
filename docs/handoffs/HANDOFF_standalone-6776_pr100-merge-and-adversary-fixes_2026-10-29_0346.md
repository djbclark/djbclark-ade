---
schema_version: 1
handoff_id: 0346
parent_handoff_ids: [6776]
lineage: deterministic
chain: [standalone-6776]
repo: djbclark-ade
workspace: djbclark-ade-zz-probe-wt
branch: zz-probe-archive
head_sha: fbcbfadfc5fa1aa8636b74d52837fef9d9b73f15
created_at: 2026-10-29T05:20:00-0400
writer: claude-code
---
# Handoff — PR 100 merge race and adversary repairs

## The Goal
Land PR 100 ([djbclark/djbclark-ade#100](https://github.com/djbclark/djbclark-ade/pull/100)): `paseo-new-seat --probe`, `bin/pytest`, and `bin/watch` archiving of retired `x ...` agents, with the adversary's findings fixed. djbclark approved the squash merge ("1. Squash-merge now", 2026-10-29); that approval covers the same merge on a newer head.

## Where We Are
PR 100 is open at head `fbcbfad` (branch `zz-probe-archive`, worktree `/Users/djbclark/src/djbclark-ade-zz-probe-wt`, clean, pushed). The PR body carries `adversary-verdict:v1` APPROVE naming `fbcbfad`, with a note that the code was reviewed at `7453d77` (round 3) and later commits are tests, docs, a `TypeError` catch and three merges of master.
CI: the last full green run was on `51d0a13` (pytest 25m13s, pytest-linux 16m53s, context-policy). After that, master moved a third time (PR 117, `870dde7`), so `fbcbfad` re-runs CI (about 25 minutes). The merge to master has NOT happened.

## What We Tried
1. First merge attempts failed three times with "Pull Request has merge conflicts": master moves every few hours (CHANGELOG and docs are shared files), and a 25-minute CI run is long enough for master to move again. Each time the fix was `git merge origin/master` in the worktree, keep both sides, test, push, re-point the marker. Conflicts so far: `CHANGELOG.md` (all three times), `bin/paseo-new-seat` (kept probe code plus master's `default_mode`), `docs/context-hygiene.md` (kept `bin/pytest` on the first test line plus master's added lines).
2. My mutation check through `bg python3 script` was refused by `bg` (exit 3, targeted runs only); running the script directly worked. Bare `python3 -m pytest` has no pytest: use `bin/pytest`.

## Key Decisions
The replaced holder of `up --force` is never archived (djbclark's option 1); its id is recorded in `~/.local/state/watch/kept.json` under an flock, and an unreadable file makes both sweeps archive nothing. Both sweeps re-read an agent's name and status just before archiving. Watcher consolidation into one tab was declined (leave as is).

## Decisions
- [ruling] "1. Never archive replaced holders (Recommended)" (djbclark, 2026-10-28)
- [ruling] "Yes, fix the gaps. I always want you to fix gaps without asking unless the fixes would be especially expensive in terms of tokens/money" (djbclark, 2026-10-28)
- [ruling] "1. Squash-merge now (Recommended)" for PR 100 (djbclark, 2026-10-29)
- [decision] a `--force`-replaced holder is recorded in kept.json and never archived; rejected: archiving it and rewriting SKILL.md; because it would archive an operator's own interactive session.

## Relations
- continues [[HANDOFF_standalone-6776_zz-probe-and-watch-archiving_2026-10-28_6776]]
- decided_in [[HANDOFF_standalone-6776_pr100-merge-and-adversary-fixes_2026-10-29_0346]]

## Evidence & Data
Adversary reports (omp, Opus 5.5 high): `~/.local/state/bigteam/adhoc-2026-10-28/adv-pr100-report.md` (BLOCK, 6998c44), `adv-pr100-r2-report.md` (APPROVE, b86797d), `adv-pr100-r3-report.md` (APPROVE, 7453d77). Job records are closed. Local tests on the branch: 45 passed (`tests/test_watch.py`, `test_paseo_new_seat_probe.py`, `test_paseo_new_seat_mode.py`, `test_bin_pytest.py`). Mutation check: with the kept.lock flock removed, the 32-process concurrency test failed 4 of 4 runs.
Known leftovers (adversary-rated informational): an unreadable kept.json exits 0 with a log line only; the stale-snapshot re-read in `archive_if_idle` has no test (the stub re-reads state on every call).

## Operator Feedback
Standing: fix known gaps without asking (memory `feedback_fix_gaps_without_asking.md`). The Claude subscription is critical (weekly 13% left, reset 2026-10-30T09:59Z): continue on omp (`omp/anthropic/claude-sonnet-5-5`), no Fable/Opus Agent-tool sub-agents, no `acp-dispatch claude`. Peer `1b6c5412` (omp, relay-ack-pr87-pt) confirmed the guard text is subscription-only.

## Where We're Going
1. Check PR 100: `gh pr view 100 --repo djbclark/djbclark-ade --json headRefOid,mergeable` and `gh pr checks 100 --repo djbclark/djbclark-ade`. If the head is still `fbcbfad`, all three checks pass, and it is MERGEABLE: `gh pr merge 100 --repo djbclark/djbclark-ade --squash --match-head-commit <that head>`.
2. If master moved and the PR conflicts again: in the worktree `git merge --no-commit --no-ff origin/master`, keep both sides of additive conflicts (read code conflicts, run the four test files via `~/ops/site-private/bin/bg bin/pytest ...`), `git-commit-own --staged`, push, rewrite the marker's `head` in the PR body (`gh pr edit 100 --body-file`), wait for CI, repeat. The marker must name the exact current head.
3. After the merge: `git worktree remove ../djbclark-ade-zz-probe-wt` (and delete the branch), `hermes-ping "djbclark-ade: PR 100 merged <sha>"`, and update this chain's Tier 1.
4. Verify the relay ack to `1b6c5412` (id `20261029-045432-e9d994`, queued because its omp agent was working): `python3 ~/src/djbclark-ade/skills/session-finder/relay.py --pending --text`. If still unsent after the agent idles, check its transcript, then re-send; report to djbclark if unreachable.
5. Optional low-severity follow-up (do it, per the standing rule, unless costly): make an unreadable kept.json exit non-zero or warn on stderr; add a test for the `archive_if_idle` re-read.

## Detached jobs
none (the three adversary job records were closed 2026-10-29).

## Quick Start
```bash
cd ~/src/djbclark-ade-zz-probe-wt && git status -sb && git log -3 --oneline
gh pr checks 100 --repo djbclark/djbclark-ade
```
