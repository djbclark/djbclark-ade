"""Shared Stage 0 dual-read helpers for tendcf multi-site ops paths and legacy ~/ops (queue #123).

Implements the locked-in `frdminc/tendcf` #98 (PR #105, `f03cb9b0`) workspace contract
alongside legacy `~/ops/site-{public,private}-*` fallback for Stage 0 dual-read:

- Default ops root: `~/tendcf-ops` (overridable via `TENDCF_OPS_ROOT`).
- Deterministic matched site pair: `tendcf-private-<slug>` (required) <-> `tendcf-public-<slug>` (optional).
- Strict slug grammar: `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\\Z`, <= 64 chars, no `-wt` suffix, no legacy aliases.
- Pair-bound selector precedence: explicit `site_name` > `TENDCF_SITE` > `$XDG_CONFIG_HOME/tendcf/active-site`
  (when `XDG_CONFIG_HOME` is an absolute path, else `~/.config/tendcf/active-site`).
- Fail-closed: never globs a sole directory under `~/tendcf-ops`; invalid/malformed selectors or
  symlinked/case-mismatched site directories are rejected rather than guessed.
- `bgrun` dual-read: `~/.local/bin/bgrun`, `<TENDCF_OPS_ROOT>/tendcf-{public,private}-<slug>/bin/bgrun`,
  and legacy `~/ops/site-*/bin/bgrun` (plus `bg` where supported).

Python 3.9+ stdlib only (no shebang: library module, callable via `python3 bin/ade_ops_paths.py ...`).
"""
from __future__ import annotations

import errno
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_TENDCF_OPS_ROOT_NAME = "tendcf-ops"
LEGACY_OPS_ROOT_NAME = "ops"
TENDCF_PRIVATE_PREFIX = "tendcf-private-"
TENDCF_PUBLIC_PREFIX = "tendcf-public-"
MAX_SLUG_LENGTH = 64
MAX_ACTIVE_SITE_BYTES = 4096
WORKTREE_SUFFIX = "-wt"

# Lowercase ASCII slug: `\Z` (not `$`) refuses a trailing newline.
SITE_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
LEGACY_SITE_DIR_RE = re.compile(r"^site-[A-Za-z0-9][A-Za-z0-9._-]*\Z")
LEGACY_SITE_NAMES = (
    "site-private-djbclark",
    "site-private",
    "site-public-djbclark",
    "site-djbclark",
)
_HOME_PREFIXES = ("~/", "$HOME/", "${HOME}/")


class OpsPathError(ValueError):
    """Raised on invalid tendcf workspace slugs, config files, or paths."""


@dataclass(frozen=True)
class SitePair:
    """Resolved pair-bound tendcf site workspace under `ops_root`."""

    ops_root: Path
    slug: str
    private_dir: Path
    public_dir: Path | None


def _env_map(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _home_dir(env: Mapping[str, str], home: Path | None = None) -> Path:
    if home is not None:
        return home
    raw = env.get("HOME", "")
    if raw and "\x00" not in raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
    return Path.home()


def _expand_path(raw: str, env: Mapping[str, str], home: Path | None = None) -> Path:
    """Expand strictly `~` and `~/...` against `_home_dir`; reject `~otheruser`, `~//...`, and NUL."""
    if not isinstance(raw, str) or not raw:
        raise OpsPathError("path must not be empty")
    if "\x00" in raw:
        raise OpsPathError("path contains a NUL byte")
    if raw == "~":
        return _home_dir(env, home)
    if raw.startswith("~/"):
        rest = raw[2:]
        if not rest or rest.startswith("/"):
            raise OpsPathError(f"malformed tilde path: {raw!r}")
        return _home_dir(env, home) / rest
    if raw.startswith("~"):
        raise OpsPathError(f"unsupported tilde user expansion in path: {raw!r}")
    return Path(raw)


def validate_site_slug(slug: str, *, label: str = "site slug") -> str:
    """Validate `<site>` slug grammar (`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\\Z`, <=64 chars, no `-wt`)."""
    if not isinstance(slug, str) or not slug:
        raise OpsPathError(f"{label} must not be empty")
    if "\x00" in slug:
        raise OpsPathError(f"{label} contains a NUL byte")
    if len(slug) > MAX_SLUG_LENGTH:
        raise OpsPathError(f"{label} {slug!r} exceeds maximum length of {MAX_SLUG_LENGTH} characters")
    if not SITE_SLUG_RE.match(slug):
        raise OpsPathError(f"invalid {label} {slug!r}")
    if slug.endswith(WORKTREE_SUFFIX):
        raise OpsPathError(f"invalid {label} {slug!r}: suffix {WORKTREE_SUFFIX!r} is reserved for worktrees")
    return slug


def is_valid_site_slug(slug: str) -> bool:
    """Return True iff `slug` satisfies the locked-in tendcf site slug grammar."""
    try:
        validate_site_slug(slug)
        return True
    except OpsPathError:
        return False


def active_site_config_path(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """XDG active-site file (`$XDG_CONFIG_HOME/tendcf/active-site` when absolute, else `~/.config/tendcf/active-site`)."""
    env_m = _env_map(env)
    raw = env_m.get("XDG_CONFIG_HOME", "")
    if raw and "\x00" not in raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate / "tendcf" / "active-site"
    return _home_dir(env_m, home) / ".config" / "tendcf" / "active-site"


def read_active_site_file(path: Path) -> str | None:
    """Read a plain single-line non-symlink active-site file; return None if absent, raise OpsPathError if invalid."""
    try:
        is_link = path.is_symlink()
    except OSError as exc:
        raise OpsPathError(f"cannot inspect active-site config {path}: {exc}") from exc
    if is_link:
        raise OpsPathError(f"active-site config must not be a symlink: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", errno.ELOOP)):
            raise OpsPathError(f"active-site config must not be a symlink: {path}") from exc
        raise OpsPathError(f"cannot read active-site config {path}: {exc}") from exc

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OpsPathError(f"active-site config must be a regular file: {path}")
        if st.st_size > MAX_ACTIVE_SITE_BYTES:
            raise OpsPathError(f"active-site config exceeds {MAX_ACTIVE_SITE_BYTES} bytes: {path}")
        fh = os.fdopen(fd, "rb")
    except OpsPathError:
        os.close(fd)
        raise
    except OSError as exc:
        os.close(fd)
        raise OpsPathError(f"cannot inspect active-site config {path}: {exc}") from exc
    except BaseException:
        os.close(fd)
        raise

    with fh:
        try:
            data = fh.read(MAX_ACTIVE_SITE_BYTES + 1)
        except OSError as exc:
            raise OpsPathError(f"cannot read active-site config {path}: {exc}") from exc

    if len(data) > MAX_ACTIVE_SITE_BYTES:
        raise OpsPathError(f"active-site config exceeds {MAX_ACTIVE_SITE_BYTES} bytes: {path}")
    if b"\x00" in data:
        raise OpsPathError(f"active-site config contains a NUL byte: {path}")
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OpsPathError(f"active-site config is not valid UTF-8: {path}: {exc}") from exc

    normalized = raw.replace("\r\n", "\n")
    if "\r" in normalized:
        raise OpsPathError(f"active-site config contains bare CR characters: {path}")

    entries: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.strip(" \t")
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped)

    if not entries:
        raise OpsPathError(f"active-site config has no site slug: {path}")
    if len(entries) > 1:
        raise OpsPathError(f"active-site config is ambiguous ({len(entries)} entries): {path}")
    return validate_site_slug(entries[0], label=f"site slug in {path}")


def tendcf_ops_root(
    env: Mapping[str, str] | None = None,
    *,
    ops_root: str | Path | None = None,
    home: Path | None = None,
) -> Path | None:
    """Resolve `ops_root` > `TENDCF_OPS_ROOT` > `~/tendcf-ops`. Returns None fail-closed if explicit override is invalid."""
    env_m = _env_map(env)
    if ops_root is not None:
        raw = str(ops_root)
        if not raw.strip():
            return None
    elif "TENDCF_OPS_ROOT" in env_m:
        raw = env_m["TENDCF_OPS_ROOT"]
        if not raw.strip():
            return None
    else:
        return _home_dir(env_m, home) / DEFAULT_TENDCF_OPS_ROOT_NAME

    try:
        expanded = _expand_path(raw, env_m, home)
    except OpsPathError:
        return None
    if not expanded.is_absolute():
        return None
    if ".." in expanded.parts:
        return None
    return expanded


def legacy_ops_root(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Legacy `~/ops` root (honors valid absolute/`~` `OPS_ROOT`, else `~/ops`)."""
    env_m = _env_map(env)
    raw = env_m.get("OPS_ROOT", "")
    if raw.strip():
        try:
            expanded = _expand_path(raw, env_m, home)
            if expanded.is_absolute() and ".." not in expanded.parts:
                return expanded
        except OpsPathError:
            pass
    return _home_dir(env_m, home) / LEGACY_OPS_ROOT_NAME


def active_site_slug(
    env: Mapping[str, str] | None = None,
    *,
    site_name: str | None = None,
    config_path: str | Path | None = None,
    home: Path | None = None,
) -> str | None:
    """Resolve active tendcf site slug with precedence `site_name` > `TENDCF_SITE` > XDG `active-site`.

    Fail-closed: an invalid or empty higher-precedence selector returns None without falling
    through, and a missing/malformed active-site file returns None (never globs `~/tendcf-ops`).
    """
    env_m = _env_map(env)
    if site_name is not None:
        try:
            return validate_site_slug(site_name, label="--site-name")
        except OpsPathError:
            return None

    if config_path is not None:
        raw_cfg = str(config_path)
        if not raw_cfg.strip():
            return None
        try:
            cfg = _expand_path(raw_cfg, env_m, home)
            return read_active_site_file(cfg)
        except OpsPathError:
            return None

    if "TENDCF_SITE" in env_m:
        raw_env = env_m["TENDCF_SITE"]
        if not raw_env:
            return None
        try:
            return validate_site_slug(raw_env, label="TENDCF_SITE")
        except OpsPathError:
            return None

    default_cfg = active_site_config_path(env_m, home=home)
    try:
        return read_active_site_file(default_cfg)
    except OpsPathError:
        return None


def _check_site_repo_dir(ops_root: Path, name: str, *, required: bool) -> Path | None:
    """Verify `<ops_root>/<name>` is an exact-case real directory inside `ops_root` (no symlinks)."""
    exact = None
    case_mismatch = None
    target_lower = name.lower()
    try:
        with os.scandir(ops_root) as it:
            for entry in it:
                if entry.name == name:
                    exact = entry
                    break
                if case_mismatch is None and entry.name.lower() == target_lower:
                    case_mismatch = entry
    except OSError as exc:
        raise OpsPathError(f"cannot read ops root {ops_root}: {exc}") from exc

    if exact is None:
        if case_mismatch is not None:
            raise OpsPathError(f"wrong directory casing for {name!r} under {ops_root}: found {case_mismatch.name!r}")
        if required:
            raise OpsPathError(f"required site repo not found: {ops_root / name}")
        return None

    candidate = Path(exact.path)
    try:
        is_link = exact.is_symlink()
        is_dir = exact.is_dir(follow_symlinks=False)
    except OSError as exc:
        raise OpsPathError(f"cannot inspect site repo {candidate}: {exc}") from exc

    if is_link:
        raise OpsPathError(f"site repo must not be a symlink: {candidate}")
    if not is_dir:
        raise OpsPathError(f"site repo is not a directory: {candidate}")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OpsPathError(f"cannot resolve site repo {candidate}: {exc}") from exc
    if resolved.parent != ops_root:
        raise OpsPathError(f"site repo resolves outside {ops_root}: {resolved}")
    return resolved


def resolve_tendcf_site_pair(
    env: Mapping[str, str] | None = None,
    *,
    site_name: str | None = None,
    ops_root: str | Path | None = None,
    config_path: str | Path | None = None,
    home: Path | None = None,
) -> SitePair | None:
    """Resolve the pair-bound `(tendcf-private-<slug>, tendcf-public-<slug>)` under `tendcf_ops_root`.

    Returns `SitePair` only when a valid selector is present and `<ops_root>/tendcf-private-<slug>`
    exists as an exact-case real non-symlink directory (and `<ops_root>/tendcf-public-<slug>`, if
    present, is likewise an exact-case real non-symlink directory). Returns None fail-closed otherwise.
    Never globs `ops_root`.
    """
    env_m = _env_map(env)
    root = tendcf_ops_root(env_m, ops_root=ops_root, home=home)
    if root is None:
        return None
    slug = active_site_slug(env_m, site_name=site_name, config_path=config_path, home=home)
    if slug is None:
        return None
    try:
        if not root.is_dir():
            return None
        resolved_root = root.resolve(strict=True)
        priv = _check_site_repo_dir(resolved_root, f"{TENDCF_PRIVATE_PREFIX}{slug}", required=True)
        assert priv is not None
        pub = _check_site_repo_dir(resolved_root, f"{TENDCF_PUBLIC_PREFIX}{slug}", required=False)
    except (OSError, RuntimeError, OpsPathError):
        return None
    return SitePair(ops_root=resolved_root, slug=slug, private_dir=priv, public_dir=pub)


def candidate_bgrun_paths(
    env: Mapping[str, str] | None = None,
    *,
    site_name: str | None = None,
    ops_root: str | Path | None = None,
    include_bg: bool = False,
    home: Path | None = None,
) -> list[Path]:
    """Ordered Stage 0 dual-read candidate paths for `bgrun` (and transitional `bg` if `include_bg`)."""
    env_m = _env_map(env)
    h = _home_dir(env_m, home)
    names = ("bgrun", "bg") if include_bg else ("bgrun",)
    candidates: list[Path] = []

    def _add(p: Path) -> None:
        if p not in candidates:
            candidates.append(p)

    for exe in names:
        _add(h / ".local" / "bin" / exe)

    pair = resolve_tendcf_site_pair(env_m, site_name=site_name, ops_root=ops_root, home=h)
    if pair is not None:
        if pair.public_dir is not None:
            for exe in names:
                _add(pair.public_dir / "bin" / exe)
        for exe in names:
            _add(pair.private_dir / "bin" / exe)

    legacy = legacy_ops_root(env_m, home=h)
    for site_dir in LEGACY_SITE_NAMES:
        for exe in names:
            _add(legacy / site_dir / "bin" / exe)

    return candidates


def find_bgrun(
    env: Mapping[str, str] | None = None,
    *,
    site_name: str | None = None,
    ops_root: str | Path | None = None,
    include_bg: bool = False,
    home: Path | None = None,
) -> Path | None:
    """Return the first existing executable `bgrun` (or `bg` when `include_bg`) across Stage 0 locations."""
    for cand in candidate_bgrun_paths(
        env, site_name=site_name, ops_root=ops_root, include_bg=include_bg, home=home
    ):
        try:
            if cand.is_file() and os.access(cand, os.X_OK):
                return cand
        except OSError:
            continue
    return None


def _is_tendcf_site_dir_name(name: str) -> bool:
    for prefix in (TENDCF_PUBLIC_PREFIX, TENDCF_PRIVATE_PREFIX):
        if name.startswith(prefix):
            return is_valid_site_slug(name[len(prefix):])
    return False


def _is_legacy_site_dir_name(name: str) -> bool:
    return bool(LEGACY_SITE_DIR_RE.match(name)) and not name.endswith(WORKTREE_SUFFIX)


def is_bgrun_path(
    token: str,
    env: Mapping[str, str] | None = None,
    *,
    allow_bg: bool = True,
    home: Path | None = None,
) -> bool:
    """Return True iff `token` names a valid Stage 0 `bgrun` (or `bg` when `allow_bg`) path.

    Accepted forms (with `~`, `$HOME`, `${HOME}`, or an absolute path; never relative, never `..`,
    never lookalikes like `bgrunner` or `-wt` worktrees):
      1. `~/.local/bin/bgrun` (and `/bg` when `allow_bg`)
      2. `<TENDCF_OPS_ROOT>/tendcf-{public,private}-<valid-slug>/bin/bgrun` (default `~/tendcf-ops`)
      3. `~/ops/site-<name>/bin/bgrun` (legacy `~/ops/site-*/bin/bgrun`)
    """
    if not isinstance(token, str) or not token or "\x00" in token:
        return False
    if any(ch.isspace() for ch in token):
        return False
    allowed_exes = ("bgrun", "bg") if allow_bg else ("bgrun",)

    # Reject empty segments (`//`), `.` and `..` anywhere after the leading prefix.
    env_m = _env_map(env)
    rel_after_home: str | None = None
    for prefix in _HOME_PREFIXES:
        if token.startswith(prefix):
            rel_after_home = token[len(prefix):]
            break

    if rel_after_home is not None:
        if not rel_after_home or rel_after_home.startswith("/"):
            return False
        parts = rel_after_home.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return False
        exe = parts[-1]
        if exe not in allowed_exes:
            return False
        if parts == [".local", "bin", exe]:
            return True
        if len(parts) == 4 and parts[0] == DEFAULT_TENDCF_OPS_ROOT_NAME and parts[2] == "bin":
            return _is_tendcf_site_dir_name(parts[1])
        if len(parts) == 4 and parts[0] == LEGACY_OPS_ROOT_NAME and parts[2] == "bin":
            return _is_legacy_site_dir_name(parts[1])
        # Also honor a custom TENDCF_OPS_ROOT under $HOME (e.g. TENDCF_OPS_ROOT=~/my-ops).
        expanded_abs = str(_home_dir(env_m, home).joinpath(*parts))
        return _matches_custom_tendcf_root(expanded_abs, allowed_exes, env_m, home)

    if not token.startswith("/"):
        return False
    if "//" in token:
        return False
    parts = token[1:].split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    exe = parts[-1]
    if exe not in allowed_exes:
        return False
    if len(parts) >= 3 and parts[-3:] == [".local", "bin", exe]:
        return True
    if len(parts) >= 4 and parts[-4] == DEFAULT_TENDCF_OPS_ROOT_NAME and parts[-2] == "bin":
        if _is_tendcf_site_dir_name(parts[-3]):
            return True
    if len(parts) >= 4 and parts[-4] == LEGACY_OPS_ROOT_NAME and parts[-2] == "bin":
        if _is_legacy_site_dir_name(parts[-3]):
            return True
    return _matches_custom_tendcf_root(token, allowed_exes, env_m, home)


def _matches_custom_tendcf_root(
    abs_path: str,
    allowed_exes: tuple[str, ...],
    env: Mapping[str, str],
    home: Path | None,
) -> bool:
    custom_root = tendcf_ops_root(env, home=home)
    if custom_root is None:
        return False
    cand = Path(abs_path)
    roots = [custom_root]
    try:
        resolved = custom_root.resolve()
        if resolved != custom_root:
            roots.append(resolved)
    except (OSError, RuntimeError):
        pass
    for root in roots:
        try:
            rel = cand.relative_to(root).parts
        except ValueError:
            continue
        if len(rel) == 3 and rel[1] == "bin" and rel[2] in allowed_exes and _is_tendcf_site_dir_name(rel[0]):
            return True
    return False


def resolve_default_bm_store(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Default Basic Memory store: active `tendcf-private-<slug>/memory` if present, else `~/ops/site-private/memory`."""
    env_m = _env_map(env)
    pair = resolve_tendcf_site_pair(env_m, home=home)
    if pair is not None:
        candidate = pair.private_dir / "memory"
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
    return legacy_ops_root(env_m, home=home) / "site-private" / "memory"


def resolve_skill_roots(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve `(private_skills_dir, site_skills_dir)` for `bin/skill-everywhere` Stage 0 dual-read.

    When an active tendcf site pair resolves, prefers `<tendcf-private-<slug>>/skills` and
    `<tendcf-public-<slug>>/skills` when those directories exist (or when the legacy dirs are absent),
    falling back seamlessly to legacy `~/ops/site-private/skills` and `~/ops/site-public-djbclark/skills`.
    """
    env_m = _env_map(env)
    legacy = legacy_ops_root(env_m, home=home)
    legacy_priv = legacy / "site-private" / "skills"
    legacy_site = legacy / "site-public-djbclark" / "skills"

    pair = resolve_tendcf_site_pair(env_m, home=home)
    if pair is None:
        return legacy_priv, legacy_site

    new_priv = pair.private_dir / "skills"
    if new_priv.is_dir() or not legacy_priv.is_dir():
        priv_root = new_priv
    else:
        priv_root = legacy_priv

    if pair.public_dir is not None:
        new_site = pair.public_dir / "skills"
        if new_site.is_dir() or not legacy_site.is_dir():
            site_root = new_site
        else:
            site_root = legacy_site
    else:
        site_root = legacy_site

    return priv_root, site_root


def resolve_ops_checkout_name(
    directory: Path,
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> str | None:
    """Return the ops checkout directory name if `directory` is inside `tendcf-ops` or legacy `~/ops`, else None.

    Under `tendcf_ops_root`: recognizes `tendcf-private-<valid-slug>`, `tendcf-public-<valid-slug>`,
    and `tendcf` (excluding `.worktrees` and `*-wt` worktrees so they resolve as normal git worktrees).
    Under legacy `~/ops`: recognizes any direct child `<repo>`.
    """
    env_m = _env_map(env)
    h = _home_dir(env_m, home)
    try:
        d = Path(directory).expanduser().resolve()
    except (OSError, RuntimeError):
        return None

    troot = tendcf_ops_root(env_m, home=h)
    if troot is not None:
        for base in _unique_resolved_paths(troot):
            try:
                parts = d.relative_to(base).parts
            except ValueError:
                continue
            if parts:
                top = parts[0]
                if top.startswith(".") or top.endswith(WORKTREE_SUFFIX):
                    return None
                if top == "tendcf" or _is_tendcf_site_dir_name(top):
                    return top
                return None

    lroot = legacy_ops_root(env_m, home=h)
    for base in _unique_resolved_paths(lroot):
        try:
            parts = d.relative_to(base).parts
        except ValueError:
            continue
        if parts:
            return parts[0]
    return None


def _unique_resolved_paths(path: Path) -> list[Path]:
    out = [path]
    try:
        resolved = path.resolve()
        if resolved != path:
            out.append(resolved)
    except (OSError, RuntimeError):
        pass
    return out


def _cli(argv: list[str]) -> int:
    if not argv:
        return 2
    cmd = argv[0]
    if cmd == "skill-roots":
        priv, site = resolve_skill_roots()
        sys.stdout.write(f"{priv}\n{site}\n")
        return 0
    if cmd == "find-bgrun":
        include_bg = "--include-bg" in argv[1:]
        found = find_bgrun(include_bg=include_bg)
        if found is None:
            return 1
        sys.stdout.write(f"{found}\n")
        return 0
    if cmd == "default-bm-store":
        sys.stdout.write(f"{resolve_default_bm_store()}\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
