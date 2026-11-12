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

## 4. Remaining walkthrough

Next after the detailed dispatch comparison: quota/routing;
web/moved skills/nightly learning; review/permissions;
remaining deletion gates and repairs. These items remain undecided except where
prior operator instructions already apply. Ask one question at a time; act on
small choices immediately and execute larger queued work after the walkthrough.
