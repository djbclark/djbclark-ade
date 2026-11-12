# Audit walkthrough decisions — 2026-11-12

This records the operator's one-item-at-a-time `/steps` walkthrough of
[the slim-down audit](change-audit-2026-11-11.md). Later choices take precedence
over the original removal plan. No runtime restoration is implied by a design choice.

## 1. Load monitoring and persistent progress

Operator selected **Design a persistent progress reminder** after comparing the
removed monitoring capabilities. Queue the design after the walkthrough:

- Cheap deterministic checks for unfinished work, stale handoffs and idle agents
  with declared next steps; evaluate available native sources and transport.
- Change/due-only notifications, cooldowns and verified delivery.
- Do not revive old relay dependencies or self-deploying checkout behavior.
- Automatic session restart is a separate decision, not authorized by this choice.
- No new decision to restore per-app CPU history, session-load-watch or old watcher
  lifecycle management. Keep existing `/watch load`, `/loadwatch` and load-watch.

Outcome: **design queued**, not implemented or installed. A session-local watchdog
is not a persistent substitute and cannot be assumed to wake a stopped session.

## 2. Pi backup coverage

Operator selected **Repair Pi backup coverage; preserve archives**. Queue the
implementation after the walkthrough:

- Restore coverage of Pi session/history data in the ADE backup tool.
- Preserve credential exclusions and existing retired-client archives.
- Add meaningful backup/recovery validation using fixtures; do not copy live
  credentials or treat an archive reader as proof of backup coverage.
- Live Mac verification remains separate from cloud source/test completion.

Outcome: **repair queued**, not yet implemented or installed. This choice does
not revive retired clients, remove their archives or change pool acceptance.

## 3. Dispatch and handoff

Operator selected both **Verify native handoff and fix demonstrated gaps** and
**Compare removed dispatch/handoff features in detail**.

Queue focused cloud verification and repairs after the walkthrough: successor
acknowledgement, preserved handoff records, predecessor archiving order, timeout
behavior and explicit recovery outcomes. Distinguish source/fixture validation
from later live Mac evidence. Do not revive the old launcher stack wholesale,
change pool acceptance, remove transitional shims or infer permission for
unattended session restart. Provide the detailed comparison during this walk.

Outcome: **verification/repairs queued**; comparison delivered in the walkthrough.

### 3a. Additional investigations selected

Operator selected both **Investigate a one-command native handoff** and
**Examine permission-mode drift and recovery further**.

Queue a native handoff convenience design with durable records, successor
acknowledgement before predecessor retirement, retry/duplicate protection and
explicit partial-failure outcomes. Do not restore input-typing or legacy relay
machinery merely for convenience.

Source inspection: ade-yolo hooks only agent.create.before; no resume or
continuous mode-repair hook is registered. Static unattended mappings cover
Claude/Codex and archived OpenCode/omp; Cursor/Pi/Antigravity/Hermes are not
mapped because catalogs are dynamic/unverified. Preserve explicit restrictive
modes and review-launch. Investigate provider-native mode discovery, verification
and drift recovery for ordinary work under the existing unattended policy;
source presence is not proof of installed plugin or end-to-end behavior.

Outcome: **investigations queued**, source comparison delivered; no mode changes,
plugin installs or automatic recovery behavior enabled during the walkthrough.

## 4. Quota controls — retain/recover all capabilities

Operator selected **Compare the removed quota controls in detail first**.
After the comparison, operator instructed: **“We want to have all of these
features unless one is esp. difficult to implement.”** This supersedes the prior
unselected quota options. Queue all eight capability areas: predictive quota
conservation, task-appropriate automatic model/provider adjustment and
restoration, advisory levels/reminders, expiring spending profiles, quota-stop
checkpoint/reset continuation, retained frontier allowances, surplus-before-reset
signals, and cache/compaction cost what-if analysis.

Use current providers and APIs; preserve existing restored functionality and
prior hard stops. Capability recovery does not mean reverting historical code,
reinstating retired clients or the governor's unconditional Fable downgrade.
Existing implementations count where their behavior is verified. Investigate
cost and feasibility first for provider switching and interruption recovery;
report concrete exceptional difficulty with alternatives rather than silently
omit features. No feature is declared exceptionally difficult solely on a
preliminary estimate. Source work is queued; live configuration is not yet changed.

For the rest of the audit, treat capability retention as the operator preference;
do not repeat per-feature yes/no questions where that preference resolves them.
Material tradeoffs and unusually difficult implementations still need explanation.

Comparison distinguishes predictive fleet-wide conservation, quota advisory
levels, temporary expiring profiles, exhaustion/reset recovery, retained frontier
headroom gates, retained pace/waste routing information, and removed cost what-if
analysis. Pause/resume does not replace exhaustion prediction. Old governor also
downgraded Fable at every level and steered critical leads to now-retired omp;
these behaviors must not be resurrected from historical code without a new choice.

## 5. Web, moved skills and nightly learning

Walkthrough continued under the capability-retention preference. Recover web
fetch fallbacks and bounded digest capability where current tools do not already
provide them; keep the restored Firecrawl router. Verify discoverability of moved
site skills rather than duplicate their source back into ADE. Restore useful
skill maintenance capabilities through current distribution/validation tooling.

Nightly learning source comparison: historical SkillOpt harvested transcripts,
replayed tasks and staged skill/instruction proposals; auto_adopt was false.
The historical guide explicitly reports max_tokens_per_night was unenforced at
its cited revision. A replacement needs actual budget enforcement, evidence
handling, current provider adapters and regression checks, not a blind runner
restore.

Operator selected **Automatically merge validated skill-only improvements**:
independent review and regression checks precede PR-based automatic adoption;
standing-order changes remain separate proposals; suspected prompt injection
blocks the affected proposal. Classify changes by their effect, not just the
filename: a skill edit that rewrites standing policy is not routine skill-only
learning. No learning job, transcript harvest, model call or automatic merge has
been enabled during this walkthrough.

## 6. Reviews and permissions

Apply existing operator decisions, not a fresh approval cycle: ordinary owned
work runs unattended; owner-authored PRs do not need pasted APPROVE markers;
unavailable review providers may be replaced with available independent reviews.
Preserve the external-input prompt-injection boundary, actual findings, required
checks and exact-head review evidence. Do not fabricate a marker or count a
skipped/unavailable reviewer as a completed review. Useful old review safeguards
should be recovered provider-neutrally, not by reviving a hard Cursor/Codex quota
dependency. This step explains the recommendation; no gate code changed.

### 6a. Detailed review comparison requested

Operator requested the before/after safeguard comparison. Source confirms
review-pr/review-launch retain exact-head detached worktrees, head validation,
structured verdicts, runtime limits and cleanup. Do not describe these as wholly
lost. What was lost includes automated consumption of local review receipts,
Codex finding/thread/request-state gates, stuck-review/re-request machinery,
per-head duplicate locks and admission control. Recover useful behavior through
available independent reviewers rather than reintroducing a required vendor.
Concurrent same-head review-pr results currently share a filename (last writer
wins), so review identity and immutable attempt evidence belong in the repair.
The review-pr docstring still teaches body-marker pasting, superseded for owner
PRs by the later owner-trust policy; document correction is needed.

No new manual-paste requirement, invented APPROVE, provider dependency, live
review launch or merge-gate code change is authorized by this comparison alone;
existing feature-recovery scope and prior trust decisions govern implementation.

## 7. Final gates and execution sequence

Operator chose to continue to final gates and repair sequence. Walkthrough
complete; no deletion approval requested or granted. Keep relay.py,
acp-dispatch/acp-dispatch-wait and acp-run until actual live evidence passes
wave6-delete-check, B2 is drained/recaptured, C3 installed callers are proved and
the date gate is met. No --allow-early, invented waives, invented APPROVE or Pi
acceptance flips. Deletion PR still requires explicit operator confirmation.
review-launch remains permanent. Nov10 evidence is historical, not a new probe.

Implementation order (parallelize disjoint work in separately claimed worktrees):

1. Pi backup repair plus bounded persistent-progress design; resolve audit
   documentation contradictions and preserve existing open implementation PRs.
2. Native handoff, permission-mode verification/recovery and provider-independent
   review evidence/coordination; build on proven current facilities.
3. Full quota capability recovery, including forecasting, appropriate automatic
   adjustments, temporary profiles, reset recovery and cost/waste analysis.
4. Web fallback/digest gaps and nightly learning with enforced budgets,
   independently reviewed automatic skill-only adoption and separate standing-order
   proposals; validate moved-skill access without duplicating source.
5. Live Mac validation/deployment evidence for completed source changes and, only
   after all original gates pass, a separately confirmed shim deletion proposal.

Design-only choices remain design-only (persistent reminder and one-command
handoff investigation) until a concrete proposal is prepared; agreed fixes can
proceed. No new broad permission question is needed for authorized ADE source
work. Escalate concrete unusual difficulty or unresolved policy tradeoffs.

| Item | Choice | Outcome at walkthrough close |
|---|---|---|
| 1 | Persistent progress reminder | Design queued; no runtime activation |
| 2 | Pi backup repair; preserve archives | Implementation queued |
| 3 | Verify/fix native handoff; investigate one-command handoff and mode drift | Queued |
| 4 | All quota capabilities unless exceptionally difficult | Recovery work queued |
| 5 | Recover web/skill capabilities; auto-adopt validated skill-only learning | Queued; standing-order edits remain proposals |
| 6 | Recover useful review coordination; preserve owner trust and external boundary | Queued under existing policy |
| 7 | Preserve evidence/date/operator deletion gates | No deletion authorized |

## 8. Explicit restoration requirements — operator follow-up

Operator explicitly requires restoring **self-compact** and
**self-handoff-to-new-session**, not just documenting manual replacements.
Investigate native APIs first and implement usable agent-invoked entry points
with durable checkpoints, duplicate protection and successor acknowledgement
before predecessor retirement. A provider/runtime lacking a supported API must
report that limitation; do not claim compaction or handoff happened merely
because a request was submitted. Ordinary self-requested handoff is authorized;
this does not silently decide the separate unattended crash-restart policy.

**YOLO is the default for all ordinary agent launches**, including children,
reviewers of trusted internal work and fresh handoff successors. Restricted
execution is reserved for external-security-critical work, including the
prompt-injection boundary. Extend verification beyond creation-time mappings to
current supported providers and resume/mode drift. Do not use defaultMode or an
unavailable provider as an excuse for silent Always Ask stalls. Preserve explicit
operator-requested restrictive modes; do not invent mode IDs or claim runtime
permissions that the host does not actually provide. Prior statements retaining
restricted review as a blanket rule must be interpreted under this narrower
external-security-critical exception.

These are implementation requirements, superseding the earlier design-only
scope for self-handoff. No runtime plugin or mode was changed by this record.
