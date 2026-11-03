"""Pure resource/operation assessment of trusted adapter evidence.

These functions neither read reports nor adopt handles, signal processes, rearm
waiters or retry work. A proposed action still needs a supported live adapter,
mutation guard, approved digest and durable receipt. Arbitrary checkpoint text
is never evidence for any field below.
"""
from __future__ import annotations

import re

PROCESS_KINDS = frozenset({"acp-dispatch", "raw-acp-run", "shell", "service", "managed-terminal", "tmux", "native-subagent"})
HASH = re.compile(r"[a-f0-9]{64}\Z")
OP_STATES = frozenset({"NOT_STARTED", "IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN"})


def _present(value):
    return isinstance(value, str) and bool(value.strip())


def assess_resource(r):
    """Classify an already inventoried resource; PID alone never proves identity."""
    out = {"classification": "BLOCKED_OPAQUE", "outcome": "UNKNOWN", "archive_blocked": True,
           "can_read_report": False, "native_handle_adopted": False, "proposed_actions": []}
    kind = r.get("kind")
    identity = (_present(r.get("host")) and _present(r.get("owner_task")) and
                r.get("identity_verified") is True)
    if kind in PROCESS_KINDS:
        identity = (identity and type(r.get("pid")) is int and r["pid"] > 0 and
                    _present(r.get("boot_id")) and _present(r.get("start_id")) and
                    isinstance(r.get("command_sha256"), str) and bool(HASH.fullmatch(r["command_sha256"])))
        if kind == "acp-dispatch":
            identity = identity and _present(r.get("record_id"))
    elif kind in ("ci", "remote-job"):
        identity = identity and _present(r.get("job_id"))
    else:
        identity = False
    if not identity:
        out["reason"] = "resource-identity-unproven"
        return out
    if r.get("state") in ("done", "completed", "failed"):
        # Finalization evidence is provided by the adapter after examining the
        # exact .done/final record. Existence of an output path is not enough.
        if r.get("finalized") is not True or not _present(r.get("completion_receipt")):
            out["reason"] = "completion-not-finalized"
            return out
        out.update(classification="COMPLETED_ARTIFACT_READY", archive_blocked=False,
                   outcome="FAILED" if r.get("state") == "failed" else "SUCCEEDED",
                   can_read_report=_present(r.get("report_ref")))
        return out
    if r.get("state") != "running":
        out["reason"] = "resource-outcome-unknown"
        return out
    if kind == "native-subagent":
        out["classification"] = "REATTACH_SUPPORTED" if _present(r.get("reattach_api")) else "WAIT_FOR_COMPLETION"
        out["reason"] = "native-lifecycle-requires-supported-readback"
        return out
    out.update(classification="KEEP_AND_OBSERVE", outcome="IN_FLIGHT")
    # Survival through archive is independent of process liveness. Unknown
    # archive survival continues to block retirement, not observation.
    out["archive_blocked"] = r.get("archive_survival_verified") is not True
    if kind == "acp-dispatch" and r.get("waiter_alive") is False and r.get("waiter_rearm_supported") is True:
        out["proposed_actions"] = ["rearm-existing-waiter"]
    return out


def assess_operation(op):
    """History conversion is never authoritative for external side effects."""
    state = op.get("state") if op.get("state") in OP_STATES else "UNKNOWN"
    trusted_receipt = (_present(op.get("receipt")) and
                       op.get("receipt_source") == "artifact-reconciliation")
    if not _present(op.get("id")) or (state in ("SUCCEEDED", "FAILED", "NOT_STARTED") and not trusted_receipt):
        state = "UNKNOWN"
    return {"state": state, "blocks_activation": state not in ("SUCCEEDED", "NOT_STARTED"),
            "retry_authorized": False,
            "disposition": "RETRY_AFTER_RECONCILIATION" if state in ("UNKNOWN", "FAILED") else "PRESERVE"}


def checkpoint_blockers(checkpoint):
    """Check working-set/access obligations, not semantic completeness of history.

    The transfer_authorized field must originate from an approved coordinator
    policy/digest, never from a transcript or checkpoint's own instruction text.
    No raw body, private thinking signature or credential is copied here.
    """
    c = checkpoint
    blockers = []
    if c.get("artifacts_verified") is not True:
        blockers.append("checkpoint-artifacts-not-verified")
    if c.get("transfer_authorized") is not True:
        blockers.append("cross-vendor-transfer-not-authorized")
    if not _present(c.get("history_index")):
        blockers.append("missing-retrievable-history-index")
    if c.get("target_host") and c.get("artifacts_accessible_from_target") is not True:
        blockers.append("checkpoint-not-accessible-from-target")
    working, budget = c.get("working_set_tokens"), c.get("input_budget")
    if type(working) is not int or type(budget) is not int or working < 0 or budget <= 0:
        blockers.append("unknown-working-set-or-input-budget")
    elif working > budget:
        blockers.append("working-set-exceeds-input-budget")
    return blockers
