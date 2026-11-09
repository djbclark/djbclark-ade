"""ade_user_install: user-scoped tool bootstrap (no shell=True, no root).

Fetches known release binaries into ``~/.local/bin`` (or ``--prefix``), or
symlinks a repo ``bin/`` entry there. Used by ``ade-install apply`` via
``install_argv``. Does not run package managers that need root; those stay
behind ``needs_system`` + a later ``--system`` unit.
"""
from __future__ import annotations

import io
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BIN = Path(__file__).resolve().parent
REPO_ROOT = BIN.parent

DEFAULT_PREFIX = Path.home() / ".local" / "bin"
USER_AGENT = "djbclark-ade-user-install/1"


class UserInstallError(ValueError):
    """Refused or failed user-scoped install."""


def host_triplet() -> tuple[str, str]:
    """Return (os_key, arch_key) for asset selection."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        os_key = "darwin"
    elif system == "linux":
        os_key = "linux"
    else:
        raise UserInstallError(f"unsupported OS for user install: {system!r}")
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        raise UserInstallError(f"unsupported arch for user install: {machine!r}")
    return os_key, arch


def _urlopen(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed release URLs
            return resp.read()
    except urllib.error.HTTPError as e:
        raise UserInstallError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise UserInstallError(f"network error fetching {url}: {e}") from e


def _github_latest_tag(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, RecursionError) as e:
        raise UserInstallError(f"could not resolve latest release for {owner}/{repo}: {e}") from e
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise UserInstallError(f"{owner}/{repo}: latest release missing tag_name")
    return tag.lstrip("v")


def uv_download_url(os_key: str, arch: str) -> str:
    if os_key == "linux":
        asset = f"uv-{arch}-unknown-linux-gnu.tar.gz"
    elif os_key == "darwin":
        # Apple ships arm64 as aarch64 in uv assets; x86_64 stays x86_64.
        asset = f"uv-{arch}-apple-darwin.tar.gz"
    else:
        raise UserInstallError(f"uv: no asset for os={os_key}")
    return f"https://github.com/astral-sh/uv/releases/latest/download/{asset}"


def just_download_url(os_key: str, arch: str, version: str) -> str:
    if os_key == "linux":
        asset = f"just-{version}-{arch}-unknown-linux-musl.tar.gz"
    elif os_key == "darwin":
        asset = f"just-{version}-{arch}-apple-darwin.tar.gz"
    else:
        raise UserInstallError(f"just: no asset for os={os_key}")
    return (
        f"https://github.com/casey/just/releases/download/"
        f"{version}/{asset}"
    )


def _extract_named_binary(blob: bytes, *, name: str, dest: Path) -> None:
    """Extract a single named file from a tar.gz into dest (mode 0755)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        member = None
        for m in tar.getmembers():
            base = Path(m.name).name
            if base == name and m.isfile():
                member = m
                break
        if member is None:
            raise UserInstallError(f"archive missing file {name!r}")
        # Avoid path traversal: only the basename is written.
        with tar.extractfile(member) as src:
            if src is None:
                raise UserInstallError(f"archive member {name!r} not readable")
            data = src.read()
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp, dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def install_uv(*, prefix: Path, dry_run: bool = False) -> dict[str, Any]:
    os_key, arch = host_triplet()
    url = uv_download_url(os_key, arch)
    dest = prefix / "uv"
    if dry_run:
        return {"id": "uv", "action": "would-fetch", "url": url, "dest": str(dest)}
    blob = _urlopen(url)
    _extract_named_binary(blob, name="uv", dest=dest)
    return {"id": "uv", "action": "installed", "url": url, "dest": str(dest)}


def install_just(*, prefix: Path, dry_run: bool = False) -> dict[str, Any]:
    os_key, arch = host_triplet()
    version = _github_latest_tag("casey", "just")
    url = just_download_url(os_key, arch, version)
    dest = prefix / "just"
    if dry_run:
        return {
            "id": "just",
            "action": "would-fetch",
            "url": url,
            "dest": str(dest),
            "version": version,
        }
    blob = _urlopen(url)
    _extract_named_binary(blob, name="just", dest=dest)
    return {
        "id": "just",
        "action": "installed",
        "url": url,
        "dest": str(dest),
        "version": version,
    }


def link_repo_bin(
    name: str,
    *,
    root: Path,
    prefix: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Symlink ``root/bin/<name>`` into ``prefix/<name>``."""
    if "/" in name or name in (".", "..") or not name:
        raise UserInstallError(f"refusing link name {name!r}")
    src = (root / "bin" / name).resolve()
    if not src.is_file():
        raise UserInstallError(f"missing repo bin tool: {src}")
    # Stay inside the chosen root's bin/.
    bin_dir = (root / "bin").resolve()
    if bin_dir not in src.parents and src.parent != bin_dir:
        raise UserInstallError(f"link source escapes repo bin/: {src}")
    dest = prefix / name
    if dry_run:
        return {"id": name, "action": "would-link", "src": str(src), "dest": str(dest)}
    prefix.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        if dest.is_symlink() and dest.resolve() == src:
            return {"id": name, "action": "unchanged", "src": str(src), "dest": str(dest)}
        dest.unlink()
    dest.symlink_to(src)
    return {"id": name, "action": "linked", "src": str(src), "dest": str(dest)}


def run_tool(
    tool: str,
    *,
    root: Path | None = None,
    prefix: Path | None = None,
    dry_run: bool = False,
    link_name: str | None = None,
) -> dict[str, Any]:
    root = (root or REPO_ROOT).resolve()
    prefix = (prefix or DEFAULT_PREFIX).expanduser().resolve()
    if tool == "uv":
        return install_uv(prefix=prefix, dry_run=dry_run)
    if tool == "just":
        return install_just(prefix=prefix, dry_run=dry_run)
    if tool == "link":
        if not link_name:
            raise UserInstallError("link requires a bin name")
        return link_repo_bin(link_name, root=root, prefix=prefix, dry_run=dry_run)
    raise UserInstallError(f"unknown tool {tool!r} (want uv|just|link)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ade-user-install",
        description="User-scoped uv/just fetch or repo bin/ symlink into ~/.local/bin.",
    )
    p.add_argument("tool", choices=("uv", "just", "link"), help="what to install")
    p.add_argument(
        "name",
        nargs="?",
        help="bin/ name when tool=link",
    )
    p.add_argument("--root", default=None, help="repository root (default: parent of this bin/)")
    p.add_argument(
        "--prefix",
        default=None,
        help=f"install prefix directory (default: {DEFAULT_PREFIX})",
    )
    p.add_argument("--dry-run", action="store_true", help="print planned action; change nothing")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = run_tool(
            args.tool,
            root=Path(args.root) if args.root else None,
            prefix=Path(args.prefix) if args.prefix else None,
            dry_run=args.dry_run,
            link_name=args.name,
        )
    except UserInstallError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.json:
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(
            f"ade-user-install: {result.get('action')} "
            f"id={result.get('id')} dest={result.get('dest')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
