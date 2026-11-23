"""bin/firecrawl-router: fallback rules, job pinning, link rewriting, the child token."""
import http.server
import importlib.machinery
import importlib.util
import io
import json
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("firecrawl_router", str(ROOT / "bin" / "firecrawl-router"))
_spec = importlib.util.spec_from_loader("firecrawl_router", _loader)
fr = importlib.util.module_from_spec(_spec)
sys.modules["firecrawl_router"] = fr
_loader.exec_module(fr)

JOB = "0b8e1f2a-1111-4222-8333-944445555666"


class Fake:
    """A canned Firecrawl backend: routes[(method, path)] = (status, json-or-None)."""

    def __init__(self):
        self.routes = {}
        self.seen = []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                fake.seen.append((self.command, self.path, self.headers.get("Authorization")))
                status, doc = fake.routes.get((self.command, self.path.split("?")[0]), (404, {"error": "no route"}))
                body = json.dumps(doc).encode() if doc is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _any

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.p, self.f = Fake(), Fake()
        self.router = fr.Router(fr.Backend("primary", self.p.base, "pk"),
                                fr.Backend("fallback", self.f.base, "fk"),
                                timeout=5, token="tok", log=io.StringIO())
        self.srv = fr.serve(self.router, "127.0.0.1:0")

    def tearDown(self):
        self.srv.shutdown()
        self.p.close()
        self.f.close()

    def req(self, method, path, body=None, token="tok"):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.router.public_base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json",
                                            **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.headers.get("X-Firecrawl-Backend"), json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("X-Firecrawl-Backend"), json.loads(e.read() or b"null")

    def ok_scrape(self, code=200):
        return (200, {"success": True, "data": {"markdown": "x", "metadata": {"statusCode": code}}})

    def test_primary_success_stays_on_primary_with_its_key(self):
        self.p.routes[("POST", "/v2/scrape")] = self.ok_scrape()
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[:2], (200, "primary"))
        self.assertEqual(self.p.seen[-1][2], "Bearer pk")
        self.assertEqual(self.f.seen, [])

    def test_wrong_token_is_refused_before_any_backend(self):
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"}, token="bad")[0], 401)
        self.assertEqual(self.p.seen, [])

    def test_5xx_falls_back_with_fallback_key(self):
        self.p.routes[("POST", "/v2/scrape")] = (500, {"error": "All scraping engines failed"})
        self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape()
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[:2], (200, "fallback"))
        self.assertEqual(self.f.seen[-1][2], "Bearer fk")

    def test_bot_wall_page_status_falls_back(self):
        self.p.routes[("POST", "/v2/scrape")] = self.ok_scrape(403)
        self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape(200)
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "fallback")

    def test_aws_waf_statuses_fall_back(self):
        for code in (202, 405):
            self.p.routes[("POST", "/v2/scrape")] = self.ok_scrape(code)
            self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape(200)
            self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "fallback", code)

    def test_http_202_with_long_markdown_stays_on_primary(self):
        long_md = "Real IEEE Xplore full paper content. " * 600  # > 20 KiB
        self.p.routes[("POST", "/v2/scrape")] = (200, {"success": True, "data": {
            "markdown": long_md, "metadata": {"statusCode": 202}}})
        self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape(200)
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "primary")
        self.assertEqual(self.f.seen, [])

    def test_http_202_with_empty_or_short_markdown_falls_back(self):
        for md in ("", "   \n  ", "short challenge"):
            self.p.routes[("POST", "/v2/scrape")] = (200, {"success": True, "data": {
                "markdown": md, "metadata": {"statusCode": 202}}})
            self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape(200)
            self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "fallback", repr(md))

    def test_challenge_body_with_status_200_falls_back(self):
        for text in ("Just a moment...\nEnable JavaScript and cookies to continue",
                     "Please enable JS and disable any ad blocker",
                     "Press & Hold to confirm you are a human (and not a bot).",
                     "Request unsuccessful. Incapsula incident ID: 123-456",
                     "Vercel Security Checkpoint"):
            self.p.routes[("POST", "/v2/scrape")] = (200, {"success": True, "data": {
                "markdown": text, "metadata": {"statusCode": 200}}})
            self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape(200)
            self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "fallback", text)

    def test_long_article_mentioning_a_challenge_stays_on_primary(self):
        md = "How to press and hold a CAPTCHA button. " + "Real article text. " * 400
        self.p.routes[("POST", "/v2/scrape")] = (200, {"success": True, "data": {
            "markdown": md, "metadata": {"statusCode": 200}}})
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "primary")
        self.assertEqual(self.f.seen, [])

    def test_open_router_needs_no_token(self):
        self.router.token = ""
        self.p.routes[("POST", "/v2/search")] = (200, {"success": True, "data": {"web": [{"url": "a"}]}})
        self.assertEqual(self.req("POST", "/v2/search", {"query": "q"}, token="")[:2], (200, "primary"))
        self.assertEqual(self.p.seen[-1][2], "Bearer pk")

    def test_open_refuses_non_loopback_listen(self):
        with self.assertRaises(SystemExit):
            fr.main(["--listen", "0.0.0.0:18805", "--open"])

    def test_serve_only_refuses_non_loopback_listen(self):
        err = io.StringIO()
        with unittest.mock.patch.object(sys, "stderr", err), self.assertRaises(SystemExit) as cm:
            fr.main(["--listen", "0.0.0.0:18805"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("needs a loopback --listen address", err.getvalue())

    def test_bound_address_is_checked_before_serving(self):
        # the string check lets "0.0.0.0" through here on purpose (a resolver mapping "localhost"
        # elsewhere is the real case); the bound address is then refused before any request is served
        router = fr.Router(fr.Backend("primary", "http://127.0.0.1:9", ""), None, 1.0, "")
        with unittest.mock.patch.object(fr, "LOOPBACK_HOSTS", ("127.0.0.1", "localhost", "0.0.0.0")):
            with self.assertRaises(SystemExit) as cm:
                fr.serve(router, "0.0.0.0:0", require_loopback=True)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(router.public_base, "")  # never started
        srv = fr.serve(router, "0.0.0.0:0", require_loopback=False)  # a tokened run may bind it
        try:
            self.assertTrue(router.public_base.startswith("http://0.0.0.0:"))
        finally:
            srv.shutdown(); srv.server_close()

    def test_loopback_listen_check(self):
        for ok in ("127.0.0.1:0", "localhost:8805"):
            self.assertTrue(fr.is_loopback_listen(ok), ok)
        # IPv6 spellings are refused: serve() binds AF_INET and could never honour them
        for bad in ("0.0.0.0:8805", "192.168.1.5:8805", ":8805", "example.com:80", "[::1]:8805", "::1:8805"):
            self.assertFalse(fr.is_loopback_listen(bad), bad)

    def test_plain_404_page_does_not_fall_back(self):
        self.p.routes[("POST", "/v2/scrape")] = self.ok_scrape(404)
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[1], "primary")
        self.assertEqual(self.f.seen, [])

    def test_empty_map_and_search_fall_back(self):
        self.p.routes[("POST", "/v2/map")] = (200, {"success": True, "links": []})
        self.f.routes[("POST", "/v2/map")] = (200, {"success": True, "links": [{"url": "a"}]})
        self.assertEqual(self.req("POST", "/v2/map", {"url": "u"})[1], "fallback")
        self.p.routes[("POST", "/v2/search")] = (200, {"success": True, "data": {"web": []}})
        self.f.routes[("POST", "/v2/search")] = (200, {"success": True, "data": {"web": [{"url": "a"}]}})
        self.assertEqual(self.req("POST", "/v2/search", {"query": "q"})[1], "fallback")

    def test_missing_route_falls_back(self):
        self.f.routes[("POST", "/v2/agent")] = (200, {"success": True, "id": JOB})
        self.assertEqual(self.req("POST", "/v2/agent", {"prompt": "p"})[1], "fallback")

    def test_failed_fallback_returns_primary_answer(self):
        self.p.routes[("POST", "/v2/scrape")] = (500, {"error": "primary"})
        self.f.routes[("POST", "/v2/scrape")] = (429, {"error": "rate limited"})
        status, backend, doc = self.req("POST", "/v2/scrape", {"url": "u"})
        self.assertEqual((status, backend, doc["error"]), (500, "primary", "primary"))

    def test_unreachable_primary_uses_fallback(self):
        self.router.primary = fr.Backend("primary", "http://127.0.0.1:9", "pk")
        self.f.routes[("POST", "/v2/scrape")] = self.ok_scrape()
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[:2], (200, "fallback"))

    def test_crawl_job_stays_on_its_backend_and_links_are_rewritten(self):
        self.p.routes[("POST", "/v2/crawl")] = (502, {"error": "down"})
        self.f.routes[("POST", "/v2/crawl")] = (200, {"success": True, "id": JOB,
                                                      "url": f"https://api.example/v2/crawl/{JOB}"})
        self.f.routes[("GET", f"/v2/crawl/{JOB}")] = (200, {"status": "scraping", "data": [],
                                                           "next": f"https://api.example/v2/crawl/{JOB}?skip=10"})
        _, backend, doc = self.req("POST", "/v2/crawl", {"url": "u"})
        self.assertEqual(backend, "fallback")
        self.assertEqual(doc["url"], f"{self.router.public_base}/v2/crawl/{JOB}")
        _, backend, doc = self.req("GET", f"/v2/crawl/{JOB}")
        self.assertEqual(backend, "fallback")
        self.assertEqual(doc["next"], f"{self.router.public_base}/v2/crawl/{JOB}?skip=10")
        self.assertFalse(any(path.startswith(f"/v2/crawl/{JOB}") for _, path, _ in self.p.seen))

    def test_no_fallback_configured(self):
        self.router.fallback = None
        self.p.routes[("POST", "/v2/scrape")] = (500, {"error": "x"})
        self.assertEqual(self.req("POST", "/v2/scrape", {"url": "u"})[:2], (500, "primary"))

    def test_build_router_env(self):
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://a/", "FIRECRAWL_API_KEY": "k"}, "")
        self.assertEqual((r.primary.base, r.fallback.base), ("https://a", "https://api.firecrawl.dev"))
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://a", "FIRECRAWL_API_KEY": "k",
                             "FIRECRAWL_ROUTER_FALLBACK": "off"}, "")
        self.assertIsNone(r.fallback)

    def test_timeout_follows_request(self):
        self.assertEqual(fr.request_timeout(b'{"timeout": 200000}', 120), 230)
        self.assertEqual(fr.request_timeout(b'{"url": "u"}', 120), 120)
        # /search hard-cap: body timeout must not inflate past the search cap (2026-10-22).
        self.assertEqual(fr.request_timeout(b'{"timeout": 200000}', 120, cap=35), 35)
        self.assertEqual(fr.request_timeout(b'{"query": "q"}', 120, cap=35), 35)
        self.assertTrue(fr.search_path("/v2/search"))
        self.assertTrue(fr.search_path("/v2/search?x=1"))
        self.assertFalse(fr.search_path("/v2/scrape"))

    def test_build_router_search_timeout(self):
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://a/"}, "")
        self.assertEqual(r.search_timeout, 35.0)
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://a/",
                             "FIRECRAWL_ROUTER_SEARCH_TIMEOUT": "20"}, "")
        self.assertEqual(r.search_timeout, 20.0)


class Backend2:
    """Records request bodies. `reply(body_dict, path) -> (status, doc)`."""

    def __init__(self, reply):
        self.reply, self.bodies = reply, []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                me.bodies.append(body)
                status, doc = me.reply(body, self.path)
                raw = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def llm_ok(text, ptok=50):
    return 200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": ptok}}


class LLMFormatsTest(unittest.TestCase):
    PAGE = "# Doc\n\nThe default tail_mode is lean.\n\nOther text.\n"

    def setUp(self):
        self.page = self.PAGE
        self.fc = Backend2(lambda b, p: (200, {"success": True, "data": {"markdown": self.page, "metadata": {"statusCode": 200}}}))
        self.llm_a = Backend2(lambda b, p: llm_ok("lean"))
        self.llm_b = Backend2(lambda b, p: llm_ok("lean (b)"))
        self.made = [self.fc, self.llm_a, self.llm_b]

    def tearDown(self):
        for b in self.made:
            b.close()

    def router(self, one_shot=10_000, chunk=5_000, trunc=False):
        rungs = [fr.Rung("sipb", self.llm_a.base, "k", "m", one_shot, chunk, check_truncation=trunc),
                 fr.Rung("big", self.llm_b.base, "k", "m2", 10**7, 10**7)]
        return fr.Router(fr.Backend("primary", self.fc.base, ""), None, timeout=5, log=io.StringIO(),
                         extractor=fr.Extractor(rungs, deadline=30, call_timeout=5))

    def scrape(self, router, body):
        reply, backend = router.handle("POST", "/v2/scrape", {"Content-Type": "application/json"}, json.dumps(body).encode())
        return reply, reply.json()

    def test_query_runs_locally_and_the_primary_never_sees_it(self):
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "tail mode?", "mode": "freeform"}]})
        self.assertEqual(doc["data"]["answer"], "lean")
        self.assertNotIn("markdown", doc["data"])
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "sipb")
        self.assertEqual(self.fc.bodies[0]["formats"], ["markdown"])
        self.assertIn("tail mode?", json.dumps(self.llm_a.bodies[0]))
        self.assertEqual(self.llm_a.bodies[0]["model"], "m")

    def test_json_v2_object_gets_strict_schema(self):
        self.llm_a.reply = lambda b, p: llm_ok('{"mode": "lean"}')
        schema = {"type": "object", "properties": {"mode": {"type": "string"}}}
        _, doc = self.scrape(self.router(), {"url": "u", "formats": ["markdown", {"type": "json", "prompt": "get", "schema": schema}]})
        self.assertEqual(doc["data"]["json"], {"mode": "lean"})
        self.assertIn("markdown", doc["data"])  # asked for, so kept
        self.assertEqual(self.llm_a.bodies[0]["response_format"]["json_schema"]["schema"], schema)

    def test_json_v1_string_with_jsonoptions(self):
        self.llm_a.reply = lambda b, p: llm_ok('```json\n{"a": 1}\n```')
        _, doc = self.scrape(self.router(), {"url": "u", "formats": ["json"], "jsonOptions": {"prompt": "p", "schema": {"type": "object"}}})
        self.assertEqual(doc["data"]["json"], {"a": 1})
        self.assertNotIn("jsonOptions", self.fc.bodies[0])
        self.assertEqual(self.fc.bodies[0]["formats"], ["markdown"])

    def test_plain_scrape_is_forwarded_untouched(self):
        body = {"url": "u", "formats": ["markdown"]}
        _, doc = self.scrape(self.router(), body)
        self.assertEqual(self.fc.bodies, [body])
        self.assertEqual(self.llm_a.bodies, [])
        self.assertNotIn("answer", doc["data"])

    def test_big_page_is_chunked_and_reduced_on_the_same_model(self):
        self.page = "\n\n".join(f"Section {i}: filler text here." for i in range(40)) + "\n\nSECRET=42\n"
        n = {"map": 0}

        def llm(b, p):
            user = b["messages"][1]["content"]
            if "Excerpt" in user:
                n["map"] += 1
                return llm_ok("SECRET is 42" if "SECRET=42" in user else "NONE")
            return llm_ok("final")
        self.llm_a.reply = llm
        r, doc = self.scrape(self.router(one_shot=300, chunk=250), {"url": "u", "formats": [{"type": "query", "prompt": "secret?"}]})
        self.assertEqual(doc["data"]["answer"], "SECRET is 42")  # one hit: no reduce call
        self.assertGreater(n["map"], 2)
        self.assertEqual(self.llm_b.bodies, [])
        self.assertRegex(r.headers["X-Firecrawl-LLM"], r"^sipbx\d+$")

    def test_truncated_prompt_is_detected_and_falls_to_next_rung(self):
        self.page = "word " * 10_000
        self.llm_a.reply = lambda b, p: llm_ok("wrong, saw 10 tokens", ptok=10)
        r, doc = self.scrape(self.router(one_shot=10**6, trunc=True), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(doc["data"]["answer"], "lean (b)")
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "big")

    def test_small_prompt_is_never_called_truncated(self):
        # repetitive text tokenizes at 5+ chars per token (2026-10-18: 1883 tokens for 9502 chars)
        self.llm_a.reply = lambda b, p: llm_ok("lean", ptok=10)
        r, doc = self.scrape(self.router(trunc=True), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "sipb")

    def test_the_16386_cap_signature_is_truncation_even_for_dense_text(self):
        self.page = "word " * 10_000  # 50k chars / 16386 = 3.05 chars per token: the ratio rule alone misses it
        self.llm_a.reply = lambda b, p: llm_ok("start lost", ptok=fr.TRUNCATION_CAP_TOKENS)
        r, doc = self.scrape(self.router(one_shot=10**6, trunc=True), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "big")

    def test_empty_page_warns_and_calls_no_model(self):
        self.page = "  \n"
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.status, 200)
        self.assertIn("no content", doc["data"]["warning"])
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "none")
        self.assertEqual(self.llm_a.bodies + self.llm_b.bodies, [])

    def test_deadline_stops_a_chunk_loop_midway(self):
        self.page = "\n\n".join(f"Section {i}: filler text here." for i in range(60))

        def slow(b, p):
            time.sleep(0.3)
            return llm_ok("NONE")
        self.llm_a.reply = slow
        router = self.router(one_shot=300, chunk=250)
        router.extractor.deadline = 0.8
        r, doc = self.scrape(router, {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertLess(len(self.llm_a.bodies), 10)
        self.assertIn("deadline", doc["data"]["warning"])
        self.assertEqual(self.llm_b.bodies, [])

    def test_a_hung_call_is_cut_at_the_deadline_not_its_own_timeout(self):
        # 2026-10-18: a SIPB call that hung for its whole call timeout ended a scrape at 322 s, past Claude
        # Code's 300 s MCP limit. The call now gets only what is left of the deadline.
        def hang(b, p):
            time.sleep(3)
            return llm_ok("late")
        self.llm_a.reply = hang
        self.llm_b.reply = hang
        router = self.router()
        router.extractor.deadline = 0.6
        t0 = time.monotonic()
        r, doc = self.scrape(router, {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertNotIn("answer", doc["data"])
        self.assertIn("deadline", doc["data"]["warning"])
        self.assertEqual(r.status, 200)

    def test_direct_quote_none_is_an_abstain_not_a_failure(self):
        self.llm_a.reply = lambda b, p: llm_ok("NONE")
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q", "mode": "directQuote"}]})
        self.assertEqual(doc["data"]["answer"], fr.LLM_ABSTAIN)
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "sipb")
        self.assertEqual(self.llm_b.bodies, [])

    def test_one_empty_reply_is_retried_on_the_same_rung(self):
        replies = iter(["", "lean"])
        self.llm_a.reply = lambda b, p: llm_ok(next(replies))
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(doc["data"]["answer"], "lean")
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "sipb")
        self.assertEqual(len(self.llm_a.bodies), 2)

    def test_two_empty_replies_fall_to_the_next_rung(self):
        self.llm_a.reply = lambda b, p: llm_ok("")
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "big")
        self.assertEqual(len(self.llm_a.bodies), 2)

    def test_a_failed_rung_is_logged_even_when_a_later_one_answers(self):
        self.llm_a.reply = lambda b, p: (500, {"error": "down"})
        router = self.router()
        self.scrape(router, {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertIn("llm rung sipb failed: HTTP 500", router.log.getvalue())

    def test_every_rung_failing_returns_the_markdown_with_a_warning(self):
        self.llm_a.reply = self.llm_b.reply = lambda b, p: (500, {"error": "down"})
        r, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.status, 200)
        self.assertEqual(doc["data"]["markdown"], self.PAGE)
        self.assertIn("LLM extraction failed", doc["data"]["warning"])
        self.assertNotIn("answer", doc["data"])
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "none")

    def test_direct_quote_must_appear_in_the_page(self):
        self.llm_a.reply = lambda b, p: llm_ok("an invented sentence")
        self.llm_b.reply = lambda b, p: llm_ok("The default tail_mode is **lean**.")
        _, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q", "mode": "directQuote"}]})
        self.assertEqual(doc["data"]["answer"], "The default tail_mode is **lean**.")

    def test_primary_failure_passes_through_without_calling_a_model(self):
        self.fc.reply = lambda b, p: (500, {"error": "boom"})
        r, _ = self.scrape(self.router(), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r.status, 500)
        self.assertEqual(self.llm_a.bodies, [])

    def test_response_format_refused_retries_without_it(self):
        seen = []

        def llm(b, p):
            seen.append("response_format" in b)
            return (400, {"error": "no"}) if "response_format" in b else llm_ok('{"x": 1}')
        self.llm_a.reply = llm
        _, doc = self.scrape(self.router(), {"url": "u", "formats": [{"type": "json", "prompt": "p"}]})
        self.assertEqual(doc["data"]["json"], {"x": 1})
        self.assertEqual(seen, [True, False])

    def test_chunks_are_lossless_and_bounded(self):
        text = ("para one\n\n" * 30) + "x" * 700 + ("\nline\n" * 50)
        parts = fr.split_chunks(text, 200)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(c) <= 200 for c in parts))

    def test_env_switch_and_defaults(self):
        self.assertIsNone(fr.build_extractor({"FIRECRAWL_ROUTER_LLM": "off"}))
        ex = fr.build_extractor({"FIRECRAWL_ROUTER_SIPB_KEY": "s", "FIRECRAWL_ROUTER_LITELLM_KEY": "l"})
        self.assertEqual([r.name for r in ex.rungs], ["sipb", "gemini-free", "gemini-free-lite"])
        self.assertTrue(ex.rungs[0].check_truncation)
        self.assertEqual(ex.rungs[0].base, "http://127.0.0.1:8890/api")
        self.assertFalse(ex.prefer_oneshot)

    def test_llm_order_litellm_first_and_oneshot_first(self):
        ex_lite = fr.build_extractor({"FIRECRAWL_ROUTER_LLM_ORDER": "litellm,sipb"})
        self.assertEqual([r.name for r in ex_lite.rungs], ["gemini-free", "gemini-free-lite", "sipb"])
        self.assertFalse(ex_lite.prefer_oneshot)

        ex_os = fr.build_extractor({"FIRECRAWL_ROUTER_LLM_ORDER": "oneshot-first"})
        self.assertEqual([r.name for r in ex_os.rungs], ["sipb", "gemini-free", "gemini-free-lite"])
        self.assertTrue(ex_os.prefer_oneshot)

        # Short page uses sipb first; long page (> sipb.one_shot) uses big one-shot first.
        rungs = [fr.Rung("sipb", self.llm_a.base, "k", "m", 200, 150, check_truncation=True),
                 fr.Rung("big", self.llm_b.base, "k", "m2", 10_000, 5_000)]
        router = fr.Router(fr.Backend("primary", self.fc.base, ""), None, timeout=5, log=io.StringIO(),
                           extractor=fr.Extractor(rungs, deadline=30, call_timeout=5, prefer_oneshot=True))
        self.page = "Short page about lean."
        r1, doc1 = self.scrape(router, {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r1.headers["X-Firecrawl-LLM"], "sipb")
        self.assertEqual(doc1["data"]["answer"], "lean")
        self.page = "Long academic paper content. " * 40  # > 200 chars, <= 10_000
        r2, doc2 = self.scrape(router, {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(r2.headers["X-Firecrawl-LLM"], "big")
        self.assertEqual(doc2["data"]["answer"], "lean (b)")


class EndpointTest(unittest.TestCase):
    """The four base URLs that receive a key must be https or loopback (2026-10-20)."""

    VARS = ("FIRECRAWL_SELFHOST_URL", "FIRECRAWL_FALLBACK_URL",
            "FIRECRAWL_ROUTER_SIPB_BASE", "FIRECRAWL_ROUTER_LITELLM_BASE")

    def build(self, var, url, **extra):
        env = {"FIRECRAWL_SELFHOST_URL": "https://primary.example", "FIRECRAWL_API_KEY": "k", **extra, var: url}
        return fr.build_router(env, "")

    def test_https_and_loopback_http_are_accepted(self):
        for var in self.VARS:
            for url in ("https://ok.example/v1", "http://127.0.0.1:9", "http://localhost:9/api",
                        "http://[::1]:9", "https://ok.example"):
                with self.subTest(var=var, url=url):
                    self.build(var, url)

    def test_plain_http_to_another_host_is_refused_naming_the_variable(self):
        for var in self.VARS:
            for url in ("http://evil.example", "http://evil.example/v1", "http://127.0.0.1.evil.example",
                        "http://127.0.0.1@evil.example", "ftp://x.example", "file:///etc/passwd", "evil.example"):
                with self.subTest(var=var, url=url), self.assertRaises(SystemExit) as cm:
                    self.build(var, url)
                self.assertIn(var, str(cm.exception.code))

    def test_userinfo_backslash_and_whitespace_are_refused(self):
        # urlparse().hostname says 127.0.0.1 / api.firecrawl.dev for these, urllib dials the whole netloc
        for var in self.VARS:
            for url in ("http://evil.example@127.0.0.1:9", "https://evil.example@api.firecrawl.dev",
                        "https://user:pw@ok.example", "https://@ok.example", "https://evil.example\\@api.firecrawl.dev",
                        "https://ok.example\\", " http://127.0.0.1:9", "http://127.0.0.1:9 ", "http://127.0.0.1:9\n",
                        "https://ok .example", "https://ok.example/a b", "\thttps://ok.example", "https://ok.example:99999"):
                with self.subTest(var=var, url=url), self.assertRaises(SystemExit) as cm:
                    self.build(var, url)
                self.assertIn(var, str(cm.exception.code))

    def test_refusal_prints_only_the_origin(self):
        with self.assertRaises(SystemExit) as cm:
            self.build("FIRECRAWL_SELFHOST_URL", "http://KEY123:PW456@evil.example:8080/v1?k=SECRET789")
        msg = str(cm.exception.code)
        self.assertTrue(msg.endswith("not http://evil.example:8080"), msg)
        for secret in ("KEY123", "PW456", "SECRET789"):
            self.assertNotIn(secret, msg)

    def test_no_variable_lifts_the_rule(self):
        # FIRECRAWL_ROUTER_ALLOW_HTTP was removed (2026-10-20): loopback http already passes, and an agent that
        # can set a base URL can set a flag next to it
        for var in self.VARS:
            for flag in ("1", "0", "true"):
                with self.subTest(var=var, flag=flag), self.assertRaises(SystemExit):
                    self.build(var, "http://evil.example", FIRECRAWL_ROUTER_ALLOW_HTTP=flag)

    def test_unused_fallback_url_is_not_checked_without_a_key(self):
        # no FIRECRAWL_API_KEY: the fallback is off, so its URL never receives anything
        fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://p.example",
                         "FIRECRAWL_FALLBACK_URL": "http://evil.example"}, "")

    def test_defaults_pass(self):
        fr.build_router({"FIRECRAWL_SELFHOST_URL": "https://p.example", "FIRECRAWL_API_KEY": "k"}, "")


class Redirector:
    """A loopback server that records Authorization and answers every request with a redirect to `to`."""

    def __init__(self, to=None, code=302):
        self.seen = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                me.seen.append((self.path, self.headers.get("Authorization")))
                self.send_response(code if to else 200)
                if to:
                    self.send_header("Location", to + self.path)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = do_POST = _any

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


REDIRECT_CODES = (301, 302, 303, 307, 308)


class NoRedirectTest(unittest.TestCase):
    def setUp(self):
        self.target = Redirector()
        self.origin = Redirector(to=self.target.base)
        self.addCleanup(self.target.close)
        self.addCleanup(self.origin.close)

    def pair(self, code):
        target = Redirector()
        origin = Redirector(to=target.base, code=code)
        self.addCleanup(target.close)
        self.addCleanup(origin.close)
        return origin, target

    def test_backend_call_does_not_follow_a_redirect(self):
        for code in REDIRECT_CODES:
            with self.subTest(code=code):
                origin, target = self.pair(code)
                reply = fr.call(fr.Backend("primary", origin.base, "secret-pk"), "POST", "/v2/scrape",
                                {"Content-Type": "application/json"}, b"{}", 5)
                self.assertEqual(reply.status, 0)
                self.assertIn(f"redirect refused (HTTP {code})", reply.error)
                self.assertEqual(origin.seen, [("/v2/scrape", "Bearer secret-pk")])
                self.assertEqual(target.seen, [])

    def test_backend_key_is_an_unredirected_header(self):
        seen = []

        class Spy(fr.urllib.request.OpenerDirector):
            def open(self, req, data=None, timeout=None):
                seen.append(req)
                raise OSError("stop")

        from unittest import mock
        with mock.patch.object(fr.urllib.request, "build_opener", return_value=Spy()) as bo:
            fr.call(fr.Backend("primary", "https://x.example", "secret-pk"), "GET", "/", {}, None, 5)
        self.assertIn(fr._NoRedirect, bo.call_args.args)
        self.assertNotIn("Authorization", seen[0].headers)
        self.assertEqual(seen[0].unredirected_hdrs.get("Authorization"), "Bearer secret-pk")

    def test_llm_rung_does_not_follow_a_redirect(self):
        for code in REDIRECT_CODES:
            with self.subTest(code=code):
                origin, target = self.pair(code)
                ex = fr.Extractor([fr.Rung("sipb", origin.base, "secret-llm", "m", 10, 10)], deadline=30, call_timeout=5)
                with self.assertRaises(fr.LLMError) as cm:
                    ex._post(ex.rungs[0], {"model": "m", "messages": []})
                self.assertIn(str(code), str(cm.exception))
                self.assertEqual(origin.seen, [("/chat/completions", "Bearer secret-llm")])
                self.assertEqual(target.seen, [])

    def test_router_does_not_leak_a_redirect_to_its_client(self):
        for code in REDIRECT_CODES:
            with self.subTest(code=code):
                origin, target = self.pair(code)
                router = fr.Router(fr.Backend("primary", origin.base, "pk"), None, timeout=5, token="tok",
                                   log=io.StringIO())
                srv = fr.serve(router, "127.0.0.1:0")
                self.addCleanup(srv.shutdown)
                r = urllib.request.Request(router.public_base + "/v2/scrape", data=b"{}", method="POST",
                                           headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(r, timeout=10)
                self.assertGreaterEqual(cm.exception.code, 500)
                self.assertIsNone(cm.exception.headers.get("Location"))
                self.assertEqual(target.seen, [])


class RequestTargetTest(unittest.TestCase):
    """A client's raw request target must not move the backend key to another host (adversary, 2026-10-20)."""

    def raw(self, router, target, method="POST"):
        import http.client
        host, _, port = router.public_base.removeprefix("http://").partition(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=10)
        try:
            conn.putrequest(method, target, skip_host=False)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", "2")
            conn.endheaders(b"{}")
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    def serve(self, base, **kw):
        router = fr.Router(fr.Backend("primary", base, "real-key"), None, timeout=5, token="", log=io.StringIO(), **kw)
        srv = fr.serve(router, "127.0.0.1:0")
        self.addCleanup(srv.shutdown)
        return router

    def test_a_target_that_names_another_host_reaches_no_server(self):
        attacker = Redirector()
        self.addCleanup(attacker.close)
        port = attacker.base.rsplit(":", 1)[1]
        # base `http://127.0.0.1` + `:PORT/v2/scrape` is a different port; `.x.example` extends the host name;
        # `@x.example` turns the base into userinfo
        cases = ((f"http://127.0.0.1", f":{port}/v2/scrape"),
                 ("http://127.0.0.1", f":{port}/v1/scrape"),
                 (f"http://127.0.0.1:{port}", ".x.example/v2/scrape"),
                 (f"http://127.0.0.1:{port}", "@x.example/v2/scrape"),
                 (f"http://127.0.0.1:{port}", ":1/v2/scrape"),
                 (f"http://127.0.0.1:{port}", "x.example/v2/scrape"),
                 (f"http://127.0.0.1:{port}", "?x=/v2/scrape"))
        for base, target in cases:
            with self.subTest(base=base, target=target):
                router = self.serve(base)
                for method in ("POST", "GET"):
                    self.assertEqual(self.raw(router, target, method), 400)
        self.assertEqual(attacker.seen, [])  # nothing reached the capture server, with or without a key

    def test_call_itself_refuses_a_target_that_changes_the_host(self):
        attacker = Redirector()
        self.addCleanup(attacker.close)
        port = attacker.base.rsplit(":", 1)[1]
        for base, target in (("http://127.0.0.1", f":{port}/v2/scrape"), ("http://localhost", ".localtest.me/x"),
                             (attacker.base, "@x.example/y"), (attacker.base, ""), (attacker.base, "v2/scrape")):
            with self.subTest(base=base, target=target):
                reply = fr.call(fr.Backend("primary", base, "real-key"), "GET", target, {}, None, 5)
                self.assertEqual(reply.status, 0)
                self.assertIn("refused", reply.error)
        self.assertEqual(attacker.seen, [])

    def test_a_double_slash_target_stays_on_the_configured_host(self):
        base, other = Redirector(), Redirector()
        self.addCleanup(base.close)
        self.addCleanup(other.close)
        router = self.serve(base.base)
        self.raw(router, "//x.example/v2/scrape")
        self.assertEqual(other.seen, [])
        # whatever the server made of "//x.example/..." it went to the base, as a path, with the key
        self.assertTrue(all(path.startswith("/") and key == "Bearer real-key" for path, key in base.seen), base.seen)

    def test_ordinary_targets_still_work(self):
        origin = Redirector()
        self.addCleanup(origin.close)
        router = self.serve(origin.base)
        self.assertEqual(self.raw(router, "/v2/scrape"), 200)
        self.assertEqual(self.raw(router, "/v2/crawl/abc?x=1", "GET"), 200)
        self.assertEqual(origin.seen, [("/v2/scrape", "Bearer real-key"), ("/v2/crawl/abc?x=1", "Bearer real-key")])


class HostAllowListTest(unittest.TestCase):
    """Tokenless serving answers only a Host that names the bound loopback server (2026-10-22)."""

    def raw(self, port, host, target="/v2/scrape"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.putrequest("POST", target, skip_host=True)
            conn.putheader("Host", host)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", "2")
            conn.endheaders(b"{}")
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    def serve(self, base):
        router = fr.Router(fr.Backend("primary", base, "real-key"), None, timeout=5, token="", log=io.StringIO())
        srv = fr.serve(router, "127.0.0.1:0")
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def test_rebinding_host_names_are_refused(self):
        origin = Redirector()
        self.addCleanup(origin.close)
        srv = self.serve(origin.base)
        port = srv.server_address[1]
        for host in ("evil.example", f"127.0.0.1.evil.example:{port}", f"evil.example:{port}",
                     f"localhost.evil.example:{port}", "[::1]", "127.0.0.1:1"):
            with self.subTest(host=host):
                self.assertEqual(self.raw(port, host), 403)
        self.assertEqual(origin.seen, [])

    def test_the_bound_loopback_host_still_answers(self):
        origin = Redirector()
        self.addCleanup(origin.close)
        srv = self.serve(origin.base)
        port = srv.server_address[1]
        for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
            with self.subTest(host=host):
                self.assertEqual(self.raw(port, host), 200)
        self.assertEqual(len(origin.seen), 2)


class ChildEnvTest(unittest.TestCase):
    def test_child_never_sees_the_router_keys(self):
        import os
        import tempfile
        from unittest import mock
        secrets_ = {"FIRECRAWL_SELFHOST_API_KEY": "gate-secret", "FIRECRAWL_ROUTER_SIPB_KEY": "sipb-secret",
                    "FIRECRAWL_ROUTER_LITELLM_KEY": "litellm-secret", "OPENALEX_API_KEY": "openalex-secret",
                    "FIRECRAWL_ROUTER_OPENALEX_KEY": "openalex-secret-2"}
        env = {"FIRECRAWL_SELFHOST_URL": "http://127.0.0.1:9", "PATH": os.environ.get("PATH", ""), **secrets_}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "env.json"
            code = f"import json,os;json.dump(dict(os.environ),open({str(out)!r},'w'))"
            with mock.patch.dict(os.environ, env, clear=True):
                rc = fr.main(["--listen", "127.0.0.1:0", "--", sys.executable, "-c", code])
            child = json.loads(out.read_text())
        self.assertEqual(rc, 0)
        for k in secrets_:
            self.assertNotIn(k, child)
        self.assertNotIn("secret", json.dumps(child))
        self.assertTrue(child["FIRECRAWL_API_URL"].startswith("http://127.0.0.1:"))
        self.assertGreater(len(child["FIRECRAWL_API_KEY"]), 20)  # the per-process router token


def _make_snapshot_bytes(domains, *, sha_override=None):
    import base64
    import hashlib
    raw = b'{"acls":[]}'
    policy = {
        "nodeAttrs": [
            {
                "target": ["*"],
                "app": {
                    "tailscale.com/app-connectors": [
                        {"name": "mitnet-required", "connectors": ["tag:mitnet-connector"], "domains": list(domains)}
                    ]
                },
            }
        ]
    }
    doc = {
        "tailnet": "example.com",
        "revision": {
            "raw": base64.b64encode(raw).decode("ascii"),
            "policy": policy,
            "etag": '"rev1"',
            "sha256": sha_override or hashlib.sha256(raw).hexdigest(),
        },
    }
    return json.dumps(doc).encode("utf-8")


def _write_exec(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)
    return str(path)


class MitBridgeTest(unittest.TestCase):
    """Mac-side MIT Libraries bridge (Slices 1a + 1b): fail-closed, scrubbed env, converters, concurrency."""

    def setUp(self):
        import os
        import socket
        import tempfile
        self._os = os
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.state_dir = self.root / "state"
        self.snap = self.root / "enrolled-snapshot.json"
        self.snap.write_bytes(_make_snapshot_bytes(["www.nature.com", "www.cambridge.org"]))
        self.snap.chmod(0o600)
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir(mode=0o700)

        # Fake listening SOCKS port for browser pre-flight (closed cleanly in tearDown).
        self.socks_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socks_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socks_srv.bind(("127.0.0.1", 0))
        self.socks_srv.listen(4)
        self.socks_port = self.socks_srv.getsockname()[1]

        self.primary = Backend2(lambda b, p: (200, {"success": True, "data": {
            "markdown": "Client Challenge",
            "metadata": {"statusCode": 200, "contentType": "text/html", "url": "https://idp.nature.com/auth"},
        }}))
        self.fallback = Backend2(lambda b, p: (200, {"success": True, "data": {
            "markdown": "commercial", "metadata": {"statusCode": 200},
        }}))

        # Sibling helper module proving -E -s keeps script directory on sys.path (F1).
        (self.root / "bridge_test_sibling.py").write_text('MARKER = "sibling-ok"\n', encoding="utf-8")

        self.fetch_bin = _write_exec(self.root / "fake_fetch.py", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
import bridge_test_sibling
assert bridge_test_sibling.MARKER == "sibling-ok"
argv = sys.argv[1:]
Path({str(self.log_dir / 'fetch_argv.json')!r}).write_text(json.dumps(argv))
Path({str(self.log_dir / 'fetch_env.json')!r}).write_text(json.dumps(dict(os.environ)))
out_dir = Path(argv[argv.index("--output") + 1])
run = out_dir / "run-sub"
run.mkdir(mode=0o700, parents=True, exist_ok=True)
pdf = run / "mit.body"
pdf.write_bytes(b"%PDF-1.7 fake body")
print(json.dumps({{
    "verdict": "enrolled",
    "mit": {{"class": "ok", "status": 200, "content_is_pdf": True}},
    "evidence": {{"body_dir": str(run), "mit_body": str(pdf)}},
}}))
""")
        self.browser_bin = _write_exec(self.root / "fake_browser.py", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
import bridge_test_sibling
assert bridge_test_sibling.MARKER == "sibling-ok"
argv = sys.argv[1:]
Path({str(self.log_dir / 'browser_argv.json')!r}).write_text(json.dumps(argv))
Path({str(self.log_dir / 'browser_env.json')!r}).write_text(json.dumps(dict(os.environ)))
out_dir = Path(argv[argv.index("--output") + 1])
run = out_dir / "run-sub"
run.mkdir(mode=0o700, parents=True, exist_ok=True)
if "--artifact" in argv:
    pdf = run / "article.pdf"
    pdf.write_bytes(b"%PDF-1.7 browser pdf")
    print(json.dumps({{
        "class": "ok", "status": 200, "content_is_pdf": True,
        "evidence": {{"body_dir": str(run), "body": str(pdf), "text": None}},
    }}))
else:
    h = run / "page.html"
    t = run / "page.txt"
    h.write_text("<html><head><title>Cambridge Paper</title></head><body><h1>Title</h1><p>Body</p></body></html>")
    t.write_text("Fallback plain text from Cambridge Paper")
    print(json.dumps({{
        "class": "ok", "status": 200, "content_is_pdf": False,
        "evidence": {{"body_dir": str(run), "body": str(h), "text": str(t)}},
    }}))
""")
        self.pdftotext_bin = _write_exec(self.root / "fake_pdftotext", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
Path({str(self.log_dir / 'pdftotext_argv.json')!r}).write_text(json.dumps(sys.argv[1:]))
Path({str(self.log_dir / 'pdftotext_env.json')!r}).write_text(json.dumps(dict(os.environ)))
sys.stdout.write("# Nature Paper\\n\\nExtracted PDF text.\\n")
""")
        self.pdfinfo_bin = _write_exec(self.root / "fake_pdfinfo", f"""#!{sys.executable}
import sys
sys.stdout.write("Title:          Deep Learning\\nPages:          12\\n")
""")
        self.pandoc_bin = _write_exec(self.root / "fake_pandoc", f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
Path({str(self.log_dir / 'pandoc_argv.json')!r}).write_text(json.dumps(sys.argv[1:]))
Path({str(self.log_dir / 'pandoc_env.json')!r}).write_text(json.dumps(dict(os.environ)))
data = sys.stdin.read()
assert "--sandbox" in sys.argv[1:]
sys.stdout.write("# Cambridge Markdown\\n\\nConverted from HTML.\\n")
""")

    def tearDown(self):
        self.socks_srv.close()
        self.primary.close()
        self.fallback.close()
        self._td.cleanup()

    def _bridge(self, mode="all", **overrides):
        mb = fr._MIT_BRIDGE_MOD
        kw = dict(
            mode=mode,
            snapshot_path=str(self.snap),
            fetch_bin=self.fetch_bin,
            browser_bin=self.browser_bin,
            python_bin=sys.executable,
            socks_host="127.0.0.1",
            socks_port=self.socks_port,
            state_dir=str(self.state_dir),
            pdftotext_bin=self.pdftotext_bin,
            pdfinfo_bin=self.pdfinfo_bin,
            pandoc_bin=self.pandoc_bin,
            cooldown_s=60.0,
            fetch_sem_timeout=0.2,
            browser_sem_timeout=0.2,
        )
        kw.update(overrides)
        return mb.MitBridge(mb.MitBridgeConfig(**kw), log=io.StringIO(), reply_cls=fr.Reply)

    def _router(self, bridge=None, with_fallback=True, extractor=None):
        return fr.Router(
            fr.Backend("primary", self.primary.base, "pk"),
            fr.Backend("fallback", self.fallback.base, "fk") if with_fallback else None,
            timeout=5,
            log=io.StringIO(),
            extractor=extractor,
            mit_bridge=bridge,
        )

    def _post(self, router, path, body):
        return router.handle("POST", path, {"Content-Type": "application/json"}, json.dumps(body).encode())

    def test_default_off_never_reads_snapshot_or_spawns(self):
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": self.primary.base}, "")
        self.assertIsNone(r.mit_bridge)
        reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((reply.status, backend), (200, "primary"))
        self.assertFalse((self.log_dir / "fetch_argv.json").exists())

    def test_non_enrolled_host_never_bridged(self):
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {"markdown": "blocked", "metadata": {"statusCode": 429}}})
        router = self._router(self._bridge(mode="all"), with_fallback=False)
        reply, backend = self._post(router, "/v2/scrape", {"url": "https://evil.example/paper.pdf"})
        self.assertEqual(backend, "primary")
        self.assertFalse((self.log_dir / "fetch_argv.json").exists())
        self.assertFalse((self.log_dir / "browser_argv.json").exists())

    def test_snapshot_refusals_fail_closed(self):
        mb = fr._MIT_BRIDGE_MOD
        # missing
        r = self._router(self._bridge(snapshot_path=str(self.root / "missing.json")), with_fallback=False)
        reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual(backend, "primary")
        self.assertEqual(reply.headers.get("X-Firecrawl-MIT-Bridge"), "skipped:snapshot-missing")

        # symlink
        link = self.root / "link.json"
        link.symlink_to(self.snap)
        r = self._router(self._bridge(snapshot_path=str(link)), with_fallback=False)
        reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:snapshot-symlink"))

        # group/world writable (0664, 0666, 0646)
        for mode in (0o664, 0o666, 0o646):
            p = self.root / f"w_{oct(mode)}.json"
            p.write_bytes(_make_snapshot_bytes(["www.nature.com"]))
            p.chmod(mode)
            r = self._router(self._bridge(snapshot_path=str(p)), with_fallback=False)
            reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
            self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:snapshot-writable"))

        # wrong owner
        with unittest.mock.patch.object(mb.os, "getuid", return_value=self._os.getuid() + 1):
            r = self._router(self._bridge(), with_fallback=False)
            reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
            self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:snapshot-owner"))

        # stale (> 7d)
        stale = self.root / "stale.json"
        stale.write_bytes(_make_snapshot_bytes(["www.nature.com"]))
        stale.chmod(0o600)
        old = time.time() - 8 * 86400
        self._os.utime(stale, (old, old))
        r = self._router(self._bridge(snapshot_path=str(stale)), with_fallback=False)
        reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:snapshot-stale"))

        # duplicate JSON key, bad checksum, empty domains
        for name, raw, want in (
            ("dup", _make_snapshot_bytes(["www.nature.com"])[:-1] + b', "tailnet": "dup"}', "skipped:snapshot-invalid"),
            ("badsha", _make_snapshot_bytes(["www.nature.com"], sha_override="0" * 64), "skipped:snapshot-invalid"),
            ("empty", _make_snapshot_bytes([]), "skipped:snapshot-empty"),
        ):
            p = self.root / f"{name}.json"
            p.write_bytes(raw)
            p.chmod(0o600)
            r = self._router(self._bridge(snapshot_path=str(p)), with_fallback=False)
            reply, backend = self._post(r, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
            self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", want), name)

        self.assertFalse((self.log_dir / "fetch_argv.json").exists())

    def test_url_and_ssrf_refusals_never_spawn(self):
        router = self._router(self._bridge(mode="all"), with_fallback=False)
        bad_urls = (
            "http://127.0.0.1/a.pdf",
            "http://169.254.169.254/a.pdf",
            "https://www.nature.com@evil.example/a.pdf",
            "https://www.nature.com.evil.example/a.pdf",
            "https://WWW.NATURE.COM/a.pdf",
            "https://www.nature.com./a.pdf",
            "https://www%2enature.com/a.pdf",
            "https://www.nature.com\\evil.example/a.pdf",
            "HTTPS://www.nature.com/a.pdf",
            "HTTP://www.nature.com/a.pdf",
        )
        for u in bad_urls:
            reply, backend = self._post(router, "/v2/scrape", {"url": u})
            self.assertEqual(backend, "primary", u)
            self.assertNotIn("X-Firecrawl-MIT-Bridge", reply.headers, u)
        # Lane 1 (mit-fetch) refuses non-443 ports and plaintext http:// (F2)
        for body in (
            {"url": "https://www.nature.com:8443/a.pdf"},
            {"url": "http://www.nature.com/a.pdf"},
            {"url": "http://www.nature.com:6379/article", "parsers": ["pdf"]},
        ):
            reply, backend = self._post(router, "/v2/scrape", body)
            self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")),
                             ("primary", "skipped:fetch-requires-https-443"), body)
        # Non-443 port refused by browser lane
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {"markdown": "wall", "metadata": {"statusCode": 429}}})
        reply, backend = self._post(router, "/v2/scrape", {"url": "https://www.cambridge.org:8443/article"})
        self.assertEqual(backend, "primary")
        self.assertEqual(reply.headers.get("X-Firecrawl-MIT-Bridge"), "skipped:browser-requires-https-443")
        self.assertFalse((self.log_dir / "fetch_argv.json").exists())
        self.assertFalse((self.log_dir / "browser_argv.json").exists())

    def test_non_scrape_routes_never_bridged(self):
        router = self._router(self._bridge(mode="all"), with_fallback=False)
        for route in ("/v2/crawl", "/v2/batch/scrape", "/v2/map", "/v2/search", "/v1/crawl"):
            reply, backend = self._post(router, route, {"url": "https://www.nature.com/articles/x.pdf"})
            self.assertEqual(backend, "primary", route)
        self.assertFalse((self.log_dir / "fetch_argv.json").exists())

    def test_happy_path_pdf_mit_fetch_and_cleanup(self):
        router = self._router(self._bridge(mode="pdf"))
        for route in ("/v2/scrape", "/v1/scrape"):
            reply, backend = self._post(router, route, {
                "url": "https://www.nature.com/articles/nature14539.pdf?token=SUPERSECRET",
                "pdfOptions": {"maxPages": 15},
                "headers": {"Cookie": "evil=1"},
                "proxy": "stealth",
            })
            self.assertEqual((reply.status, backend), (200, "mit-fetch"), route)
            doc = reply.json()
            self.assertTrue(doc["success"])
            self.assertIn("Extracted PDF text", doc["data"]["markdown"])
            meta = doc["data"]["metadata"]
            self.assertEqual(meta["statusCode"], 200)
            self.assertEqual(meta["contentType"], "application/pdf")
            self.assertEqual(meta["numPages"], 12)
            self.assertEqual(meta["title"], "Deep Learning")
            self.assertEqual(meta["proxyUsed"], "mit-bridge")
            self.assertEqual(meta["sourceURL"], "https://www.nature.com/articles/nature14539.pdf")
            self.assertNotIn("SUPERSECRET", json.dumps(doc))
        # Verify fetch.py received --enrolled-only and -- before URL, and pdftotext received -l 15
        f_argv = json.loads((self.log_dir / "fetch_argv.json").read_text())
        self.assertIn("--enrolled-only", f_argv)
        self.assertIn("--artifact", f_argv)
        self.assertEqual(f_argv[-2], "--")
        self.assertNotIn("Cookie", json.dumps(f_argv))
        p_argv = json.loads((self.log_dir / "pdftotext_argv.json").read_text())
        self.assertEqual(p_argv[p_argv.index("-l") + 1], "15")
        # Verify temp run dir was removed and no commercial fallback called
        self.assertEqual(list(self.state_dir.glob("run-*")), [])
        self.assertEqual(self.fallback.bodies, [])
        # Log redaction: no query token or article text
        self.assertNotIn("SUPERSECRET", router.log.getvalue())
        self.assertNotIn("Extracted PDF text", router.log.getvalue())

    def test_happy_path_html_mit_browser_and_pandoc_fallback(self):
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {
            "markdown": "Just a moment...", "metadata": {"statusCode": 429},
        }})
        router = self._router(self._bridge(mode="all"))
        url = "https://www.cambridge.org/core/journals/jfm/article/test"
        reply, backend = self._post(router, "/v2/scrape", {"url": url, "formats": ["markdown", "html"]})
        self.assertEqual((reply.status, backend), (200, "mit-browser"))
        doc = reply.json()
        self.assertIn("Cambridge Markdown", doc["data"]["markdown"])
        self.assertIn("<h1>Title</h1>", doc["data"]["html"])
        self.assertNotIn("rawHtml", doc["data"])
        self.assertEqual(doc["data"]["metadata"]["title"], "Cambridge Paper")
        self.assertEqual(doc["data"]["metadata"]["proxyUsed"], "mit-bridge")
        self.assertIn("--sandbox", json.loads((self.log_dir / "pandoc_argv.json").read_text()))
        self.assertEqual(list(self.state_dir.glob("run-*")), [])

        # When pandoc fails, fall back cleanly to page.txt
        bad_pandoc = _write_exec(self.root / "bad_pandoc", f"#!{sys.executable}\nimport sys; sys.exit(1)\n")
        router2 = self._router(self._bridge(mode="all", pandoc_bin=bad_pandoc))
        reply2, backend2 = self._post(router2, "/v2/scrape", {"url": url})
        self.assertEqual((reply2.status, backend2), (200, "mit-browser"))
        doc2 = reply2.json()
        self.assertIn("Fallback plain text", doc2["data"]["markdown"])
        self.assertIn("plain text fallback", doc2["data"]["warning"])
        self.assertNotIn("html", doc2["data"])

    def test_working_mit_html_stays_on_primary(self):
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {
            "markdown": "# Nature HTML Article\n\n" + ("Full text. " * 200),
            "metadata": {"statusCode": 200, "contentType": "text/html"},
        }})
        router = self._router(self._bridge(mode="all"))
        reply, backend = self._post(router, "/v2/scrape", {"url": "https://www.nature.com/articles/nature14539"})
        self.assertEqual((reply.status, backend), (200, "primary"))
        self.assertFalse((self.log_dir / "fetch_argv.json").exists())
        self.assertFalse((self.log_dir / "browser_argv.json").exists())

    def test_fetch_botwall_falls_through_to_browser_pdf_in_all_mode(self):
        wall_fetch = _write_exec(self.root / "wall_fetch.py", f"""#!{sys.executable}
import json
print(json.dumps({{"verdict": "enrolled", "mit": {{"class": "botwall", "status": 403, "content_is_pdf": False}}, "evidence": {{"mit_body": None}}}}))
""")
        router = self._router(self._bridge(mode="all", fetch_bin=wall_fetch))
        reply, backend = self._post(router, "/v2/scrape", {
            "url": "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S0022112067000400",
        })
        self.assertEqual((reply.status, backend), (200, "mit-browser"))
        self.assertIn("Extracted PDF text", reply.json()["data"]["markdown"])
        self.assertIn("--artifact", json.loads((self.log_dir / "browser_argv.json").read_text()))

    def test_fail_closed_errors_and_process_group_kill_and_no_commercial_fallback(self):
        # 1. Timeout kills child + grandchild process group
        pid_file = self.root / "grandchild.pid"
        hang_fetch = _write_exec(self.root / "hang_fetch.py", f"""#!{sys.executable}
import subprocess, sys, time
from pathlib import Path
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
Path({str(pid_file)!r}).write_text(str(p.pid))
time.sleep(30)
""")
        router = self._router(self._bridge(mode="pdf", fetch_bin=hang_fetch, fetch_kill_timeout=0.4))
        reply, backend = self._post(router, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual(backend, "primary")
        self.assertEqual(reply.headers.get("X-Firecrawl-MIT-Bridge"), "skipped:fetch-timeout")
        self.assertEqual(self.fallback.bodies, [])  # enrolled URL NEVER goes to commercial fallback
        self.assertEqual(list(self.state_dir.glob("run-*")), [])
        if pid_file.exists():
            gpid = int(pid_file.read_text())
            time.sleep(0.1)
            with self.assertRaises(ProcessLookupError):
                self._os.kill(gpid, 0)

        # 2. Oversized PDF (> 32 MiB) & non-PDF magic & path traversal
        escape_fetch = _write_exec(self.root / "escape_fetch.py", f"""#!{sys.executable}
import json
print(json.dumps({{"verdict": "enrolled", "mit": {{"class": "ok", "content_is_pdf": True}}, "evidence": {{"mit_body": "/etc/passwd"}}}}))
""")
        router_esc = self._router(self._bridge(mode="pdf", fetch_bin=escape_fetch))
        reply, backend = self._post(router_esc, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:path-escape"))

        bad_pdf_fetch = _write_exec(self.root / "bad_pdf_fetch.py", f"""#!{sys.executable}
import json, sys
from pathlib import Path
out_dir = Path(sys.argv[sys.argv.index("--output") + 1])
p = out_dir / "mit.body"
p.write_bytes(b"<html>not a pdf</html>")
print(json.dumps({{"verdict": "enrolled", "mit": {{"class": "ok", "content_is_pdf": True}}, "evidence": {{"mit_body": str(p)}}}}))
""")
        router_np = self._router(self._bridge(mode="pdf", fetch_bin=bad_pdf_fetch))
        reply, backend = self._post(router_np, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:not-pdf-magic"))

        # 3. Tunnel down fails fast (<1s) without spawning browserfetch
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {"markdown": "wall", "metadata": {"statusCode": 429}}})
        router_td = self._router(self._bridge(mode="all", socks_port=9))
        reply, backend = self._post(router_td, "/v2/scrape", {"url": "https://www.cambridge.org/core/article"})
        self.assertEqual((backend, reply.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:tunnel-down"))
        self.assertFalse((self.log_dir / "browser_argv.json").exists())
        # Second hit within 60s hits cooldown
        reply2, backend2 = self._post(router_td, "/v2/scrape", {"url": "https://www.cambridge.org/core/article2"})
        self.assertEqual((backend2, reply2.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:cooldown"))

    def test_concurrency_semaphore_isolation(self):
        self.primary.reply = lambda b, p: (
            (200, {"success": True, "data": {"markdown": "wall", "metadata": {"statusCode": 429}}})
            if "cambridge.org" in b.get("url", "")
            else (200, {"success": True, "data": {"markdown": "ok", "metadata": {"statusCode": 200}}})
        )
        bridge = self._bridge(mode="all", max_browser=1, browser_sem_timeout=0.05)
        router = self._router(bridge, with_fallback=False)
        # Hold the single browser semaphore slot
        self.assertTrue(bridge.browser_sem.acquire(blocking=False))
        try:
            r_busy, b_busy = self._post(router, "/v2/scrape", {"url": "https://www.cambridge.org/core/article"})
            self.assertEqual((b_busy, r_busy.headers.get("X-Firecrawl-MIT-Bridge")), ("primary", "skipped:busy"))
            # Concurrent non-enrolled request still succeeds on primary immediately
            r_other, b_other = self._post(router, "/v2/scrape", {"url": "https://example.com/page"})
            self.assertEqual((r_other.status, b_other), (200, "primary"))
        finally:
            bridge.browser_sem.release()

    def test_subprocess_env_is_scrubbed(self):
        real_home = "/tmp/operator-home"
        secrets_env = {
            "HOME": real_home,
            "FIRECRAWL_SELFHOST_API_KEY": "secret-hyades",
            "FIRECRAWL_API_KEY": "secret-commercial",
            "FIRECRAWL_ROUTER_SIPB_KEY": "secret-sipb",
            "FIRECRAWL_ROUTER_LITELLM_KEY": "secret-litellm",
            "SSH_AUTH_SOCK": "/tmp/fake-ssh.sock",
        }
        with unittest.mock.patch.dict(self._os.environ, secrets_env):
            router = self._router(self._bridge(mode="all"))
            self._post(router, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
            self.primary.reply = lambda b, p: (200, {"success": True, "data": {"markdown": "wall", "metadata": {"statusCode": 429}}})
            self._post(router, "/v2/scrape", {"url": "https://www.cambridge.org/core/article"})

        for name, allow_ssh, isolate_home in (
            ("fetch_env.json", True, False),
            ("browser_env.json", False, True),
            ("pdftotext_env.json", False, True),
            ("pandoc_env.json", False, True),
        ):
            env = json.loads((self.log_dir / name).read_text())
            for k in ("FIRECRAWL_SELFHOST_API_KEY", "FIRECRAWL_API_KEY",
                      "FIRECRAWL_ROUTER_SIPB_KEY", "FIRECRAWL_ROUTER_LITELLM_KEY"):
                self.assertNotIn(k, env, (name, k))
            self.assertNotIn("secret-", json.dumps(env), name)
            if allow_ssh:
                self.assertEqual(env.get("SSH_AUTH_SOCK"), "/tmp/fake-ssh.sock")
            else:
                self.assertNotIn("SSH_AUTH_SOCK", env, name)
            if isolate_home:
                self.assertEqual(env.get("HOME"), env.get("TMPDIR"), name)
                self.assertNotEqual(env.get("HOME"), real_home, name)
            else:
                self.assertEqual(env.get("HOME"), real_home, name)

    def test_llm_query_on_bridged_content_uses_normal_extractor_ladder(self):
        # Operator ruling 2026-11-22: no SIPB-only guard; normal sipb -> litellm ladder runs on bridged content.
        llm_sipb = Backend2(lambda b, p: (500, {"error": "sipb down"}))
        llm_lite = Backend2(lambda b, p: llm_ok("answer from litellm"))
        self.addCleanup(llm_sipb.close)
        self.addCleanup(llm_lite.close)
        ex = fr.Extractor([
            fr.Rung("sipb", llm_sipb.base, "ks", "qwen", 10_000, 5_000, check_truncation=True),
            fr.Rung("gemini-free", llm_lite.base, "kl", "gemini-free", 600_000, 400_000),
        ], deadline=30, call_timeout=5)
        router = self._router(self._bridge(mode="pdf"), extractor=ex)
        reply, backend = self._post(router, "/v2/scrape", {
            "url": "https://www.nature.com/articles/x.pdf",
            "formats": [{"type": "query", "prompt": "summary?"}],
        })
        self.assertEqual((reply.status, backend), (200, "mit-fetch"))
        self.assertEqual(reply.headers.get("X-Firecrawl-LLM"), "gemini-free")
        self.assertEqual(reply.json()["data"]["answer"], "answer from litellm")

    def test_startup_sweeps_orphan_run_dirs_only(self):
        self.state_dir.mkdir(mode=0o700, parents=True)
        orphan = self.state_dir / "run-orphan"
        orphan.mkdir(mode=0o700)
        (orphan / "stale.pdf").write_bytes(b"%PDF")
        old = time.time() - 900
        self._os.utime(orphan, (old, old))
        active = self.state_dir / "run-active"
        active.mkdir(mode=0o700)
        (active / "live.pdf").write_bytes(b"%PDF")
        keep = self.state_dir / "keep.txt"
        keep.write_text("keep")
        _ = self._bridge(mode="pdf")
        self.assertFalse(orphan.exists())
        self.assertTrue(active.exists())
        self.assertTrue(keep.exists())

    def test_single_snapshot_load_and_non_enrolled_header_hygiene(self):
        # F3: snapshot.load() called once per request; healthy non-enrolled scrapes get no bridge header;
        # stale snapshot is logged clearly even on non-enrolled scrapes.
        bridge = self._bridge(mode="pdf")
        router = self._router(bridge, with_fallback=False)
        with unittest.mock.patch.object(bridge.snapshot, "load", wraps=bridge.snapshot.load) as spy:
            reply, backend = self._post(router, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual((reply.status, backend), (200, "mit-fetch"))
        self.assertEqual(spy.call_count, 1)

        # Healthy non-enrolled scrape with valid snapshot or mixed-case URL: no X-Firecrawl-MIT-Bridge header.
        self.primary.reply = lambda b, p: (200, {"success": True, "data": {
            "markdown": "# Example\n\nReal content.", "metadata": {"statusCode": 200},
        }})
        for url in ("https://example.com/page", "https://GitHub.com/foo"):
            r_ok, b_ok = self._post(router, "/v2/scrape", {"url": url})
            self.assertEqual((r_ok.status, b_ok), (200, "primary"), url)
            self.assertNotIn("X-Firecrawl-MIT-Bridge", r_ok.headers, url)

        # Stale snapshot: logged on primary, no header on healthy 200 example.com, header on failing scrape.
        stale = self.root / "stale_log.json"
        stale.write_bytes(_make_snapshot_bytes(["www.nature.com"]))
        stale.chmod(0o600)
        old = time.time() - 8 * 86400
        self._os.utime(stale, (old, old))
        router_stale = self._router(self._bridge(mode="pdf", snapshot_path=str(stale)), with_fallback=False)
        r_healthy, _ = self._post(router_stale, "/v2/scrape", {"url": "https://example.com/ok"})
        self.assertNotIn("X-Firecrawl-MIT-Bridge", r_healthy.headers)
        self.assertIn("mit-bridge skipped:snapshot-stale", router_stale.log.getvalue())

    def test_stdout_cap_kills_stubborn_grandchild_in_process_group(self):
        # F4: leader exits on SIGTERM while grandchild ignores SIGTERM; SIGKILL reaps grandchild cleanly.
        mb = fr._MIT_BRIDGE_MOD
        pid_file = self.root / "stubborn.pid"
        flooder = _write_exec(self.root / "flooder.py", f"""#!{sys.executable}
import signal, subprocess, sys, time
from pathlib import Path
p = subprocess.Popen([sys.executable, "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
Path({str(pid_file)!r}).write_text(str(p.pid))
sys.stdout.write("A" * 200000)
sys.stdout.flush()
time.sleep(5)
""")
        res = mb.run_bounded(
            [sys.executable, "-E", "-s", flooder],
            env=mb.scrubbed_env(),
            timeout=5.0,
            max_stdout=4096,
            kill_on_stdout_cap=True,
        )
        self.assertTrue(res.stdout_truncated)
        self.assertEqual(len(res.stdout), 4096)
        gpid = int(pid_file.read_text())
        time.sleep(0.15)
        with self.assertRaises(ProcessLookupError):
            self._os.kill(gpid, 0)

    def test_header_injection_in_subprocess_class_is_normalized(self):
        # F6: CR/LF or arbitrary text in subprocess class normalizes to "unknown".
        bad_fetch = _write_exec(self.root / "inj_fetch.py", f"""#!{sys.executable}
import json
print(json.dumps({{"verdict": "enrolled", "mit": {{"class": "bad\\r\\nInjected: 1", "content_is_pdf": False}}, "evidence": {{"mit_body": None}}}}))
""")
        router = self._router(self._bridge(mode="pdf", fetch_bin=bad_fetch), with_fallback=False)
        reply, backend = self._post(router, "/v2/scrape", {"url": "https://www.nature.com/articles/x.pdf"})
        self.assertEqual(backend, "primary")
        hdr = reply.headers.get("X-Firecrawl-MIT-Bridge", "")
        self.assertEqual(hdr, "skipped:fetch-not-pdf-unknown")
        self.assertNotIn("\r", hdr)
        self.assertNotIn("\n", hdr)

    def test_cooldown_validation_and_missing_bridge_module_warning(self):
        # F8: non-finite/out-of-range cooldown falls back to default; missing module logs warning.
        mb = fr._MIT_BRIDGE_MOD
        for bad_cd in ("inf", "-inf", "nan", "-5", "99999"):
            b = mb.build_mit_bridge({
                "FIRECRAWL_ROUTER_MIT_BRIDGE": "pdf",
                "FIRECRAWL_ROUTER_MIT_SNAPSHOT": str(self.snap),
                "FIRECRAWL_ROUTER_MIT_STATE_DIR": str(self.state_dir),
                "FIRECRAWL_ROUTER_MIT_COOLDOWN_S": bad_cd,
            }, log=io.StringIO())
            self.assertEqual(b.config.cooldown_s, mb.DEFAULT_COOLDOWN_S, bad_cd)

        err = io.StringIO()
        with unittest.mock.patch.object(fr, "_MIT_BRIDGE_MOD", None), unittest.mock.patch.object(sys, "stderr", err):
            r = fr.build_router({
                "FIRECRAWL_SELFHOST_URL": self.primary.base,
                "FIRECRAWL_ROUTER_MIT_BRIDGE": "pdf",
                "FIRECRAWL_ROUTER_MIT_SNAPSHOT": str(self.snap),
            }, "")
        self.assertIsNone(r.mit_bridge)
        self.assertIn("firecrawl_mit_bridge.py is missing", err.getvalue())

        err2 = io.StringIO()
        with unittest.mock.patch.object(fr, "_OA_FALLBACK_MOD", None), unittest.mock.patch.object(sys, "stderr", err2):
            r2 = fr.build_router({
                "FIRECRAWL_SELFHOST_URL": self.primary.base,
                "FIRECRAWL_ROUTER_OA_FALLBACK": "allowlist",
            }, "")
        self.assertIsNone(r2.oa_fallback)
        self.assertIn("firecrawl_oa_fallback.py is missing", err2.getvalue())


if __name__ == "__main__":
    unittest.main()
