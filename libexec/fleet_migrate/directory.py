"""Offline identity-directory and receipt protocol, not live routing authority.

Only a future trusted, fenced coordinator may persist/publish commit_ready's
result as live authority. No caller may derive readiness/fence/commit receipts
from transcript bodies. No live relay integration is activated by this module.
"""
from __future__ import annotations

import copy
import hashlib

from .planning import canonical

IDENTITY_FIELDS = ("host", "id", "native_id", "incarnation")


def identity_key(identity):
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS):
        raise ValueError("invalid-full-identity")
    if any(not isinstance(identity.get(k), str) or not identity[k] or len(identity[k]) > 512 for k in IDENTITY_FIELDS):
        raise ValueError("invalid-full-identity")
    return hashlib.sha256(canonical(identity)).hexdigest()


def empty_directory():
    return {"schema_version": 1, "epoch": 0, "tasks": {}, "lineage": []}


def directory_digest(directory):
    _validate(directory)
    return hashlib.sha256(canonical(directory)).hexdigest()


def _validate(d):
    if (not isinstance(d, dict) or d.get("schema_version") != 1 or type(d.get("epoch")) is not int or
            d["epoch"] < 0 or not isinstance(d.get("tasks"), dict) or not isinstance(d.get("lineage"), list)):
        raise ValueError("invalid-directory-schema")
    old_ids = set()
    last_epoch = 0
    for edge in d["lineage"]:
        if not isinstance(edge, dict):
            raise ValueError("invalid-lineage-edge")
        old, new = identity_key(edge.get("old")), identity_key(edge.get("new"))
        if (old == new or old in old_ids or type(edge.get("epoch")) is not int or
                edge["epoch"] <= last_epoch or edge["epoch"] > d["epoch"]):
            raise ValueError("ambiguous-or-stale-lineage")
        old_ids.add(old)
        last_epoch = edge["epoch"]
    for task in d["tasks"].values():
        if (not isinstance(task, dict) or type(task.get("generation")) is not int or task["generation"] < 1 or
                task.get("status") != "ready"):
            raise ValueError("invalid-directory-task")
        identity_key(task.get("current"))


def resolve(directory, identity, *, purpose="message"):
    _validate(directory)
    identity_key(identity)
    if purpose == "history":
        return copy.deepcopy(identity)
    if purpose != "message":
        raise ValueError("unknown-resolution-purpose")
    aliases = {identity_key(e["old"]): e["new"] for e in directory["lineage"]}
    seen = set()
    current = identity
    while identity_key(current) in aliases:
        key = identity_key(current)
        if key in seen:
            raise ValueError("cyclic-lineage")
        seen.add(key)
        current = aliases[key]
    return copy.deepcopy(current)


def commit_ready(directory, *, task, source, destination, expected_generation, commit_receipt):
    """Construct next immutable epoch; does NOT fence/activate, persist or publish.

    Readiness receipts are opaque references from a trusted adapter contract, not
    assertions parsed from the replacement's answer. The future state coordinator
    must verify them against artifacts under its lock before calling this helper.
    """
    _validate(directory)
    identity_key(source)
    if not isinstance(task, str) or not task or not commit_receipt:
        raise ValueError("missing-coordinator-commit")
    dest = destination.get("identity")
    identity_key(dest)
    required = ("workspace_id", "tui", "vendor", "model", "thinking", "billing_pool", "ready_receipt", "fence_receipt")
    if any(not isinstance(destination.get(k), str) or not destination[k] for k in required):
        raise ValueError("successor-readiness-unproven")
    existing = directory["tasks"].get(task)
    if any(name != task and value.get("current") == source for name, value in directory["tasks"].items()):
        raise ValueError("source-belongs-to-another-task")
    generation = existing.get("generation", 0) if existing else 0
    if type(expected_generation) is not int or expected_generation != generation:
        raise ValueError("stale-owner-generation")
    if existing and source != existing.get("current"):
        raise ValueError("predecessor-is-not-current-owner")
    used = [e[side] for e in directory["lineage"] for side in ("old", "new")]
    used += [t["current"] for t in directory["tasks"].values()]
    if dest == source or any(identity_key(x) == identity_key(dest) for x in used):
        raise ValueError("successor-identity-already-used")
    if any(e["old"] == source for e in directory["lineage"]):
        raise ValueError("predecessor-already-retired")
    d = copy.deepcopy(directory)
    d["epoch"] += 1
    d["lineage"].append({"old": copy.deepcopy(source), "new": copy.deepcopy(dest), "epoch": d["epoch"],
                          "task": task, "commit_receipt": commit_receipt})
    d["tasks"][task] = {"generation": generation + 1, "current": copy.deepcopy(dest), "status": "ready",
                         "route": {k: destination[k] for k in required}, "commit_epoch": d["epoch"]}
    _validate(d)
    return d


def notification(directory, recipient):
    digest = directory_digest(directory)
    key = identity_key(recipient)
    update_id = hashlib.sha256(canonical([directory["epoch"], digest, key])).hexdigest()
    return {"kind": "identity-update", "update_id": update_id, "epoch": directory["epoch"],
            "directory_digest": digest, "recipient": copy.deepcopy(recipient),
            "directory_ref": f"directory-{directory['epoch']}-{digest}.json",
            "mappings": copy.deepcopy(directory["lineage"]),
            "current_tasks": copy.deepcopy(directory["tasks"]),
            "ack_request": "directory-applied:" + update_id}


def update_recipients(ledger, directory, peers):
    """Union prepare/commit/reconcile rosters; current committed aliases win.

    Ledger is separate from the immutable directory digest. No previous offline
    or unreachable recipient is silently removed. No send is performed here.
    """
    result = copy.deepcopy(ledger)
    known = [row["identity"] for row in ledger.values() if not row.get("superseded")]
    incoming = [resolve(directory, p) for p in peers]
    by_endpoint = {}
    for p in incoming:
        endpoint = (p["host"], p["id"])
        if endpoint in by_endpoint and by_endpoint[endpoint] != p:
            raise ValueError("ambiguous-recipient-incarnation")
        by_endpoint[endpoint] = p
    known += incoming
    for peer in known:
        current = resolve(directory, peer)
        # Preserve old receipts for audit but never let them cover a successor
        # or a newly observed incarnation of the same concrete endpoint.
        old_key = identity_key(peer)
        observed = by_endpoint.get((peer["host"], peer["id"]))
        replaced = observed is not None and observed != peer
        if (current != peer or replaced) and old_key in result:
            result[old_key]["superseded"] = True
        if replaced and current == peer:
            continue
        msg = notification(directory, current)
        key = identity_key(current)
        old = result.get(key)
        if old and old.get("update_id") == msg["update_id"] and not old.get("superseded"):
            continue
        history = list(old.get("previous_receipts", [])) if old else []
        if old:
            history.append({k: old.get(k) for k in ("epoch", "digest", "update_id", "transport", "applied")})
        result[key] = {"identity": current, "epoch": msg["epoch"], "digest": msg["directory_digest"],
                       "update_id": msg["update_id"], "transport": "pending", "applied": False,
                       "previous_receipts": history}
    return result


def receipt(ledger, directory, recipient, *, update_id, epoch, digest, kind, authenticated_caller):
    """Accept only exact-epoch receipts. Authenticated caller comes from adapter.

    Rendered text/title/transcript matching is not an authenticated caller. The
    adapter must supply relay's verified recipient incarnation on application
    acknowledgments. Transport receipt kinds are supplied by the transport, not
    arbitrary peer messages. This function sends nothing (acks never ask acks).
    """
    if kind not in ("queued", "accepted", "delivered", "unreachable", "blocked", "uncertain", "applied"):
        raise ValueError("unsupported-receipt-kind")
    expected = notification(directory, recipient)
    key = identity_key(recipient)
    if (epoch != expected["epoch"] or digest != expected["directory_digest"] or update_id != expected["update_id"] or
            key not in ledger or ledger[key].get("update_id") != update_id or ledger[key].get("superseded")):
        raise ValueError("stale-or-unbound-receipt")
    if kind == "applied" and authenticated_caller != recipient:
        raise ValueError("unauthenticated-application-ack")
    result = copy.deepcopy(ledger)
    row = result[key]
    if kind == "applied":
        row["applied"] = True
    elif row.get("transport") != "delivered":
        row["transport"] = kind
    return result


def convergence(ledger):
    rows = [r for r in ledger.values() if not r.get("superseded")]
    return {"total": len(rows), "historical_recipients": len(ledger) - len(rows), "delivered": sum(r.get("transport") == "delivered" for r in rows),
            "applied": sum(r.get("applied") is True for r in rows),
            "pending": sum(r.get("applied") is not True for r in rows),
            "unreachable": sum(r.get("transport") == "unreachable" for r in rows),
            "blocked": sum(r.get("transport") == "blocked" for r in rows),
            "converged": bool(rows) and all(r.get("applied") is True for r in rows)}
