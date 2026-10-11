"""Unit tests for bin/web-get: failover order, block-page detection, exit 5 when every provider
fails, usage errors, key redaction. A local stub HTTP server stands in for Exa (SSE MCP),
Parallel (JSON MCP), Jina (MCP, r.jina.ai, s.jina.ai) and the Wayback Machine; fake crwl and
composio scripts stand in for the CLIs. No network."""

from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "web-get"
_loader = importlib.machinery.SourceFileLoader("web_get", str(SCRIPT))
wg = importlib.util.module_from_spec(importlib.util.spec_from_loader("web_get", _loader))
_loader.exec_module(wg)

KEY = "jina_TESTKEY_0123456789abcdef"
ARTICLE = "This is the real article body. " * 40  # ~1240 chars
BLOCK = "<html><title>Just a moment...</title>Checking your browser before accessing.</html>" + " " * 300
# Verbatim from a live `web-get search ... --only exa` on 2026-10-11 (Exa's free tier, rc 0).
EXA_RATE_LIMIT = ("You've hit Exa's free MCP rate limit. To continue using without limits, create your "
                  "own Exa API key.\n\nFix: Create API key at https://dashboard.exa.ai/api-keys , and "
                  "then update Exa MCP URL to this https://mcp.exa.ai/mcp?exaApiKey=YOUR_EXA_API_KEY")

# provider -> mode; reset per test. Modes: ok, http500, iserror, rpcerror, empty, block, slow,
# ratelimit (Exa's verbatim notice as content), trickle (SSE pings, never a reply), sse-open
# (the reply, then the stream stays open with pings), capped (exa: a body of exactly
# maxCharacters), and for parallel's web_fetch: crosshost, rootredirect, soft404, wrongtitle
# (a missing zillow listing answered with the site's city page), samehost (a legit redirect).
# do_GET also has slow (sleep 3 s).
MODES: dict[str, str] = {}
ARGS: list[dict] = []
HITS: list[str] = []
PATHS: list[str] = []
AUTH_SEEN: list[str] = []


def _search_rows(tag: str) -> list[dict]:
    return [{"title": f"{tag} result {i}", "url": f"https://example.org/{tag}/{i}",
             "excerpts": [f"{tag} snippet {i} about the query"]} for i in range(1, 6)]


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: str, ctype: str = "application/json", hdrs=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (hdrs or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # ---- MCP
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        msg = json.loads(self.rfile.read(n) or b"{}")
        prov = self.path.strip("/").split("/")[0]  # exa | parallel | jinamcp
        AUTH_SEEN.append(self.headers.get("Authorization") or "")
        if "id" not in msg:  # notification
            self.send_response(202)
            self.end_headers()
            return
        mode = MODES.get(prov, "ok")
        sse = prov in ("exa", "jinamcp")
        if msg["method"] == "initialize":
            return self._rpc(msg["id"], {"protocolVersion": "2025-03-26", "capabilities": {}},
                             sse, {"Mcp-Session-Id": f"sid-{prov}"})
        HITS.append(f"{prov}:{msg['params']['name']}")
        if self.headers.get("Mcp-Session-Id") != f"sid-{prov}":
            return self._send(400, '{"error":"missing session"}')
        if mode == "slow":
            time.sleep(3)
        if mode in ("trickle", "sse-open"):
            return self._trickle(msg, mode == "sse-open")
        if mode == "http500":
            return self._send(500, "upstream exploded")
        if mode == "rpcerror":
            return self._rpc(msg["id"], None, sse, err={"code": -32602, "message": "bad params"})
        if mode == "iserror":
            return self._rpc(msg["id"], {"content": [{"type": "text", "text": "Error fetching URL(s): CRAWL_UNKNOWN_ERROR"}],
                                         "isError": True}, sse)
        tool, args = msg["params"]["name"], msg["params"]["arguments"]
        ARGS.append({"prov": prov, "tool": tool, **args})
        if prov == "parallel" and tool == "web_fetch" and mode in PARALLEL_PAGES:
            got, title = PARALLEL_PAGES[mode](args["urls"][0])
            text = json.dumps({"results": [{"url": got, "title": title,
                                            "full_content": "parallel-fetch " + ARTICLE}]})
            return self._rpc(msg["id"], {"content": [{"type": "text", "text": text}]}, sse)
        if mode == "empty":
            text = "" if prov != "parallel" else json.dumps({"results": [], "errors": [
                {"url": "x", "error_type": "connect_error", "http_status_code": None}]})
        elif mode == "block":
            text = BLOCK
        elif mode == "ratelimit":
            text = EXA_RATE_LIMIT
        elif tool in ("web_search_exa",):
            text = "\n\n---\n\n".join(f"Title: exa {i}\nURL: https://exa.example/{i}\nHighlights: hit"
                                     for i in range(args.get("numResults", 3)))
        elif tool == "web_search":
            text = json.dumps({"results": _search_rows("parallel")})
        elif tool == "web_fetch_exa" and mode == "capped":
            n = args["maxCharacters"]
            text = f"# page\nURL: {args['urls'][0]}\nPublished: 2026-10-11\n\n" + (ARTICLE * (n // len(ARTICLE) + 1))[:n]
        elif tool == "web_fetch_exa":
            text = f"Title: page\nURL: {args['urls'][0]}\n\nexa-fetch {ARTICLE}"
        elif tool == "web_fetch":
            text = json.dumps({"results": [{"url": args["urls"][0], "title": "P",
                                            "full_content": "parallel-fetch " + ARTICLE}]})
        elif tool == "search_web":
            if not self.headers.get("Authorization"):
                return self._send(401, '{"error":"unauthorized"}')
            return self._rpc(msg["id"], {"content": [
                {"type": "text", "text": f"title: jm {i}\nurl: https://jm.example/{i}\nsnippet: s"}
                for i in range(3)]}, sse)
        else:
            return self._rpc(msg["id"], None, sse, err={"code": -32601, "message": "no tool"})
        self._rpc(msg["id"], {"content": [{"type": "text", "text": text}]}, sse)

    def _trickle(self, msg, reply_first):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            if reply_first:
                tool = msg["params"]["name"]
                text = (f"Title: page\nURL: https://x.example/\n\nexa-fetch {ARTICLE}" if tool == "web_fetch_exa"
                        else "Title: exa 0\nURL: https://exa.example/0\n\n---\n\nTitle: exa 1\nURL: https://exa.example/1")
                obj = {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": text}]}}
                self.wfile.write(("event: message\ndata: " + json.dumps(obj) + "\n\n").encode())
                self.wfile.flush()
            for _ in range(60):  # ~30 s of keep-alive pings
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(0.5)
        except OSError:
            pass

    def _rpc(self, rid, result, sse, hdrs=None, err=None):
        obj = {"jsonrpc": "2.0", "id": rid}
        obj.update({"error": err} if err else {"result": result})
        if sse:
            self._send(200, "event: message\ndata: " + json.dumps(obj) + "\n\n", "text/event-stream", hdrs)
        else:
            self._send(200, json.dumps(obj), "application/json", hdrs)

    # ---- plain HTTP
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        parts = u.path.lstrip("/").split("/", 1)
        prov = parts[0]
        AUTH_SEEN.append(self.headers.get("Authorization") or "")
        HITS.append(f"{prov}:GET")
        PATHS.append(self.path)
        mode = MODES.get(prov, "ok")
        if mode == "slow":
            time.sleep(3)
        if mode == "http500":
            return self._send(500, "nope", "text/plain")
        if mode == "block":
            return self._send(200, BLOCK, "text/html")
        if mode == "empty":
            return self._send(200, "", "text/plain")
        if mode == "html404":
            return self._send(404, "<!DOCTYPE html><html><head><title>Wayback Machine</title>"
                                   "<script>/* @licstart */</script></head></html>", "text/html")
        if prov == "r":  # r.jina.ai/<target>
            target = parts[1] if len(parts) > 1 else ""
            if "web.archive" in target or "/wayback-web/" in target:
                return self._send(200, f"Title: archived\n\nwayback-via-jina {ARTICLE}", "text/plain")
            if "deadhost" in target:
                return self._send(200, "Warning: Target URL returned error 404: Not Found\n" + "x" * 300, "text/plain")
            return self._send(200, f"Title: t\nURL Source: {target}\n\njina-reader {ARTICLE}", "text/plain")
        if prov == "s":
            if not self.headers.get("Authorization"):
                return self._send(401, '{"code":401}')
            return self._send(200, json.dumps({"code": 200, "data": [
                {"title": f"sj {i}", "url": f"https://sj.example/{i}", "description": "d"} for i in range(4)]}))
        if prov == "wayback":
            q = urllib.parse.parse_qs(u.query).get("url", [""])[0]
            port = self.server.server_address[1]
            return self._send(200, json.dumps({"archived_snapshots": {"closest": {
                "available": True, "timestamp": "20260101000000",
                "url": f"http://127.0.0.1:{port}/wayback-web/web/20260101000000/{q}"}}}))
        if prov == "wayback-web":
            return self._send(200, f"<html><body><p>wayback-direct {ARTICLE}</p></body></html>", "text/html")
        self._send(404, "not found", "text/plain")


PARALLEL_PAGES = {
    "crosshost": lambda u: ("https://elsewhere.example/landing", "Landing"),
    "rootredirect": lambda u: (urllib.parse.urljoin(u, "/"), "Site home"),
    "soft404": lambda u: (u, "Page Not Found | Site"),
    "wrongtitle": lambda u: (u, "Anchorage AK Real Estate - Anchorage AK Homes For Sale | Zillow"),
    "samehost": lambda u: (urllib.parse.urljoin(u.replace("http://", "https://www.", 1), "/new/listing-moved"),
                           "Main Street listing (moved)"),
}


class StubServer(http.server.ThreadingHTTPServer):
    request_queue_size = 64  # `check` opens 10 connections at once; the default 5 drops some
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    srv = StubServer(("127.0.0.1", 0), Stub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def fakes(tmp_path):
    crwl = tmp_path / "crwl"
    crwl.write_text("#!/bin/sh\n"
                    'case "$CRWL_MODE" in fail) echo "Error: NoneType" >&2; exit 1;; '
                    'slow) sleep 5;; esac\n'
                    "printf 'crawl4ai-js %s\\n' \"$1\"; i=0; while [ $i -lt 30 ]; do "
                    "printf 'rendered javascript content line\\n'; i=$((i+1)); done\n")
    comp = tmp_path / "composio"
    comp.write_text("#!/bin/sh\n"
                    'if [ "$COMPOSIO_MODE" = fail ]; then echo "not connected" >&2; exit 1; fi\n'
                    "echo '{\"successful\": true, \"data\": {\"results\": [{\"title\": \"ddg 1\", "
                    "\"link\": \"https://ddg.example/1\", \"snippet\": \"duck snippet\"}]}}'\n")
    for p in (crwl, comp):
        p.chmod(0o755)
    return {"crwl": str(crwl), "composio": str(comp)}


@pytest.fixture(autouse=True)
def reset():
    MODES.clear()
    HITS.clear()
    PATHS.clear()
    AUTH_SEEN.clear()
    ARGS.clear()


def _env(server, fakes, key=True, extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("WEB_GET_", "JINA_"))}
    e.update({
        "WEB_GET_EXA_URL": f"{server}/exa/mcp", "WEB_GET_PARALLEL_URL": f"{server}/parallel/mcp",
        "WEB_GET_JINA_MCP_URL": f"{server}/jinamcp/v1", "WEB_GET_JINA_READER_URL": f"{server}/r",
        "WEB_GET_JINA_SEARCH_URL": f"{server}/s", "WEB_GET_WAYBACK_API_URL": f"{server}/wayback/available",
        "WEB_GET_WAYBACK_WEB_URL": f"{server}/wayback-web", "WEB_GET_CRWL": fakes["crwl"],
        "WEB_GET_COMPOSIO": fakes["composio"], "WEB_GET_CHECK_URL": "https://example.com/",
        "WEB_GET_NO_SECRETSPEC": "1",
    })
    if key:
        e["JINA_API_KEY"] = KEY
    e.update(extra or {})
    return e


def run(server, fakes, *args, key=True, extra=None, timeout=60):
    e = _env(server, fakes, key, extra)
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=e, capture_output=True,
                       text=True, timeout=timeout)
    assert KEY not in p.stdout and KEY not in p.stderr, "Jina key leaked to output"
    return p


# ------------------------------------------------------------------ fetch ladder


def test_fetch_first_provider_wins(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a")
    assert p.returncode == 0, p.stderr
    assert "exa-fetch" in p.stdout
    assert "web-get: provider=exa url=https://site.example/a" in p.stderr
    assert not any(h.startswith("parallel") for h in HITS)


@pytest.mark.parametrize("mode", ["http500", "iserror", "rpcerror", "empty", "block"])
def test_fetch_exa_failure_modes_fall_to_parallel(server, fakes, mode):
    MODES["exa"] = mode
    p = run(server, fakes, "fetch", "https://site.example/a", "--json")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["provider"] == "parallel"
    assert [a["provider"] for a in out["attempts"]] == ["exa", "parallel"]
    assert out["attempts"][0]["ok"] is False and out["attempts"][0]["error"]
    if mode == "block":
        assert "block page" in out["attempts"][0]["error"]
    assert "parallel-fetch" in out["content"]


def test_fetch_full_order_to_wayback(server, fakes):
    MODES.update(exa="http500", parallel="empty", r="block")
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", "--verbose",
            extra={"CRWL_MODE": "fail"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert [a["provider"] for a in out["attempts"]] == ["exa", "parallel", "jina-reader", "crawl4ai", "wayback"]
    assert out["provider"] == "wayback"
    # r.jina.ai is in block mode, so the direct id_ snapshot is used
    assert "wayback-direct" in out["content"] and "Wayback Machine snapshot" in out["content"]
    assert "/wayback-web/web/20260101000000id_/" not in out["url"]  # provenance is the snapshot
    assert "try exa: FAIL" in p.stderr and "try wayback: ok" in p.stderr


def test_fetch_crawl4ai_after_jina_fails(server, fakes):
    MODES.update(exa="iserror", parallel="iserror", r="http500")
    p = run(server, fakes, "fetch", "https://js.example/", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "crawl4ai"
    assert "crawl4ai-js https://js.example/" in out["content"]


def test_fetch_only_crawl4ai(server, fakes):
    p = run(server, fakes, "fetch", "https://js.example/", "--only", "crwl")
    assert p.returncode == 0
    assert "web-get: provider=crawl4ai" in p.stderr
    assert HITS == []


def test_fetch_skip_list(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--skip", "exa,parallel", "--json")
    out = json.loads(p.stdout)
    assert out["provider"] == "jina-reader"
    assert f"Bearer {KEY}" in AUTH_SEEN  # key sent to reader when available


def test_fetch_jina_reader_keyless(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "jina-reader", key=False)
    assert p.returncode == 0 and "jina-reader" in p.stdout
    assert all(a == "" for a in AUTH_SEEN)


def test_fetch_target_error_page_is_failure(server, fakes):
    p = run(server, fakes, "fetch", "https://deadhost.example/", "--only", "jina-reader")
    assert p.returncode == 5
    assert "Target URL returned error 404" in p.stderr


def test_fetch_all_fail_exit_5_pause_message(server, fakes):
    MODES.update(exa="iserror", parallel="empty", r="http500", **{"wayback": "http500", "wayback-web": "http500"})
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", extra={"CRWL_MODE": "fail"})
    assert p.returncode == 5
    assert "ALL PROVIDERS FAILED" in p.stderr and "pause dependent work" in p.stderr
    for name in ("exa", "parallel", "jina-reader", "crawl4ai", "wayback"):
        assert f"{name}: " in p.stderr
    out = json.loads(p.stdout)
    assert out["ok"] is False and out["content"] is None and len(out["attempts"]) == 5


def test_fetch_timeout_moves_on(server, fakes):
    MODES["exa"] = "slow"
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--timeout", "1", "--json")
    out = json.loads(p.stdout)
    assert out["attempts"][0] == {**out["attempts"][0], "provider": "exa", "ok": False, "error": "timeout"}
    assert out["provider"] == "parallel"
    assert time.monotonic() - t0 < 10


def test_fetch_crwl_timeout_killed(server, fakes):
    p = run(server, fakes, "fetch", "https://js.example/", "--only", "crawl4ai", "--crwl-timeout", "1",
            extra={"CRWL_MODE": "slow"})
    assert p.returncode == 5 and "timeout" in p.stderr


def test_crwl_has_its_own_longer_timeout(server, fakes):
    # --timeout 1 applies to the HTTP providers only; crawl4ai keeps its own (longer) budget.
    p = run(server, fakes, "fetch", "https://js.example/", "--only", "crawl4ai", "--timeout", "1",
            extra={"CRWL_MODE": "slow", "WEB_GET_CRWL_TIMEOUT": "20"})
    assert p.returncode == 0, p.stderr
    assert "crawl4ai-js" in p.stdout


def test_sigterm_kills_crwl_child(server, fakes, tmp_path):
    pidfile = tmp_path / "crwl.pid"
    crwl = tmp_path / "crwl-hang"
    crwl.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 60\n")
    crwl.chmod(0o755)
    e = _env(server, fakes, extra={"WEB_GET_CRWL": str(crwl)})
    proc = subprocess.Popen([sys.executable, "-I", str(SCRIPT), "fetch", "https://js.example/",
                             "--only", "crawl4ai"], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 15
    while not (pidfile.exists() and pidfile.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.1)
    child = int(pidfile.read_text())
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 128 + signal.SIGTERM
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("crwl child survived SIGTERM to web-get")


def test_http_error_html_body_reduced_to_title(server, fakes):
    MODES["wayback-web"] = "html404"
    MODES.update(wayback="http500", r="http500")
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback")
    assert p.returncode == 5
    assert "HTTP 404: page 'Wayback Machine'" in p.stderr and "<script" not in p.stderr


def test_crwl_gets_js_delay(server, fakes, tmp_path):
    argv = tmp_path / "argv"
    crwl = tmp_path / "crwl-argv"
    crwl.write_text(f'#!/bin/sh\necho "$@" > {argv}\nyes content line | head -40\n')
    crwl.chmod(0o755)
    p = run(server, fakes, "fetch", "https://js.example/", "--only", "crawl4ai",
            extra={"WEB_GET_CRWL": str(crwl)})
    assert p.returncode == 0
    assert argv.read_text().split() == ["https://js.example/", "-o", "markdown", "-c",
                                        "delay_before_return_html=3"]


def test_fetch_max_bytes(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--max-bytes", "100")
    assert p.returncode == 0
    assert len(p.stdout.encode()) <= 101
    assert "truncated to 100 bytes" in p.stderr
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--max-bytes", "100",
                         "--json").stdout)
    assert out["truncated"] is True
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    assert out["truncated"] is False


def test_fetch_exa_rate_limit_notice_fails_over(server, fakes):
    MODES["exa"] = "ratelimit"
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    assert out["provider"] == "parallel"
    assert "rate-limit/quota" in out["attempts"][0]["error"]


def test_fetch_sse_trickle_respects_wall_clock_timeout(server, fakes):
    MODES["exa"] = "trickle"
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--timeout", "2", "--json")
    assert time.monotonic() - t0 < 15
    out = json.loads(p.stdout)
    assert out["attempts"][0]["provider"] == "exa" and "timeout" in out["attempts"][0]["error"]
    assert out["provider"] == "parallel"


def test_sse_stream_left_open_after_reply_is_not_a_hang(server, fakes):
    MODES["exa"] = "sse-open"
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "exa", "--timeout", "20")
    assert p.returncode == 0, p.stderr
    assert time.monotonic() - t0 < 10


def test_iri_url_is_encoded_for_jina_and_wayback(server, fakes):
    p = run(server, fakes, "fetch", "https://de.wikipedia.org/wiki/Köln", "--only", "jina-reader")
    assert p.returncode == 0, p.stderr
    assert any("K%C3%B6ln" in x for x in PATHS)
    PATHS.clear()
    MODES["r"] = "http500"
    p = run(server, fakes, "fetch", "https://de.wikipedia.org/wiki/Köln", "--only", "wayback")
    assert p.returncode == 0, p.stderr
    assert all(x.isascii() for x in PATHS)
    MODES.clear()
    p = run(server, fakes, "fetch", "https://site.example/a b[1]", "--only", "jina-reader")
    assert p.returncode == 0, p.stderr


# ------------------------------------------------------------------ search ladder


def test_search_exa_first(server, fakes):
    p = run(server, fakes, "search", "agents social network", "--n", "2")
    assert p.returncode == 0
    assert p.stdout.count("URL: https://exa.example/") == 2
    assert "web-get: provider=exa query=agents social network" in p.stderr


def test_search_order_to_composio(server, fakes):
    MODES.update(exa="rpcerror", parallel="http500", jinamcp="iserror", s="http500")
    p = run(server, fakes, "search", "q", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0
    assert [a["provider"] for a in out["attempts"]] == ["exa", "parallel", "jina-mcp", "jina-search", "composio"]
    assert "https://ddg.example/1" in out["content"]


def test_search_parallel_formats_results(server, fakes):
    p = run(server, fakes, "search", "q", "--only", "parallel", "--n", "3")
    assert p.returncode == 0
    assert p.stdout.count("URL: https://example.org/parallel/") == 3


def test_search_jina_needs_key(server, fakes):
    p = run(server, fakes, "search", "q", "--only", "jina", "--json", key=False,
            extra={"COMPOSIO_MODE": "fail"})
    out = json.loads(p.stdout)
    assert p.returncode == 5
    assert [a["provider"] for a in out["attempts"]] == ["jina-mcp", "jina-search"]
    assert all("no Jina key" in a["error"] for a in out["attempts"])


def test_search_jina_with_key(server, fakes):
    p = run(server, fakes, "search", "q", "--only", "jina-mcp")
    assert p.returncode == 0 and "https://jm.example/0" in p.stdout
    p = run(server, fakes, "search", "q", "--only", "jina-search")
    assert p.returncode == 0 and "https://sj.example/0" in p.stdout


def test_search_exa_rate_limit_notice_fails_over(server, fakes):
    MODES["exa"] = "ratelimit"
    p = run(server, fakes, "search", "q", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "parallel"
    assert "rate-limit/quota" in out["attempts"][0]["error"]
    p = run(server, fakes, "search", "q", "--only", "exa")
    assert p.returncode == 5 and "ALL PROVIDERS FAILED" in p.stderr


def test_search_sse_trickle_respects_wall_clock_timeout(server, fakes):
    MODES["exa"] = "trickle"
    t0 = time.monotonic()
    p = run(server, fakes, "search", "q", "--only", "exa", "--timeout", "2")
    assert p.returncode == 5 and "timeout" in p.stderr
    assert time.monotonic() - t0 < 15


def test_search_all_fail_exit_5(server, fakes):
    MODES.update(exa="empty", parallel="empty", jinamcp="http500", s="http500")
    p = run(server, fakes, "search", "q", extra={"COMPOSIO_MODE": "fail"})
    assert p.returncode == 5 and p.stdout == ""
    assert "ALL PROVIDERS FAILED" in p.stderr and "composio rc=1" in p.stderr


# ------------------------------------------------------------------ check, usage


def test_check_healthy(server, fakes):
    p = run(server, fakes, "check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert len([ln for ln in p.stdout.splitlines() if " ok " in ln]) == 10


def test_check_too_few_healthy(server, fakes):
    p = run(server, fakes, "check", "--only", "exa,parallel", "--json",
            extra={"WEB_GET_EXA_URL": "http://127.0.0.1:9/x"})
    out = json.loads(p.stdout)
    assert p.returncode == 5 and out["healthy"] == 2


def test_check_needs_search_and_fetch(server, fakes):
    p = run(server, fakes, "check", "--only", "exa,parallel,jina-mcp,jina-search,composio",
            "--skip", "", "--json", extra={"WEB_GET_CRWL": "/nonexistent/crwl"})
    # fetch-side exa and parallel still count, so this is healthy; now drop all fetch providers
    assert p.returncode == 0
    MODES.update(exa="http500", parallel="http500")
    p = run(server, fakes, "check", "--only", "exa,parallel,jina-mcp,jina-search,composio")
    assert p.returncode == 5  # 3 search providers healthy, no fetch provider


@pytest.mark.parametrize("args", [
    ["fetch", "ftp://x"], ["fetch", "notaurl"], ["search", "  "], ["search", "q", "--n", "0"],
    ["search", "q", "--only", "bogus"], ["fetch", "https://a.example", "--only", "composio"],
    ["search", "q", "--timeout", "0"], [],
])
def test_usage_errors_exit_2(server, fakes, args):
    p = run(server, fakes, *args)
    assert p.returncode == 2


# ------------------------------------------------------------------ pure functions


@pytest.mark.parametrize("text", [
    BLOCK, "Access Denied. You don't have permission. " + "x" * 300,
    "We do not support this site. " + "y" * 300, "Please complete the CAPTCHA to continue " + "z" * 300,
    "Attention Required! | Cloudflare " + "w" * 300,
])
def test_block_pages_detected(text):
    with pytest.raises(wg.ProviderError, match="block"):
        wg.check_fetch_content(text)


def test_long_article_mentioning_captcha_is_content():
    text = "An essay on why CAPTCHA systems fail. " + ARTICLE * 5
    assert wg.check_fetch_content(text)


@pytest.mark.parametrize("text", [
    EXA_RATE_LIMIT, "Rate limit reached for this key. " + "q" * 300,
    "Insufficient credits. Please upgrade your plan to continue. " + "c" * 300,
])
def test_quota_notices_detected(text):
    with pytest.raises(wg.ProviderError, match="rate-limit/quota"):
        wg.check_fetch_content(text)
    with pytest.raises(wg.ProviderError):
        wg.check_search_content(text)


def test_search_results_about_rate_limits_are_content():
    rows = [{"title": f"API rate limit design {i}", "url": f"https://ex.org/{i}",
             "snippet": "How to handle a quota, an API key and credits. " * 8} for i in range(8)]
    assert wg.check_search_content(wg.fmt_results(rows, 8))


def test_normalize_url():
    assert wg.normalize_url("https://de.wikipedia.org/wiki/Köln") == "https://de.wikipedia.org/wiki/K%C3%B6ln"
    assert wg.normalize_url("https://münchen.de/a b?x=ä&y=1") == "https://xn--mnchen-3ya.de/a%20b?x=%C3%A4&y=1"
    once = wg.normalize_url("https://ex.org/a%20b?q=%C3%A4")
    assert once == "https://ex.org/a%20b?q=%C3%A4" and wg.normalize_url(once) == once
    assert wg.normalize_url("http://[::1]:8080/x") == "http://[::1]:8080/x"


def test_hard_guard(monkeypatch):
    monkeypatch.setattr(wg, "GUARD_SLACK", 0.2)
    t0 = time.monotonic()
    with pytest.raises(wg._HardTimeout):
        wg.guarded(0.1, lambda: time.sleep(10))
    assert time.monotonic() - t0 < 3


def test_near_empty():
    with pytest.raises(wg.ProviderError, match="near-empty"):
        wg.check_fetch_content("short page")


def test_parse_rpc_sse_and_json():
    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"x":1}}\n\n'
    assert wg.parse_rpc_body(sse, 3)["result"] == {"x": 1}
    assert wg.parse_rpc_body('{"jsonrpc":"2.0","id":2,"result":{}}', 2)["id"] == 2
    with pytest.raises(wg.ProviderError):
        wg.parse_rpc_body("<html>gateway</html>", 1)


def test_parse_set_aliases():
    assert wg.parse_set("jina") == {"jina-mcp", "jina-reader", "jina-search"}
    assert wg.parse_set("crwl, exa") == {"crawl4ai", "exa"}
    with pytest.raises(ValueError):
        wg.parse_set("firecrawl")


def test_redact():
    wg._jina_state["key"] = "sekrit-123"
    try:
        assert wg.redact("HTTP 401 Bearer sekrit-123") == "HTTP 401 Bearer ***"
    finally:
        wg._jina_state["key"] = None


def test_html_to_text():
    assert wg.html_to_text("<html><script>x()</script><p>Hello</p><p>World</p></html>") == "Hello\nWorld"


def test_truncate_bytes_utf8_safe():
    assert wg.truncate_bytes("héllo", 2) == "h"


# ------------------------------------------------------------------ 2026-10-11 gap fixes


@pytest.mark.parametrize("mode,why", [
    ("crosshost", "redirected to another host: elsewhere.example"),
    ("rootredirect", "redirected to the site root"),
    ("soft404", "soft-404 title"),
    ("wrongtitle", "shares no word with the URL path"),
])
def test_parallel_wrong_page_falls_through(server, fakes, mode, why):
    MODES.update(exa="iserror", parallel=mode)
    out = json.loads(run(server, fakes, "fetch", "https://www.zillow.example/homedetails/1-Main-St/1_zpid/",
                         "--json").stdout)
    assert out["provider"] == "jina-reader"
    par = out["attempts"][1]
    assert par["provider"] == "parallel" and par["ok"] is False
    assert "wrong page" in par["error"] and why in par["error"]


def test_parallel_same_host_redirect_passes(server, fakes):
    MODES.update(exa="iserror", parallel="samehost")
    p = run(server, fakes, "fetch", "http://site.example/homedetails/1-Main-St/1_zpid/", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "parallel"
    assert out["url"] == "https://www.site.example/new/listing-moved"
    assert "parallel-fetch" in out["content"]


@pytest.mark.parametrize("req,got,title,bad", [
    ("https://www.zillow.com/homedetails/1-Main-St/1_zpid/", None,
     "Anchorage AK Real Estate - Anchorage AK Homes For Sale | Zillow", "shares no word"),
    ("https://www.zillow.com/homedetails/1-Main-St/1_zpid/", None,
     "1 Main St, Anchorage, AK 99501 | Zillow", None),
    ("http://github.com/djbclark", "https://github.com/djbclark/", "djbclark · GitHub", None),
    ("http://www.python.org/doc", "https://python.org/doc/", "Our Documentation | Python.org", None),
    ("https://de.wikipedia.org/wiki/K%C3%B6ln", None, "Köln – Wikipedia", None),
    ("https://en.wikipedia.org/wiki/Moltbook", "https://en.m.wikipedia.org/wiki/Moltbook",
     "Moltbook - Wikipedia", None),
    ("https://ex.org/docs/getting-started", "https://ex.org/docs/quickstart", "Quickstart", None),
    ("https://ex.org/docs/getting-started", None, "Getting started with Ex", None),
    ("https://ex.org/a/old-name", "https://other.org/x", "x", "another host"),
    ("https://ex.org/blog/some-post", "https://ex.org/", "Ex", "site root"),
    ("https://ex.org/", "https://ex.org", "Ex", None),
    ("https://ex.org/x", None, "404", "soft-404"),
    ("https://ex.org/x", None, "Oops! That page can't be found.", "soft-404"),
    ("https://ex.org/x", None, "", None),
    # verifier 2026-10-11: correct pages the first title rule rejected
    ("https://docs.python.org/3/library/stdtypes.html", None,
     "Built-in Types — Python 3.13.0 documentation", None),
    ("https://en.wikipedia.org/wiki/Samuel_Clemens", None, "Mark Twain - Wikipedia", None),
    ("https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
     "d842425e4bf79ba039352da0f658a906-Abstract-Conference.html", None,
     "Toolformer: Language Models Can Teach Themselves to Use Tools", None),
    # soft-404 only in page-chrome forms, and not when the path is about 404s
    ("https://en.wikipedia.org/wiki/HTTP_404", None, "HTTP 404 - Wikipedia", None),
    ("https://ex.org/x", None, "Why Free Will Does Not Exist", None),
    ("https://ex.org/x", None, "Error 404", "soft-404"),
    ("https://ex.org/x", None, "404 Not Found", "soft-404"),
    # redirectors, aliases, index pages, shared hosting
    ("https://doi.org/10.1038/nature14539", "https://www.nature.com/articles/nature14539",
     "Deep learning | Nature", None),
    ("https://youtu.be/abc", "https://www.youtube.com/watch?v=abc", "x - YouTube", None),
    ("https://twitter.com/karpathy", "https://x.com/karpathy", "Andrej Karpathy (@karpathy) / X", None),
    ("https://ex.org/index.html", "https://ex.org/", "Ex", None),
    ("https://ex.org/blog/some-post", "https://ex.org/en/", "Ex", "site root"),
    ("https://alice.github.io/notes", "https://bob.github.io/notes", "Notes", "another host"),
])
def test_page_mismatch(req, got, title, bad):
    body = {"https://en.wikipedia.org/wiki/Samuel_Clemens":
            "Samuel Langhorne Clemens (November 30, 1835 - April 21, 1910), known by the pen "
            "name Mark Twain, was an American writer.",
            "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
            "d842425e4bf79ba039352da0f658a906-Abstract-Conference.html":
            "Toolformer\n\nPart of Advances in Neural Information Processing Systems 36 "
            "(NeurIPS 2023) Main Conference Track\n\nAbstract\n\nLanguage models ..."}.get(req)
    why = wg.page_mismatch(req, got, title, body)
    if bad is None:
        assert why is None, why
    else:
        assert why and bad in why


def test_page_mismatch_body_echo_does_not_vouch():
    # the zillow city page with the requested URL echoed in a link and as a bare URL
    req = "https://www.zillow.com/homedetails/1-Main-St/1_zpid/"
    body = f"Homes for sale [Main listing]({req}) see {req} and www.zillow.com/homedetails/2"
    why = wg.page_mismatch(req, None, "Anchorage AK Real Estate - Anchorage AK Homes For Sale | Zillow",
                           body)
    assert why and "shares no word" in why


@pytest.mark.parametrize("args,extra", [
    (["--wayback-timeout", "nan"], {}),
    (["--timeout", "inf"], {}),
    ([], {"WEB_GET_WAYBACK_TIMEOUT": "abc"}),
    ([], {"WEB_GET_CRWL_TIMEOUT": "nan"}),
])
def test_bad_budgets_are_usage_errors(server, fakes, args, extra):
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", *args, extra=extra)
    assert p.returncode == 2, p.stderr
    assert "Traceback" not in p.stderr and "ALL PROVIDERS FAILED" not in p.stderr


def test_rung_budgets_never_below_timeout():
    assert wg.rung_budget(None, "WEB_GET_NO_SUCH_VAR", 120.0, 300.0) == 300.0
    assert wg.rung_budget(None, "WEB_GET_NO_SUCH_VAR", 120.0, 45.0) == 120.0
    assert wg.rung_budget(2.0, "WEB_GET_NO_SUCH_VAR", 120.0, 300.0) == 2.0


def test_check_narrowed_to_one_provider(server, fakes):
    p = run(server, fakes, "check", "--only", "jina-reader", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["ok"] is True and out["healthy"] == 1, p.stderr
    p = run(server, fakes, "check", "--only", "jina-reader", "--json",
            extra={"WEB_GET_JINA_READER_URL": "http://127.0.0.1:9/x"})
    assert p.returncode == 5 and "ALL PROVIDERS FAILED" not in p.stderr


def test_wayback_has_its_own_longer_timeout(server, fakes):
    MODES.update(wayback="slow", r="http500")  # the availability API answers after 3 s
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", "--timeout", "1",
            extra={"WEB_GET_WAYBACK_TIMEOUT": "20"})
    assert p.returncode == 0, p.stderr
    assert "wayback-direct" in p.stdout
    MODES.update(wayback="slow", **{"wayback-web": "slow"})
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback",
            "--wayback-timeout", "1")
    assert p.returncode == 5 and "timeout" in p.stderr
    assert time.monotonic() - t0 < 15


def test_provider_timeout_budgets():
    assert wg.provider_timeout("exa", 45, 150, 120) == 45
    assert wg.provider_timeout("crawl4ai", 45, 150, 120) == 150
    assert wg.provider_timeout("wayback", 45, 150, 120) == 120
    assert wg.provider_timeout("wayback", 45, 150) == wg.DEFAULT_WAYBACK_TIMEOUT == 120


def test_exa_cap_is_flagged_truncated(server, fakes):
    MODES["exa"] = "capped"
    p = run(server, fakes, "fetch", "https://site.example/a", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "exa"
    assert out["truncated"] is True and out["truncated_by"] == "exa"
    assert out["truncated_to"] == wg.EXA_MAX_CHARS == 200000
    assert "exa returned its 200000-character cap" in p.stderr
    p = run(server, fakes, "fetch", "https://site.example/a")
    assert "exa returned its 200000-character cap" in p.stderr


def test_exa_below_cap_not_truncated(server, fakes):
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    assert out["provider"] == "exa" and out["truncated"] is False and "truncated_by" not in out


def test_max_bytes_does_not_shrink_exa_request(server, fakes):
    # Exa always gets its full cap: a small --max-bytes must not make Exa's reply near-empty.
    p = run(server, fakes, "fetch", "https://site.example/a", "--max-bytes", "100", "--json")
    out = json.loads(p.stdout)
    assert out["provider"] == "exa" and out["truncated_by"] == "max-bytes"
    assert [a["maxCharacters"] for a in ARGS if a["tool"] == "web_fetch_exa"] == [200000]


def test_exa_body_chars():
    assert wg.exa_body_chars("# t\nURL: u\nPublished: d\n\n" + "x" * 50) == 50
    assert wg.exa_body_chars("no header " * 3) == 30


def test_wayback_timeout_usage_error(server, fakes):
    assert run(server, fakes, "fetch", "https://a.example", "--wayback-timeout", "0").returncode == 2
