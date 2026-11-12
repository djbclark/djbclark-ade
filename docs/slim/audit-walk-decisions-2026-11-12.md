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

## 2. Remaining walkthrough

Next: Pi/client retirement and backup coverage. Then dispatch/handoff/unattended
operation; quota/routing; web/moved skills/nightly learning; review/permissions;
remaining deletion gates and repairs. These items remain undecided except where
prior operator instructions already apply. Ask one question at a time; act on
small choices immediately and execute larger queued work after the walkthrough.
