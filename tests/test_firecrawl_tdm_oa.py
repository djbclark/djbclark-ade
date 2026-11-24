"""Unit tests for CORE v3 + Springer Nature Free OA (firecrawl_oa_fallback.py)
and opt-in Wiley TDM PDF API lane (firecrawl_wiley_tdm.py + firecrawl-router)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

REPO = Path(__file__).resolve().parent.parent


def _load_script(name: str, relpath: str):
    path = REPO / relpath
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


fr = _load_script("firecrawl_router_tdm_test", "bin/firecrawl-router")
oa = fr._OA_FALLBACK_MOD
wt = fr._WILEY_TDM_MOD


def _write_exec(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nstream\nhello wiley\nendstream\n%%EOF\n"


class _FakeHTTPResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self._headers = list(headers.items())
        self._hdr_map = {k.lower(): v for k, v in headers.items()}
        self._buf = io.BytesIO(body)

    def getheaders(self):
        return self._headers

    def getheader(self, name: str, default=None):
        return self._hdr_map.get(name.lower(), default)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


class _ScriptedConnFactory:
    """In-memory HTTPSConnection replacement recording all requests and headers."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, host, port=443, **kwargs):
        factory = self

        class _Conn:
            def __init__(self):
                self._resp = None
                self.sock = None

            def request(self, method, target, headers=None):
                rec = {
                    "host": host,
                    "port": port,
                    "method": method,
                    "target": target,
                    "headers": dict(headers or {}),
                    "kwargs": dict(kwargs),
                }
                factory.calls.append(rec)
                status, rhdrs, body = factory.handler(rec)
                self._resp = _FakeHTTPResponse(status, rhdrs, body)

            def getresponse(self):
                return self._resp

            def close(self):
                pass

        return _Conn()


class TestSpringerAndCoreOA(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.state_dir = self.root / "oa-state"
        self.fake_pandoc = _write_exec(
            self.root / "pandoc",
            f"#!{sys.executable}\nimport sys\ndata = sys.stdin.read()\nif '<article' not in data:\n    sys.exit(1)\nprint('# Converted JATS Body\\n\\nClean paper text from Springer Nature OA API.')\n",
        )
        self.fake_pdftotext = _write_exec(
            self.root / "pdftotext",
            f"#!{sys.executable}\nprint('Extracted PDF markdown text from repository copy.')\n",
        )
        self.fake_pdfinfo = _write_exec(
            self.root / "pdfinfo",
            f"#!{sys.executable}\nprint('Pages: 12\\nTitle: Fake PDF Paper')\n",
        )
        self.fake_secretspec = _write_exec(
            self.root / "sudo-secretspec",
            f"""#!{sys.executable}
import sys
name = sys.argv[2]
keys = {{
    "CORE_API_KEY": "core-secret-test-key-123456",
    "SPRINGER_NATURE_API_KEY": "springer-secret-key-987654",
}}
if name in keys:
    print(keys[name])
    sys.exit(0)
sys.exit(1)
""",
        )

    def tearDown(self):
        self.td.cleanup()

    def _make_oa(self, factory, *, version_policy="all", core_mode="auto", springer_mode="auto", secretspec=None):
        cfg = oa.OaFallbackConfig(
            mode="allowlist",
            version_policy=version_policy,
            content_api=False,
            core_mode=core_mode,
            springer_mode=springer_mode,
            secretspec_bin=str(secretspec if secretspec is not None else self.fake_secretspec),
            state_dir=str(self.state_dir),
            pdftotext_bin=str(self.fake_pdftotext),
            pdfinfo_bin=str(self.fake_pdfinfo),
            pandoc_bin=str(self.fake_pandoc),
        )
        return oa.OaFallback(
            cfg,
            log=io.StringIO(),
            reply_cls=fr.Reply,
            conn_factory=factory,
            resolver=lambda host, port=443: "93.184.216.34",
            sleep_fn=lambda _s: None,
        )

    def test_extract_jats_article_rejects_entity_and_doi_mismatch(self):
        good = (
            b'<?xml version="1.0"?><response><records>'
            b'<article><front><article-meta>'
            b'<article-id pub-id-type="doi">10.1038/s41586-020-2649-2</article-id>'
            b'<title-group><article-title>Nature <i>OA</i> Title</article-title></title-group>'
            b'</article-meta></front><body><p>Body</p></body></article>'
            b'</records></response>'
        )
        art, title, err = oa.extract_jats_article(good, "10.1038/s41586-020-2649-2")
        self.assertEqual(err, "")
        self.assertIsNotNone(art)
        self.assertEqual(title, "Nature OA Title")

        # XXE / entity expansion rejected
        evil = b'<!DOCTYPE foo [<!ENTITY xxe "boom">]>' + good
        art2, _, err2 = oa.extract_jats_article(evil, "10.1038/s41586-020-2649-2")
        self.assertIsNone(art2)
        self.assertEqual(err2, "springer-unsafe-xml")

        # Wrong DOI rejected
        art3, _, err3 = oa.extract_jats_article(good, "10.1038/s41586-099-9999-9")
        self.assertIsNone(art3)
        self.assertEqual(err3, "springer-doi-mismatch")

        # B1: <!DOCTYPE without <!ENTITY rejected; NUL bytes rejected; malformed XML rejected
        doc_type = b'<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "jats.dtd">' + good
        self.assertEqual(oa.extract_jats_article(doc_type, "10.1038/s41586-020-2649-2")[2], "springer-unsafe-xml")
        self.assertEqual(oa.extract_jats_article(good + b"\x00", "10.1038/s41586-020-2649-2")[2], "springer-unsafe-xml")
        self.assertEqual(oa.extract_jats_article(b"<article><unclosed>", "10.1038/s41586-020-2649-2")[2], "springer-bad-xml")

        # B1: DOI inside XML comment or outside <front><article-meta> cannot spoof verification
        spoofed = (
            b'<article><!-- <article-id pub-id-type="doi">10.1038/s41586-020-2649-2</article-id> -->'
            b'<front><article-meta></article-meta></front>'
            b'<back><related-article><article-id pub-id-type="doi">10.1038/s41586-020-2649-2</article-id></related-article></back></article>'
        )
        self.assertEqual(oa.extract_jats_article(spoofed, "10.1038/s41586-020-2649-2")[2], "springer-doi-missing")

        # B1: attribute ordering before pub-id-type="doi" accepted
        reordered = (
            b'<article><front><article-meta>'
            b'<article-id id="d1" pub-id-type="doi">10.1038/s41586-020-2649-2</article-id>'
            b'</article-meta></front><body><p>ok</p></body></article>'
        )
        self.assertEqual(oa.extract_jats_article(reordered, "10.1038/s41586-020-2649-2")[2], "")

    def test_springer_no_redirect_401_disable_circuit_breakers_and_priority_before_paid_content_api(self):
        # 302 redirect on api.springernature.com refused (single hop; ?api_key= never leaves host)
        factory_302 = _ScriptedConnFactory(lambda rec: (302, {"Location": "https://evil.example/leak"}, b""))
        fb_302 = self._make_oa(factory_302)
        art, _, err = fb_302.springer_client.fetch_jats("10.1038/s41586-020-2649-2", time.monotonic() + 10.0)
        self.assertIsNone(art)
        self.assertEqual(err, "springer-http-302")
        self.assertEqual(len(factory_302.calls), 1)

        # 401 disables springer_key_state
        fb_401 = self._make_oa(_ScriptedConnFactory(lambda rec: (401, {}, b"unauth")))
        fb_401.springer_client.fetch_jats("10.1038/s41586-020-2649-2", time.monotonic() + 10.0)
        self.assertIsNone(fb_401.springer_key_state.get())

        # B2: 429, fetch-error (OSError), and fetch-timeout (TimeoutError) trip circuit breaker
        for exc_or_status in (429, OSError("conn reset"), TimeoutError("timed out")):
            def _make_handler(val):
                def _h(rec):
                    if isinstance(val, Exception):
                        raise val
                    return val, {}, b""
                return _h
            fb_cb = self._make_oa(_ScriptedConnFactory(_make_handler(exc_or_status)))
            fb_cb.springer_client.fetch_jats("10.1038/s41586-020-2649-2", time.monotonic() + 10.0)
            self.assertTrue(fb_cb.springer_client._circuit_open(), f"expected circuit open for {exc_or_status!r}")

        # Springer OA runs BEFORE $0.01 content.openalex.org
        jats_xml = (
            b'<article><front><article-meta>'
            b'<article-id pub-id-type="doi">10.1038/s41586-020-2649-2</article-id>'
            b'</article-meta></front><body><p>Free VoR JATS</p></body></article>'
        )
        def handler_prio(rec):
            if rec["host"] == "api.openalex.org":
                return 200, {"Content-Type": "application/json"}, json.dumps({
                    "id": "https://openalex.org/W4387321091",
                    "doi": "https://doi.org/10.1038/s41586-020-2649-2",
                    "open_access": {"is_oa": True, "oa_status": "gold"},
                    "has_content": {"pdf": True},
                    "content_urls": {"pdf": "https://content.openalex.org/works/W4387321091.pdf"},
                    "locations": [],
                }).encode()
            if rec["host"] == "api.springernature.com":
                return 200, {"Content-Type": "application/xml"}, jats_xml
            raise AssertionError(f"should not call paid host {rec['host']}")

        factory_prio = _ScriptedConnFactory(handler_prio)
        fb_prio = self._make_oa(factory_prio)
        fb_prio.config.content_api = True
        primary = fr.Reply(403, {}, b"blocked")
        body = json.dumps({"url": "https://www.nature.com/articles/s41586-020-2649-2"}).encode()
        reply, backend, _ = fb_prio.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertEqual(backend, "oa-fallback")
        self.assertEqual(reply.headers.get("X-Firecrawl-OA-Source"), "springer-oa")
        self.assertFalse(any(c["host"] == "content.openalex.org" for c in factory_prio.calls))

    def test_core_doi_mismatch_circuit_breakers_and_path_a_allowlist(self):
        # CORE DOI mismatch rejected
        fb_mm = self._make_oa(_ScriptedConnFactory(lambda rec: (
            200, {}, json.dumps({"results": [{"id": 1, "doi": "10.1145/9999999.9999999", "fullText": "X" * 600}]}).encode()
        )))
        item, err = fb_mm.core_client.lookup_doi("10.1145/3600006.3613165", time.monotonic() + 10.0)
        self.assertIsNone(item)
        self.assertEqual(err, "core-doi-mismatch")

        # B2: CORE 429, fetch-error (OSError), and fetch-timeout (TimeoutError) trip circuit breaker
        for exc_or_status in (429, OSError("conn reset"), TimeoutError("timed out")):
            def _make_handler(val):
                def _h(rec):
                    if isinstance(val, Exception):
                        raise val
                    return val, {}, b""
                return _h
            fb_cb = self._make_oa(_ScriptedConnFactory(_make_handler(exc_or_status)))
            fb_cb.core_client.lookup_doi("10.1145/3600006.3613165", time.monotonic() + 10.0)
            self.assertTrue(fb_cb.core_client._circuit_open(), f"expected CORE circuit open for {exc_or_status!r}")

        # B3: CORE Path A skips untrusted/core/content.openalex/http/non-443/publisher URLs without starving trusted arxiv PDF
        def handler_path_a(rec):
            if rec["host"] == "api.openalex.org":
                return 404, {}, b"{}"
            if rec["host"] == "api.core.ac.uk":
                return 200, {"Content-Type": "application/json"}, json.dumps({
                    "results": [{
                        "id": 777,
                        "doi": "10.1145/3600006.3613165",
                        "title": "CORE Path A Paper",
                        "license": "cc-by",
                        "sourceFulltextUrls": [
                            "https://evil.example/paper.pdf",
                            "https://untrusted2.example/paper.pdf",
                            "https://download.core.ac.uk/777.pdf",
                            "https://content.openalex.org/works/W123.pdf",
                            "http://arxiv.org/pdf/2309.06180.pdf",
                            "https://arxiv.org:8443/pdf/2309.06180.pdf",
                            "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165",
                            "https://arxiv.org/pdf/2309.06180.pdf?download=1",
                        ],
                        "fullText": "Not available for public API users.",
                    }],
                }).encode()
            if rec["host"] == "arxiv.org":
                return 200, {"Content-Type": "application/pdf"}, _fake_pdf_bytes()
            raise AssertionError(f"unexpected host {rec['host']}")

        factory_a = _ScriptedConnFactory(handler_path_a)
        fb_a = self._make_oa(factory_a)
        primary = fr.Reply(403, {}, b"blocked")
        body = json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode()
        reply, backend, note = fb_a.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertEqual(backend, "oa-fallback")
        self.assertEqual(reply.status, 200)
        self.assertIn("core-arxiv", note)
        fetched_hosts = [c["host"] for c in factory_a.calls]
        self.assertEqual(fetched_hosts, ["api.openalex.org", "api.core.ac.uk", "arxiv.org"])

    def test_springer_oa_rescues_when_openalex_closed_and_redacts_api_key(self):
        jats_xml = (
            b'<?xml version="1.0"?><response><records>'
            b'<article><front><article-meta>'
            b'<article-id pub-id-type="doi">10.1038/s41586-020-2649-2</article-id>'
            b'<title-group><article-title>AlphaFold OA Study</article-title></title-group>'
            b'</article-meta></front><body><p>Hello JATS</p></body></article>'
            b'</records></response>'
        )

        def handler(rec):
            if rec["host"] == "api.openalex.org":
                return 200, {"Content-Type": "application/json"}, json.dumps({
                    "id": "https://openalex.org/W12345",
                    "doi": "https://doi.org/10.1038/s41586-020-2649-2",
                    "open_access": {"is_oa": False, "oa_status": "closed"},
                    "locations": [],
                }).encode()
            if rec["host"] == "api.springernature.com":
                self.assertIn("api_key=springer-secret-key-987654", rec["target"])
                return 200, {"Content-Type": "application/xml"}, jats_xml
            raise AssertionError(f"unexpected host {rec['host']}")

        factory = _ScriptedConnFactory(handler)
        fb = self._make_oa(factory)
        primary = fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")
        body = json.dumps({"url": "https://www.nature.com/articles/s41586-020-2649-2"}).encode()
        reply, backend, note = fb.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)

        self.assertEqual(backend, "oa-fallback")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers.get("X-Firecrawl-OA-Source"), "springer-oa")
        self.assertIn("springer-oa", note)
        raw_reply = reply.body.decode("utf-8")
        # CRITICAL: api_key must NEVER appear anywhere in response body or headers
        self.assertNotIn("springer-secret-key-987654", raw_reply)
        self.assertNotIn("api_key", raw_reply)
        doc = json.loads(raw_reply)
        self.assertEqual(doc["data"]["metadata"]["oaSource"], "Springer Nature Open Access API")
        self.assertEqual(doc["data"]["metadata"]["title"], "AlphaFold OA Study")
        self.assertIn("Springer Nature Open Access API", doc["data"]["warning"])

    def test_core_oa_inline_fulltext_rescues_when_openalex_404(self):
        long_text = "A" * 500 + " Deep reinforcement learning open access text from institutional repository."

        def handler(rec):
            if rec["host"] == "api.openalex.org":
                return 404, {"Content-Type": "application/json"}, b'{"error":"not found"}'
            if rec["host"] == "api.core.ac.uk":
                self.assertEqual(rec["headers"].get("Authorization"), "Bearer core-secret-test-key-123456")
                self.assertTrue(rec["target"].startswith("/v3/search/works/?"))
                return 200, {"Content-Type": "application/json", "X-RateLimit-Remaining": "9"}, json.dumps({
                    "totalHits": 1,
                    "results": [{
                        "id": 987654321,
                        "doi": "10.1145/3600006.3613165",
                        "title": "PagedAttention CORE Copy",
                        "license": "cc-by",
                        "sourceFulltextUrls": ["https://core.ac.uk/download/987654321.pdf"],
                        "fullText": long_text,
                    }],
                }).encode()
            raise AssertionError(f"unexpected host {rec['host']}")

        factory = _ScriptedConnFactory(handler)
        fb = self._make_oa(factory)
        primary = fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")
        body = json.dumps({"url": "https://dl.acm.org/doi/pdf/10.1145/3600006.3613165"}).encode()
        reply, backend, note = fb.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)

        self.assertEqual(backend, "oa-fallback")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers.get("X-Firecrawl-OA-Source"), "core")
        self.assertIn("core", note)
        raw_reply = reply.body.decode("utf-8")
        self.assertNotIn("core-secret-test-key-123456", raw_reply)
        doc = json.loads(raw_reply)
        self.assertEqual(doc["data"]["metadata"]["url"], "https://core.ac.uk/works/987654321")
        self.assertEqual(doc["data"]["metadata"]["oaVersion"], "unknown")
        self.assertIn("may differ from the Version of Record", doc["data"]["warning"])

    def test_core_rejects_public_stub_doi_mismatch_and_peer_reviewed_policy(self):
        def handler_stub(rec):
            if rec["host"] == "api.openalex.org":
                return 404, {}, b"{}"
            return 200, {}, json.dumps({
                "results": [{
                    "id": 123,
                    "doi": "10.1145/3600006.3613165",
                    "fullText": "Not available for public API users.",
                }]
            }).encode()

        fb = self._make_oa(_ScriptedConnFactory(handler_stub))
        primary = fr.Reply(403, {}, b"blocked")
        body = json.dumps({"url": "https://dl.acm.org/doi/10.1145/3600006.3613165"}).encode()
        r1, b1, _ = fb.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r1)
        self.assertIsNone(b1)

        # peer-reviewed policy skips CORE completely (zero CORE API calls)
        factory_pr = _ScriptedConnFactory(handler_stub)
        fb_pr = self._make_oa(factory_pr, version_policy="peer-reviewed")
        r2, b2, _ = fb_pr.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r2)
        self.assertIsNone(b2)
        self.assertFalse(any(c["host"] == "api.core.ac.uk" for c in factory_pr.calls))

    def test_core_auto_mode_makes_no_calls_when_key_missing(self):
        factory = _ScriptedConnFactory(lambda rec: (404, {}, b"{}"))
        fb = self._make_oa(factory, secretspec="")
        primary = fr.Reply(403, {}, b"blocked")
        body = json.dumps({"url": "https://dl.acm.org/doi/10.1145/3600006.3613165"}).encode()
        fb.maybe_fallback("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        hosts = [c["host"] for c in factory.calls]
        self.assertEqual(hosts, ["api.openalex.org"])

    def test_build_oa_fallback_invalid_provider_modes_fail_closed(self):
        log = io.StringIO()
        fb = oa.build_oa_fallback({
            "FIRECRAWL_ROUTER_OA_FALLBACK": "allowlist",
            "FIRECRAWL_ROUTER_OA_CORE": "bogus",
            "FIRECRAWL_ROUTER_OA_SPRINGER": "bogus",
            "FIRECRAWL_ROUTER_OA_SECRETSPEC_BIN": "",
            "FIRECRAWL_ROUTER_OA_STATE_DIR": str(self.state_dir),
        }, log=log)
        self.assertEqual(fb.config.core_mode, "off")
        self.assertEqual(fb.config.springer_mode, "off")


class TestWileyTdm(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.state_dir = self.root / "wiley-state"
        self.token = "12345678-1234-4123-8123-123456789abc"
        self.fake_pdftotext = _write_exec(
            self.root / "pdftotext",
            f"#!{sys.executable}\nprint('Wiley TDM extracted PDF text content.')\n",
        )
        self.fake_pdfinfo = _write_exec(
            self.root / "pdfinfo",
            f"#!{sys.executable}\nprint('Pages: 8\\nTitle: Angewandte Chemie Paper')\n",
        )
        self.fake_secretspec = _write_exec(
            self.root / "sudo-secretspec",
            f"#!{sys.executable}\nimport sys\nif sys.argv[2] == 'WILEY_TDM_TOKEN':\n    print('{self.token}')\n    sys.exit(0)\nsys.exit(1)\n",
        )

    def tearDown(self):
        self.td.cleanup()

    def _make_wiley(self, socks_factory, direct_factory=None, *, mode="on", allow_cloud_llm=False, clock=None):
        cfg = wt.WileyTdmConfig(
            mode=mode,
            secretspec_bin=str(self.fake_secretspec),
            socks_host="127.0.0.1",
            socks_port=18830,
            state_dir=str(self.state_dir),
            min_spacing_s=10.0,
            max_per_10min=60,
            allow_cloud_llm=allow_cloud_llm,
            pdftotext_bin=str(self.fake_pdftotext),
            pdfinfo_bin=str(self.fake_pdfinfo),
        )
        return wt.WileyTdm(
            cfg,
            log=io.StringIO(),
            reply_cls=fr.Reply,
            socks_conn_factory=socks_factory,
            direct_conn_factory=direct_factory or socks_factory,
            resolver=lambda host, port=443: "52.73.125.33",
            clock=clock or time.monotonic,
        )

    def test_wiley_target_scoping(self):
        self.assertTrue(wt.is_wiley_target("onlinelibrary.wiley.com", "10.1002/anie.4701250"))
        self.assertTrue(wt.is_wiley_target("asme.onlinelibrary.wiley.com", "10.1002/jomd.70010"))
        self.assertTrue(wt.is_wiley_target("doi.org", "10.1111/jtsb.12390"))
        self.assertFalse(wt.is_wiley_target("doi.org", "10.1038/s41586-020-2649-2"))
        self.assertFalse(wt.is_wiley_target("pubs.acs.org", "10.1021/jacs.6c12304"))
        self.assertFalse(wt.is_wiley_target("evilwiley.com", "10.1002/anie.4701250"))

    def test_wiley_build_refuses_non_loopback_socks_and_unknown_mode(self):
        log = io.StringIO()
        self.assertIsNone(wt.build_wiley_tdm({
            "FIRECRAWL_ROUTER_WILEY_TDM": "on",
            "FIRECRAWL_ROUTER_WILEY_SOCKS_HOST": "192.168.1.5",
        }, log=log))
        self.assertIsNone(wt.build_wiley_tdm({
            "FIRECRAWL_ROUTER_WILEY_TDM": "bogus",
        }, log=log))

    def test_wiley_socks5_handshake_remote_dns(self):
        """Verify RFC 1928 ATYP=0x03 domain handshake on a real local socket pair."""
        received = {}
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def server():
            conn, _ = srv.accept()
            try:
                greet = conn.recv(3)
                received["greet"] = greet
                conn.sendall(b"\x05\x00")
                hdr = conn.recv(4)
                received["hdr"] = hdr
                dlen = conn.recv(1)[0]
                dhost = conn.recv(dlen)
                dport = struct.unpack("!H", conn.recv(2))[0]
                received["dest"] = (dhost.decode("ascii"), dport)
                conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                received["payload"] = conn.recv(4)
            finally:
                conn.close()
                srv.close()

        t = threading.Thread(target=server, daemon=True)
        t.start()
        sock = wt.socks5_connect("127.0.0.1", port, "api.wiley.com", 443, 5.0)
        try:
            sock.sendall(b"PING")
        finally:
            sock.close()
        t.join(timeout=5.0)
        self.assertEqual(received["greet"], b"\x05\x01\x00")
        self.assertEqual(received["hdr"], b"\x05\x01\x00\x03")
        self.assertEqual(received["dest"], ("api.wiley.com", 443))
        self.assertEqual(received["payload"], b"PING")

        with self.assertRaises(ValueError):
            wt.socks5_connect("10.0.0.1", port, "api.wiley.com", 443, 1.0)

    def test_wiley_redirect_strips_token_and_rate_limits_second_call(self):
        socks_factory = _ScriptedConnFactory(lambda rec: (
            302,
            {"Location": "https://s3.amazonaws.com/wiley-bucket/paper.pdf?sig=abc"},
            b"",
        ))
        direct_factory = _ScriptedConnFactory(lambda rec: (
            200,
            {"Content-Type": "application/pdf"},
            _fake_pdf_bytes(),
        ))
        now = [1000.0]
        w = self._make_wiley(socks_factory, direct_factory, clock=lambda: now[0])
        primary = fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")
        body = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()

        reply, backend, note = w.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertEqual(backend, "wiley-tdm")
        self.assertEqual(reply.status, 200)
        self.assertIn("wiley-tdm", note)
        # Token sent ONLY on initial api.wiley.com SOCKS call, NEVER on redirect!
        self.assertEqual(len(socks_factory.calls), 1)
        self.assertEqual(socks_factory.calls[0]["headers"].get("Wiley-TDM-Client-Token"), self.token)
        self.assertEqual(len(direct_factory.calls), 1)
        self.assertNotIn("Wiley-TDM-Client-Token", direct_factory.calls[0]["headers"])
        # Token never appears in reply body
        self.assertNotIn(self.token, reply.body.decode("utf-8"))
        # Zero leftover run-* dirs
        self.assertEqual(list(self.state_dir.glob("run-*")), [])

        # Immediate second request (<10s spacing) fails closed as rate-limited
        now[0] += 2.0
        r2, b2, n2 = w.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r2)
        self.assertIsNone(b2)
        self.assertEqual(n2, "rate-limited")

    def test_router_blocks_cloud_llm_extraction_on_wiley_tdm_by_default(self):
        socks_factory = _ScriptedConnFactory(lambda rec: (
            200,
            {"Content-Type": "application/pdf"},
            _fake_pdf_bytes(),
        ))
        w = self._make_wiley(socks_factory, allow_cloud_llm=False)

        class _BoomExtractor:
            log = io.StringIO()
            def run(self, wants, md):
                raise AssertionError("Extractor MUST NOT be called for wiley-tdm when allow_cloud_llm is False")

        primary_backend = fr.Backend("primary", "http://127.0.0.1:1", "")
        router = fr.Router(primary_backend, None, 30.0, log=io.StringIO(), extractor=_BoomExtractor(), wiley_tdm=w)
        with unittest.mock.patch.object(fr, "call", return_value=fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")):
            req = json.dumps({
                "url": "https://onlinelibrary.wiley.com/doi/10.1002/anie.4701250",
                "formats": [{"type": "query", "prompt": "Summarize"}],
            }).encode()
            reply, backend = router.handle("POST", "/v2/scrape", {}, req)

        self.assertEqual(backend, "wiley-tdm")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers.get("X-Firecrawl-LLM"), "blocked-policy")
        doc = json.loads(reply.body.decode("utf-8"))
        self.assertIn("Wiley TDM extracted PDF text", doc["data"]["markdown"])
        self.assertIn("External LLM extraction (query/json) is disabled for wiley-tdm", doc["data"]["warning"])

    def test_missing_wiley_module_logs_warning_and_fails_closed(self):
        err = io.StringIO()
        with unittest.mock.patch.object(fr, "_WILEY_TDM_MOD", None), unittest.mock.patch.object(sys, "stderr", err):
            r = fr.build_router({
                "FIRECRAWL_SELFHOST_URL": "http://127.0.0.1:18805",
                "FIRECRAWL_ROUTER_WILEY_TDM": "on",
            }, "")
        self.assertIsNone(r.wiley_tdm)
        self.assertIn("firecrawl_wiley_tdm.py is missing", err.getvalue())

    def test_wiley_auto_mode_silent_without_token_and_401_disables_key(self):
        missing_ss = _write_exec(self.root / "missing-ss", f"#!{sys.executable}\nimport sys\nsys.exit(1)\n")
        cfg = wt.WileyTdmConfig(
            mode="auto",
            secretspec_bin=str(missing_ss),
            state_dir=str(self.state_dir),
            pdftotext_bin=str(self.fake_pdftotext),
        )
        w_auto = wt.WileyTdm(cfg, log=io.StringIO(), reply_cls=fr.Reply)
        primary = fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")
        body = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()
        r, b, note = w_auto.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r)
        self.assertIsNone(b)
        self.assertEqual(note, "")

        # 401 disables key_state for 600s so subsequent calls fail fast without hammering api.wiley.com
        factory_401 = _ScriptedConnFactory(lambda rec: (401, {}, b"unauthorized"))
        w401 = self._make_wiley(factory_401)
        r1, b1, n1 = w401.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r1)
        self.assertEqual(n1, "unauthorized")
        self.assertIsNone(w401.key_state.get())

    def test_wiley_same_host_redirect_offsite_401_ssrf_and_pdf_validation(self):
        primary = fr.Reply(403, {"Content-Type": "text/html"}, b"Just a moment...")
        body = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()

        # Same-host api.wiley.com redirect strips token and stays on SOCKS5
        step = [0]
        def same_host_h(rec):
            step[0] += 1
            if step[0] == 1:
                return 302, {"Location": "https://api.wiley.com/onlinelibrary/tdm/v1/stream/1"}, b""
            return 200, {"Content-Type": "application/pdf"}, _fake_pdf_bytes()
        sf = _ScriptedConnFactory(same_host_h)
        w_same = self._make_wiley(sf)
        r, b, _ = w_same.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertEqual(b, "wiley-tdm")
        self.assertEqual(len(sf.calls), 2)
        self.assertEqual(sf.calls[0]["headers"].get("Wiley-TDM-Client-Token"), self.token)
        self.assertNotIn("Wiley-TDM-Client-Token", sf.calls[1]["headers"])

        # S2: Off-site 401 does NOT disable valid token
        sf_401 = _ScriptedConnFactory(lambda rec: (302, {"Location": "https://s3.amazonaws.com/b/p.pdf"}, b""))
        df_401 = _ScriptedConnFactory(lambda rec: (401, {}, b"expired presign"))
        w_off401 = self._make_wiley(sf_401, df_401)
        r2, _, n2 = w_off401.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
        self.assertIsNone(r2)
        self.assertEqual(n2, "redirect-unauthorized")
        self.assertEqual(w_off401.key_state.get(), self.token)

        # S2: Off-site redirect trying to re-enter api.wiley.com fails closed
        sf_back = _ScriptedConnFactory(lambda rec: (302, {"Location": "https://s3.amazonaws.com/b/p.pdf"}, b""))
        df_back = _ScriptedConnFactory(lambda rec: (302, {"Location": "https://api.wiley.com/internal"}, b""))
        w_back = self._make_wiley(sf_back, df_back)
        self.assertEqual(w_back.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], "redirect-back-to-api")

        # Scheme downgrade, non-443 port, private IP SSRF, redirect loop, bad PDF magic / missing EOF / wrong CT
        for loc, expected_err, resolver in [
            ("http://s3.amazonaws.com/p.pdf", "scheme-or-port", lambda h, p=443: "52.1.2.3"),
            ("https://s3.amazonaws.com:8443/p.pdf", "scheme-or-port", lambda h, p=443: "52.1.2.3"),
            ("https://internal.example/p.pdf", "ssrf-blocked", lambda h, p=443: None),
        ]:
            w_bad = self._make_wiley(_ScriptedConnFactory(lambda rec, l=loc: (302, {"Location": l}, b"")))
            w_bad._resolver = resolver
            self.assertEqual(w_bad.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], expected_err)

        w_loop = self._make_wiley(_ScriptedConnFactory(lambda rec: (302, {"Location": "https://api.wiley.com/loop"}, b"")))
        self.assertEqual(w_loop.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], "too-many-redirects")

        for ct, payload, expected in [
            ("text/html", b"<html>nope</html>", "not-pdf"),
            ("application/pdf", b"not-a-pdf%%EOF", "not-pdf-magic"),
            ("application/pdf", b"%PDF-1.4\ntruncated", "corrupt-pdf"),
        ]:
            w_pdf = self._make_wiley(_ScriptedConnFactory(lambda rec, c=ct, p=payload: (200, {"Content-Type": c}, p)))
            self.assertEqual(w_pdf.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], expected)

    def test_wiley_rate_limit_10min_cap_concurrency_cooldowns_and_env_clamping(self):
        # 10-min sliding cap
        now = [1000.0]
        rl = wt.WileyRateLimiter(min_spacing_s=10.0, max_per_10min=2, clock=lambda: now[0])
        self.assertTrue(rl.try_acquire())
        now[0] += 15.0
        self.assertTrue(rl.try_acquire())
        now[0] += 15.0
        self.assertFalse(rl.try_acquire())
        now[0] += 600.0
        self.assertTrue(rl.try_acquire())

        # Concurrency=1 returns busy; missing pdftotext fails before network call
        primary = fr.Reply(403, {}, b"blocked")
        body = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()
        sf = _ScriptedConnFactory(lambda rec: (200, {"Content-Type": "application/pdf"}, _fake_pdf_bytes()))
        w_busy = self._make_wiley(sf)
        w_busy._sem.acquire()
        try:
            self.assertEqual(w_busy.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], "busy")
        finally:
            w_busy._sem.release()

        w_nobin = self._make_wiley(sf)
        w_nobin.config.pdftotext_bin = ""
        self.assertEqual(w_nobin.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)[2], "pdftotext-missing")
        self.assertEqual(len(sf.calls), 0)

        # B2: 403, 429, 500, and fetch-error / fetch-timeout trip cooldown
        for val in (403, 429, 500, OSError("reset"), TimeoutError("timeout")):
            def _mk(v):
                def _h(rec):
                    if isinstance(v, Exception):
                        raise v
                    return v, {}, b""
                return _h
            w_cd = self._make_wiley(_ScriptedConnFactory(_mk(val)))
            w_cd.maybe_fetch("POST", "/v2/scrape", body, primary, "HTTP 403", fr.Reply)
            self.assertTrue(w_cd._in_cooldown(), f"expected cooldown for {val!r}")

        # Env clamping
        w_env = wt.build_wiley_tdm({
            "FIRECRAWL_ROUTER_WILEY_TDM": "on",
            "FIRECRAWL_ROUTER_WILEY_MIN_SPACING_S": "0",
            "FIRECRAWL_ROUTER_WILEY_MAX_PER_10MIN": "999",
            "FIRECRAWL_ROUTER_WILEY_ALLOW_CLOUD_LLM": "bogus",
            "FIRECRAWL_ROUTER_WILEY_STATE_DIR": str(self.state_dir),
            "FIRECRAWL_ROUTER_WILEY_SECRETSPEC_BIN": "",
        }, log=io.StringIO())
        self.assertEqual(w_env.config.min_spacing_s, wt.DEFAULT_MIN_SPACING_S)
        self.assertEqual(w_env.config.max_per_10min, wt.DEFAULT_MAX_PER_10MIN)
        self.assertFalse(w_env.allow_cloud_llm)

    def test_router_integration_oa_before_wiley_enrolled_guard_json_block_and_hidden_env(self):
        # OA succeeds -> Wiley TDM never called
        sf_wiley = _ScriptedConnFactory(lambda rec: (_ for _ in ()).throw(AssertionError("Wiley must not be called when OA succeeds")))
        w = self._make_wiley(sf_wiley)

        class _HitOA:
            enabled = True
            log = io.StringIO()
            _reply_cls = fr.Reply
            client = None
            core_client = None
            springer_client = None
            def maybe_fallback(self, *a, **kw):
                return fr.Reply(200, {"Content-Type": "application/json"}, b'{"success":true,"data":{"markdown":"OA copy"}}'), "oa-fallback", "oa:arxiv"

        primary_b = fr.Backend("primary", "http://127.0.0.1:1", "")
        fallback_b = fr.Backend("fallback", "http://127.0.0.1:2", "fb-key")
        router = fr.Router(primary_b, fallback_b, 30.0, log=io.StringIO(), oa_fallback=_HitOA(), wiley_tdm=w)
        with unittest.mock.patch.object(fr, "call", return_value=fr.Reply(403, {}, b"Just a moment...")):
            req = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()
            reply, backend = router.handle("POST", "/v2/scrape", {}, req)
        self.assertEqual(backend, "oa-fallback")

        # was_enrolled=True prevents commercial fallback even when both OA and Wiley fail
        class _EnrolledSkipBridge:
            enabled = True
            log = io.StringIO()
            _reply_cls = fr.Reply
            def maybe_bridge(self, *a, **kw):
                return None, None, "browser-botwall", True

        class _MissOA:
            enabled = True
            log = io.StringIO()
            _reply_cls = fr.Reply
            client = None
            core_client = None
            springer_client = None
            def maybe_fallback(self, *a, **kw):
                return None, None, "not-oa"

        w_miss = self._make_wiley(_ScriptedConnFactory(lambda rec: (404, {}, b"missing")))
        router_enr = fr.Router(primary_b, fallback_b, 30.0, log=io.StringIO(), mit_bridge=_EnrolledSkipBridge(), oa_fallback=_MissOA(), wiley_tdm=w_miss)
        calls = []
        def fake_call(b, *a, **kw):
            calls.append(b.name)
            return fr.Reply(403, {}, b"Just a moment...")
        with unittest.mock.patch.object(fr, "call", side_effect=fake_call):
            req = json.dumps({"url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250"}).encode()
            _, backend = router_enr.handle("POST", "/v2/scrape", {}, req)
        self.assertEqual(backend, "primary")
        self.assertEqual(calls, ["primary"])

        # formats: ["json"] + jsonOptions blocked on wiley-tdm by default, allowed when allow_cloud_llm=True
        sf_ok = _ScriptedConnFactory(lambda rec: (200, {"Content-Type": "application/pdf"}, _fake_pdf_bytes()))
        called_llm = []
        class _TrackExtractor:
            log = io.StringIO()
            def run(self, wants, md):
                called_llm.append(len(md))
                return {"json": {"ok": True}}, "sipb", ""

        req_json = json.dumps({
            "url": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/anie.4701250",
            "formats": ["json"],
            "jsonOptions": {"prompt": "Extract title"},
        }).encode()
        r_blk = fr.Router(primary_b, None, 30.0, log=io.StringIO(), extractor=_TrackExtractor(), wiley_tdm=self._make_wiley(sf_ok, allow_cloud_llm=False))
        with unittest.mock.patch.object(fr, "call", return_value=fr.Reply(403, {}, b"Just a moment...")):
            rep1, b1 = r_blk.handle("POST", "/v1/scrape", {}, req_json)
        self.assertEqual(b1, "wiley-tdm")
        self.assertEqual(rep1.headers.get("X-Firecrawl-LLM"), "blocked-policy")
        self.assertEqual(called_llm, [])

        r_ok = fr.Router(primary_b, None, 30.0, log=io.StringIO(), extractor=_TrackExtractor(), wiley_tdm=self._make_wiley(sf_ok, allow_cloud_llm=True))
        with unittest.mock.patch.object(fr, "call", return_value=fr.Reply(403, {}, b"Just a moment...")):
            rep2, b2 = r_ok.handle("POST", "/v1/scrape", {}, req_json)
        self.assertEqual(b2, "wiley-tdm")
        self.assertEqual(rep2.headers.get("X-Firecrawl-LLM"), "sipb")
        self.assertEqual(len(called_llm), 1)

        # All 6 new secret env vars are scrubbed before spawning firecrawl-mcp
        router_src = (REPO / "bin/firecrawl-router").read_text(encoding="utf-8")
        for var in (
            "CORE_API_KEY", "FIRECRAWL_ROUTER_CORE_KEY",
            "SPRINGER_NATURE_API_KEY", "FIRECRAWL_ROUTER_SPRINGER_KEY",
            "WILEY_TDM_TOKEN", "FIRECRAWL_ROUTER_WILEY_TDM_TOKEN",
        ):
            self.assertIn(f'"{var}"', router_src)

    def test_socks5_negative_framing_and_input_validation(self):
        # Input validation: bool ports, non-finite timeout, invalid host
        with self.assertRaises(ValueError):
            wt.socks5_connect("127.0.0.1", True, "api.wiley.com", 443, 2.0)
        with self.assertRaises(ValueError):
            wt.socks5_connect("127.0.0.1", 1, "api.wiley.com", True, 2.0)
        with self.assertRaises(ValueError):
            wt.socks5_connect("127.0.0.1", 1, "api.wiley.com", 443, float("nan"))
        with self.assertRaises(ValueError):
            wt.socks5_connect("127.0.0.1", 1, "api.wiley.com\r\n", 443, 2.0)
        with self.assertRaises(ValueError):
            wt.socks5_connect("127.0.0.1", 1, "api wiley.com", 443, 2.0)

        def _run_server(reply_bytes: bytes, *, expect_ok: bool):
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            def _srv():
                c, _ = srv.accept()
                try:
                    c.recv(3)
                    if reply_bytes == b"AUTH_REJECT":
                        c.sendall(b"\x05\xff")
                    elif reply_bytes == b"EOF":
                        pass
                    else:
                        c.sendall(b"\x05\x00")
                        c.recv(256)
                        c.sendall(reply_bytes)
                finally:
                    c.close()
                    srv.close()
            t = threading.Thread(target=_srv, daemon=True)
            t.start()
            if expect_ok:
                s = wt.socks5_connect("127.0.0.1", port, "api.wiley.com", 443, 2.0)
                s.close()
            else:
                with self.assertRaises(OSError):
                    wt.socks5_connect("127.0.0.1", port, "api.wiley.com", 443, 2.0)
            t.join(timeout=2.0)

        _run_server(b"AUTH_REJECT", expect_ok=False)
        _run_server(b"EOF", expect_ok=False)
        _run_server(b"\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00", expect_ok=False)  # non-zero REP
        _run_server(b"\x05\x00\x00\x09\x00\x00", expect_ok=False)                  # unknown ATYP
        _run_server(b"\x05\x00\x00\x03\x04test\x01\xbb", expect_ok=True)           # ATYP=3 domain
        _run_server(b"\x05\x00\x00\x04" + b"\x00" * 16 + b"\x01\xbb", expect_ok=True)  # ATYP=4 IPv6


if __name__ == "__main__":
    unittest.main()
