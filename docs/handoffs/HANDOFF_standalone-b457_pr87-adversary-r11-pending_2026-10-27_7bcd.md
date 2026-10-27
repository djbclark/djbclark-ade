---
schema_version: 1
handoff_id: 7bcd
parent_handoff_ids: [7273]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: djbclark-ade (lead session 750c1e02-86d6-425a-90d3-c37f8a0e04e9, resumed from baton of fd720445)
branch: feat/expect-ack-no-transcript (PR 87 worktree /Users/djbclark/src/djbclark-ade-expect-notx-wt)
head_sha: 26a37f39229e9d83d5da8d3ffda7f206cd2708fe
created_at: 2026-10-27T06:57:00-04:00
writer: claude-code
---
# Handoff — PR 87 at head 26a37f3, adversary round 11 pending, PR 88 blocks CI

## The Goal
Continues chain `standalone-b457` (parent handoff 7273, deterministic: this session started from its baton).

Get [PR 87](https://github.com/djbclark/djbclark-ade/pull/87) (relay `--expect-ack` for transcript-less senders, plus Hermes gateway caller identity) through adversary review, Codex review and CI to a merge. The merge needs djbclark's explicit yes pinned to the final head (`gh pr merge 87 --squash --match-head-commit <sha>`). After it: notify PR 79's owner (already merged), then the gates follow-up PR and model-tiers S1 per handoff 7273.

## Where We Are
PR 87 worktree `/Users/djbclark/src/djbclark-ade-expect-notx-wt`, branch `feat/expect-ack-no-transcript`, pushed head `26a37f39229e9d83d5da8d3ffda7f206cd2708fe`, clean tree. History: 466df5b, 9f069fa, 5b7cb8a, a031a2f, fcd4bcc, fb7042b (master merge, CHANGELOG conflict kept both lines), 22059bf (Hermes gateway caller identity in `relay.py`), 2fe0bf2 (docs), 26a37f3 (docs-only repair N11 for adversary r10 BLOCK).

Done this window:
1. Adversary r5, r8 and r10 BLOCKs repaired; r9 approved fcd4bcc.
2. Codex P2 #1 (reservation timing) and P2 #2 (Hermes caller identity) addressed in code (`hermes_caller`, `hermes_turn_pid`, `hermes_gateway_pid`, `descends_from`, `CTX["caller"]`; `expect_resolve_by_relay` requires an exact non-empty `t.sid == me.sid` for a `hermes-gw` caller). 23 tests in `TestExpectAnsweredInsideABlockingSend` using the production identity path.
3. Docs rewritten to state the wide same-user residual (r10 BLOCK): `CHANGELOG.md`, `docs/queue.md` item 9, `skills/session-finder/SKILL.md`, `skills/peer-relay/SKILL.md`.

Adversary round 11 (docs-only review of `2fe0bf2..26a37f3`) is dispatched and RUNNING. Its report `.../adhoc-2026-10-25/adv-notx-r11-report.md` was 102 bytes (`STATUS: working` and a checklist) at 06:54 on 2026-10-27, `.done` absent. No waiter was armed.

[PR 88](https://github.com/djbclark/djbclark-ade/pull/88) (head 091964e, merge-ready, owned by w2Q:p3, awaiting the operator's merge choice) fixes the six inherited `test_acp_dispatch_brief_footer` failures. Until it merges, PR 87's CI `pytest` job is red on the master baseline, not on PR 87's own changes.

PR 87 body (`/tmp/pr87-body.md`, may be gone: re-fetch with `gh pr view 87 --json body`) is STALE: it says "nine rounds", last verdict r9 at fcd4bcc, and does not mention rounds 10/11, 2fe0bf2/26a37f3, the Hermes identity work, the accepted same-user residual or F2.

## What We Tried
1. I yielded PR 87 to `bb2a32df` (a load-watcher session, label `0c95ddea`) believing it was a second lead. Wrong: it had resolved my chain by directory through `/baton`. Corrected by relay (ack `stand-down-pr87-20261026`); it stood down. The earlier Hermes-ping saying I yielded is stale and was not re-pinged.
2. My `adv-notx-r9-brief.md` heredoc overwrote another session's file (which had overwritten `adv-notx-r8-brief.md`); the prompts survive in the job records.
3. omp rejects `--perm read-only`: adversary slices run `--perm all` with a read-only brief plus a diff check.
4. Fabricated-`self` test helper replaced by production-identity `hermes_world` + `answer_as_hermes` after Codex P2 #2; the fabricated form hid the real gateway path.
5. CI `pytest` cancelled on fcd4bcc: `gh run rerun --failed`, green. CI on fb7042b failed on the six inherited footer tests (PR 88's).

## Key Decisions
Gateway identity implemented inside PR 87 (not split off). Residual A4a accepted and documented. After r10 BLOCK the code was left as is and the docs now state a wide same-user forgeability bound instead; the F2 crash (Unicode-digit lock file `ValueError` in `hermes_turn_pid`) is knowingly left unfixed. Rejected: fixing F2 and the same-user spoof in code (djbclark chose docs only).

## Decisions
- [ruling] "2. Fix N1/N2 first" at the r6 approval card (djbclark, 2026-10-26)
- [ruling] "2. Implement gateway identity" for Codex P2 #2 (djbclark, 2026-10-26)
- [ruling] "1. Fix inside PR 87 (Recommended)" for the herdr-pane misattribution D1 A2/C2b (djbclark, 2026-10-26)
- [ruling] "1. Accept, document it (Recommended)" for residual A4a (djbclark, 2026-10-26)
- [ruling] "2. Docs only" after adversary r10 BLOCK: leave the code, state the wide same-user residual, do not fix F2 (djbclark, 2026-10-26)
- [decision] Run round 11 as a narrow docs-only adversary review of `2fe0bf2..26a37f3`; rejected: skipping the review of a docs-only repair; because every earlier repair reintroduced a defect class (memory feedback_re_review_every_repair).
- [decision] Hermes gateway conversations can close an expectation by relay but never open one; rejected: letting them open; because there is no transcript path to verify the asker.

## Relations
- continues [[HANDOFF_standalone-b457_ack-wave-prs-and-d2-live_2026-10-26_7273]]
- decided_in [[HANDOFF_standalone-b457_pr87-adversary-r11-pending_2026-10-27_7bcd]]

## Evidence & Data
PR 87 head 26a37f3, `reviewDecision` empty, open. PR 88 head 091964e, open, not merged (checked 2026-10-27). Reports and briefs under `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/`: `adv-notx-r5..r10-report.md`, `notx-repair-N5..N9,N11-report.md`, `notx-design-D1-report.md`, `notx-build-B1-report.md`, `adv-notx-r11-brief.md`. Tests last run: relay suites passed earlier in the window; no test run after the docs-only 26a37f3. Transcript: `/Users/djbclark/.claude/projects/-Users-djbclark-src-djbclark-ade/750c1e02-86d6-425a-90d3-c37f8a0e04e9.jsonl`.

## Operator Feedback
djbclark's rulings above. A card for Codex P2 was rejected once ("[Request interrupted by user for tool use]"); the next `/steps` card worked.

## Where We're Going
1. Arm the round 11 waiter (own `run_in_background` call, timeout 7200000) and read the verdict: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r11.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r11-report.md.done`, then `acp-dispatch check` the record, read the report, close the record (`.closed=(now|floor)` via temp file + `mv -f`). BLOCK means another docs repair slice (Sonnet 5.5 high via `acp-dispatch omp`) and round 12.
2. On APPROVE: update the PR 87 body (rounds 10/11, head 26a37f3, Hermes identity work, accepted same-user residual, F2 open, relay.py docstring lines still overstating, the load-watcher provenance note).
3. Wait for PR 88 to merge (w2Q:p3 owns it). Then fetch, merge origin/master into the branch (CHANGELOG conflicts likely: keep both lines, keep the `(#87)` line), run the relay suites and `tests/test_fleet_tidy.py` via `~/ops/site-private/bin/bg`, push. A new merge head means the r11 approval covers the previous head only: say so and offer a further round.
4. Post `@codex review` on the final head, resolve the Codex P2 #2 thread (GraphQL `resolveReviewThread`) only after the head is reviewed, poll `python3 /tmp/ciwatch/poll.py 87` and `bin/pr-wait --head <sha> --out … --no-request --json 87` until `merge_ready: true`.
5. Ask djbclark for the merge yes pinned to the final head (question card with numbered options, links in prose first) and `hermes-ping "djbclark-ade: PR 87 ready … https://github.com/djbclark/djbclark-ade/pull/87"`.
6. After the merge: gates follow-up PR and model-tiers S1 (handoff 7273). Check `relay.py --pending` for unacknowledged messages to w2F:p45 (20261026-182131-6c5dd8, 20261026-182214-32e844) and w2Q:p3 (20261026-182227-213bd8, 20261026-190858-4ba75a, 20261026-193430-5e5789).

## Detached jobs
1. Job file `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r11.json`; report `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r11-report.md`; `.done` `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r11-report.md.done` (absent at 06:56 on 2026-10-27, so still running); rearm `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r11.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r11-report.md.done`. Opus 5.5 high adversary, docs-only review of `2fe0bf2..26a37f3`; read its verdict line and findings, act per step 1 above.

## Quick Start
```bash
cd /Users/djbclark/src/djbclark-ade-expect-notx-wt && git status -s && git log --oneline -3
~/src/djbclark-ade/bin/acp-dispatch check /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r11.json
gh pr view 88 --json state,mergedAt
gh pr view 87 --json state,headRefOid
```
