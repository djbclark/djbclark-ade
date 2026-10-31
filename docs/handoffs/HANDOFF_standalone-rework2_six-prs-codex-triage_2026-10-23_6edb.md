---
schema_version: 1
handoff_id: 6edb
parent_handoff_ids: [4583]
lineage: deterministic
chain: [standalone-rework2]
repo: kool-ade
workspace: main
branch: master
head_sha: 2187f8e
created_at: 2026-10-23T20:14:01-0400
writer: claude-code
---
# Handoff: rework-2 lead, six PRs in flight, Codex triage done, nudge hook revived

## The Goal

Land the 2026-10-23 rework-2 follow-ups (docs/queue.md "Follow-ups from PRs 29 and 30") and fix everything their
reviews uncovered. Each PR gets an adversary APPROVE on its exact head, quoted with the SHA in the body, then
Codex (code AND security review) on that head, no open Codex thread, CI, and `gh pr merge N --squash
--match-head-commit <sha>`. Lead: Paseo agent 23ca18d7 (Claude Code session c812e139, Opus 5.5 high).

## Where We Are

Merged or pushed to master this session:
1. PR 33 (`[lead] pipeline_effort = "medium"`) merged as d06d48c.
2. d618809: a mode-only hotfix restored +x on 12 shebang scripts. `claude/hooks/context_size_nudge.py` had been
   100644 since 836b306 (2026-10-19), so `hook-deadline` exited 127 and no context-size nudge ran for 4 days. Now
   rc 0 and the nudge fires.
3. docs/queue.md 01adaba (item 8: unresolved Codex findings on merged PRs) and 2187f8e (item 9: accepted LOWs and
   the declined findings).
4. 104 Codex threads on merged PRs 15-30 resolved via GraphQL `resolveReviewThread`. The triage judged them
   fixed (93) or process-only (11). Its report is `~/.local/state/bigteam/rework2-codex-triage/codex-triage-report.md`.
   The 8 still-applies threads stay open, 6 of them until PRs 36-38 merge.

Open PRs (each in its own cow pasture `~/.cow/pastures/kool-ade/<name>`):

| PR | Pasture, head | State |
|---|---|---|
| [32](https://github.com/djbclark/djbclark-ade/pull/32) `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` + `tests/test_bin_modes.py` | subagent-model, 9fa0605 | Round 6 APPROVE at dcf7e8d. Codex code and security completed on dcf7e8d, no findings, no open thread. The merge FAILED on a conflict with master, so 9fa0605 merges master (both-sides resolution in CHANGELOG.md and docs/model-routing.md; 5 tests passed; pushed). Round 7 (merge-only review) is running. |
| [34](https://github.com/djbclark/djbclark-ade/pull/34) `bin/pr-wait` (draft) | pr-wait, a4366f8 | Round 3 BLOCK (security findings ignored), fixed in a4366f8: `merge_ready`, `merge_blockers`, `-open-findings.json`, security_review, any-comment thread match; 44 tests. Round 4 is running. |
| [35](https://github.com/djbclark/djbclark-ade/pull/35) self-slash LOWs (draft) | review-selfslash, d102e18 | Rounds 2-4 each found another fail-open in how this agent's mode is passed on. d102e18 (lead's own fix) believes only a plain string Provider/Mode; 77 tests pass, a mutant failed. Round 5 is running. It also cures master's red macOS CI (bash 3.2 `mode_args[@]` unbound, line 679 on master). |
| [36](https://github.com/djbclark/djbclark-ade/pull/36) claude-quota-guard (batch A, draft) | codex-fix-a, 0f5b2a1 | Round 1 BLOCK (fix reintroduced the stale-row class), fixed; 223 tests. Round 2 is running. |
| [37](https://github.com/djbclark/djbclark-ade/pull/37) skill-everywhere symlinks (batch B, security P2) | codex-fix-b, db413a9 | Round 1 APPROVE LOW only, quoted in the body. Ready; `@codex review` requested 2026-10-24T00:00:58Z. Waiting on CI and Codex. |
| [38](https://github.com/djbclark/djbclark-ade/pull/38) acp-run/acp-dispatch (batch C) | codex-fix-c, fe69c41 | Round 1 APPROVE LOW only, quoted. Ready; `@codex review` requested 2026-10-24T00:09:13Z. Waiting on CI and Codex. |

Every PR's macOS `pytest` fails the same master test until PR 35 merges: `tests/test_self_slash.py::SelfSlashPaseoTests::test_successor_to_a_non_claude_provider_from_another_provider_passes_no_mode`.
That failure is known and not the PR's; PR 33 merged with it, by judgment.

## What We Tried

1. Codex findings selected by head SHA only (the prototype `~/.local/state/bigteam/adhoc-2026-10-23/pr-wait.sh` and
   my own filter) read "0 findings" on PR 32 while a P1 on earlier head 3c40470 was open. The source of truth is
   GraphQL `reviewThreads.isResolved`, plus the marker's `has_unresolved_findings` for both `code_review` AND
   `security_review`. Round 3 on PR 34 caught the security half.
2. The first `gh pr merge 32` failed: the PR conflicted after PR 33 merged. A hermes-ping in the same command had
   already said "merged"; a correction ping followed. The rule is now in
   `site-private/memory/feedback_ping_telegram_and_chat.md`: ping only after verifying.
3. Deriving the round 4 brief by blanket `replace("adv-selfslash-3","…-4")` rewrote the "read round 3's report"
   pointer. It was corrected with `acp-dispatch tell`; the rule is in memory `feedback_briefs_quoted_heredoc.md`.
   `acp-dispatch` strips a copied footer, so footers are not a problem.
4. `xargs -d` is BSD on this Mac (a hook blocked it); use `gxargs`. BSD `chmod --` failed; use `gchmod`.
5. PR 35's fail-open was patched three times (stream, missing key, malformed value). Each round found the next
   variant, so prefer a whitelist (accept only known-good values) to patching variant by variant.

## Key Decisions

1. Accepted LOW-only verdicts as merge-ready (PRs 37 and 38) instead of another Opus round. The LOWs are in docs/queue.md item 9.
2. Declined two triage findings: PR 25 4323896253 (relay.py refuses safely, and relay.py is mid-edit by
   another session) and PR 22 4323297397 (footer slot wildcard; low impact). Their threads stay open.
3. Fixed PR 35's round 4 LOW myself rather than via the worker (a small, clear change).
4. Merged PR 33 with the known-red macOS test, rather than holding every PR until PR 35 lands.
5. d618809 went straight to master: mode-only, restoring a broken hook. Other sessions also commit directly here.

## Evidence & Data

1. The triage counted 112 threads: fixed 93, process 11, still-applies 8 (all P2). Thread dumps are in
   `~/.local/state/bigteam/rework2-codex-triage/threads/`; the resolution log is `resolve.log` (resolved=104, failed=0).
2. The nudge hook: `hook-deadline 4 ~/.claude/hooks/context_size_nudge.py` gave rc 127 before d618809 and rc 0 after.
3. Briefs, reports and fix notes live under `~/.local/state/bigteam/rework2-{subagent-model,pr-wait,review-selfslash,codex-triage}/`.

## Operator Feedback

Nothing new this half of the session. Earlier rulings: queue items 1 and 2 approved (2026-10-23); coordinate with
djbclark-ade-rework-pw (peer 6ebd939, relay id a0c69a11).

## Where We're Going

1. **Read each running review as its waiter returns, then carry each PR to merge** (Detached jobs below):
   1. PR 32: on round 7 APPROVE, update `~/.local/state/bigteam/rework2-subagent-model/pr-body-final.md` to quote it
      with 9fa0605 and `gh pr edit 32 --body-file` it. Codex last reviewed dcf7e8d: comment `@codex review`, then wait
      for the marker's `code_review.commit_sha` and `security_review.commit_sha` to equal 9fa0605, both `completed`
      with `has_unresolved_findings: false`, and GraphQL to show no open Codex thread. Then merge with
      `--match-head-commit 9fa0605…` (full SHA: `git -C ~/.cow/pastures/kool-ade/subagent-model rev-parse HEAD`).
      Verify `state` is `MERGED`, THEN hermes-ping.
   2. PR 35 round 5 is **APPROVE (head d102e18, LOW only)**, the last line of
      `~/.local/state/bigteam/rework2-review-selfslash/adv-selfslash-5-report.md`. Decide on its F1 before merging.
      On macOS /bin/bash 3.2 with a UTF-8 collation locale, the `[a-z0-9_-]` range at bin/self-slash:706 matches
      "Claude"/"CLAUDE"/"claudé". So a plan agent can still get a bypassPermissions claude successor.
      1. Recommendation: fix it. Spell the class out (`*[!abcdefghijklmnopqrstuvwxyz0123456789_-]*`) or
         `LC_ALL=C` for the `case`, add a test row, and run a quick round 6. F2 is the usage text at
         bin/self-slash:164-165, which should name the not-a-string/not-a-plain-id refusal.
      2. Otherwise record F1 as an accepted LOW in docs/queue.md item 9.
      3. Then quote the verdict and the SHA in the body, `gh pr ready`, `@codex review`, wait, and merge. Merge PR 35
         FIRST: it turns master's macOS CI green.
   2a. PR 36 round 2 is **BLOCK (head 0f5b2a1, MEDIUM)**, the last line of
      `~/.local/state/bigteam/rework2-codex-triage/adv-codex-fix-a-2-report.md`. A borrowed 5-hour twin with no
      reset or pace ages the decision without supplying a reported value. That is the idle shape, 229 of 300 real
      snapshots. The result is a false stale/watch and a collector-down ping on the mixed shape, at
      bin/claude-quota-guard:370-371 and :506.
      1. Send the report's findings section to the codex-fix-a worker (`acp-dispatch resume` on its record under
         `~/.local/state/bigteam/rework2-codex-triage/jobs/`).
      2. Then run adversary round 3, written fresh per memory feedback_briefs_quoted_heredoc.
   2b. PR 34 (round 4): on APPROVE, the same flow as PR 35.
   3. PRs 37 and 38: their prototype waiters may not survive the clear. If `~/.local/state/bigteam/rework2-codex-triage/pr3{7,8}-wait.rc` exist, read them and the `-wait.log` files beside them; otherwise check directly: `gh pr checks N --json
      name,state`; the Codex marker on the comment with `codex-pull-request-review-summary` (both reviews,
      head SHA); GraphQL `reviewThreads` (unresolved, any comment from `chatgpt-codex-connector`). Then merge with
      `--match-head-commit`.
   4. After PRs 36-38 merge, resolve their 6 triage threads (36: 4361062518, 4361062506; 37: 4361214081; 38:
      4322594869, 4323297404, 4324164145).
2. When PR 34 merges, use `bin/pr-wait` for every later PR instead of the prototype.
3. When 24f5b849 (relay b242f866, standalone-869e) relays that relay.py and fleet.py have landed, add the
   workspace-name-ledger queue entry from `~/.local/state/bigteam/workspace-name-ledger/brief.md` and build it.
   The main checkout's dirty relay/fleet/helm/session-finder files are that session's; never stage them.
4. Peer 6ebd939 (PR 31, claude-fleet-governor) was told about its two current open Codex threads. On its handoff,
   adopt `~/.local/state/handoffs/chains/standalone-329d/SESSION_LOG.md`.
5. Remove pastures as their PRs merge: `bin/cow-pasture remove kool-ade/<name> --force`, after checking
   `git status` and that nothing is unpushed. Pastures: subagent-model, pr-wait, review-selfslash, codex-fix-a/b/c,
   codex-triage (read-only, removable now), modes-hotfix.
6. Watch `bin/claude-quota-guard status` until 2026-10-30.

## Detached jobs

1. `~/.local/state/bigteam/rework2-subagent-model/jobs/adv-subagent-7.json`: PR 32 round 7 (merge-only review of 9fa0605).
   1. Report: `~/.local/state/bigteam/rework2-subagent-model/adv-subagent-7-report.md`; `.done` not yet present.
   2. Rearm: `~/src/djbclark-ade/bin/acp-dispatch-wait ~/.local/state/bigteam/rework2-subagent-model/jobs/adv-subagent-7.json ~/.local/state/bigteam/rework2-subagent-model/adv-subagent-7-report.md.done`
2. `~/.local/state/bigteam/rework2-pr-wait/jobs/adv-pr-wait-4.json`: PR 34 round 4 on a4366f8.
   1. Report: `~/.local/state/bigteam/rework2-pr-wait/adv-pr-wait-4-report.md`; `.done` not yet present.
   2. Rearm: `~/src/djbclark-ade/bin/acp-dispatch-wait ~/.local/state/bigteam/rework2-pr-wait/jobs/adv-pr-wait-4.json ~/.local/state/bigteam/rework2-pr-wait/adv-pr-wait-4-report.md.done`
3. adv-selfslash-5 (PR 35 round 5) and adv-codex-fix-a-2 (PR 36 round 2): read, `check` rc 0, and closed.
   Their verdicts are in item 1.2 and item 1.2a.

After reading each report: run `acp-dispatch check <record>`, then close it with
`jq '.closed=(now|floor)' f > f.tmp && mv -f f.tmp f`. The PR 37 and 38 CI/Codex waits were `run_in_background`
prototype waiters and do not survive: check those PRs directly (item 1.3).

## Quick Start

```bash
cd ~/src/djbclark-ade
for r in rework2-subagent-model/jobs/adv-subagent-7 rework2-pr-wait/jobs/adv-pr-wait-4 ; do bin/acp-dispatch check ~/.local/state/bigteam/$r.json; done
for n in 32 34 35 36 37 38; do gh pr checks $n --repo djbclark/kool-ade --json name,state > /tmp/c$n.json; echo "$n rc=$?"; done
gh api graphql -f query='query{repository(owner:"djbclark",name:"kool-ade"){pullRequest(number:37){headRefOid reviewThreads(first:100){nodes{isResolved comments(first:100){nodes{databaseId author{login}}}}}}}}' > /tmp/t37.json
```
