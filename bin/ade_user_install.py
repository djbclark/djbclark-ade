"""ade_user_install: user-scoped tool bootstrap (no shell=True, no root).

Fetches known release binaries into ``~/.local/bin`` (or ``--prefix``), or
symlinks a repo ``bin/`` entry there. Used by ``ade-install apply`` via
``install_argv``. Does not run package managers that need root; those stay
behind ``needs_system`` + a later ``--system`` unit.

Also wraps vendor installers that only publish a downloadable script or
tarball (Cursor Agent, Hermes) so ``ade-install`` never needs ``curl|bash``.
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
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
DEFAULT_SHARE = Path.home() / ".local" / "share"
USER_AGENT = "djbclark-ade-user-install/1"

CURSOR_INSTALL_SCRIPT = "https://cursor.com/install"
CURSOR_VERSION_RE = re.compile(
    r"downloads\.cursor\.com/lab/([0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9a-f]+)/"
)
HERMES_INSTALL_SCRIPT = "https://hermes-agent.nousresearch.com/install.sh"

# Vendor HTTPS fetch + run/extract has the same trust model as the official
# curl|bash installers this replaces (TLS to the publisher CDN; no forever pin —
# standing order 8). Non-dry-run Cursor/Hermes installs refuse unless the
# operator sets ADE_USER_INSTALL_TRUST_VENDOR=1 so apply --yes cannot silently
# execute an unverified script/tarball.
VENDOR_TRUST_ENV = "ADE_USER_INSTALL_TRUST_VENDOR"


def _require_vendor_trust(tool: str) -> None:
    if os.environ.get(VENDOR_TRUST_ENV, "").strip() in ("1", "true", "yes"):
        return
    raise UserInstallError(
        f"{tool}: refusing unverified vendor download/exec without "
        f"{VENDOR_TRUST_ENV}=1 (TLS-to-publisher only; same trust as curl|bash; "
        "no forever digest pin — order 8). Dry-run needs no trust env."
    )


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


def cursor_lab_triplet() -> tuple[str, str]:
    """Cursor lab paths use linux|darwin and x64|arm64."""
    os_key, arch = host_triplet()
    lab_arch = "x64" if arch == "x86_64" else "arm64"
    return os_key, lab_arch


def _urlopen(url: str, *, timeout: float = 60.0, accept: str = "application/octet-stream") -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
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


def _resolve_cursor_version() -> str:
    """Read the version pin from Cursor's published install script."""
    text = _urlopen(
        CURSOR_INSTALL_SCRIPT,
        timeout=30.0,
        accept="text/plain,*/*",
    ).decode("utf-8", errors="replace")
    match = CURSOR_VERSION_RE.search(text)
    if not match:
        raise UserInstallError(
            f"could not parse Cursor Agent version from {CURSOR_INSTALL_SCRIPT}"
        )
    return match.group(1)


def _safe_extract_tar_gz(blob: bytes, dest: Path, *, strip_prefix: str = "dist-package/") -> None:
    """Extract a tar.gz into dest, refusing path traversal; optional top prefix strip."""
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("./"):
                name = name[2:]
            if strip_prefix and name.startswith(strip_prefix):
                name = name[len(strip_prefix) :]
            if not name or name.endswith("/"):
                continue
            if member.issym() or member.islnk():
                continue
            if not member.isfile():
                continue
            parts = Path(name).parts
            if any(p in ("", ".", "..") for p in parts) or name.startswith("/"):
                raise UserInstallError(f"refusing unsafe archive member {member.name!r}")
            target = (dest / name).resolve()
            if dest_resolved not in target.parents and target.parent != dest_resolved:
                raise UserInstallError(f"archive member escapes dest: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                if src is None:
                    raise UserInstallError(f"archive member {member.name!r} not readable")
                data = src.read()
            target.write_bytes(data)
            mode = member.mode
            if mode:
                target.chmod(mode & 0o777)


def install_cursor_cli(
    *,
    prefix: Path,
    share: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch Cursor Agent from downloads.cursor.com (no curl|bash)."""
    os_key, lab_arch = cursor_lab_triplet()
    version = _resolve_cursor_version()
    url = (
        f"https://downloads.cursor.com/lab/{version}/"
        f"{os_key}/{lab_arch}/agent-cli-package.tar.gz"
    )
    share_root = (share or DEFAULT_SHARE).expanduser().resolve()
    final_dir = share_root / "cursor-agent" / "versions" / version
    agent_bin = final_dir / "cursor-agent"
    dest_agent = prefix / "agent"
    dest_legacy = prefix / "cursor-agent"
    if dry_run:
        return {
            "id": "cursor-cli",
            "action": "would-fetch",
            "url": url,
            "dest": str(dest_agent),
            "version": version,
            "share": str(final_dir),
            "trust": VENDOR_TRUST_ENV,
        }
    _require_vendor_trust("cursor-cli")
    blob = _urlopen(url, timeout=120.0)
    versions_dir = final_dir.parent
    versions_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(versions_dir), prefix=".tmp-") as tmp:
        tmp_path = Path(tmp) / "extract"
        _safe_extract_tar_gz(blob, tmp_path)
        if not (tmp_path / "cursor-agent").is_file():
            raise UserInstallError("Cursor Agent archive missing cursor-agent binary")
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(str(tmp_path), str(final_dir))
    prefix.mkdir(parents=True, exist_ok=True)
    for link in (dest_agent, dest_legacy):
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(agent_bin)
    return {
        "id": "cursor-cli",
        "action": "installed",
        "url": url,
        "dest": str(dest_agent),
        "version": version,
        "share": str(final_dir),
    }


def install_hermes(*, dry_run: bool = False) -> dict[str, Any]:
    """Download Hermes install.sh and run it with argv (bash script --non-interactive).

    Avoids ``curl|bash`` by fetching via urllib, writing a temp file, then
    ``subprocess.run([bash, path, --non-interactive], shell=False)``.
    """
    if dry_run:
        return {
            "id": "hermes",
            "action": "would-run-script",
            "url": HERMES_INSTALL_SCRIPT,
            "argv": ["bash", "<temp>/install.sh", "--non-interactive"],
            "trust": VENDOR_TRUST_ENV,
        }
    _require_vendor_trust("hermes")
    blob = _urlopen(HERMES_INSTALL_SCRIPT, timeout=60.0, accept="text/plain,*/*")
    with tempfile.TemporaryDirectory(prefix="ade-hermes-install-") as tmp:
        script = Path(tmp) / "install.sh"
        script.write_bytes(blob)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        proc = subprocess.run(  # noqa: S603 — argv list only, never shell
            ["bash", str(script), "--non-interactive"],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )
        # Keep vendor progress off our stdout so `ade-user-install hermes --json` stays parseable.
        if proc.stdout:
            sys.stderr.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            raise UserInstallError(
                f"hermes install.sh exited {proc.returncode} (url={HERMES_INSTALL_SCRIPT})"
            )
    return {
        "id": "hermes",
        "action": "installed",
        "url": HERMES_INSTALL_SCRIPT,
        "argv": ["bash", "install.sh", "--non-interactive"],
    }


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
    if tool == "cursor-cli":
        return install_cursor_cli(prefix=prefix, dry_run=dry_run)
    if tool == "hermes":
        return install_hermes(dry_run=dry_run)
    if tool == "link":
        if not link_name:
            raise UserInstallError("link requires a bin name")
        return link_repo_bin(link_name, root=root, prefix=prefix, dry_run=dry_run)
    raise UserInstallError(
        f"unknown tool {tool!r} (want uv|just|cursor-cli|hermes|link)"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ade-user-install",
        description=(
            "User-scoped uv/just/cursor-cli fetch, Hermes installer wrap, "
            "or repo bin/ symlink into ~/.local/bin."
        ),
    )
    p.add_argument(
        "tool",
        choices=("uv", "just", "cursor-cli", "hermes", "link"),
        help="what to install",
    )
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
