"""firecrawl_oa_fallback: OpenAlex + Crossref Free-OA fallback tier for bin/firecrawl-router (stdlib only).

Feature-flagged (default OFF: FIRECRAWL_ROUTER_OA_FALLBACK=off), Hyades-first,
fail-closed Open Access fallback scoped strictly to POST /v1/scrape and POST
/v2/scrape. When Hyades fails (bot-wall / 403 / 429 / 5xx / PDF-mismatch /
unreachable) and mit-bridge does not answer, this module:
  1. Extracts a scholarly identifier (DOI / Nature slug / arXiv / PMID / PMCID /
     ScienceDirect PII -> Crossref Polite Pool alternative-id) with linear-time
     non-backtracking parsers.
  2. Queries OpenAlex singleton /works/{kind}:{val} ($0 free) and scans ALL
     locations[] (plus opt-in content.openalex.org when key active + budget allows),
     strictly excluding the failed publisher domain and doi.org/hdl redirectors.
  3. Downloads the vetted OA copy through an SSRF-pinned HTTPS client
     (_PinnedHTTPSConnection + per-hop resolve_global() blocking non-global,
     CGNAT 100.64.0.0/10, NAT64 64:ff9b::/96, and ipv4_mapped private IPs;
     https:443 only; <= 5 hops; streaming byte caps; Authorization stripped on
     every 3xx redirect).
  4. Validates %PDF- + %%EOF tail (or non-challenge trusted-repo HTML), converts
     in a private 0700 temp dir via pdftotext/pdfinfo or pandoc --sandbox with
     scrubbed_env() and killpg teardown, and returns a transparent Firecrawl v2
     JSON response with mandatory provenance data.warning.

Security invariants:
  - OPENALEX_API_KEY is fetched lazily in memory via sudo-secretspec (KeyState),
    sent ONLY as an unredirected Authorization: Bearer header to exact
    api.openalex.org / content.openalex.org, never in query params, plists,
    argv, logs, exceptions, firecrawl-mcp env, or converter scrubbed_env().
  - Every failure returns (None, None, reason_tag) so Router._forward() fails
    closed to Hyades' untouched reply.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import posixpath
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse


def _load_mit_bridge_helpers():
    """Load sibling firecrawl_mit_bridge under normal python3, python3 -I, or -E -s."""
    if "firecrawl_mit_bridge" in sys.modules:
        return sys.modules["firecrawl_mit_bridge"]
    bridge_path = Path(__file__).resolve().parent / "firecrawl_mit_bridge.py"
    if not bridge_path.is_file():
        raise ImportError(f"firecrawl_oa_fallback: sibling missing: {bridge_path}")
    spec = importlib.util.spec_from_file_location("firecrawl_mit_bridge", str(bridge_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"firecrawl_oa_fallback: cannot load sibling: {bridge_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["firecrawl_mit_bridge"] = mod
    spec.loader.exec_module(mod)
    return mod


_MB = _load_mit_bridge_helpers()

parse_url = _MB.parse_url
valid_host = _MB.valid_host
redact_url = _MB.redact_url
scrubbed_env = _MB.scrubbed_env
run_bounded = _MB.run_bounded
_decode_capped_utf8 = _MB._decode_capped_utf8
_safe_stat_inside = _MB._safe_stat_inside
is_pdf_target = _MB.is_pdf_target
requested_pdf_max_pages = _MB.requested_pdf_max_pages
requested_formats = _MB.requested_formats
needs_pdf_bridge = _MB.needs_pdf_bridge
needs_browser_bridge = _MB.needs_browser_bridge
_extract_html_title = _MB._extract_html_title
CONTROL_CHARS_RE = _MB.CONTROL_CHARS_RE
BRIDGE_CHALLENGE_MAX_CHARS = _MB.BRIDGE_CHALLENGE_MAX_CHARS
MAX_PDF_BYTES = _MB.MAX_PDF_BYTES
MAX_HTML_BYTES = _MB.MAX_HTML_BYTES
MAX_MARKDOWN_BYTES = _MB.MAX_MARKDOWN_BYTES
MAX_PDFINFO_STDOUT_BYTES = _MB.MAX_PDFINFO_STDOUT_BYTES
PDFTOTEXT_TIMEOUT = _MB.PDFTOTEXT_TIMEOUT
PDFINFO_TIMEOUT = _MB.PDFINFO_TIMEOUT
PANDOC_TIMEOUT = _MB.PANDOC_TIMEOUT
ORPHAN_MIN_AGE_S = _MB.ORPHAN_MIN_AGE_S
SCRAPE_ROUTES = _MB.SCRAPE_ROUTES
_parse_int_clamped = _MB._parse_int_clamped
_resolve_bin = _MB._resolve_bin


# ---- Constants, policy allowlists & resource caps --------------------------

VALID_OA_MODES = frozenset(("off", "allowlist", "pinned"))
VALID_VERSION_POLICIES = frozenset(("all", "peer-reviewed"))
VALID_ON_OFF = frozenset(("on", "off"))
VALID_PROVIDER_MODES = frozenset(("off", "auto", "on"))

ALLOWED_OA_VERSIONS = frozenset(("publishedVersion", "acceptedVersion", "submittedVersion"))
PEER_REVIEWED_VERSIONS = frozenset(("publishedVersion", "acceptedVersion"))
ALLOWED_OA_STATUSES = frozenset(("diamond", "gold", "green", "hybrid", "bronze", "closed"))
SAFE_LICENSE_RE = re.compile(r"^[a-z0-9._-]{1,64}$", re.ASCII)
SAFE_REASON_RE = re.compile(r"^[a-z0-9_.:-]{1,64}$", re.ASCII)
SAFE_OPENALEX_ID_RE = re.compile(r"^https://openalex\.org/W\d{1,16}$", re.ASCII)
SAFE_WORK_KEY_RE = re.compile(r"^W\d{1,16}$", re.ASCII)
SAFE_CORE_ID_RE = re.compile(r"^\d{1,16}$", re.ASCII)
CONTENT_API_PATH_RE = re.compile(r"^/works/W\d{1,16}\.pdf$", re.ASCII)
SAFE_CONTACT_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$", re.ASCII)
SAFE_KEY_RE = re.compile(r"^[\x21-\x7e]{8,512}$", re.ASCII)

OPENALEX_API_HOST = "api.openalex.org"
OPENALEX_CONTENT_HOST = "content.openalex.org"
CROSSREF_API_HOST = "api.crossref.org"
CORE_API_HOST = "api.core.ac.uk"
SPRINGER_API_HOST = "api.springernature.com"
SPRINGER_DOI_PREFIXES = (
    "10.1038/",
    "10.1007/",
    "10.1186/",
    "10.1057/",
    "10.1140/",
    "10.1365/",
    "10.4333/",
)
OPENALEX_SELECT_FIELDS = (
    "id,doi,title,publication_year,open_access,best_oa_location,"
    "primary_location,locations,has_content,content_urls"
)

SECRET_NAME = "OPENALEX_API_KEY"
SECRET_REASON = "firecrawl-router: OpenAlex OA fallback API key (memory only)"
CORE_SECRET_NAME = "CORE_API_KEY"
CORE_SECRET_REASON = "firecrawl-router: CORE API v3 OA fallback key (memory only)"
SPRINGER_SECRET_NAME = "SPRINGER_NATURE_API_KEY"
SPRINGER_SECRET_REASON = "firecrawl-router: Springer Nature Free OA API key (memory only)"
DEFAULT_SECRETSPEC_BIN = "/usr/local/bin/sudo-secretspec"
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/firecrawl-oa-fallback")

KEY_LOAD_TIMEOUT_S = 15.0
KEY_MISS_CACHE_S = 300.0
KEY_403_COOLDOWN_S = 600.0

OPENALEX_TIMEOUT_S = 6.0
OPENALEX_MAX_BYTES = 2 * 1024 * 1024
OPENALEX_CIRCUIT_S = 30.0
OPENALEX_MAX_RPS_RETRY_S = 2.0

CORE_TIMEOUT_S = 8.0
CORE_MAX_BYTES = 4 * 1024 * 1024
CORE_MIN_FULLTEXT_CHARS = 400
CORE_COOLDOWN_S = 60.0
CORE_CIRCUIT_S = 30.0

SPRINGER_TIMEOUT_S = 8.0
SPRINGER_MAX_BYTES = 16 * 1024 * 1024
SPRINGER_COOLDOWN_S = 60.0
SPRINGER_CIRCUIT_S = 30.0

CROSSREF_TIMEOUT_S = 5.0
CROSSREF_MAX_BYTES = 256 * 1024
CROSSREF_COOLDOWN_S = 60.0

FETCH_DEADLINE_S = 20.0
FETCH_CONNECT_TIMEOUT_S = 5.0
TOTAL_OA_BUDGET_S = 35.0
MAX_CANDIDATES = 3
MAX_REDIRECTS = 5

DEFAULT_MAX_CONCURRENT = 2
MAX_CONCURRENT_CAP = 4
SEM_ACQUIRE_TIMEOUT_S = 5.0
DEFAULT_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 3600.0

CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
NAT64_NET = ipaddress.ip_network("64:ff9b::/96")
NAT64_LOCAL_NET = ipaddress.ip_network("64:ff9b:1::/48")

# Parity with fetch.py same_site() multi-tenant / ccTLD exclusions.
SECOND_LEVEL_PARENTS = frozenset((
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "co.jp", "edu.sg",
))
PLATFORM_PARENTS = frozenset((
    "github.io", "cloudfront.net", "herokuapp.com", "appspot.com",
    "azurewebsites.net", "s3.amazonaws.com", "amazonaws.com", "fastly.net",
    "netlify.app", "vercel.app", "pages.dev", "workers.dev", "web.app",
    "firebaseapp.com", "blogspot.com", "azureedge.net", "akamaized.net",
    "akamai.net", "akamaiedge.net", "googleusercontent.com",
    "r2.cloudflarestorage.com",
))
CC_SECOND_LEVEL = frozenset(("co", "com", "org", "net", "ac", "gov", "edu"))

BLOCKED_REDIRECTOR_HOSTS = frozenset(("doi.org", "dx.doi.org", "hdl.handle.net"))

TIER1_OA_HOSTS = frozenset((
    "arxiv.org",
    "export.arxiv.org",
    "pmc.ncbi.nlm.nih.gov",
    "www.ncbi.nlm.nih.gov",  # restricted to /pmc/articles/ path prefix
    "europepmc.org",
    "biorxiv.org",
    "www.biorxiv.org",
    "medrxiv.org",
    "www.medrxiv.org",
    "osti.gov",
    "www.osti.gov",
    "hal.science",
    "zenodo.org",
    "cds.cern.ch",
    "journals.plos.org",
    "plos.org",
    "elifesciences.org",
    "peerj.com",
    "eprint.iacr.org",
    "aclanthology.org",
    "proceedings.mlr.press",
    "openreview.net",
    "proceedings.neurips.cc",
    "papers.nips.cc",
    "ceur-ws.org",
    "dspace.mit.edu",
))

INSTITUTIONAL_OA_HOSTS = frozenset((
    "dash.harvard.edu",
    "escholarship.org",
    "repository.upenn.edu",
    "deepblue.lib.umich.edu",
    "authors.library.caltech.edu",
    "dr.ntu.edu.sg",
    "ora.ox.ac.uk",
    "www.repository.cam.ac.uk",
    "eprints.whiterose.ac.uk",
    "biblio.ugent.be",
    "lirias.kuleuven.be",
))

TRUSTED_OA_HOSTS = TIER1_OA_HOSTS | INSTITUTIONAL_OA_HOSTS

# Trusted repos known to serve full-text HTML articles (not abstract-only stubs).
TRUSTED_HTML_OA_HOSTS = frozenset((
    "pmc.ncbi.nlm.nih.gov",
    "www.ncbi.nlm.nih.gov",  # /pmc/articles/ only
    "europepmc.org",
    "arxiv.org",             # /html/ only
    "journals.plos.org",
    "elifesciences.org",
    "peerj.com",
))

# Combined bot-wall + challenge detector (aligns with firecrawl-router BOT_WALL_RE + BRIDGE_CHALLENGE_RE).
OA_CHALLENGE_RE = re.compile(
    r"just a moment\.\.\.|attention required!? \| cloudflare|checking your browser|"
    r"performing security verification|enable javascript and cookies|"
    r"verify you are (?:a )?human|you have been blocked|received a high number of requests|"
    r"powered and protected by|please enable js and disable any ad blocker|"
    r"captcha-delivery\.com|press (?:&|and) hold|incapsula incident id|"
    r"request unsuccessful\. incapsula|vercel security checkpoint|"
    r"let'?s confirm you are human|awswaf|the requested url was rejected|"
    r"client challenge|attention required|cf-chl|"
    r"challenge-platform/[^\s\"'<>]{0,64}orchestrate",
    re.I,
)

# ---- Safe, linear-time identifier extraction & DOI normalization -----------

DOI_STRICT_RE = re.compile(r"^10\.\d{4,9}/[A-Za-z0-9._;()/:-]{1,200}$", re.ASCII)
DOI_ORG_PATH_RE = re.compile(r"^/(10\.\d{4,9}/[^?#\s]{1,250})$", re.ASCII)
STD_DOI_PATH_RE = re.compile(
    r"/doi/(?:(?:abs|full|pdf|pdfdirect|epdf|reader|book|citation|figure|suppl)/)?"
    r"(10\.\d{4,9}/[^?#\s]{1,250})",
    re.I | re.ASCII,
)
APS_DOI_PATH_RE = re.compile(
    r"^/[a-z0-9-]{1,32}/(?:abstract|pdf|export)/(10\.1103/[^?#\s]{1,250})$",
    re.I | re.ASCII,
)
PUB_DOI_PATH_RE = re.compile(
    r"/(?:article|articles|chapter|book|abstract|pdf|export|stable|content/pdf|journal/[^/]{1,64})/"
    r"(10\.\d{4,9}/[^?#\s]{1,250})",
    re.I | re.ASCII,
)
PUBLISHER_DOI_TAIL_HOSTS = frozenset((
    "link.springer.com",
    "journals.aps.org",
    "iopscience.iop.org",
    "www.jstor.org",
    "www.spiedigitallibrary.org",
    "pubs.aip.org",
    "pubs.rsc.org",
    "direct.mit.edu",
    "pubs.geoscienceworld.org",
))
TAIL_DOI_RE = re.compile(r"/(10\.\d{4,9}/[^?#\s]{1,250})$", re.ASCII)
NATURE_SLUG_RE = re.compile(
    r"^(?:s\d{5}-\d{3}-\d{4,5}-[0-9a-z]|nature\d{1,12}|n[a-z]{1,20}\d{1,12})$",
    re.ASCII,
)
ARXIV_NEW_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d{1,3})?$", re.ASCII)
ARXIV_OLD_RE = re.compile(r"^([a-z-]{2,32}/\d{7})(?:v\d{1,3})?$", re.ASCII)
PMID_PATH_RE = re.compile(r"^/(\d{5,10})/?$", re.ASCII)
PMCID_PATH_RE = re.compile(r"^/(?:pmc/)?articles/(PMC\d{4,10})(?:/[^?#\s]{0,128})?$", re.I | re.ASCII)
SCIENCEDIRECT_PII_RE = re.compile(
    r"^/science/article/(?:abs/)?pii/([A-Za-z0-9]{10,24})(?:/(?:pdfft|pdf))?/?$",
    re.I | re.ASCII,
)

_TRAILING_ACTION_SEGMENTS = (
    "/full.pdf",
    ".full.pdf",
    "/pdfdirect",
    "/references",
    "/abstract",
    "/download",
    "/epdf",
    "/full",
    "/meta",
    "/pdf",
    ".pdf",
)


def normalize_doi(raw: str, *, already_unquoted: bool = False) -> str | None:
    """Normalize and strictly validate a DOI string; fail closed to None."""
    if not isinstance(raw, str) or not raw or len(raw) > 512:
        return None
    s = (raw if already_unquoted else urllib.parse.unquote(raw)).strip()
    lower = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if lower.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    # Strip trailing slashes, known publisher action suffixes, and stray sentence punctuation.
    for _ in range(4):
        prev = s
        s = s.rstrip("/")
        low = s.lower()
        for suf in _TRAILING_ACTION_SEGMENTS:
            if low.endswith(suf):
                cand = s[:-len(suf)]
                # Only strip if a non-empty DOI suffix remains after "10.xxxx/".
                slash = cand.find("/")
                if slash > 0 and slash < len(cand) - 1:
                    s = cand
                    low = s.lower()
                    break
        while s and s[-1] in ".,;:":
            s = s[:-1]
        while s.endswith(")") and s.count(")") > s.count("("):
            s = s[:-1]
        if s == prev:
            break
    if not s or ".." in s:
        return None
    if not DOI_STRICT_RE.fullmatch(s):
        return None
    return s


def extract_identifier(url: str) -> tuple[str, str] | None:
    """Extract a bounded scholarly lookup key (kind, value) from a canonical URL."""
    if not isinstance(url, str) or len(url) > 4096:
        return None
    parsed = parse_url(url)
    if parsed is None:
        return None
    _, host, _ = parsed
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    path = urllib.parse.unquote(parts.path or "")
    if len(path) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return None

    # 1. doi.org / dx.doi.org
    if host in ("doi.org", "dx.doi.org"):
        m = DOI_ORG_PATH_RE.match(path)
        if m:
            doi = normalize_doi(m.group(1), already_unquoted=True)
            if doi:
                return ("doi", doi)
        return None

    # 2. Standard /doi/... paths (ACM, Wiley, Taylor & Francis, SAGE, ACS, Science, SIAM, PNAS, ...)
    m = STD_DOI_PATH_RE.search(path)
    if m:
        doi = normalize_doi(m.group(1), already_unquoted=True)
        if doi:
            return ("doi", doi)

    # 3. Publisher-specific DOI-in-path
    if host == "journals.aps.org":
        m = APS_DOI_PATH_RE.match(path)
        if m:
            doi = normalize_doi(m.group(1), already_unquoted=True)
            if doi:
                return ("doi", doi)
    m = PUB_DOI_PATH_RE.search(path)
    if m:
        doi = normalize_doi(m.group(1), already_unquoted=True)
        if doi:
            return ("doi", doi)
    if host in PUBLISHER_DOI_TAIL_HOSTS:
        m = TAIL_DOI_RE.search(path)
        if m:
            doi = normalize_doi(m.group(1), already_unquoted=True)
            if doi:
                return ("doi", doi)

    # 4. Nature article slugs (www.nature.com/articles/<slug>)
    if host == "www.nature.com" and path.startswith("/articles/"):
        seg = path[len("/articles/"):].rstrip("/")
        if seg.lower().endswith(".pdf"):
            seg = seg[:-4]
        if "/" not in seg and NATURE_SLUG_RE.fullmatch(seg):
            doi = normalize_doi(f"10.1038/{seg}", already_unquoted=True)
            if doi:
                return ("doi", doi)

    # 5. Direct open-repository IDs (arXiv, PubMed, PMC)
    if host in ("arxiv.org", "export.arxiv.org"):
        for prefix in ("/abs/", "/pdf/", "/html/"):
            if path.startswith(prefix):
                seg = path[len(prefix):].rstrip("/")
                if seg.lower().endswith(".pdf"):
                    seg = seg[:-4]
                m_new = ARXIV_NEW_RE.fullmatch(seg)
                if m_new:
                    return ("arxiv", m_new.group(1))
                m_old = ARXIV_OLD_RE.fullmatch(seg)
                if m_old:
                    return ("arxiv", m_old.group(1))
                break
    if host == "pubmed.ncbi.nlm.nih.gov":
        m = PMID_PATH_RE.match(path)
        if m:
            return ("pmid", m.group(1))
    if host == "pmc.ncbi.nlm.nih.gov" or (host == "www.ncbi.nlm.nih.gov" and path.startswith("/pmc/articles/")):
        m = PMCID_PATH_RE.match(path)
        if m:
            return ("pmcid", m.group(1).upper())

    # 6. ScienceDirect PII -> resolved via Crossref Polite Pool
    if host == "www.sciencedirect.com":
        m = SCIENCEDIRECT_PII_RE.match(path)
        if m:
            return ("pii", m.group(1).upper())

    return None


# ---- Domain, host-policy, and SSRF IP-pinning helpers ----------------------


def _is_multi_tenant_parent(parent: str) -> bool:
    labels = parent.split(".")
    if len(labels) < 2:
        return True
    if parent in SECOND_LEVEL_PARENTS:
        return True
    if any(parent == p or parent.endswith("." + p) for p in PLATFORM_PARENTS):
        return True
    if len(labels) == 2 and len(labels[1]) == 2 and labels[0] in CC_SECOND_LEVEL:
        return True
    return False


def _registrable_domain(host: str) -> str:
    """Best-effort registrable domain for publisher self-loop exclusion."""
    labels = host.split(".")
    if len(labels) < 2:
        return host
    if any(host == p or host.endswith("." + p) for p in PLATFORM_PARENTS):
        return host
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in CC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    if len(labels) >= 3 and ".".join(labels[-2:]) in SECOND_LEVEL_PARENTS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_publisher_domain(candidate_host: str, requested_host: str) -> bool:
    """True when candidate_host is requested_host or shares its publisher domain."""
    if not candidate_host or not requested_host:
        return False
    if candidate_host == requested_host:
        return True
    return _registrable_domain(candidate_host) == _registrable_domain(requested_host)


def _is_excluded_publisher_host(candidate_host: str, requested_host: str) -> bool:
    """Exclude failed host itself and same-publisher siblings, while allowing distinct vetted OA repos."""
    if not candidate_host or not requested_host:
        return False
    if candidate_host == requested_host:
        return True
    if candidate_host in TRUSTED_OA_HOSTS:
        return False
    return same_publisher_domain(candidate_host, requested_host)


def same_site(host: str, start_host: str, allowed: frozenset[str]) -> bool:
    """True if host is allowed, start_host, a subdomain of start_host, or a same-site sibling."""
    if host == start_host or host in allowed:
        return True
    if not _is_multi_tenant_parent(start_host) and host.endswith("." + start_host):
        return True
    parent = start_host.split(".", 1)[1] if "." in start_host else ""
    if not parent or _is_multi_tenant_parent(parent):
        return False
    return host.endswith("." + parent)


def _is_r2_storage_host(host: str) -> bool:
    """True for <account>.r2.cloudflarestorage.com (allowed ONLY on direct redirect from content.openalex.org)."""
    if not host.endswith(".r2.cloudflarestorage.com"):
        return False
    labels = host.split(".")
    return len(labels) >= 4 and all(bool(x) for x in labels)


def _strict_path_prefix(path: str, prefix: str) -> bool:
    """Enforce prefix confinement rejecting raw/unquoted dot-segments, backslashes, control chars, and encoded slashes/dots."""
    if not isinstance(path, str) or not path.startswith("/"):
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or "\\" in path:
        return False
    low = path.lower()
    if "%2f" in low or "%5c" in low or "%2e" in low:
        return False
    if any(seg in (".", "..") for seg in path.split("/")):
        return False
    unq = urllib.parse.unquote(path)
    if any(ord(c) < 32 or ord(c) == 127 for c in unq) or "\\" in unq:
        return False
    if any(seg in (".", "..") for seg in unq.split("/")):
        return False
    norm_raw = posixpath.normpath(path)
    norm_unq = posixpath.normpath(unq)
    return (
        norm_raw.startswith(prefix)
        and len(norm_raw) > len(prefix)
        and norm_unq.startswith(prefix)
        and len(norm_unq) > len(prefix)
    )


def _trusted_host_path_ok(host: str, url: str) -> bool:
    """Enforce path restrictions for multi-purpose trusted hosts."""
    path = urllib.parse.urlsplit(url).path or ""
    if host == "www.ncbi.nlm.nih.gov":
        return _strict_path_prefix(path, "/pmc/articles/")
    if host == OPENALEX_CONTENT_HOST:
        return bool(CONTENT_API_PATH_RE.fullmatch(path))
    return True


def _is_trusted_html_url(host: str, url: str) -> bool:
    if host not in TRUSTED_HTML_OA_HOSTS:
        return False
    path = urllib.parse.urlsplit(url).path or ""
    if host == "www.ncbi.nlm.nih.gov":
        return _strict_path_prefix(path, "/pmc/articles/")
    if host == "arxiv.org":
        return _strict_path_prefix(path, "/html/")
    return True


def _source_slug(host: str) -> str:
    """Short header-safe source slug for X-Firecrawl-OA-Source."""
    mapping = {
        "arxiv.org": "arxiv",
        "export.arxiv.org": "arxiv",
        "pmc.ncbi.nlm.nih.gov": "pmc",
        "www.ncbi.nlm.nih.gov": "pmc",
        "europepmc.org": "europepmc",
        "biorxiv.org": "biorxiv",
        "www.biorxiv.org": "biorxiv",
        "medrxiv.org": "medrxiv",
        "www.medrxiv.org": "medrxiv",
        "osti.gov": "osti",
        "www.osti.gov": "osti",
        "hal.science": "hal",
        "zenodo.org": "zenodo",
        "cds.cern.ch": "cern-cds",
        "journals.plos.org": "plos",
        "plos.org": "plos",
        "elifesciences.org": "elife",
        "peerj.com": "peerj",
        "eprint.iacr.org": "iacr",
        "aclanthology.org": "acl",
        "proceedings.mlr.press": "pmlr",
        "openreview.net": "openreview",
        "proceedings.neurips.cc": "neurips",
        "papers.nips.cc": "neurips",
        "ceur-ws.org": "ceur-ws",
        "dspace.mit.edu": "dspace-mit",
        OPENALEX_CONTENT_HOST: "openalex-content",
        CORE_API_HOST: "core",
        SPRINGER_API_HOST: "springer-oa",
    }
    if host in mapping:
        return mapping[host]
    if host in INSTITUTIONAL_OA_HOSTS:
        return "institutional-repo"
    return "oa-repo"


def _is_global_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    check = mapped or ip
    if (
        not check.is_global
        or check.is_multicast
        or check.is_private
        or check.is_loopback
        or check.is_link_local
        or check.is_reserved
        or check.is_unspecified
    ):
        return False
    if check.version == 4 and check in CGNAT_NET:
        return False
    if check.version == 6 and (check in NAT64_NET or check in NAT64_LOCAL_NET):
        return False
    return True


def resolve_global(host: str, port: int = 443) -> str | None:
    """Return first resolved IP literal iff EVERY A/AAAA record is globally routable."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addrs = [info[4][0].split("%", 1)[0] for info in infos]
    if not addrs:
        return None
    for a in addrs:
        if not _is_global_ip(a):
            return None
    return addrs[0]


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects TCP to a pre-verified IP literal while validating TLS SNI=host."""

    def __init__(
        self,
        host: str,
        port: int = 443,
        *,
        pinned_ip: str,
        timeout: float = FETCH_CONNECT_TIMEOUT_S,
        context: ssl.SSLContext | None = None,
    ):
        super().__init__(host, port=port, timeout=timeout, context=context or _make_ssl_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            raise


def _read_bounded_response(
    resp: http.client.HTTPResponse,
    conn: http.client.HTTPConnection,
    max_bytes: int,
    deadline: float,
) -> tuple[bytes | None, str]:
    """Stream response body with strict byte cap and wall-clock deadline."""
    raw_cl = resp.getheader("Content-Length")
    if raw_cl is not None:
        try:
            cl = int(raw_cl.strip())
        except ValueError:
            cl = -1
        if cl > max_bytes:
            return None, "oa-too-large"
    buf = bytearray()
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None, "fetch-timeout"
        sock = getattr(conn, "sock", None)
        if sock is not None:
            try:
                sock.settimeout(min(FETCH_CONNECT_TIMEOUT_S, left))
            except OSError:
                pass
        try:
            chunk = resp.read(65536)
        except TimeoutError:
            return None, "fetch-timeout"
        except OSError:
            return None, "fetch-error"
        if not chunk:
            break
        if len(buf) + len(chunk) > max_bytes:
            return None, "oa-too-large"
        buf.extend(chunk)
    return bytes(buf), ""


def _pinned_https_request(
    url: str,
    *,
    headers: dict[str, str],
    max_bytes: int,
    deadline: float,
    conn_factory=_PinnedHTTPSConnection,
    resolver=resolve_global,
) -> tuple[int, dict[str, str], bytes | None, str]:
    """Single-hop (no-redirect) SSRF-pinned HTTPS GET over port 443."""
    parsed = parse_url(url)
    if parsed is None:
        return 0, {}, None, "url-refused"
    scheme, host, port = parsed
    if scheme != "https" or port != 443:
        return 0, {}, None, "https-443-required"
    left = deadline - time.monotonic()
    if left <= 0:
        return 0, {}, None, "fetch-timeout"
    pinned_ip = resolver(host, 443)
    if pinned_ip is None:
        return 0, {}, None, "ssrf-blocked"

    parts = urllib.parse.urlsplit(url)
    try:
        safe_path = urllib.parse.quote(parts.path or "/", safe="/:@!$&'()*+,;=-._~%")
        safe_query = urllib.parse.quote(parts.query, safe="/?:@!$&'()*+,;=-._~%") if parts.query else ""
        target = f"{safe_path}?{safe_query}" if safe_query else safe_path
        target.encode("ascii")
    except (UnicodeEncodeError, ValueError):
        return 0, {}, None, "url-refused"

    conn = conn_factory(host, 443, pinned_ip=pinned_ip, timeout=min(FETCH_CONNECT_TIMEOUT_S, left))
    try:
        conn.request("GET", target, headers=headers)
        resp = conn.getresponse()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        if 300 <= resp.status < 400:
            return resp.status, resp_headers, b"", ""
        body, err = _read_bounded_response(resp, conn, max_bytes, deadline)
        return resp.status, resp_headers, body, err
    except (UnicodeEncodeError, ValueError):
        return 0, {}, None, "url-refused"
    except TimeoutError:
        return 0, {}, None, "fetch-timeout"
    except (OSError, http.client.HTTPException, ssl.SSLError):
        return 0, {}, None, "fetch-error"
    finally:
        try:
            conn.close()
        except OSError:
            pass


# ---- Memory-only secret key loader (sudo-secretspec) -----------------------


def load_secret_key(
    secretspec_bin: str,
    secret_name: str,
    reason: str,
    *,
    validator: re.Pattern[str] = SAFE_KEY_RE,
    label: str = "oa",
    log=sys.stderr,
) -> str | None:
    """Load an API key in memory via sudo-secretspec; never logs the key value."""
    if not secretspec_bin:
        return None
    try:
        res = subprocess.run(
            [secretspec_bin, "get", secret_name, "--reason", reason],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=KEY_LOAD_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"firecrawl-router: {label} key load failed: {type(exc).__name__}", file=log, flush=True)
        return None
    val = res.stdout.decode("utf-8", "replace").rstrip("\r\n")
    if res.returncode != 0 or not validator.fullmatch(val):
        print(
            f"firecrawl-router: {label} key unavailable: rc={res.returncode} usable={bool(validator.fullmatch(val))}",
            file=log,
            flush=True,
        )
        return None
    return val


def load_openalex_key(secretspec_bin: str, log=sys.stderr) -> str | None:
    """Load OPENALEX_API_KEY in memory via sudo-secretspec; never logs the key."""
    return load_secret_key(
        secretspec_bin,
        SECRET_NAME,
        SECRET_REASON,
        validator=SAFE_KEY_RE,
        label="oa",
        log=log,
    )


class KeyState:
    """Lazy in-memory key cache with 300 s miss caching and 10 min 403 cooldown."""

    def __init__(self, loader, *, miss_cache_s: float = KEY_MISS_CACHE_S):
        self._loader = loader
        self._miss_cache_s = miss_cache_s
        self._lock = threading.Lock()
        self._key: str | None = None
        self._last_attempt: float | None = None
        self._disabled_until: float = 0.0

    def get(self) -> str | None:
        now = time.monotonic()
        with self._lock:
            if now < self._disabled_until:
                return None
            if self._key:
                return self._key
            if self._last_attempt is not None and (now - self._last_attempt) < self._miss_cache_s:
                return None
            self._last_attempt = now
            self._key = self._loader()
            return self._key

    def disable_for(self, seconds: float) -> None:
        with self._lock:
            self._key = None
            self._disabled_until = max(self._disabled_until, time.monotonic() + max(0.0, seconds))


# ---- OpenAlex + Crossref API Client ----------------------------------------


class OpenAlexClient:
    """Bounded, fail-closed OpenAlex singleton + Crossref PII client."""

    def __init__(
        self,
        key_state: KeyState | None,
        *,
        contact: str = "",
        log=sys.stderr,
        conn_factory=_PinnedHTTPSConnection,
        resolver=resolve_global,
        sleep_fn=time.sleep,
    ):
        self.key_state = key_state
        self.contact = contact if (contact and SAFE_CONTACT_RE.fullmatch(contact)) else ""
        self.log = log
        self._conn_factory = conn_factory
        self._resolver = resolver
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._remaining_usd: float | None = None
        self._reset_at: float = 0.0
        self._billable_paused_until: float = 0.0
        self._openalex_breaker_until: float = 0.0
        self._crossref_cooldown_until: float = 0.0
        self._crossref_sem = threading.BoundedSemaphore(1)

    def _update_rate_headers(self, headers: dict[str, str]) -> None:
        rem_usd_raw = headers.get("x-ratelimit-remaining-usd")
        rem_credits_raw = headers.get("x-ratelimit-remaining")
        reset_raw = headers.get("x-ratelimit-reset")
        now = time.monotonic()
        with self._lock:
            if rem_usd_raw is not None:
                try:
                    val = float(rem_usd_raw.strip())
                    if math.isfinite(val) and val >= 0.0:
                        self._remaining_usd = val
                except ValueError:
                    pass
            elif rem_credits_raw is not None:
                try:
                    credits_val = float(rem_credits_raw.strip())
                    if math.isfinite(credits_val) and credits_val >= 0.0:
                        # OpenAlex credits: 10,000 credits = $1.00 (1 credit = $0.0001).
                        self._remaining_usd = credits_val * 0.0001
                except ValueError:
                    pass
            if reset_raw is not None:
                try:
                    sec = float(reset_raw.strip())
                    if math.isfinite(sec) and sec >= 0.0:
                        self._reset_at = now + min(sec, 86400.0)
                except ValueError:
                    pass

    def can_spend_billable(self, cost_usd: float) -> bool:
        now = time.monotonic()
        with self._lock:
            if now < self._billable_paused_until:
                return False
            if self._remaining_usd is not None:
                if self._reset_at and now >= self._reset_at:
                    self._remaining_usd = None
                elif self._remaining_usd < cost_usd:
                    return False
        return True

    def record_content_api_status(self, status: int, headers: dict[str, str], body: bytes | None) -> None:
        self._update_rate_headers(headers)
        if status in (401, 403) and self.key_state is not None:
            self.key_state.disable_for(KEY_403_COOLDOWN_S)
        elif status == 429:
            reason = self._parse_error_reason(body)
            if reason in ("daily_budget", "first_dollar", "not_enough_credits"):
                pause = self._parse_retry_after(headers, default=3600.0, cap=86400.0)
                with self._lock:
                    self._billable_paused_until = max(self._billable_paused_until, time.monotonic() + pause)
                    self._remaining_usd = 0.0

    @staticmethod
    def _parse_error_reason(body: bytes | None) -> str:
        if not body:
            return ""
        try:
            doc = json.loads(body[:8192].decode("utf-8", "replace"))
        except ValueError:
            return ""
        if not isinstance(doc, dict):
            return ""
        for k in ("reason", "error", "message"):
            v = doc.get(k)
            if isinstance(v, str):
                low = v.lower()
                for tag in ("requests_per_second", "daily_budget", "first_dollar", "not_enough_credits", "key_not_activated"):
                    if tag in low:
                        return tag
        return ""

    @staticmethod
    def _parse_retry_after(headers: dict[str, str], default: float, cap: float) -> float:
        raw = headers.get("retry-after") or headers.get("x-ratelimit-reset")
        if raw:
            try:
                v = float(raw.strip())
                if math.isfinite(v) and v >= 0.0:
                    return min(v, cap)
            except ValueError:
                pass
        return min(default, cap)

    def lookup_work(self, kind: str, value: str, deadline: float) -> tuple[dict | None, str]:
        """Free ($0) OpenAlex singleton lookup by doi / arxiv / pmid / pmcid."""
        now = time.monotonic()
        with self._lock:
            if now < self._openalex_breaker_until:
                return None, "openalex-circuit"

        if kind == "doi":
            encoded = urllib.parse.quote(value, safe="/:.-_()")
            path_id = f"doi:{encoded}"
        elif kind == "arxiv":
            encoded = urllib.parse.quote(value, safe="/.-")
            path_id = f"arxiv:{encoded}"
        elif kind == "pmid":
            if not re.fullmatch(r"\d{5,10}", value, re.ASCII):
                return None, "invalid-id"
            path_id = f"pmid:{value}"
        elif kind == "pmcid":
            if not re.fullmatch(r"PMC\d{4,10}", value, re.ASCII):
                return None, "invalid-id"
            path_id = f"pmcid:{value}"
        else:
            return None, "unsupported-id"

        url = f"https://{OPENALEX_API_HOST}/works/{path_id}?select={OPENALEX_SELECT_FIELDS}"
        key = self.key_state.get() if self.key_state is not None else None
        retried_rps = False
        retried_keyless = False

        for _ in range(3):
            call_deadline = min(deadline, time.monotonic() + OPENALEX_TIMEOUT_S)
            if call_deadline <= time.monotonic():
                return None, "openalex-timeout"
            hdrs = {
                "Accept": "application/json",
                "User-Agent": "firecrawl-router-oa/1.0",
            }
            if key:
                hdrs["Authorization"] = f"Bearer {key}"
            status, resp_hdrs, body, err = _pinned_https_request(
                url,
                headers=hdrs,
                max_bytes=OPENALEX_MAX_BYTES,
                deadline=call_deadline,
                conn_factory=self._conn_factory,
                resolver=self._resolver,
            )
            self._update_rate_headers(resp_hdrs)
            if err:
                if err == "oa-too-large":
                    return None, "oa-too-large"
                with self._lock:
                    self._openalex_breaker_until = time.monotonic() + OPENALEX_CIRCUIT_S
                return None, "openalex-timeout" if err == "fetch-timeout" else f"openalex-{err}"
            if 300 <= status < 400:
                return None, "openalex-redirect-refused"
            if status == 200 and body is not None:
                try:
                    doc = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return None, "openalex-bad-json"
                if not isinstance(doc, dict):
                    return None, "openalex-bad-json"
                return doc, ""
            if status == 404:
                return None, "not-found"
            if status in (401, 403) and key and not retried_keyless:
                if self.key_state is not None:
                    self.key_state.disable_for(KEY_403_COOLDOWN_S)
                key = None
                retried_keyless = True
                continue
            if status == 429:
                reason = self._parse_error_reason(body)
                if reason in ("daily_budget", "first_dollar", "not_enough_credits"):
                    pause = self._parse_retry_after(resp_hdrs, default=3600.0, cap=86400.0)
                    with self._lock:
                        self._billable_paused_until = max(self._billable_paused_until, time.monotonic() + pause)
                        self._remaining_usd = 0.0
                    return None, "budget-exhausted"
                if reason == "requests_per_second" and not retried_rps:
                    delay = self._parse_retry_after(resp_hdrs, default=1.0, cap=OPENALEX_MAX_RPS_RETRY_S)
                    if time.monotonic() + delay + 0.5 < deadline:
                        retried_rps = True
                        self._sleep(delay)
                        continue
                return None, "rate-limited"
            if status >= 500:
                with self._lock:
                    self._openalex_breaker_until = time.monotonic() + OPENALEX_CIRCUIT_S
                return None, f"openalex-{status}"
            return None, f"openalex-{status}"
        return None, "openalex-error"

    def resolve_pii_to_doi(self, pii: str, deadline: float) -> tuple[str | None, str]:
        """Resolve a ScienceDirect PII to a verified DOI via Crossref Polite Pool."""
        if not re.fullmatch(r"[A-Z0-9]{10,24}", pii):
            return None, "invalid-pii"
        now = time.monotonic()
        with self._lock:
            if now < self._crossref_cooldown_until:
                return None, "crossref-cooldown"
        wait_s = min(2.0, max(0.05, deadline - now))
        if not self._crossref_sem.acquire(timeout=wait_s):
            return None, "crossref-busy"
        try:
            call_deadline = min(deadline, time.monotonic() + CROSSREF_TIMEOUT_S)
            if call_deadline <= time.monotonic():
                return None, "crossref-timeout"
            q = f"filter=alternative-id:{pii}&rows=1&select=DOI,alternative-id"
            if self.contact:
                q += "&mailto=" + urllib.parse.quote(self.contact, safe="@._+-")
            url = f"https://{CROSSREF_API_HOST}/works?{q}"
            ua = f"firecrawl-router-oa/1.0 (mailto:{self.contact})" if self.contact else "firecrawl-router-oa/1.0"
            status, _hdrs, body, err = _pinned_https_request(
                url,
                headers={"Accept": "application/json", "User-Agent": ua},
                max_bytes=CROSSREF_MAX_BYTES,
                deadline=call_deadline,
                conn_factory=self._conn_factory,
                resolver=self._resolver,
            )
            if err:
                return None, "crossref-timeout" if err == "fetch-timeout" else f"crossref-{err}"
            if 300 <= status < 400:
                return None, "crossref-redirect-refused"
            if status == 429:
                with self._lock:
                    self._crossref_cooldown_until = time.monotonic() + CROSSREF_COOLDOWN_S
                return None, "crossref-rate-limited"
            if status != 200 or body is None:
                return None, f"crossref-{status}"
            try:
                doc = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None, "crossref-bad-json"
            msg = doc.get("message") if isinstance(doc, dict) else None
            items = msg.get("items") if isinstance(msg, dict) else None
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                return None, "crossref-not-found"
            item = items[0]
            alt_ids = item.get("alternative-id")
            if not isinstance(alt_ids, list):
                return None, "crossref-pii-mismatch"
            if not any(isinstance(a, str) and a.strip().upper() == pii for a in alt_ids):
                return None, "crossref-pii-mismatch"
            doi = normalize_doi(str(item.get("DOI") or ""))
            if not doi:
                return None, "crossref-bad-doi"
            return doi, ""
        finally:
            self._crossref_sem.release()


# ---- Springer Nature Free OA JATS & CORE API v3 Clients --------------------


_JATS_DOI_RE = re.compile(
    r'<article-id\s+pub-id-type=["\']doi["\'][^>]{0,80}>([^<]{1,220})</article-id>',
    re.IGNORECASE,
)
_JATS_TITLE_RE = re.compile(
    r"<article-title\b[^>]{0,80}>(.*?)</article-title>",
    re.IGNORECASE | re.DOTALL,
)
_XML_TAG_RE = re.compile(r"<[^>]{1,200}>")
_CORE_PUBLIC_STUB = "not available for public api users"


def is_springer_doi(doi: str) -> bool:
    d = (doi or "").strip().lower()
    return any(d.startswith(p) for p in SPRINGER_DOI_PREFIXES)


def extract_jats_article(xml_bytes: bytes, expected_doi: str) -> tuple[bytes | None, str, str]:
    """Safely extract <article>...</article> from Springer OA JATS response (O(n), XXE-safe).

    Returns (article_xml, title, error_tag).
    """
    if not xml_bytes:
        return None, "", "springer-empty"
    if b"<!entity" in xml_bytes.lower():
        return None, "", "springer-unsafe-xml"
    # Linear O(n) scan for <article ...> ... </article> (avoids regex backtracking).
    start = -1
    pos = 0
    lower = xml_bytes.lower()
    while True:
        idx = lower.find(b"<article", pos)
        if idx < 0:
            break
        nxt = idx + len(b"<article")
        if nxt < len(lower) and lower[nxt:nxt + 1] in (b">", b" ", b"\t", b"\r", b"\n"):
            start = idx
            break
        pos = idx + 8
    if start < 0:
        return None, "", "springer-no-article"
    end_tag = b"</article>"
    end = lower.find(end_tag, start)
    if end < 0:
        return None, "", "springer-truncated-xml"
    article = xml_bytes[start : end + len(end_tag)]

    head_text = article[:32768].decode("utf-8", "replace")
    doi_m = _JATS_DOI_RE.search(head_text)
    if not doi_m:
        return None, "", "springer-doi-missing"
    got_doi = normalize_doi(doi_m.group(1).strip())
    if not got_doi or got_doi.lower() != expected_doi.lower():
        return None, "", "springer-doi-mismatch"

    title = ""
    title_m = _JATS_TITLE_RE.search(head_text)
    if title_m:
        raw_t = _XML_TAG_RE.sub(" ", title_m.group(1))
        title = _sanitize_text(raw_t)
    return article, title, ""


class SpringerOaClient:
    """Bounded, fail-closed Springer Nature Free Open Access JATS XML client."""

    def __init__(
        self,
        key_state: KeyState | None,
        *,
        log=sys.stderr,
        conn_factory=_PinnedHTTPSConnection,
        resolver=resolve_global,
    ):
        self.key_state = key_state
        self.log = log
        self._conn_factory = conn_factory
        self._resolver = resolver
        self._lock = threading.Lock()
        self._circuit_until: float = 0.0

    def _circuit_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._circuit_until

    def _trip_circuit(self, seconds: float) -> None:
        with self._lock:
            self._circuit_until = max(self._circuit_until, time.monotonic() + max(0.0, seconds))

    def fetch_jats(self, doi: str, deadline: float) -> tuple[bytes | None, str, str]:
        """Fetch OA JATS XML for a Springer Nature DOI. Never logs or returns api_key."""
        if not is_springer_doi(doi):
            return None, "", "springer-prefix-skip"
        if self._circuit_open():
            return None, "", "springer-cooldown"
        key = self.key_state.get() if self.key_state is not None else None
        if not key:
            return None, "", "springer-no-key"

        qs = urllib.parse.urlencode({"q": f"doi:{doi}", "p": "1", "api_key": key})
        req_url = f"https://{SPRINGER_API_HOST}/openaccess/jats?{qs}"
        headers = {
            "User-Agent": "firecrawl-router-oa/1.0",
            "Accept": "application/xml, text/xml",
            "Accept-Encoding": "identity",
        }
        req_deadline = min(deadline, time.monotonic() + SPRINGER_TIMEOUT_S)
        # _pinned_https_request never follows redirects so ?api_key= cannot leave api.springernature.com
        status, _hdrs, body, err = _pinned_https_request(
            req_url,
            headers=headers,
            max_bytes=SPRINGER_MAX_BYTES,
            deadline=req_deadline,
            conn_factory=self._conn_factory,
            resolver=self._resolver,
        )
        if err:
            if err in ("network-error", "timeout"):
                self._trip_circuit(SPRINGER_CIRCUIT_S)
            return None, "", f"springer-{err}"
        if status in (401, 403):
            if self.key_state is not None:
                self.key_state.disable_for(KEY_403_COOLDOWN_S)
            return None, "", f"springer-http-{status}"
        if status == 429:
            self._trip_circuit(SPRINGER_COOLDOWN_S)
            return None, "", "springer-rate-limited"
        if status != 200 or not body:
            if status >= 500:
                self._trip_circuit(SPRINGER_CIRCUIT_S)
            return None, "", f"springer-http-{status}"
        return extract_jats_article(body, doi)


class CoreOaClient:
    """Bounded, fail-closed CORE API v3 DOI lookup client."""

    def __init__(
        self,
        key_state: KeyState | None,
        *,
        log=sys.stderr,
        conn_factory=_PinnedHTTPSConnection,
        resolver=resolve_global,
    ):
        self.key_state = key_state
        self.log = log
        self._conn_factory = conn_factory
        self._resolver = resolver
        self._lock = threading.Lock()
        self._circuit_until: float = 0.0

    def _circuit_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._circuit_until

    def _trip_circuit(self, seconds: float) -> None:
        with self._lock:
            self._circuit_until = max(self._circuit_until, time.monotonic() + max(0.0, seconds))

    def lookup_doi(
        self,
        doi: str,
        deadline: float,
        *,
        require_key: bool = True,
    ) -> tuple[dict | None, str]:
        if self._circuit_open():
            return None, "core-cooldown"
        key = self.key_state.get() if self.key_state is not None else None
        if require_key and not key:
            return None, "core-no-key"

        qs = urllib.parse.urlencode({"q": f'doi:"{doi}"', "limit": "3"})
        # Trailing slash on /v3/search/works/ avoids 301 redirect
        req_url = f"https://{CORE_API_HOST}/v3/search/works/?{qs}"
        headers = {
            "User-Agent": "firecrawl-router-oa/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req_deadline = min(deadline, time.monotonic() + CORE_TIMEOUT_S)
        status, resp_hdrs, body, err = _pinned_https_request(
            req_url,
            headers=headers,
            max_bytes=CORE_MAX_BYTES,
            deadline=req_deadline,
            conn_factory=self._conn_factory,
            resolver=self._resolver,
        )
        if err:
            if err in ("network-error", "timeout"):
                self._trip_circuit(CORE_CIRCUIT_S)
            return None, f"core-{err}"
        if status in (401, 403):
            if key and self.key_state is not None:
                self.key_state.disable_for(KEY_403_COOLDOWN_S)
            return None, f"core-http-{status}"
        if status == 429:
            self._trip_circuit(CORE_COOLDOWN_S)
            return None, "core-rate-limited"
        if status != 200 or not body:
            if status >= 500:
                self._trip_circuit(CORE_CIRCUIT_S)
            return None, f"core-http-{status}"
        rem = (resp_hdrs.get("x-ratelimit-remaining") or "").strip()
        if rem == "0":
            self._trip_circuit(10.0)
        try:
            doc = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return None, "core-bad-json"
        results = doc.get("results") if isinstance(doc, dict) else None
        if not isinstance(results, list) or not results:
            return None, "core-not-found"
        for item in results[:3]:
            if not isinstance(item, dict):
                continue
            item_doi = normalize_doi(str(item.get("doi") or ""))
            if item_doi and item_doi.lower() == doi.lower():
                return item, ""
        return None, "core-doi-mismatch"


# ---- Candidate filtering & deterministic ranking ---------------------------


@dataclass(frozen=True)
class OaCandidate:
    url: str
    host: str
    is_direct_pdf: bool
    oa_version: str
    oa_license: str
    oa_source: str
    is_content_api: bool
    score: tuple[int, int, int, int, int, int]


def _sanitize_text(val: object, fallback: str = "") -> str:
    if isinstance(val, str):
        cleaned = " ".join(CONTROL_CHARS_RE.sub("", val).split())[:300]
        if cleaned:
            return cleaned
    if isinstance(fallback, str) and fallback:
        return " ".join(CONTROL_CHARS_RE.sub("", fallback).split())[:300]
    return ""


def _sanitize_version(val: object) -> str:
    if isinstance(val, str) and val in ALLOWED_OA_VERSIONS:
        return val
    return "unknown"


def _sanitize_status(val: object) -> str:
    if isinstance(val, str) and val in ALLOWED_OA_STATUSES:
        return val
    return "unknown"


def _sanitize_license(val: object) -> str:
    if isinstance(val, str):
        low = val.strip().lower()
        if SAFE_LICENSE_RE.fullmatch(low):
            return low
    return "unspecified"


def _has_open_license(lic: str) -> int:
    if lic == "public-domain" or lic.startswith("cc-") or lic in ("cc0", "pd", "mit", "apache-2.0", "bsd"):
        return 1
    return 0


def _version_rank(ver: str) -> int:
    return {"publishedVersion": 3, "acceptedVersion": 2, "submittedVersion": 1}.get(ver, 0)


def rank_oa_candidates(
    work: dict,
    requested_host: str,
    *,
    host_policy: str = "allowlist",
    version_policy: str = "all",
    content_api_allowed: bool = False,
    cooldown_hosts: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[OaCandidate], str]:
    """Filter and deterministically rank OA candidate URLs from an OpenAlex work.

    Returns (ranked_candidates, skip_reason_if_empty).
    """
    if not isinstance(work, dict):
        return [], "not-oa"

    oa_obj = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
    best_loc = work.get("best_oa_location") if isinstance(work.get("best_oa_location"), dict) else None
    raw_locs = work.get("locations") if isinstance(work.get("locations"), list) else []

    all_locs: list[dict] = []
    if best_loc is not None:
        all_locs.append(best_loc)
    for loc in raw_locs:
        if isinstance(loc, dict):
            all_locs.append(loc)

    oa_locs = [loc for loc in all_locs if loc.get("is_oa") is True]
    has_content_obj = work.get("has_content") if isinstance(work.get("has_content"), dict) else {}
    has_content_pdf = (
        content_api_allowed
        and has_content_obj.get("pdf") is True
        and (oa_obj.get("is_oa") is True or bool(oa_locs))
        and isinstance(work.get("content_urls"), dict)
        and isinstance(work["content_urls"].get("pdf"), str)
    )
    if not oa_locs and not has_content_pdf:
        return [], "not-oa"
    if oa_obj.get("is_oa") is False and not oa_locs:
        return [], "not-oa"

    seen_urls: set[str] = set()
    candidates: list[OaCandidate] = []
    saw_allowlist_drop = False
    saw_cooldown_drop = False
    saw_version_drop = False

    def _consider(
        raw_url: object,
        *,
        is_direct_pdf: bool,
        version: str,
        lic: str,
        source_name: str,
        is_repo_type: int,
        is_content_api: bool = False,
    ) -> None:
        nonlocal saw_allowlist_drop, saw_cooldown_drop, saw_version_drop
        if not isinstance(raw_url, str) or not raw_url:
            return
        parsed = parse_url(raw_url)
        if parsed is None:
            return
        scheme, host, port = parsed
        if scheme != "https" or port != 443:
            return
        if raw_url in seen_urls:
            return
        if _is_excluded_publisher_host(host, requested_host):
            return
        if host in BLOCKED_REDIRECTOR_HOSTS:
            return
        if version_policy == "peer-reviewed" and version not in PEER_REVIEWED_VERSIONS:
            saw_version_drop = True
            return
        if host in cooldown_hosts:
            saw_cooldown_drop = True
            return

        if is_content_api:
            if host != OPENALEX_CONTENT_HOST or not _trusted_host_path_ok(host, raw_url):
                return
            trust_tier = 2
            best_ver = _sanitize_version(best_loc.get("version")) if best_loc else "unknown"
            band = 4 if best_ver == "publishedVersion" else 1
        else:
            if host in TIER1_OA_HOSTS:
                if not _trusted_host_path_ok(host, raw_url):
                    saw_allowlist_drop = True
                    return
                trust_tier = 3
            elif host in INSTITUTIONAL_OA_HOSTS:
                trust_tier = 2
            else:
                if host_policy != "pinned":
                    saw_allowlist_drop = True
                    return
                trust_tier = 1

            # Non-PDF landing pages are only used for trusted full-text HTML repos.
            if not is_direct_pdf and not _is_trusted_html_url(host, raw_url):
                return

            v_rank = _version_rank(version)
            if trust_tier == 3:
                band = 6 if (is_direct_pdf and v_rank >= 2) else 3
            elif trust_tier == 2:
                band = 5 if (is_direct_pdf and v_rank >= 2) else 2
            else:
                band = 0

        score = (
            band,
            trust_tier,
            1 if is_direct_pdf else 0,
            _version_rank(version),
            _has_open_license(lic),
            is_repo_type,
        )
        seen_urls.add(raw_url)
        candidates.append(
            OaCandidate(
                url=raw_url,
                host=host,
                is_direct_pdf=is_direct_pdf,
                oa_version=version,
                oa_license=lic,
                oa_source=_sanitize_text(source_name, fallback=host),
                is_content_api=is_content_api,
                score=score,
            )
        )

    for loc in oa_locs:
        ver = _sanitize_version(loc.get("version"))
        lic = _sanitize_license(loc.get("license"))
        src = loc.get("source") if isinstance(loc.get("source"), dict) else {}
        src_name = str(src.get("display_name") or "")
        is_repo = 1 if src.get("type") == "repository" else 0
        pdf_url = loc.get("pdf_url")
        landing_url = loc.get("landing_page_url")
        if isinstance(pdf_url, str) and pdf_url:
            _consider(
                pdf_url,
                is_direct_pdf=True,
                version=ver,
                lic=lic,
                source_name=src_name,
                is_repo_type=is_repo,
            )
        if isinstance(landing_url, str) and landing_url and landing_url != pdf_url:
            _consider(
                landing_url,
                is_direct_pdf=False,
                version=ver,
                lic=lic,
                source_name=src_name,
                is_repo_type=is_repo,
            )

    if has_content_pdf:
        content_url = work["content_urls"]["pdf"]
        ver = _sanitize_version(best_loc.get("version")) if best_loc else "unknown"
        lic = _sanitize_license(best_loc.get("license")) if best_loc else "unspecified"
        _consider(
            content_url,
            is_direct_pdf=True,
            version=ver,
            lic=lic,
            source_name="OpenAlex Content Archive",
            is_repo_type=1,
            is_content_api=True,
        )

    if not candidates:
        if saw_cooldown_drop:
            return [], "cooldown"
        if saw_allowlist_drop:
            return [], "allowlist-filtered"
        if saw_version_drop:
            return [], "version-filtered"
        return [], "no-eligible-candidate"

    # Deterministic tie-breaking: highest score first, then canonical URL ascending.
    candidates.sort(key=lambda c: (tuple(-x for x in c.score), c.url))
    return candidates, ""


# ---- Configuration & Runtime -----------------------------------------------


@dataclass
class OaFallbackConfig:
    mode: str = "off"               # "off" | "allowlist" | "pinned"
    version_policy: str = "all"     # "all" | "peer-reviewed"
    content_api: bool = False       # FIRECRAWL_ROUTER_OA_CONTENT_API=on
    core_mode: str = "auto"         # "off" | "auto" (if CORE_API_KEY) | "on" (incl. keyless)
    springer_mode: str = "auto"     # "off" | "auto" (if SPRINGER_NATURE_API_KEY) | "on"
    allow_enrolled: bool = True     # FIRECRAWL_ROUTER_OA_ENROLLED=on|off
    secretspec_bin: str = DEFAULT_SECRETSPEC_BIN
    state_dir: str = DEFAULT_STATE_DIR
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    cooldown_s: float = DEFAULT_COOLDOWN_S
    contact: str = ""
    pdftotext_bin: str = ""
    pdfinfo_bin: str = ""
    pandoc_bin: str = ""
    pdftotext_timeout: float = PDFTOTEXT_TIMEOUT
    pdfinfo_timeout: float = PDFINFO_TIMEOUT
    pandoc_timeout: float = PANDOC_TIMEOUT
    sem_timeout: float = SEM_ACQUIRE_TIMEOUT_S
    fetch_deadline_s: float = FETCH_DEADLINE_S
    total_budget_s: float = TOTAL_OA_BUDGET_S


def build_oa_fallback(env: dict[str, str], log=sys.stderr) -> OaFallback | None:
    """Build OaFallback from environment variables, or None when disabled/invalid."""
    raw_mode = (env.get("FIRECRAWL_ROUTER_OA_FALLBACK") or "off").strip().lower()
    if raw_mode not in VALID_OA_MODES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_FALLBACK={raw_mode!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        return None
    if raw_mode == "off":
        return None

    raw_ver = (env.get("FIRECRAWL_ROUTER_OA_VERSIONS") or "all").strip().lower()
    if raw_ver not in VALID_VERSION_POLICIES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_VERSIONS={raw_ver!r}; failing closed (peer-reviewed)",
            file=log,
            flush=True,
        )
        raw_ver = "peer-reviewed"

    raw_content = (env.get("FIRECRAWL_ROUTER_OA_CONTENT_API") or "off").strip().lower()
    if raw_content not in VALID_ON_OFF:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_CONTENT_API={raw_content!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        raw_content = "off"

    raw_core = (env.get("FIRECRAWL_ROUTER_OA_CORE") or "auto").strip().lower()
    if raw_core not in VALID_PROVIDER_MODES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_CORE={raw_core!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        raw_core = "off"

    raw_springer = (env.get("FIRECRAWL_ROUTER_OA_SPRINGER") or "auto").strip().lower()
    if raw_springer not in VALID_PROVIDER_MODES:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_SPRINGER={raw_springer!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        raw_springer = "off"

    raw_enrolled = (env.get("FIRECRAWL_ROUTER_OA_ENROLLED") or "on").strip().lower()
    if raw_enrolled not in VALID_ON_OFF:
        print(
            f"firecrawl-router: unknown FIRECRAWL_ROUTER_OA_ENROLLED={raw_enrolled!r}; failing closed (off)",
            file=log,
            flush=True,
        )
        raw_enrolled = "off"

    if "FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN" in env:
        secretspec_bin = (env.get("FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN") or "").strip()
    else:
        secretspec_bin = DEFAULT_SECRETSPEC_BIN

    max_conc = _parse_int_clamped(
        env.get("FIRECRAWL_ROUTER_OA_MAX_CONCURRENT"), DEFAULT_MAX_CONCURRENT, 1, MAX_CONCURRENT_CAP
    )
    try:
        raw_cd = float(env.get("FIRECRAWL_ROUTER_OA_COOLDOWN_S") or DEFAULT_COOLDOWN_S)
        cooldown_s = raw_cd if (math.isfinite(raw_cd) and 0.0 <= raw_cd <= MAX_COOLDOWN_S) else DEFAULT_COOLDOWN_S
    except ValueError:
        cooldown_s = DEFAULT_COOLDOWN_S

    contact = (env.get("FIRECRAWL_ROUTER_OA_CONTACT") or "").strip()
    if contact and not SAFE_CONTACT_RE.fullmatch(contact):
        contact = ""

    cfg = OaFallbackConfig(
        mode=raw_mode,
        version_policy=raw_ver,
        content_api=(raw_content == "on"),
        core_mode=raw_core,
        springer_mode=raw_springer,
        allow_enrolled=(raw_enrolled == "on"),
        secretspec_bin=secretspec_bin,
        state_dir=(env.get("FIRECRAWL_ROUTER_OA_STATE_DIR") or DEFAULT_STATE_DIR).strip(),
        max_concurrent=max_conc,
        cooldown_s=cooldown_s,
        contact=contact,
        pdftotext_bin=_resolve_bin(
            env.get("FIRECRAWL_ROUTER_OA_PDFTOTEXT_BIN") or env.get("FIRECRAWL_ROUTER_MIT_PDFTOTEXT_BIN"),
            "pdftotext",
            "/opt/homebrew/bin/pdftotext",
        ),
        pdfinfo_bin=_resolve_bin(
            env.get("FIRECRAWL_ROUTER_OA_PDFINFO_BIN") or env.get("FIRECRAWL_ROUTER_MIT_PDFINFO_BIN"),
            "pdfinfo",
            "/opt/homebrew/bin/pdfinfo",
        ),
        pandoc_bin=_resolve_bin(
            env.get("FIRECRAWL_ROUTER_OA_PANDOC_BIN") or env.get("FIRECRAWL_ROUTER_MIT_PANDOC_BIN"),
            "pandoc",
            "/opt/homebrew/bin/pandoc",
        ),
    )
    return OaFallback(cfg, log=log)


def _safe_reason_tag(tag: str) -> str:
    return tag if SAFE_REASON_RE.fullmatch(tag) else "error"


def needs_oa_fallback(url: str, host: str, req_doc: dict, primary_reply, fallback_reason_str: str) -> bool:
    """True when Hyades failed or returned a bot-wall/PDF-mismatch eligible for OA rescue."""
    if primary_reply.status != 200:
        return True
    if fallback_reason_str:
        return True
    if needs_browser_bridge(primary_reply, fallback_reason_str):
        return True
    if is_pdf_target(url, req_doc) and needs_pdf_bridge(primary_reply, host):
        return True
    return False


class OaFallback:
    """OpenAlex + Crossref Free-OA fallback runtime."""

    def __init__(
        self,
        config: OaFallbackConfig,
        *,
        log=sys.stderr,
        reply_cls=None,
        conn_factory=_PinnedHTTPSConnection,
        resolver=resolve_global,
        sleep_fn=time.sleep,
    ):
        self.config = config
        self.log = log
        self._reply_cls = reply_cls
        self._conn_factory = conn_factory
        self._resolver = resolver
        self.oa_sem = threading.BoundedSemaphore(config.max_concurrent)
        self._cooldown_lock = threading.Lock()
        self._cooldowns: dict[str, float] = {}
        self.key_state = (
            KeyState(lambda: load_openalex_key(self.config.secretspec_bin, log=self.log))
            if config.secretspec_bin
            else None
        )
        self.core_key_state = (
            KeyState(
                lambda: load_secret_key(
                    self.config.secretspec_bin,
                    CORE_SECRET_NAME,
                    CORE_SECRET_REASON,
                    label="core-oa",
                    log=self.log,
                )
            )
            if config.secretspec_bin
            else None
        )
        self.springer_key_state = (
            KeyState(
                lambda: load_secret_key(
                    self.config.secretspec_bin,
                    SPRINGER_SECRET_NAME,
                    SPRINGER_SECRET_REASON,
                    label="springer-oa",
                    log=self.log,
                )
            )
            if config.secretspec_bin
            else None
        )
        self.client = OpenAlexClient(
            self.key_state,
            contact=config.contact,
            log=log,
            conn_factory=conn_factory,
            resolver=resolver,
            sleep_fn=sleep_fn,
        )
        self.core_client = CoreOaClient(
            self.core_key_state,
            log=log,
            conn_factory=conn_factory,
            resolver=resolver,
        )
        self.springer_client = SpringerOaClient(
            self.springer_key_state,
            log=log,
            conn_factory=conn_factory,
            resolver=resolver,
        )
        if self.enabled:
            self._ensure_private_state_dir()
            self.sweep_orphans()

    @property
    def enabled(self) -> bool:
        return self.config.mode in ("allowlist", "pinned")

    # -- private state dir & orphan sweep

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

    # -- per-host negative cooldown

    def _active_cooldown_hosts(self) -> set[str]:
        if self.config.cooldown_s <= 0:
            return set()
        now = time.monotonic()
        with self._cooldown_lock:
            expired = [h for h, exp in self._cooldowns.items() if now >= exp]
            for h in expired:
                self._cooldowns.pop(h, None)
            return set(self._cooldowns.keys())

    def _set_cooldown(self, host: str) -> None:
        if self.config.cooldown_s <= 0 or not host:
            return
        with self._cooldown_lock:
            self._cooldowns[host] = time.monotonic() + self.config.cooldown_s

    # -- main entry point (fail-closed)

    def maybe_fallback(
        self,
        method: str,
        path: str,
        body: bytes | None,
        primary_reply,
        fallback_reason_str: str,
        reply_cls=None,
        *,
        was_enrolled: bool = False,
    ) -> tuple[object | None, str | None, str]:
        """Try resolving a failed scholarly scrape to a vetted Open Access copy.

        Returns:
          (Reply, "oa-fallback", log_note) on success;
          (None, None, "") when request is not eligible (non-scrape or healthy primary);
          (None, None, reason_tag) when eligible scrape skipped/failed closed.
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
            return None, None, ""
        _, host, _ = parsed

        if not needs_oa_fallback(url, host, req_doc, primary_reply, fallback_reason_str):
            return None, None, ""
        if was_enrolled and not self.config.allow_enrolled:
            return None, None, "enrolled-disabled"

        try:
            ident = extract_identifier(url)
            if ident is None:
                return None, None, "no-identifier"

            if not self.oa_sem.acquire(timeout=self.config.sem_timeout):
                return None, None, "busy"
            try:
                return self._execute_fallback(url, host, req_doc, ident, rcls)
            finally:
                self.oa_sem.release()
        except Exception:  # noqa: BLE001 - fail closed unconditionally
            return None, None, "internal-error"

    def _execute_fallback(
        self,
        url: str,
        requested_host: str,
        req_doc: dict,
        ident: tuple[str, str],
        reply_cls,
    ) -> tuple[object | None, str | None, str]:
        deadline = time.monotonic() + self.config.total_budget_s
        kind, val = ident

        if kind == "pii":
            doi, cr_err = self.client.resolve_pii_to_doi(val, deadline)
            if not doi:
                return None, None, _safe_reason_tag(cr_err or "crossref-failed")
            kind, val = "doi", doi

        work, oa_err = self.client.lookup_work(kind, val, deadline)
        last_err = oa_err or "openalex-error"
        springer_tried = False

        if work is not None:
            key_active = self.key_state is not None and bool(self.key_state.get())
            content_api_allowed = (
                self.config.content_api
                and key_active
                and self.client.can_spend_billable(0.01)
            )
            candidates, rank_err = rank_oa_candidates(
                work,
                requested_host,
                host_policy=self.config.mode,
                version_policy=self.config.version_policy,
                content_api_allowed=content_api_allowed,
                cooldown_hosts=self._active_cooldown_hosts(),
            )
            if candidates:
                if not self._ensure_private_state_dir():
                    return None, None, "state-dir-invalid"
                free_cands = [c for c in candidates[:MAX_CANDIDATES] if not c.is_content_api]
                paid_cands = [c for c in candidates[:MAX_CANDIDATES] if c.is_content_api]
                last_err = "fetch-failed"
                for cand in free_cands:
                    if time.monotonic() >= deadline:
                        last_err = "budget-timeout"
                        break
                    fetch_deadline = min(deadline, time.monotonic() + self.config.fetch_deadline_s)
                    fetched, final_url, content_kind, f_err = self._fetch_candidate(
                        cand, requested_host, fetch_deadline
                    )
                    if fetched is None:
                        last_err = f_err or "fetch-failed"
                        continue
                    reply, c_err = self._convert_and_build_reply(
                        fetched=fetched,
                        content_kind=content_kind,
                        requested_url=url,
                        final_url=final_url,
                        cand=cand,
                        work=work,
                        resolved_doi=val if kind == "doi" else None,
                        req_doc=req_doc,
                        deadline=deadline,
                        reply_cls=reply_cls,
                    )
                    if reply is not None:
                        slug = _source_slug(cand.host)
                        return reply, "oa-fallback", f"oa:{slug} {cand.oa_version}"
                    last_err = c_err or "converter-failed"

                # Try free Springer Nature OA JATS VoR before spending $0.01 on content.openalex.org
                if kind == "doi" and self._springer_eligible(val) and time.monotonic() < deadline:
                    springer_tried = True
                    sp_reply, sp_note = self._try_springer_oa(url, val, work, req_doc, deadline, reply_cls)
                    if sp_reply is not None:
                        return sp_reply, "oa-fallback", sp_note

                for cand in paid_cands:
                    if time.monotonic() >= deadline:
                        last_err = "budget-timeout"
                        break
                    fetch_deadline = min(deadline, time.monotonic() + self.config.fetch_deadline_s)
                    fetched, final_url, content_kind, f_err = self._fetch_candidate(
                        cand, requested_host, fetch_deadline
                    )
                    if fetched is None:
                        last_err = f_err or "fetch-failed"
                        continue
                    reply, c_err = self._convert_and_build_reply(
                        fetched=fetched,
                        content_kind=content_kind,
                        requested_url=url,
                        final_url=final_url,
                        cand=cand,
                        work=work,
                        resolved_doi=val if kind == "doi" else None,
                        req_doc=req_doc,
                        deadline=deadline,
                        reply_cls=reply_cls,
                    )
                    if reply is not None:
                        slug = _source_slug(cand.host)
                        return reply, "oa-fallback", f"oa:{slug} {cand.oa_version}"
                    last_err = c_err or "converter-failed"
            else:
                last_err = rank_err or "no-eligible-candidate"

        # Secondary zero-risk OA tiers when OpenAlex failed or had no eligible/working copy
        if kind == "doi" and not springer_tried and self._springer_eligible(val) and time.monotonic() < deadline:
            sp_reply, sp_note = self._try_springer_oa(url, val, work or {}, req_doc, deadline, reply_cls)
            if sp_reply is not None:
                return sp_reply, "oa-fallback", sp_note

        if kind == "doi" and self.config.core_mode != "off" and time.monotonic() < deadline:
            core_reply, core_note = self._try_core_oa(
                url, requested_host, val, work or {}, req_doc, deadline, reply_cls
            )
            if core_reply is not None:
                return core_reply, "oa-fallback", core_note

        return None, None, _safe_reason_tag(last_err)

    def _springer_eligible(self, doi: str) -> bool:
        return self.config.springer_mode != "off" and is_springer_doi(doi) and self.springer_key_state is not None

    def _try_springer_oa(
        self,
        requested_url: str,
        doi: str,
        work: dict,
        req_doc: dict,
        deadline: float,
        reply_cls,
    ) -> tuple[object | None, str]:
        article_xml, jats_title, s_err = self.springer_client.fetch_jats(doi, deadline)
        if article_xml is None:
            return None, s_err
        if not self.config.pandoc_bin or not os.path.isfile(self.config.pandoc_bin) or not os.access(self.config.pandoc_bin, os.X_OK):
            return None, "pandoc-missing"
        if not self._ensure_private_state_dir():
            return None, "state-dir-invalid"
        run_dir = None
        try:
            run_dir = tempfile.mkdtemp(prefix="run-", dir=self.config.state_dir)
            os.chmod(run_dir, 0o700)
            env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir, home=run_dir)
            left = deadline - time.monotonic()
            if left <= 0.2:
                return None, "budget-timeout"
            res = run_bounded(
                [self.config.pandoc_bin, "--sandbox", "-f", "jats", "-t", "gfm-raw_html", "--wrap=none"],
                env=env,
                timeout=min(self.config.pandoc_timeout, left),
                max_stdout=MAX_MARKDOWN_BYTES + 1,
                stdin_bytes=article_xml,
                kill_on_stdout_cap=True,
            )
            if res.timed_out or (res.returncode != 0 and not res.stdout_truncated):
                return None, "pandoc-failed"
            md, dec_trunc = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
            truncated = dec_trunc or res.stdout_truncated
            if not md.strip():
                return None, "pandoc-empty"
            title = _sanitize_text(work.get("title"), fallback=jats_title)
            if title and not md.lstrip().startswith("#"):
                md = f"# {title}\n\n{md}"
            safe_oa_url = f"https://{SPRINGER_API_HOST}/openaccess/jats?q=doi:{urllib.parse.quote(doi, safe='/:.-_()')}"
            warn_parts = [
                f"Served Open Access JATS XML copy (publishedVersion, license: open-access) "
                f"from Springer Nature Open Access API at {safe_oa_url} instead of the requested publisher URL "
                f"because the publisher scrape failed."
            ]
            if truncated:
                warn_parts.append("Extracted content truncated to 2 MiB.")
            metadata: dict[str, object] = {
                "sourceURL": redact_url(requested_url),
                "url": safe_oa_url,
                "statusCode": 200,
                "contentType": "application/xml",
                "proxyUsed": "oa-fallback",
                "doi": doi,
                "oaStatus": "gold",
                "oaVersion": "publishedVersion",
                "oaLicense": "open-access",
                "oaSource": "Springer Nature Open Access API",
            }
            if title:
                metadata["title"] = title
            payload = json.dumps(
                {"success": True, "data": {"markdown": md, "warning": " ".join(warn_parts), "metadata": metadata}}
            ).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "X-Firecrawl-Backend": "oa-fallback",
                "X-Firecrawl-OA-Source": "springer-oa",
            }
            return reply_cls(200, headers, payload), "oa:springer-oa publishedVersion"
        finally:
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)

    def _try_core_oa(
        self,
        requested_url: str,
        requested_host: str,
        doi: str,
        work: dict,
        req_doc: dict,
        deadline: float,
        reply_cls,
    ) -> tuple[object | None, str]:
        # CORE search results do not reliably distinguish submitted vs peer-reviewed versions.
        if self.config.version_policy == "peer-reviewed":
            return None, "core-version-unknown"
        require_key = self.config.core_mode == "auto"
        item, c_err = self.core_client.lookup_doi(doi, deadline, require_key=require_key)
        if item is None:
            return None, c_err

        # Path A: Try any vetted repository URL in sourceFulltextUrls (excluding core.ac.uk & failed publisher)
        src_urls = item.get("sourceFulltextUrls")
        if isinstance(src_urls, list) and self._ensure_private_state_dir():
            cooldown_hosts = self._active_cooldown_hosts()
            tried = 0
            for raw_u in src_urls:
                if tried >= 2 or time.monotonic() >= deadline:
                    break
                if not isinstance(raw_u, str):
                    continue
                parsed = parse_url(raw_u)
                if parsed is None:
                    continue
                scheme, host, port = parsed
                if scheme != "https" or port != 443:
                    continue
                if host in ("core.ac.uk", "www.core.ac.uk", CORE_API_HOST):
                    continue
                if host in BLOCKED_REDIRECTOR_HOSTS or _is_excluded_publisher_host(host, requested_host):
                    continue
                if host in cooldown_hosts:
                    continue
                if self.config.mode == "allowlist" and not _trusted_host_path_ok(host, raw_u):
                    continue
                tried += 1
                cand = OaCandidate(
                    url=raw_u,
                    host=host,
                    is_direct_pdf=raw_u.lower().endswith(".pdf"),
                    oa_version="unknown",
                    oa_license=_sanitize_license(item.get("license")),
                    oa_source="CORE Open Access Repository",
                    is_content_api=False,
                    score=(0, 0, 0, 0, 0, 0),
                )
                fetch_deadline = min(deadline, time.monotonic() + self.config.fetch_deadline_s)
                fetched, final_url, content_kind, _f_err = self._fetch_candidate(
                    cand, requested_host, fetch_deadline
                )
                if fetched is None:
                    continue
                reply, _conv_err = self._convert_and_build_reply(
                    fetched=fetched,
                    content_kind=content_kind,
                    requested_url=requested_url,
                    final_url=final_url,
                    cand=cand,
                    work=work or {"title": item.get("title"), "doi": doi},
                    resolved_doi=doi,
                    req_doc=req_doc,
                    deadline=deadline,
                    reply_cls=reply_cls,
                )
                if reply is not None:
                    return reply, f"oa:core-{_source_slug(cand.host)} unknown"

        # Path B: Inline CORE fullText (requires registered key; skipped under peer-reviewed-only policy)
        if self.config.version_policy == "peer-reviewed":
            return None, "core-version-unknown"
        raw_ft = item.get("fullText")
        if not isinstance(raw_ft, str):
            return None, "core-no-fulltext"
        if _CORE_PUBLIC_STUB in raw_ft.lower():
            return None, "core-key-required"
        ft_clean = CONTROL_CHARS_RE.sub("", raw_ft).strip()
        if len(ft_clean) < CORE_MIN_FULLTEXT_CHARS:
            return None, "core-short-fulltext"
        if len(ft_clean) < BRIDGE_CHALLENGE_MAX_CHARS and OA_CHALLENGE_RE.search(ft_clean):
            return None, "core-challenge-text"
        md, truncated = _decode_capped_utf8(ft_clean.encode("utf-8", "replace"), MAX_MARKDOWN_BYTES)

        core_id = str(item.get("id") or "").strip()
        safe_oa_url = (
            f"https://core.ac.uk/works/{core_id}"
            if SAFE_CORE_ID_RE.fullmatch(core_id)
            else f"https://{CORE_API_HOST}/v3/search/works/"
        )
        title = _sanitize_text(work.get("title") or item.get("title"))
        oa_lic = _sanitize_license(item.get("license"))
        warn_parts = [
            f"Served Open Access repository fullText (unknown version, license: {oa_lic}) "
            f"from CORE Open Access Repository at {safe_oa_url} instead of the requested publisher URL "
            f"because the publisher scrape failed; content may differ from the Version of Record."
        ]
        if truncated:
            warn_parts.append("Extracted content truncated to 2 MiB.")
        metadata: dict[str, object] = {
            "sourceURL": redact_url(requested_url),
            "url": safe_oa_url,
            "statusCode": 200,
            "contentType": "text/plain; charset=utf-8",
            "proxyUsed": "oa-fallback",
            "doi": doi,
            "oaStatus": "green",
            "oaVersion": "unknown",
            "oaLicense": oa_lic,
            "oaSource": "CORE Open Access Repository",
        }
        if title:
            metadata["title"] = title
        payload = json.dumps(
            {"success": True, "data": {"markdown": md, "warning": " ".join(warn_parts), "metadata": metadata}}
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Firecrawl-Backend": "oa-fallback",
            "X-Firecrawl-OA-Source": "core",
        }
        return reply_cls(200, headers, payload), "oa:core unknown"

    # -- Hop-by-hop SSRF-pinned downloader

    def _fetch_candidate(
        self,
        cand: OaCandidate,
        requested_host: str,
        deadline: float,
    ) -> tuple[bytes | None, str, str, str]:
        """Fetch candidate with hop-by-hop SSRF validation and redirect loop (0..5)."""
        cur_url = cand.url
        start_host = cand.host
        prev_host = ""
        bearer_key = (
            self.key_state.get()
            if (cand.is_content_api and self.key_state is not None)
            else None
        )

        for hop in range(MAX_REDIRECTS + 1):
            if time.monotonic() >= deadline:
                self._set_cooldown(start_host)
                return None, cur_url, "", "fetch-timeout"
            parsed = parse_url(cur_url)
            if parsed is None:
                return None, cur_url, "", "url-refused"
            scheme, host, port = parsed
            if scheme != "https":
                return None, cur_url, "", "scheme-downgrade"
            if port != 443:
                return None, cur_url, "", "port-refused"
            if _is_excluded_publisher_host(host, requested_host):
                return None, cur_url, "", "redirect-publisher"
            if host in BLOCKED_REDIRECTOR_HOSTS:
                return None, cur_url, "", "redirect-blocked"
            if host == "www.ncbi.nlm.nih.gov" and not _trusted_host_path_ok(host, cur_url):
                return None, cur_url, "", "allowlist-filtered"

            if hop == 0:
                if self.config.mode == "allowlist":
                    if host not in TRUSTED_OA_HOSTS and not (
                        cand.is_content_api and host == OPENALEX_CONTENT_HOST and _trusted_host_path_ok(host, cur_url)
                    ):
                        return None, cur_url, "", "allowlist-filtered"
            else:
                if self.config.mode == "allowlist":
                    # Never climb up to parent (e.g. dspace.mit.edu -> *.mit.edu).
                    allowed_redirect = (
                        (host in TRUSTED_OA_HOSTS and _trusted_host_path_ok(host, cur_url))
                        or (
                            start_host != OPENALEX_CONTENT_HOST
                            and not _is_multi_tenant_parent(start_host)
                            and (host == start_host or host.endswith("." + start_host))
                        )
                        or (cand.is_content_api and prev_host == OPENALEX_CONTENT_HOST and _is_r2_storage_host(host))
                    )
                    if not allowed_redirect:
                        return None, cur_url, "", "redirect-off-site"

            hdrs = {
                "User-Agent": "firecrawl-router-oa/1.0",
                "Accept": "application/pdf, text/html;q=0.9, application/xhtml+xml;q=0.8",
            }
            # Attach Authorization ONLY on hop 0 to exact content.openalex.org; NEVER on redirects.
            if hop == 0 and cand.is_content_api and host == OPENALEX_CONTENT_HOST and bearer_key:
                hdrs["Authorization"] = f"Bearer {bearer_key}"

            max_bytes = MAX_PDF_BYTES if cand.is_direct_pdf else MAX_HTML_BYTES
            status, resp_hdrs, body, err = _pinned_https_request(
                cur_url,
                headers=hdrs,
                max_bytes=max_bytes,
                deadline=deadline,
                conn_factory=self._conn_factory,
                resolver=self._resolver,
            )
            if cand.is_content_api and host == OPENALEX_CONTENT_HOST:
                self.client.record_content_api_status(status, resp_hdrs, body)

            if err:
                if err in ("fetch-timeout", "fetch-error"):
                    self._set_cooldown(start_host)
                return None, cur_url, "", err

            if 300 <= status < 400:
                loc = (resp_hdrs.get("location") or "").strip()
                if not loc:
                    return None, cur_url, "", "redirect-missing-location"
                if hop >= MAX_REDIRECTS:
                    return None, cur_url, "", "too-many-redirects"
                prev_host = host
                cur_url = urllib.parse.urljoin(cur_url, loc)
                continue

            if status != 200 or body is None:
                if status in (403, 429) or status >= 500:
                    self._set_cooldown(start_host)
                return None, cur_url, "", f"fetch-http-{status}"

            ctype = (resp_hdrs.get("content-type") or "").lower().split(";", 1)[0].strip()
            path_low = (urllib.parse.urlsplit(cur_url).path or "").lower()
            is_pdf = ctype == "application/pdf" or (
                ctype in ("application/octet-stream", "") and (cand.is_direct_pdf or path_low.endswith(".pdf"))
            )
            if is_pdf:
                if len(body) < 10 or body[:5] != b"%PDF-":
                    return None, cur_url, "", "not-pdf-magic"
                if b"%%EOF" not in body[-4096:]:
                    return None, cur_url, "", "pdf-truncated"
                return body, cur_url, "pdf", ""

            is_html = ctype in ("text/html", "application/xhtml+xml")
            if is_html and (not cand.is_direct_pdf) and _is_trusted_html_url(host, cur_url):
                if len(body) > MAX_HTML_BYTES:
                    return None, cur_url, "", "oa-too-large"
                preview = body[:16384].decode("utf-8", "replace")
                if len(body) < 65536 and OA_CHALLENGE_RE.search(preview):
                    self._set_cooldown(start_host)
                    return None, cur_url, "", "oa-challenge-html"
                return body, cur_url, "html", ""

            if is_html and len(body) < 65536 and OA_CHALLENGE_RE.search(body[:16384].decode("utf-8", "replace")):
                self._set_cooldown(start_host)
                return None, cur_url, "", "oa-challenge-html"
            return None, cur_url, "", "unexpected-content-type"

        return None, cur_url, "", "too-many-redirects"

    # -- Sandboxed conversion & transparent Firecrawl v2 JSON synthesis

    def _convert_and_build_reply(
        self,
        *,
        fetched: bytes,
        content_kind: str,
        requested_url: str,
        final_url: str,
        cand: OaCandidate,
        work: dict,
        resolved_doi: str | None,
        req_doc: dict,
        deadline: float,
        reply_cls,
    ) -> tuple[object | None, str]:
        run_dir = None
        try:
            run_dir = tempfile.mkdtemp(prefix="run-", dir=self.config.state_dir)
            os.chmod(run_dir, 0o700)
            env = scrubbed_env(include_ssh_auth_sock=False, tmpdir=run_dir, home=run_dir)
            max_pages = requested_pdf_max_pages(req_doc)
            num_pages: int | None = None
            doc_title = ""
            truncated = False
            content_type = "application/pdf" if content_kind == "pdf" else "text/html; charset=utf-8"

            if content_kind == "pdf":
                if not self.config.pdftotext_bin or not os.path.isfile(self.config.pdftotext_bin) or not os.access(self.config.pdftotext_bin, os.X_OK):
                    return None, "pdftotext-missing"
                pdf_file = os.path.join(run_dir, "article.pdf")
                fd = os.open(pdf_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fd = -1
                        fh.write(fetched)
                finally:
                    if fd >= 0:
                        os.close(fd)
                verified_path, err = _safe_stat_inside(run_dir, pdf_file, MAX_PDF_BYTES)
                if verified_path is None:
                    return None, err
                left = deadline - time.monotonic()
                if left <= 0.2:
                    return None, "budget-timeout"
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
                    return None, "pdftotext-timeout"
                if res.returncode != 0 and not res.stdout_truncated:
                    return None, "pdftotext-failed"
                md, dec_trunc = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
                truncated = dec_trunc or res.stdout_truncated
                if not md.strip():
                    return None, "pdftotext-empty"
                num_pages, doc_title = self._read_pdfinfo(verified_path, env, deadline)
            else:
                if not self.config.pandoc_bin or not os.path.isfile(self.config.pandoc_bin) or not os.access(self.config.pandoc_bin, os.X_OK):
                    return None, "pandoc-missing"
                left = deadline - time.monotonic()
                if left <= 0.2:
                    return None, "budget-timeout"
                res = run_bounded(
                    [self.config.pandoc_bin, "--sandbox", "-f", "html", "-t", "gfm-raw_html", "--wrap=none"],
                    env=env,
                    timeout=min(self.config.pandoc_timeout, left),
                    max_stdout=MAX_MARKDOWN_BYTES + 1,
                    stdin_bytes=fetched,
                    kill_on_stdout_cap=True,
                )
                if res.timed_out:
                    return None, "pandoc-timeout"
                if res.returncode != 0 and not res.stdout_truncated:
                    return None, "pandoc-failed"
                md, dec_trunc = _decode_capped_utf8(res.stdout, MAX_MARKDOWN_BYTES)
                truncated = dec_trunc or res.stdout_truncated
                if not md.strip():
                    return None, "pandoc-empty"
                if len(md) < BRIDGE_CHALLENGE_MAX_CHARS and OA_CHALLENGE_RE.search(md):
                    self._set_cooldown(cand.host)
                    return None, "oa-challenge-html"
                doc_title = _extract_html_title(fetched.decode("utf-8", "replace"))

            safe_source_url = redact_url(requested_url)
            final_parsed = parse_url(final_url)
            if cand.is_content_api and final_parsed and _is_r2_storage_host(final_parsed[1]):
                safe_oa_url = redact_url(cand.url)
            else:
                safe_oa_url = redact_url(final_url)
            work_title = _sanitize_text(work.get("title"), fallback=doc_title)
            oa_obj = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
            oa_status = _sanitize_status(oa_obj.get("oa_status"))

            work_id_raw = str(work.get("id") or "").strip()
            openalex_id = ""
            if SAFE_OPENALEX_ID_RE.fullmatch(work_id_raw):
                openalex_id = work_id_raw
            elif SAFE_WORK_KEY_RE.fullmatch(work_id_raw):
                openalex_id = f"https://openalex.org/{work_id_raw}"

            work_doi = normalize_doi(str(work.get("doi") or "")) or resolved_doi or ""

            metadata: dict[str, object] = {
                "sourceURL": safe_source_url,
                "url": safe_oa_url,
                "statusCode": 200,
                "contentType": content_type,
                "proxyUsed": "oa-fallback",
                "doi": work_doi,
                "openalexId": openalex_id,
                "oaStatus": oa_status,
                "oaVersion": cand.oa_version,
                "oaLicense": cand.oa_license,
                "oaSource": cand.oa_source,
            }
            if work_title:
                metadata["title"] = work_title
            if num_pages is not None:
                metadata["numPages"] = num_pages

            if cand.oa_version != "publishedVersion":
                warn_parts = [
                    f"Served Open Access repository copy ({cand.oa_version}, license: {cand.oa_license}) "
                    f"from {cand.oa_source} at {safe_oa_url} instead of the requested publisher URL "
                    f"because the publisher scrape failed; content may differ from the Version of Record."
                ]
            else:
                warn_parts = [
                    f"Served Open Access repository copy (publishedVersion, license: {cand.oa_license}) "
                    f"from {cand.oa_source} at {safe_oa_url} instead of the requested publisher URL "
                    f"because the publisher scrape failed."
                ]
            if truncated:
                warn_parts.append("Extracted content truncated to 2 MiB.")
            if num_pages is not None and num_pages > max_pages:
                warn_parts.append(f"PDF truncated to first {max_pages} of {num_pages} pages.")

            data: dict[str, object] = {
                "markdown": md,
                "warning": " ".join(warn_parts),
                "metadata": metadata,
            }
            if content_kind == "html":
                fmts = requested_formats(req_doc)
                if "html" in fmts:
                    data["html"] = _decode_capped_utf8(fetched, MAX_MARKDOWN_BYTES)[0]
                if "rawHtml" in fmts:
                    data["rawHtml"] = _decode_capped_utf8(fetched, MAX_MARKDOWN_BYTES)[0]

            payload = json.dumps({"success": True, "data": data}).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "X-Firecrawl-Backend": "oa-fallback",
                "X-Firecrawl-OA-Source": _source_slug(cand.host),
            }
            return reply_cls(200, headers, payload), ""
        finally:
            if run_dir:
                shutil.rmtree(run_dir, ignore_errors=True)

    def _read_pdfinfo(self, pdf_path: str, env: dict[str, str], deadline: float) -> tuple[int | None, str]:
        if not self.config.pdfinfo_bin or not os.path.isfile(self.config.pdfinfo_bin) or not os.access(self.config.pdfinfo_bin, os.X_OK):
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
