"""model_tiers: roles → concrete models per vendor (config/model-tiers.toml).

Design: docs/history/model-tiers-design.md (S2 loader + S4 promote core).
Public API used by bin/ade-model-tiers and bin/route_agent.py:

  load(path=None) -> Tiers
  from_dict(data, ...) -> Tiers    # pure effective-tree consumer; legacy load is unchanged
  resolve(vendor, role, route=None) -> str
  classify(model) -> (vendor|None, role|None, status)
  frontier_tokens() -> list[str]
  rank(vendor) -> int
  ranked_frontier(n) -> (vendor, id)
  pool(vendor, role) -> dict|None
  display(vendor, role) -> str
  promote(...) -> PromoteResult
  set_role(...) -> PromoteResult
  dump_toml(data) -> str
  atomic_write(path, text)

DEFAULTS mirror today's shipped file; a missing/unreadable file falls back to
DEFAULTS (same fail-safe shape as ade_gates). Tests fail when file and DEFAULTS drift.
No secrets: the file and CLI argv never carry credentials.
"""
from __future__ import annotations

import copy
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import tomllib

ROLES: tuple[str, ...] = ("frontier", "judgment", "everyday", "bulk")
SCHEMA = 1

# Fail-safe copy of today's table (2026-11-09). Keep in sync with config/model-tiers.toml.
DEFAULTS: dict[str, Any] = {
    "meta": {"schema": SCHEMA, "updated": "2026-11-09"},
    "rank": {
        "order": ["claude", "codex"],
        "since": "2026-10-26",
        "reason": (
            "djbclark 2026-10-26: Fable is the top frontier coding model; "
            "codex astra is the acclaimed second"
        ),
    },
    "vendor": {
        "claude": {
            "family": (
                r"^(anthropic/|claude/|omp/anthropic/)?"
                r"(claude-[a-z]+-[0-9][\w.\[\]-]*|opus|sonnet|haiku|fable)$"
            ),
            "roles": {
                "frontier": "claude-fable-5-1",
                "judgment": "claude-opus-5-5",
                "everyday": "claude-sonnet-5-5",
                "bulk": "claude-haiku-5-5",
            },
            "spell": {
                "claude": "{alias}",
                "claude-code": "{alias}",
                "paseo": "{id}",
                "omp": "anthropic/{id}",
                "agy": "{id}",
                "cursor": "{id}",
                "copilot": "{id_dotted}",
            },
            "cascade": 2,
            "pools": {
                "frontier": {
                    "pool_family": "fable",
                    "quota_scope": "model_sublimit",
                    "label_has": "Fable",
                }
            },
        },
        "codex": {
            "family": r"^(opencode-go/)?gpt-[0-9][\w.-]*$",
            "roles": {
                "frontier": "gpt-6-astra",
                "judgment": "gpt-6.1-sol",
                "everyday": "gpt-6.1-sol",
                "bulk": "gpt-6-luna",
            },
            "spell": {"codex": "{id}", "opencode-go": "opencode-go/{id}"},
            "cascade": 2,
            "pools": {},
        },
    },
    "model": {
        "claude-fable-5-1": {
            "vendor": "claude",
            "alias": "fable",
            "display": "Fable 5.1",
        },
        "claude-opus-5-5": {
            "vendor": "claude",
            "alias": "opus",
            "display": "Opus 5.5",
        },
        "claude-sonnet-5-5": {
            "vendor": "claude",
            "alias": "sonnet",
            "display": "Sonnet 5.5",
            "spellings": {"copilot": "claude-sonnet-5.5"},
        },
        "claude-haiku-5-5": {
            "vendor": "claude",
            "alias": "haiku",
            "display": "Haiku 5.5",
        },
        "gpt-6-astra": {"vendor": "codex", "display": "GPT-6 Astra"},
        "gpt-6.1-sol": {"vendor": "codex", "display": "GPT-6.1 Sol"},
        "gpt-6-luna": {"vendor": "codex", "display": "GPT-6 Luna"},
    },
    "former": {},
}

_LOGGED: set[str] = set()
_CACHE: dict[str, "Tiers"] = {}


class TiersError(ValueError):
    """Invalid model-tiers.toml, unknown vendor/role, or refused promote."""


@dataclass
class Tiers:
    """Parsed, validated tiers plus provenance."""

    data: dict[str, Any]
    path: Path | None = None
    source: str = "code"  # "file" | "code" | "effective"
    error: str | None = None

    def vendors(self) -> list[str]:
        return list((self.data.get("vendor") or {}).keys())

    def vendor(self, name: str) -> dict[str, Any]:
        v = (self.data.get("vendor") or {}).get(name)
        if not isinstance(v, dict):
            raise TiersError(f"unknown vendor {name!r}")
        return v

    def role_id(self, vendor: str, role: str) -> str:
        if role not in ROLES:
            raise TiersError(f"unknown role {role!r}; want one of {ROLES}")
        roles = self.vendor(vendor).get("roles") or {}
        mid = roles.get(role)
        if not isinstance(mid, str) or not mid:
            raise TiersError(f"vendor {vendor!r} has no id for role {role!r}")
        return mid


@dataclass(frozen=True)
class PromoteResult:
    before: dict[str, Any]
    after: dict[str, Any]
    text: str
    path: Path
    dry_run: bool
    changed: bool
    notes: list[str] = field(default_factory=list)


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_path(root: Path | None = None) -> Path:
    env = os.environ.get("MODEL_TIERS_TOML")
    if env:
        return Path(env)
    return (root or repo_root_from_here()) / "config" / "model-tiers.toml"


def _log_once(msg: str) -> None:
    if msg not in _LOGGED:
        _LOGGED.add(msg)
        print(f"model_tiers: {msg}", file=sys.stderr)


def clear_cache() -> None:
    _CACHE.clear()
    _LOGGED.clear()


def _quote_toml_str(s: str) -> str:
    """Emit a TOML basic string (double-quoted) with escapes."""
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _quote_toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return _quote_toml_str(key)


def _format_inline_table(d: dict[str, Any]) -> str:
    parts: list[str] = []
    for k, v in d.items():
        parts.append(f"{_quote_toml_key(str(k))} = {_format_value(v)}")
    return "{ " + ", ".join(parts) + " }"


def _format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return _quote_toml_str(v)
    if isinstance(v, list):
        return "[ " + ", ".join(_format_value(x) for x in v) + " ]"
    if isinstance(v, dict):
        return _format_inline_table(v)
    raise TiersError(f"cannot emit TOML for {type(v).__name__}")


def dump_toml(data: dict[str, Any]) -> str:
    """Deterministic TOML for our known shape (no secrets)."""
    lines: list[str] = [
        "# Model tiers: roles → concrete models per vendor "
        "(docs/history/model-tiers-design.md).",
        "# Regenerated by bin/ade-model-tiers; merge by PR. No secrets.",
        "",
    ]
    meta = data.get("meta") or {}
    lines.append("[meta]")
    lines.append(f"schema = {int(meta.get('schema', SCHEMA))}")
    lines.append(f"updated = {_quote_toml_str(str(meta.get('updated', '')))}")
    lines.append("")

    rank = data.get("rank") or {}
    lines.append("[rank]")
    order = list(rank.get("order") or [])
    lines.append(f"order = {_format_value(order)}")
    if rank.get("since"):
        lines.append(f"since = {_quote_toml_str(str(rank['since']))}")
    if rank.get("reason"):
        lines.append(f"reason = {_quote_toml_str(str(rank['reason']))}")
    lines.append("")

    vendors = data.get("vendor") or {}
    for vname, vbody in vendors.items():
        if not isinstance(vbody, dict):
            continue
        lines.append(f"[vendor.{_quote_toml_key(str(vname))}]")
        if "family" in vbody:
            lines.append(f"family = {_quote_toml_str(str(vbody['family']))}")
        if "roles" in vbody:
            lines.append(f"roles = {_format_inline_table(dict(vbody['roles']))}")
        if "spell" in vbody:
            lines.append(f"spell = {_format_inline_table(dict(vbody['spell']))}")
        if "cascade" in vbody:
            lines.append(f"cascade = {int(vbody['cascade'])}")
        pools = vbody.get("pools")
        if pools is None:
            pools = {}
        lines.append(f"pools = {_format_inline_table(dict(pools))}")
        lines.append("")

    models = data.get("model") or {}
    for mid, mbody in models.items():
        if not isinstance(mbody, dict):
            continue
        lines.append(f"[model.{_quote_toml_str(str(mid))}]")
        for key in ("vendor", "alias", "display"):
            if key in mbody and mbody[key] is not None:
                lines.append(f"{key} = {_quote_toml_str(str(mbody[key]))}")
        if isinstance(mbody.get("spellings"), dict) and mbody["spellings"]:
            lines.append(
                f"spellings = {_format_inline_table(dict(mbody['spellings']))}"
            )
        lines.append("")

    former = data.get("former") or {}
    lines.append("[former]")
    if not former:
        lines.append("")
    else:
        for mid, fbody in former.items():
            if not isinstance(fbody, dict):
                continue
            # Nested former entry as [former."id"] would need another table;
            # store as an inline table assignment under [former].
            lines.append(
                f"{_quote_toml_str(str(mid))} = {_format_inline_table(dict(fbody))}"
            )
        lines.append("")
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    """Temp file beside the target, fsync, os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            os.chmod(tmp, mode)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _validate(data: dict[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TiersError(f"{label}: root must be a table")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise TiersError(f"{label}: missing [meta]")
    schema = meta.get("schema")
    if schema != SCHEMA:
        raise TiersError(f"{label}: unsupported schema {schema!r} (want {SCHEMA})")
    rank = data.get("rank")
    if not isinstance(rank, dict) or not isinstance(rank.get("order"), list) or not rank["order"]:
        raise TiersError(f"{label}: [rank].order must be a non-empty array")
    for name in rank["order"]:
        if not isinstance(name, str) or not name:
            raise TiersError(f"{label}: [rank].order entries must be non-empty strings")
    vendors = data.get("vendor")
    if not isinstance(vendors, dict) or not vendors:
        raise TiersError(f"{label}: missing [vendor.*]")
    for vname in rank["order"]:
        if vname not in vendors:
            raise TiersError(f"{label}: rank names unknown vendor {vname!r}")
    models = data.get("model")
    if not isinstance(models, dict):
        raise TiersError(f"{label}: [model] must be a table")
    for vname, vbody in vendors.items():
        if not isinstance(vbody, dict):
            raise TiersError(f"{label}: [vendor.{vname}] must be a table")
        family = vbody.get("family")
        if not isinstance(family, str) or not family:
            raise TiersError(f"{label}: [vendor.{vname}].family must be a non-empty string")
        try:
            re.compile(family)
        except re.error as e:
            raise TiersError(f"{label}: [vendor.{vname}].family: {e}") from e
        roles = vbody.get("roles")
        if not isinstance(roles, dict):
            raise TiersError(f"{label}: [vendor.{vname}].roles must be a table")
        for role in ROLES:
            mid = roles.get(role)
            if not isinstance(mid, str) or not mid:
                raise TiersError(
                    f"{label}: [vendor.{vname}].roles.{role} must be a non-empty string"
                )
            if mid not in models:
                raise TiersError(
                    f"{label}: role {vname}/{role} id {mid!r} has no [model] entry"
                )
        cascade = vbody.get("cascade", 2)
        if not isinstance(cascade, int) or isinstance(cascade, bool) or not 1 <= cascade <= 4:
            raise TiersError(
                f"{label}: [vendor.{vname}].cascade must be an int 1..4, got {cascade!r}"
            )
        pools = vbody.get("pools", {})
        if pools is None:
            pools = {}
        if not isinstance(pools, dict):
            raise TiersError(f"{label}: [vendor.{vname}].pools must be a table")
        for role, pbody in pools.items():
            if role not in ROLES:
                raise TiersError(f"{label}: pools key {role!r} is not a role")
            if not isinstance(pbody, dict):
                raise TiersError(f"{label}: pools.{role} must be a table")
    for mid, mbody in models.items():
        if not isinstance(mbody, dict):
            raise TiersError(f"{label}: [model.{mid}] must be a table")
        vend = mbody.get("vendor")
        if vend not in vendors:
            raise TiersError(f"{label}: [model.{mid}].vendor {vend!r} unknown")
    former = data.get("former", {})
    if former is None:
        former = {}
    if not isinstance(former, dict):
        raise TiersError(f"{label}: [former] must be a table")
    out = copy.deepcopy(data)
    out.setdefault("former", {})
    return out


def _read_toml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None, f"{path}: not a regular file"
            return tomllib.load(fh), None
    except OSError as e:
        return None, f"{path}: {e.strerror or e}"
    except (tomllib.TOMLDecodeError, ValueError, RecursionError) as e:
        return None, f"{path}: not valid TOML ({e})"


def from_dict(
    data: dict[str, Any], *, path: Path | None = None, source: str = "effective",
    error: str | None = None,
) -> Tiers:
    """Validate an effective tier tree without file reads or a default fallback.

    Only canonical tier tables are inputs. Report fields such as source/path,
    frontier_tokens and sublimit_families are never config authority. Preserve
    legacy load() behavior; effective consumers additionally need the spell map
    and pool_family types their helpers consume to be safe after overlays.
    """
    label = f"effective model tiers ({path})" if path else "effective model tiers"
    if not isinstance(data, dict):
        raise TiersError(f"{label}: root must be a table")
    raw = {key: data[key] for key in ("meta", "rank", "vendor", "model", "former") if key in data}
    validated = _validate(raw, label=label)
    for vendor, body in validated["vendor"].items():
        spell = body.get("spell", {})
        if not isinstance(spell, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in spell.items()
        ):
            raise TiersError(f"{label}: vendor.{vendor}.spell must be a string map")
        for role, pool_body in (body.get("pools") or {}).items():
            family = pool_body.get("pool_family")
            if family is not None and (not isinstance(family, str) or not family):
                raise TiersError(f"{label}: vendor.{vendor}.pools.{role}.pool_family must be a non-empty string")
    tiers = Tiers(data=validated, path=path, source=source, error=error)
    # Derive before a runtime consumer publishes any state.
    frontier_tokens(tiers)
    sublimit_families(tiers)
    return tiers


def load(path: Path | str | None = None, *, use_cache: bool = True) -> Tiers:
    """Load and validate tiers. Missing/bad file → DEFAULTS (logged once)."""
    p = Path(path) if path is not None else default_path()
    key = str(p)
    if use_cache and key in _CACHE:
        return _CACHE[key]
    raw, err = _read_toml(p)
    if err is not None or raw is None:
        _log_once(f"falling back to DEFAULTS ({err or 'empty'})")
        tiers = Tiers(data=copy.deepcopy(DEFAULTS), path=p, source="code", error=err)
    else:
        try:
            data = _validate(raw, label=str(p))
            tiers = Tiers(data=data, path=p, source="file", error=None)
        except TiersError as e:
            _log_once(f"falling back to DEFAULTS ({e})")
            tiers = Tiers(
                data=copy.deepcopy(DEFAULTS), path=p, source="code", error=str(e)
            )
    if use_cache:
        _CACHE[key] = tiers
    return tiers


def defaults_match_file(path: Path | None = None) -> list[str]:
    """Return drift messages when DEFAULTS and the shipped file disagree on roles/rank/models."""
    p = path or default_path()
    raw, err = _read_toml(p)
    if err or raw is None:
        return [f"cannot read {p}: {err}"]
    try:
        file_data = _validate(raw, label=str(p))
    except TiersError as e:
        return [str(e)]
    msgs: list[str] = []
    for vname, vbody in DEFAULTS["vendor"].items():
        fvend = (file_data.get("vendor") or {}).get(vname) or {}
        if dict(vbody["roles"]) != dict(fvend.get("roles") or {}):
            msgs.append(f"vendor.{vname}.roles drift: file={fvend.get('roles')} defaults={vbody['roles']}")
        if vbody["family"] != fvend.get("family"):
            msgs.append(f"vendor.{vname}.family drift")
        if int(vbody.get("cascade", 2)) != int(fvend.get("cascade", 2)):
            msgs.append(f"vendor.{vname}.cascade drift")
    if list(DEFAULTS["rank"]["order"]) != list((file_data.get("rank") or {}).get("order") or []):
        msgs.append("rank.order drift")
    for mid, mbody in DEFAULTS["model"].items():
        fm = (file_data.get("model") or {}).get(mid) or {}
        for key in ("vendor", "alias", "display"):
            if mbody.get(key) != fm.get(key):
                msgs.append(f"model.{mid}.{key} drift: file={fm.get(key)!r} defaults={mbody.get(key)!r}")
    return msgs


def _strip_model(raw: str) -> str:
    """Drop effort flags, bracket suffixes like [1m], and surrounding whitespace."""
    s = raw.strip()
    # Drop trailing --effort … / --thinking …
    s = re.split(r"\s+--(?:effort|thinking)\b", s, maxsplit=1)[0].strip()
    # Drop a trailing [suffix]
    s = re.sub(r"\[[^\]]*\]\s*$", "", s).strip()
    return s


def _bare_id(model: str) -> str:
    """Last path segment after route prefixes (anthropic/, omp/anthropic/, opencode-go/)."""
    s = _strip_model(model)
    for prefix in ("omp/anthropic/", "anthropic/", "claude/", "opencode-go/"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    return s


# Trailing hyphenated numeric version: claude-opus-5-5 → prefix claude-opus, ver 5-5.
_ID_VERSION_SUFFIX_RE = re.compile(r"^(?P<prefix>.+?)-(?P<ver>\d+(?:-\d+)*)$")


def _id_dotted(mid: str) -> str:
    """Preserve the model-name prefix; convert only the numeric version suffix to dots.

    ``claude-opus-5-5`` → ``claude-opus-5.5`` (Sonnet's ``claude-sonnet-5.5``
    convention). Must not rewrite name separators (``claude.opus.5-5``).
    """
    m = _ID_VERSION_SUFFIX_RE.fullmatch(mid)
    if not m:
        return mid
    return f"{m.group('prefix')}-{m.group('ver').replace('-', '.')}"


def _alias_owned_by_higher_role(
    t: Tiers, vendor: str, role: str, mid: str, alias: str
) -> bool:
    """True when another current ladder model holds the same alias at a higher role.

    After ``promote`` reuses an alias (e.g. ``fable``), the displaced same-family
    model still lists that alias under ``[model.*]``. Returning the alias for the
    lower role makes judgment fallback keep selecting the new frontier; use the
    canonical id instead. The higher role (earlier in ``ROLES``) keeps the alias.
    """
    alias_l = alias.lower()
    try:
        my_idx = ROLES.index(role)
    except ValueError:
        my_idx = len(ROLES)
    vbody = (t.data.get("vendor") or {}).get(vendor)
    if not isinstance(vbody, dict):
        return False
    roles = vbody.get("roles") or {}
    for i, r in enumerate(ROLES):
        if i >= my_idx:
            break
        other = roles.get(r)
        if not isinstance(other, str) or other == mid:
            continue
        other_alias = ((t.data.get("model") or {}).get(other) or {}).get("alias")
        if isinstance(other_alias, str) and other_alias.lower() == alias_l:
            return True
    return False


def classify(
    model: str, tiers: Tiers | None = None
) -> tuple[str | None, str | None, str]:
    """Return (vendor, role, status) where status is current|former|unknown|untiered."""
    t = tiers or load()
    bare = _bare_id(model)
    low = bare.lower()
    # Exact id or alias hit among current roles.
    for vname, vbody in (t.data.get("vendor") or {}).items():
        roles = vbody.get("roles") or {}
        for role, mid in roles.items():
            if not isinstance(mid, str):
                continue
            if bare == mid or low == mid.lower():
                return vname, role, "current"
            alias = ((t.data.get("model") or {}).get(mid) or {}).get("alias")
            if isinstance(alias, str) and low == alias.lower():
                return vname, role, "current"
    # Former ids.
    for mid, fbody in (t.data.get("former") or {}).items():
        if bare == mid or low == str(mid).lower():
            if isinstance(fbody, dict):
                return (
                    fbody.get("vendor"),
                    fbody.get("last_role"),
                    "former",
                )
    # Family match → unknown-in-family = frontier.
    for vname, vbody in (t.data.get("vendor") or {}).items():
        fam = vbody.get("family")
        if not isinstance(fam, str):
            continue
        if re.fullmatch(fam, bare, flags=re.IGNORECASE) or re.fullmatch(
            fam, _strip_model(model), flags=re.IGNORECASE
        ):
            return vname, "frontier", "unknown"
    return None, None, "untiered"


def resolve(
    vendor: str, role: str, route: str | None = None, tiers: Tiers | None = None
) -> str:
    """Spelling for route, else the alias (claude) / canonical id."""
    t = tiers or load()
    mid = t.role_id(vendor, role)
    mmeta = (t.data.get("model") or {}).get(mid) or {}
    alias = mmeta.get("alias") if isinstance(mmeta.get("alias"), str) else None
    # Shared alias with a higher current role → canonical id for this role.
    if (
        isinstance(alias, str)
        and _alias_owned_by_higher_role(t, vendor, role, mid, alias)
    ):
        alias = None
    id_dotted = _id_dotted(mid)
    # Prefer per-model spelling override.
    if route and isinstance(mmeta.get("spellings"), dict):
        override = mmeta["spellings"].get(route)
        if isinstance(override, str) and override:
            return override
    spell_map = (t.vendor(vendor).get("spell") or {}) if route else {}
    template = spell_map.get(route) if route else None
    if not isinstance(template, str) or not template:
        if alias:
            return alias
        return mid
    return (
        template.replace("{id}", mid)
        .replace("{alias}", alias or mid)
        .replace("{id_dotted}", id_dotted)
    )


def frontier_tokens(tiers: Tiers | None = None) -> list[str]:
    """Every spelling and alias of each vendor's frontier role (for substring gates)."""
    t = tiers or load()
    tokens: list[str] = []
    seen: set[str] = set()

    def add(tok: str) -> None:
        low = tok.lower()
        if low and low not in seen:
            seen.add(low)
            tokens.append(tok)

    for vname in t.vendors():
        mid = t.role_id(vname, "frontier")
        add(mid)
        mmeta = (t.data.get("model") or {}).get(mid) or {}
        if isinstance(mmeta.get("alias"), str):
            add(mmeta["alias"])
        spell = t.vendor(vname).get("spell") or {}
        for route in spell:
            add(resolve(vname, "frontier", route, tiers=t))
        if isinstance(mmeta.get("spellings"), dict):
            for v in mmeta["spellings"].values():
                if isinstance(v, str):
                    add(v)
    return tokens


def rank(vendor: str, tiers: Tiers | None = None) -> int:
    """1-based vendor rank; raises if unknown."""
    t = tiers or load()
    order = list((t.data.get("rank") or {}).get("order") or [])
    try:
        return order.index(vendor) + 1
    except ValueError as e:
        raise TiersError(f"vendor {vendor!r} not in rank.order") from e


def ranked_frontier(n: int, tiers: Tiers | None = None) -> tuple[str, str]:
    """(vendor, id) for the n-th ranked vendor's frontier role (1-based)."""
    t = tiers or load()
    order = list((t.data.get("rank") or {}).get("order") or [])
    if n < 1 or n > len(order):
        raise TiersError(f"rank {n} out of range 1..{len(order)}")
    vendor = order[n - 1]
    return vendor, t.role_id(vendor, "frontier")


def pool(vendor: str, role: str, tiers: Tiers | None = None) -> dict[str, Any] | None:
    t = tiers or load()
    pools = t.vendor(vendor).get("pools") or {}
    body = pools.get(role)
    return dict(body) if isinstance(body, dict) else None


def display(vendor: str, role: str, tiers: Tiers | None = None) -> str:
    t = tiers or load()
    mid = t.role_id(vendor, role)
    mmeta = (t.data.get("model") or {}).get(mid) or {}
    d = mmeta.get("display")
    return str(d) if isinstance(d, str) and d else mid


def sublimit_families(tiers: Tiers | None = None) -> tuple[str, ...]:
    """pool_family values from every vendor's pools (route_agent SUBLIMIT_FAMILIES)."""
    t = tiers or load()
    out: list[str] = []
    seen: set[str] = set()
    for vname in t.vendors():
        pools = t.vendor(vname).get("pools") or {}
        for pbody in pools.values():
            if not isinstance(pbody, dict):
                continue
            fam = pbody.get("pool_family")
            if isinstance(fam, str) and fam and fam not in seen:
                seen.add(fam)
                out.append(fam)
    return tuple(out)


def _ensure_model_entry(
    data: dict[str, Any],
    mid: str,
    *,
    vendor: str,
    alias: str | None,
    display_name: str | None,
) -> None:
    models = data.setdefault("model", {})
    if mid in models and isinstance(models[mid], dict):
        body = models[mid]
        if alias and not body.get("alias"):
            body["alias"] = alias
        if display_name and not body.get("display"):
            body["display"] = display_name
        return
    body: dict[str, Any] = {"vendor": vendor}
    if alias:
        body["alias"] = alias
    if display_name:
        body["display"] = display_name
    models[mid] = body


def promote(
    *,
    vendor: str,
    new_id: str,
    reason: str,
    alias: str | None = None,
    display_name: str | None = None,
    cascade: int | None = None,
    path: Path | None = None,
    dry_run: bool = False,
    today: str | None = None,
) -> PromoteResult:
    """Promote new_id to frontier; shift the ladder by cascade (default vendor.cascade).

    No network, no secrets. Caller commits the file in a claimed workspace.
    """
    if not isinstance(new_id, str) or not new_id.strip():
        raise TiersError("--new must be a non-empty model id")
    new_id = new_id.strip()
    if not isinstance(reason, str) or len(reason.strip()) < 3:
        raise TiersError("--reason must be at least 3 characters")
    reason = reason.strip()
    p = Path(path) if path is not None else default_path()
    tiers = load(p, use_cache=False)
    # Promote always edits the file's content when source=file; when falling back
    # to DEFAULTS, start from DEFAULTS so a first write can create the file.
    data = copy.deepcopy(tiers.data)
    vbody = data.get("vendor", {}).get(vendor)
    if not isinstance(vbody, dict):
        raise TiersError(f"unknown vendor {vendor!r}")
    fam = vbody.get("family")
    if not isinstance(fam, str) or not re.fullmatch(fam, new_id, flags=re.IGNORECASE):
        raise TiersError(
            f"new id {new_id!r} does not match [vendor.{vendor}].family; "
            f"pass a matching id or update family first"
        )
    casc = int(cascade if cascade is not None else vbody.get("cascade", 2))
    if not 1 <= casc <= 4:
        raise TiersError(f"cascade must be 1..4, got {casc}")
    roles = dict(vbody.get("roles") or {})
    before_roles = dict(roles)
    # cascade N: new → frontier; roles[0..N-2] shift one step down; roles[N..] stay.
    # The role pushed off the cascade window (old roles[N-1]) goes to [former].
    # Example cascade=2: frontier=new, judgment=old frontier; old judgment → former;
    # everyday/bulk unchanged (operator OPEN 2 / DECIDED 4).
    old_ladder = [roles[r] for r in ROLES]
    new_ladder: list[str] = list(old_ladder)
    new_ladder[0] = new_id
    for i in range(1, casc):
        new_ladder[i] = old_ladder[i - 1]
    pushed_mid = old_ladder[casc - 1]
    pushed_role = ROLES[casc - 1]
    notes: list[str] = []
    for i, role in enumerate(ROLES):
        roles[role] = new_ladder[i]
    vbody["roles"] = roles
    day = today or date.today().isoformat()
    _ensure_model_entry(
        data, new_id, vendor=vendor, alias=alias, display_name=display_name
    )
    former = data.setdefault("former", {})
    if pushed_mid not in new_ladder:
        former[pushed_mid] = {
            "vendor": vendor,
            "last_role": pushed_role,
            "until": day,
        }
        notes.append(f"former: {pushed_mid} last_role={pushed_role}")
    elif pushed_mid != new_id:
        notes.append(
            f"kept {pushed_mid} on the ladder (duplicate with a lower role); "
            f"no [former] row"
        )
    meta = data.setdefault("meta", {})
    meta["schema"] = SCHEMA
    meta["updated"] = day
    meta["last_promote_reason"] = reason
    data = _validate(data, label="promote result")
    text = dump_toml(data)
    before = copy.deepcopy(tiers.data)
    changed = dump_toml(before) != text
    if changed and not dry_run:
        atomic_write(p, text)
        clear_cache()
    return PromoteResult(
        before=before,
        after=data,
        text=text,
        path=p,
        dry_run=dry_run,
        changed=changed,
        notes=notes,
    )


def set_role(
    *,
    vendor: str,
    role: str,
    new_id: str,
    reason: str,
    alias: str | None = None,
    display_name: str | None = None,
    path: Path | None = None,
    dry_run: bool = False,
    today: str | None = None,
) -> PromoteResult:
    """Set one role's id without shifting the ladder (everyday/bulk releases)."""
    if role not in ROLES:
        raise TiersError(f"unknown role {role!r}")
    if not isinstance(new_id, str) or not new_id.strip():
        raise TiersError("--id must be a non-empty model id")
    new_id = new_id.strip()
    if not isinstance(reason, str) or len(reason.strip()) < 3:
        raise TiersError("--reason must be at least 3 characters")
    p = Path(path) if path is not None else default_path()
    tiers = load(p, use_cache=False)
    data = copy.deepcopy(tiers.data)
    vbody = data.get("vendor", {}).get(vendor)
    if not isinstance(vbody, dict):
        raise TiersError(f"unknown vendor {vendor!r}")
    fam = vbody.get("family")
    if not isinstance(fam, str) or not re.fullmatch(fam, new_id, flags=re.IGNORECASE):
        raise TiersError(
            f"id {new_id!r} does not match [vendor.{vendor}].family"
        )
    roles = dict(vbody.get("roles") or {})
    old = roles.get(role)
    roles[role] = new_id
    vbody["roles"] = roles
    day = today or date.today().isoformat()
    _ensure_model_entry(
        data, new_id, vendor=vendor, alias=alias, display_name=display_name
    )
    notes: list[str] = []
    if isinstance(old, str) and old != new_id and old not in roles.values():
        data.setdefault("former", {})[old] = {
            "vendor": vendor,
            "last_role": role,
            "until": day,
        }
        notes.append(f"former: {old} last_role={role}")
    meta = data.setdefault("meta", {})
    meta["schema"] = SCHEMA
    meta["updated"] = day
    meta["last_set_reason"] = reason.strip()
    data = _validate(data, label="set result")
    text = dump_toml(data)
    before = copy.deepcopy(tiers.data)
    changed = dump_toml(before) != text
    if changed and not dry_run:
        atomic_write(p, text)
        clear_cache()
    return PromoteResult(
        before=before,
        after=data,
        text=text,
        path=p,
        dry_run=dry_run,
        changed=changed,
        notes=notes,
    )


def public_dict(tiers: Tiers | None = None) -> dict[str, Any]:
    """JSON-serialisable view for policy / ade-config projection."""
    t = tiers or load()
    return {
        "meta": copy.deepcopy(t.data.get("meta") or {}),
        "rank": copy.deepcopy(t.data.get("rank") or {}),
        "vendor": copy.deepcopy(t.data.get("vendor") or {}),
        "model": copy.deepcopy(t.data.get("model") or {}),
        "former": copy.deepcopy(t.data.get("former") or {}),
        "frontier_tokens": frontier_tokens(t),
        "sublimit_families": list(sublimit_families(t)),
        "source": t.source,
        "path": str(t.path) if t.path else None,
        "error": t.error,
    }
