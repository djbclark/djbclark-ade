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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

LOCK_TIMEOUT_SECONDS = 30.0


class LockBusy(TimeoutError):
    """The state lock stayed held past the timeout (not any other timeout)."""


def state_dir() -> Path:
    """`$ADE_ROUTE_ADJUST_DIR` or the default; a relative path is refused (it would land in the cwd,
    which can be a repository worktree)."""
    path = Path(os.environ.get("ADE_ROUTE_ADJUST_DIR") or "~/.local/state/ade/route-adjust").expanduser()
    if not path.is_absolute():
        raise ValueError(f"ADE_ROUTE_ADJUST_DIR must be an absolute path, got {str(path)!r}")
    return path


def skey(repo: str | None, kind: str) -> str:
    """State key: floors are repo-scoped ([dispatch.repo_overrides]), so holds are too."""
    return f"{repo.lower()}:{kind}" if repo else kind


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
    """The saved state; a missing, corrupt, wrongly typed or foreign-schema file reads as empty or
    drops the bad row (no holds: plain stateless routing, never a stranded kind)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty_state()
    if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
            or not isinstance(data.get("kinds"), dict)):
        return empty_state()
    kinds: dict[str, Any] = {}
    for key, row in data["kinds"].items():
        if not isinstance(key, str) or not isinstance(row, dict):
            continue
        raw_held = row.get("held")
        held = {pool: info for pool, info in (raw_held if isinstance(raw_held, dict) else {}).items()
                if isinstance(pool, str) and isinstance(info, dict) and _parse(info.get("since"))}
        last = row.get("last") if isinstance(row.get("last"), str) else None
        refused = row.get("refused") if isinstance(row.get("refused"), str) else None
        kinds[key] = {"last": last, "held": held, "refused": refused}
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
def locked(directory: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """One writer at a time over read-modify-write (two leads re-planning together). Gives up after
    `timeout` seconds with TimeoutError, so a hung holder cannot block every later call; symlinks are
    not followed."""
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "state.lock", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"route-adjust lock {directory / 'state.lock'} busy for {timeout:g}s") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def log_events(directory: Path, events: list[dict[str, Any]]) -> None:
    """One line per change, appended in a single write each (O_APPEND keeps lines whole)."""
    if not events:
        return
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "changes.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        for event in events:
            os.write(fd, (json.dumps(event, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)


# --- headroom --------------------------------------------------------------------------

def floors(router: Any, svc: Any, kind: str, info: dict[str, Any], min_headroom: float
           ) -> list[tuple[str, float | None, float]]:
    """(label, reading, floor) for each simple number that gates `kind` on `svc`, for the reason text:
    the pool's tightest window against the router floor (a reserve's own floor, codex's `plenty_min`
    for an everyday kind), and claude's Fable sublimit for `frontier`."""
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


def _cut(value: Any, margin: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return max(0.0, float(value) - margin)


def recovered(router: Any, svc: Any, kind: str, quota: dict[str, Any], min_headroom: float,
              margin: float, repo: str | None) -> bool:
    """Would the pool still take `kind` with `margin` points less in every reading? That puts the margin on
    the floor that actually binds (min/reserve floor, plenty_min, the Fable sublimit, the slice's
    estimate floor and measured history), not just on min_headroom."""
    info = quota.get(svc.name) or {}
    if info.get("remaining") is None:
        return False
    lowered = dict(info)
    lowered["remaining"] = _cut(info.get("remaining"), margin)
    for field in ("windows", "sublimits"):
        if isinstance(info.get(field), dict):
            lowered[field] = {k: _cut(v, margin) for k, v in info[field].items()}
    return bool(router.pool_usable(svc, kind, {**quota, svc.name: lowered}, min_headroom=min_headroom, repo=repo))


# --- the step --------------------------------------------------------------------------

def transitions(router: Any, keys: dict[str, str], state: dict[str, Any], *, quota: dict[str, Any],
                fresh: bool, now: datetime, cfg: dict[str, Any], min_headroom: float,
                repo: str | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    """Expire, hold and release per kind. `keys` maps kind -> state key. Returns (state, events, placed)
    where `placed` maps state key -> pool held this call. Without a fresh reading nothing is held or
    released (a stale number is neither a dip nor a recovery); expiry still applies, and a timestamp
    in the future counts as expired (a clock stepped back would otherwise pin the hold)."""
    out = json.loads(json.dumps(state))              # deep copy of plain JSON
    events: list[dict[str, Any]] = []
    placed: dict[str, str] = {}
    by_name = router.BY_NAME
    for kind, key in keys.items():
        row = out["kinds"].setdefault(key, {"last": None, "held": {}, "refused": None})
        held = row["held"]
        for pool in list(held):
            since = _parse(held[pool].get("since"))
            age = None if since is None else (now - since).total_seconds()
            if age is None or age < 0 or age > cfg["max_hold_seconds"]:
                del held[pool]
                events.append(_event("expire", kind, now, pool=pool,
                                     why=f"hold older than {cfg['max_hold_seconds']:g}s or timestamp invalid"))
        if not fresh:
            continue
        for pool in list(held):
            svc = by_name.get(pool)
            since = _parse(held[pool].get("since"))
            dwelled = since is not None and (now - since).total_seconds() >= cfg["min_dwell_seconds"]
            if svc is None or (dwelled and recovered(router, svc, kind, quota, min_headroom,
                                                     cfg["restore_margin"], repo)):
                del held[pool]
                events.append({"event": "release", "kind": kind, "pool": pool, "at": _iso(now)})
        last = row.get("last")
        svc = by_name.get(last) if last else None
        if svc is not None and last not in held:
            why = short_reason(router, svc, kind, quota, min_headroom, repo)
            if why:
                info = quota.get(last) or {}
                held[last] = {"since": _iso(now), "remaining": info.get("remaining"), "why": why}
                placed[key] = last
    return out, events, placed


def _event(name: str, kind: str, now: datetime, **fields: Any) -> dict[str, Any]:
    return {"event": name, "kind": kind, "at": _iso(now), **fields}


def _names_never(never: set[str], svc: Any, model: str) -> bool:
    """Exact matches only: the pool name, its agent, a model's provider prefix, or an `omp-` family name.
    Never a substring of the model id ("composer" contains "omp")."""
    provider = model.split("/", 1)[0] if "/" in model else ""
    names = {svc.name, svc.acp_agent, getattr(svc, "agent", ""), provider}
    return bool(names & never) or any(n.startswith(f"{x}-") for n in (svc.name, svc.acp_agent) for x in never)


def _refusal(router: Any, kind: str, choice: Any, cfg: dict[str, Any]) -> str | None:
    """A reason this choice may not be launched, or None. The two hard rules."""
    svc = choice.service
    parts = (choice.model or "").split()
    model = parts[0] if parts else ""
    if _names_never(set(cfg["never_target"]), svc, model):
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

    The tracked pool of a kind is the one its FIRST slice in the wave gets; a kind's later slices (spread
    over pools by `max_parallel`) neither move it nor log. `enabled = false` is `plan` plus the two hard
    rules, with no state. Held pools are avoided, not excluded: the quality band stays anchored where plain
    `plan` anchors it, and a held pool still takes the kind when nothing acceptable remains.

    Result: {"rows": [(kind, Choice|None, refusal|None)], "state": ..., "events": [...],
             "held": {kind: [pool...]}, "fresh": bool}."""
    now = now or datetime.now(UTC)
    cfg = cfg or settings(router)
    fresh = bool(quota) and age is not None and age <= cfg["max_age_seconds"]
    tracking = cfg["enabled"]
    keys = {k: skey(repo, k) for k in dict.fromkeys(kinds)}
    if tracking:
        new_state, events, placed = transitions(router, keys, state, quota=quota, fresh=fresh, now=now,
                                                cfg=cfg, min_headroom=min_headroom, repo=repo)
    else:
        new_state, events, placed = empty_state(), [], {}
        for key in keys.values():
            new_state["kinds"][key] = {"last": None, "held": {}, "refused": None}
    kind_exclude = {k: set(new_state["kinds"][key]["held"]) for k, key in keys.items()}
    never = set(cfg["never_target"])
    skip = set(exclude) | never | {
        s.name for s in router.BY_NAME.values()
        if _names_never(never, s, "") or any(_names_never(never, s, m.split()[0])
                                             for m in s.models.values() if m.split())}
    refusals: list[str | None] = []
    planned = router.plan(kinds, quota=quota, min_headroom=min_headroom, exclude=skip, repo=repo,
                          kind_exclude=kind_exclude, reject=lambda k, c: _refusal(router, k, c, cfg),
                          refusals=refusals)
    rows: list[tuple[str, Any, str | None]] = []
    seen: set[str] = set()
    changed: set[str] = set()                                   # state keys with a change line this call
    for (kind, choice), refusal in zip(planned, refusals):
        key = keys[kind]
        row = new_state["kinds"][key]
        first = key not in seen
        seen.add(key)
        if refusal is not None:
            rows.append((kind, None, refusal))
            if first and row.get("refused") != refusal:
                events.append(_event("refuse", kind, now, why=refusal))
            if first:
                row["refused"] = refusal
            continue
        rows.append((kind, choice, None))
        if choice is None or not first:
            continue
        row["refused"] = None
        pool = choice.service.name
        if pool in row["held"]:
            # held, but nothing acceptable could take the kind: restore early rather than strand it
            was = row["held"].pop(pool)
            events.append(_event("restore", kind, now, to=pool, why="no acceptable alternative pool",
                                 was=was.get("why")))
            changed.add(key)
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
            changed.add(key)
        row["last"] = pool
    for key, pool in placed.items():                            # a hold with no route line to carry it
        if key not in changed:
            kind = next(k for k, v in keys.items() if v == key)
            events.append(_event("hold", kind, now, pool=pool, why=new_state["kinds"][key]["held"][pool]["why"]))
    restored = {(e["kind"], e.get("to")) for e in events if e["event"] == "restore"}
    events = [e for e in events if not (e["event"] == "release" and (e["kind"], e["pool"]) in restored)]
    if not tracking:
        events = [e for e in events if e["event"] == "refuse"]      # nothing else changed: no state kept
    held = {k: sorted(new_state["kinds"][key]["held"]) for k, key in keys.items() if new_state["kinds"][key]["held"]}
    return {"rows": rows, "state": new_state, "events": events, "held": held, "fresh": fresh}


def _released(events: list[dict[str, Any]], kind: str, pool: str) -> bool:
    return any(e["event"] == "release" and e["kind"] == kind and e["pool"] == pool for e in events)
