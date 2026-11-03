"""Pure, deterministic selection and shared migration-mutation guard.

Inventory metadata is evidence for a *draft*, never proof of a fence or consent.
No imports here can launch a process, read HOME, invoke a model or send a message.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = 1
POLICY = "fleet-migrate-v1-fable-astra"
LIVE = frozenset({"idle", "running", "working", "error", "blocked", "unknown", "initializing"})
MUTATIONS = frozenset({"create", "fence", "scheduler", "ownership", "archive", "placement"})
ROUTES = frozenset({"opencode-go", "cline", "deepseek"})
# Recommendations for Opus/Sonnet are deliberately not automatic policy entries.
EXACT_MODELS = {("anthropic", "anthropic/claude-fable-5-1", "pi", "openai"):
                ("openai/gpt-6-astra", "high")}
AGENT_FIELDS = ("id", "host", "native_id", "tui", "vendor", "model", "billing_route",
                "title", "status", "workspace_id", "membership", "channel")
RUNTIME_BLOCKERS = [
    "authoritative-live-inventory-adapter-not-admitted",
    "predecessor-fence-with-child-survival-not-proven",
    "per-task-continuation-control-not-proven",
    "safe-top-level-activation-and-desktop-tab-proof-not-proven",
    "universal-return-route-and-authenticated-application-ack-not-proven",
    "paid-pi-dispatch-canary-not-verified",
]


def normalized(value):
    return value.casefold().strip() if isinstance(value, str) else ""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def plan_digest(plan):
    return hashlib.sha256(canonical({k: v for k, v in plan.items() if k != "digest"})).hexdigest()


def _key(row):
    return (row.get("host"), row.get("id"))


def protected_workspaces(inventory, retained=()):
    keys = {_key(w) for w in retained}
    keys.update(_key(w) for w in inventory.get("workspaces", []) if w.get("name") == "Dann Home")
    return [{"host": h, "id": i} for h, i in sorted(keys)]


def guard(agent, inventory, retained, category):
    """Return blockers; notification permission is separate from all migration actions.

    Callers must hold the coordinator lock and provide a freshly validated inventory
    before EVERY mutation. This predicate is not a source fence or a live adapter.
    """
    if category == "notify":
        return []
    if category not in MUTATIONS:
        return ["unknown-action-category"]
    reasons = []
    protected = {_key(w) for w in protected_workspaces(inventory, retained)}
    if (agent.get("host"), agent.get("workspace_id")) in protected:
        reasons.append("protected-workspace")
    title_signal = "dann" in normalized(agent.get("title"))
    model_signal = "deepseek" in normalized(agent.get("model"))
    # Resolve an explicit billing route, not the TUI label, title or vendor alone.
    route = normalized(agent.get("billing_route"))
    if title_signal and model_signal and route in ROUTES:
        reasons.append("protected-signals")
    elif title_signal or (model_signal and route in ROUTES):
        reasons.append("inconsistent-protection-signals-review")
    hosts = inventory.get("hosts", [])
    if not hosts or any(h.get("complete") is not True or h.get("reachable") is not True for h in hosts):
        reasons.append("incomplete-host-inventory")
    if agent.get("host") not in {h.get("id") for h in hosts}:
        reasons.append("unknown-host")
    members = {_key(w) for w in inventory.get("workspaces", [])}
    if (agent.get("membership") != "authoritative" or
            (agent.get("host"), agent.get("workspace_id")) not in members):
        reasons.append("unknown-workspace-membership")
    if not agent.get("native_id"):
        reasons.append("unknown-native-identity")
    return reasons


def sanitize_inventory(raw):
    """Whitelist metadata; never retain arbitrary transcript/env/checkpoint bodies."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw.get("schema_version") != SCHEMA:
        raise ValueError("unsupported-inventory-schema")
    fields = {"hosts": ("id", "complete", "reachable"),
              "workspaces": ("host", "id", "name"),
              "agents": AGENT_FIELDS,
              "catalog": ("tui", "vendor", "model", "thinking", "billing_pool", "context")}
    out = {"schema_version": SCHEMA}
    for collection, names in fields.items():
        rows = raw.get(collection)
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("invalid-inventory-" + collection)
        out[collection] = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid-record-" + collection)
            clean = {k: row.get(k) for k in names}
            for k, v in clean.items():
                if k in ("complete", "reachable"):
                    if type(v) is not bool:
                        raise ValueError("invalid-boolean-" + k)
                elif k == "context":
                    if type(v) is not int or v <= 0:
                        raise ValueError("invalid-context")
                elif k == "thinking":
                    if not isinstance(v, list) or not all(isinstance(x, str) and len(x) < 32 for x in v):
                        raise ValueError("invalid-thinking")
                elif v is not None and (not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 for c in v)):
                    raise ValueError("invalid-metadata-" + k)
            identity = (_key(clean) if collection in ("workspaces", "agents") else
                        clean.get("id") if collection == "hosts" else
                        (clean.get("tui"), clean.get("vendor"), clean.get("model")))
            if identity in seen:
                raise ValueError("duplicate-inventory-" + collection)
            seen.add(identity)
            out[collection].append(clean)
        out[collection].sort(key=lambda r: canonical(r))
    return out


def _groups(agents):
    grouped = {}
    for a in agents:
        # Bridge views may collapse only on an explicit full native identity.
        key = (a.get("host"), "native", a["native_id"]) if a.get("native_id") else (a.get("host"), "view", a.get("id"))
        grouped.setdefault(key, []).append(a)
    return list(grouped.values())


def _destination(source, catalog, to_tui, to_vendor):
    mapped = EXACT_MODELS.get((normalized(source.get("vendor")), normalized(source.get("model")), to_tui, to_vendor))
    if not mapped:
        return None, "no-approved-exact-model-mapping"
    model, thinking = mapped
    matches = [m for m in catalog if normalized(m.get("tui")) == to_tui and
               normalized(m.get("vendor")) == to_vendor and m.get("model") == model]
    if len(matches) != 1 or thinking not in matches[0].get("thinking", []) or not matches[0].get("billing_pool"):
        return None, "destination-capability-or-pool-unknown"
    return {**matches[0], "thinking": thinking}, None


def build_plan(raw, *, from_tui, from_vendor=None, to_tui, to_vendor, include_herdr=False):
    inv = sanitize_inventory(raw)
    options = {"from_tui": normalized(from_tui), "from_vendor": normalized(from_vendor) or None,
               "to_tui": normalized(to_tui), "to_vendor": normalized(to_vendor), "include_herdr": include_herdr}
    if not options["from_tui"] or not options["to_tui"] or not options["to_vendor"] or type(include_herdr) is not bool:
        raise ValueError("invalid-plan-options")
    p = {"schema_version": SCHEMA, "policy_version": POLICY, "options": options,
         "inventory": inv, "protected_workspaces": protected_workspaces(inv),
         "selected": [], "excluded": [], "unresolved": [], "recipients": [],
         "runtime_blockers": list(RUNTIME_BLOCKERS), "execution_authorized": False}
    for views in _groups(inv["agents"]):
        live_views = [a for a in views if normalized(a.get("status")) in LIVE]
        recipients = [a for a in live_views if a.get("channel") and not str(a.get("id", "")).startswith("pid")]
        if recipients:
            p["recipients"].append(recipients[0])
        candidates = [a for a in live_views if
                      (normalized(a.get("tui")) == options["from_tui"] or
                       (include_herdr and normalized(a.get("tui")) == "herdr-" + options["from_tui"])) and
                      (not options["from_vendor"] or normalized(a.get("vendor")) == options["from_vendor"])]
        if not candidates:
            continue
        a = candidates[0]
        reasons = sorted({b for v in views for b in guard(v, inv, p["protected_workspaces"], "create")})
        row = {"source": a, "views": views, "reasons": reasons}
        if reasons:
            p["excluded" if any(b in ("protected-workspace", "protected-signals") for b in reasons) else "unresolved"].append(row)
            continue
        destination, blocker = _destination(a, inv["catalog"], options["to_tui"], options["to_vendor"])
        if blocker:
            row["reasons"] = [blocker]
            p["unresolved"].append(row)
        else:
            row["destination"] = destination
            p["selected"].append(row)
    p["digest"] = plan_digest(p)
    return p


def validate_plan(p):
    """Digest is integrity, not authentication. Recompute selection as a second gate."""
    if not isinstance(p, dict) or p.get("schema_version") != SCHEMA:
        return ["unsupported-plan-schema"]
    errors = []
    try:
        if p.get("digest") != plan_digest(p):
            errors.append("digest-mismatch")
        expected = build_plan(p.get("inventory"), **p.get("options", {}))
        if p != expected:
            errors.append("plan-policy-or-content-mismatch")
    except (ValueError, TypeError, KeyError, RecursionError):
        errors.append("invalid-plan-content")
    return errors
