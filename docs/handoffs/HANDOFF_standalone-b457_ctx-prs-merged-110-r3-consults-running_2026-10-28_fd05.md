---
schema_version: 1
handoff_id: fd05
parent_handoff_ids: [0d0e]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: handoff/standalone-b457-2026-10-28b
head_sha: c87ba0800657c5ad8ee329c7ad067d8d90195a9d
created_at: 2026-10-28T23:59:00-0400
writer: claude-code
---
# Handoff — context PRs 107/108/111 merged; PR 110 round 3, PR 114 and two picklist consults in flight

## The Goal
Finish the context-visibility audit (`docs/queue.md`, "Context visibility in Paseo and compact/handoff discipline"): PRs 107 (`bin/context-watch`), 108 (nudge retune), 110 (self-slash fixes), then the sibling `RecursionError` PR last. Also the picklist research (PR 111's queue entry): decide how `relay.py` and `self-slash` avoid blocking on TUI picklists, build only what djbclark picks.

## Where We Are
All times New York. Every merge needs djbclark's yes, pinned to the reviewed head.

| PR | Head | State |
|---|---|---|
| 107 context-watch | merged `2756fe8` | done, worktree removed |
| 108 nudge retune | merged `b31af4c` | done, worktree removed |
| 111 picklist queue entry | merged `c87ba08` | done, worktree removed |
| 110 self-slash fixes | `7605a48e49a4907a2e586db4bab04bfa4a342828` (worktree `~/src/djbclark-ade-ctx-selfslash-wt`) | adversary r2 APPROVE was at f65c795; CI `pytest-linux` then failed one new test; repair slice pushed 7605a48; **adversary r3 running**; PR is now **CONFLICTING with master** (CHANGELOG, after 107/108/111 merged); the PR body carries NO adversary marker yet |
| 114 zero-usage nudge fix (F2) | `c72fdf9fad8ce0ebc35cdf10e82aff54a9e24b2e` (worktree `~/src/djbclark-ade-ctx-f2-wt`) | adversary r1 APPROVE at c7f58c4, r2 APPROVE at c72fdf9, marker for c72fdf9 is in the PR body; CI `pytest-linux` and `pytest` were pending at last look; mergeable |
| 105 uutils port | owned by bb2a32df | not mine; do not touch its branch or body |

Also done: `~/ops/site-private/memory/feedback_self_compact.md` updated for the 267k wall (site-private `a8fa0d0`, pushed; the shared `~/ops/site-private` checkout fast-forwarded with `reset --keep`, 43 foreign `memory/codex` edits untouched).

Picklist research report (measured, 168 lines): `~/.local/state/bigteam/adhoc-2026-10-28/picklist-research-report.md`. djbclark picked "run the frontier consult first" (card option 2): two consults are running (Detached jobs 2 and 3).

The shared checkout `~/src/djbclark-ade` is on master `ca28a40` and carries foreign uncommitted edits: `skills/paseo*/SKILL.md` (four files), and `bin/self-slash` and `skills/session-finder/prompt_line.py` (15 and 6 lines; the `prompt_line.py` one is the zcode `IndexError` fix for the RAW print). Not mine: do not stage, stash or reset. PR 110 touches `bin/self-slash`, so whoever owns those edits will collide with it: ask them through `session-finder/relay.py` (`session-finder` skill to find the owner) before merging 110.

## What We Tried
1. The first PR 110 CI failure looked like a flake. It was not: `bin/self-slash:160` prepends `/opt/homebrew/bin` to PATH, so on the Mac the real `gdate` beat the test's fake `gdate` and the fake-clock test ran on the real clock; on Linux the fake clock drove it and a 300 s fake budget was too small for 80 reads at 5 s. Fix: `SELF_SLASH_PATH_AS_IS=1` (skips the prepend; set in the test setUp) plus `SELF_SLASH_WAIT=600` for that test, assertion unchanged, plus the adversary's B3 test. Linux itself was not run (no container); the cause was reproduced on macOS by removing the SELF_SLASH_WAIT line.
2. Running the nudge tests with the default `python3` (3.15, no pytest) and with `/usr/bin/python3` (3.9, fails collection on `typing.override` for the self-slash tests) failed; the nudge tests run with `bg /usr/bin/python3`, the self-slash tests with `bg /opt/homebrew/bin/uv run --with pytest --with pyyaml python -m pytest`.
3. A research dispatch with `--kind research` has no pool (router: Claude subscription held tight, weekly 82%); it went out as `--kind judgment` on omp Opus 5.5 high (API credits, $80 expiring 2026-11-04).
4. `git-commit-own` in `~/ops/site-private` commits but did not push (master was behind): rebuilt the commit in a temporary worktree, pushed, then `git reset --keep origin/master` in the shared checkout.

## Key Decisions
Fixing F2 (zero-usage `<synthetic>` stub reads as context 0) was a one-line change taken on the standing "fix known gaps without asking" ruling; its merge still waits for djbclark. The picklist research ran as one cheap read-only slice first, then two independent advise-only consults (omp Opus 5.5 high; codex `gpt-6-astra` via `--kind frontier --role advise`); Fable was skipped because the Claude subscription is tight.

## Decisions
- [ruling] "2. Run the frontier consult first" (picklist build order, card pick) (djbclark, 2026-10-28)
- [ruling] "1. Merge 107 and 108 (Recommended)" (card pick, each pinned to its reviewed head) (djbclark, 2026-10-28)
- [ruling] "1. Merge PR 111 (Recommended)" (card pick, pinned to 1ecb34d) (djbclark, 2026-10-28)
- [ruling] "1. Update the three lines (Recommended)" for the stale +200k wording in feedback_self_compact.md (djbclark, 2026-10-28)
- [ruling] "1. Not yet; coordinate with bb2a32df first (Recommended)" for the PostToolUse nudge trigger and any settings.json change (djbclark, 2026-10-28)
- [decision] Send the PR 110 CI repair to an omp Sonnet 5.5 slice and re-review it with adversary r3; rejected: rerun CI or raise a real timeout; because the failure was a platform-dependent fake clock, a real defect; in [PR 110](https://github.com/djbclark/djbclark-ade/pull/110).
- [decision] Fold only adversary r1 A1 into PR 114 (stronger hook-level test) and leave the two Low notes of r2; rejected: more rounds on a one-line fix; because both notes are optional and the baseline assert already kills the mutant; in [PR 114](https://github.com/djbclark/djbclark-ade/pull/114).

## Relations
- continues [[HANDOFF_standalone-b457_ctx-prs-107-110-adversary-running_2026-10-28_0d0e]]
- decided_in [[HANDOFF_standalone-b457_ctx-prs-merged-110-r3-consults-running_2026-10-28_fd05]]

## Evidence & Data
Tests: nudge `claude/hooks/handoff-tools/tests/test_context_size_nudge.py` 117 passed (mutation: reverting the F2 line fails the new test); PR 110 repair 129 passed across `tests/test_self_slash_prompt_wait.py`, `tests/test_self_slash.py`, `tests/test_prompt_line.py` (Mac). CI log of the failed Linux run: `/tmp/pr110/job.log` (run 40809550183, job 123236366898). Adversary reports: `~/.local/state/bigteam/adhoc-2026-10-28/adv-pr108-r4-report.md`, `adv-pr110-r2-report.md`, `adv-pr114-report.md`, `adv-pr114-r2-report.md`, `repair-pr110-ci-report.md`. Picklist findings in the research report: no route recognises a picker/permission prompt/slash menu on the screen today (they read as "draft"); herdr#5263 and paseo#7602 are open upstream and bite us; the 37 self-slash give-ups are mostly not pickers. Quota 2026-10-28 ~23:00: Claude 7d 82% (tight; no Fable/Opus Agent-tool sub-agents), Codex weekly 94% left, omp credits $80 of $200 left (expire 2026-11-04).

## Operator Feedback
Standing: ask before every merge pinned to the reviewed head; do not touch `~/.claude/settings.json` without asking; do not edit `~/CLAUDE.md`; fix known gaps without asking, ask only before merging or an especially costly action.

## Where We're Going
1. Re-arm the three waiters (Detached jobs), then read `adv-pr110-r3-report.md`. APPROVE: merge origin/master into `ctx-selfslash-2026-10-28` in its worktree (`git status` and `git log -3` first; resolve the CHANGELOG conflict by keeping both sets of lines), re-run `tests/test_self_slash_prompt_wait.py tests/test_self_slash.py tests/test_prompt_line.py` through `bg` with uv, push, write the marker for the NEW head into the PR body (a merge commit moves the head: re-run adversary on the delta if it is more than a CHANGELOG merge), confirm CI 3/3, then ask djbclark to merge pinned to that head. BLOCK: repair slice (omp Sonnet 5.5) in that worktree, then re-review.
2. Ask djbclark to merge PR 114 pinned to `c72fdf9fad8ce0ebc35cdf10e82aff54a9e24b2e` once `gh pr checks 114 -R djbclark/djbclark-ade` shows all green.
3. Read both consult reports (`picklist-consult-opus-report.md`, `picklist-consult-astra-report.md`), compare with the research report's design (D) and E, and bring djbclark numbered options with cost, risk and a recommendation; build only what he picks. Option 1 of the earlier card (harness + `MODAL` state in `prompt_line.classify` + self-slash waits on `blocked`) must wait for PR 110 to merge (same file) and for the owner of the foreign `bin/self-slash`/`prompt_line.py` edits.
4. Find the owner of the foreign uncommitted edits to `bin/self-slash` and `skills/session-finder/prompt_line.py` in the shared checkout (`session-finder` skill) and agree an order with them before PR 110 merges; the `prompt_line.py` hunk looks like the zcode `IndexError` fix (research report A1e).
5. Chase bb2a32df (Paseo agent bb2a32df-81a6-4370-927a-d61717b6e985) for the unacked `nudge-overlap` relay via `session-finder/relay.py`; re-route if overdue by 6 h. Whichever of PR 108 (merged) and bb2a32df's `feat/nudge-log-posttooluse` lands second takes the adversary's F1 hardening (cap rejected needle hits or read backward in growing steps).
6. Remove worktrees after their PRs merge: `-ctx-selfslash-wt`, `-ctx-f2-wt`, `-uutils-wt` (after PR 105, owner bb2a32df), and `-handoff-b-wt` after this handoff branch is merged or dropped.
7. Follow-ups, last: sibling `RecursionError` PR (`guard_level` in `bin/claude-fleet-governor`, `load_state` in `bin/claude-quota-guard`); PR 110 adversary notes B1, B2, B5 (Low); a PostToolUse nudge trigger needs a `~/.claude/settings.json` change (ask first); PR 114 adversary notes B1/B2 (Low); `ACP_RUN_AGENT` not scrubbed by `test_context_size_nudge.py` (20 failures inside an acp-run slice, round-1 A3).

## Detached jobs
1. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr110-r3.json`; report `.../adv-pr110-r3-report.md`; done `.../adv-pr110-r3-report.md.done` (absent at 23:58, still running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/adv-pr110-r3.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/adv-pr110-r3-report.md.done`. Adversary round 3 of PR 110 at 7605a48; act per Where We're Going 1.
2. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/picklist-consult-opus.json`; report `.../picklist-consult-opus-report.md`; done `.../picklist-consult-opus-report.md.done` (absent, running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/picklist-consult-opus.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/picklist-consult-opus-report.md.done`. Advise-only consult (omp Opus 5.5 high) on the picklist design.
3. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/picklist-consult-astra.json`; report `.../picklist-consult-astra-report.md`; done `.../picklist-consult-astra-report.md.done` (absent, running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/picklist-consult-astra.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/picklist-consult-astra-report.md.done`. Advise-only consult (codex gpt-6-astra, frontier allowance) on the same brief.
All other records of this session are closed. No sub-agent report is BLOCKED.

## Quick Start
```bash
cd ~/src/djbclark-ade
# re-arm each waiter above as its own run_in_background Bash call (timeout 7200000)
for j in adv-pr110-r3 picklist-consult-opus picklist-consult-astra; do bin/acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-28/jobs/$j.json; done
for n in 110 114; do gh pr view $n -R djbclark/djbclark-ade --json state,headRefOid,mergeable; gh pr checks $n -R djbclark/djbclark-ade; done
```
