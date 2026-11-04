# Dispatch completion notices

Added 2026-11-04 after a Paseo watcher's completed research sat unread: a background waiter inherited the lead's identity and `relay.py` correctly refused its completion message as “that is this session”.

`bin/acp-dispatch-notify RECORD --target PASEO_AGENT_ID` runs the existing `acp-dispatch-wait` and relays its outcome once. Use it as the background waiter when the harness has no tracked background Bash tool. Detach it using the harness's existing process/job mechanism; retain stdout/stderr. This command does not detach itself, install a job, cancel a slice, or rerun work.

The notification uses relay's existing external-notice context, which suppresses inherited session IDs **and ancestor identity**. Ordinary agent self-messages remain refused. A busy recipient uses relay's existing notice queue, not a force-steer or replacement turn. The message names the waiter outcome and record, not a claimed successful report: exit 76 still means re-arm the waiter, not restart the slice.

The relay receipt is parsed as JSON without `run_captured`'s 400-character clipping. Only `result: delivered` counts as delivery. Accepted, queued, malformed, missing and failed receipts trigger one Hermes fallback and exit 1; no uncertain message is resent. Receipt text stays on stdout for reconciliation.

Exit 0 means a successful waiter and proven delivery; after proven delivery another nonnegative waiter status is preserved. Exit 1 means delivery is unproven (fallback attempted), or a signaled waiter. Exit 2 means invalid arguments or unreadable record. The record must contain an absolute `report` path. No report content or record-supplied command is executed.

Focused regressions: `tests/test_acp_dispatch_notify.py` tests identity scrubbing, receipt preservation, accepted/queued/refused outcomes, no retry, and the exit-76 distinction.
