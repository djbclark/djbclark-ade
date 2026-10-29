---
schema_version: 1
handoff_id: 4496
parent_handoff_ids: [1513]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 07894079af22c3a4274810a093bef6f3cadc85a5
created_at: 2026-10-28T20:15:00-04:00
writer: claude-code
---
# Handoff — Linux CI fixed (PR 102), queue PR 99 merged, uutils port slice running, audit next

## The Goal
Work down the djbclark-ade queue: keep CI green, then the context-visibility and compact/handoff discipline audit (djbclark: "examine, search, talk, fix"), the uutils
port that lets Linux CI unpin `ubuntu-24.04`, and last the sibling `RecursionError` PR.

## Where We Are
1. PR 99 merged as `0789407` (three `docs/queue.md` entries: context-visibility audit, uutils port, sibling `RecursionError` readers). Pinned to `834be6a`, CI 3/3.
2. PR 102 merged as `962a463`: `pytest-linux` and `context-policy` pinned to `ubuntu-24.04`. Root cause of the red Linux CI on master (1f56db3, cf00dfb) and PR 99:
   `ubuntu-latest` became ubuntu-26.04 on 2026-10-28, whose coreutils are Rust uutils multicall binaries; the workflow's `ln -sf $(command -v tool) ~/.local/bin/g<tool>`
   symlinks fail ("Requested utility 'gtr' does not match executable name"): run 40723793153 showed 90 failed, 5814 passed in 29m32s. Last green run 40669526660 was on 24.04.
3. The queue-worktree and CI-pin worktrees are removed. The relay `tx: null` item the last handoff listed was already done (queue item 9, PR 87); not re-queued.
4. `.claude/settings.json` dirt in `~/src/djbclark-ade` was graft re-adding project hooks; `graft-hook-guard.sh` strips them in the background each session (log
   `~/.local/state/graft-hook-timeout-fix.log`). Tree was clean afterwards. Nothing to do.
5. A named ack went to bb2a32df through `relay.py` (`delivered`). Its PR 101 (relay `ack_token`, 4 lines) is theirs; no objection sent, no action owed.
6. Uutils port slice RUNNING (codex `gpt-6.1-sol`, medium, `--kind code`, detached): worktree `~/src/djbclark-ade-uutils-wt`, branch `ci/uutils-port-2026-10-28`, brief
   `~/.local/state/ade-briefs/uutils-port-2026-10-28.md`. It pushes its branch but opens no PR and merges nothing; the lead opens the PR.
7. Tests run this session: none locally (docs and CI changes only); CI evidence above.

## What We Tried
1. Rerunning the cancelled `pytest-linux` job twice (PR 99): cancelled at the 30 min cap, then 90 real failures. A rerun cannot fix an image change; the first log read showed
   "REFUSED after 900s" waits and I had called it a hang or flake before reading the failing log. Retracted: it was a systematic runner-image change.
2. `gh api .../jobs/ID/logs` returns nothing for a cancelled job; `gh run view RUN --job ID --log` works once the job has completed (needs no `--allow-escape-sequences`).

## Key Decisions
Gitignoring `.claude/settings.json` (djbclark's question) was not done: the file is tracked on purpose (statusLine, permissions) and the guard strips the duplicate hooks
already. For the Linux CI I pinned the image rather than editing the suite, as the stopgap; the real port is the running slice. CI-only PR 102 skipped the adversary round and
the CHANGELOG, and djbclark merged it on that basis. For the uutils slice the router picked codex (98% headroom) because Claude is tight (79% weekly, projected 112%).

## Decisions
- [decision] Pin the Linux CI jobs to ubuntu-24.04 as a stopgap; rejected: leaving ubuntu-latest and fixing the suite first; because master was red and every PR blocked; in [PR 102](https://github.com/djbclark/djbclark-ade/pull/102).
- [decision] Route the uutils port slice to codex gpt-6.1-sol at medium; rejected: a Claude or omp Sonnet slice; because Claude is tight and codex has 98% headroom.
- [ruling] "3. Both in parallel" for the audit and the uutils port (djbclark, 2026-10-28)
- [ruling] "1. Squash-merge PR 102 (Recommended)" (djbclark, 2026-10-28)
- [ruling] "1. Squash-merge PR 99 (Recommended)" (djbclark, 2026-10-28)
- [ruling] "2. Leave it, and find why the guard did not strip it" (djbclark, 2026-10-28)

## Relations
- continues [[HANDOFF_standalone-b457_pr98-recursion-merged-queue-next_2026-10-28_1513]]
- decided_in [[HANDOFF_standalone-b457_linux-ci-fixed-uutils-slice-running_2026-10-28_4496]]

## Evidence & Data
Failing-test tally on 26.04: test_ade_git_hooks 16, test_self_slash 14, test_self_slash_codex 12, test_acp_dispatch 6, test_wait_file 3, others 1-2. Job durations:
24.04 `pytest-linux` 15-21 min; macOS `pytest` 27-31 min (cap 45). Job log command: `gh run view 40723793153 --job 123117608064 --log`.
Audit measurements (2026-10-27): 48 auto-compactions Oct 23-27 at ~267k, one self-slash `/compact`, 27 handoff cycles, Paseo meter ignores `autoCompactWindow` 300000
(getpaseo/paseo#4949). Brief: `~/.local/state/ade-briefs/context-visibility-and-handoff-audit-2026-10-27.md`.

## Operator Feedback
djbclark chose both audit and uutils in parallel; asked whether the settings.json noise should be gitignored (answered no, with reasons).

## Where We're Going
1. THE next action: the context-visibility audit, in this order from the queue entry in `docs/queue.md` ("Context visibility in Paseo and compact/handoff discipline"):
   (a) read `~/.claude/state/context-nudges.json` against the 35 sessions that peaked at 200-270k and the two failure classes (4 "gave up, no empty input prompt seen",
   2 failed successor launches); (b) web search first (how others show live per-agent context, Paseo plans for #4949); (c) bring numbered options to djbclark before
   building; (d) fix in a claimed worktree with tests, a CHANGELOG line and an adversary verdict. Ask before touching `~/.claude/settings.json`.
2. Collect the uutils slice (Detached jobs below). When its report says CI green on 26.04: open the PR from `ci/uutils-port-2026-10-28` (fill the `(#TBD)` in its CHANGELOG
   line), run an adversary round via `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high` (workflow and script change), then ask djbclark
   before merging pinned to the reviewed head. Remove `~/src/djbclark-ade-uutils-wt` after the merge.
3. Last in the queue (djbclark ruled): the sibling `RecursionError` PR (`guard_level` in `bin/claude-fleet-governor`, `load_state` in `bin/claude-quota-guard`), failing tests
   first by forcing `RecursionError` as `tests/test_gates.py:1414` does; one adversary round.
4. Pools stay with Dann 6; the Item-32 wording and the `pkill -f` example for item 33 go to an Opus 5.5 session (I never edit `~/CLAUDE.md`).

## Detached jobs
1. Job file `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/uutils-port.json`; report `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/uutils-port-report.md`;
   `.done` `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/uutils-port-report.md.done` (not present at handoff time, slice running).
   Rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/uutils-port.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/uutils-port-report.md.done`
   (background, timeout 7200000), then `acp-dispatch check` on the record. It is the codex slice that ports the Linux suite to ubuntu-26.04; read its report, never its final message.

## Quick Start
```bash
cd ~/src/djbclark-ade
git log --oneline -4                       # expect this handoff's commit on top of 0789407
git worktree list                          # ~/src/djbclark-ade-uutils-wt is the running slice's; do not touch while it runs
acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-28/jobs/uutils-port.json
gh pr list --state open --json number,title,headRefName --jq '.[]|[.number,.title,.headRefName]|@tsv'
```
