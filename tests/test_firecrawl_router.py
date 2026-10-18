"""bin/firecrawl-router: fallback rules, job pinning, link rewriting, the child token."""
import http.server
import importlib.machinery
import importlib.util
import io
import json
import sys
import threading
import unittest
import urllib.error
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
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "http://a/", "FIRECRAWL_API_KEY": "k"}, "")
        self.assertEqual((r.primary.base, r.fallback.base), ("http://a", "https://api.firecrawl.dev"))
        r = fr.build_router({"FIRECRAWL_SELFHOST_URL": "http://a", "FIRECRAWL_API_KEY": "k",
                             "FIRECRAWL_ROUTER_FALLBACK": "off"}, "")
        self.assertIsNone(r.fallback)

    def test_timeout_follows_request(self):
        self.assertEqual(fr.request_timeout(b'{"timeout": 200000}', 120), 230)
        self.assertEqual(fr.request_timeout(b'{"url": "u"}', 120), 120)


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
        self.page = "word " * 400
        self.llm_a.reply = lambda b, p: llm_ok("wrong, saw 10 tokens", ptok=10)
        r, doc = self.scrape(self.router(trunc=True), {"url": "u", "formats": [{"type": "query", "prompt": "q"}]})
        self.assertEqual(doc["data"]["answer"], "lean (b)")
        self.assertEqual(r.headers["X-Firecrawl-LLM"], "big")

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


if __name__ == "__main__":
    unittest.main()
