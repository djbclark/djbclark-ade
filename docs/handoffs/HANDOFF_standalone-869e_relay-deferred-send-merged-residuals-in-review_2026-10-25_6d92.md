---
schema_version: 1
handoff_id: 6d92
parent_handoff_ids: [843b]
lineage: deterministic
chain: [standalone-869e]
repo: kool-ade
workspace: main
branch: master
head_sha: 52cff0324b1ebdef98d36b317bdecafa81429b23
created_at: 2026-10-25T01:20:00-0400
writer: claude-code
---
# Handoff — relay deferred send merged; its residuals fix is in adversary review

## The Goal
Fix peer messaging in `skills/session-finder/relay.py`: a send to a busy agent that cannot steer (Cline, every ACP provider, codex/omp/opencode/pi without `--steer`) was refused or blocked by `--idle S` and the text was lost; a Cline caller arrived as `[relay from unknown]`. Then close the review residuals.

## Where We Are
1. Queue item L-D merged as PR 49 (`a912a22`, 2026-10-24).
2. PR 57 merged as `7a033b8`: deferred send (a busy-only refusal is queued in `~/.local/state/relay/deferred/`, a detached `relay.py --deliver` sends when idle; exit **0** with `queued: <id>`, `--json` `"state":"queued"`; `--no-defer`, `--idle S`, `--pending`, `--cancel ID`, `--sweep`; bounds 20/target 20/sender 100; failure notice to the sender) plus `sender_name` from `PASEO_AGENT_ID`. Four adversary rounds (BLOCK, BLOCK, APPROVE a5902ee, APPROVE f3873a2). Live check: the Cline note queued as `20261024-225339-550207` and `--pending` later showed it `delivered`.
3. Standing order 9 added to `AGENTS.md` (`62cc40b`): every branch starts in its own worktree (`git worktree add -b NAME ~/src/djbclark-ade-NAME-wt origin/master`), never in the shared checkout.
4. **In flight:** branch `fix/relay-deferred-residuals`, head `f7aabb78aa28ac4c9ef214e7f8bb380753092d06`, worktree `~/src/djbclark-ade-relay-residuals-wt`, pushed, no PR. It fixes PR 57 round-4 residuals C1 (pid checked at poll time only when stored sid and transcript are empty), C2 (herdr rows by membership; undetected row with several same-named processes refused at queue time), C4 (deliverer env paths resolved). 449 tests passed, every new mutant killed. The narrow adversary round on it is running (omp, Opus 5.5).
5. Shared checkout `~/src/djbclark-ade` is on `master` (52cff03 at write time). Dirty files there are other sessions': `.agents/skills/fastino-glide/` (and at times `bin/paseo-set-model*`, `bin/rumination-watch`).

## What We Tried
1. Exit code 3 for "queued" (my first design): adversary round 1 showed it breaks `fleet-watch upr_relay` (dispatches a duplicate fallback worker and queues a new record every tick) and `load-watch` (reports a busy watcher unreachable). Replaced by exit 0 plus a `queued:` line.
2. `git checkout -b` in the shared checkout: it was on another session's branch, so my L-D branch carried two foreign commits. Fixed by rebasing in a worktree; now a standing order.
3. A mutation check run in suite order only: the L-D test passed with the fix only in suite order (the fake never created the lock file). Always run new tests alone with `-k` too.
4. A thread-based timing test for L-D: the class stubs `time.sleep`, so the holder never released; replaced by a deterministic fake lock.

## Key Decisions
1. Deferral is the default for busy-only refusals (matches djbclark 2026-10-23: relay should pick the best option itself); `--no-defer` is the escape hatch. Time-critical senders (`bin/load-watch notify/send_to`, `bin/session-load-watch`) pass `--no-defer`.
2. No launchd job for the sweep (records are re-armed by the opportunistic sweep at the start of every relay run). Not built; optional follow-up.
3. M-A (`docs/queue.md`, env-free relayed-turn detection, MEDIUM) stays queued by djbclark's choice.
4. PR 57 residuals C3 (sid-less pane with a same-named foreground child is refused at queue time) and C5 (deferred Hermes turn starts in `/`) stay as informational notes.
5. Adversary runs on `omp` Opus 5.5 high (`acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high --perm all` with a read-only brief; omp has no read-only mode). Builders run on `omp` Sonnet 5.5 high (`--kind code`) because the Claude subscription is tight.

## Evidence & Data
1. PR 49: https://github.com/djbclark/djbclark-ade/pull/49, PR 57: https://github.com/djbclark/djbclark-ade/pull/57. CI for both: pytest and pytest-linux passed.
2. Reports under `~/.local/state/bigteam/relay-comms/` (adv1..adv4, repair1..3, build) and `~/.local/state/bigteam/relay-residuals/` (build report, adv1 brief).
3. PR 57 residuals paragraph: `docs/queue.md`, section "relay.py deferred send and Paseo sender label".
4. The real relay queue holds two fake `failed` records from the builder's early smoke test (`20261024-194844-fe1631`, `20261024-194854-57fcc1`); a sweep prunes them a week after they ended.

## Operator Feedback
1. "Resurface the cline issue later" (done: the Cline note was queued and delivered).
2. "We need to fix the communications issue in general, work on that." (PR 57).
3. `/steps`: M-A not now; Cline reply dropped then resent after the fix; standing order 9 added; fix C1, C2, C4 now.

## Where We're Going
1. **Read the adversary result for `f7aabb7`** (see Detached jobs). APPROVE: open the PR, fill `PR_N`, wait for CI, merge. BLOCK: send a repair brief to a `--kind code` omp Sonnet slice in the same worktree, then a narrow adversary round.
   1. PR: `gh pr create --repo djbclark/kool-ade --base master --head fix/relay-deferred-residuals --title "relay.py: close PR 57 round-4 residuals C1, C2, C4" --body-file <body>`. Body quotes the adversary verdict line with the reviewed SHA (`APPROVE <sha>`), the C1/C2/C4 summary, and that the commit after the reviewed head only fills `PR_N`.
   2. After the number exists: `gsed -i 's/PR_N/#NN/g' CHANGELOG.md docs/queue.md` in the worktree (check `rg PR_N` first; the queue paragraph says "fixed in PR_N"), commit with `git-commit-own`, push, wait `gh pr checks NN --watch` (run in the background), then `gh pr merge NN --squash --match-head-commit <head>`.
   3. Cleanup: `git worktree remove ~/src/djbclark-ade-relay-residuals-wt`, `git branch -D fix/relay-deferred-residuals`, `git push origin --delete fix/relay-deferred-residuals`, close the job records (`.closed=(now|floor)` with temp file and `mv -f`).
2. `/loose` Rule 4 is still owed after item 1: ask handoff-and-continue / finish-and-archive / keep working.
3. Optional, only if djbclark asks: M-A (`rg -n 'M-A, env-free' docs/queue.md`), a launchd job for `relay.py --sweep`.
4. Remember: every branch in its own worktree; never commit in the shared checkout on a feature branch.

## Detached jobs
1. `~/.local/state/bigteam/relay-residuals/jobs/relay-residuals-adv1.json`
   1. report: `/Users/djbclark/.local/state/bigteam/relay-residuals/relay-residuals-adv1-report.md`
   2. done: `/Users/djbclark/.local/state/bigteam/relay-residuals/relay-residuals-adv1-report.md.done` (check `ls` first; it may exist already)
   3. rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/relay-residuals/jobs/relay-residuals-adv1.json /Users/djbclark/.local/state/bigteam/relay-residuals/relay-residuals-adv1-report.md.done` as its own `run_in_background` call (long timeout 7200000), then `acp-dispatch check <record>`.
   4. What it is: narrow adversary round (omp Opus 5.5) on `git diff origin/master` of `f7aabb7`. Its last line is the verdict (`APPROVE ...` or `BLOCK ...`); then close the record.

## Quick Start
```bash
cd ~/src/djbclark-ade && git status -sb | head -3
ls ~/.local/state/bigteam/relay-residuals/relay-residuals-adv1-report.md.done
acp-dispatch check ~/.local/state/bigteam/relay-residuals/jobs/relay-residuals-adv1.json
tail -3 ~/.local/state/bigteam/relay-residuals/relay-residuals-adv1-report.md
git -C ~/src/djbclark-ade-relay-residuals-wt log --oneline -2
python3 skills/session-finder/relay.py --pending
```
