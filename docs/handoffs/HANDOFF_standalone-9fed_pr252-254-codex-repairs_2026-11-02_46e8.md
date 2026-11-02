---
schema_version: 1
handoff_id: 46e8
parent_handoff_ids: [9fed]
lineage: deterministic
chain: [standalone-9fed]
repo: djbclark-ade
workspace: handoff-snipe-session
branch: handoff-snipe-session
head_sha: 9bd8bd9edd622afd798c903cf6fbe63a8149b894
created_at: 2026-11-02T16:25:00-0500
writer: claude-code
---
# Handoff — PR 252 ready, PR 254 repair rounds

## The Goal
Land djbclark-ade PRs 252 (barnowl skill note on Snipe) and 254 (bash_habits_gate subshell false positive) through the lead's lander (lead 1e61c979). Each needs: local Codex review clean on the head (`bin/local-review N --head SHA`, any finding blocks), an adversary APPROVE marker for that exact head in the PR body, CI green. The lead merges; repairs route to this chain. Also still watching asedeno/snipe PRs 2 and 3 and roost-api.mit.edu (human's items otherwise).

## Where We Are
1. PR 252 is DONE on my side. Head 49c2f9d72b5fa5d1bff3005bed90053d90c052a5 (worktree /Users/djbclark/src/djbclark-ade-snipe-note-wt, branch snipe-note, pushed). Local review clean on this head; adversary round 3 APPROVE, marker already in the PR body; lead 1e61c979 told by relay (delivered). CI on the new head not re-read by me.
2. PR 254 is NOT done. Head 2e4abfb025b6aad28491535209dd416382a645fb (worktree /Users/djbclark/src/djbclark-ade-habits-subshell-wt, branch habits-gate-subshell, pushed, 149 tests pass). Local review of this head FOUND a third P2: "Preserve expression context when trimming closing parentheses" (hook line ~325). `[[ $tool =~ ^(awk|sed)$ ]] && echo recognized` and `ls @(awk|sed)` now falsely deny, because `before_unmatched_close` trims at any unmatched `)`. Full text: ~/.local/state/local-review/djbclark__djbclark-ade-pr254-2e4abfb025b6aad28491535209dd416382a645fb.out. Adversary round on 2e4abfb (adversary-pr254c) was dispatched and may still be running or finished.
3. The lead was NOT yet told that 254 needs another repair (only that it was in review).

## What We Tried
1. Head 5a0c9c0 (original): trimmed every stage at an unmatched `)`. Codex: (a) the trimmed last stage re-scoped the exit-status check (`echo $(printf x | cat) && echo done` falsely denied), (b) an escaped `\)` truncates a stage so GNU options after it pass.
2. Head 45d9d82: `_paren_scan` skips escaped parens; `closes_substitution` exempted pipelines whose last stage ends a `$(`, `<(`, `>(` substitution, except bare assignments. FAILED: Codex found `git merge --ff-only topic | tee $(printf /tmp/merge.log | cat -) && git push` newly passes, and `(x=$(false | tail -2)) && printf PUSHED` passes, `FOO=$(printf x | cat) env && echo done` falsely denied. The adversary BLOCKed the same class (tee/tr inside substitution args, `echo $(git merge | tail) && git push`, `local x=$(...)`). Lesson: any heuristic exemption of the status check re-opens the 2026-10-18 incident shape.
3. Head 2e4abfb: dropped the exemption entirely. Status check uses the UNTRIMMED `raw_stages[-1]` (byte-for-byte master behaviour); trimming plus the escaped-paren fix apply only to the GNU-option checks. This fixed rounds 1-2 but trimming itself still regresses regex/glob parens (round 3 finding).

## Key Decisions
Chosen: keep the status check identical to master; narrow only the GNU-option trimming. Rejected: exempting substitutions from the status check (three rounds of false negatives). Planned next narrowing (NOT yet implemented): trim a stage at its unmatched `)` only when the `(` that `)` closes is a `$(`, `<(` or `>(` opener (the char before that `(`), computed from the prefix of earlier stages; bare `(`, `^(`, `@(`, `=~ (` openers never trigger a trim. Needs `_paren_scan` to keep scanning past an unmatched `)` in the prefix and to return open-paren indexes (it already returns indexes). `$((` arithmetic: the inner `(` follows `(`, so no trim. Alternative if this keeps failing: ask the lead whether to drop trimming and fix only the original `cut --jq` symptom differently, or close 254 and note the false positive in the gate doc (the gate is a convenience hook that fails open).

## Decisions
- [decision] The pipe-status check reads untrimmed raw stages; rejected: a substitution exemption; because three Codex/adversary rounds found fail-open widening of the 2026-10-18 `merge | tail && push` incident.
- [decision] Trim a stage only at a `)` closing a `$(`, `<(` or `>(` opener; rejected: trimming at any unmatched `)`; because regex and extended-glob parens (`=~ ^(awk|sed)$`, `@(awk|sed)`) regress.
- [decision] PR 252 states the human-only scope once at the top of the Snipe section and names the human per step; rejected: scoping only item 1; because adversary BLOCKed 36306374 (the roost `curl` from pastebin was still an agent-followable imperative).

## Relations
- continues [[HANDOFF_standalone-9fed_snipe-pastebin-latest-hook-fix_2026-11-02_9fed]]
- decided_in [[HANDOFF_standalone-9fed_pr252-254-codex-repairs_2026-11-02_46e8]]

## Evidence & Data
- Adversary reports: ~/.local/state/bigteam/adhoc-2026-11-02/adversary-pr252{,b,c}-report.md, adversary-pr254{,b,c}-report.md; probe corpus script and output beside them (pr254b_probe.py, probe.out).
- Local reviews: ~/.local/state/local-review/djbclark__djbclark-ade-pr25{2,4}-<head>.json and .out.
- Tests: `~/ops/site-private-djbclark/bin/bg bin/pytest -q tests/test_bash_habits_gate.py` in the 254 worktree: 149 passed at 2e4abfb. New tests: escaped-paren denials, `(a | tail) && b`, tee/substitution and `(x=$(false | tail -2)) && printf PUSHED` denials, `echo $(printf x | cat) && echo done` pass.
- Scratch: /tmp/adv-9fed (briefs, logs).
- Quota: guard level `critical`; no new Claude subscription work until 2026-11-06T09:59:59Z; use omp (adversary rounds via `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high --perm all`; omp has no verified read-only mode, so briefs say read-only and the worktree diff is checked after).

## Operator Feedback
Lead 7c58015b (2026-11-02): ask decisions through relay.py as a picklist, never AskUserQuestion cards; the Paseo daemon was restarted once at 20:36Z (nothing lost). Lead 1e61c979: findings of any priority block; repairs are mine; tell it when each head has clean review plus marker.

## Where We're Going
1. NEXT: in the 254 worktree implement the narrowed trim (above), add tests: `[[ $tool =~ ^(awk|sed)$ ]] && echo recognized` passes, `ls @(awk|sed)` passes, `gh api x $(echo $r | cut -d/ -f1):master --jq .y` still passes, `echo x | cut -d\) --complement -f1` denied, the status-check cases stay denied; run the test file via bg; `git-commit-own` and push; then `bin/local-review 254 --head <new sha>` (background), dispatch an adversary on the new head (omp; brief: diff verdicts of master vs head over a corpus including regex, glob, arithmetic and substitution commands), and when both are clean put the marker in the PR body (replace the old marker line) and relay to 1e61c979.
2. Read adversary-pr254c-report.md (head 2e4abfb) for extra findings before step 1; do not rerun it.
3. PR 252: re-read CI for 49c2f9d (`gh pr checks 252 -R djbclark/djbclark-ade`); if the lead merges, remove the worktree /Users/djbclark/src/djbclark-ade-snipe-note-wt only after `gh pr view 252 --json state` reads MERGED. Same for 254 and /Users/djbclark/src/djbclark-ade-habits-subshell-wt. PR 256 (open-clean-env) also edits the gate and waits for 254.
4. Watch https://github.com/asedeno/snipe/pull/2 and /3 and `curl -s -o /dev/null -w '%{http_code}' https://roost-api.mit.edu`; report to djbclark when roost answers (roost signup and `R l` are the human's).
5. autorename "no transcript" root cause: lead's PR 259 appears to cover it (changelog fragment autorename-transcript-path); confirm before doing anything.
6. Optional, ask first: delete the seven throwaway `ci/*` branches on the djbclark/snipe fork and the pasture /Users/djbclark/.cow/pastures/snipe.

## Detached jobs
- /Users/djbclark/.local/state/bigteam/adhoc-2026-11-02/jobs/adversary-pr254c.json: report /Users/djbclark/.local/state/bigteam/adhoc-2026-11-02/adversary-pr254c-report.md; done path .../adversary-pr254c-report.md.done (check whether it exists); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-11-02/jobs/adversary-pr254c.json /Users/djbclark/.local/state/bigteam/adhoc-2026-11-02/adversary-pr254c-report.md.done` (run_in_background, 7200000 ms), then `acp-dispatch check` the record. Adversary round on head 2e4abfb; the verdict is superseded by the planned fix but its findings are worth reading. Close the record afterwards.
All other adversary records of this session are closed.

## Quick Start
```
cd /Users/djbclark/src/djbclark-ade-habits-subshell-wt && git status --short && git log -3 --oneline
gh pr view 254 -R djbclark/djbclark-ade --json state,headRefOid
gh pr checks 252 -R djbclark/djbclark-ade
python3 /Users/djbclark/src/djbclark-ade/skills/session-finder/relay.py 1e61c979 --message-file FILE --wait 30   # lead; --steer only if it is working and the queue is full
```
Peers: lead 1e61c979 (lander, expects "ready" messages with head SHAs), lead 7c58015b (restart/quiesce notices only).
