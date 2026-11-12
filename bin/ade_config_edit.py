"""ade_config_edit: comment-preserving atomic scalar set for ADE config TOML.

Pure helper used by ``ade-config set``. Stdlib only. Edits one scalar assignment
in place (or inserts a simple ``key = value`` under an existing/new table header),
then reparses with ``tomllib`` and checks the resulting tree equals the expected
type-aware tree with exactly that path changed.

Does not write unmanaged environment-override sources (ROUTING_POLICY / GATES_TOML).
Does not create ``config/ade.toml`` when absent (that would suppress legacy projection).
Local sets record per-machine choices. Effective-config readers adopt them on
their next load; a set does not prove runtime reload (adoption=recorded-only).
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import ade_config as ac
import ade_install_catalog as catalog

ADOPTION_RECORDED_ONLY = "recorded-only"
ADOPTION_NOTE = (
    "local/repo set records the choice in TOML; effective-config readers adopt it "
    "on their next load, but this write does not reload running consumers or "
    "prove runtime adoption"
)

# Paths under these roots are refused by the scalar editor (arrays / AoT / selectors).
_REFUSED_ROOTS = frozenset({"service"})
KEY_METADATA_FIELDS = frozenset({"create_url", "verify", "expiry", "notes"})
# W16 (2026-11-12): bounded string-array and choice writes. Anything not listed stays refused.
KEY_ARRAY_FIELDS = frozenset({"verify_argv", "components"})
COMPONENT_ARRAY_FIELDS = frozenset({"install_argv", "update_argv", "probe_argv", "system_argv",
                                    "system_argv_darwin", "platforms"})
JOB_ARRAY_FIELDS = frozenset({"set", "platforms"})
CHOICE_FIELDS = frozenset({"chosen"})
KEY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# install row kinds: first path part after ``install`` -> (field allowlist, identity key)
INSTALL_ROWS = {
    "component": (COMPONENT_ARRAY_FIELDS | CHOICE_FIELDS, "id"),
    "jobs": (JOB_ARRAY_FIELDS | CHOICE_FIELDS, "name"),
}


class EditError(ac.ConfigError):
    """Unsupported target form, verification failure, or refused write."""


@dataclass(frozen=True)
class SetTarget:
    """Resolved write destination for one set."""

    path: Path
    file_parts: tuple[str, ...]  # dotted path parts inside the file
    kind: str  # local/unified/legacy_routing/legacy_gates/legacy_context/legacy_key
    target: str  # "local" | "repo"
    created: bool
    key_name: str | None = None
    # Array-of-tables row edit: (header parts, identity field, identity value). None = table path.
    row: tuple[tuple[str, ...], str, str] | None = None


@dataclass(frozen=True)
class SetResult:
    target: SetTarget
    before: Any
    after: Any
    changed: bool
    dry_run: bool
    adoption: str
    adoption_note: str
    text_before: str | None = None
    text_after: str | None = None


def parse_cli_value(raw: str, *, as_string: bool) -> Any:
    """Parse VALUE as a TOML scalar, or force a string with --string."""
    if as_string:
        return raw
    try:
        wrapped = tomllib.loads(f"_ = {raw}\n")
    except tomllib.TOMLDecodeError as e:
        raise EditError(
            f"VALUE is not a TOML scalar ({e}); quote it or pass --string"
        ) from e
    value = wrapped["_"]
    if isinstance(value, dict):
        raise EditError("VALUE must be a scalar (bool, number, or string) or an array of strings; not a table")
    if isinstance(value, list):
        _check_string_array(value)
    return value


def _check_string_array(value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise EditError("array VALUE must be a TOML array of non-empty strings")
    if any(ch in v for v in value for ch in ("\0", "\n", "\r")):
        raise EditError("array VALUE: control characters refused")


def encode_toml_value(value: Any) -> str:
    """Single-line TOML for a scalar or an array of strings."""
    if isinstance(value, list):
        _check_string_array(value)
        return "[" + ", ".join(encode_toml_scalar(v) for v in value) + "]"
    return encode_toml_scalar(value)


def encode_toml_scalar(value: Any) -> str:
    """Encode a Python scalar as a single-line TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # noqa: PLR0124
            raise EditError("float VALUE must be finite")
        # Keep a decimal so tomllib round-trips as float, not int.
        text = repr(value)
        if "e" in text.lower() or "." in text:
            return text
        return text + ".0"
    if isinstance(value, str):
        # JSON basic-string escaping is a safe subset for TOML basic strings.
        return json.dumps(value, ensure_ascii=False)
    raise EditError(f"unsupported scalar type {type(value).__name__}")


def values_equal(left: Any, right: Any) -> bool:
    """Type-aware equality: bool is never int/float; int is never float."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if set(left) != set(right):
            return False
        return all(values_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(values_equal(a, b) for a, b in zip(left, right))
    return left == right


def split_dotted_path(dotted: str) -> tuple[str, ...]:
    if not dotted or dotted.strip() != dotted:
        raise EditError("PATH must be a non-empty dotted path without surrounding whitespace")
    if dotted.startswith(("context_budget.", "keys.", "install.")):
        try:
            parts = ac.metadata_path_parts(dotted)
        except ac.ConfigError as error:
            raise EditError(str(error)) from error
    else:
        parts = tuple(dotted.split("."))
    if any(not p or p.strip() != p for p in parts):
        raise EditError(f"invalid PATH {dotted!r}")
    if "[" in dotted or "]" in dotted or "\n" in dotted or "\r" in dotted or "\0" in dotted:
        raise EditError(
            f"PATH {dotted!r}: service selectors and index paths are not supported by scalar set"
        )
    if parts[0] in _REFUSED_ROOTS:
        raise EditError(
            f"PATH {dotted!r}: editing [[{parts[0]}]] / array entries is not supported by scalar set"
        )
    return parts


def get_from_tree(data: dict[str, Any], parts: tuple[str, ...]) -> Any:
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(part)
        cur = cur[part]
    return cur


def set_in_tree(data: dict[str, Any], parts: tuple[str, ...], value: Any) -> dict[str, Any]:
    if not parts:
        raise EditError("empty path")
    out = copy.deepcopy(data)
    cur: Any = out
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = copy.deepcopy(value)
    return out


def _install_row_selector(dotted: str, parts: tuple[str, ...]) -> tuple[frozenset[str], str]:
    """Validate ``install.component.ID.FIELD`` / ``install.jobs.NAME.FIELD``; return (fields, identity key)."""
    if len(parts) != 4 or parts[1] not in INSTALL_ROWS or parts[3] not in INSTALL_ROWS[parts[1]][0]:
        allowed = {k: sorted(v[0]) for k, v in INSTALL_ROWS.items()}
        raise EditError(
            f"PATH {dotted!r}: install set supports install.component.ID.FIELD / install.jobs.NAME.FIELD "
            f"for existing rows only, fields {allowed}"
        )
    return INSTALL_ROWS[parts[1]]


def resolve_set_target(
    dotted: str,
    *,
    target: str,
    root: Path,
    home: Path,
) -> SetTarget:
    """Choose the real file to edit. Never writes ROUTING_POLICY / GATES_TOML paths."""
    if target not in ("local", "repo"):
        raise EditError(f"unknown --target {target!r} (want local or repo)")
    parts = split_dotted_path(dotted)
    install_row = _install_row_selector(dotted, parts) if parts[0] == "install" else None
    if parts[0] == "keys" and (len(parts) != 3 or parts[2] not in KEY_METADATA_FIELDS | KEY_ARRAY_FIELDS):
        raise EditError(
            f"PATH {dotted!r}: keys set only supports named-key metadata "
            f"{sorted(KEY_METADATA_FIELDS | KEY_ARRAY_FIELDS)}"
        )
    if parts[0] == "context_budget" and not (
        parts == ("context_budget", "dirs") or (len(parts) in {3, 4} and parts[1] == "budget")
    ):
        raise EditError(f"PATH {dotted!r}: context set only supports numeric budget leaves and dirs")
    root = root.resolve()
    home = home.resolve()

    if install_row is not None:
        if target == "local":
            raise EditError(
                f"PATH {dotted!r}: install component/job arrays replace whole in local.toml, so a "
                "local row edit would shadow the entire array; use --target repo"
            )
        new_path = ac.default_new_config_path(root)
        if ac.input_present(new_path):
            aot = ("install", parts[1])
            return SetTarget(path=new_path, file_parts=(parts[3],), kind="unified", target="repo",
                             created=False, row=(aot, install_row[1], parts[2]))
        path = root / "config/install.toml"
        aot = ("component",) if parts[1] == "component" else ("install", "jobs")
        return SetTarget(path=path, file_parts=(parts[3],), kind="legacy_install", target="repo",
                         created=not ac.input_present(path), row=(aot, install_row[1], parts[2]))

    if target == "local":
        path = ac.default_local_path(home)
        created = not ac.input_present(path)
        return SetTarget(
            path=path,
            file_parts=parts,
            kind="local",
            target="local",
            created=created,
        )

    new_path = ac.default_new_config_path(root)
    if ac.input_present(new_path):
        return SetTarget(
            path=new_path,
            file_parts=parts,
            kind="unified",
            target="repo",
            created=False,
        )

    # Legacy projection: route domain keys live in routing.toml; gates.* in gates.toml.
    if parts[0] == "context_budget":
        path = root / "config/context-budget.toml"
        return SetTarget(path=path, file_parts=parts[1:], kind="legacy_context", target="repo",
                         created=not ac.input_present(path))
    if parts[0] == "keys":
        path = root / "config/install.toml"
        return SetTarget(path=path, file_parts=(parts[2],), kind="legacy_key", target="repo",
                         created=not ac.input_present(path), key_name=parts[1],
                         row=(("key",), "name", parts[1]))
    if parts[0] == "gates":
        if len(parts) < 2:
            raise EditError("PATH gates alone is a table; scalar set needs a leaf under gates.*")
        return SetTarget(
            path=ac.default_gates_path(root),
            file_parts=parts[1:],  # strip effective "gates." prefix
            kind="legacy_gates",
            target="repo",
            created=not ac.input_present(ac.default_gates_path(root)),
        )
    if parts[0] in ac.ROUTING_DOMAIN_KEYS:
        return SetTarget(
            path=ac.default_routing_path(root),
            file_parts=parts,
            kind="legacy_routing",
            target="repo",
            created=not ac.input_present(ac.default_routing_path(root)),
        )
    raise EditError(
        f"PATH {dotted!r}: with legacy projection (no config/ade.toml), "
        f"repo set only supports routing-domain keys or gates.*"
    )


# --- TOML text scanner (stdlib; not a full parser) -------------------------------------------


def _is_bare_key_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_-"


def _scan_string_end(text: str, start: int) -> int:
    """start points at opening quote(s). Return index past the closing quote(s)."""
    n = len(text)
    if text.startswith('"""', start):
        i = start + 3
        while i < n:
            if text.startswith('"""', i):
                return i + 3
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            i += 1
        raise EditError("unterminated multiline basic string")
    if text.startswith("'''", start):
        i = start + 3
        while i < n:
            if text.startswith("'''", i):
                return i + 3
            i += 1
        raise EditError("unterminated multiline literal string")
    if text[start] == '"':
        i = start + 1
        while i < n:
            ch = text[i]
            if ch == '"':
                return i + 1
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == "\n":
                raise EditError("unterminated basic string")
            i += 1
        raise EditError("unterminated basic string")
    if text[start] == "'":
        i = start + 1
        while i < n:
            if text[i] == "'":
                return i + 1
            if text[i] == "\n":
                raise EditError("unterminated literal string")
            i += 1
        raise EditError("unterminated literal string")
    raise EditError("not a string")


def _scan_scalar_value_end(text: str, start: int) -> int:
    """Return index past a single-line scalar (or refuse arrays/tables/multiline)."""
    n = len(text)
    i = start
    while i < n and text[i] in " \t":
        i += 1
    if i >= n:
        raise EditError("missing value")
    ch = text[i]
    if ch in "[{":
        raise EditError("arrays and inline tables are not supported by scalar set")
    if ch in "\"'":
        end = _scan_string_end(text, i)
        if text.startswith('"""', i) or text.startswith("'''", i):
            raise EditError("multiline strings are not supported by scalar set")
        return end
    # bare: bool / number / special float — stop at whitespace, comment, or newline
    j = i
    while j < n and text[j] not in " \t\r\n#,}]":
        j += 1
    if j == i:
        raise EditError("missing value")
    return j


def _parse_header(line: str) -> tuple[str, tuple[str, ...]] | None:
    """Return ('table'|'aot', parts) for a header line, else None."""
    s = line.strip()
    if not s.startswith("["):
        return None
    return _decode_table_header(s)


def _decode_table_header(line: str) -> tuple[str, tuple[str, ...]]:
    try:
        return ac.decode_table_key_chain(line)
    except ac.ConfigError as error:
        raise EditError(str(error)) from error


def _encode_key(part: str) -> str:
    return part if re.fullmatch(r"[A-Za-z0-9_-]+", part) else json.dumps(part, ensure_ascii=False)


@dataclass
class _AssignmentHit:
    key_start: int
    value_start: int
    value_end: int
    table_parts: tuple[str, ...]
    key: str


def find_scalar_assignment(text: str, table_parts: tuple[str, ...], key: str) -> _AssignmentHit | None:
    """Locate a simple ``key = <scalar>`` under ``[table_parts]``; ignore strings/comments."""
    n = len(text)
    i = 0
    current: tuple[str, ...] = ()
    in_aot = False
    hit: _AssignmentHit | None = None

    while i < n:
        # skip UTF-8 BOM
        if i == 0 and text.startswith("\ufeff"):
            i = 1
            continue
        # newline
        if text[i] in "\r\n":
            i += 1
            continue
        # whitespace at line start
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            break
        if text[i] == "#":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        # header?
        if text[i] == "[":
            line_end = i
            while line_end < n and text[line_end] not in "\r\n":
                line_end += 1
            line = text[i:line_end]
            # ensure this is a real header, not leftover junk: no string open before [
            parsed = _parse_header(line)
            if parsed is None:
                raise EditError(f"unreadable header near offset {i}")
            kind, parts = parsed
            current = parts
            in_aot = kind == "aot"
            i = line_end
            continue
        # potential key
        if not _is_bare_key_char(text[i]) and text[i] not in "\"'":
            # unknown line content: skip to EOL (may be blank already handled)
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        key_start = i
        # read key (bare or quoted single-segment only)
        if text[i] in "\"'":
            if text.startswith('"""', i) or text.startswith("'''", i):
                raise EditError("multiline key names are not supported")
            key_end = _scan_string_end(text, i)
            try:
                key_name = tomllib.loads(f"_ = {text[i:key_end]}\n")["_"]
            except tomllib.TOMLDecodeError as e:
                raise EditError(f"invalid quoted key: {e}") from e
            if not isinstance(key_name, str):
                raise EditError("key name must be a string")
            j = key_end
        else:
            j = i
            while j < n and _is_bare_key_char(text[j]):
                j += 1
            key_name = text[i:j]
            # dotted bare keys at table body: lead.fable_lead = ...
            if j < n and text[j] == ".":
                # dotted key assignment — unsupported for editing
                while j < n and text[j] not in "\r\n":
                    j += 1
                # if this dotted key matches our full path under root table, refuse explicitly later via miss+present
                i = j
                continue
        while j < n and text[j] in " \t":
            j += 1
        if j >= n or text[j] != "=":
            # not an assignment (e.g. stray token); skip line
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        j += 1  # skip =
        while j < n and text[j] in " \t":
            j += 1
        value_start = j
        # Refuse editing inside array-of-tables entirely when the current header is AoT.
        if in_aot:
            try:
                value_end = _scan_scalar_value_end(text, value_start)
            except EditError:
                # skip complex AoT value lines
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            i = value_end
            while i < n and text[i] not in "\r\n":
                if text[i] == "#":
                    while i < n and text[i] not in "\r\n":
                        i += 1
                    break
                if text[i] not in " \t":
                    raise EditError("trailing tokens after value are not supported")
                i += 1
            continue
        if current == table_parts and key_name == key:
            if value_start < n and text[value_start] == "[":
                value_end = _skip_brackets(text, value_start)
            else:
                value_end = _scan_scalar_value_end(text, value_start)
            # ensure rest of line is only whitespace/comment
            k = value_end
            while k < n and text[k] in " \t":
                k += 1
            if k < n and text[k] not in "#\r\n":
                raise EditError(
                    f"unsupported trailing content after {key!r} assignment"
                )
            if hit is not None:
                raise EditError(
                    f"duplicate assignment for {'.'.join(table_parts + (key,))!r}"
                )
            hit = _AssignmentHit(
                key_start=key_start,
                value_start=value_start,
                value_end=value_end,
                table_parts=table_parts,
                key=key,
            )
            i = k
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        # skip this assignment's value (may be complex) without editing
        try:
            value_end = _scan_scalar_value_end(text, value_start)
            i = value_end
            while i < n and text[i] not in "\r\n":
                if text[i] == "#":
                    while i < n and text[i] not in "\r\n":
                        i += 1
                    break
                i += 1
        except EditError:
            # complex value (array/inline/multiline): skip whole line region carefully
            # For multiline strings starting here, advance via string scanner.
            while value_start < n and text[value_start] in " \t":
                value_start += 1
            if value_start < n and (
                text.startswith('"""', value_start) or text.startswith("'''", value_start)
                or text[value_start] in "\"'"
            ):
                try:
                    i = _scan_string_end(text, value_start)
                except EditError:
                    raise
                while i < n and text[i] not in "\r\n":
                    i += 1
            elif value_start < n and text[value_start] in "[{":
                # bracket matching outside strings/comments
                i = _skip_brackets(text, value_start)
                while i < n and text[i] not in "\r\n":
                    if text[i] == "#":
                        while i < n and text[i] not in "\r\n":
                            i += 1
                        break
                    i += 1
            else:
                while i < n and text[i] not in "\r\n":
                    i += 1
    return hit


def _skip_brackets(text: str, start: int) -> int:
    """Skip an inline array/table starting at start; respect strings and nesting."""
    n = len(text)
    stack = [text[start]]
    i = start + 1
    while i < n and stack:
        ch = text[i]
        if ch in "\"'":
            i = _scan_string_end(text, i)
            continue
        if ch == "#":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch in "[{":
            stack.append(ch)
            i += 1
            continue
        if ch in "]}":
            open_ch = stack.pop()
            if (open_ch, ch) not in (("[", "]"), ("{", "}")):
                raise EditError("mismatched brackets in TOML value")
            i += 1
            continue
        i += 1
    if stack:
        raise EditError("unterminated array/inline table")
    return i


def find_table_insert_point(text: str, table_parts: tuple[str, ...]) -> tuple[int, bool]:
    """Return (offset, table_exists). Offset is where a new ``key = value`` line may be inserted."""
    n = len(text)
    if not table_parts:
        # Root table: new keys must precede the first header.
        i = 0
        while i < n:
            while i < n and text[i] in " \t\r\n\ufeff":
                i += 1
            if i < n and text[i] == "[":
                return i, True
            while i < n and text[i] not in "\r\n":
                if text[i] == "#":
                    while i < n and text[i] not in "\r\n":
                        i += 1
                elif text[i] in "\"'":
                    i = _scan_string_end(text, i)
                elif text[i] == "[":
                    i = _skip_brackets(text, i)
                else:
                    i += 1
        return n, True
    i = 0
    current: tuple[str, ...] = ()
    in_aot = False
    table_start: int | None = None
    last_content_end: int | None = None
    next_header_start: int | None = None

    while i < n:
        if i == 0 and text.startswith("\ufeff"):
            i = 1
            continue
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            break
        if text[i] in "\r\n":
            i += 1
            continue
        if text[i] == "#":
            line_start = i
            while i < n and text[i] not in "\r\n":
                i += 1
            if current == table_parts and not in_aot and table_start is not None:
                last_content_end = i
            continue
        if text[i] == "[":
            line_start = i
            line_end = i
            while line_end < n and text[line_end] not in "\r\n":
                line_end += 1
            parsed = _parse_header(text[line_start:line_end])
            if parsed is None:
                raise EditError(f"unreadable header near offset {line_start}")
            kind, parts = parsed
            if table_start is not None and next_header_start is None and current == table_parts:
                next_header_start = line_start
            current = parts
            in_aot = kind == "aot"
            if parts == table_parts and kind == "table":
                table_start = line_end
                last_content_end = line_end
                next_header_start = None
            i = line_end
            continue
        # body line
        line_start = i
        # advance over assignment / content
        while i < n and text[i] not in "\r\n":
            # handle strings so fake headers in multiline content don't matter for insert
            if text[i] in "\"'":
                i = _scan_string_end(text, i)
                continue
            if text[i] == "#":
                while i < n and text[i] not in "\r\n":
                    i += 1
                break
            i += 1
        if current == table_parts and not in_aot and table_start is not None:
            last_content_end = i
    if table_start is None:
        return len(text), False
    if next_header_start is not None:
        # insert just before the next header; prefer after last content
        return last_content_end if last_content_end is not None else next_header_start, True
    return (last_content_end if last_content_end is not None else len(text)), True


def apply_scalar_edit(text: str, file_parts: tuple[str, ...], value: Any) -> str:
    """Return new file text with exactly one scalar path set, comments preserved."""
    if not file_parts:
        raise EditError("empty file path")
    table_parts = file_parts[:-1]
    key = file_parts[-1]

    encoded = encode_toml_value(value)
    hit = find_scalar_assignment(text, table_parts, key)
    if hit is not None:
        return text[: hit.value_start] + encoded + text[hit.value_end :]

    # Insert
    insert_at, exists = find_table_insert_point(text, table_parts)
    line = f"{_encode_key(key)} = {encoded}"
    if exists:
        prefix = text[:insert_at]
        suffix = text[insert_at:]
        # ensure newline before insertion when needed
        needs_nl_before = bool(prefix) and not prefix.endswith(("\n", "\r"))
        chunk = ("\n" if needs_nl_before else "") + line + "\n"
        # if suffix starts mid-file before a header, keep separation
        return prefix + chunk + suffix

    # Create table header(s) at EOF
    header = ".".join(_encode_key(part) for part in table_parts)
    parts_out: list[str] = []
    body = text
    if body and not body.endswith("\n"):
        body += "\n"
    if body and not body.endswith("\n\n"):
        # one blank line before a new table when file non-empty
        if not body.endswith("\n"):
            body += "\n"
        elif not body.endswith("\n\n") and body != "\n":
            body += "\n"
    if header:
        parts_out.append(f"[{header}]")
    parts_out.append(line)
    addition = "\n".join(parts_out) + "\n"
    return body + addition


def _read_text_regular(path: Path) -> tuple[str, int]:
    """Read a regular file; refuse symlinks and nonregular paths. Returns (text, mode)."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as e:
        raise EditError(f"{path}: {e.strerror or e}") from e
    if stat.S_ISLNK(st.st_mode):
        raise EditError(f"{path}: refuses to edit through a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise EditError(f"{path}: not a regular file")
    try:
        data = path.read_bytes()
    except OSError as e:
        raise EditError(f"{path}: {e.strerror or e}") from e
    # Reject NULs; TOML is text.
    if b"\x00" in data:
        raise EditError(f"{path}: binary file with NUL bytes")
    return data.decode("utf-8"), stat.S_IMODE(st.st_mode)


def _parse_file_tree(text: str, path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise EditError(f"{path}: not valid TOML after edit planning ({e})") from e
    if not isinstance(data, dict):
        raise EditError(f"{path}: root must be a table")
    return data


def _rows_at(data: dict[str, Any], aot: tuple[str, ...]) -> list[Any]:
    cur: Any = data
    for part in aot:
        if not isinstance(cur, dict) or part not in cur:
            return []
        cur = cur[part]
    if not isinstance(cur, list):
        raise EditError(f"{'.'.join(aot)} must be an array of tables")
    return cur


def _row_index(data: dict[str, Any], row: tuple[tuple[str, ...], str, str]) -> int:
    aot, ident_key, ident = row
    matches = [i for i, r in enumerate(_rows_at(data, aot))
               if isinstance(r, dict) and r.get(ident_key) == ident]
    if len(matches) != 1:
        raise EditError(f"{'.'.join(aot)} {ident_key}={ident!r}: exactly one existing row identity required")
    return matches[0]


def _row_edit(text: str, aot: tuple[str, ...], index: int, field: str, value: Any) -> str:
    """Edit one existing ``[[aot]]`` row body through a synthetic ordinary table.

    Lexical boundaries reuse the scalar scanner's string/bracket skipping. The
    caller additionally proves the complete parsed tree changed only one indexed
    field; no public array reordering or row creation is enabled here.
    """
    headers = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n\ufeff":
            i += 1
        if i >= len(text):
            break
        start = i
        if text[i] == "[":
            end = text.find("\n", i)
            end = len(text) if end == -1 else end
            parsed = _parse_header(text[i:end])
            if parsed is None:
                raise EditError("unsupported catalog header")
            headers.append((start, end, parsed))
            i = end
        else:
            while i < len(text) and text[i] not in "\r\n":
                if text[i] == "#":
                    end = text.find("\n", i)
                    i = len(text) if end == -1 else end
                elif text[i] in "\"'":
                    i = _scan_string_end(text, i)
                elif text[i] in "[{":
                    i = _skip_brackets(text, i)
                else:
                    i += 1
    rows = [i for i, (_, _, parsed) in enumerate(headers) if parsed == ("aot", aot)]
    if index >= len(rows):
        raise EditError("row could not be located in supported TOML text")
    header_index = rows[index]
    start, body_start, _ = headers[header_index]
    end = headers[header_index + 1][0] if header_index + 1 < len(headers) else len(text)
    synthetic = "[__ade_row__]"
    edited = apply_scalar_edit(synthetic + text[body_start:end], ("__ade_row__", field), value)
    if not edited.startswith(synthetic):
        raise EditError("row scalar verification failed")
    return text[:body_start] + edited[len(synthetic):] + text[end:]


def _append_legacy_key_row(text: str, name: str) -> str:
    """Append ``[[key]]`` carrying only its identity (the one supported registry creation)."""
    if not KEY_NAME_RE.fullmatch(name):
        raise EditError(f"key identity {name!r}: must match {KEY_NAME_RE.pattern}")
    body = text if not text or text.endswith("\n") else text + "\n"
    return body + ("\n" if body else "") + f"[[key]]\nname = {encode_toml_scalar(name)}\n"


def _metadata_domain(parts: tuple[str, ...]) -> frozenset[str] | None:
    if parts[0] == "context_budget":
        return ac.CONTEXT_BUDGET_DOMAINS
    if parts[0] in {"keys", "install"}:
        return ac.CATALOG_DOMAINS
    return None


def _validate_metadata_effective(data: dict[str, Any], *, root: Path, domains: frozenset[str]) -> None:
    if domains == ac.CONTEXT_BUDGET_DOMAINS:
        ac.context_budget_config(data)
    else:
        try:
            raw = catalog.catalog_from_effective(data)
            ac.validate_tree(raw, ac.read_catalog_schema(root), label="effective install catalog")
            catalog.validate_catalog_semantics(raw, path=Path("effective install catalog"))
        except catalog.CatalogValidationError as error:
            raise EditError(str(error)) from error


def _validate_metadata_candidate(after: dict[str, Any], target: SetTarget, *, root: Path,
                                 home: Path, domains: frozenset[str]) -> None:
    effective = ac.load_effective(root=root, home=home, domains=domains,
                                  _candidate=(target.path, after))
    _validate_metadata_effective(effective.data, root=root, domains=domains)


def validate_target_tree(data: dict[str, Any], target: SetTarget, *, root: Path) -> None:
    """Validate the post-edit file against the real source constraints for that kind."""
    schema = ac.read_schema(ac.default_schema_path(root))
    if target.kind == "local":
        ac.require_schema_version(data, target.path, required=False)
        ac.validate_tree(data, schema, label=str(target.path), partial=True)
        ac.validate_context_budget(data, path=target.path)
        ac._validate_catalog_domains(data, target.path)
        ac.reject_duplicate_services(data.get("service"), label=str(target.path))
        return
    if target.kind == "unified":
        ac.require_schema_version(data, target.path, required=True)
        ac.validate_tree(data, schema, label=str(target.path))
        ac.validate_context_budget(data, path=target.path)
        ac._validate_catalog_domains(data, target.path)
        ac.reject_duplicate_services(data.get("service"), label=str(target.path))
        return
    if target.kind == "legacy_context":
        projected = {"context_budget": data}
        ac.validate_context_budget(projected, path=target.path)
        return
    if target.kind in {"legacy_key", "legacy_install"}:
        ac.require_schema_version(data, target.path, required=True)
        ac.validate_tree(data, ac.read_catalog_schema(root), label=str(target.path))
        try:
            catalog.validate_catalog_semantics(data, path=target.path)
        except catalog.CatalogValidationError as error:
            raise EditError(str(error)) from error
        return
    if target.kind == "legacy_routing":
        # Full legacy shape, including unrelated [[service]] entries.
        ac.validate_legacy_routing_shape(data, target.path)
        ac.reject_duplicate_services(data.get("service"), label=str(target.path))
        return
    if target.kind == "legacy_gates":
        # Must remain a mapping; frontier numbers when present must be numeric (ade_gates parity).
        if not isinstance(data, dict):
            raise EditError(f"{target.path}: root must be a table")
        frontier = data.get("frontier")
        if frontier is not None:
            if not isinstance(frontier, dict):
                raise EditError(f"{target.path}: [frontier] must be a table")
            for key, val in frontier.items():
                if not ac.is_num(val):
                    raise EditError(
                        f"{target.path}: [frontier].{key} must be a number, got {val!r}"
                    )
        floors = data.get("floors")
        if floors is not None and not isinstance(floors, dict):
            raise EditError(f"{target.path}: [floors] must be a table")
        return
    raise EditError(f"unknown target kind {target.kind!r}")


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _atomic_replace(path: Path, text: str, *, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        else:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _check_value_shape(parts: tuple[str, ...], value: Any) -> None:
    """Type the value for its path; arrays only where the allowlist names them."""
    if isinstance(value, dict):
        raise EditError("VALUE must be a scalar or an array of strings")
    is_array_path = (
        parts == ("context_budget", "dirs")
        or (parts[0] == "keys" and len(parts) == 3 and parts[2] in KEY_ARRAY_FIELDS)
        or (parts[0] == "install" and len(parts) == 4 and parts[1] == "component"
            and parts[3] in COMPONENT_ARRAY_FIELDS)
        or (parts[0] == "install" and len(parts) == 4 and parts[1] == "jobs" and parts[3] in JOB_ARRAY_FIELDS)
    )
    if isinstance(value, list):
        if not is_array_path:
            raise EditError("VALUE must be a scalar (arrays are only accepted for the documented array fields)")
        _check_string_array(value)
        return
    if is_array_path:
        raise EditError(f"{'.'.join(parts)} requires an array of non-empty strings")
    if parts[0] == "context_budget" and not ac.is_num(value):
        raise EditError("context budget values must be finite numeric scalars")
    if parts[0] == "keys" and not isinstance(value, str):
        raise EditError("key metadata values must be strings")
    if parts[0] == "install" and parts[3] in CHOICE_FIELDS and not isinstance(value, bool):
        raise EditError("install chosen must be true or false")


def _install_row_exists(current: dict[str, Any], parts: tuple[str, ...]) -> bool:
    install = current.get("install", {})
    rows = install.get("component" if parts[1] == "component" else "jobs", []) if isinstance(install, dict) else []
    ident_key = INSTALL_ROWS[parts[1]][1]
    return any(isinstance(r, dict) and r.get(ident_key) == parts[2] for r in rows)


def set_scalar(
    dotted: str,
    value: Any,
    *,
    target: str = "local",
    root: Path | None = None,
    home: Path | None = None,
    dry_run: bool = False,
    create_key: bool = False,
) -> SetResult:
    """Set one scalar (or documented string-array) path. Default target is local (per-machine).

    ``create_key`` permits adding a new registry identity (``keys.NAME.FIELD``): a new
    ``[keys.NAME]`` table, or an appended ``[[key]]`` row in the legacy catalog.
    """
    root = (root or ac.repo_root_from_here()).resolve()
    home_path = (home if home is not None else Path.home()).resolve()
    resolved = resolve_set_target(dotted, target=target, root=root, home=home_path)
    parts = split_dotted_path(dotted)
    domains = _metadata_domain(parts)
    _check_value_shape(parts, value)
    if create_key and parts[0] != "keys":
        raise EditError("--create-key applies only to keys.NAME.FIELD paths")
    creating = False

    with _file_lock(resolved.path):
        if parts[0] in {"keys", "install"}:
            current = ac.load_effective(root=root, home=home_path, domains=ac.CATALOG_DOMAINS)
            _validate_metadata_effective(current.data, root=root, domains=ac.CATALOG_DOMAINS)
            if parts[0] == "keys" and parts[1] not in current.data.get("keys", {}):
                if not create_key:
                    raise EditError(
                        f"key {parts[1]!r}: creating a new registry identity needs --create-key"
                    )
                if not KEY_NAME_RE.fullmatch(parts[1]):
                    raise EditError(f"key identity {parts[1]!r}: must match {KEY_NAME_RE.pattern}")
                creating = True
            if parts[0] == "install" and not _install_row_exists(current.data, parts):
                raise EditError(f"{dotted}: creating new install rows is not supported")
        mode: int | None = None
        exists = ac.input_present(resolved.path)
        if not exists:
            if resolved.kind != "local":
                raise EditError(
                    f"{resolved.path}: refuses to create a new {resolved.kind} file "
                    "(local is the only create-on-set target; repo set edits the "
                    "current source of that domain)"
                )
            text_before = ""
            before_tree: dict[str, Any] = {}
            before_value = None
            missing_before = True
        else:
            text_before, mode = _read_text_regular(resolved.path)
            before_tree = _parse_file_tree(text_before, resolved.path)
            if creating and resolved.row is not None:
                # Legacy registry: append the identity row first, then edit it like any existing row.
                text_before = _append_legacy_key_row(text_before, parts[1])
                before_tree = _parse_file_tree(text_before, resolved.path)
            try:
                if resolved.row is not None:
                    before_value = _rows_at(before_tree, resolved.row[0])[
                        _row_index(before_tree, resolved.row)][resolved.file_parts[0]]
                else:
                    before_value = get_from_tree(before_tree, resolved.file_parts)
                missing_before = False
            except KeyError:
                before_value = None
                missing_before = True
            if not missing_before and isinstance(before_value, dict):
                raise EditError(f"{dotted}: existing value is a table; scalar set refuses to replace it")
            if not missing_before and isinstance(before_value, list) and not isinstance(value, list):
                raise EditError(f"{dotted}: existing value is an array; scalar set refuses to replace it")

        if not missing_before and values_equal(before_value, value):
            if domains is not None:
                validate_target_tree(before_tree, resolved, root=root)
                _validate_metadata_candidate(before_tree, resolved, root=root, home=home_path, domains=domains)
            return SetResult(
                target=resolved,
                before=before_value,
                after=value,
                changed=False,
                dry_run=dry_run,
                adoption=ADOPTION_RECORDED_ONLY,
                adoption_note=ADOPTION_NOTE,
                text_before=text_before,
                text_after=text_before,
            )

        # If the value exists in the parsed tree but we could not find a simple
        # assignment (dotted key / inline / etc.), refuse rather than double-write.
        if not missing_before and resolved.row is None:
            hit = find_scalar_assignment(
                text_before, resolved.file_parts[:-1], resolved.file_parts[-1]
            )
            if hit is None:
                raise EditError(
                    f"{dotted}: present in parsed TOML but not as a simple "
                    "table key assignment; refused"
                )

        if resolved.row is not None:
            index = _row_index(before_tree, resolved.row)
            text_after = _row_edit(text_before, resolved.row[0], index, resolved.file_parts[0], value)
        else:
            text_after = apply_scalar_edit(text_before, resolved.file_parts, value)
        after_tree = _parse_file_tree(text_after, resolved.path)
        if resolved.row is not None:
            expected = copy.deepcopy(before_tree)
            _rows_at(expected, resolved.row[0])[_row_index(expected, resolved.row)][resolved.file_parts[0]] = (
                copy.deepcopy(value))
        else:
            expected = set_in_tree(before_tree, resolved.file_parts, value)
        if not values_equal(after_tree, expected):
            raise EditError(
                f"{dotted}: edit verification failed "
                "(parsed tree is not exactly the requested change)"
            )
        validate_target_tree(after_tree, resolved, root=root)
        if domains is not None:
            _validate_metadata_candidate(after_tree, resolved, root=root, home=home_path, domains=domains)

        if not dry_run:
            _atomic_replace(resolved.path, text_after, mode=mode)
            # Re-read proof for non-create writes.
            text_read, _ = _read_text_regular(resolved.path)
            if text_read != text_after:
                raise EditError(f"{resolved.path}: read-back mismatch after write")

        return SetResult(
            target=resolved,
            before=before_value,
            after=value,
            changed=True,
            dry_run=dry_run,
            adoption=ADOPTION_RECORDED_ONLY,
            adoption_note=ADOPTION_NOTE,
            text_before=text_before,
            text_after=text_after,
        )
