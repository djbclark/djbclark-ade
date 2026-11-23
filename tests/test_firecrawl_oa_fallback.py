"""Zero-network unit and integration tests for bin/firecrawl_oa_fallback.py and Router OA fallback."""
from __future__ import annotations

import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]


def _load_router():
    if "firecrawl_router" in sys.modules:
        return sys.modules["firecrawl_router"]
    loader = importlib.machinery.SourceFileLoader("firecrawl_router", str(ROOT / "bin" / "firecrawl-router"))
    spec = importlib.util.spec_from_loader("firecrawl_router", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["firecrawl_router"] = mod
    loader.exec_module(mod)
    return mod


fr = _load_router()
oa = fr._OA_FALLBACK_MOD
mb = fr._MIT_BRIDGE_MOD


def _write_exec(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)
    return str(path)


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes | list[bytes]):
        self.status = status
        self._headers = dict(headers)
        if isinstance(body, bytes):
            self._chunks = [body] if body else []
        else:
            self._chunks = list(body)
        self._idx = 0

    def getheaders(self):
        return list(self._headers.items())

    def getheader(self, name: str, default=None):
        low = name.lower()
        for k, v in self._headers.items():
            if k.lower() == low:
                return v
        return default

    def read(self, amt: int = -1) -> bytes:
        if self._idx >= len(self._chunks):
            return b""
        chunk = self._chunks[self._idx]
        if amt is None or amt < 0 or len(chunk) <= amt:
            self._idx += 1
            return chunk
        self._chunks[self._idx] = chunk[amt:]
        return chunk[:amt]


class _FakePinnedConnFactory:
    """In-memory fake for _PinnedHTTPSConnection recording every host, pinned_ip, target, and header."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def __call__(self, host: str, port: int = 443, *, pinned_ip: str, timeout: float = 5.0, context=None):
        factory = self

        class _Conn:
            def __init__(self):
                self.host = host
                self.port = port
                self.pinned_ip = pinned_ip
                self.timeout = timeout
                self.sock = None
                self._resp = None

            def request(self, method: str, target: str, headers: dict | None = None):
                rec = {
                    "host": host,
                    "port": port,
                    "pinned_ip": pinned_ip,
                    "method": method,
                    "target": target,
                    "headers": dict(headers or {}),
                }
                factory.calls.append(rec)
                res = factory.responder(rec)
                if isinstance(res, BaseException):
                    raise res
                status, hdrs, body = res
                self._resp = _FakeResponse(status, hdrs, body)

            def getresponse(self):
                return self._resp

            def close(self):
                pass

        return _Conn()


def _valid_pdf_bytes(extra: bytes = b"") -> bytes:
    return b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n" + extra + b"\n%%EOF\n"


def _acm_sosp_work() -> dict:
    return {
        "id": "https://openalex.org/W4387321091",
        "doi": "https://doi.org/10.1145/3600006.3613165",
        "title": "Efficient Memory Management for Large Language Model Serving with PagedAttention",
        "publication_year": 2023,
        "open_access": {"is_oa": True, "oa_status": "hybrid"},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165",
            "landing_page_url": "https://doi.org/10.1145/3600006.3613165",
            "version": "publishedVersion",
            "license": "cc-by",
            "source": {"display_name": "SOSP", "type": "conference"},
        },
        "locations": [
            {
                "is_oa": True,
                "pdf_url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165",
                "landing_page_url": "https://dl.acm.org/doi/10.1145/3600006.3613165",
                "version": "publishedVersion",
                "license": "cc-by",
                "source": {"display_name": "SOSP", "type": "conference"},
            },
            {
                "is_oa": True,
                "pdf_url": "https://arxiv.org/pdf/2309.06180",
                "landing_page_url": "http://arxiv.org/abs/2309.06180",
                "version": "submittedVersion",
                "license": "cc-by",
                "source": {"display_name": "arXiv (Cornell University)", "type": "repository"},
            },
        ],
        "has_content": {"pdf": True},
        "content_urls": {"pdf": "https://content.openalex.org/works/W4387321091.pdf"},
    }


def _elsevier_work() -> dict:
    return {
        "id": "https://openalex.org/W2975245087",
        "doi": "https://doi.org/10.1016/j.artint.2021.103504",
        "title": "DeepProbLog: Neural Probabilistic Logic Programming",
        "open_access": {"is_oa": True, "oa_status": "bronze"},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": "https://www.sciencedirect.com/science/article/pii/S0004370221000552",
            "landing_page_url": "https://www.sciencedirect.com/science/article/pii/S0004370221000552",
            "version": "publishedVersion",
            "license": "elsevier-oa",
            "source": {"display_name": "Artificial Intelligence", "type": "journal"},
        },
        "locations": [
            {
                "is_oa": True,
                "pdf_url": "https://pdf.sciencedirect.com/S0004370221000552.pdf",
                "version": "publishedVersion",
                "license": "cc-by",
                "source": {"display_name": "ScienceDirect", "type": "journal"},
            },
            {
                "is_oa": True,
                "pdf_url": "https://arxiv.org/pdf/1907.08194",
                "version": "submittedVersion",
                "license": "cc-by",
                "source": {"display_name": "arXiv", "type": "repository"},
            },
            {
                "is_oa": True,
                "pdf_url": "https://biblio.ugent.be/publication/8721037/file/8721039.pdf",
                "version": "publishedVersion",
                "license": "cc-by",
                "source": {"display_name": "Ghent University", "type": "repository"},
            },
        ],
        "has_content": {"pdf": True},
        "content_urls": {"pdf": "https://content.openalex.org/works/W2975245087.pdf"},
    }


def _aps_prl_work() -> dict:
    return {
        "id": "https://openalex.org/W4396576837",
        "doi": "https://doi.org/10.1103/PhysRevLett.132.181601",
        "title": "APS PRL 2024 Hybrid Paper",
        "open_access": {"is_oa": True, "oa_status": "hybrid"},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": None,
            "landing_page_url": "https://doi.org/10.1103/PhysRevLett.132.181601",
            "version": "publishedVersion",
            "license": "cc-by",
            "source": {"display_name": "Physical Review Letters", "type": "journal"},
        },
        "locations": [
            {
                "is_oa": True,
                "pdf_url": "http://cds.cern.ch/record/2890999/files/2311.01501.pdf",
                "version": "submittedVersion",
                "license": "cc-by",
                "source": {"display_name": "CERN CDS", "type": "repository"},
            },
            {
                "is_oa": True,
                "pdf_url": "https://arxiv.org/pdf/2311.01501",
                "version": "submittedVersion",
                "license": "cc-by",
                "source": {"display_name": "arXiv", "type": "repository"},
            },
        ],
    }


def _wiley_pmc_work() -> dict:
    return {
        "id": "https://openalex.org/W4391316368",
        "doi": "https://doi.org/10.1002/14651858.cd001431.pub6",
        "title": "Wiley Green OA via PMC",
        "open_access": {"is_oa": True, "oa_status": "green"},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": None,
            "landing_page_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/10823577",
            "version": "publishedVersion",
            "license": "public-domain",
            "source": {"display_name": "PubMed Central", "type": "repository"},
        },
        "locations": [
            {
                "is_oa": True,
                "pdf_url": None,
                "landing_page_url": "https://www.ncbi.nlm.nih.gov/pubmed/10823577",
                "version": "publishedVersion",
                "license": "public-domain",
                "source": {"display_name": "PubMed", "type": "repository"},
            },
            {
                "is_oa": True,
                "pdf_url": None,
                "landing_page_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/10823577",
                "version": "publishedVersion",
                "license": "public-domain",
                "source": {"display_name": "PubMed Central", "type": "repository"},
            },
        ],
    }


class IdentifierExtractionTest(unittest.TestCase):
    """Category 2: Identifier extraction, normalization, and ReDoS bounds."""

    def test_extract_doi_publishers_and_nature_and_repos(self):
        cases = (
            ("https://doi.org/10.1145/3600006.3613165", ("doi", "10.1145/3600006.3613165")),
            ("https://dx.doi.org/10.1016/j.artint.2021.103504.", ("doi", "10.1016/j.artint.2021.103504")),
            ("https://dl.acm.org/doi/pdf/10.1145/3600006.3613165?download=true", ("doi", "10.1145/3600006.3613165")),
            ("https://dl.acm.org/doi/pdf/10.1145%2F3600006.3613165", ("doi", "10.1145/3600006.3613165")),
            ("https://onlinelibrary.wiley.com/doi/epdf/10.1002/anie.4701250", ("doi", "10.1002/anie.4701250")),
            ("https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.132.181601", ("doi", "10.1103/PhysRevLett.132.181601")),
            ("https://link.springer.com/article/10.1007/s00000-023-00001-x/full", ("doi", "10.1007/s00000-023-00001-x")),
            ("https://link.springer.com/content/pdf/10.1007/s00000-023-00001-x.pdf", ("doi", "10.1007/s00000-023-00001-x")),
            ("https://iopscience.iop.org/article/10.1088/1361-648X/ab1234/pdf", ("doi", "10.1088/1361-648X/ab1234")),
            ("https://www.jstor.org/stable/10.2307/20031001", ("doi", "10.2307/20031001")),
            ("https://www.science.org/doi/10.1126/science.aed0788.full.pdf", ("doi", "10.1126/science.aed0788")),
            ("https://www.nature.com/articles/nature14539", ("doi", "10.1038/nature14539")),
            ("https://www.nature.com/articles/s41586-023-06747-5.pdf", ("doi", "10.1038/s41586-023-06747-5")),
            ("https://arxiv.org/abs/2309.06180v2", ("arxiv", "2309.06180")),
            ("https://arxiv.org/pdf/hep-th/9711200v1.pdf", ("arxiv", "hep-th/9711200")),
            ("https://pubmed.ncbi.nlm.nih.gov/29456894/", ("pmid", "29456894")),
            ("https://pmc.ncbi.nlm.nih.gov/articles/PMC10823577/", ("pmcid", "PMC10823577")),
            ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10823577/", ("pmcid", "PMC10823577")),
            ("https://www.sciencedirect.com/science/article/pii/S0004370221000552", ("pii", "S0004370221000552")),
            ("https://www.sciencedirect.com/science/article/abs/pii/s0004370221000552", ("pii", "S0004370221000552")),
        )
        for url, want in cases:
            with self.subTest(url=url):
                self.assertEqual(oa.extract_identifier(url), want)

    def test_normalize_doi_strict_validation_and_single_unquote(self):
        self.assertEqual(oa.normalize_doi("10.1016/S0004-3702(21)00055-2"), "10.1016/S0004-3702(21)00055-2")
        self.assertEqual(oa.normalize_doi("10.1145/3600006.3613165),."), "10.1145/3600006.3613165")
        self.assertEqual(oa.normalize_doi("10.1145/3600006.3613165/epdf"), "10.1145/3600006.3613165")
        # Double-encoded slash must NOT pass extract_identifier (unquote once only -> '%' remains -> rejected).
        self.assertIsNone(oa.extract_identifier("https://dl.acm.org/doi/pdf/10.1145%252F3600006.3613165"))
        # Path traversal and invalid characters rejected.
        for bad in ("10.1145/../../etc/passwd", "10.1145/a b", "10.1145/a?b=1", "10.1145/a#b", "10.1145/a%20b", "not-a-doi"):
            self.assertIsNone(oa.normalize_doi(bad), bad)
        # Non-scholarly URLs return None.
        self.assertIsNone(oa.extract_identifier("https://ieeexplore.ieee.org/document/7780459"))
        self.assertIsNone(oa.extract_identifier("https://www.nature.com/articles/editorial-2026"))

    def test_hostile_4kib_urls_rejected_quickly_without_redos(self):
        hostile = [
            "https://dl.acm.org/doi/" + ("pdf/" * 900) + "10.1145/" + ("a" * 300),
            "https://www.nature.com/articles/" + ("s" * 3900) + ".pdf",
            "https://link.springer.com/" + ("article/" * 450) + "10.1007/" + ("x" * 300),
            "https://www.sciencedirect.com/science/article/pii/" + ("A" * 3900),
            "https://doi.org/" + ("1" * 4500),
        ]
        for u in hostile:
            t0 = time.monotonic()
            res = oa.extract_identifier(u)
            dt = time.monotonic() - t0
            self.assertLess(dt, 0.05, (u[:60], dt))
            if len(u) > 4096:
                self.assertIsNone(res)


class CandidateRankingTest(unittest.TestCase):
    """Category 3: Candidate ranking, publisher loop avoidance, policies, content.openalex.org."""

    def test_acm_elsevier_aps_wiley_fixtures(self):
        # ACM SOSP: dl.acm.org excluded -> arxiv wins
        cands, err = oa.rank_oa_candidates(_acm_sosp_work(), "dl.acm.org", host_policy="allowlist")
        self.assertEqual(err, "")
        self.assertEqual([c.url for c in cands], ["https://arxiv.org/pdf/2309.06180"])

        # Elsevier: www.sciencedirect.com & pdf.sciencedirect.com excluded; biblio.ugent.be (published) beats arxiv (submitted)
        cands, err = oa.rank_oa_candidates(_elsevier_work(), "www.sciencedirect.com", host_policy="allowlist")
        self.assertEqual(err, "")
        self.assertEqual([c.host for c in cands], ["biblio.ugent.be", "arxiv.org"])

        # APS PRL: doi.org excluded, http://cds.cern.ch excluded -> arxiv wins
        cands, err = oa.rank_oa_candidates(_aps_prl_work(), "journals.aps.org", host_policy="allowlist")
        self.assertEqual(err, "")
        self.assertEqual([c.url for c in cands], ["https://arxiv.org/pdf/2311.01501"])

        # Wiley green OA: www.ncbi.nlm.nih.gov/pubmed/ dropped; /pmc/articles/ HTML wins
        cands, err = oa.rank_oa_candidates(_wiley_pmc_work(), "onlinelibrary.wiley.com", host_policy="allowlist")
        self.assertEqual(err, "")
        self.assertEqual([c.url for c in cands], ["https://www.ncbi.nlm.nih.gov/pmc/articles/10823577"])
        self.assertFalse(cands[0].is_direct_pdf)

    def test_version_and_host_and_content_api_policies(self):
        # peer-reviewed drops submittedVersion arxiv on ACM
        cands, err = oa.rank_oa_candidates(_acm_sosp_work(), "dl.acm.org", version_policy="peer-reviewed")
        self.assertEqual((cands, err), ([], "version-filtered"))

        # content.openalex.org enabled with best_oa_location.version == publishedVersion beats submittedVersion arxiv
        cands, err = oa.rank_oa_candidates(_acm_sosp_work(), "dl.acm.org", content_api_allowed=True)
        self.assertEqual(err, "")
        self.assertEqual([c.host for c in cands], ["content.openalex.org", "arxiv.org"])

        # On Elsevier, free publishedVersion biblio.ugent.be still beats paid-quota content.openalex.org
        cands, err = oa.rank_oa_candidates(_elsevier_work(), "www.sciencedirect.com", content_api_allowed=True)
        self.assertEqual([c.host for c in cands], ["biblio.ugent.be", "content.openalex.org", "arxiv.org"])

        # When best_oa_location is NOT publishedVersion, content.openalex.org ranks BELOW free arxiv
        w = _acm_sosp_work()
        w["best_oa_location"]["version"] = "submittedVersion"
        cands, _ = oa.rank_oa_candidates(w, "dl.acm.org", content_api_allowed=True)
        self.assertEqual([c.host for c in cands], ["arxiv.org", "content.openalex.org"])

        # Unknown host dropped in allowlist mode, accepted lowest-ranked in pinned mode
        unknown_work = {
            "open_access": {"is_oa": True, "oa_status": "green"},
            "locations": [{
                "is_oa": True,
                "pdf_url": "https://repo.unlisted-uni.example/paper.pdf",
                "version": "publishedVersion",
                "license": "cc-by",
                "source": {"display_name": "Unlisted Uni", "type": "repository"},
            }],
        }
        self.assertEqual(
            oa.rank_oa_candidates(unknown_work, "dl.acm.org", host_policy="allowlist"),
            ([], "allowlist-filtered"),
        )
        cands, err = oa.rank_oa_candidates(unknown_work, "dl.acm.org", host_policy="pinned")
        self.assertEqual(err, "")
        self.assertEqual(cands[0].host, "repo.unlisted-uni.example")


class SsrfAndPinnedIpTest(unittest.TestCase):
    """Category 4: SSRF IP filtering, pinned connection, and redirect defenses."""

    def test_resolve_global_blocks_private_cgnat_nat64_mapped_and_mixed(self):
        def _fake_gai(ips):
            return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

        blocked = [
            ["127.0.0.1"],
            ["::1"],
            ["10.0.0.1"],
            ["172.16.0.1"],
            ["192.168.1.5"],
            ["169.254.169.254"],
            ["100.64.0.1"],
            ["100.127.255.254"],
            ["::ffff:127.0.0.1"],
            ["::ffff:100.64.0.5"],
            ["64:ff9b::127.0.0.1"],
            ["64:ff9b::10.0.0.1"],
            ["93.184.216.34", "127.0.0.1"],  # mixed global + private MUST be refused
        ]
        for ips in blocked:
            with self.subTest(ips=ips):
                with unittest.mock.patch.object(oa.socket, "getaddrinfo", return_value=_fake_gai(ips)):
                    self.assertIsNone(oa.resolve_global("arxiv.org", 443))

        with unittest.mock.patch.object(oa.socket, "getaddrinfo", return_value=_fake_gai(["93.184.216.34"])):
            self.assertEqual(oa.resolve_global("arxiv.org", 443), "93.184.216.34")

    def test_pinned_https_connection_connects_to_ip_with_host_sni_and_tls12(self):
        fake_sock = unittest.mock.MagicMock()
        wrapped_sock = unittest.mock.MagicMock()
        ctx = oa._make_ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

        with unittest.mock.patch.object(oa.socket, "create_connection", return_value=fake_sock) as cc, \
             unittest.mock.patch.object(ctx, "wrap_socket", return_value=wrapped_sock) as ws:
            conn = oa._PinnedHTTPSConnection("arxiv.org", 443, pinned_ip="93.184.216.34", timeout=3.0, context=ctx)
            conn.connect()
        cc.assert_called_once_with(("93.184.216.34", 443), 3.0)
        ws.assert_called_once_with(fake_sock, server_hostname="arxiv.org")
        self.assertIs(conn.sock, wrapped_sock)

    def test_redirect_downgrade_non443_loop_publisher_and_offsite_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cand = oa.OaCandidate(
                url="https://arxiv.org/pdf/2309.06180",
                host="arxiv.org",
                is_direct_pdf=True,
                oa_version="submittedVersion",
                oa_license="cc-by",
                oa_source="arXiv",
                is_content_api=False,
                score=(3, 3, 1, 1, 1, 1),
            )
            cases = (
                ("http://arxiv.org/pdf/2309.06180", "scheme-downgrade"),
                ("https://arxiv.org:8443/pdf/2309.06180", "port-refused"),
                ("https://dl.acm.org/doi/pdf/10.1145/3600006.3613165", "redirect-publisher"),
                ("https://pubs.acm.org/doi/pdf/10.1145/3600006.3613165", "redirect-publisher"),
                ("https://evil.example/paper.pdf", "redirect-off-site"),
                ("https://acct.r2.cloudflarestorage.com/paper.pdf", "redirect-off-site"),
                ("https://doi.org/10.1145/3600006.3613165", "redirect-blocked"),
            )
            for loc, want_err in cases:
                with self.subTest(loc=loc):
                    factory = _FakePinnedConnFactory(lambda rec, _loc=loc: (302, {"Location": _loc}, b""))
                    fb = oa.OaFallback(
                        oa.OaFallbackConfig(mode="allowlist", secretspec_bin="", state_dir=td),
                        log=io.StringIO(),
                        conn_factory=factory,
                        resolver=lambda h, p: "93.184.216.34",
                    )
                    body, _, _, err = fb._fetch_candidate(cand, "dl.acm.org", time.monotonic() + 10)
                    self.assertIsNone(body)
                    self.assertEqual(err, want_err)

            # >5 redirects refused
            hop_n = {"n": 0}
            def _loop(rec):
                hop_n["n"] += 1
                return (302, {"Location": f"https://arxiv.org/pdf/hop{hop_n['n']}.pdf"}, b"")
            fb_loop = oa.OaFallback(
                oa.OaFallbackConfig(mode="allowlist", secretspec_bin="", state_dir=td),
                log=io.StringIO(),
                conn_factory=_FakePinnedConnFactory(_loop),
                resolver=lambda h, p: "93.184.216.34",
            )
            body, _, _, err = fb_loop._fetch_candidate(cand, "dl.acm.org", time.monotonic() + 10)
            self.assertIsNone(body)
            self.assertEqual(err, "too-many-redirects")
            self.assertEqual(hop_n["n"], 6)


class OaFallbackEndToEndTest(unittest.TestCase):
    """Categories 1, 5, 6, 7: End-to-end Router integration, secrets, converters, concurrency, LLM, enrolled."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.state_dir = self.root / "oa-state"
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir(mode=0o700)

        self.pdftotext_bin = _write_exec(self.root / "fake_pdftotext", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
Path({str(self.log_dir / 'pdftotext_argv.json')!r}).write_text(json.dumps(sys.argv[1:]))
Path({str(self.log_dir / 'pdftotext_env.json')!r}).write_text(json.dumps(dict(os.environ)))
sys.stdout.write("# PagedAttention Paper\\n\\nConverted Open Access PDF body.\\n")
""")
        self.pdfinfo_bin = _write_exec(self.root / "fake_pdfinfo", f"""#!{sys.executable}
import sys
sys.stdout.write("Title:          Fallback PDF Title\\nPages:          16\\n")
""")
        self.pandoc_bin = _write_exec(self.root / "fake_pandoc", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
Path({str(self.log_dir / 'pandoc_argv.json')!r}).write_text(json.dumps(sys.argv[1:]))
Path({str(self.log_dir / 'pandoc_env.json')!r}).write_text(json.dumps(dict(os.environ)))
assert "--sandbox" in sys.argv[1:]
sys.stdout.write("# PMC Full Text Article\\n\\nConverted Open Access HTML body.\\n")
""")
        self.secretspec_bin = _write_exec(self.root / "fake_secretspec", f"""#!{sys.executable}
import json, sys
from pathlib import Path
Path({str(self.log_dir / 'secretspec_argv.json')!r}).write_text(json.dumps(sys.argv[1:]))
sys.stdout.write("OA_SECRET_TEST_KEY_12345\\n")
""")

    def tearDown(self):
        self._td.cleanup()

    def _make_oa(self, responder, **overrides):
        factory = _FakePinnedConnFactory(responder)
        kw = dict(
            mode="allowlist",
            version_policy="all",
            content_api=False,
            allow_enrolled=True,
            secretspec_bin="",
            state_dir=str(self.state_dir),
            pdftotext_bin=self.pdftotext_bin,
            pdfinfo_bin=self.pdfinfo_bin,
            pandoc_bin=self.pandoc_bin,
            cooldown_s=60.0,
            sem_timeout=0.1,
        )
        kw.update(overrides)
        inst = oa.OaFallback(
            oa.OaFallbackConfig(**kw),
            log=io.StringIO(),
            reply_cls=fr.Reply,
            conn_factory=factory,
            resolver=lambda h, p: "93.184.216.34",
            sleep_fn=lambda _s: None,
        )
        return inst, factory

    def _blocked_primary_reply(self, code: int = 403):
        return fr.Reply(
            200,
            {"Content-Type": "application/json"},
            json.dumps({"success": True, "data": {"markdown": "Just a moment...", "metadata": {"statusCode": code}}}).encode(),
        )

    def _router(self, primary_reply, oa_inst=None, fallback_reply=None, mit_bridge=None, extractor=None):
        router = fr.Router(
            fr.Backend("primary", "http://127.0.0.1:9", "pk"),
            fr.Backend("fallback", "http://127.0.0.1:9", "fk") if fallback_reply is not None else None,
            timeout=5,
            log=io.StringIO(),
            extractor=extractor,
            mit_bridge=mit_bridge,
            oa_fallback=oa_inst,
        )
        seen_backends = []

        def fake_call(backend, method, path, headers, body, timeout):
            seen_backends.append(backend.name)
            return primary_reply if backend.name == "primary" else fallback_reply

        return router, fake_call, seen_backends

    def test_category1_default_off_invalid_env_and_route_gating(self):
        err = io.StringIO()
        self.assertIsNone(oa.build_oa_fallback({}, log=err))
        self.assertIsNone(oa.build_oa_fallback({"FIRECRAWL_ROUTER_OA_FALLBACK": "off"}, log=err))
        self.assertIsNone(oa.build_oa_fallback({"FIRECRAWL_ROUTER_OA_FALLBACK": "bogus"}, log=err))
        self.assertIn("failing closed (off)", err.getvalue())

        err2 = io.StringIO()
        inst = oa.build_oa_fallback({
            "FIRECRAWL_ROUTER_OA_FALLBACK": "allowlist",
            "FIRECRAWL_ROUTER_OA_VERSIONS": "bogus",
            "FIRECRAWL_ROUTER_OA_CONTENT_API": "bogus",
            "FIRECRAWL_ROUTER_OA_ENROLLED": "bogus",
            "FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN": "",
            "FIRECRAWL_ROUTER_OA_STATE_DIR": str(self.state_dir),
            "FIRECRAWL_ROUTER_OA_COOLDOWN_S": "nan",
        }, log=err2)
        self.assertEqual(inst.config.version_policy, "peer-reviewed")
        self.assertFalse(inst.config.content_api)
        self.assertFalse(inst.config.allow_enrolled)
        self.assertEqual(inst.config.cooldown_s, oa.DEFAULT_COOLDOWN_S)

        # Non-scrape routes and healthy 200 primary never call OpenAlex
        inst2, factory = self._make_oa(lambda rec: self.fail("should never make network call"))
        for route in ("/v2/crawl", "/v2/batch/scrape", "/v2/map", "/v2/search", "/v1/crawl"):
            r, b, note = inst2.maybe_fallback("POST", route, json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode(),
                                              self._blocked_primary_reply(), "page status 403", fr.Reply)
            self.assertEqual((r, b, note), (None, None, ""), route)

        ok_reply = fr.Reply(200, {"Content-Type": "application/json"}, json.dumps({
            "success": True, "data": {"markdown": "Real article body " * 100, "metadata": {"statusCode": 200}},
        }).encode())
        r, b, note = inst2.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://dl.acm.org/doi/10.1145/3600006.3613165"}).encode(),
                                          ok_reply, "", fr.Reply)
        self.assertEqual((r, b, note), (None, None, ""))
        self.assertEqual(factory.calls, [])

    def test_category5_secret_isolation_content_api_and_403_fallback(self):
        work = _acm_sosp_work()

        def responder(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json", "X-RateLimit-Remaining-Usd": "0.95"},
                        json.dumps(work).encode())
            if rec["host"] == "content.openalex.org":
                return (302, {"Location": "https://oa-bucket.r2.cloudflarestorage.com/works/W4387321091.pdf?X-Amz-Signature=PRESIGN"}, b"")
            if rec["host"] == "oa-bucket.r2.cloudflarestorage.com":
                return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
            raise AssertionError(f"unexpected host: {rec['host']}")

        inst, factory = self._make_oa(
            responder,
            content_api=True,
            secretspec_bin=self.secretspec_bin,
        )
        router, fake_call, _ = self._router(self._blocked_primary_reply(), oa_inst=inst)
        with unittest.mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "ENV_LEAK_KEY", "FIRECRAWL_ROUTER_OPENALEX_KEY": "ENV_LEAK_KEY2"}), \
             unittest.mock.patch.object(fr, "call", side_effect=fake_call):
            reply, backend = router.handle(
                "POST", "/v2/scrape", {"Content-Type": "application/json"},
                json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165?secret=URLTOK"}).encode(),
            )

        self.assertEqual((reply.status, backend), (200, "oa-fallback"))
        self.assertEqual(reply.headers.get("X-Firecrawl-Backend"), "oa-fallback")
        self.assertEqual(reply.headers.get("X-Firecrawl-OA-Source"), "openalex-content")
        doc = reply.json()
        meta = doc["data"]["metadata"]
        self.assertEqual(meta["sourceURL"], "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165")
        self.assertEqual(meta["url"], "https://content.openalex.org/works/W4387321091.pdf")
        self.assertNotIn("PRESIGN", json.dumps(doc))
        self.assertNotIn("URLTOK", json.dumps(doc))
        self.assertNotIn("OA_SECRET_TEST_KEY_12345", json.dumps(doc))
        self.assertNotIn("OA_SECRET_TEST_KEY_12345", router.log.getvalue())

        # Verify Authorization header sent ONLY to api.openalex.org and content.openalex.org, stripped on R2 redirect, never in query
        self.assertEqual([c["host"] for c in factory.calls], [
            "api.openalex.org", "content.openalex.org", "oa-bucket.r2.cloudflarestorage.com"
        ])
        self.assertEqual(factory.calls[0]["headers"].get("Authorization"), "Bearer OA_SECRET_TEST_KEY_12345")
        self.assertNotIn("api_key", factory.calls[0]["target"])
        self.assertEqual(factory.calls[1]["headers"].get("Authorization"), "Bearer OA_SECRET_TEST_KEY_12345")
        self.assertNotIn("Authorization", factory.calls[2]["headers"])

        # Verify converter scrubbed_env has zero secrets
        conv_env = json.loads((self.log_dir / "pdftotext_env.json").read_text())
        self.assertNotIn("OPENALEX_API_KEY", conv_env)
        self.assertNotIn("FIRECRAWL_ROUTER_OPENALEX_KEY", conv_env)
        self.assertNotIn("OA_SECRET_TEST_KEY_12345", json.dumps(conv_env))

        # Verify 403 key_not_activated disables key and retries cleanly keyless
        seen_auth = []
        def responder_403(rec):
            if rec["host"] == "api.openalex.org":
                seen_auth.append(rec["headers"].get("Authorization"))
                if rec["headers"].get("Authorization"):
                    return (403, {"Content-Type": "application/json"}, b'{"error":"key_not_activated"}')
                return (200, {"Content-Type": "application/json"}, json.dumps(work).encode())
            if rec["host"] == "arxiv.org":
                seen_auth.append(("arxiv", rec["headers"].get("Authorization")))
                return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
            raise AssertionError(rec["host"])

        inst2, _ = self._make_oa(responder_403, secretspec_bin=self.secretspec_bin)
        reply2, backend2, _ = inst2.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((reply2.status, backend2), (200, "oa-fallback"))
        self.assertEqual(seen_auth, ["Bearer OA_SECRET_TEST_KEY_12345", None, ("arxiv", None)])

    def test_category6_pdf_html_truncation_oversize_challenge_and_orphan_sweep(self):
        # 1. Valid PDF with submittedVersion -> mandatory warning flags non-VoR, temp dir cleaned
        work = _acm_sosp_work()
        work["title"] = "Clean\x00Title\x07 " + ("X" * 350)
        work["locations"][1]["source"]["display_name"] = "arXiv\x1b[31m Repo"

        def resp_pdf(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(work).encode())
            if rec["host"] == "arxiv.org":
                return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
            raise AssertionError(rec["host"])

        inst, _ = self._make_oa(resp_pdf)
        reply, backend, _ = inst.maybe_fallback(
            "POST", "/v1/scrape",
            json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165", "pdfOptions": {"maxPages": 10}}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((reply.status, backend), (200, "oa-fallback"))
        doc = reply.json()
        meta = doc["data"]["metadata"]
        self.assertEqual(meta["proxyUsed"], "oa-fallback")
        self.assertNotEqual(meta["sourceURL"], meta["url"])
        self.assertEqual(meta["doi"], "10.1145/3600006.3613165")
        self.assertEqual(meta["openalexId"], "https://openalex.org/W4387321091")
        self.assertEqual(meta["oaStatus"], "hybrid")
        self.assertEqual(meta["oaVersion"], "submittedVersion")
        self.assertEqual(meta["oaLicense"], "cc-by")
        self.assertNotIn("\x00", meta["title"])
        self.assertLessEqual(len(meta["title"]), 300)
        self.assertNotIn("\x1b", meta["oaSource"])
        self.assertIn("submittedVersion", doc["data"]["warning"])
        self.assertIn("content may differ from the Version of Record", doc["data"]["warning"])
        self.assertIn("first 10 of 16 pages", doc["data"]["warning"])
        self.assertEqual(list(self.state_dir.glob("run-*")), [])

        # 2. Truncated PDF missing %%EOF advances to next candidate
        ework = _elsevier_work()
        def resp_trunc(rec):
            if rec["host"] == "api.crossref.org":
                return (200, {"Content-Type": "application/json"}, json.dumps({
                    "message": {"items": [{"DOI": "10.1016/j.artint.2021.103504", "alternative-id": ["S0004370221000552"]}]}
                }).encode())
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(ework).encode())
            if rec["host"] == "biblio.ugent.be":
                return (200, {"Content-Type": "application/pdf"}, b"%PDF-1.7 truncated without eof marker")
            if rec["host"] == "arxiv.org":
                return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
            raise AssertionError(rec["host"])

        inst2, factory2 = self._make_oa(resp_trunc, contact="ops@example.edu")
        reply2, backend2, _ = inst2.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://www.sciencedirect.com/science/article/pii/S0004370221000552"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((reply2.status, backend2), (200, "oa-fallback"))
        self.assertEqual([c["host"] for c in factory2.calls], [
            "api.crossref.org", "api.openalex.org", "biblio.ugent.be", "arxiv.org"
        ])
        self.assertIn("mailto:ops@example.edu", factory2.calls[0]["headers"]["User-Agent"])

        # 3. Crossref PII mismatch refused
        def resp_pii_bad(rec):
            return (200, {"Content-Type": "application/json"}, json.dumps({
                "message": {"items": [{"DOI": "10.1016/j.artint.2021.103504", "alternative-id": ["WRONGPII99999"]}]}
            }).encode())
        inst_pii, _ = self._make_oa(resp_pii_bad)
        r_pii, b_pii, n_pii = inst_pii.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://www.sciencedirect.com/science/article/pii/S0004370221000552"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((r_pii, b_pii, n_pii), (None, None, "crossref-pii-mismatch"))

        # 4. >32 MiB streaming PDF aborted immediately
        def resp_big(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(_acm_sosp_work()).encode())
            return (200, {"Content-Type": "application/pdf"}, [b"%PDF-1.7\n"] + [b"A" * (1024 * 1024)] * 33)
        inst_big, _ = self._make_oa(resp_big)
        r_big, b_big, n_big = inst_big.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((r_big, b_big, n_big), (None, None, "oa-too-large"))

        # 5. Trusted-repo HTML (Wiley -> PMC redirect) via pandoc --sandbox, publishedVersion warning
        def resp_pmc(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(_wiley_pmc_work()).encode())
            if rec["host"] == "www.ncbi.nlm.nih.gov":
                return (301, {"Location": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10823577/"}, b"")
            if rec["host"] == "pmc.ncbi.nlm.nih.gov":
                return (200, {"Content-Type": "text/html; charset=utf-8"},
                        b"<html><head><title>PMC Paper</title></head><body><h1>Article</h1><p>Full text.</p></body></html>")
            raise AssertionError(rec["host"])

        inst_pmc, _ = self._make_oa(resp_pmc)
        r_pmc, b_pmc, _ = inst_pmc.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://onlinelibrary.wiley.com/doi/full/10.1002/14651858.cd001431.pub6", "formats": ["markdown", "html"]}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((r_pmc.status, b_pmc), (200, "oa-fallback"))
        self.assertEqual(r_pmc.headers.get("X-Firecrawl-OA-Source"), "pmc")
        pmc_doc = r_pmc.json()
        self.assertIn("Converted Open Access HTML body", pmc_doc["data"]["markdown"])
        self.assertIn("<h1>Article</h1>", pmc_doc["data"]["html"])
        self.assertIn("publishedVersion", pmc_doc["data"]["warning"])
        self.assertNotIn("content may differ from the Version of Record", pmc_doc["data"]["warning"])
        self.assertIn("--sandbox", json.loads((self.log_dir / "pandoc_argv.json").read_text()))

        # 6. Challenge HTML from OA repo rejected + sets cooldown
        def resp_chal(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(_wiley_pmc_work()).encode())
            return (200, {"Content-Type": "text/html"}, b"<html><title>Just a moment...</title><body>Checking your browser</body></html>")
        inst_ch, _ = self._make_oa(resp_chal)
        r_ch, b_ch, n_ch = inst_ch.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://onlinelibrary.wiley.com/doi/full/10.1002/14651858.cd001431.pub6"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((r_ch, b_ch, n_ch), (None, None, "oa-challenge-html"))
        # Second call hits cooldown without hitting PMC
        r_ch2, b_ch2, n_ch2 = inst_ch.maybe_fallback(
            "POST", "/v2/scrape",
            json.dumps({"url": "https://onlinelibrary.wiley.com/doi/full/10.1002/14651858.cd001431.pub6"}).encode(),
            self._blocked_primary_reply(), "page status 403", fr.Reply,
        )
        self.assertEqual((r_ch2, b_ch2, n_ch2), (None, None, "cooldown"))

        # 7. Startup orphan sweep removes >10 min run-* dirs only
        sweep_dir = self.root / "sweep-state"
        sweep_dir.mkdir(mode=0o700)
        old_run = sweep_dir / "run-old"
        old_run.mkdir(mode=0o700)
        old_t = time.time() - 900
        os.utime(old_run, (old_t, old_t))
        new_run = sweep_dir / "run-new"
        new_run.mkdir(mode=0o700)
        keep_file = sweep_dir / "keep.txt"
        keep_file.write_text("ok")
        self._make_oa(lambda rec: (404, {}, b""), state_dir=str(sweep_dir))
        self.assertFalse(old_run.exists())
        self.assertTrue(new_run.exists())
        self.assertTrue(keep_file.exists())

    def test_category7_fail_closed_concurrency_llm_and_enrolled_ordering(self):
        # 1. Closed work (is_oa: false) -> untouched Hyades reply + X-Firecrawl-OA-Fallback: skipped:not-oa
        closed_work = {"id": "https://openalex.org/W1", "open_access": {"is_oa": False, "oa_status": "closed"}, "locations": []}
        inst_closed, _ = self._make_oa(lambda rec: (200, {"Content-Type": "application/json"}, json.dumps(closed_work).encode()))
        first = self._blocked_primary_reply(403)
        router, fake_call, _ = self._router(first, oa_inst=inst_closed)
        with unittest.mock.patch.object(fr, "call", side_effect=fake_call):
            r, b = router.handle("POST", "/v2/scrape", {"Content-Type": "application/json"},
                                 json.dumps({"url": "https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.134.023803"}).encode())
        self.assertEqual((r.status, b, r.headers.get("X-Firecrawl-OA-Fallback")), (200, "primary", "skipped:not-oa"))
        self.assertEqual(r.body, first.body)

        # 2. OpenAlex 404, 429 (RPS retry + daily_budget), 500 circuit breaker
        inst_404, _ = self._make_oa(lambda rec: (404, {}, b"{}"))
        self.assertEqual(
            inst_404.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://doi.org/10.1145/1.2"}).encode(), first, "403", fr.Reply),
            (None, None, "not-found"),
        )

        rps_calls = {"n": 0}
        def resp_rps(rec):
            if rec["host"] == "api.openalex.org":
                rps_calls["n"] += 1
                if rps_calls["n"] == 1:
                    return (429, {"Retry-After": "1"}, b'{"reason":"requests_per_second"}')
                return (200, {"Content-Type": "application/json"}, json.dumps(_acm_sosp_work()).encode())
            return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
        inst_rps, _ = self._make_oa(resp_rps)
        r_rps, b_rps, _ = inst_rps.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://dl.acm.org/doi/10.1145/3600006.3613165"}).encode(), first, "403", fr.Reply)
        self.assertEqual((r_rps.status, b_rps, rps_calls["n"]), (200, "oa-fallback", 2))

        # 500 triggers 30s circuit breaker so 2nd call skips without hitting network
        calls_500 = {"n": 0}
        def resp_500(rec):
            calls_500["n"] += 1
            return (500, {}, b"err")
        inst_500, _ = self._make_oa(resp_500)
        self.assertEqual(inst_500.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://doi.org/10.1145/1.2"}).encode(), first, "403", fr.Reply)[2], "openalex-500")
        self.assertEqual(inst_500.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://doi.org/10.1145/1.2"}).encode(), first, "403", fr.Reply)[2], "openalex-circuit")
        self.assertEqual(calls_500["n"], 1)

        # Credit-unit header (50 credits = $0.005 < $0.01) disables billable content.openalex.org while $0 singleton still works
        inst_cred, _ = self._make_oa(lambda rec: (200, {"X-RateLimit-Remaining": "50"}, json.dumps(_acm_sosp_work()).encode()), content_api=True)
        work_ok, err_ok = inst_cred.client.lookup_work("doi", "10.1145/3600006.3613165", time.monotonic() + 10)
        self.assertIsNotNone(work_ok)
        self.assertEqual(err_ok, "")
        self.assertFalse(inst_cred.client.can_spend_billable(0.01))

        # 3. Saturated oa_sem returns skipped:busy
        inst_busy, _ = self._make_oa(lambda rec: (200, {}, b"{}"), max_concurrent=1, sem_timeout=0.05)
        self.assertTrue(inst_busy.oa_sem.acquire(blocking=False))
        try:
            self.assertEqual(
                inst_busy.maybe_fallback("POST", "/v2/scrape", json.dumps({"url": "https://doi.org/10.1145/1.2"}).encode(), first, "403", fr.Reply),
                (None, None, "busy"),
            )
        finally:
            inst_busy.oa_sem.release()

        # 4. formats: ["query"] on oa-fallback runs Extractor AND preserves mandatory data.warning
        def resp_acm(rec):
            if rec["host"] == "api.openalex.org":
                return (200, {"Content-Type": "application/json"}, json.dumps(_acm_sosp_work()).encode())
            return (200, {"Content-Type": "application/pdf"}, _valid_pdf_bytes())
        inst_llm, _ = self._make_oa(resp_acm)
        ex = fr.Extractor([fr.Rung("sipb", "http://127.0.0.1:9", "k", "m", 10_000, 5_000)], deadline=10, call_timeout=5)
        router_llm, fake_call_llm, _ = self._router(first, oa_inst=inst_llm, extractor=ex)
        with unittest.mock.patch.object(fr, "call", side_effect=fake_call_llm), \
             unittest.mock.patch.object(ex, "run", return_value=({"answer": "PagedAttention uses virtual memory."}, "sipb", "")):
            r_q, b_q = router_llm.handle(
                "POST", "/v2/scrape", {"Content-Type": "application/json"},
                json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165",
                            "formats": [{"type": "query", "prompt": "What does PagedAttention use?"}]}).encode(),
            )
        self.assertEqual((r_q.status, b_q), (200, "oa-fallback"))
        q_doc = r_q.json()
        self.assertEqual(q_doc["data"]["answer"], "PagedAttention uses virtual memory.")
        self.assertIn("submittedVersion", q_doc["data"]["warning"])
        self.assertIn("content may differ from the Version of Record", q_doc["data"]["warning"])

        # 5. Enrolled host ordering: mit-bridge fails closed -> OA rescues when allow_enrolled=True;
        #    if OA also fails, NEVER hits commercial fallback!
        class _FailMitBridge:
            enabled = True
            log = io.StringIO()
            _reply_cls = fr.Reply
            def maybe_bridge(self, method, path, body, primary_reply, reason, rcls):
                return None, None, "browser-botwall", True

        fb_reply = fr.Reply(200, {"Content-Type": "application/json"}, b'{"success":true,"data":{"markdown":"commercial"}}')
        inst_enr_ok, _ = self._make_oa(resp_acm, allow_enrolled=True)
        r_e1, fc_e1, seen_e1 = self._router(first, oa_inst=inst_enr_ok, fallback_reply=fb_reply, mit_bridge=_FailMitBridge())
        with unittest.mock.patch.object(fr, "call", side_effect=fc_e1):
            rep1, back1 = r_e1.handle("POST", "/v2/scrape", {"Content-Type": "application/json"},
                                      json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode())
        self.assertEqual((rep1.status, back1), (200, "oa-fallback"))
        self.assertEqual(seen_e1, ["primary"])  # never hit commercial fallback

        # Enrolled host where BOTH mit-bridge and OA fail -> still never hits commercial fallback
        inst_enr_fail, _ = self._make_oa(lambda rec: (404, {}, b"{}"), allow_enrolled=True)
        r_e2, fc_e2, seen_e2 = self._router(first, oa_inst=inst_enr_fail, fallback_reply=fb_reply, mit_bridge=_FailMitBridge())
        with unittest.mock.patch.object(fr, "call", side_effect=fc_e2):
            rep2, back2 = r_e2.handle("POST", "/v2/scrape", {"Content-Type": "application/json"},
                                      json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode())
        self.assertEqual((rep2.status, back2), (200, "primary"))
        self.assertEqual(rep2.headers.get("X-Firecrawl-MIT-Bridge"), "skipped:browser-botwall")
        self.assertEqual(rep2.headers.get("X-Firecrawl-OA-Fallback"), "skipped:not-found")
        self.assertEqual(seen_e2, ["primary"])  # commercial fallback NEVER called!

        # Enrolled host with FIRECRAWL_ROUTER_OA_ENROLLED=off -> skips OA without calling OpenAlex, never hits commercial
        inst_enr_off, f_off = self._make_oa(lambda rec: self.fail("should not call OpenAlex"), allow_enrolled=False)
        r_e3, fc_e3, seen_e3 = self._router(first, oa_inst=inst_enr_off, fallback_reply=fb_reply, mit_bridge=_FailMitBridge())
        with unittest.mock.patch.object(fr, "call", side_effect=fc_e3):
            rep3, back3 = r_e3.handle("POST", "/v2/scrape", {"Content-Type": "application/json"},
                                      json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode())
        self.assertEqual((rep3.status, back3), (200, "primary"))
        self.assertEqual(rep3.headers.get("X-Firecrawl-OA-Fallback"), "skipped:enrolled-disabled")
        self.assertEqual(f_off.calls, [])
        self.assertEqual(seen_e3, ["primary"])

    def test_cli_smoke_loads_both_siblings_under_E_s_and_I(self):
        probe = (
            "import importlib.machinery, importlib.util, sys; "
            f"loader = importlib.machinery.SourceFileLoader('fr', {str(ROOT / 'bin' / 'firecrawl-router')!r}); "
            "spec = importlib.util.spec_from_loader('fr', loader); "
            "mod = importlib.util.module_from_spec(spec); "
            "sys.modules['fr'] = mod; "
            "loader.exec_module(mod); "
            "assert mod._MIT_BRIDGE_MOD is not None, 'mit bridge missing'; "
            "assert mod._OA_FALLBACK_MOD is not None, 'oa fallback missing'; "
            "print('OK')"
        )
        for flags in (["-E", "-s"], ["-I"]):
            with self.subTest(mode="import", flags=flags):
                r = subprocess.run(
                    [sys.executable, *flags, "-c", probe],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), "OK")
            with self.subTest(mode="cli", flags=flags):
                r2 = subprocess.run(
                    [sys.executable, *flags, str(ROOT / "bin" / "firecrawl-router"), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(r2.returncode, 0, r2.stderr)
                self.assertIn("firecrawl-router", r2.stdout)


if __name__ == "__main__":
    unittest.main()
