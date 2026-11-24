"""firecrawl_wiley_tdm: Opt-in Wiley TDM PDF API lane for bin/firecrawl-router (stdlib only).

Feature-flagged (default OFF: FIRECRAWL_ROUTER_WILEY_TDM=off; supports "off" | "on" | "auto"),
Hyades-first + OA-first, fail-closed full-text PDF lane scoped strictly to POST /v1/scrape
and POST /v2/scrape for Wiley Online Library URLs / Wiley DOIs when Hyades and Open Access
fallback both failed.

How it works:
  1. Loads WILEY_TDM_TOKEN (UUID) lazily in memory via sudo-secretspec (KeyState) — never in
     LaunchAgent plists, argv, os.environ, URLs, logs, or exceptions.
  2. Connects to https://api.wiley.com:443/onlinelibrary/tdm/v1/articles/{encoded_doi} over
     the loopback SOCKS5 tunnel (default 127.0.0.1:18830 -> pastebin MIT IP) using RFC 1928
     ATYP=0x03 (remote DNS on MIT host) and end-to-end TLS (CERT_REQUIRED, check_hostname,
     TLSv1.2+, server_hostname="api.wiley.com") so the SSH hop never sees the token or PDF.
  3. Enforces Wiley's published rate limits client-side (default >= 10.0 s spacing and <= 60
     requests per 10-minute sliding window, max 1 concurrent request, non-blocking fail-closed).
  4. Strips Wiley-TDM-Client-Token unconditionally on any 3xx redirect and follows presigned
     HTTPS:443 redirects only through SSRF-pinned global-IP connections.
  5. Validates %PDF- magic + %%EOF tail, converts in a private 0700 temp dir via pdftotext +
     pdfinfo with scrubbed_env() and killpg teardown, and returns a Firecrawl v2 JSON response
     with backend "wiley-tdm" and mandatory provenance warning.
  6. Router._scrape_with_llm() blocks third-party cloud LLM extraction on backend "wiley-tdm"
     by default (FIRECRAWL_ROUTER_WILEY_ALLOW_CLOUD_LLM=off) to respect Wiley Terms of Use.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import http.client
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import stat
import struct
import sys
import tempfile
import threading
import time
import urllib.parse


def _load_sibling(name: str, filename: str):
    if name in sys.modules:
        return sys.modules[name]
    mod_path = Path(__file__).resolve().parent / filename
    if not mod_path.is_file():
        raise ImportError(f"firecrawl_wiley_tdm: sibling missing: {mod_path}")
    spec = importlib.util.spec_from_file_location(name, str(mod_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"firecrawl_wiley_tdm: cannot load sibling: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_MB = _load_sibling("firecrawl_mit_bridge", "firecrawl_mit_bridge.py")
_OA = _load_sibling("firecrawl_oa_fallback", "firecrawl_oa_fallback.py")

parse_url = _MB.parse_url
redact_url = _MB.redact_url
scrubbed_env = _MB.scrubbed_env
run_bounded = _MB.run_bounded
_decode_capped_utf8 = _MB._decode_capped_utf8
_safe_stat_inside = _MB._safe_stat_inside
requested_pdf_max_pages = _MB.requested_pdf_max_pages
CONTROL_CHARS_RE = _MB.CONTROL_CHARS_RE
MAX_PDF_BYTES = _MB.MAX_PDF_BYTES
MAX_MARKDOWN_BYTES = _MB.MAX_MARKDOWN_BYTES
MAX_PDFINFO_STDOUT_BYTES = _MB.MAX_PDFINFO_STDOUT_BYTES
PDFTOTEXT_TIMEOUT = _MB.PDFTOTEXT_TIMEOUT
PDFINFO_TIMEOUT = _MB.PDFINFO_TIMEOUT
ORPHAN_MIN_AGE_S = _MB.ORPHAN_MIN_AGE_S
SCRAPE_ROUTES = _MB.SCRAPE_ROUTES
_parse_int_clamped = _MB._parse_int_clamped
_resolve_bin = _MB._resolve_bin

extract_identifier = _OA.extract_identifier
normalize_doi = _OA.normalize_doi
needs_oa_fallback = _OA.needs_oa_fallback
resolve_global = _OA.resolve_global
_make_ssl_context = _OA._make_ssl_context
_PinnedHTTPSConnection = _OA._PinnedHTTPSConnection
_read_bounded_response = _OA._read_bounded_response
_safe_reason_tag = _OA._safe_reason_tag
KeyState = _OA.KeyState
load_secret_key = _OA.load_secret_key


# ---- Constants -------------------------------------------------------------

VALID_WILEY_MODES = frozenset(("off", "on", "auto"))
VALID_ON_OFF = frozenset(("on", "off"))

WILEY_API_HOST = "api.wiley.com"
WILEY_API_PREFIX = "/onlinelibrary/tdm/v1/articles/"
WILEY_USER_AGENT = "firecrawl-router-wiley-tdm/1.0"

WILEY_DOI_PREFIXES = (
    "10.1002/",
    "10.1111/",
    "10.1029/",
    "10.1113/",
    "10.1046/",
    "10.1049/",
    "10.1096/",
    "10.1100/",
    "10.15252/",
)

SAFE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    re.ASCII,
)

WILEY_SECRET_NAME = "WILEY_TDM_TOKEN"
WILEY_SECRET_REASON = "firecrawl-router: Wiley TDM API token (memory only)"
DEFAULT_SECRETSPEC_BIN = "/usr/local/bin/sudo-secretspec"
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/firecrawl-wiley-tdm")
DEFAULT_SOCKS_HOST = "127.0.0.1"
DEFAULT_SOCKS_PORT = 18830

DEFAULT_MIN_SPACING_S = 10.0
MIN_SPACING_FLOOR_S = 5.0
MAX_SPACING_CAP_S = 120.0
DEFAULT_MAX_PER_10MIN = 60
RATE_WINDOW_S = 600.0

FETCH_CONNECT_TIMEOUT_S = 8.0
FETCH_DEADLINE_S = 35.0
TOTAL_WILEY_BUDGET_S = 45.0
MAX_REDIRECTS = 5

WILEY_401_COOLDOWN_S = 600.0
WILEY_403_COOLDOWN_S = 60.0
WILEY_429_COOLDOWN_S = 120.0
WILEY_5XX_COOLDOWN_S = 30.0


def is_wiley_target(host: str, doi: str) -> bool:
    """True when the request targets a Wiley Online Library host or known Wiley DOI prefix."""
    h = (host or "").strip().lower()
    d = (doi or "").strip().lower()
    if not d:
        return False
    if h == "onlinelibrary.wiley.com" or h.endswith(".onlinelibrary.wiley.com"):
        return True
    if h in ("doi.org", "dx.doi.org") and any(d.startswith(p) for p in WILEY_DOI_PREFIXES):
        return True
    return False


def _is_loopback_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address((host or "").strip()).is_loopback
    except ValueError:
        return False


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("socks5: unexpected EOF")
        buf.extend(chunk)
    return bytes(buf)


def socks5_connect(
    socks_host: str,
    socks_port: int,
    dest_host: str,
    dest_port: int,
    timeout: float,
) -> socket.socket:
    """Open a TCP socket to dest_host:dest_port via loopback SOCKS5 (ATYP=0x03 remote DNS)."""
    if not _is_loopback_ip(socks_host):
        raise ValueError("socks5: proxy host must be a loopback IP literal")
    if not (1 <= int(socks_port) <= 65535):
        raise ValueError("socks5: invalid proxy port")
    host_b = dest_host.encode("ascii")
    if not host_b or len(host_b) > 255:
        raise ValueError("socks5: invalid target hostname")
    if not (1 <= int(dest_port) <= 65535):
        raise ValueError("socks5: invalid target port")

    sock = socket.create_connection((socks_host, int(socks_port)), timeout=max(0.5, timeout))
    try:
        sock.settimeout(max(0.5, timeout))
        # RFC 1928 greeting: VER=5, NMETHODS=1, METHOD=0 (no auth)
        sock.sendall(b"\x05\x01\x00")
        greeting = _recv_exact(sock, 2)
        if greeting != b"\x05\x00":
            raise OSError(f"socks5: unsupported auth reply {greeting!r}")
        # CONNECT request with ATYP=0x03 (domain name resolved remotely on MIT host)
        req = b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack("!H", int(dest_port))
        sock.sendall(req)
        hdr = _recv_exact(sock, 4)
        if hdr[0] != 5 or hdr[1] != 0 or hdr[2] != 0:
            raise OSError(f"socks5: connect failed rep=0x{hdr[1]:02x}")
        atyp = hdr[3]
        if atyp == 1:
            _recv_exact(sock, 4 + 2)
        elif atyp == 4:
            _recv_exact(sock, 16 + 2)
        elif atyp == 3:
            alen = _recv_exact(sock, 1)[0]
            _recv_exact(sock, alen + 2)
        else:
            raise OSError(f"socks5: unknown atyp=0x{atyp:02x}")
        return sock
    except Exception:
        try:
            sock.close()
        except OSError:
            pass
        raise


class _Socks5HTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection tunneling over loopback SOCKS5 with end-to-end TLS verification."""

    def __init__(
        self,
        host: str,
        port: int = 443,
        *,
        socks_host: str = DEFAULT_SOCKS_HOST,
        socks_port: int = DEFAULT_SOCKS_PORT,
        timeout: float = FETCH_CONNECT_TIMEOUT_S,
        context: ssl.SSLContext | None = None,
    ):
        super().__init__(host, port, timeout=timeout, context=context or _make_ssl_context())
        self._socks_host = socks_host
        self._socks_port = socks_port
        self._tls_hostname = host

    def connect(self) -> None:
        raw = socks5_connect(
            self._socks_host,
            self._socks_port,
            self._tls_hostname,
            self.port,
            self.timeout if self.timeout is not None else FETCH_CONNECT_TIMEOUT_S,
        )
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self._tls_hostname)
        except Exception:
            try:
                raw.close()
            except OSError:
                pass
            raise


class WileyRateLimiter:
    """Thread-safe non-blocking rate limiter enforcing Wiley's spacing & 10-min cap."""

    def __init__(
        self,
        *,
        min_spacing_s: float = DEFAULT_MIN_SPACING_S,
        max_per_10min: int = DEFAULT_MAX_PER_10MIN,
        clock=time.monotonic,
    ):
        self.min_spacing_s = min_spacing_s
        self.max_per_10min = max_per_10min
        self._clock = clock
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()

    def try_acquire(self) -> bool:
        now = self._clock()
        with self._lock:
            cutoff = now - RATE_WINDOW_S
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_per_10min:
                return False
            if self._timestamps and (now - self._timestamps[-1]) < self.min_spacing_s:
                return False
            self._timestamps.append(now)
            return True


@dataclass
class WileyTdmConfig:
    mode: str = "off"                         # "off" | "on" | "auto"
    secretspec_bin: str = DEFAULT_SECRETSPEC_BIN
    socks_host: str = DEFAULT_SOCKS_HOST
    socks_port: int = DEFAULT_SOCKS_PORT
    state_dir: str = DEFAULT_STATE_DIR
    min_spacing_s: float = DEFAULT_MIN_SPACING_S
    max_per_10min: int = DEFAULT_MAX_PER_10MIN
    allow_cloud_llm: bool = False             # FIRECRAWL_ROUTER_WILEY_ALLOW_CLOUD_LLM=off
    pdftotext_bin: str = ""
    pdfinfo_bin: str = ""
    pdftotext_timeout: float = PDFTOTEXT_TIMEOUT
    pdfinfo_timeout: float = PDFINFO_TIMEOUT
    fetch_deadline_s: float = FETCH_DEADLINE_S
    total_budget_s: float = TOTAL_WILEY_BUDGET_S


def build_wiley_tdm(env: dict[str, str], log=sys.stderr) -> WileyTdm | None:
    """Build WileyTdm from env vars, or None when disabled/invalid (fail-closed)."""
    raw_mode = (env.get("FIRECRAWL_ROUTER_WILEY_TDM") or "off").strip().lower()
    if raw_mode not in VALID_WILEY_MODES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_WILEY_TDM={raw_mode!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        return None
    if raw_mode == "off":
        return None

    socks_host = (
        env.get("FIRECRAWL_ROUTER_WILEY_SOCKS_HOST")
        or env.get("FIRECRAWL_ROUTER_MIT_SOCKS_HOST")
        or DEFAULT_SOCKS_HOST
    ).strip()
    if not _is_loopback_ip(socks_host):
        print(
            f"firecrawl-router: non-loopback FIRECRAWL_ROUTER_WILEY_SOCKS_HOST={socks_host!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        return None

    socks_port = _parse_int_clamped(
        env.get("FIRECRAWL_ROUTER_WILEY_SOCKS_PORT") or env.get("FIRECRAWL_ROUTER_MIT_SOCKS_PORT"),
        DEFAULT_SOCKS_PORT,
        1,
        65535,
    )

    if "FIRECRAWL_ROUTER_WILEY_SECRETSPEC_BIN" in env:
        secretspec_bin = (env.get("FIRECRAWL_ROUTER_WILEY_SECRETSPEC_BIN") or "").strip()
    elif "FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN" in env:
        secretspec_bin = (env.get("FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN") or "").strip()
    else:
        secretspec_bin = DEFAULT_SECRETSPEC_BIN

    try:
        raw_sp = float(env.get("FIRECRAWL_ROUTER_WILEY_MIN_SPACING_S") or DEFAULT_MIN_SPACING_S)
        min_spacing = (
            raw_sp
            if (math.isfinite(raw_sp) and MIN_SPACING_FLOOR_S <= raw_sp <= MAX_SPACING_CAP_S)
            else DEFAULT_MIN_SPACING_S
        )
    except ValueError:
        min_spacing = DEFAULT_MIN_SPACING_S

    max_per_10min = _parse_int_clamped(
        env.get("FIRECRAWL_ROUTER_WILEY_MAX_PER_10MIN"),
        DEFAULT_MAX_PER_10MIN,
        1,
        DEFAULT_MAX_PER_10MIN,
    )

    raw_llm = (env.get("FIRECRAWL_ROUTER_WILEY_ALLOW_CLOUD_LLM") or "off").strip().lower()
    if raw_llm not in VALID_ON_OFF:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_WILEY_ALLOW_CLOUD_LLM={raw_llm!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        raw_llm = "off"

    cfg = WileyTdmConfig(
        mode=raw_mode,
        secretspec_bin=secretspec_bin,
        socks_host=socks_host,
        socks_port=socks_port,
        state_dir=(env.get("FIRECRAWL_ROUTER_WILEY_STATE_DIR") or DEFAULT_STATE_DIR).strip(),
        min_spacing_s=min_spacing,
        max_per_10min=max_per_10min,
        allow_cloud_llm=(raw_llm == "on"),
        pdftotext_bin=_resolve_bin(
            env.get("FIRECRAWL_ROUTER_WILEY_PDFTOTEXT_BIN")
            or env.get("FIRECRAWL_ROUTER_OA_PDFTOTEXT_BIN")
            or env.get("FIRECRAWL_ROUTER_MIT_PDFTOTEXT_BIN"),
            "pdftotext",
            "/opt/homebrew/bin/pdftotext",
        ),
        pdfinfo_bin=_resolve_bin(
            env.get("FIRECRAWL_ROUTER_WILEY_PDFINFO_BIN")
            or env.get("FIRECRAWL_ROUTER_OA_PDFINFO_BIN")
            or env.get("FIRECRAWL_ROUTER_MIT_PDFINFO_BIN"),
            "pdfinfo",
            "/opt/homebrew/bin/pdfinfo",
        ),
    )
    return WileyTdm(cfg, log=log)


class WileyTdm:
    """Opt-in Wiley TDM PDF API runtime over loopback SOCKS5."""

    def __init__(
        self,
        config: WileyTdmConfig,
        *,
        log=sys.stderr,
        reply_cls=None,
        socks_conn_factory=_Socks5HTTPSConnection,
        direct_conn_factory=_PinnedHTTPSConnection,
        resolver=resolve_global,
        clock=time.monotonic,
    ):
        self.config = config
        self.log = log
        self._reply_cls = reply_cls
        self._socks_conn_factory = socks_conn_factory
        self._direct_conn_factory = direct_conn_factory
        self._resolver = resolver
        self._clock = clock
        self._sem = threading.BoundedSemaphore(1)
        self._rate_limiter = WileyRateLimiter(
            min_spacing_s=config.min_spacing_s,
            max_per_10min=config.max_per_10min,
            clock=clock,
        )
        self._state_lock = threading.Lock()
        self._cooldown_until: float = 0.0
        self.key_state = (
            KeyState(
                lambda: load_secret_key(
                    self.config.secretspec_bin,
                    WILEY_SECRET_NAME,
                    WILEY_SECRET_REASON,
                    validator=SAFE_UUID_RE,
                    label="wiley-tdm",
                    log=self.log,
                )
            )
            if config.secretspec_bin
            else None
        )
        if self.enabled:
            self._ensure_private_state_dir()
            self.sweep_orphans()

    @property
    def enabled(self) -> bool:
        return self.config.mode in ("on", "auto")

    @property
    def allow_cloud_llm(self) -> bool:
        return self.config.allow_cloud_llm

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

    def sweep_orphans(self, min_age_s: float = ORPHAN_MIN_AGE_S) -> None:
        base = self.config.state_dir
        now = time.time()
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
                if (
                    stat.S_ISDIR(est.st_mode)
                    and est.st_uid == os.getuid()
                    and now - est.st_mtime > min_age_s
                ):
                    shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:
                pass

    def _in_cooldown(self) -> bool:
        with self._state_lock:
            return self._clock() < self._cooldown_until

    def _set_cooldown(self, seconds: float) -> None:
        with self._state_lock:
            self._cooldown_until = max(self._cooldown_until, self._clock() + max(0.0, seconds))

    def maybe_fetch(
        self,
        method: str,
        path: str,
        body: bytes | None,
        primary_reply,
        fallback_reason_str: str,
        reply_cls=None,
    ) -> tuple[object | None, str | None, str]:
        """Try Wiley TDM PDF API for failed Wiley scrapes. Fail-closed on any error."""
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
            return None, None, ""
        _, host, _ = parsed
        if not needs_oa_fallback(url, host, req_doc, primary_reply, fallback_reason_str):
            return None, None, ""

        ident = extract_identifier(url)
        if ident is None or ident[0] != "doi":
            return None, None, ""
        doi = ident[1]
        if not is_wiley_target(host, doi):
            return None, None, ""

        token = self.key_state.get() if self.key_state is not None else None
        if not token:
            return None, None, "" if self.config.mode == "auto" else "no-token"
        if self._in_cooldown():
            return None, None, "cooldown"
        if not self._sem.acquire(blocking=False):
            return None, None, "busy"
        try:
            if not self._rate_limiter.try_acquire():
                return None, None, "rate-limited"
            return self._execute_fetch(url, doi, token, req_doc, rcls)
        except Exception:  # noqa: BLE001 - fail closed unconditionally
            return None, None, "internal-error"
        finally:
            self._sem.release()

    def _execute_fetch(
        self,
        requested_url: str,
        doi: str,
        token: str,
        req_doc: dict,
        reply_cls,
    ) -> tuple[object | None, str | None, str]:
        if not self._ensure_private_state_dir():
            return None, None, "state-dir-invalid"
        deadline = time.monotonic() + self.config.total_budget_s
        fetch_deadline = min(deadline, time.monotonic() + self.config.fetch_deadline_s)
        pdf_bytes, f_err = self._download_pdf(doi, token, fetch_deadline)
        if pdf_bytes is None:
            return None, None, _safe_reason_tag(f_err or "fetch-failed")
        return self._convert_and_build_reply(
            pdf_bytes=pdf_bytes,
            requested_url=requested_url,
            doi=doi,
            req_doc=req_doc,
            deadline=deadline,
            reply_cls=reply_cls,
        )

    def _socks_request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        deadline: float,
    ) -> tuple[int, dict[str, str], bytes | None, str]:
        parsed = parse_url(url)
        if parsed is None:
            return 0, {}, None, "invalid-url"
        scheme, host, port = parsed
        if scheme != "https" or port != 443:
            return 0, {}, None, "scheme-or-port"
        parts = urllib.parse.urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        rem = deadline - time.monotonic()
        if rem <= 0.1:
            return 0, {}, None, "timeout"
        conn = None
        try:
            conn = self._socks_conn_factory(
                host,
                443,
                socks_host=self.config.socks_host,
                socks_port=self.config.socks_port,
                timeout=min(FETCH_CONNECT_TIMEOUT_S, rem),
                context=_make_ssl_context(),
            )
            conn.request("GET", target, headers=headers)
            resp = conn.getresponse()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            status = resp.status
            if 300 <= status < 400:
                resp.read(1024)
                return status, resp_headers, b"", ""
            data, err = _read_bounded_response(resp, conn, max_bytes, deadline)
            return status, resp_headers, data, err
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            return 0, {}, None, "socks-error"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

    def _download_pdf(self, doi: str, token: str, deadline: float) -> tuple[bytes | None, str]:
        encoded_doi = urllib.parse.quote(doi, safe="")
        cur_url = f"https://{WILEY_API_HOST}{WILEY_API_PREFIX}{encoded_doi}"

        for hop in range(MAX_REDIRECTS + 1):
            parsed = parse_url(cur_url)
            if parsed is None:
                return None, "invalid-url"
            scheme, host, port = parsed
            if scheme != "https" or port != 443:
                return None, "scheme-or-port"
            is_wiley_api = (hop == 0 and host == WILEY_API_HOST)
            headers = {
                "User-Agent": WILEY_USER_AGENT,
                "Accept": "application/pdf",
                "Accept-Encoding": "identity",
            }
            if is_wiley_api:
                headers["Wiley-TDM-Client-Token"] = token
                status, resp_hdrs, data, err = self._socks_request(
                    cur_url,
                    headers=headers,
                    max_bytes=MAX_PDF_BYTES,
                    deadline=deadline,
                )
            elif host == WILEY_API_HOST:
                # Redirect stayed on api.wiley.com: strip token unconditionally, stay on SOCKS5
                status, resp_hdrs, data, err = self._socks_request(
                    cur_url,
                    headers=headers,
                    max_bytes=MAX_PDF_BYTES,
                    deadline=deadline,
                )
            else:
                # Presigned redirect off api.wiley.com: token stripped, global-IP SSRF pinned
                status, resp_hdrs, data, err = _OA._pinned_https_request(
                    cur_url,
                    headers=headers,
                    max_bytes=MAX_PDF_BYTES,
                    deadline=deadline,
                    conn_factory=self._direct_conn_factory,
                    resolver=self._resolver,
                )

            if err:
                if err in ("socks-error", "network-error", "timeout"):
                    self._set_cooldown(WILEY_5XX_COOLDOWN_S)
                return None, err

            if status in (301, 302, 303, 307, 308):
                loc = (resp_hdrs.get("location") or "").strip()
                if not loc or hop >= MAX_REDIRECTS:
                    return None, "too-many-redirects"
                cur_url = urllib.parse.urljoin(cur_url, loc)
                continue

            if status == 401:
                if self.key_state is not None:
                    self.key_state.disable_for(WILEY_401_COOLDOWN_S)
                return None, "unauthorized"
            if status == 403:
                self._set_cooldown(WILEY_403_COOLDOWN_S)
                return None, "access-denied"
            if status == 404:
                return None, "unknown-doi"
            if status == 429:
                self._set_cooldown(WILEY_429_COOLDOWN_S)
                return None, "upstream-429"
            if status != 200 or data is None:
                if status >= 500:
                    self._set_cooldown(WILEY_5XX_COOLDOWN_S)
                return None, f"http-{status}"

            ct = (resp_hdrs.get("content-type") or "").split(";", 1)[0].strip().lower()
            if ct and ct not in ("application/pdf", "application/octet-stream"):
                return None, "not-pdf"
            if not data.startswith(b"%PDF-"):
                return None, "not-pdf-magic"
            if b"%%EOF" not in data[-4096:]:
                return None, "corrupt-pdf"
            return data, ""

        return None, "too-many-redirects"

    def _read_pdfinfo(self, pdf_path: str, env: dict[str, str], deadline: float) -> tuple[int | None, str]:
        if (
            not self.config.pdfinfo_bin
            or not os.path.isfile(self.config.pdfinfo_bin)
            or not os.access(self.config.pdfinfo_bin, os.X_OK)
        ):
            return None, ""
        left = deadline - time.monotonic()
        if left <= 0.2:
            return None, ""
        res = run_bounded(
            [self.config.pdfinfo_bin, "-enc", "UTF-8", "--", pdf_path],
            env=env,
            timeout=min(self.config.pdfinfo_timeout, left),
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

    def _convert_and_build_reply(
        self,
        *,
        pdf_bytes: bytes,
        requested_url: str,
        doi: str,
        req_doc: dict,
        deadline: float,
        reply_cls,
    ) -> tuple[object | None, str | None, str]:
        run_dir = None
        try:
            if (
                not self.config.pdftotext_bin
                or not os.path.isfile(self.config.pdftotext_bin)
                or not os.access(self.config.pdftotext_bin, os.X_OK)
            ):
                return None, None, "pdftotext-missing"
            run_dir = tempfile.mkdtemp(prefix="run-", dir=self.config.state_dir)
            os.chmod(run_dir, 0o700)
            env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir, home=run_dir)
            pdf_file = os.path.join(run_dir, "article.pdf")
            fd = os.open(pdf_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fd = -1
                    fh.write(pdf_bytes)
            finally:
                if fd >= 0:
                    os.close(fd)
            verified_path, err = _safe_stat_inside(run_dir, pdf_file, MAX_PDF_BYTES)
            if verified_path is None:
                return None, None, err
            left = deadline - time.monotonic()
            if left <= 0.2:
                return None, None, "budget-timeout"
            max_pages = requested_pdf_max_pages(req_doc)
            res = run_bounded(
                [
                    self.config.pdftotext_bin,
                    "-q",
                    "-enc",
                    "UTF-8",
                    "-nopgbrk",
                    "-l",
                    str(max_pages),
                    "--",
                    verified_path,
                    "-",
                ],
                env=env,
                timeout=min(self.config.pdftotext_timeout, left),
                max_stdout=MAX_MARKDOWN_BYTES + 1,
                kill_on_stdout_cap=True,
            )
            if res.timed_out:
                return None, None, "pdftotext-timeout"
            if res.returncode != 0 and not res.stdout_truncated:
                return None, None, "pdftotext-failed"
            md, dec_trunc = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
            truncated = dec_trunc or res.stdout_truncated
            if not md.strip():
                return None, None, "pdftotext-empty"
            num_pages, doc_title = self._read_pdfinfo(verified_path, env, deadline)

            safe_source_url = redact_url(requested_url)
            safe_api_url = f"https://{WILEY_API_HOST}{WILEY_API_PREFIX}{urllib.parse.quote(doi, safe='')}"
            metadata: dict[str, object] = {
                "sourceURL": safe_source_url,
                "url": safe_api_url,
                "statusCode": 200,
                "contentType": "application/pdf",
                "proxyUsed": "wiley-tdm",
                "doi": doi,
            }
            if doc_title:
                metadata["title"] = doc_title
            if num_pages is not None:
                metadata["numPages"] = num_pages

            warn_parts = [
                "Served via official MIT-IP Wiley TDM PDF API (api.wiley.com); "
                "subject to Wiley TDM Terms of Use (non-commercial research; do not redistribute)."
            ]
            if truncated:
                warn_parts.append("Extracted content truncated to 2 MiB.")
            if num_pages is not None and num_pages > max_pages:
                warn_parts.append(f"PDF truncated to first {max_pages} of {num_pages} pages.")

            payload = json.dumps(
                {
                    "success": True,
                    "data": {
                        "markdown": md,
                        "warning": " ".join(warn_parts),
                        "metadata": metadata,
                    },
                }
            ).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "X-Firecrawl-Backend": "wiley-tdm",
            }
            return reply_cls(200, headers, payload), "wiley-tdm", f"wiley-tdm {num_pages or '?'}pp"
        finally:
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)
