---
schema_version: 1
handoff_id: 8381
parent_handoff_ids: [b457]
lineage: deterministic
chain: [standalone-b457]
repo: kool-ade
workspace: main
branch: master
head_sha: 760704f294857c9495af8d63b0aaca856f8aa63f
created_at: 2026-10-24T11:50:00-0400
writer: claude-code
---
# Handoff — PR 39 and PR 42 merged, queue additions, Paseo/tuios/fork rulings

## The Goal
Continue chain standalone-b457: land the ade-scan-state follow-up (done), get master CI green (Linux done), record djbclark's new queue items, then work the queue in order (docs/queue.md): isolation I0 W1-W8, Paseo tabs slices, Basic Memory W2-W8, then the Paseo connected-hosts upgrade, then (ask first) the fork-instead-of-brew question, tuios last.

## Where We Are
1. PR 39 (ade-scan-state follow-up after PR 27) merged as bcb1f8e after adversary round 70 (APPROVE at 14c7347) and a clean Codex review at 0c85f1b.
2. PR 42 (time-bomb fix in tests/test_acp_dispatch_quota_d2.py) merged as 760704f after adversary `adv-ci-green` (APPROVE at c12d005) and a clean Codex code and security review at 93980b9 (the first security review failed to run; `@codex security review` retry passed). Linux CI is green on it; macOS stays red on exactly one test, test_self_slash ...passes_no_mode, a real bash 3.2 bug (`mode_args[@]` unbound) that PR 35 fixes.
3. Master head 760704f, clean except untracked `.agents/skills/fastino-glide/` (not mine). No open job records of this session; the worktrees and branches of both PRs are removed.
4. Queue sections added to docs/queue.md this session (all pushed): Paseo connected hosts (items: quiesce, then design; corrected: shipped in stable 0.13.0, brew installed it 11:15 AM, daemon version unverified, restart needs a separate yes), ade-scan-state follow-up 2 (adversary round 70 leftovers: LOW shallow-with-origin bundles, INFO 2-5), tuios support (LAST, tertiary tier, ask before costly steps), firecrawl developer search resurface (end of queue; SKILL.md note committed 5734f37, fix prompt was put on the clipboard), consider dropping the brew Paseo for our fork (ASK FIRST, disruptive).
5. Other sessions: PR 44 (fix/ci-quota-fixture-and-bash32, the ~/ops unpin session) appeared while I merged PR 42 and overlaps both fixes: check it against master (its quota-fixture half is now duplicate; its bash 3.2 half duplicates PR 35). I told the unpin session (relay w2N:pW) that PR 42 is mine and PR 35 may be taken over. PR 40's owner (Paseo agent 24f5b849 "Relay route ladder") was told master is fixed, to merge master into PR 40 and ask djbclark before merging.

## What We Tried
1. Guessed the red CI came from commits ec71303 and 76a3b94: wrong. `gh run list` showed macOS red since 184b14d (10-23) and Linux red from 12:27Z on 10-24 with a docs-only commit, which pointed to a clock-dependent test; the hard-coded quotaResetTimeStamp 2026-10-24T18:18:05Z was the cause.
2. Said "master red since 13:04Z": retracted (it was since 10-23 22:45Z on macOS).
3. `acp-dispatch omp --perm read-only` is refused (omp has no verified read-only mode): use `--perm all` with a read-only brief.
4. `firecrawl_developer_search` 404s: the Hyades backend has no /v2/search/developer (router log). A separate agent opened PR 41 (merged) to answer it from GitHub; resurface item still stands to remove the SKILL.md note if it now works.
5. `relay.py afe31994` found no session (it is a Claude session id fleet.py does not list); the Paseo agent id 24f5b849 worked.
6. A stray "@chief-of-staff" line slipped into the PR 42 body; removed immediately.

## Key Decisions
1. Fix the TEST (time bomb), not the code; do not duplicate PR 35's bash 3.2 fix. Rejected: rewriting the file's fixed-now parse tests.
2. Merged PR 39 and PR 42 past red macOS CI (the same single failing test as master, outside the PRs' files), disclosed in each hand-off message.
3. grokbot's paseo-queue-note request (twice) was a duplicate: 6e90e00 is already on master; branch left; comment posted on PR 39 (https://github.com/djbclark/djbclark-ade/pull/39#issuecomment-6386214964) at djbclark's yes.
4. Interface tiers: Paseo first-class, herdr second, tuios third (memory feedback_heavy_web_search). Heavy web search in all work.

## Evidence & Data
Master CI history: /tmp is gone after restart; reproduce with `gh run list --branch master --limit 60`. Reports: ~/.local/state/bigteam/adhoc-2026-10-24/{adv-scan-70,ci-green,adv-ci-green}-report.md. Tests: tests/test_ade_scan_state.py 245 passed 1 skipped (PR 39); tests/test_acp_dispatch_quota_d2.py 21 passed; CI on PR 42: Linux pass, macOS 3254 passed 1 failed (self_slash).

## Operator Feedback
1. Ask before restarting the Paseo daemon, and before replacing the brew Paseo with the fork (disruptive).
2. Fix prompt for the firecrawl problem goes to the clipboard and the problem is resurfaced at queue end.
3. Add paseo-queue-note answer to GitHub with the @chief-of-staff text (done).

## Where We're Going
1. THE NEXT ACTION: `cd ~/src/djbclark-ade && git pull --ff-only && gh pr list --state open` then check PR 44 (overlaps PR 42/PR 35) and whether the ~/ops unpin session took PR 35; do not write a duplicate fix.
2. `aiuse --available --json 2>/dev/null` (jq per `aiuse schema`), then work docs/queue.md top-down via `acp-dispatch` (route with `route_agent.py plan --kinds code`): ade-scan-state follow-up 2, I0 isolation W1-W8, Paseo tabs slices, Basic Memory W2-W8.
3. Ask djbclark before: restarting the Paseo daemon (verify its version first: connected hosts need 0.13.0), replacing brew Paseo with the fork, anything costly for tuios.
4. At the end of the queue: firecrawl developer search resurface; tuios last.

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git pull --ff-only && git log --oneline -5
gh pr list --state open
rg -n '^## ' docs/queue.md | head -14
aiuse --available --json 2>/dev/null > /tmp/aiuse.json; jq -r '.available[]|"\(.provider)\t\(.usable_now)\t\(.headroom_percent)"' /tmp/aiuse.json
```
