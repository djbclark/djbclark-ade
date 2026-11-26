"""Owned-key merge for agents/ chezmoi modify_ helpers (Phase 1 residual, 2026-11-10).

Desired (rendered template) keys are owned and applied; keys that exist only in the live
file stay. Dicts merge recursively. When both values are lists, retain desired entries
first, then live-only entries, without deep-equality duplicates — except any dictionary
`args` list (positional argv, replaced atomically whole like Codex top-level `notify`).
Scalars and differing types use desired. No secrets,
no companion render, and no write to the operator's live ~/.claude or ~/.codex paths
(order 11): those targets are refused until a later chezmoi apply slice owns that step.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

# Live targets this helper must not write (order 11 / "no live ~/.claude apply").
_LIVE_REFUSE = (
    Path(".claude") / "settings.json",
    Path(".codex") / "config.toml",
)


def merge_owned(live: Any, desired: Any) -> Any:
    """Keep unowned live keys; apply owned desired keys.

    Desired dicts recurse and keep live-only keys when live is a dict. Ordinary
    lists retain the first occurrence of each deeply equal entry in desired then
    live order. Entries are opaque whole values: compare and deep-copy their
    original content without normalizing nested dicts/lists or merging by
    identity. For ordinary collection lists, an empty desired list preserves live
    entries; deletion requires removing entries explicitly outside this helper.
    Dictionary `args` lists (e.g., `mcp_servers.<name>.args`) are atomic
    positional argv vectors like Codex top-level `notify`: when owned, desired
    replaces live whole (preserving repeated flags and allowing `[]` to clear
    live args); when unowned, live `args` stays intact. New/type-changing desired
    dictionaries recurse by key until each list boundary; new/type-changing
    ordinary lists deduplicate outer entries on the first merge, too. Otherwise
    desired replaces live. Results are deep copies, so changing them never
    changes either input.
    """
    if isinstance(desired, dict):
        out = copy.deepcopy(live) if isinstance(live, dict) else {}
        for key, value in desired.items():
            # `args` is an executable's positional argv, like `notify`: repeated flags are meaningful
            # and the whole vector is replaced, never unioned or deduped (Codex review on #771).
            if key == "args" and isinstance(value, list):
                out[key] = copy.deepcopy(value)
            elif key in out:
                out[key] = merge_owned(out[key], value)
            else:
                out[key] = merge_owned(None, value)
        return out
    if isinstance(desired, list):
        out = []
        for entry in desired + (live if isinstance(live, list) else []):
            if entry not in out:
                out.append(copy.deepcopy(entry))
        return out
    return copy.deepcopy(desired)


def refuse_live_home(path: Path, home: Path | None = None) -> str | None:
    """Return a refusal message if path is the operator's live Claude/Codex config."""
    home = (home or Path.home()).expanduser().resolve()
    try:
        real = path.expanduser().resolve()
    except OSError:
        real = path.expanduser()
    for rel in _LIVE_REFUSE:
        if real == (home / rel):
            return (
                f"refusing to write live {rel} (order 11); pass a temp or fixture path"
            )
    return None


def load_json(text: str) -> dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def load_toml(text: str) -> dict[str, Any]:
    data = tomllib.loads(text)
    if not isinstance(data, dict):
        raise ValueError("TOML root must be a table")
    return data


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    if _BARE_KEY.fullmatch(key):
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    raise TypeError(f"unsupported TOML scalar type: {type(value).__name__}")


def _toml_array(value: list[Any]) -> str:
    if not value:
        return "[]"
    if all(not isinstance(x, (dict, list)) for x in value):
        return "[ " + ", ".join(_toml_scalar(x) for x in value) + ",]"
    # Nested arrays of scalars only (Codex notify is flat strings).
    parts = []
    for item in value:
        if isinstance(item, list):
            parts.append(_toml_array(item))
        elif isinstance(item, dict):
            raise TypeError("array of tables is not supported by this encoder")
        else:
            parts.append(_toml_scalar(item))
    return "[ " + ", ".join(parts) + ",]"


def dump_toml(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> str:
    """Minimal TOML encoder for merge output (dicts → tables; lists/scalars inline)."""
    lines: list[str] = []
    scalars: list[tuple[str, Any]] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append((key, value))
    for key, value in scalars:
        k = _toml_key(key)
        if isinstance(value, list):
            lines.append(f"{k} = {_toml_array(value)}")
        else:
            lines.append(f"{k} = {_toml_scalar(value)}")
    if scalars and tables and prefix == ():
        lines.append("")
    for key, value in tables:
        path = prefix + (key,)
        header = ".".join(_toml_key(p) for p in path)
        # Emit header even for empty tables so round-trips keep the key.
        lines.append(f"[{header}]")
        body = dump_toml(value, path)
        if body:
            lines.append(body.rstrip("\n"))
        lines.append("")
    text = "\n".join(lines).rstrip() + ("\n" if lines else "")
    return text


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    """Write text beside path then os.replace (review rule 6)."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        elif path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_text(path: Path | None, label: str) -> str:
    if path is None:
        return sys.stdin.read()
    try:
        return path.expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"modify_merge: cannot read {label} {path}: {e.strerror}") from e
