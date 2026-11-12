#!/usr/bin/env python3
"""Stateful, launch-time pool adjustment with restoration (W8, 2026-11-12).

`route_agent.py plan` is a stateless snapshot: it picks the best pool right now. This
module adds the memory a mid-run quota dip needs, for NEW launches only:

  * a kind's last routed pool whose headroom falls below its floor is held off, and
    launches of that kind move to the next eligible pool (the router's own `route`, so
    the quality band, wave caps, frontier gates and `never_route` all still apply);
  * a held pool comes back only after it recovers `restore_margin` points above its
    floor and has been held `min_dwell_seconds` (hysteresis, so a pool hovering at its
    floor does not flap); a hold never strands a kind: with no alternative, an usable
    held pool is restored early;
  * every change (switch, restore, expiry, refusal) is one JSON line in the change log.

Hard rules, enforced here and tested: a `frontier` slice is never silently downgraded
(a frontier route to a non-frontier model is REFUSED and reported); a pool in
`[routing.adjust].never_target` (omp) is never a target; running agents are never
touched (this only shapes the next launch line); nothing here writes policy.

Config: `[routing.adjust]` in config/routing.toml. State and log: `$ADE_ROUTE_ADJUST_DIR`
(default ~/.local/state/ade/route-adjust/). Offline-testable: pass `quota`/`age`/`now`.
The router module is injected (`router`), so the CLI and tests share one set of globals.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

UTC = timezone.utc
SCHEMA_VERSION = 1
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "restore_margin": 10.0,        # points above the floor before a held pool is restored
    "min_dwell_seconds": 900,      # a hold lasts at least this long (anti-flap)
    "max_hold_seconds": 21600,     # a hold expires after this long even without a fresh reading
    "max_age_seconds": 1500,       # a snapshot older than this changes no hold (aiuse's own `fresh`)
    "never_target": ["omp"],       # pools and agents adjustment never routes to
}


def settings(router: Any) -> dict[str, Any]:
    """`[routing.adjust]` over DEFAULTS, validated; ValueError names the bad key."""
    raw = ((getattr(router, "POLICY", None) or {}).get("routing") or {}).get("adjust") or {}
    if not isinstance(raw, dict):
        raise ValueError("routing policy: [routing.adjust] must be a table")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"routing policy: [routing.adjust] unknown key(s) {sorted(unknown)}")
    cfg = {**DEFAULTS, **raw}
    if not isinstance(cfg["enabled"], bool):
        raise ValueError("routing policy: [routing.adjust] enabled must be true or false")
    for key in ("restore_margin", "min_dwell_seconds", "max_hold_seconds", "max_age_seconds"):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"routing policy: [routing.adjust] {key} must be a number >= 0")
    never = cfg["never_target"]
    if not (isinstance(never, list) and all(isinstance(x, str) and x for x in never)):
        raise ValueError("routing policy: [routing.adjust] never_target must be an array of names")
    cfg["never_target"] = sorted({*never, "omp"})      # omp can be added to, never removed
    return cfg


# --- state and log ---------------------------------------------------------------------

def state_dir() -> Path:
    return Path(os.environ.get("ADE_ROUTE_ADJUST_DIR") or "~/.local/state/ade/route-adjust").expanduser()


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def empty_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "kinds": {}}


def load_state(path: Path) -> dict[str, Any]:
    """The saved state; a missing, corrupt or foreign-schema file reads as empty (no holds:
    plain stateless routing, never a stranded kind)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty_state()
    if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
            or not isinstance(data.get("kinds"), dict)):
        return empty_state()
    kinds: dict[str, Any] = {}
    for kind, row in data["kinds"].items():
        if not isinstance(kind, str) or not isinstance(row, dict):
            continue
        held = {pool: info for pool, info in (row.get("held") or {}).items()
                if isinstance(pool, str) and isinstance(info, dict) and _parse(info.get("since"))}
        last = row.get("last") if isinstance(row.get("last"), str) else None
        kinds[kind] = {"last": last, "held": held}
    return {"schema_version": SCHEMA_VERSION, "kinds": kinds}


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomic: temp file beside the target, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def locked(directory: Path) -> Iterator[None]:
    """One writer at a time over read-modify-write (two leads re-planning together)."""
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "state.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def log_events(directory: Path, events: list[dict[str, Any]]) -> None:
    """One line per change, appended in a single write each (O_APPEND keeps lines whole)."""
    if not events:
        return
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "changes.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        for event in events:
            os.write(fd, (json.dumps(event, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)


# --- headroom --------------------------------------------------------------------------

def floors(router: Any, svc: Any, kind: str, info: dict[str, Any], min_headroom: float
           ) -> list[tuple[str, float | None, float]]:
    """(label, reading, floor) for each number that gates `kind` on `svc`: the pool's tightest
    window against the router floor (a reserve's own floor, codex's `plenty_min` for an
    everyday kind), and claude's Fable sublimit for `frontier`."""
    floor = max(min_headroom, svc.reserve_floor or 0.0)
    if kind in (svc.plenty_kinds or ()):
        floor = max(floor, router.PLENTY_MIN)
    rows: list[tuple[str, float | None, float]] = [("remaining", info.get("remaining"), floor)]
    if svc.name == "claude" and kind == "frontier":
        gate = router.frontier_gate()["frontier1_min_left"]
        rows.append(("fable sublimit", (info.get("sublimits") or {}).get("fable"), gate))
    return rows


def short_reason(router: Any, svc: Any, kind: str, quota: dict[str, Any], min_headroom: float,
                 repo: str | None) -> str | None:
    """Why `svc` cannot take `kind` now by headroom; None when it can or when it has no reading
    (an unknown pool is never displaced: absence of data is not a shortfall)."""
    info = quota.get(svc.name) or {}
    if info.get("remaining") is None:
        return None
    if router.pool_usable(svc, kind, quota, min_headroom=min_headroom, repo=repo):
        return None
    for label, value, floor in floors(router, svc, kind, info, min_headroom):
        if value is not None and value < floor:
            return f"{label} {value:.0f}% left < floor {floor:.0f}%"
    return "slice does not fit the remaining window"


def recovered(router: Any, svc: Any, kind: str, quota: dict[str, Any], min_headroom: float,
              margin: float, repo: str | None) -> bool:
    info = quota.get(svc.name) or {}
    if info.get("remaining") is None:
        return False
    if not router.pool_usable(svc, kind, quota, min_headroom=min_headroom, repo=repo):
        return False
    return all(value is None or value >= floor + margin
               for _, value, floor in floors(router, svc, kind, info, min_headroom))


# --- the step --------------------------------------------------------------------------

def transitions(router: Any, kinds: list[str], state: dict[str, Any], *, quota: dict[str, Any],
                fresh: bool, now: datetime, cfg: dict[str, Any], min_headroom: float,
                repo: str | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Expire, hold and release per kind. Returns (state, events, shorts) where `shorts` maps
    kind -> {pool: reason} for pools held off this call. Without a fresh reading nothing is
    held or released (a stale number is neither a dip nor a recovery); expiry still applies."""
    out = json.loads(json.dumps(state))              # deep copy of plain JSON
    events: list[dict[str, Any]] = []
    shorts: dict[str, dict[str, str]] = {}
    by_name = router.BY_NAME
    for kind in dict.fromkeys(kinds):
        row = out["kinds"].setdefault(kind, {"last": None, "held": {}})
        held = row["held"]
        for pool in list(held):
            since = _parse(held[pool].get("since"))
            if since is not None and (now - since).total_seconds() > cfg["max_hold_seconds"]:
                del held[pool]
                events.append(_event("expire", kind, now, pool=pool,
                                     why=f"hold older than {cfg['max_hold_seconds']:g}s"))
        if not fresh:
            continue
        for pool in list(held):
            svc = by_name.get(pool)
            since = _parse(held[pool].get("since"))
            dwelled = since is not None and (now - since).total_seconds() >= cfg["min_dwell_seconds"]
            if svc is None or (dwelled and recovered(router, svc, kind, quota, min_headroom,
                                                     cfg["restore_margin"], repo)):
                del held[pool]
                shorts.setdefault(kind, {})
                events.append({"event": "release", "kind": kind, "pool": pool, "at": _iso(now)})
        last = row.get("last")
        svc = by_name.get(last) if last else None
        if svc is not None and last not in held:
            why = short_reason(router, svc, kind, quota, min_headroom, repo)
            if why:
                info = quota.get(last) or {}
                held[last] = {"since": _iso(now), "remaining": info.get("remaining"), "why": why}
                shorts.setdefault(kind, {})[last] = why
    return out, events, shorts


def _event(name: str, kind: str, now: datetime, **fields: Any) -> dict[str, Any]:
    return {"event": name, "kind": kind, "at": _iso(now), **fields}


def _refusal(router: Any, kind: str, choice: Any, cfg: dict[str, Any]) -> str | None:
    """A reason this choice may not be launched, or None. The two hard rules."""
    svc = choice.service
    model = (choice.model or "").split()[0] if (choice.model or "").split() else ""
    never = set(cfg["never_target"])
    if (svc.name in never or svc.acp_agent in never
            or any(n in model.lower() for n in never if n)):
        return f"{svc.name} is in [routing.adjust].never_target"
    if kind == "frontier" and not router.is_frontier_model(model):
        return (f"frontier slice would run on {svc.name} {model or '(no model)'}, "
                "a cheaper tier: refused, not downgraded")
    return None


def adjust(router: Any, kinds: list[str], *, quota: dict[str, Any], age: float | None,
           state: dict[str, Any], now: datetime | None = None, exclude: set[str] | frozenset[str] = frozenset(),
           min_headroom: float = 15.0, repo: str | None = None, cfg: dict[str, Any] | None = None
           ) -> dict[str, Any]:
    """Plan one wave with hysteresis. Pure: returns the new state and events, writes nothing.

    Result: {"rows": [(kind, Choice|None, refusal|None)], "state": ..., "events": [...],
             "held": {kind: [pool...]}, "fresh": bool}."""
    now = now or datetime.now(UTC)
    cfg = cfg or settings(router)
    fresh = bool(quota) and age is not None and age <= cfg["max_age_seconds"]
    new_state, events, _ = transitions(router, kinds, state, quota=quota, fresh=fresh, now=now,
                                       cfg=cfg, min_headroom=min_headroom, repo=repo)
    kind_exclude = {k: set(new_state["kinds"][k]["held"]) | set(cfg["never_target"])
                    for k in new_state["kinds"] if k in kinds}
    skip = set(exclude) | set(cfg["never_target"])
    planned = router.plan(kinds, quota=quota, min_headroom=min_headroom, exclude=skip, repo=repo,
                          kind_exclude=kind_exclude)
    rows: list[tuple[str, Any, str | None]] = []
    for kind, choice in planned:
        row = new_state["kinds"][kind]
        refusal = _refusal(router, kind, choice, cfg) if choice is not None else None
        if choice is not None and refusal is not None:
            events.append(_event("refuse", kind, now, pool=choice.service.name, why=refusal))
            rows.append((kind, None, refusal))
            continue
        if choice is not None:
            pool = choice.service.name
            if pool in row["held"]:
                # held, but nothing else could take the kind: restore early rather than strand it
                why = row["held"].pop(pool)
                events.append(_event("restore", kind, now, to=pool, why="no alternative pool",
                                     was=why.get("why")))
            elif row.get("last") != pool:
                prev = row.get("last")
                if prev is None:
                    events.append(_event("route", kind, now, to=pool))
                elif _released(events, kind, pool):
                    events.append(_event("restore", kind, now, **{"from": prev}, to=pool,
                                         why="recovered above floor + margin"))
                else:
                    held_why = (row["held"].get(prev) or {}).get("why")
                    events.append(_event("switch", kind, now, **{"from": prev}, to=pool,
                                         why=held_why or "better pool by score"))
            row["last"] = pool
        rows.append((kind, choice, None))
    restored = {(e["kind"], e.get("to")) for e in events if e["event"] == "restore"}
    events = [e for e in events if not (e["event"] == "release" and (e["kind"], e["pool"]) in restored)]
    held = {k: sorted(v["held"]) for k, v in new_state["kinds"].items() if v["held"]}
    return {"rows": rows, "state": new_state, "events": events, "held": held, "fresh": fresh}


def _released(events: list[dict[str, Any]], kind: str, pool: str) -> bool:
    return any(e["event"] == "release" and e["kind"] == kind and e["pool"] == pool for e in events)
