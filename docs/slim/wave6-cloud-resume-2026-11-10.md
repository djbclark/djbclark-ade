# Wave 6 resumed in a fresh cloud environment — 2026-11-10

## A. Verified starting point

- ADE base: `7589e329e4a43f5569e9e14c349cec812d99e24d`.
  GitHub reports #534 and #535 merged. The initial cloud checkout was older;
  work uses a separate linked worktree, branch `wave6-cloud-resume-20261110`,
  claimed by `codex-wave6-root` for 72 hours.
- `python3 bin/wave6-delete-check --inventory --dry-run --json` exits 0:
  `callers_remaining=0`, `coverage_ok=true`, `fixture_shape_ok=true`,
  `gate_exits.evaluate_no_evidence=1`, `ready=false`, `mac_live_blocked=true`.
  This is inventory/fixture validation, not a live-evidence check.
- The earlier archive at `~/tmp/wave6-mac-from-bigmac-20261110/` is absent
  on this fresh host. Its earlier verification remains recorded in
  [the handoff](wave6-cloud-handoff-2026-11-10.md); no new archive verification
  or Darwin recapture was performed here.
- Neither `paseo` nor `aiuse` is on PATH. `route_agent.py show` reports an
  absent quota snapshot. Account quota and native Mac session state are unknown.
  No live pool acceptance, session labels, or outside configuration changed.
- `graft` and the local `graft/` graph are absent; preparation used targeted
  documentation/source inspection. One fresh-context GPT-6.1 Sol medium
  subagent prepared A3/A4; no extra frontier orchestrator was started.

## B. Read-only follow-up findings

### B1. A3/A4 — native routing must preserve capacity checks

The existing native routing procedure (`skills/model-routing/SKILL.md` D5)
does not subtract sibling in-flight reservations. Replacing the legacy
launcher name alone would therefore weaken the outside projects' stated
quota invariant. The migration must retain allowance, fresh headroom,
per-project estimate floors, and conservative accounting for other live work;
unknown capacity must hold the launch.

### B2. A5 — active instructions confirmed, no blanket historical waive

Read-only GitHub inspection of `djbclark/cfengine-all` at
`9bcc7f51eb384b23d381a3b6de9d58cff0f259d6` found active instructions in
`AGENTS.md` (blob `a0a6ad9dcf66dca934ce7da7a6da98236135c684`):

- Line 63 describes the current `fleet-watch upstream` draft-writing path.
- Lines 166–175 direct resumed sessions to a fleet relay and `/cfenginewatch`.
- Search also found dated references in
  `docs/handoffs/HANDOFF_standalone-3fd9_upstream-watch-relay_2026-10-24_6a9f.md`.

These are distinct active and historical categories. Search was not an
exhaustive local C3 probe. No migration or waive was applied; preserve the
dated handoff and existing upstream-contact approval rules.

### B3. A6 — passive history remains distinct from live teaching

Read-only inspection of `djbclark/aiuse` `AGENTS.md` (blob
`b5d50dd291be5bd406c578c71ce4e1db6f484738`) confirms both passive ACP
context-log accounting and historical delegation-enforcement teaching.
This is preliminary classification, not an exhaustive source audit. Retain
logs and accounting; any historical-reader waive needs its own explicit grant.

## C. Boundaries and next action

The next decision remains A3+A4 order-11 authorization, on a concrete
instruction-file migration proposal. No outside edits are authorized by this
record. C1+C2 are already granted; do not ask again. A5–A7 and X1 follow one
card at a time. X2 requires Mac access and proof the old lead has ended.

Keep `relay.py`, `acp-dispatch`, `acp-run`, and `review-launch`. Do not use
`--allow-early`; the deadline remains 2026-11-20. No deletion PR before the
real evidence gate exits 0 and the operator confirms. Keep Pi
Grok/Antigravity/SIPB/Go `accepted=false`.
