"""Provider → unattended (YOLO / Bypass) Paseo mode ids.

Home rule restored 2026-11-10: ordinary launches and MCP-created children run
unattended. Wave 4 E6 had mapped ``--perm all`` to each provider's
``defaultMode`` (Claude's advertised default is ``auto``; a create with no
usable unattended mode falls through to Always Ask / ``default``). That was
plan drift — YOLO was the standing policy (paseo-new-seat / paseo-bypass-watch
before the slim-down deleted them).

Explicit restrictive requests and external-security-critical work stay restricted.
External untrusted input (GitHub artifacts) is data per AGENTS.md Trust, not an
Always Ask prompt gate.
"""
from __future__ import annotations

# Source-backed native mode IDs. Unknown/dynamic providers require exact
# catalog/control evidence; no mode ID is inferred from a display label.
YOLO_MODE_BY_PROVIDER: dict[str, str] = {
    "claude": "bypassPermissions",
    "codex": "full-access",
    "antigravity": "full-access",
    "copilot": "allow-all",
    # Other providers require the catalog/control API below.
}

# Modes that prompt (or classify into prompts). Force YOLO when these are set
# or when modeId is missing.
PROMPTING_MODE_IDS = frozenset({
    "default",       # Always Ask
    "auto",
    "acceptEdits",
    "auto-review",   # Codex: still routes some approvals
})

# Explicit operator restrictive modes: never override.
RESTRICTIVE_MODE_IDS = frozenset({
    "plan",
    "read-only",
    "dontAsk",
})

# Legacy ID vocabulary only; membership here never proves a provider mode.
UNATTENDED_MODE_IDS = frozenset({
    "bypassPermissions",
    "bypass",
    "full-access",
    "full",
    "build",
    "danger-full-access",
    "yolo",
})


def provider_id(provider: str | None) -> str:
    """``claude`` from ``claude`` or ``claude/sonnet``."""
    raw = (provider or "").strip()
    if not raw:
        return ""
    return raw.split("/", 1)[0]


def yolo_mode(provider: str | None) -> str | None:
    """Unattended mode id for *provider*, or None when unknown / dynamic."""
    return YOLO_MODE_BY_PROVIDER.get(provider_id(provider))


def resolve_launch_mode(
    provider: str | None,
    requested: str | None = None,
    *,
    fallback: str | None = None,
) -> str:
    """Mode for an ordinary ``paseo run`` / ``--perm all`` launch.

    Preserve explicit restrictive requests; otherwise use a source-backed mode.
    ``fallback`` is retained for caller compatibility, but never grants unattended
    authority. Dynamic providers require ``plan_unattended_config``.
    """
    req = (requested or "").strip() or None
    if req and req in RESTRICTIVE_MODE_IDS:
        return req
    yolo = yolo_mode(provider)
    if yolo:
        return yolo
    raise ModeUnavailable(f"no verified unattended mode for {provider_id(provider)!r}; "
                          "inspect the native catalog/control API instead of using defaultMode")


class ModeUnavailable(ValueError):
    """The host did not provide enough evidence to run ordinary work unattended."""


def plan_unattended_config(
    provider: str, catalog: dict, *, controls: dict | None = None,
    requested: str | None = None, scope: str = "ordinary",
) -> dict:
    """Plan from one exact native provider entry; never infer mode IDs from labels.

    Native protocol snapshots currently omit isUnattended. The known mode IDs
    below are source-backed at getpaseo/paseo 4df5307e; catalog membership remains
    mandatory. ACP auto_accept requires the actual advertised toggle control.
    """
    pid = provider_id(provider)
    result = {"status": "unavailable", "provider": pid, "mode_id": None,
              "provider_options": {}, "evidence": "none", "reason": "invalid native catalog"}
    if scope not in {"ordinary", "external-security-critical", "operator-restrictive"}:
        result["reason"] = "unknown work scope"
        return result
    if scope != "ordinary" or requested in RESTRICTIVE_MODE_IDS:
        result.update(status="exempt", mode_id=requested, evidence="explicit-restriction",
                      reason="preserve explicit restrictive/external-security-critical scope")
        return result
    if pid in {"omp", "opencode", "crush", "agy", "grok"}:
        result["reason"] = "retired client is not an ordinary dispatch route"
        return result
    if not isinstance(catalog, dict) or catalog.get("provider") != pid:
        return result
    if not (catalog.get("enabled") is True or catalog.get("enabled") == "Enabled") or catalog.get("status") not in ("ready", "available") or catalog.get("error"):
        result["reason"] = "provider is not positively enabled and available"
        return result
    modes = catalog.get("modes")
    if not isinstance(modes, list) or any(not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"] for m in modes):
        result["reason"] = "native mode IDs unavailable (provider ls labels are insufficient)"
        return result
    ids = [m["id"] for m in modes]
    if len(ids) != len(set(ids)):
        result["reason"] = "duplicate native mode IDs"
        return result
    source_modes = {"claude": "bypassPermissions", "codex": "full-access", "antigravity": "full-access", "copilot": "allow-all"}
    marked = [m["id"] for m in modes if m.get("isUnattended") is True]
    selected = source_modes.get(pid)
    if selected in ids:
        result.update(status="ready", mode_id=selected, evidence="source-and-catalog",
                      mechanism="mode", reason="source-backed unattended mode present in exact catalog")
        return result
    if len(marked) == 1:
        result.update(status="ready", mode_id=marked[0], evidence="catalog-marked",
                      mechanism="mode", reason="native catalog marks one unattended mode")
        return result
    control_rows = controls.get("controls") if isinstance(controls, dict) and not controls.get("error") else None
    if pid == "cursor" and isinstance(control_rows, list) and any(
        isinstance(c, dict) and c.get("type") == "toggle" and c.get("key") == "auto_accept"
        for c in control_rows
    ):
        # Cursor is ACP; this is the daemon-owned tool-approval control, not a
        # guessed provider mode. Preserve a selectable mode or omit it entirely.
        selected = requested or catalog.get("defaultModeId")
        if selected is not None and selected not in ids:
            result["reason"] = "requested/default Cursor mode absent from native catalog"
            return result
        result.update(status="ready", mode_id=selected, provider_options={"auto_accept": True},
                      mechanism="control", evidence="source-and-advertised-control",
                      reason="ACP auto_accept toggle advertised by exact Cursor catalog")
        return result
    if pid == "pi" and not ids:
        result["reason"] = ("Pi exposes no selectable modes; extension UI requests can still block; "
                            "no permission-control verification is available")
        result["evidence"] = "source-modeless"
        return result
    result["reason"] = "no source-backed/catalog-marked unattended mode or supported control"
    return result


def verify_unattended_snapshot(plan: dict, snapshot: dict, *, agent_id: str | None = None) -> dict:
    """Verify effective native state, not the set-mode/create acknowledgement.

    Uppercase CLI inspect lacks options/features on some hosts: control-backed
    verification must then report unavailable, not assume auto_accept is set.
    """
    def fail(reason):
        return {"ok": False, "reason": reason}
    if not isinstance(plan, dict) or plan.get("status") not in {"ready", "exempt"} or not isinstance(snapshot, dict):
        return fail("no ready plan/native snapshot")
    if plan.get("status") == "exempt":
        if plan.get("mode_id") not in RESTRICTIVE_MODE_IDS or plan.get("evidence") != "explicit-restriction":
            return fail("exemption has no explicit restrictive mode")
    elif plan.get("mechanism") not in {"mode", "control"} or (plan.get("mechanism") == "mode" and not plan.get("mode_id")):
        return fail("invalid planned verification mechanism")
    sid = snapshot.get("id", snapshot.get("Id"))
    if not isinstance(sid, str) or (agent_id is not None and sid != agent_id):
        return fail("agent identity mismatch")
    if snapshot.get("provider", snapshot.get("Provider")) != plan.get("provider"):
        return fail("provider identity mismatch")
    archived = snapshot.get("archivedAt") is not None if "archivedAt" in snapshot else snapshot.get("Archived") is not False
    if archived or snapshot.get("status", snapshot.get("Status")) not in ("idle", "running"):
        return fail("agent is not a verified live unarchived runtime")
    modes = snapshot.get("availableModes", snapshot.get("AvailableModes"))
    if plan.get("mode_id") is not None and (not isinstance(modes, list) or not any(
        isinstance(m, dict) and m.get("id") == plan["mode_id"] for m in modes
    )):
        return fail("planned mode missing from runtime catalog")
    current = snapshot.get("currentModeId", snapshot.get("Mode"))
    if plan.get("mode_id") is not None and current != plan["mode_id"]:
        return fail("effective mode drift/missing mode readback")
    if plan.get("mechanism") == "control":
        options = snapshot.get("options")
        if not isinstance(options, dict) or options.get("auto_accept") is not True:
            return fail("effective auto_accept option missing/false")
    return {"ok": True, "reason": "effective native mode/control readback matches plan"}
