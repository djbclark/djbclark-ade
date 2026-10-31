---
schema_version: 1
handoff_id: c671
parent_handoff_ids: []
lineage: none
chain: [go-followups-20261025]
repo: kool-ade
workspace: codex-herdr-env
branch: fix/codex-herdr-env
head_sha: 6e795a593b831bee6e8c373e8fc11d94699aeaaa
created_at: 2026-10-25T22:59:10-04:00
writer: codex
---

# Handoff — Go safeguards delivered; finish Codex/Herdr review

## The Goal

Investigate OpenCode Go spend and implement proportionate model/context safeguards.
That work and its RTK/setup follow-ups landed. Finish the remaining Codex/Herdr
environment fix in [PR 71](https://github.com/djbclark/djbclark-ade/pull/71), with
current-head review, operator-approved merge and activation, and a fresh-session
probe. Keep long jobs in the background so conversation remains responsive.

## Where We Are

At the audit, the claimed worktree was clean and fully pushed at the frontmatter
SHA. Subsequent source changes add this handoff and a narrow lifecycle safety guard
described below; reviews must cover their final pushed head. The shared checkout was
clean on master at 7aa20eef990c28a770ee30c891247adc2c70ef75, seven commits behind its
then-current origin/master. It is a side workspace owned by another chain; never
replace its Tier 1 pointer. Recheck all git and hosted state on resume.

PR 71 merged master through 5e72a8f, preserving both sides of the changelog.
Its final policy uses inherit=all, default exclusions enabled, and no include_only.
It retains four-owner-marker scrubbing for ACP children and the atomic,
output-redacted configuration installer. Live Codex configuration was not changed.

The worker is DONE. Its final report records 76 focused tests and 979 subtests
passing through bg, a passing template check and an exclusion-policy mutant caught.
Those are worker-reported results, not a new root test run. Hosted macOS/Linux
tests were still running at the audit; context-policy passed, Cursor checks were
neutral. No review threads were open.

Important missing delivery: the PR description still describes the old strict
allowlist and quotes adversary approval for 1e7f941, not the revised head. The
independent review of the revision has NOT been dispatched. Codex's summary also
still covers 1e7f941: code review running, security completed. Neither is approval
for the revised head. Do not treat pending CI as the only remaining work.

## What We Tried

The original narrow allowlist restored six Herdr variables while excluding other
terminal context. A newer master commit deliberately restored broader inheritance;
the worker correctly blocked rather than choosing between contradictory policies.
The operator then selected master's broader inheritance in /steps, and the same
worker reconciled the branch without a new dispatch or live changes.

An older Codex code review stalled after two requests; its waiter timed out after
2700 seconds. Do not repeatedly request the same old review or infer a clean result
from timeout. Review the new final head once, collect state by SHA and unresolved
threads, and escalate a genuinely stalled gate rather than silently waiving it.

Native request_user_input works in Plan mode. Asynchronous submission is not proof
that a terminal chooser appeared. Repeated /steps was not an answer. The latest
operator choices below were collected through the native chooser.

During handoff execution, a lifecycle dry run without Herdr tool variables selected
an unrelated Paseo Cline agent. Explicit Codex baton syntax made it refuse before
sending anything. The parent Codex PID 15849 retained the six Herdr variables;
fresh herdr agent get confirmed the current CODEX_THREAD_ID matches w2F:p45.
Added a fail-closed CODEX_THREAD_ID guard before Cline hub discovery, a fake-hub
regression test, a handoff instruction and changelog entry. Real lifecycle calls
restore only the verified parent host variables and name this owned chain explicitly.
The verified-identity dry run succeeded for herdr w2F:p45 with exactly `/new` then
`$baton /Users/djbclark/.local/state/handoffs/chains/go-followups-20261025/SESSION_LOG.md`.
No lifecycle command was sent during either dry run. The new guard's targeted
regression run was queued through bg, but had not run because load 40.04 exceeded
the eight-core machine's gate. Do not claim a pass or bypass the load gate.

## Key Decisions

Preserve master's broader launching-terminal inheritance and Codex's default
exclusions. The strict allowlist was explicitly rejected. Do not reopen this policy
decision or reserve relay/fleet/where changes for this branch.

The operator approved and received PR 68 merge/activation. PR 71 merge and live
activation remain unapproved: prepare a concrete reviewed artifact first, then ask.
The operator declined rotation of a credential exposed during review. Leave it
unchanged; do not reopen that choice or read credential-bearing transcripts.

The operator chose handoff and continue after /loose. They want background work,
one question at a time for real decisions, and no duplicate CI/watch terminals.

## Decisions

- [ruling] "1. Keep master (Recommended)" (djbclark, 2026-10-25)
- [ruling] "2. Leave token unchanged" (djbclark, 2026-10-25)
- [ruling] "1. Handoff and continue (Recommended)" (djbclark, 2026-10-25)
- [decision] Keep broader inheritance with default exclusions; rejected: strict include_only policy; because the operator selected the newer master policy; in [PR 71](https://github.com/djbclark/djbclark-ade/pull/71).

## Relations

- decided_in [[HANDOFF_go-followups-20261025_final-review_2026-10-25_c671]]

## Evidence & Data

Private task root: /Users/djbclark/.local/state/bigteam/go-followups-20261025/.
Read codex-env-report.md only with its finalized .done marker. The directory is
mode 0700; retain paid reports and backups. Do not read the original
codex-adversary.jsonl or its model transcript: that review exposed a credential.
Use the sanitized codex-adversary-r2-report.md as historical evidence only.

Changed implementation paths: agents/codex/config.toml.tmpl, agents/README.md,
bin/codex-env-policy-apply, tools/acp-run/acp-run and README, focused tests,
docs/orchestration-practices.md and CHANGELOG.md. Installer hardening includes
private backup creation, atomic replacement at realpath, unrelated-byte and set
preservation, repeat no-op, malformed input and concurrent-change refusals, and
secret-safe output. Preserve those regression proofs when fixing review findings.
Handoff execution also changed bin/self-slash, tests/test_self_slash.py and
skills/handoff/SKILL.md for the Codex/Cline discovery safety guard.

[PR 64](https://github.com/djbclark/djbclark-ade/pull/64),
[PR 65](https://github.com/djbclark/djbclark-ade/pull/65) and
[PR 68](https://github.com/djbclark/djbclark-ade/pull/68) were verified MERGED;
[PR 70](https://github.com/djbclark/djbclark-ade/pull/70) was verified CLOSED.
The live OpenCode plugin guard check returned zero and both managed plugins matched
canonical copies. The native Go guard symlink exists. Production compaction and
restart persistence remain normal-use verification, not proven live repairs.
The original Go work's completion artifact is
/Users/djbclark/.local/state/bigteam/go-cost-context-policy/implementation-complete.md.

Upstream search covered open/closed issues and PRs in openai/codex using
shell_environment_policy filters and include_only inherit. Nearest reports:
[ignored filters](https://github.com/openai/codex/issues/40896) and
[app-server inheritance](https://github.com/openai/codex/issues/48096).
No distinct new bug was established; do not file a duplicate without reproduction.

The removed Go follow-up worktree is gone. A private temporary reviewer probe
remains at /tmp/codex-adv-check/check.py (0600); preserve evidence rather than
discarding paid work. No uncommitted probe edits were present in either checkout.

## Operator Feedback

Background commands must remain conversational: detach once, keep one waiter per
head, and do not hold the turn open with repeated long polling. Never cancel paid
work without approval. Coordinate via session-finder/relay.py, not direct panes.
Peer lead e934e0e6-6767-40be-bc72-576254955377 acknowledged that it will not touch
PR 71 or its worktree. No reply was requested. New relay questions require
--expect-ack; follow current relay instructions.

## Where We're Going

1. Refresh PR 71's actual head and CI, then obtain fresh exact-head independent
   adversary review using the clean codex-adversary-r2 record below. Re-probe quota
   and current routing first. No new feature work or live configuration changes.
2. Rewrite the PR description around broader inheritance, the actual focused
   results and the final-head verdict. Remove stale approval claims. Request the
   required Codex reviews for that final head and use one background pr-wait.
3. Fix actual findings in the claimed worktree, push, and refresh only affected
   validation/reviews. Never count an old-head verdict as current approval.
4. Once all required evidence is ready, use /steps for explicit PR 71 merge and
   activation approval. Merge with --match-head-commit, then run the reviewed
   installer and fresh zero-inference probes. Do not restart busy agents.
5. Update owned state, report limits honestly, remove the owned worktree only
   after completion, and send one hermes-ping per completion/operator-needed event.

## Detached jobs

All four task job records were finalized DONE and their reports collected; no
unfinished model job needs rearming. Historical records remain intentionally open
for report retention and in-place continuation, not as proof that a process runs.

The clean review record is
/Users/djbclark/.local/state/bigteam/go-followups-20261025/jobs/codex-adversary-r2.json;
its report is the task root's codex-adversary-r2-report.md and .done exists.
Resume this record with a new exact-head read-only review brief, never the
credential-contaminated original codex-adversary record. After resuming, use its
printed rearm command once in the background. Worker record codex-env.json is
DONE; resume it only for an actual requested fix, never to reconstruct a report.
rtk-adversary.json is DONE and needs no further work.

A separate targeted local test is pending behind bg's load gate, tool terminal
session 72179. Its command, from the claimed worktree, is:
`/Users/djbclark/ops/site-private/bin/bg uv run --with pytest python -m pytest -q tests/test_self_slash.py -k 'a_codex_session_is_never_discovered or a_claude_session_is_never_discovered'`.
Collect its exit/output if the terminal remains available; do not cancel or repeat
it while pending. It is a session child rather than a durable ACP dispatch. If it
does not survive, the final pushed head's hosted suite remains the validation
authority; never reconstruct a local pass. No dev server or probe service runs.

Hosted CI survives the chat session. No active current-head review aggregator was
started by root. Old pr71-final-summary.json is an old-head timeout, not current
status. Session-child terminal waiters are not promised to survive a reset.

## Quick Start

Read the owned chain, not the shared checkout's main pointer:
/Users/djbclark/.local/state/handoffs/chains/go-followups-20261025/SESSION_LOG.md.
Work in /Users/djbclark/src/djbclark-ade-codex-herdr-env-wt.

```sh
git status --short --branch
git rev-parse HEAD
gh pr view 71 --repo djbclark/kool-ade --json headRefOid,mergeable,statusCheckRollup,body
aiuse --available --json
```

Read the current model-routing and session-handoff skills. Use acp-dispatch resume
on the clean review record with -f BRIEF --detach --no-wait, followed by its single
background rearm waiter. Review only tracked diffs and synthetic test data; never
real configs or credential-bearing transcripts. No merge permission is implied.

Lifecycle note: use this worktree's bin/self-slash (includes merged PR 69), with an explicit --then baton argument naming the owned chain above. The shared checkout's main pointer belongs to another session. Codex uses $baton; do not submit /baton as plain text.
