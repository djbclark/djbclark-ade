"""firecrawl_mit_bridge: Mac-side MIT Libraries PDF and Cloudflare-walled scrape bridge for bin/firecrawl-router (stdlib only).

Feature-flagged (default OFF), Hyades-first, fail-closed bridge scoped strictly
to POST /v1/scrape and POST /v2/scrape for exact enrolled FQDNs present in a
fresh (<= 7d), user-owned, non-writable Tailscale policy snapshot.

Two lanes:
  1. `mit-fetch` (mode `pdf` or `all`): invokes `fetch.py fetch --artifact
     --enrolled-only` and converts PDFs with `pdftotext` / `pdfinfo`.
  2. `mit-browser` (mode `all`): invokes `browserfetch.py` through the local
     MITnet SOCKS5 tunnel (`127.0.0.1:18830`) and converts PDFs with
     `pdftotext` / `pdfinfo` or HTML with `pandoc --sandbox` (fallback to
     `browserfetch.py`'s `page.txt`).

Security invariants:
  - Subprocesses receive a strict allowlisted minimal environment (zero
    FIRECRAWL_*, LITELLM_*, MIT_SIPB_*, or other daemon keys).
  - URL canonicalization matches `fetch.parse_url()` byte-for-byte.
  - Snapshot validation refuses symlinks (`O_NOFOLLOW`), wrong UID,
    group/world-writable modes (`mode & 0o022`), age > 7 days, size > 1 MiB,
    duplicate JSON keys, invalid raw-policy checksums, and empty domain sets.
  - Per-run 0700 directories live inside a private 0700 state directory (never
    shared /tmp), are deleted in `finally`, and orphaned `run-*` dirs are swept
    on startup.
  - All subprocess stdout/stderr reads are strictly bounded and timeouts kill
    the entire process group (`SIGTERM` then `SIGKILL`).
  - Every failure returns `(None, None, reason)` so the caller fails closed to
    the untouched Hyades response.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

# ---- Constants & resource caps ---------------------------------------------

VALID_MODES = frozenset(("off", "pdf", "all"))
SCRAPE_ROUTES = frozenset(("/v1/scrape", "/v2/scrape"))

SNAPSHOT_MAX_AGE = 7 * 24 * 3600
SNAPSHOT_MAX_BYTES = 1 * 1024 * 1024
MANAGED_CAP = "tailscale.com/app-connectors"
MANAGED_APP = "mitnet-required"

MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_HTML_BYTES = 16 * 1024 * 1024
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
MAX_JSON_STDOUT_BYTES = 256 * 1024
MAX_PDFINFO_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 1024

DEFAULT_PDF_MAX_PAGES = 200
HARD_PDF_MAX_PAGES = 200

FETCH_CLI_TIMEOUT = 25
FETCH_KILL_TIMEOUT = 60.0
BROWSER_CLI_TIMEOUT = 45
BROWSER_KILL_TIMEOUT = 65.0
PDFTOTEXT_TIMEOUT = 15.0
PDFINFO_TIMEOUT = 5.0
PANDOC_TIMEOUT = 10.0
TUNNEL_PROBE_TIMEOUT = 0.5

FETCH_SEM_ACQUIRE_TIMEOUT = 5.0
BROWSER_SEM_ACQUIRE_TIMEOUT = 10.0
DEFAULT_MAX_FETCH = 2
MAX_FETCH_CAP = 4
DEFAULT_MAX_BROWSER = 1
MAX_BROWSER_CAP = 2
DEFAULT_COOLDOWN_S = 60.0

DEFAULT_FETCH_BIN = os.path.expanduser("~/src/xvm-debian-howto/scripts/mitnet-routing/fetch.py")
DEFAULT_BROWSER_BIN = os.path.expanduser("~/src/xvm-debian-howto/scripts/mitnet-routing/browserfetch.py")
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/firecrawl-mit-bridge")
DEFAULT_SOCKS_HOST = "127.0.0.1"
DEFAULT_SOCKS_PORT = 18830

MIT_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Challenge phrases matched on short Hyades bodies (aligns with firecrawl-router + fetch.py).
BRIDGE_CHALLENGE_RE = re.compile(
    r"client challenge|just a moment\.\.\.|attention required|verify you are (?:a )?human|"
    r"enable javascript and cookies|cf-chl|challenge-platform/[^\s\"'<>]{0,64}orchestrate",
    re.I,
)
BRIDGE_CHALLENGE_MAX_CHARS = 5000

# ---- URL canonicalization (byte-for-byte parity with fetch.py) -------------

BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


def valid_host(host: str) -> str | None:
    """Normalized ASCII lowercase FQDN, or None (IP literals, local names,
    numeric TLDs, '%', userinfo and non-ASCII are all refused)."""
    if not isinstance(host, str) or not host.isascii():
        return None
    host = host.lower()
    if host.endswith("."):
        host = host[:-1]
    if not host or len(host) > 253 or "%" in host or "@" in host:
        return None
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2 or not all(re.fullmatch(r"[a-z0-9-]{1,63}", x) for x in labels):
        return None
    if labels[-1].isdigit():
        return None
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        return None
    return host


def parse_url(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) for a CANONICAL plain http(s) URL, else None.
    Canonical means the host exactly as written is already the validated host
    (lowercase ASCII, no trailing dot) and any explicit port is 1-65535."""
    if not isinstance(url, str) or len(url) > 4096:
        return None
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url) or "\\" in url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    netloc = parts.netloc
    if parts.scheme not in ("http", "https") or not netloc.isascii():
        return None
    if "@" in netloc or "%" in netloc or "[" in netloc or "]" in netloc:
        return None
    raw_host, sep, raw_port = netloc.partition(":")
    host = valid_host(raw_host)
    if host is None or raw_host != host:
        return None
    default = 443 if parts.scheme == "https" else 80
    if not sep:
        return parts.scheme, host, default
    if not (raw_port.isascii() and raw_port.isdigit() and 1 <= int(raw_port) <= 65535):
        return None
    return parts.scheme, host, int(raw_port)


def redact_url(url: str) -> str:
    """Scheme + host[:port] + path only; drop userinfo, query, fragment."""
    p = urllib.parse.urlsplit(url)
    netloc = p.hostname or ""
    if p.port:
        netloc += f":{p.port}"
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path or "", "", ""))


# ---- Strict JSON & snapshot validation -------------------------------------


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key: {k}")
        out[k] = v
    return out


def _reject_constant(token: str) -> object:
    raise ValueError(f"non-finite JSON constant: {token}")


def _parse_strict_json(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _extract_enrolled_domains(snapshot: object) -> frozenset[str]:
    """Validate transport snapshot structure and extract canonical enrolled hosts."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("revision"), dict):
        raise ValueError("invalid snapshot")
    rev = snapshot["revision"]
    raw_b64 = rev.get("raw")
    etag = rev.get("etag")
    sha = rev.get("sha256")
    if not isinstance(raw_b64, str) or not isinstance(etag, str) or not etag.strip():
        raise ValueError("invalid revision metadata")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("invalid revision sha256")
    try:
        raw_bytes = base64.b64decode(raw_b64.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid revision raw base64") from exc
    if hashlib.sha256(raw_bytes).hexdigest() != sha:
        raise ValueError("revision sha256 mismatch")

    policy = rev.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    nodes = policy.get("nodeAttrs", [])
    if not isinstance(nodes, list):
        raise ValueError("nodeAttrs must be an array")
    matches = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("invalid nodeAttrs entry")
        apps = node.get("app", {})
        if not isinstance(apps, dict):
            raise ValueError("invalid nodeAttrs app")
        entries = apps.get(MANAGED_CAP, [])
        if not isinstance(entries, list) or not all(isinstance(x, dict) for x in entries):
            raise ValueError("invalid app entries")
        matches.extend(e for e in entries if e.get("name") == MANAGED_APP)
    if len(matches) > 1:
        raise ValueError("duplicate managed app")
    if not matches:
        return frozenset()
    names = matches[0].get("domains")
    if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
        raise ValueError("invalid managed app domains")
    canonical: set[str] = set()
    for name in names:
        h = valid_host(name)
        if h is None or h != name:
            raise ValueError("non-canonical enrolled host in snapshot")
        canonical.add(h)
    return frozenset(canonical)


class SnapshotCache:
    """Stat-cached, fail-closed loader for the operator enrollment snapshot."""

    def __init__(self, path: str, max_age: float = SNAPSHOT_MAX_AGE):
        self.path = path
        self.max_age = max_age
        self._lock = threading.Lock()
        self._key: tuple[int, int, int] | None = None
        self._domains: frozenset[str] = frozenset()

    def load(self) -> tuple[frozenset[str] | None, str]:
        """Return (domains, '') on valid non-empty snapshot, else (None, reason)."""
        if not self.path:
            return None, "snapshot-unset"
        now = time.time()
        try:
            lst = os.lstat(self.path)
        except OSError:
            return None, "snapshot-missing"
        if stat.S_ISLNK(lst.st_mode):
            return None, "snapshot-symlink"
        if not stat.S_ISREG(lst.st_mode):
            return None, "snapshot-not-regular"
        if lst.st_uid != os.getuid():
            return None, "snapshot-owner"
        if lst.st_mode & 0o022 != 0:
            return None, "snapshot-writable"
        if now - lst.st_mtime > self.max_age:
            return None, "snapshot-stale"
        if lst.st_size <= 0 or lst.st_size > SNAPSHOT_MAX_BYTES:
            return None, "snapshot-size"

        key = (lst.st_mtime_ns, lst.st_ino, lst.st_size)
        with self._lock:
            if self._key == key and self._domains:
                return self._domains, ""

        # Open with O_NOFOLLOW + fstat to prevent symlink TOCTOU swap.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except OSError:
            return None, "snapshot-open"
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return None, "snapshot-not-regular"
            if st.st_uid != os.getuid():
                return None, "snapshot-owner"
            if st.st_mode & 0o022 != 0:
                return None, "snapshot-writable"
            if time.time() - st.st_mtime > self.max_age:
                return None, "snapshot-stale"
            if st.st_size <= 0 or st.st_size > SNAPSHOT_MAX_BYTES:
                return None, "snapshot-size"
            with os.fdopen(fd, "rb") as fh:
                fd = -1
                raw = fh.read(SNAPSHOT_MAX_BYTES + 1)
        except OSError:
            return None, "snapshot-read"
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

        if len(raw) > SNAPSHOT_MAX_BYTES:
            return None, "snapshot-size"
        try:
            doc = _parse_strict_json(raw)
            domains = _extract_enrolled_domains(doc)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None, "snapshot-invalid"
        if not domains:
            return None, "snapshot-empty"

        key = (st.st_mtime_ns, st.st_ino, st.st_size)
        with self._lock:
            self._key = key
            self._domains = domains
        return domains, ""


# ---- Subprocess hygiene: scrubbed env, bounded reads, killpg ---------------


def scrubbed_env(
    base_env: dict[str, str] | None = None,
    *,
    include_ssh_auth_sock: bool = False,
    tmpdir: str | None = None,
) -> dict[str, str]:
    """Minimal allowlisted environment for bridge subprocesses.
    Zero FIRECRAWL_*, LITELLM_*, MIT_SIPB_*, or other daemon credentials."""
    src = os.environ if base_env is None else base_env
    env = {
        "PATH": src.get("PATH") or "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": src.get("HOME", ""),
        "LANG": src.get("LANG") or "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    if tmpdir:
        env["TMPDIR"] = tmpdir
    elif src.get("TMPDIR"):
        env["TMPDIR"] = src["TMPDIR"]
    if include_ssh_auth_sock and src.get("SSH_AUTH_SOCK"):
        env["SSH_AUTH_SOCK"] = src["SSH_AUTH_SOCK"]
    return env


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Terminate an entire subprocess session cleanly (SIGTERM -> SIGKILL)."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


@dataclass
class BoundedResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    stdout_truncated: bool = False


def run_bounded(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    max_stdout: int,
    max_stderr: int = MAX_STDERR_BYTES,
    stdin_bytes: bytes | None = None,
    kill_on_stdout_cap: bool = True,
) -> BoundedResult:
    """Run argv (shell=False, new session) with bounded stdout/stderr and killpg timeout."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    out_buf = bytearray()
    err_buf = bytearray()
    state = {"out_trunc": False, "killed_cap": False}

    def _read_stream(stream, buf: bytearray, cap: int, is_stdout: bool) -> None:
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                if len(buf) < cap:
                    take = min(len(chunk), cap - len(buf))
                    buf.extend(chunk[:take])
                    if take < len(chunk) and is_stdout:
                        state["out_trunc"] = True
                        if kill_on_stdout_cap:
                            state["killed_cap"] = True
                            _kill_process_group(proc)
                            break
                elif is_stdout:
                    state["out_trunc"] = True
                    if kill_on_stdout_cap:
                        state["killed_cap"] = True
                        _kill_process_group(proc)
                        break
        except OSError:
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _write_stdin() -> None:
        assert proc.stdin is not None
        try:
            if stdin_bytes:
                proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        except OSError:
            try:
                proc.stdin.close()
            except OSError:
                pass

    t_out = threading.Thread(target=_read_stream, args=(proc.stdout, out_buf, max_stdout, True), daemon=True)
    t_err = threading.Thread(target=_read_stream, args=(proc.stderr, err_buf, max_stderr, False), daemon=True)
    t_out.start()
    t_err.start()
    t_in = None
    if stdin_bytes is not None:
        t_in = threading.Thread(target=_write_stdin, daemon=True)
        t_in.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
    finally:
        if t_in is not None:
            t_in.join(timeout=2.0)
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        if proc.poll() is None:
            _kill_process_group(proc)

    return BoundedResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=bytes(out_buf),
        stderr=bytes(err_buf),
        timed_out=timed_out,
        stdout_truncated=state["out_trunc"],
    )


# ---- Safe file helpers inside private run dirs -----------------------------


def _safe_read_inside(run_dir: str, candidate_path: str | None, max_bytes: int) -> tuple[bytes | None, str]:
    """Read a regular non-symlink file inside run_dir with fstat size cap."""
    if not isinstance(candidate_path, str) or not candidate_path:
        return None, "missing-artifact"
    base_real = os.path.realpath(run_dir)
    cand_real = os.path.realpath(candidate_path)
    try:
        if os.path.commonpath([base_real, cand_real]) != base_real or cand_real == base_real:
            return None, "path-escape"
    except ValueError:
        return None, "path-escape"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate_path, flags)
    except OSError:
        return None, "artifact-open"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "artifact-not-regular"
        if st.st_size <= 0:
            return None, "artifact-empty"
        if st.st_size > max_bytes:
            return None, "artifact-too-large"
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            data = fh.read(max_bytes + 1)
    except OSError:
        return None, "artifact-read"
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
    if len(data) > max_bytes:
        return None, "artifact-too-large"
    return data, ""


def _safe_stat_inside(run_dir: str, candidate_path: str | None, max_bytes: int) -> tuple[str | None, str]:
    """Verify candidate_path is a regular non-symlink file inside run_dir <= max_bytes."""
    if not isinstance(candidate_path, str) or not candidate_path:
        return None, "missing-artifact"
    base_real = os.path.realpath(run_dir)
    cand_real = os.path.realpath(candidate_path)
    try:
        if os.path.commonpath([base_real, cand_real]) != base_real or cand_real == base_real:
            return None, "path-escape"
    except ValueError:
        return None, "path-escape"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate_path, flags)
    except OSError:
        return None, "artifact-open"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "artifact-not-regular"
        if st.st_size <= 0:
            return None, "artifact-empty"
        if st.st_size > max_bytes:
            return None, "artifact-too-large"
        head = os.read(fd, 5)
    except OSError:
        return None, "artifact-read"
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    if head != b"%PDF-":
        return None, "not-pdf-magic"
    return cand_real, ""


def _decode_capped_utf8(raw: bytes, max_bytes: int) -> tuple[str, bool]:
    truncated = len(raw) > max_bytes
    sliced = raw[:max_bytes]
    # errors="ignore" cleanly drops any trailing partial multi-byte UTF-8 sequence.
    return sliced.decode("utf-8", "ignore"), truncated


def _sanitize_stderr(raw: bytes) -> str:
    txt = raw[:MAX_STDERR_BYTES].decode("utf-8", "replace")
    txt = CONTROL_CHARS_RE.sub("", txt)
    return " ".join(txt.split())[:200]


# ---- Request & Hyades-reply inspection helpers -----------------------------


def is_pdf_target(url: str, req_doc: dict) -> bool:
    """True when the target URL or request options indicate a PDF scrape."""
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(".pdf") or "/pdf/" in path or "/content/view/" in path:
        return True
    parsers = req_doc.get("parsers")
    if isinstance(parsers, list):
        for item in parsers:
            if item == "pdf":
                return True
            if isinstance(item, dict) and item.get("type") == "pdf":
                return True
    return False


def requested_pdf_max_pages(req_doc: dict) -> int:
    """Extract pdfOptions.maxPages or parsers[{type:pdf, maxPages}], clamped 1..HARD_PDF_MAX_PAGES."""
    val = None
    pdf_opts = req_doc.get("pdfOptions")
    if isinstance(pdf_opts, dict):
        val = pdf_opts.get("maxPages")
    if val is None:
        parsers = req_doc.get("parsers")
        if isinstance(parsers, list):
            for item in parsers:
                if isinstance(item, dict) and item.get("type") == "pdf" and "maxPages" in item:
                    val = item.get("maxPages")
                    break
    if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
        return min(val, HARD_PDF_MAX_PAGES)
    return DEFAULT_PDF_MAX_PAGES


def requested_formats(req_doc: dict) -> set[str]:
    """Return the set of requested Firecrawl output format names."""
    formats = req_doc.get("formats")
    if not isinstance(formats, list):
        return {"markdown"}
    out: set[str] = set()
    for f in formats:
        if isinstance(f, str):
            out.add(f)
        elif isinstance(f, dict) and isinstance(f.get("type"), str):
            out.add(f["type"])
    return out or {"markdown"}


def needs_pdf_bridge(primary_reply, target_host: str) -> bool:
    """True when Hyades failed to deliver a valid parsed PDF for an enrolled PDF URL."""
    if primary_reply.status != 200:
        return True
    doc = primary_reply.json()
    if not isinstance(doc, dict) or doc.get("success") is not True:
        return True
    data = doc.get("data")
    if not isinstance(data, dict):
        return True
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if meta.get("statusCode") not in (None, 200):
        return True
    ctype = str(meta.get("contentType") or "").lower().split(";", 1)[0].strip()
    if ctype and ctype != "application/pdf":
        return True
    # Check if Hyades landed on an IdP host (e.g., idp.nature.com).
    for key in ("url", "sourceURL"):
        landed = meta.get(key)
        if isinstance(landed, str):
            lp = parse_url(landed)
            if lp and lp[1] != target_host and lp[1].startswith("idp."):
                return True
    md = data.get("markdown")
    if not isinstance(md, str) or not md.strip():
        return True
    if len(md) < BRIDGE_CHALLENGE_MAX_CHARS and BRIDGE_CHALLENGE_RE.search(md):
        return True
    # If contentType wasn't reported as application/pdf, require non-HTML heuristic only
    # when statusCode was missing; if contentType is empty and markdown looks like real
    # text (not a challenge), treat Hyades as succeeded unless contentType explicitly mismatched.
    return False


def needs_browser_bridge(primary_reply, fallback_reason_str: str) -> bool:
    """True when Hyades hit a bot wall, transport error, or failure recoverable by browserfetch."""
    if primary_reply.status != 200:
        return True
    if fallback_reason_str:
        return True
    doc = primary_reply.json()
    if not isinstance(doc, dict) or doc.get("success") is not True:
        return True
    data = doc.get("data")
    if not isinstance(data, dict):
        return True
    md = data.get("markdown")
    if isinstance(md, str) and len(md) < BRIDGE_CHALLENGE_MAX_CHARS and BRIDGE_CHALLENGE_RE.search(md):
        return True
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    code = meta.get("statusCode")
    if code in (403, 405, 429, 503):
        return True
    if code == 202 and (not isinstance(md, str) or len(md.strip()) < BRIDGE_CHALLENGE_MAX_CHARS):
        return True
    return False


def _extract_html_title(html_text: str) -> str:
    m = TITLE_RE.search(html_text[:32768])
    if not m:
        return ""
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
    return " ".join(title.split())[:300]


# ---- Bridge configuration & runtime ----------------------------------------


@dataclass
class MitBridgeConfig:
    mode: str = "off"  # "off" | "pdf" | "all"
    snapshot_path: str = ""
    fetch_bin: str = DEFAULT_FETCH_BIN
    browser_bin: str = DEFAULT_BROWSER_BIN
    python_bin: str = sys.executable
    mit_host: str = ""
    chrome_bin: str = ""
    socks_host: str = DEFAULT_SOCKS_HOST
    socks_port: int = DEFAULT_SOCKS_PORT
    state_dir: str = DEFAULT_STATE_DIR
    max_fetch: int = DEFAULT_MAX_FETCH
    max_browser: int = DEFAULT_MAX_BROWSER
    pdftotext_bin: str = ""
    pdfinfo_bin: str = ""
    pandoc_bin: str = ""
    cooldown_s: float = DEFAULT_COOLDOWN_S
    fetch_cli_timeout: int = FETCH_CLI_TIMEOUT
    fetch_kill_timeout: float = FETCH_KILL_TIMEOUT
    browser_cli_timeout: int = BROWSER_CLI_TIMEOUT
    browser_kill_timeout: float = BROWSER_KILL_TIMEOUT
    pdftotext_timeout: float = PDFTOTEXT_TIMEOUT
    pdfinfo_timeout: float = PDFINFO_TIMEOUT
    pandoc_timeout: float = PANDOC_TIMEOUT
    fetch_sem_timeout: float = FETCH_SEM_ACQUIRE_TIMEOUT
    browser_sem_timeout: float = BROWSER_SEM_ACQUIRE_TIMEOUT


def _parse_int_clamped(raw: str | None, default: int, lo: int, hi: int) -> int:
    try:
        v = int(raw) if raw is not None and raw != "" else default
    except ValueError:
        return default
    return max(lo, min(hi, v))


def _resolve_bin(env_val: str | None, name: str, fallback: str) -> str:
    if env_val:
        return env_val
    return shutil.which(name) or fallback


def build_mit_bridge(env: dict[str, str], log=sys.stderr) -> MitBridge | None:
    """Build a MitBridge from environment variables, or None when disabled."""
    raw_mode = (env.get("FIRECRAWL_ROUTER_MIT_BRIDGE") or "off").strip().lower()
    if raw_mode not in VALID_MODES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_MIT_BRIDGE={raw_mode!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        return None
    if raw_mode == "off":
        return None
    snapshot_path = (env.get("FIRECRAWL_ROUTER_MIT_SNAPSHOT") or "").strip()
    if not snapshot_path:
        print(
            "firecrawl-router: FIRECRAWL_ROUTER_MIT_BRIDGE enabled without FIRECRAWL_ROUTER_MIT_SNAPSHOT; failing closed",
            file=log,
            flush=True,
        )
        return None
    mit_host = (env.get("FIRECRAWL_ROUTER_MIT_HOST") or "").strip()
    if mit_host and not MIT_HOST_RE.fullmatch(mit_host):
        print("firecrawl-router: invalid FIRECRAWL_ROUTER_MIT_HOST; failing closed", file=log, flush=True)
        return None
    socks_host = (env.get("FIRECRAWL_ROUTER_MIT_SOCKS_HOST") or DEFAULT_SOCKS_HOST).strip()
    if socks_host not in ("127.0.0.1", "localhost", "::1"):
        print("firecrawl-router: FIRECRAWL_ROUTER_MIT_SOCKS_HOST must be loopback; failing closed", file=log, flush=True)
        return None
    socks_port = _parse_int_clamped(env.get("FIRECRAWL_ROUTER_MIT_SOCKS_PORT"), DEFAULT_SOCKS_PORT, 1, 65535)
    max_fetch = _parse_int_clamped(env.get("FIRECRAWL_ROUTER_MIT_MAX_FETCH"), DEFAULT_MAX_FETCH, 1, MAX_FETCH_CAP)
    max_browser = _parse_int_clamped(env.get("FIRECRAWL_ROUTER_MIT_MAX_BROWSER"), DEFAULT_MAX_BROWSER, 1, MAX_BROWSER_CAP)
    try:
        cooldown_s = max(0.0, float(env.get("FIRECRAWL_ROUTER_MIT_COOLDOWN_S") or DEFAULT_COOLDOWN_S))
    except ValueError:
        cooldown_s = DEFAULT_COOLDOWN_S

    cfg = MitBridgeConfig(
        mode=raw_mode,
        snapshot_path=snapshot_path,
        fetch_bin=(env.get("FIRECRAWL_ROUTER_MIT_FETCH_BIN") or DEFAULT_FETCH_BIN).strip(),
        browser_bin=(env.get("FIRECRAWL_ROUTER_MIT_BROWSER_BIN") or DEFAULT_BROWSER_BIN).strip(),
        python_bin=(env.get("FIRECRAWL_ROUTER_MIT_PYTHON") or sys.executable).strip(),
        mit_host=mit_host,
        chrome_bin=(env.get("FIRECRAWL_ROUTER_MIT_CHROME") or "").strip(),
        socks_host=socks_host,
        socks_port=socks_port,
        state_dir=(env.get("FIRECRAWL_ROUTER_MIT_STATE_DIR") or DEFAULT_STATE_DIR).strip(),
        max_fetch=max_fetch,
        max_browser=max_browser,
        pdftotext_bin=_resolve_bin(env.get("FIRECRAWL_ROUTER_MIT_PDFTOTEXT_BIN"), "pdftotext", "/opt/homebrew/bin/pdftotext"),
        pdfinfo_bin=_resolve_bin(env.get("FIRECRAWL_ROUTER_MIT_PDFINFO_BIN"), "pdfinfo", "/opt/homebrew/bin/pdfinfo"),
        pandoc_bin=_resolve_bin(env.get("FIRECRAWL_ROUTER_MIT_PANDOC_BIN"), "pandoc", "/opt/homebrew/bin/pandoc"),
        cooldown_s=cooldown_s,
    )
    return MitBridge(cfg, log=log)


class MitBridge:
    """Mac-side MIT Libraries scrape bridge for enrolled hosts."""

    def __init__(self, config: MitBridgeConfig, log=sys.stderr, reply_cls=None):
        self.config = config
        self.log = log
        self._reply_cls = reply_cls
        self.snapshot = SnapshotCache(config.snapshot_path)
        self.fetch_sem = threading.BoundedSemaphore(config.max_fetch)
        self.browser_sem = threading.BoundedSemaphore(config.max_browser)
        self._cooldown_lock = threading.Lock()
        self._cooldowns: dict[tuple[str, str], float] = {}
        if self.enabled:
            self._ensure_private_state_dir()
            self.sweep_orphans()

    @property
    def enabled(self) -> bool:
        return self.config.mode in ("pdf", "all") and bool(self.config.snapshot_path)

    # -- private state dir & startup sweep

    def _ensure_private_state_dir(self) -> bool:
        base = self.config.state_dir
        try:
            os.makedirs(base, mode=0o700, exist_ok=True)
            st = os.lstat(base)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                return False
            if st.st_uid != os.getuid():
                return False
            if st.st_mode & 0o077 != 0:
                os.chmod(base, 0o700)
            return True
        except OSError:
            return False

    def sweep_orphans(self) -> None:
        """Delete leftover run-* dirs from a prior crash/SIGKILL."""
        base = self.config.state_dir
        try:
            st = os.lstat(base)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                return
            if st.st_uid != os.getuid() or st.st_mode & 0o022 != 0:
                return
            entries = list(os.scandir(base))
        except OSError:
            return
        for entry in entries:
            if not entry.name.startswith("run-"):
                continue
            try:
                est = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(est.st_mode) and est.st_uid == os.getuid():
                    shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:
                pass

    # -- cooldown & tunnel pre-flight

    def _in_cooldown(self, host: str, lane: str) -> bool:
        if self.config.cooldown_s <= 0:
            return False
        now = time.monotonic()
        with self._cooldown_lock:
            exp = self._cooldowns.get((host, lane), 0.0)
            if now < exp:
                return True
            if exp:
                self._cooldowns.pop((host, lane), None)
            return False

    def _set_cooldown(self, host: str, lane: str) -> None:
        if self.config.cooldown_s <= 0:
            return
        with self._cooldown_lock:
            self._cooldowns[(host, lane)] = time.monotonic() + self.config.cooldown_s

    def _tunnel_listening(self) -> bool:
        try:
            with socket.create_connection(
                (self.config.socks_host, self.config.socks_port),
                timeout=TUNNEL_PROBE_TIMEOUT,
            ):
                return True
        except OSError:
            return False

    # -- request eligibility

    def _parse_scrape_request(self, method: str, path: str, body: bytes | None) -> tuple[dict, str, tuple[str, str, int]] | None:
        if method != "POST":
            return None
        route = path.split("?", 1)[0].rstrip("/")
        if route not in SCRAPE_ROUTES:
            return None
        try:
            doc = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        url = doc.get("url")
        if not isinstance(url, str):
            return None
        parsed = parse_url(url)
        if parsed is None:
            return None
        return doc, url, parsed

    def is_enrolled_request(self, method: str, path: str, body: bytes | None) -> bool:
        """True if this is a POST /v{1,2}/scrape for an exact enrolled host in a valid snapshot."""
        if not self.enabled:
            return False
        parsed_req = self._parse_scrape_request(method, path, body)
        if parsed_req is None:
            return False
        _, _, (_, host, _) = parsed_req
        domains, _ = self.snapshot.load()
        return domains is not None and host in domains

    # -- main bridge entry point (fail-closed)

    def maybe_bridge(
        self,
        method: str,
        path: str,
        body: bytes | None,
        primary_reply,
        fallback_reason_str: str,
        reply_cls=None,
    ) -> tuple[object | None, str | None, str]:
        """Try bridging an enrolled scrape after Hyades returned `primary_reply`.

        Returns:
          (Reply, backend_name, note) when bridged successfully;
          (None, None, reason_tag) when skipped or failed closed (caller returns primary_reply).
        """
        rcls = reply_cls or self._reply_cls or type(primary_reply)
        if not self.enabled:
            return None, None, ""
        if method != "POST":
            return None, None, ""
        route = path.split("?", 1)[0].rstrip("/")
        if route not in SCRAPE_ROUTES:
            return None, None, ""
        try:
            req_doc = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None, None, ""
        if not isinstance(req_doc, dict) or not isinstance(req_doc.get("url"), str):
            return None, None, ""
        url = req_doc["url"]
        parsed = parse_url(url)
        if parsed is None:
            return None, None, "url-refused"
        scheme, host, port = parsed

        domains, snap_err = self.snapshot.load()
        if domains is None:
            return None, None, snap_err
        if host not in domains:
            return None, None, ""

        pdf_target = is_pdf_target(url, req_doc)
        try:
            # Lane 1: PDF via fetch.py
            if pdf_target and needs_pdf_bridge(primary_reply, host):
                reply, reason = self._run_fetch_lane(url, host, req_doc, rcls)
                if reply is not None:
                    return reply, "mit-fetch", "pdf-bridged"
                # If fetch.py failed and browser lane is enabled, fall through on https:443.
                if self.config.mode == "all" and scheme == "https" and port == 443:
                    b_reply, b_reason = self._run_browser_lane(url, host, req_doc, True, rcls)
                    if b_reply is not None:
                        return b_reply, "mit-browser", "browser-pdf-bridged"
                    return None, None, f"{reason};{b_reason}"
                return None, None, reason

            # Lane 2: Cloudflare / bot-walled HTML (or non-PDF) via browserfetch.py
            if needs_browser_bridge(primary_reply, fallback_reason_str):
                if self.config.mode != "all":
                    return None, None, "mode-pdf-only"
                if scheme != "https" or port != 443:
                    return None, None, "browser-requires-https-443"
                b_reply, b_reason = self._run_browser_lane(url, host, req_doc, pdf_target, rcls)
                if b_reply is not None:
                    return b_reply, "mit-browser", "browser-bridged"
                return None, None, b_reason

            return None, None, "primary-ok"
        except Exception:  # noqa: BLE001 - fail closed unconditionally
            return None, None, "internal-error"

    # -- Lane 1: fetch.py -> pdftotext / pdfinfo

    def _run_fetch_lane(self, url: str, host: str, req_doc: dict, reply_cls) -> tuple[object | None, str]:
        if self._in_cooldown(host, "mit-fetch"):
            return None, "cooldown"
        if not os.path.isfile(self.config.fetch_bin):
            return None, "fetch-bin-missing"
        if not os.path.isfile(self.config.pdftotext_bin) or not os.access(self.config.pdftotext_bin, os.X_OK):
            return None, "pdftotext-missing"
        if not self._ensure_private_state_dir():
            return None, "state-dir-invalid"
        if not self.fetch_sem.acquire(timeout=self.config.fetch_sem_timeout):
            return None, "busy"
        run_dir = None
        try:
            run_dir = tempfile.mkdtemp(prefix="run-", dir=self.config.state_dir)
            os.chmod(run_dir, 0o700)
            argv = [
                self.config.python_bin,
                "-I",
                self.config.fetch_bin,
                "fetch",
                "--artifact",
                "--enrolled-only",
                "--enrolled-snapshot",
                self.config.snapshot_path,
                "--output",
                run_dir,
                "--timeout",
                str(self.config.fetch_cli_timeout),
            ]
            if self.config.mit_host:
                argv.extend(["--mit-host", self.config.mit_host])
            argv.extend(["--", url])
            env = scrubbed_env(include_ssh_auth_sock=True, tmpdir=run_dir)
            res = run_bounded(
                argv,
                env=env,
                timeout=self.config.fetch_kill_timeout,
                max_stdout=MAX_JSON_STDOUT_BYTES,
            )
            if res.timed_out:
                self._set_cooldown(host, "mit-fetch")
                return None, "fetch-timeout"
            if res.returncode != 0 or res.stdout_truncated:
                return None, f"fetch-rc-{res.returncode}"
            try:
                meta = json.loads(res.stdout.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None, "fetch-bad-json"
            if not isinstance(meta, dict):
                return None, "fetch-bad-json"
            mit = meta.get("mit")
            ev = meta.get("evidence")
            if not isinstance(mit, dict) or not isinstance(ev, dict):
                return None, "fetch-bad-json"
            mit_cls = str(mit.get("class") or "unknown")
            if mit_cls in ("botwall", "transport"):
                self._set_cooldown(host, "mit-fetch")
                return None, f"fetch-{mit_cls}"
            if mit_cls != "ok" or mit.get("content_is_pdf") is not True:
                return None, f"fetch-not-pdf-{mit_cls}"
            body_path, err = _safe_stat_inside(run_dir, ev.get("mit_body"), MAX_PDF_BYTES)
            if body_path is None:
                return None, err
            return self._convert_pdf_reply(body_path, url, req_doc, run_dir, reply_cls)
        finally:
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)
            self.fetch_sem.release()

    # -- Lane 2: browserfetch.py -> pdftotext OR pandoc --sandbox / page.txt

    def _run_browser_lane(
        self,
        url: str,
        host: str,
        req_doc: dict,
        want_artifact: bool,
        reply_cls,
    ) -> tuple[object | None, str]:
        if self._in_cooldown(host, "mit-browser"):
            return None, "cooldown"
        if not os.path.isfile(self.config.browser_bin):
            return None, "browser-bin-missing"
        if not self._tunnel_listening():
            self._set_cooldown(host, "mit-browser")
            return None, "tunnel-down"
        if not self._ensure_private_state_dir():
            return None, "state-dir-invalid"
        if not self.browser_sem.acquire(timeout=self.config.browser_sem_timeout):
            return None, "busy"
        run_dir = None
        try:
            run_dir = tempfile.mkdtemp(prefix="run-", dir=self.config.state_dir)
            os.chmod(run_dir, 0o700)
            argv = [
                self.config.python_bin,
                "-I",
                self.config.browser_bin,
                "--enrolled-snapshot",
                self.config.snapshot_path,
                "--output",
                run_dir,
                "--timeout",
                str(self.config.browser_cli_timeout),
            ]
            if want_artifact:
                argv.append("--artifact")
            if self.config.chrome_bin:
                argv.extend(["--chrome", self.config.chrome_bin])
            argv.extend(["--", url])
            env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir)
            res = run_bounded(
                argv,
                env=env,
                timeout=self.config.browser_kill_timeout,
                max_stdout=MAX_JSON_STDOUT_BYTES,
            )
            if res.timed_out:
                self._set_cooldown(host, "mit-browser")
                return None, "browser-timeout"
            if res.stdout_truncated:
                return None, "browser-bad-json"
            meta = None
            if res.stdout:
                try:
                    meta = json.loads(res.stdout.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    meta = None
            if not isinstance(meta, dict):
                return None, f"browser-rc-{res.returncode}"
            cls = str(meta.get("class") or "unknown")
            if cls in ("botwall", "transport"):
                self._set_cooldown(host, "mit-browser")
                return None, f"browser-{cls}"
            if res.returncode != 0 or cls != "ok":
                return None, f"browser-{cls}"
            ev = meta.get("evidence")
            if not isinstance(ev, dict):
                return None, "browser-bad-json"

            if meta.get("content_is_pdf") is True:
                if not os.path.isfile(self.config.pdftotext_bin) or not os.access(self.config.pdftotext_bin, os.X_OK):
                    return None, "pdftotext-missing"
                body_path, err = _safe_stat_inside(run_dir, ev.get("body"), MAX_PDF_BYTES)
                if body_path is None:
                    return None, err
                return self._convert_pdf_reply(body_path, url, req_doc, run_dir, reply_cls)

            if want_artifact:
                return None, "browser-not-pdf"

            status_code = meta.get("status") if isinstance(meta.get("status"), int) else 200
            return self._convert_html_reply(ev.get("body"), ev.get("text"), url, req_doc, run_dir, status_code, reply_cls)
        finally:
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)
            self.browser_sem.release()

    # -- Converters & Firecrawl v2 JSON synthesis

    def _convert_pdf_reply(
        self,
        pdf_path: str,
        url: str,
        req_doc: dict,
        run_dir: str,
        reply_cls,
    ) -> tuple[object | None, str]:
        max_pages = requested_pdf_max_pages(req_doc)
        env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir)
        argv = [
            self.config.pdftotext_bin,
            "-q",
            "-enc",
            "UTF-8",
            "-nopgbrk",
            "-l",
            str(max_pages),
            "--",
            pdf_path,
            "-",
        ]
        res = run_bounded(
            argv,
            env=env,
            timeout=self.config.pdftotext_timeout,
            max_stdout=MAX_MARKDOWN_BYTES + 1,
            kill_on_stdout_cap=True,
        )
        if res.timed_out:
            return None, "pdftotext-timeout"
        if res.returncode != 0 and not res.stdout_truncated:
            return None, "pdftotext-failed"
        md, truncated = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
        truncated = truncated or res.stdout_truncated
        if not md.strip():
            return None, "pdftotext-empty"

        num_pages, title = self._read_pdfinfo(pdf_path, env)
        safe_url = redact_url(url)
        metadata: dict[str, object] = {
            "sourceURL": safe_url,
            "url": safe_url,
            "statusCode": 200,
            "contentType": "application/pdf",
            "proxyUsed": "mit-bridge",
        }
        if num_pages is not None:
            metadata["numPages"] = num_pages
        if title:
            metadata["title"] = title

        data: dict[str, object] = {"markdown": md, "metadata": metadata}
        warnings = []
        if truncated:
            warnings.append("Extracted PDF markdown truncated to 2 MiB.")
        if num_pages is not None and num_pages > max_pages:
            warnings.append(f"PDF truncated to first {max_pages} of {num_pages} pages.")
        if warnings:
            data["warning"] = " ".join(warnings)
        payload = json.dumps({"success": True, "data": data}).encode("utf-8")
        return reply_cls(200, {"Content-Type": "application/json"}, payload), ""

    def _read_pdfinfo(self, pdf_path: str, env: dict[str, str]) -> tuple[int | None, str]:
        if not self.config.pdfinfo_bin or not os.path.isfile(self.config.pdfinfo_bin) or not os.access(self.config.pdfinfo_bin, os.X_OK):
            return None, ""
        res = run_bounded(
            [self.config.pdfinfo_bin, "-enc", "UTF-8", "--", pdf_path],
            env=env,
            timeout=self.config.pdfinfo_timeout,
            max_stdout=MAX_PDFINFO_STDOUT_BYTES,
            kill_on_stdout_cap=True,
        )
        if res.timed_out or res.returncode != 0:
            return None, ""
        num_pages = None
        title = ""
        for line in res.stdout.decode("utf-8", "replace").splitlines():
            key, sep, val = line.partition(":")
            if not sep:
                continue
            k = key.strip().lower()
            v = val.strip()
            if k == "pages" and v.isdigit():
                num_pages = int(v)
            elif k == "title" and v:
                title = CONTROL_CHARS_RE.sub("", v)[:300]
        return num_pages, title

    def _convert_html_reply(
        self,
        html_path: str | None,
        text_path: str | None,
        url: str,
        req_doc: dict,
        run_dir: str,
        status_code: int,
        reply_cls,
    ) -> tuple[object | None, str]:
        html_bytes, html_err = _safe_read_inside(run_dir, html_path, MAX_HTML_BYTES)
        env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir)
        md = ""
        truncated = False
        used_fallback_txt = False

        if html_bytes is not None and self.config.pandoc_bin and os.path.isfile(self.config.pandoc_bin) and os.access(self.config.pandoc_bin, os.X_OK):
            res = run_bounded(
                [self.config.pandoc_bin, "--sandbox", "-f", "html", "-t", "gfm-raw_html", "--wrap=none"],
                env=env,
                timeout=self.config.pandoc_timeout,
                max_stdout=MAX_MARKDOWN_BYTES + 1,
                stdin_bytes=html_bytes,
                kill_on_stdout_cap=True,
            )
            if not res.timed_out and (res.returncode == 0 or res.stdout_truncated):
                cand, trunc = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
                if cand.strip():
                    md = cand
                    truncated = trunc or res.stdout_truncated

        if not md.strip():
            txt_bytes, txt_err = _safe_read_inside(run_dir, text_path, MAX_HTML_BYTES)
            if txt_bytes is None:
                return None, html_err or txt_err or "html-convert-failed"
            md, truncated = _decode_capped_utf8(txt_bytes, MAX_MARKDOWN_BYTES)
            if not md.strip():
                return None, "html-empty"
            used_fallback_txt = True

        safe_url = redact_url(url)
        html_str = html_bytes.decode("utf-8", "replace") if html_bytes is not None else ""
        title = _extract_html_title(html_str) if html_str else ""
        metadata: dict[str, object] = {
            "sourceURL": safe_url,
            "url": safe_url,
            "statusCode": status_code,
            "contentType": "text/html; charset=utf-8",
            "proxyUsed": "mit-bridge",
        }
        if title:
            metadata["title"] = title

        fmts = requested_formats(req_doc)
        data: dict[str, object] = {"markdown": md, "metadata": metadata}
        if html_bytes is not None:
            if "html" in fmts:
                data["html"] = _decode_capped_utf8(html_bytes, MAX_MARKDOWN_BYTES)[0]
            if "rawHtml" in fmts:
                data["rawHtml"] = _decode_capped_utf8(html_bytes, MAX_MARKDOWN_BYTES)[0]
        warnings = []
        if truncated:
            warnings.append("Extracted HTML content truncated to 2 MiB.")
        if used_fallback_txt:
            warnings.append("Used plain text fallback (pandoc unavailable or failed).")
        if warnings:
            data["warning"] = " ".join(warnings)
        payload = json.dumps({"success": True, "data": data}).encode("utf-8")
        return reply_cls(200, {"Content-Type": "application/json"}, payload), ""
