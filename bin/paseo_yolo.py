"""Provider → unattended (YOLO / Bypass) Paseo mode ids.

Home rule restored 2026-11-10: ordinary launches and MCP-created children run
unattended. Wave 4 E6 had mapped ``--perm all`` to each provider's
``defaultMode`` (Claude's advertised default is ``auto``; a create with no
usable unattended mode falls through to Always Ask / ``default``). That was
plan drift — YOLO was the standing policy (paseo-new-seat / paseo-bypass-watch
before the slim-down deleted them).

Restrictive modes (plan, read-only, …) and ``bin/review-launch`` stay restricted.
External untrusted input (GitHub artifacts) is data per AGENTS.md Trust, not an
Always Ask prompt gate.
"""
from __future__ import annotations

# Provider id → modeId that Paseo's manifest marks isUnattended (or the closest
# known no-prompt mode). ACP providers with dynamic mode catalogs (cursor, …)
# are omitted: leave their create alone rather than invent a mode id.
YOLO_MODE_BY_PROVIDER: dict[str, str] = {
    "claude": "bypassPermissions",
    "codex": "full-access",
    "opencode": "build",
    "omp": "full",
    # cursor / pi / antigravity / hermes / muse: dynamic or unverified catalogs —
    # do not invent a modeId; callers fall back to provider defaultMode.
}

# Modes that prompt (or classify into prompts). Force YOLO when these are set
# or when modeId is missing.
PROMPTING_MODE_IDS = frozenset({
    "default",       # Always Ask
    "auto",
    "acceptEdits",
    "auto-review",   # Codex: still routes some approvals
})

# Explicit restrictive / review modes: never override.
RESTRICTIVE_MODE_IDS = frozenset({
    "plan",
    "read-only",
    "dontAsk",
})

# Already unattended — leave alone (plugin may still set OpenCode auto_accept).
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

    An explicit restrictive or already-unattended *requested* mode wins.
    Otherwise use the provider's YOLO id. Unknown providers keep *fallback*
    (typically ``paseo provider ls`` ``defaultMode``) rather than inventing
    a mode id that the catalog may reject.
    """
    req = (requested or "").strip() or None
    if req and req in RESTRICTIVE_MODE_IDS:
        return req
    if req and req in UNATTENDED_MODE_IDS:
        return req
    yolo = yolo_mode(provider)
    if yolo:
        return yolo
    fb = (fallback or "").strip() or None
    if fb:
        return fb
    return req or "default"
