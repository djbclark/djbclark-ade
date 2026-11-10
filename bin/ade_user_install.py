"""ade_user_install: user-scoped tool bootstrap (no shell=True, no root).

Fetches known release binaries into ``~/.local/bin`` (or ``--prefix``), or
symlinks a repo ``bin/`` entry there. Used by ``ade-install apply`` via
``install_argv``. Does not run package managers that need root; those stay
behind ``needs_system`` + a later ``--system`` unit.

Linux ``sudo-secretspec`` is the exception that is still user-scoped here: the
release has no single apt argv, so this helper resolves ``releases/latest``,
fetches the versioned tarball + ``.sha256``, extracts media, and reports (or
optionally runs) the ``libexec`` installer argv. Privilege-boundary install
remains opt-in via ``--declarations``.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

BIN = Path(__file__).resolve().parent
REPO_ROOT = BIN.parent

DEFAULT_PREFIX = Path.home() / ".local" / "bin"
USER_AGENT = "djbclark-ade-user-install/1"

SECRETSPEC_OWNER = "frdminc"
SECRETSPEC_REPO = "sudo-secretspec"
SECRETSPEC_LINUX_TRIPLE = "x86_64-unknown-linux-gnu"

UrlOpen = Callable[[str], bytes]
TagResolver = Callable[[str, str], str]
CmdRunner = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]


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


def secretspec_linux_asset_names(version: str) -> tuple[str, str]:
    """Return (tarball, sha256 sidecar) names for a resolved Linux release version.

    Version is the tag without a leading ``v`` (e.g. ``0.21.1-sudo.5``). Asset
    names are versioned; callers must resolve latest first — never pin a URL.
    """
    if not version or "/" in version or ".." in version or version.startswith("."):
        raise UserInstallError(f"refusing sudo-secretspec version {version!r}")
    base = f"sudo-secretspec-{version}-{SECRETSPEC_LINUX_TRIPLE}.tar.gz"
    return base, f"{base}.sha256"


def secretspec_linux_download_urls(version: str) -> dict[str, str]:
    """Build GitHub release download URLs for the resolved version (not pinned)."""
    ver = version[1:] if version.startswith("v") else version
    tag = f"v{ver}"
    tarball, sha_name = secretspec_linux_asset_names(ver)
    base = (
        f"https://github.com/{SECRETSPEC_OWNER}/{SECRETSPEC_REPO}/releases/download/"
        f"{tag}"
    )
    return {
        "version": ver,
        "tag": tag,
        "tarball_name": tarball,
        "sha256_name": sha_name,
        "tarball_url": f"{base}/{tarball}",
        "sha256_url": f"{base}/{sha_name}",
        # releases/latest is the discovery surface in packaging/README; assets
        # themselves are versioned under the tag download path above.
        "latest_page": (
            f"https://github.com/{SECRETSPEC_OWNER}/{SECRETSPEC_REPO}/releases/latest"
        ),
    }


def _parse_sha256_sidecar(text: str, *, expected_name: str) -> str:
    """Parse a ``sha256sum``-style sidecar; return the hex digest for expected_name."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0], parts[-1]
        name = name.lstrip("*")
        if name == expected_name or Path(name).name == expected_name:
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                raise UserInstallError(f"invalid sha256 digest in sidecar: {digest!r}")
            return digest.lower()
    raise UserInstallError(f"sha256 sidecar missing entry for {expected_name!r}")


def _extract_tar_gz_root(blob: bytes, dest_dir: Path) -> Path:
    """Extract a release tarball into dest_dir; return the single top-level dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = tar.getmembers()
        # Refuse path traversal / absolute members.
        for m in members:
            p = Path(m.name)
            if p.is_absolute() or ".." in p.parts:
                raise UserInstallError(f"refusing unsafe archive member {m.name!r}")
        tar.extractall(dest_dir, filter="data")  # type: ignore[call-arg]
    tops = [p for p in dest_dir.iterdir() if p.name not in (".", "..")]
    if len(tops) != 1 or not tops[0].is_dir():
        raise UserInstallError(
            f"expected one top-level directory in sudo-secretspec media, got {[p.name for p in tops]!r}"
        )
    return tops[0]


def install_sudo_secretspec(
    *,
    prefix: Path,
    dry_run: bool = False,
    declarations: Path | None = None,
    run_install: bool = False,
    urlopen: UrlOpen | None = None,
    resolve_tag: TagResolver | None = None,
    runner: CmdRunner | None = None,
) -> dict[str, Any]:
    """Linux multi-step sudo-secretspec media helper (no pinned release URL).

    Resolves the latest GitHub release tag, builds the versioned asset URLs,
    downloads tarball + ``.sha256``, verifies, extracts under
    ``{prefix.parent}/lib/sudo-secretspec/<version>/``, and reports the
    ``libexec`` installer argv. Running the privileged installer requires both
    ``declarations`` and ``run_install=True`` (opt-in; later unit by default).
    """
    os_key, arch = host_triplet()
    if os_key != "linux" or arch != "x86_64":
        raise UserInstallError(
            f"sudo-secretspec Linux helper supports linux/x86_64 only "
            f"(got {os_key}/{arch}; use brew on macOS)"
        )
    resolve = resolve_tag or _github_latest_tag
    version = resolve(SECRETSPEC_OWNER, SECRETSPEC_REPO)
    meta = secretspec_linux_download_urls(version)
    stage_root = (prefix.parent / "lib" / "sudo-secretspec" / meta["version"]).resolve()
    media_dir = (
        stage_root
        / "extract"
        / f"sudo-secretspec-{meta['version']}-{SECRETSPEC_LINUX_TRIPLE}"
    )
    libexec = media_dir / "libexec" / "sudo-secretspec"
    install_argv: list[str] = [
        "sudo",
        str(libexec),
        "install",
        "--declarations",
        str(declarations) if declarations is not None else "/path/secretspec.toml",
    ]
    # Never put secret values on argv — only a declarations file path.
    attestation_argv = [
        "gh",
        "attestation",
        "verify",
        meta["tarball_name"],
        "--repo",
        f"{SECRETSPEC_OWNER}/{SECRETSPEC_REPO}",
    ]
    if dry_run:
        return {
            "id": "sudo-secretspec",
            "action": "would-fetch-extract",
            "version": meta["version"],
            "tag": meta["tag"],
            "latest_page": meta["latest_page"],
            "tarball_url": meta["tarball_url"],
            "sha256_url": meta["sha256_url"],
            "stage_root": str(stage_root),
            "media_dir": str(media_dir),
            "dest": str(media_dir),
            "attestation_argv": attestation_argv,
            "libexec_install_argv": install_argv,
            "run_install": False,
            "note": (
                "dry-run: resolve releases/latest → versioned asset → sha256 → extract; "
                "libexec install is opt-in via --declarations --run-install"
            ),
        }

    fetch = urlopen or _urlopen
    tarball_blob = fetch(meta["tarball_url"])
    sha_blob = fetch(meta["sha256_url"])
    expected = _parse_sha256_sidecar(
        sha_blob.decode("utf-8"), expected_name=meta["tarball_name"]
    )
    actual = hashlib.sha256(tarball_blob).hexdigest()
    if actual != expected:
        raise UserInstallError(
            f"sudo-secretspec sha256 mismatch: expected {expected}, got {actual}"
        )
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    # Write verified tarball + sidecar beside an extract/ subdir (not mixed in).
    tarball_path = stage_root / meta["tarball_name"]
    tarball_path.write_bytes(tarball_blob)
    (stage_root / meta["sha256_name"]).write_bytes(sha_blob)
    extract_root = stage_root / "extract"
    extracted = _extract_tar_gz_root(tarball_blob, extract_root)
    media_dir = extracted
    libexec = media_dir / "libexec" / "sudo-secretspec"
    if not libexec.is_file():
        raise UserInstallError(f"extracted media missing libexec installer: {libexec}")

    result: dict[str, Any] = {
        "id": "sudo-secretspec",
        "action": "staged",
        "version": meta["version"],
        "tag": meta["tag"],
        "tarball_url": meta["tarball_url"],
        "sha256_url": meta["sha256_url"],
        "sha256": actual,
        "stage_root": str(stage_root),
        "media_dir": str(media_dir),
        "dest": str(media_dir),
        "tarball_path": str(tarball_path),
        "attestation_argv": [
            "gh",
            "attestation",
            "verify",
            str(tarball_path),
            "--repo",
            f"{SECRETSPEC_OWNER}/{SECRETSPEC_REPO}",
        ],
        "libexec_install_argv": [
            "sudo",
            str(libexec),
            "install",
            "--declarations",
            str(declarations) if declarations is not None else "/path/secretspec.toml",
        ],
        "run_install": False,
    }

    if run_install:
        if declarations is None:
            raise UserInstallError(
                "--run-install requires --declarations PATH (no secrets on argv)"
            )
        decl = declarations.expanduser().resolve()
        if not decl.is_file():
            raise UserInstallError(f"declarations file not found: {decl}")
        argv = ["sudo", str(libexec), "install", "--declarations", str(decl)]
        result["libexec_install_argv"] = argv
        run = runner or (
            lambda a, cwd: subprocess.run(  # noqa: S603 — argv list only
                a,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        )
        proc = run(argv, media_dir)
        result["run_install"] = True
        result["install_returncode"] = proc.returncode
        result["install_stdout"] = (proc.stdout or "")[-2000:]
        result["install_stderr"] = (proc.stderr or "")[-2000:]
        if proc.returncode != 0:
            result["action"] = "install-failed"
            raise UserInstallError(
                f"libexec install exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
            )
        result["action"] = "installed"
    return result


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
    declarations: Path | None = None,
    run_install: bool = False,
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
    if tool == "sudo-secretspec":
        return install_sudo_secretspec(
            prefix=prefix,
            dry_run=dry_run,
            declarations=declarations,
            run_install=run_install,
        )
    raise UserInstallError(f"unknown tool {tool!r} (want uv|just|link|sudo-secretspec)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="ade-user-install",
        description=(
            "User-scoped uv/just fetch, repo bin/ symlink, or Linux "
            "sudo-secretspec release-media staging into ~/.local."
        ),
    )
    p.add_argument(
        "tool",
        choices=("uv", "just", "link", "sudo-secretspec"),
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
    p.add_argument(
        "--declarations",
        default=None,
        help=(
            "path to secretspec.toml for sudo-secretspec libexec install "
            "(never a secret value; required with --run-install)"
        ),
    )
    p.add_argument(
        "--run-install",
        action="store_true",
        help=(
            "after staging Linux media, run sudo ./libexec/sudo-secretspec "
            "install --declarations PATH (opt-in privilege boundary)"
        ),
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
            declarations=Path(args.declarations) if args.declarations else None,
            run_install=args.run_install,
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
