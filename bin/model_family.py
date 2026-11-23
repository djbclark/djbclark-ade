"""Model-family resolution: the newest id of a family, from the live provider catalog (operator 2026-11-21).

Routing config (`config/ade.toml` `[[service]].models`) may name a model FAMILY, a glob such as `gpt-*-astra` or
`gemini-*-neon`, instead of a pinned id. `route_agent.py` resolves it at plan/route time to the newest id
`paseo provider models <provider> --json` lists, by VERSION ordering (the numbers the `*` stands for: 6.2 > 6.1 > 6,
4 > 3.8, 6.10 > 6.9), never lexical. Operator ruling: "the newest version of agents are always used ... we never need
to judge newer versions of agents, we can just assume they are better", so there is no canary or eval gate here.

Catalog entries may be bare model id strings or objects carrying `id` and `thinkingOptionIds`. When a legacy family
name embeds a trailing `-<effort>` suffix (such as `gemini-*-neon-high`) that has no direct id match, `resolve`
strips `-<effort>` and matches catalog entries whose `thinkingOptionIds` includes `<effort>`, returning the base id
with `thinking=<effort>` so the launcher emits `--thinking <effort>`.

An id with no `*`/`?` is a literal and passes through untouched (existing explicit ids keep working).

Order of resolution for a family:
  1. an active hold (`[routing.model_holds]` keyed by the family; `until` is the last day it holds), unset by default;
  2. the newest catalog match;
  3. catalog unreadable, or no id matches: the last id recorded in state, and the note says so;
  4. nothing at all: the family string is returned unchanged and the source reads `unresolved`.
State (`ROUTE_AGENT_MODEL_STATE`, default `~/.local/state/djbclark-ade/route-model-resolved.json`) records, per
provider and family, the newest catalog id, the one before it and when it changed, so `route_agent.py models`
(and `show`) can report that a family moved to a newer id.

Pure functions plus one small JSON state file; no network and no subprocess here (the catalog is passed in).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # not POSIX: the replace stays atomic, only the read-modify-write is unserialized
    fcntl = None  # type: ignore[assignment]

WILDCARDS = ("*", "?")
STATE_ENV = "ROUTE_AGENT_MODEL_STATE"


def is_family(model: str) -> bool:
    """A model string that names a family (carries a glob wildcard) rather than one pinned id."""
    return any(w in model for w in WILDCARDS)


# A `*` stands for a VERSION (1-3 digits per dotted part: 6, 6.2, 6.10), never for words or dates, so `gpt-*-astra` does not
# match gpt-6-mini-astra, gemini-*-neon does not match gemini-4.5-flash-lite-neon or gpt-20261121-astra, and a
# `-preview` or `-mini` line is never "the newest" of a family that does not name it (adversary 2026-11-21, MED-2).
VERSION = r"[0-9]{1,3}(?:\.[0-9]{1,3})*"


def family_regex(glob: str) -> re.Pattern[str]:
    """`*` as a capture group that matches version text only, `?` as one digit; everything else literal. The captures
    are what the version order reads."""
    out = []
    for ch in glob:
        out.append(f"({VERSION})" if ch == "*" else "([0-9])" if ch == "?" else re.escape(ch))
    return re.compile("".join(out))


def version_key(captures: tuple[str, ...]) -> tuple[int, ...]:
    """The numbers inside the wildcard-captured parts, as a tuple: ("6.2",) -> (6, 2); ("6",) -> (6,); ("3.8",) -> (3, 8).
    Tuples compare element-wise and a shorter prefix is smaller, so 6.2 > 6.1 > 6 and 4 > 3.8; 6.10 > 6.9 (integers)."""
    return tuple(int(n) for c in captures for n in re.findall(r"\d+", c))


def matches(glob: str, ids: list[str]) -> list[tuple[tuple[int, ...], str]]:
    """(version key, id) for every catalog id the family matches in full, oldest first."""
    rx = family_regex(glob)
    found = []
    for mid in ids:
        m = rx.fullmatch(mid)
        if m:
            found.append((version_key(m.groups()), mid))
    return sorted(found)


def parse_catalog(entries: Any) -> tuple[list[str], dict[str, tuple[str, ...]]] | None:
    """Normalise a provider catalog list (bare model id strings, Paseo `{id, thinkingOptionIds}` dicts, or mixed) into
    `(ids, thinking_options)`. `thinking_options` maps each model id with a non-empty `thinkingOptionIds` list to a
    deduplicated tuple in catalog order. Returns None when `entries` is not a list."""
    if not isinstance(entries, list):
        return None
    ids: list[str] = []
    thinking: dict[str, tuple[str, ...]] = {}
    for item in entries:
        if isinstance(item, str):
            if item:
                ids.append(item)
        elif isinstance(item, dict):
            mid = item.get("id") or item.get("model")
            if not isinstance(mid, str) or not mid:
                continue
            ids.append(mid)
            raw_opts = item.get("thinkingOptionIds")
            if isinstance(raw_opts, list):
                opts = tuple(dict.fromkeys(o.strip() for o in raw_opts if isinstance(o, str) and o.strip()))
                if opts:
                    thinking[mid] = tuple(dict.fromkeys((*thinking[mid], *opts))) if mid in thinking else opts
    return ids, thinking


def newest(glob: str, ids: list[str]) -> str | None:
    """The newest id of the family in `ids` by version order (ties: the lexically last id, so the answer is stable)."""
    found = matches(glob, ids)
    return found[-1][1] if found else None


def newest_with_thinking(glob: str, ids: list[str],
                         thinking_options: dict[str, tuple[str, ...]] | None = None) -> tuple[str | None, str | None]:
    """The newest match of `glob` in `ids` as `(model_id, inferred_thinking)`.

    Tries a direct catalog id match first (preserving legacy embedded-effort catalogs). When no direct id matches and
    `glob` ends with `-<effort>` (with a family before `-` and no wildcard in `<effort>`), strips `-<effort>` and
    matches against catalog entries whose `thinkingOptionIds` includes `<effort>`."""
    top = newest(glob, ids)
    if top is not None:
        return top, None
    if thinking_options:
        base, sep, suffix = glob.rpartition("-")
        if sep == "-" and base and suffix and is_family(base) and not is_family(suffix):
            eligible = [mid for mid in ids if suffix in thinking_options.get(mid, ())]
            base_top = newest(base, eligible)
            if base_top is not None:
                return base_top, suffix
    return None, None


def check_effort(model: str, effort: str | None,
                 thinking_options: dict[str, tuple[str, ...]] | None) -> str:
    """Return a warning sentence when `model` declares non-empty `thinkingOptionIds` and `effort` is not in them."""
    if not effort or not thinking_options:
        return ""
    opts = thinking_options.get(model)
    if opts and effort not in opts:
        return f"requested effort {effort!r} is not in {model} thinkingOptionIds ({', '.join(opts)})"
    return ""


@dataclass(frozen=True)
class Hold:
    """`[routing.model_holds]` entry: keep `model` for the family until `until` (inclusive) instead of the newest id."""

    model: str
    until: date
    reason: str = ""


def parse_holds(table: Any) -> dict[str, Hold]:
    """`{family: {model, until, reason}}` from the config table; a malformed entry raises ValueError naming the family."""
    if table in (None, {}):
        return {}
    if not isinstance(table, dict):
        raise ValueError("[routing.model_holds] must be a table keyed by model family")  # noqa: TRY004
    holds: dict[str, Hold] = {}
    for family, row in table.items():
        if not isinstance(row, dict) or not isinstance(row.get("model"), str) or not row["model"]:
            raise ValueError(f"[routing.model_holds] {family!r}: needs model = \"<id>\"")
        until = row.get("until")
        if isinstance(until, datetime):
            until = until.date()
        elif isinstance(until, str):
            try:
                until = date.fromisoformat(until)
            except ValueError as exc:
                raise ValueError(f"[routing.model_holds] {family!r}: until must be YYYY-MM-DD") from exc
        if not isinstance(until, date):
            raise ValueError(f"[routing.model_holds] {family!r}: needs until = YYYY-MM-DD (a hold always ends)")
        holds[str(family)] = Hold(model=row["model"], until=until, reason=str(row.get("reason") or ""))
    return holds


@dataclass(frozen=True)
class Resolution:
    family: str                 # the configured model string (glob or literal)
    model: str                  # the id to launch with (the family string itself when unresolved)
    source: str                 # literal | catalog | hold | state | unresolved
    newest: str | None = None   # the newest catalog match, when the catalog was readable and matched
    note: str = ""              # a sentence for plan output; empty for a plain catalog or literal resolution
    thinking: str | None = None # effort inferred from a legacy `-<effort>` suffix via catalog thinkingOptionIds

    @property
    def resolved(self) -> bool:
        return self.source != "unresolved"


def resolve(family: str, ids: list[str] | None, *, holds: dict[str, Hold] | None = None, today: date | None = None,
            last: str | None = None, thinking_options: dict[str, tuple[str, ...]] | None = None,
            effort: str | None = None, last_thinking: str | None = None) -> Resolution:
    """Resolve one model family. `ids` is the provider catalog (None = unreadable), `last` the id recorded in state."""
    if not is_family(family):
        return Resolution(family, family, "literal", note=check_effort(family, effort, thinking_options))
    today = today or datetime.now(UTC).date()
    top, inferred = newest_with_thinking(family, ids, thinking_options) if ids is not None else (None, None)
    hold = (holds or {}).get(family)
    hold_note = ""
    if hold is not None:
        if today <= hold.until:
            why = f": {hold.reason}" if hold.reason else ""
            ahead = f"; newest catalog id is {top}" if top and top != hold.model else ""
            eff_warn = check_effort(hold.model, effort, thinking_options)
            tail = f"; {eff_warn}" if eff_warn else ""
            return Resolution(family, hold.model, "hold", top,
                              f"{family} held at {hold.model} until {hold.until.isoformat()}{why}{ahead}{tail}")
        hold_note = f"hold on {family} ({hold.model}) expired {hold.until.isoformat()}; "
    if top is not None:
        eff_warn = check_effort(top, effort or inferred, thinking_options)
        notes = []
        if hold_note:
            notes.append(f"{hold_note}{family} -> {top}")
        if eff_warn:
            notes.append(eff_warn)
        return Resolution(family, top, "catalog", top, "; ".join(notes), thinking=inferred)
    why = "catalog unreadable" if ids is None else "no catalog id matches"
    if last:
        return Resolution(family, last, "state", None,
                          f"{hold_note}{family}: {why}; using the last resolved id {last} from state",
                          thinking=last_thinking)
    return Resolution(family, family, "unresolved", None,
                      f"{hold_note}{family}: {why} and no id recorded in state; the family string stays in the "
                      "launch line, name a model by hand")


# --- state -------------------------------------------------------------------------------------------------------------

def state_path() -> Path:
    env = os.environ.get(STATE_ENV)
    return Path(env) if env else Path.home() / ".local" / "state" / "djbclark-ade" / "route-model-resolved.json"


def state_key(provider: str, family: str) -> str:
    return f"{provider}:{family}"


def load_state(path: Path | None = None) -> dict[str, dict[str, str]]:
    try:
        data = json.loads((path or state_path()).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("id"), str)} \
        if isinstance(data, dict) else {}


def record(provider: str, family: str, model_id: str, *, thinking: str | None = None,
           now: datetime | None = None, path: Path | None = None) -> bool:
    """Record `model_id` as the newest catalog id of the family. True when it differs from the recorded one (a first
    sighting is not a change). The read-modify-write holds an exclusive lock on `<state>.lock` (two routers recording
    different families at once no longer lose one row) and the file is replaced atomically; a read-only state
    directory is ignored (False)."""
    path = path or state_path()
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    key = state_key(provider, family)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(path):
            state = load_state(path)
            old = state.get(key)
            if old and old.get("id") == model_id and old.get("thinking") == (thinking or None):
                return False
            changed = bool(old and old.get("id") != model_id)
            row = {"id": model_id, "at": stamp}
            if thinking:
                row["thinking"] = thinking
            if changed:
                row["previous"] = old["id"]
                row["changed_at"] = stamp
            elif old and old.get("previous"):
                row["previous"] = old["previous"]
                if old.get("changed_at"):
                    row["changed_at"] = old["changed_at"]
            state[key] = row
            fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(state, fh, indent=1, sort_keys=True)
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
    except OSError:
        return False
    return changed


@contextlib.contextmanager
def _locked(path: Path):
    """Exclusive advisory lock on `<path>.lock` for the duration of the block (a no-op without fcntl)."""
    if fcntl is None:
        yield
        return
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def last_entry(provider: str, family: str, path: Path | None = None) -> tuple[str | None, str | None]:
    row = load_state(path).get(state_key(provider, family))
    if not row:
        return None, None
    thinking = row.get("thinking")
    return row["id"], (thinking if isinstance(thinking, str) and thinking else None)


def last_id(provider: str, family: str, path: Path | None = None) -> str | None:
    return last_entry(provider, family, path)[0]
