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
                    "FIRECRAWL_ROUTER_LITELLM_KEY": "litellm-secret", "FIRECRAWL_ROUTER_GITHUB_KEY": "github-secret"}
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


class GitHubFake:
    """A canned GitHub search API: handler(endpoint, q) -> (status, headers, doc); every call is recorded."""

    def __init__(self, handler):
        self.calls = []
        gh = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(url.query)["q"][0]
                gh.calls.append((url.path, q, self.headers.get("Authorization")))
                status, headers, doc = handler(url.path.rsplit("/", 1)[-1], q)
                body = json.dumps(doc).encode()
                self.send_response(status)
                for k, v in {"Content-Type": "application/json", **headers}.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def gh_issue(repo, n, title, body="", state="closed", pr=False):
    item = {"html_url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{n}", "title": title, "number": n,
            "repository_url": f"https://api.github.com/repos/{repo}", "state": state, "body": body,
            "updated_at": "2026-10-20T00:00:00Z"}
    if pr:
        item["pull_request"] = {"merged_at": "2026-10-20T00:00:00Z"}
    return item


def gh_file(repo, path, fragment, private=False):
    return {"html_url": f"https://github.com/{repo}/blob/abc/{path}", "path": path, "name": path.rsplit("/", 1)[-1],
            "repository": {"full_name": repo, "private": private},
            "text_matches": [{"property": "content", "fragment": fragment}]}


class DeveloperSearchTest(unittest.TestCase):
    """/v2/search/developer and categories ["developer"], answered from GitHub when there is no commercial fallback."""

    def start(self, handler, fallback=False, token="ghp-test-token", secretspec=None):
        self.gh, self.p, self.f = GitHubFake(handler), Fake(), Fake()
        kw = {"token": token} if secretspec is None else {"secretspec": secretspec}
        dev = fr.DevSearch(self.gh.base, timeout=5, **kw)
        self.log = io.StringIO()
        self.router = fr.Router(fr.Backend("primary", self.p.base, "pk"),
                                fr.Backend("fallback", self.f.base, "fk") if fallback else None,
                                timeout=5, token="", log=self.log, dev=dev)
        self.srv = fr.serve(self.router, "127.0.0.1:0")
        self.addCleanup(lambda: (self.srv.shutdown(), self.gh.close(), self.p.close(), self.f.close()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.router.public_base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.headers, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, e.headers, json.loads(e.read())

    @staticmethod
    def normal(endpoint, q):
        if endpoint == "code":
            return 200, {}, {"items": [gh_file("o/lib", "README.md", "# lib"), gh_file("o/lib", "docs/state.md", "state doc"),
                                       gh_file("o/lib", "src/proto.go", "func Proto() {}")]}
        if "is:pr" in q:
            return 200, {}, {"items": [gh_issue("o/lib", 7, "Fix state", "the fix", pr=True)]}
        return 200, {}, {"items": [gh_issue("o/lib", 3, "State bug", "it breaks", state="open")]}

    def test_ranked_results_in_firecrawl_shape(self):
        self.start(self.normal)
        status, headers, doc = self.call("GET", "/v2/search/developer?query=how+do+I+fix+state+protocol&k=10")
        self.assertEqual((status, headers["X-Firecrawl-Backend"]), (200, "github"))
        self.assertEqual(doc["source"], "github")
        # round-robin across kinds in a fixed order, one result of each kind first
        self.assertEqual([r["id"] for r in doc["results"]],
                         ["readme:o/lib", "doc:o/lib:docs/state.md", "pull_request:o/lib#7",
                          "issue:o/lib#3", "code:o/lib:src/proto.go"])
        pr = doc["results"][2]
        self.assertEqual((pr["type"], pr["title"]), ("pull_request", "Fix state"))
        self.assertIn("merged", pr["passages"][0]["text"])
        self.assertEqual(doc["coverage"], {"issue": "ok", "pull_request": "ok", "readme": "ok", "doc": "ok", "code": "ok"})
        self.assertEqual(self.p.seen, [])  # the primary never saw it
        queries = {c[0].rsplit("/", 1)[-1] + ("-pr" if "is:pr" in c[1] else ""): c[1] for c in self.gh.calls}
        self.assertIn("is:pr is:merged", queries["issues-pr"])
        self.assertIn("is:issue", queries["issues"])
        self.assertEqual(queries["code"], "fix state protocol")  # stopwords dropped
        self.assertEqual({c[2] for c in self.gh.calls}, {"Bearer ghp-test-token"})

    def test_k_caps_results_and_unsupported_filters_are_refused(self):
        self.start(self.normal)
        _, _, doc = self.call("GET", "/v2/search/developer?query=state&k=2")
        self.assertEqual(len(doc["results"]), 2)
        status, _, err = self.call("GET", "/v2/search/developer?query=state&license=MIT")
        self.assertEqual(status, 400)
        self.assertIn("license", err["error"])
        status, _, _ = self.call("POST", "/v2/search/developer", {"query": "state", "types": ["issue"], "repos": ["no-slash"]})
        self.assertEqual(status, 400)

    def test_a_query_cannot_smuggle_in_a_github_qualifier(self):
        self.start(self.normal)
        self.call("POST", "/v2/search/developer", {"query": "repo:victim/private user:x OR is:pr secret"})
        for _, q, _ in self.gh.calls:
            self.assertNotIn("repo:victim", q)
            self.assertNotIn("user:", q)
            self.assertNotIn(" OR ", q)

    def test_zero_hits_retry_once_with_fewer_terms(self):
        # GitHub ANDs every term: a four-word question finds nothing until half the terms are dropped
        self.start(lambda e, q: (200, {}, {"items": [] if "beta" in q else [gh_issue("o/lib", 1, "hit")]}))
        status, _, doc = self.call("POST", "/v2/search/developer", {"query": "alpha beta gamma delta", "types": ["issue"]})
        self.assertEqual(status, 200)
        self.assertEqual([q for _, q, _ in self.gh.calls],
                         ["alpha beta gamma delta is:issue is:public", "alpha gamma is:issue is:public"])
        self.assertEqual([r["id"] for r in doc["results"]], ["issue:o/lib#1"])

    def test_closed_code_bucket_degrades_then_stays_closed_until_reset(self):
        def handler(endpoint, q):
            if endpoint == "code":
                return 403, {"Retry-After": "60", "X-RateLimit-Remaining": "0"}, {"message": "API rate limit exceeded"}
            return self.normal(endpoint, q)
        self.start(handler)
        status, _, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual(status, 200)
        self.assertEqual({r["type"] for r in doc["results"]}, {"issue", "pull_request"})
        self.assertEqual((doc["coverage"]["doc"], doc["coverage"]["issue"]), ("unavailable", "ok"))
        self.assertIn("code:", doc["warning"])
        before = sum(1 for p, _, _ in self.gh.calls if p.endswith("/code"))
        self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual(sum(1 for p, _, _ in self.gh.calls if p.endswith("/code")), before)  # no second call into a closed bucket

    def test_everything_rate_limited_is_a_429_with_retry_after(self):
        self.start(lambda e, q: (403, {"Retry-After": "42"}, {"message": "secondary rate limit"}))
        status, headers, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual(status, 429)
        self.assertEqual(headers["Retry-After"], "42")
        self.assertFalse(doc["success"])

    def test_failures_without_a_rate_limit_are_a_502(self):
        self.start(lambda e, q: (401, {}, {"message": "Bad credentials"}))
        status, _, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual(status, 502)
        self.assertIn("HTTP 401", doc["error"])

    def test_search_category_returns_web_results(self):
        self.start(self.normal)
        status, _, doc = self.call("POST", "/v2/search", {"query": "state", "categories": ["developer"], "limit": 2})
        self.assertEqual(status, 200)
        web = doc["data"]["web"]
        self.assertEqual([w["position"] for w in web], [1, 2])
        self.assertEqual({w["category"] for w in web}, {"developer"})
        self.assertTrue(all(w["url"].startswith("https://github.com/") for w in web))

    def test_other_searches_still_go_to_the_primary(self):
        self.start(self.normal)
        self.p.routes[("POST", "/v2/search")] = (200, {"success": True, "data": {"web": [{"url": "https://x"}]}})
        for body in ({"query": "q"}, {"query": "q", "categories": ["research"]}, {"query": "q", "categories": ["developer", "gov"]}):
            self.call("POST", "/v2/search", body)
        self.assertEqual(len(self.p.seen), 3)
        self.assertEqual(self.gh.calls, [])

    def test_a_commercial_fallback_keeps_its_own_index(self):
        self.start(self.normal, fallback=True)
        self.f.routes[("GET", "/v2/search/developer")] = (200, {"success": True, "results": [{"id": "issue:a/b#1"}]})
        status, headers, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual((status, headers["X-Firecrawl-Backend"], doc["results"][0]["id"]), (200, "fallback", "issue:a/b#1"))
        self.assertEqual(self.gh.calls, [])

    def test_token_comes_from_secretspec_once_and_never_reaches_a_log_or_reply(self):
        import os
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            counter, script = Path(d) / "count", Path(d) / "sudo-secretspec"
            script.write_text(f"#!/bin/sh\necho x >> {counter}\n"
                              f'[ "$1 $2" = "get GITHUB_TOKEN" ] && printf "%s\\n" ghp-from-vault\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            self.start(self.normal, secretspec=str(script))
            _, _, doc = self.call("GET", "/v2/search/developer?query=state")
            self.call("GET", "/v2/search/developer?query=state+again")
            self.assertEqual(counter.read_text().count("x"), 1)
        self.assertEqual({c[2] for c in self.gh.calls}, {"Bearer ghp-from-vault"})
        self.assertNotIn("ghp-from-vault", self.log.getvalue() + json.dumps(doc))

    def test_private_repositories_never_come_back(self):
        # the token is a classic PAT that reads private repositories: issue queries say is:public, and a code hit
        # counts only when GitHub reports its repository as not private (a missing flag is not public)
        def handler(endpoint, q):
            if endpoint == "code":
                leaked = gh_file("me/secret", "notes.md", "private text", private=True)
                unknown = {**gh_file("me/unknown", "notes.md", "unknown"), "repository": {"full_name": "me/unknown"}}
                return 200, {}, {"items": [leaked, unknown, gh_file("o/lib", "docs/a.md", "public text")]}
            return self.normal(endpoint, q)
        self.start(handler)
        _, _, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertNotIn("me/", json.dumps(doc))
        self.assertIn("doc:o/lib:docs/a.md", [r["id"] for r in doc["results"]])
        for path, q, _ in self.gh.calls:
            if path.endswith("/issues"):
                self.assertIn("is:public", q)

    def test_an_empty_answer_at_the_rate_limit_is_still_a_200(self):
        # the last request of the minute returns 0 hits and closes the bucket, so the fewer-terms retry is refused:
        # that is "nothing found", not "rate limited"
        self.start(lambda e, q: (200, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 50)},
                                 {"items": []}))
        status, _, doc = self.call("GET", "/v2/search/developer?query=alpha+beta+gamma+delta")
        self.assertEqual((status, doc["results"]), (200, []))

    def test_non_ascii_terms_survive_and_oversized_queries_fit_githubs_limit(self):
        self.start(self.normal)
        self.call("POST", "/v2/search/developer", {"query": "naïve café 東京エラー", "types": ["issue"]})
        self.assertEqual(self.gh.calls[0][1], "naïve café 東京エラー is:issue is:public")
        self.gh.calls.clear()
        self.call("POST", "/v2/search/developer", {"query": " ".join(["w" * 200] * 8), "repos": ["a/" + "b" * 30] * 3})
        self.assertTrue(self.gh.calls)
        self.assertTrue(all(len(q) <= 256 for _, q, _ in self.gh.calls))
        status, _, err = self.call("POST", "/v2/search/developer", {"query": "x1", "repos": ["a/" + "b" * 30] * 6})
        self.assertEqual(status, 400)
        self.assertIn("repos is too long", err["error"])

    def test_malformed_upstream_items_are_skipped(self):
        self.start(lambda e, q: (200, {}, {"items": ["oops", None, {"html_url": "https://github.com/o/r/issues/1", "title": "ok",
                                                                    "number": 1, "repository_url": "https://api.github.com/repos/o/r",
                                                                    "text_matches": ["x", None]}]}))
        status, _, doc = self.call("POST", "/v2/search/developer", {"query": "state", "types": ["issue"]})
        self.assertEqual((status, [r["id"] for r in doc["results"]]), (200, ["issue:o/r#1"]))

    def test_readme_and_doc_classification(self):
        files = [gh_file("o/lib", "README.md", "a"), gh_file("o/lib", "pkg/README", "b"), gh_file("o/lib", "readme_parser.py", "c"),
                 gh_file("o/lib", "docs/guide.rst", "d"), gh_file("o/lib", "src/x.go", "e")]
        self.start(lambda e, q: (200, {}, {"items": files if e == "code" else []}))
        _, _, doc = self.call("GET", "/v2/search/developer?query=state&k=10")
        self.assertEqual({r["id"]: r["type"] for r in doc["results"]},
                         {"readme:o/lib": "readme", "readme:o/lib:pkg/README": "readme", "code:o/lib:readme_parser.py": "code",
                          "doc:o/lib:docs/guide.rst": "doc", "code:o/lib:src/x.go": "code"})

    def test_repos_scope_applies_to_docs_and_bad_numbers_are_refused(self):
        self.start(self.normal)
        status, _, _ = self.call("POST", "/v2/search/developer", {"query": "state", "types": ["doc"], "repos": ["o/lib"]})
        self.assertEqual(status, 200)
        self.assertIn("repo:o/lib", self.gh.calls[0][1])
        for bad in ({"k": True}, {"k": 0}, {"k": 101}, {"passages": 6}, {"min_stars": 0}, {"fork": 0}):
            status, _, _ = self.call("POST", "/v2/search/developer", {"query": "state", **bad})
            self.assertEqual(status, 400, bad)
        status, _, err = self.call("POST", "/v2/search", {"query": "state", "categories": ["developer"], "limit": 0})
        self.assertEqual(status, 400)
        self.assertIn("limit must", err["error"])

    def test_category_search_names_the_fields_it_ignores(self):
        self.start(self.normal)
        _, _, doc = self.call("POST", "/v2/search", {"query": "state", "categories": ["developer"],
                                                      "scrapeOptions": {"formats": ["markdown"]}, "tbs": "qdr:d"})
        self.assertIn("scrapeOptions, tbs", doc["warning"])

    def test_a_rejected_token_is_dropped_and_not_re_read_inside_a_minute(self):
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            counter, script = Path(d) / "count", Path(d) / "sudo-secretspec"
            script.write_text(f"#!/bin/sh\necho x >> {counter}\nprintf 'revoked\\n'\n")
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            self.start(lambda e, q: (401, {}, {"message": "Bad credentials"}), secretspec=str(script))
            self.call("GET", "/v2/search/developer?query=state")
            self.call("GET", "/v2/search/developer?query=state")
            self.assertEqual(counter.read_text().count("x"), 1)  # the second search ran unauthenticated, no new read
        self.assertIn(None, {c[2] for c in self.gh.calls})

    def test_a_busy_router_answers_429_instead_of_queueing_forever(self):
        self.start(self.normal)
        self.router.dev.budget = 0.3
        for _ in range(fr.DEV_SLOTS):
            self.assertTrue(self.router.dev._slots.acquire(timeout=1))
        self.addCleanup(lambda: [self.router.dev._slots.release() for _ in range(fr.DEV_SLOTS)])
        status, headers, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual((status, headers["Retry-After"], doc["success"]), (429, "5", False))
        self.assertEqual(self.gh.calls, [])

    def test_numbers_must_be_integers_not_infinity_floats_or_null_limits(self):
        self.start(self.normal)
        for bad in ({"k": float("inf")}, {"k": 5.9}, {"passages": float("inf")}, {"k": [3]}):
            status, _, _ = self.call("POST", "/v2/search/developer", {"query": "state", **bad})
            self.assertEqual(status, 400, bad)
        status, _, _ = self.call("GET", "/v2/search/developer?query=state&k=3")  # a query string carries digits
        self.assertEqual(status, 200)
        status, _, _ = self.call("POST", "/v2/search", {"query": "state", "categories": ["developer"], "limit": None})
        self.assertEqual(status, 200)
        status, _, err = self.call("POST", "/v2/search", {"query": "state", "categories": ["developer"], "limit": 500})
        self.assertEqual((status, err["error"]), (400, "firecrawl-router: limit must be an integer 1-100"))

    def test_an_upstream_item_of_the_wrong_shape_is_skipped_not_fatal(self):
        bad = {**gh_file("o/lib", "docs/a.md", "x"), "repository": "o/lib"}
        self.start(lambda e, q: (200, {}, {"items": [bad, gh_file("o/lib", "docs/ok.md", "fine")] if e == "code" else []}))
        status, _, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual((status, [r["id"] for r in doc["results"]]), (200, ["doc:o/lib:docs/ok.md"]))

    def test_only_the_v2_routes_are_taken_over(self):
        self.start(self.normal)
        for path in ("/v1/search/developer?query=state", "/v3/search/developer?query=state"):
            status, _, _ = self.call("GET", path)
            self.assertEqual(status, 404)
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(len(self.p.seen), 2)

    def test_a_scoped_search_cannot_tell_a_missing_repo_from_an_empty_one(self):
        # GitHub answers 422 for a repo that does not exist (or that the token cannot see) and 200 with no items for an
        # existing one: both must look the same, and a scoped search never makes a second (fewer-terms) call
        self.start(lambda e, q: (422, {}, {"message": "Validation Failed"}))
        status, _, doc = self.call("POST", "/v2/search/developer",
                                   {"query": "alpha beta gamma delta", "repos": ["ghost/repo"]})
        self.assertEqual((status, doc["results"], doc["coverage"]["issue"], "warning" in doc), (200, [], "ok", False))
        self.assertEqual(len(self.gh.calls), 3)

    def test_no_token_runs_unauthenticated_and_says_so(self):
        self.start(self.normal, token="", secretspec="/nonexistent/sudo-secretspec")
        status, _, doc = self.call("GET", "/v2/search/developer?query=state")
        self.assertEqual(status, 200)
        self.assertEqual({c[2] for c in self.gh.calls}, {None})
        self.assertIn("no GitHub token", doc["warning"])


if __name__ == "__main__":
    unittest.main()
