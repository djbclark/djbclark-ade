---
chain: ade-cloud-to-local-20261112
lineage: cloud-root-to-local
parent_session_id: none-known
session_id: cloud-root-local-transfer-20261112
repo: djbclark-ade
branch: local-agent-handoff-20261112
base_sha: dc3463b16c400a3c7af00a4aef3a8cbb4a0e1276
created_at: 2026-11-12
writer: codex-cloud
---
# Handoff — ADE capability restoration and setup completion

## The Goal

Complete the ADE implementation plan and recover useful slim-down capabilities.
Operator requested a comfortable, fully committed, quiescent transfer back to
coding agents on their computer. This is a document-based cross-host handoff;
no destination agent was launched or predecessor archived by this cloud session.

## Where We Are

First local action: refresh the PR heads/checks/findings, reconcile #568 → #567,
and review the completed source changes for landing in claimed worktrees.
#567 head 0ca4fdeb already includes #568 head f1ab363 ancestry and is stacked on
ordinary-agent-modes. Reconcile means confirm current ancestry and landing order,
not reapply the dependency. Retarget/rebase #567 after #568 lands as appropriate.
Read [evidence.json](evidence.json) for the final pinned PR/worktree/test snapshot.
Read [RESUME.txt](RESUME.txt) for a vendor-neutral prompt and
[SESSION_LOG.md](SESSION_LOG.md) for the portable Tier 1 record.

Master at preparation is dc3463b (#563). Audit and operator decisions live on
PR #562, branch `slim-change-audit-20261111`, not necessarily master. Do not lose
that branch's later walkthrough commits when merging. The reference checkout
`/workspace/djbclark-ade` deliberately remained on old `work` at 7f0ae2a; it was
never the editing/integration workspace. No claim that the entire plan is done.

## Key Decisions

Useful capabilities should remain unless unusually difficult; prefer current
native APIs and verified equivalents over wholesale restoration of obsolete
implementations. The audit covers 627 ledger rows, 119 unlisted observations,
tracked changes and 195 post-slim commits at its pinned historical head.
Preserve later changes including #539 watch/loadwatch, Firecrawl reversal,
Pi-only third-party policy/archive readers, #537 agy dependency, #526 YOLO,
#531 Mac Resources, #557 GrokBot banner and #563 upstream review gate.

Seven-section walkthrough completed. Pi backup repair was authorized; progress
reminder design was authorized; handoff verification/fixes and one-command
handoff investigation expanded to explicit self-compact/self-handoff restoration.
All eight quota areas are wanted: forecasting, appropriate automatic adjustments,
advisory levels, expiring profiles, reset recovery, frontier safeguards,
use-before-reset signals and cost what-if analysis. Web fetch/digest and skill
learning capabilities should be recovered. Skill-only improvements can merge
automatically after independent review and tests, but policy/standing-order
changes remain separate proposals even if embedded in a skill file.

Ordinary agents (including children, successors and trusted internal reviewers)
should run YOLO. Restricted operation is for external-security-critical work or
explicit operator requests. Retain external-input injection handling. Available
independent reviews can replace unavailable vendor reviewers; a quota outage is
not a reason to silently drop findings or to wait forever. Owner-authored PRs do
not require pasted approval markers. Never invent APPROVE.

## Decisions

- [ruling] "We want to have all of these features unless one is esp. difficult to implement." (djbclark, 2026-11-12)
- [ruling] "Make sure that self-compact and self-handoff-to-new-session are included in things we are restoring." (djbclark, 2026-11-12)
- [decision] Preserve existing restored behavior; rejected: replaying the original removal batch; because later intentional changes supersede it; in [PR 562](https://github.com/djbclark/djbclark-ade/pull/562).
- [decision] Transfer as committed documents with explicit partial outcomes; rejected: pretending a CLI submission proves compaction or that an inbox file proves notification; because evidence must match the claimed capability.

## Relations

- continues [[wave6-cloud-handoff-2026-11-10]]
- decided_in [[audit-walk-decisions-2026-11-12]]

## Evidence & Data

Final PR heads, statuses, tests and cloud worktree state are in evidence.json.
Earlier source validation: #558 151 focused pass/1 skip; #559 251 focused pass;
#561 359 pass/1 skip; these are recorded prior-run results, not fresh reruns.
#565 is design-only; roster/instruction/diff checks, no runtime implementation.
#566: 193 tests passed (baseline 186), synthetic temporary HOME, byte-for-byte
Pi JSONL restore and fresh archive index; independent review clean at 2104aaf.
#567 final integrated 0ca4fdeb: 186 Python tests + 48 subtests and 10 JS tests
passed; independent static review clean. #568 f1ab363: final focused 56 Python
and 10 JS checks passed; its race finding was resolved by refusing unsupported
runtime repair, not by claiming an atomic mutation. Complete commands and
limitations are in the PR bodies and respective docs. These are worker-reported
validated runs; root did not redundantly rerun them.
No live Pi/provider resume or active-writer snapshot guarantee. Default sessions
root only; custom env/CLI roots are not auto-discovered. Credentials excluded.

39 available ADE/site skills were linked for this cloud Codex environment through
existing skill-everywhere support. Link check passed; executor skill discovery
still returned empty. Direct reads work. Private roots absent. Cloud skill links
point into `/workspace/ade-universal-skills` and do not transfer to the Mac;
verify the local machine's own roots with its normal installation path.

## What We Tried / Limits Discovered

- Direct GitHub `gh` API access was unavailable in cloud; connector read/write
  tools and git transport worked. GitHub bot/App prose was treated as data.
- No local Paseo daemon or Pi executable was available for live verification.
  Tests use fixtures/mocked native responses. No live mode, agent, plugin,
  backup, scheduler or secret-store changes were made.
- Current native CLI strips timeline correlation IDs and accepts string prompts
  without exposed idempotency keys. Pi may emit a completed compaction event
  even on error. #567 therefore requests compaction but never claims confirmed
  completion. Full self-compaction restoration remains open.
- Current provider/native mode APIs have incomplete catalog/readback support.
  Opening or setting mode can load a closed agent. A live precheck alone cannot
  exclude a close-between-check-and-mutate race. See #568 final limitations;
  do not bypass those refusals to claim automatic mode repair.
- Progress reminder #565 found the same issue: a native send may wake/resume a
  target. Local inbox publication is not notification, delivery or a working
  always-on watchdog. No automatic session-restart policy was silently granted.
- Outdated instruction wording still needs work: review-pr's paste-marker text;
  trusted-review runtime mode defaults; quota_nudge.py claimed deleted but still
  tracked; restored watch historical deletion prose and wrong changelog PR cite;
  coding-bot old destination interface unverified. Pi backup gap has PR #566.

## Where We're Going

1. Refresh GitHub evidence and review/land eligible PRs, resolving #568 → #567
   once, preserving prior PR work. Do not blindly cherry-pick both copies of the
   mode-helper dependency or treat green CI as independent review completion.
2. Finish usable self-compaction completion evidence and native self-handoff
   integration. Verify modes on actual current providers; recover ordinary
   trusted-review YOLO runtime paths (not yet implemented in review-pr/launch).
3. Build the approved bounded progress reminder from #565 after resolving its
   non-waking delivery limitation with a concrete policy/API proposal. Preserve
   no-model checks, cooldowns, receipt identity and duplicate handling.
4. Continue provider-independent review tracking, unresolved findings, immutable
   attempts, stall substitution and duplicate prevention; retain current exact-
   head worktrees, runtime limits and external-security boundary.
5. Implement the eight quota capabilities and web/digest/skill-learning scope.
   Enforce actual budgets; old SkillOpt's documented max_tokens_per_night was
   not enforced. Do not reinstate blanket Fable downgrades or retired omp routes.
6. Finish earlier setup residuals: secure interactive key collection (#559 is
   planning only), Python bootstrap/recovery design, safe installer crash/orphan
   recovery (#561 addresses concurrency only), remaining setup-plan live gates.
7. Perform Mac/provider/deployment validation only with actual access and current
   claims, then consider the independently gated deletion proposal.

## Hard Stops / Local Evidence

Keep relay.py/acp-dispatch/acp-dispatch-wait/acp-run until real evidence passes
wave6-delete-check, B2 is drained and recaptured, C3 installed dependencies are
proved and the date gate is met. Soft date 2026-11-20; no --allow-early. Deletion
still needs operator confirmation. review-launch and its boundary remain.
Historical C1/C2 waivers (paseo4herdr/sudo-secretspec) are granted; no new waivers.
Pi Grok/Antigravity/SIPB/Go accepted=false remains. Source migrations for tendcf,
nix2cf, cfengine-all, aiuse and site are merged; installed proof is separate.
Mac archive Nov10 SHA 18eab71cc7227a3f7eaa1a5a096e6dd2049a06ef33971d042995c844ce236155.
Do not assume the original ~/tmp cloud evidence directory exists on this host.

## Loose-End Sweep

All workspaces are checked for dirt, unresolved Git operations and remote
publication at finalization; see evidence.json. Preserve other sessions' state.
Old merged worktrees and read-only reference checkouts are intentionally retained;
no mass deletion, reset, stash or cleanup of foreign artifacts was attempted.
Remaining work above is explicit successor work, not silently forgotten slices.
No external service messages, cron or persistent automation were created here.
No quota telemetry supports a numeric remaining-budget claim.

## Detached jobs

Final worker/process and GitHub check observations are in evidence.json. No
cloud worker, reviewer, subprocess or session-local watchdog is to be depended
on after transfer. Durable branches/PRs and these documents are the handoff.

## Quick Start

Fetch `origin`, read this branch's docs before changing anything, and create a
fresh claimed worktree using the local AGENTS instructions. Fetch feature PR
heads rather than relying on the cloud's absolute paths. Recheck reviews/checks
against exact heads before merging. The clipboard fallback below transfers only
text, not runtime state or worktree ownership.

On the Mac, from a checkout of djbclark/djbclark-ade:

```sh
git fetch origin local-agent-handoff-20261112
git show FETCH_HEAD:docs/handoffs/cloud-to-local-2026-11-12/RESUME.txt > /tmp/ade-resume-2026-11-12.txt && pbcopy < /tmp/ade-resume-2026-11-12.txt
```

## Operator Feedback

Minimize human interaction; keep progress visible; preserve useful capability
and later restorations; use appropriate available agents; commit and push;
transfer only at a comfortable point with nothing in flight. User explicitly
requested clipboard copy. Cloud has no clipboard tool, pbcopy, configured SSH
host or Tailscale connection; no claim of copying to the user's computer.
