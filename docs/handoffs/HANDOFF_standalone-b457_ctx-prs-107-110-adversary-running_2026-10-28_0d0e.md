---
schema_version: 1
handoff_id: 0d0e
parent_handoff_ids: [4496]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: docs/queue-picklist-deadlocks-2026-10-28
head_sha: 94411d1
created_at: 2026-10-28T23:10:00-04:00
writer: claude-code
---
# Handoff — context-visibility PRs 107/108/110 under adversary review, picklist research queued

## The Goal
Finish the context-visibility audit from `docs/queue.md` ("Context visibility in Paseo and compact/handoff discipline"): djbclark picked all four fixes (retune nudge tiers, fix self-slash failures, live per-agent context readout, comment on getpaseo/paseo#4949). Then the sibling `RecursionError` PR, last in the queue. Also queued this session (PR 111): research on keeping `relay.py` and self-slash from blocking on TUI picklists.

## Where We Are
All times New York. Nothing is merged yet from this audit; every merge needs djbclark's yes, pinned to the reviewed head.

| PR | Branch / worktree | Head | State |
|---|---|---|---|
| 105 uutils port (ubuntu-latest) | owned by bb2a32df, worktree `~/src/djbclark-ade-uutils-wt` | 0ddb0b9 | adversary APPROVE at c2ff438 and 0ddb0b9, CI 3/3 SUCCESS; bb2a32df asks for the merge. Do not touch its branch or body. |
| 107 `bin/context-watch` | `ctx-ctxwatch-2026-10-28`, `~/src/djbclark-ade-ctx-ctxwatch-wt` | 368459f | adversary r3 APPROVE at 368459f (marker in PR body); CI SUCCESS,SUCCESS. Ready to ask for merge. |
| 108 nudge retune | `ctx-nudge-2026-10-28`, `~/src/djbclark-ade-ctx-nudge-wt` | bf759f6 | adversary r4 running; PR body still carries the stale APPROVE marker at dc03730. |
| 110 self-slash fixes | `ctx-selfslash-2026-10-28`, `~/src/djbclark-ade-ctx-selfslash-wt` | f65c795 | adversary r2 running (r1 BLOCK at 557fae5, repaired). |
| 111 queue entry (picklist research) | `docs/queue-picklist-deadlocks-2026-10-28`, `~/src/djbclark-ade-queue-picklist-wt` | 94411d1 (+ this handoff) | docs only, open, no review needed; merge decision with djbclark. |

The getpaseo/paseo#4949 comment is posted (djbclark approved "as written").

## What We Tried
1. PR 108 repair r2 used `session_state["level"] = max(level, fired)`. After a mid-turn compaction this kept the level stuck high: adversary r2 BLOCK at 25e7972. Re-reviewing every repair is the lesson (`feedback_re_review_every_repair`).
2. Repair r3 scanned a 2 MB tail for `compact_boundary`; r3 adversary found the cap missed 4.3% of real boundaries (BLOCK at 2cff315). Repair r4 scans the whole appended region in 1 MB chunks (overlap 128, cap 64 MB, tail-window fallback), boundary recognised by `json.loads` (type system, subtype compact_boundary, not sidechain).
3. PR 107 first version printed unsanitised titles: terminal escape injection (BLOCK at 5ff68da). Fixed with `clean_text`, uuid-only ids, a capped per-row window.
4. PR 110 first version: stale mode list, typed into stale marker rows, busy regex, wall-clock gating (BLOCK at 557fae5). Fixed by probing the installed claude CLI for modes and a wide prompt read.
5. Codex dispatch refused at 0% quota: re-routed the uutils slice to omp Sonnet 5.5. `--kind research` is not eligible for omp, `--perm read-only` is unsupported for omp and agy: used `--perm all` with a read-only brief and checked `git status` after.

## Key Decisions
Nudge tiers derive from the auto-compaction wall (267k = `autoCompactWindow` 300000 minus ~33k buffer), not a fixed 200k. Context readout is a separate read-only script, not a change to Paseo. The picklist research must not consult agy: djbclark supplied its Gemini report already (saved verbatim at `~/.local/state/ade-briefs/picklist-deadlock-gemini-report-2026-10-28.md`).

## Decisions
- [ruling] "Retune nudge tiers, fix the self-slash failures, live per-agent context readout, comment on getpaseo/paseo#4949" (all four picked from the card) (djbclark, 2026-10-28)
- [ruling] "Post it as written" for the #4949 comment (djbclark, 2026-10-28)
- [ruling] "Fix F1-F4, re-review, then ask to merge" for PR 108's low findings (djbclark, 2026-10-28)
- [ruling] "do not use it [agy/Gemini] as one of the agents you consult since we have this" for the picklist research (djbclark, 2026-10-28)
- [decision] Nudge thresholds derive from the 267k wall; rejected: keep fixed +200k tiers; because the wall is reached before the old tiers fire; in [PR 108](https://github.com/djbclark/djbclark-ade/pull/108).
- [decision] Whole-region chunked scan for compact_boundary; rejected: a 2 MB tail cap; because it missed 4.3% of real boundaries; in [PR 108](https://github.com/djbclark/djbclark-ade/pull/108).
- [decision] Per-agent readout as a read-only `bin/context-watch`; rejected: patching Paseo's meter; because upstream owns it and `paseo agent inspect --json` omits context fields; in [PR 107](https://github.com/djbclark/djbclark-ade/pull/107).

## Relations
- continues [[HANDOFF_standalone-b457_linux-ci-fixed-uutils-slice-running_2026-10-28_4496]]
- decided_in [[HANDOFF_standalone-b457_ctx-prs-107-110-adversary-running_2026-10-28_0d0e]]

## Evidence & Data
Tests: PR 108 `claude/hooks/handoff-tools/tests/test_context_size_nudge.py` 98 passed, 18 deselected; PR 107 `tests/test_context_watch.py` 43 tests; PR 110 `tests/test_self_slash_prompt_wait.py` (new), `tests/test_self_slash.py`, `tests/test_prompt_line.py`; PR 105 CI run 40793978347 all 3 jobs success on ubuntu-26.04 (5873 passed, 24 skipped). Briefs and reports: `~/.local/state/bigteam/adhoc-2026-10-28/*-brief.md`, `*-report.md`. Saved drafts: `~/.local/state/ade-briefs/paseo-4949-comment-draft-2026-10-28.md`. Shared checkout `~/src/djbclark-ade` is on master ca28a40 with four foreign dirty files (`skills/paseo*/SKILL.md`), not mine.

## Operator Feedback
Standing: ask before every merge pinned to the reviewed head; do not touch `~/.claude/settings.json` without asking; do not edit `~/CLAUDE.md`. djbclark asked in the picklist request which TUI clients and orchestration mechanism are used for agent-to-agent talk: answered in a reply (relay.py routes paseo/dispatch/launch/pane/socket over herdr/Paseo panes; Agent-tool sub-agents; acp-dispatch for slices).

## Where We're Going
1. Re-arm the two adversary waiters (below), read `adv-pr108-r4-report.md` and `adv-pr110-r2-report.md`. APPROVE: write the marker for the exact head into the PR body (`gh pr edit --body-file`), replacing PR 108's stale dc03730 marker, then ask djbclark to merge. BLOCK: dispatch a repair slice (omp Sonnet 5.5) in that PR's worktree after `git status` and `git log -3`, then re-review the repair.
2. Ask djbclark for a squash merge of PR 107 pinned to 368459f (`gh pr merge 107 --squash --match-head-commit <full sha>`); then 108 and 110 as their verdicts land. Rebase risk: bb2a32df's `feat/nudge-log-posttooluse` overlaps PR 108.
3. Chase bb2a32df (71621660 / bb2a32df-81a6-4370-927a-d61717b6e985) for the unacked `nudge-overlap` relay via `session-finder/relay.py`; overdue acks are re-routed after 6 h.
4. Remove merged worktrees: `-uutils-wt` (after PR 105), `-ctx-nudge-wt`, `-ctx-ctxwatch-wt`, `-ctx-selfslash-wt`, `-queue-picklist-wt`.
5. Picklist research per PR 111's queue entry (web search, verify Gemini's leads, frontier consult never agy, talk to djbclark): not started.
6. Follow-ups: sibling `RecursionError` PR last (`guard_level` in `bin/claude-fleet-governor`, `load_state` in `bin/claude-quota-guard`); stale +200k lines in `~/ops/site-private/memory/feedback_self_compact.md` (lines 5, 88, 117) need djbclark's decision (another repo); a PostToolUse nudge trigger needs a `~/.claude/settings.json` change (ask first); page ping thresholds and `REPEAT_EVERY` are unreachable before the wall (documented only). Out of scope here: Item-32 wording and the `pkill -f` example for item 33 go to an Opus 5.5 session.

## Detached jobs
1. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr108-r4.json`; report `.../adv-pr108-r4-report.md`; done `.../adv-pr108-r4-report.md.done` (absent at 23:10, still running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr108-r4.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/adv-pr108-r4-report.md.done`. Adversary round 4 of PR 108 at bf759f6; act per Where We're Going 1.
2. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr110-r2.json`; report `.../adv-pr110-r2-report.md`; done `.../adv-pr110-r2-report.md.done` (absent, still running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr110-r2.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/adv-pr110-r2-report.md.done`. Adversary round 2 of PR 110 at f65c795.
All other records of this session are closed. No sub-agent report is BLOCKED.

## Quick Start
```bash
cd ~/src/djbclark-ade
# re-arm each waiter above as its own run_in_background Bash call (timeout 7200000)
acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr108-r4.json
acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr110-r2.json
for n in 107 108 110 111; do gh pr view $n --json state,headRefOid,statusCheckRollup; done
```
