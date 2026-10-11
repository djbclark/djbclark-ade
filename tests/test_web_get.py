"""Unit tests for bin/web-get: failover order, block-page detection, exit 5 when every provider
fails, usage errors, key redaction. A local stub HTTP server stands in for Exa (SSE MCP),
Parallel (JSON MCP), Jina (MCP, r.jina.ai, s.jina.ai), the Exa REST API, a PDF host (under
$WEB_GET_PDF_VIA) and the Wayback Machine; fake crwl, composio, pdftotext and sudo-secretspec
scripts stand in for the CLIs (curl is the real one). No network."""

from __future__ import annotations

import gzip
import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import shutil

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "web-get"
_loader = importlib.machinery.SourceFileLoader("web_get", str(SCRIPT))
wg = importlib.util.module_from_spec(importlib.util.spec_from_loader("web_get", _loader))
_loader.exec_module(wg)

KEY = "jina_TESTKEY_0123456789abcdef"
EXA_KEY = "exa-TESTKEY-0123-4567-89ab-cdef0123"
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
EXA_SEEN: list[dict] = []  # Exa REST requests: {path, x-api-key, body}
WAYBACK_CDX: list[dict] = []  # CDX API queries seen
WAYBACK_CDX_STAMPS: list[str] = []  # captures the fake CDX lists (newest first); "" = none


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal valid PDF (Helvetica text, one content stream per page) for pdftotext."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        ops = "BT /F1 11 Tf 14 TL 40 750 Td " + " ".join(
            f"({ln}) Tj T*" for ln in lines) + " ET"
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
                    f"{len(objs)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PDF_PAGES = [[f"System card page one line {i} about model evaluations." for i in range(8)],
             [f"Page two line {i}: welfare, alignment and safeguards." for i in range(8)]]
PDF_BYTES = make_pdf(PDF_PAGES)


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
        prov = self.path.strip("/").split("/")[0]  # exa | parallel | jinamcp | exaapi
        if prov == "exaapi":
            return self._exa_rest(msg)
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
        elif tool == "web_fetch_exa" and mode == "soft404":
            text = f"# Page Not Found\nURL: {args['urls'][0]}\n\nSorry, nothing here. {ARTICLE}"
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

    def _exa_rest(self, body):
        path = "/" + self.path.strip("/").split("/", 1)[1]
        EXA_SEEN.append({"path": path, "key": self.headers.get("x-api-key") or "",
                         "auth": self.headers.get("Authorization") or "", "body": body,
                         "raw_path": self.path})
        HITS.append(f"exaapi:{path}")
        mode = MODES.get("exaapi", "ok")
        if self.headers.get("x-api-key") != EXA_KEY or mode == "http401":
            return self._send(401, json.dumps({"requestId": "r1", "error": "Invalid API key",
                                               "tag": "INVALID_API_KEY"}))
        if mode == "http402":
            return self._send(402, json.dumps({"requestId": "r1", "error": "No more credits",
                                               "tag": "NO_MORE_CREDITS"}))
        if path == "/search":
            rows = [{"title": f"exa-api {i}", "url": f"https://exa-api.example/{i}",
                     "highlights": [f"highlight {i} about the query"]}
                    for i in range(body.get("numResults", 3))]
            return self._send(200, json.dumps({"requestId": "r2", "results": rows,
                                               "costDollars": {"total": 0.005}}))
        url = body["urls"][0]
        if mode == "statuserror":
            return self._send(200, json.dumps({"requestId": "r3", "results": [], "statuses": [
                {"id": url, "status": "error", "error": {"tag": "CRAWL_NOT_FOUND",
                                                          "httpStatusCode": 404}}]}))
        n = body["text"]["maxCharacters"]
        text = ((ARTICLE * (n // len(ARTICLE) + 1))[:n] if mode == "capped"
                else "exa-api-fetch " + ARTICLE)
        title = "Anchorage AK Real Estate | Zillow" if mode == "wrongpage" else "Page"
        return self._send(200, json.dumps({"requestId": "r4", "results": [
            {"id": url, "url": url, "title": title, "text": text}],
            "statuses": [{"id": url, "status": "success", "source": "cached"}]}))

    def _wayback(self, u, rest, mode):
        """Live behaviour 2026-10-11: /web/<any ts>id_/<url> redirects to the nearest capture,
        served as archived (gzip included); an uncaptured URL is 404 'Wayback Machine'."""
        if rest.startswith("cdx/"):
            q = urllib.parse.parse_qs(u.query)
            WAYBACK_CDX.append(q)
            if mode == "cdx503" and len(WAYBACK_CDX) == 1:  # live 2026-10-11, clears on retry
                return self._send(503, "<html><title>Internet Archive: Temporarily Offline</title></html>", "text/html")
            rows = [["timestamp"]] + [[t] for t in WAYBACK_CDX_STAMPS]
            return self._send(200, json.dumps(rows if WAYBACK_CDX_STAMPS else []), "application/json")
        m = re.match(r"web/(\d+)id_/(.*)", rest)
        if not m:
            return self._send(404, "<html><head><title>Wayback Machine</title></head></html>", "text/html")
        ts, target = m.groups()
        if mode in ("cdxonly", "cdx503") and ts not in WAYBACK_CDX_STAMPS:  # newest capture an archived 404
            return self._send(404, "<html><head><title>Wayback Machine</title></head></html>", "text/html")
        if mode == "blocklatest" and ts not in WAYBACK_CDX_STAMPS:
            ts = "20260301000000"
            if not self.path.startswith(f"/wayback-web/web/{ts}id_/"):
                return self._redirect(f"/wayback-web/web/{ts}id_/{target}")
            return self._send(200, BLOCK, "text/html")
        cap = ts if ts in WAYBACK_CDX_STAMPS else "20260101000000"
        if ts != cap:
            return self._redirect(f"/wayback-web/web/{cap}id_/{target}")
        page = f"<html><body><p>wayback-direct {cap} {ARTICLE}</p></body></html>".encode()
        if mode == "gzip":
            page = gzip.compress(page)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if mode == "gzip":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _redirect(self, path):
        self.send_response(302)
        self.send_header("Location", path)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _trickle(self, msg, reply_first):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            if reply_first:
                tool = msg["params"]["name"]
                text = (f"Title: page\nURL: {msg['params']['arguments']['urls'][0]}\n\nexa-fetch {ARTICLE}" if tool == "web_fetch_exa"
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
            if mode == "badkey" and self.headers.get("Authorization"):  # a revoked key
                return self._send(401, '{"code":401,"name":"AuthenticationRequiredError"}')
            if "web.archive" in target or "/wayback-web/" in target:
                return self._send(200, f"Title: archived\n\nwayback-via-jina {ARTICLE}", "text/plain")
            if "deadhost" in target:
                return self._send(200, "Warning: Target URL returned error 404: Not Found\n" + "x" * 300, "text/plain")
            if mode == "zillowcity":  # live 2026-10-11: an empty title, the city page's heading
                return self._send(200, f"Title: \nURL Source: {target}\n\nMarkdown Content:\n"
                                       f"# Anchorage AK Real Estate\n\nHomes for sale {ARTICLE}", "text/plain")
            if mode == "wrongtitle":
                return self._send(200, f"Title: Anchorage AK Real Estate | Zillow\nURL Source: {target}"
                                       f"\n\nHomes for sale {ARTICLE}", "text/plain")
            body = ARTICLE * 250 if mode == "long" else ARTICLE  # long: ~310000 chars
            title = " ".join(urllib.parse.unquote(urllib.parse.urlsplit(target).path).replace("/", " ").split())
            return self._send(200, f"Title: {title}\nURL Source: {target}\n\njina-reader {body}", "text/plain")
        if prov == "s":
            if not self.headers.get("Authorization"):
                return self._send(401, '{"code":401}')
            return self._send(200, json.dumps({"code": 200, "data": [
                {"title": f"sj {i}", "url": f"https://sj.example/{i}", "description": "d"} for i in range(4)]}))
        if prov == "wayback":  # the retired availability API: it must not be called
            return self._send(200, json.dumps({"archived_snapshots": {}}))
        if prov == "pdfsrv":  # /pdfsrv/<target url, query included>
            target = self.path.split("/pdfsrv/", 1)[-1]
            if "loginwall" in target:
                return self._send(200, f"<html><title>Sign in</title><p>Sign in {ARTICLE}</p></html>", "text/html")
            if target.endswith(".pdf") or "pdfnoext" in target:
                data = PDF_BYTES
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            return self._send(200, f"<html><body><p>an html page {ARTICLE}</p></body></html>", "text/html")
        if prov == "wayback-web":  # web.archive.org: /web/<ts>id_/<url> and /cdx/search/cdx
            return self._wayback(u, parts[1] if len(parts) > 1 else "", mode)
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
                    f'echo "$@" >> {tmp_path}/crwl.calls\n'
                    'case "$CRWL_MODE" in fail) echo "Error: NoneType" >&2; exit 1;; '
                    'pdfcrash) echo "Error: \'NoneType\' object has no attribute \'raw_markdown\'" >&2; exit 1;; '
                    'slow) sleep 5;; esac\n'
                    "printf 'crawl4ai-js %s\\n' \"$1\"; i=0; while [ $i -lt 30 ]; do "
                    "printf 'rendered javascript content line\\n'; i=$((i+1)); done\n")
    comp = tmp_path / "composio"
    comp.write_text("#!/bin/sh\n"
                    'if [ "$COMPOSIO_MODE" = fail ]; then echo "not connected" >&2; exit 1; fi\n'
                    "echo '{\"successful\": true, \"data\": {\"results\": [{\"title\": \"ddg 1\", "
                    "\"link\": \"https://ddg.example/1\", \"snippet\": \"duck snippet\"}]}}'\n")
    pdft = tmp_path / "pdftotext"
    pdft.write_text("#!/bin/sh\n"
                    f'echo "$@" > {tmp_path}/pdftotext.argv\n'
                    # records only whether a key reached the child, never the key
                    f'if [ -n "$JINA_API_KEY$EXA_API_KEY" ]; then echo leaked; else echo clean; fi > {tmp_path}/pdftotext.env\n'
                    'if [ "$PDFT_MODE" = slow ]; then sleep 20; fi\n'
                    'i=0; while [ $i -lt 6 ]; do printf "fake pdf text page one line %s\\n" $i; i=$((i+1)); done\n'
                    "printf '\\f'\n"
                    'i=0; while [ $i -lt 6 ]; do printf "fake pdf text page two line %s\\n" $i; i=$((i+1)); done\n'
                    "printf '\\f'\n")
    vault = tmp_path / "vault" / "sudo-secretspec"
    vault.parent.mkdir()
    # Logs its argv (must never hold a key), then runs the child with both keys set, as
    # `sudo-secretspec run --reason R -- cmd...` does.
    vault.write_text("#!/bin/sh\n"
                     f'echo "$@" >> {tmp_path}/vault.calls\n'
                     'while [ "$1" != "--" ]; do shift; done; shift\n'
                     f'JINA_API_KEY={KEY} EXA_API_KEY={EXA_KEY} exec "$@"\n')
    for p in (crwl, comp, pdft, vault):
        p.chmod(0o755)
    return {"crwl": str(crwl), "composio": str(comp), "pdftotext": str(pdft),
            "vault_dir": str(vault.parent), "tmp": tmp_path}


@pytest.fixture(autouse=True)
def reset():
    MODES.clear()
    HITS.clear()
    PATHS.clear()
    AUTH_SEEN.clear()
    ARGS.clear()
    EXA_SEEN.clear()
    WAYBACK_CDX.clear()
    WAYBACK_CDX_STAMPS.clear()


def _env(server, fakes, key=True, extra=None, exa_key=False):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("WEB_GET_", "JINA_", "EXA_"))}
    e.update({
        "WEB_GET_EXA_API_URL": f"{server}/exaapi", "WEB_GET_PDF_VIA": f"{server}/pdfsrv",
        "WEB_GET_PDFTOTEXT": fakes["pdftotext"], "WEB_GET_CHECK_PDF_URL": "https://pdf.example/probe.pdf",
        "TMPDIR": str(fakes["tmp"]),
        "WEB_GET_EXA_URL": f"{server}/exa/mcp", "WEB_GET_PARALLEL_URL": f"{server}/parallel/mcp",
        "WEB_GET_JINA_MCP_URL": f"{server}/jinamcp/v1", "WEB_GET_JINA_READER_URL": f"{server}/r",
        "WEB_GET_JINA_SEARCH_URL": f"{server}/s",
        "WEB_GET_WAYBACK_WEB_URL": f"{server}/wayback-web", "WEB_GET_CRWL": fakes["crwl"],
        "WEB_GET_COMPOSIO": fakes["composio"], "WEB_GET_CHECK_URL": "https://example.com/",
        "WEB_GET_NO_SECRETSPEC": "1",
    })
    if key:
        e["JINA_API_KEY"] = KEY
    if exa_key:
        e["EXA_API_KEY"] = EXA_KEY
    e.update(extra or {})
    return e


def run(server, fakes, *args, key=True, extra=None, timeout=60, exa_key=False):
    e = _env(server, fakes, key, extra, exa_key)
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=e, capture_output=True,
                       text=True, timeout=timeout)
    assert KEY not in p.stdout and KEY not in p.stderr, "Jina key leaked to output"
    assert EXA_KEY not in p.stdout and EXA_KEY not in p.stderr, "Exa key leaked to output"
    return p


# ------------------------------------------------------------------ fetch ladder


def test_fetch_first_provider_wins(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a")
    assert p.returncode == 0, p.stderr
    assert "exa-fetch" in p.stdout
    assert "web-get: provider=exa-mcp url=https://site.example/a" in p.stderr
    assert not any(h.startswith("parallel") for h in HITS)


@pytest.mark.parametrize("mode", ["http500", "iserror", "rpcerror", "empty", "block"])
def test_fetch_exa_failure_modes_fall_to_parallel(server, fakes, mode):
    MODES["exa"] = mode
    p = run(server, fakes, "fetch", "https://site.example/a", "--json")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["provider"] == "parallel"
    assert [a["provider"] for a in out["attempts"]] == ["exa-api", "exa-mcp", "parallel"]
    assert "no Exa key" in out["attempts"][0]["error"]
    assert out["attempts"][1]["ok"] is False and out["attempts"][1]["error"]
    if mode == "block":
        assert "block page" in out["attempts"][1]["error"]
    assert "parallel-fetch" in out["content"]


def test_fetch_full_order_to_wayback(server, fakes):
    MODES.update(exa="http500", parallel="empty", r="block")
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", "--verbose",
            extra={"CRWL_MODE": "fail"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert [a["provider"] for a in out["attempts"]] == ["exa-api", "exa-mcp", "parallel", "jina-reader",
                                                       "pdf", "crawl4ai", "wayback"]
    assert "not a PDF" in out["attempts"][4]["error"]
    assert out["provider"] == "wayback"
    # the raw id_ capture is read straight from the archive, not through r.jina.ai
    assert "wayback-direct" in out["content"] and "Wayback Machine snapshot 20260101000000" in out["content"]
    assert "/wayback-web/web/20260101000000/" in out["url"]  # provenance: the replay URL, no id_
    assert out["snapshot"] is True and "Wayback Machine snapshot, not the live page" in p.stderr
    assert "try exa-mcp: FAIL" in p.stderr and "try wayback: ok" in p.stderr


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
    for name in ("exa-api", "exa-mcp", "parallel", "jina-reader", "pdf", "crawl4ai", "wayback"):
        assert f"{name}: " in p.stderr
    out = json.loads(p.stdout)
    assert out["ok"] is False and out["content"] is None and len(out["attempts"]) == 7


def test_fetch_timeout_moves_on(server, fakes):
    MODES["exa"] = "slow"
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--timeout", "1", "--json")
    out = json.loads(p.stdout)
    assert out["attempts"][1] == {**out["attempts"][1], "provider": "exa-mcp", "ok": False, "error": "timeout"}
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


def _no_reader_calls():
    return not any(h.startswith(("r:", "wayback:")) for h in HITS)  # no r.jina.ai, no availability API


def test_wayback_reads_capture_directly_keyless(server, fakes):
    # Live 2026-10-11: archive.org/wayback/available answers {} for everything, and keyless
    # r.jina.ai gets 403 AbuseAlleviationError for web.archive.org. Neither may be needed.
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", "--json", key=False)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["snapshot"] is True and "wayback-direct 20260101000000" in out["content"]
    assert out["url"].endswith("/wayback-web/web/20260101000000/https://site.example/a")
    assert _no_reader_calls() and not WAYBACK_CDX, HITS
    assert any(re.search(r"/web/\d{14}id_/https://site.example/a$", x) for x in PATHS), PATHS


def test_wayback_gzip_capture_is_decoded(server, fakes):
    MODES["wayback-web"] = "gzip"  # an id_ capture comes back as archived, gzip included
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", key=False)
    assert p.returncode == 0, p.stderr
    assert "wayback-direct" in p.stdout and "\ufffd" not in p.stdout


def test_wayback_falls_back_to_cdx_capture(server, fakes):
    MODES["wayback-web"] = "cdxonly"  # the newest capture is an archived 404
    WAYBACK_CDX_STAMPS.append("20250101000000")
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", "--json", key=False)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert "wayback-direct 20250101000000" in out["content"]
    assert "/web/20250101000000/" in out["url"]
    assert WAYBACK_CDX and WAYBACK_CDX[0]["filter"] == ["statuscode:200"]
    assert WAYBACK_CDX[0]["url"] == ["https://site.example/a"]


def test_wayback_cdx_503_is_retried_once(server, fakes):
    MODES["wayback-web"] = "cdx503"
    WAYBACK_CDX_STAMPS.append("20250101000000")
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", key=False)
    assert p.returncode == 0, p.stderr
    assert "wayback-direct 20250101000000" in p.stdout and len(WAYBACK_CDX) == 2


def test_wayback_skips_block_page_capture(server, fakes):
    MODES["wayback-web"] = "blocklatest"  # the newest capture is a verification wall
    WAYBACK_CDX_STAMPS.append("20250101000000")
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", key=False)
    assert p.returncode == 0, p.stderr
    assert "wayback-direct 20250101000000" in p.stdout


def test_wayback_not_archived_says_so(server, fakes):
    MODES["wayback-web"] = "cdxonly"  # and the CDX lists nothing
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback")
    assert p.returncode == 5
    assert "no capture" in p.stderr and "not archived" in p.stderr
    assert _no_reader_calls(), HITS  # with nothing captured, r.jina.ai is not asked even with a key


def test_wayback_jina_fallback_needs_a_key(server, fakes):
    MODES["wayback-web"] = "blocklatest"  # a capture exists but reads as a block page
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", key=False)
    assert p.returncode == 5 and "block page" in p.stderr and _no_reader_calls(), HITS
    HITS.clear()
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", "--json")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert "wayback-via-jina" in out["content"] and out["snapshot"] is True
    assert "/web/20260301000000/" in out["url"] and "r:GET" in HITS


def test_decode_body_content_encodings():
    import zlib
    page = "caf\u00e9 page"
    assert wg._decode_body(page.encode(), "") == page
    assert wg._decode_body(gzip.compress(page.encode()), "gzip") == page
    assert wg._decode_body(zlib.compress(page.encode()), "deflate") == page
    c = zlib.compressobj(wbits=-15)
    assert wg._decode_body(c.compress(page.encode()) + c.flush(), "deflate") == page
    with pytest.raises(wg.ProviderError, match="unsupported content-encoding br"):
        wg._decode_body(b"x", "br")
    with pytest.raises(wg.ProviderError, match="bad gzip body"):
        wg._decode_body(b"not gzip", "gzip")


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
    assert "rate-limit/quota" in out["attempts"][1]["error"]


def test_fetch_sse_trickle_respects_wall_clock_timeout(server, fakes):
    MODES["exa"] = "trickle"
    t0 = time.monotonic()
    p = run(server, fakes, "fetch", "https://site.example/a", "--timeout", "2", "--json")
    assert time.monotonic() - t0 < 15
    out = json.loads(p.stdout)
    assert out["attempts"][1]["provider"] == "exa-mcp" and "timeout" in out["attempts"][1]["error"]
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
    assert "web-get: provider=exa-mcp query=agents social network" in p.stderr


def test_search_order_to_composio(server, fakes):
    MODES.update(exa="rpcerror", parallel="http500", jinamcp="iserror", s="http500")
    p = run(server, fakes, "search", "q", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0
    assert [a["provider"] for a in out["attempts"]] == ["exa-api", "exa-mcp", "parallel", "jina-mcp",
                                                       "jina-search", "composio"]
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
    assert "rate-limit/quota" in out["attempts"][1]["error"]
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
    p = run(server, fakes, "check", exa_key=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert len([ln for ln in p.stdout.splitlines() if " ok " in ln]) == 13
    assert any(e["path"] == "/search" for e in EXA_SEEN) and any(e["path"] == "/contents" for e in EXA_SEEN)
    assert any("probe.pdf" in x for x in PATHS)  # the pdf rung probed a PDF, not example.com


def test_check_too_few_healthy(server, fakes):
    p = run(server, fakes, "check", "--only", "exa,parallel", "--json",
            extra={"WEB_GET_EXA_URL": "http://127.0.0.1:9/x"})
    out = json.loads(p.stdout)
    assert p.returncode == 5 and out["healthy"] == 2


def test_check_needs_search_and_fetch(server, fakes):
    p = run(server, fakes, "check", "--only", "exa,parallel,jina-mcp,jina-search,composio",
            "--skip", "", "--json", extra={"WEB_GET_CRWL": "/nonexistent/crwl"}, exa_key=True)
    # fetch-side exa and parallel still count, so this is healthy; now drop all fetch providers
    assert p.returncode == 0
    MODES.update(exa="http500", parallel="http500", exaapi="http401")
    p = run(server, fakes, "check", "--only", "exa,parallel,jina-mcp,jina-search,composio", exa_key=True)
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
    assert wg.parse_set("crwl, exa") == {"crawl4ai", "exa-api", "exa-mcp"}
    assert wg.parse_set("pdftotext,exa-api") == {"pdf", "exa-api"}
    with pytest.raises(ValueError):
        wg.parse_set("firecrawl")


def test_redact():
    wg._keys["JINA_API_KEY"], wg._keys["EXA_API_KEY"] = "sekrit-123", "exa-sekrit-456"
    try:
        assert wg.redact("HTTP 401 Bearer sekrit-123") == "HTTP 401 Bearer ***"
        assert wg.redact("x-api-key: exa-sekrit-456") == "x-api-key: ***"
    finally:
        wg._keys["JINA_API_KEY"] = wg._keys["EXA_API_KEY"] = None


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
    par = out["attempts"][2]
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


def test_check_wayback_probes_its_own_page(server, fakes):
    p = run(server, fakes, "check", "--only", "wayback", "--json", key=False)
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["ok"] is True, p.stderr
    assert any("/web/" in x and "id_/https://www.iana.org/help/example-domains" in x for x in PATHS), PATHS
    PATHS.clear()
    p = run(server, fakes, "check", "--only", "wayback", "--json", key=False,
            extra={"WEB_GET_CHECK_WAYBACK_URL": "https://probe.example/w"})
    assert p.returncode == 0 and any(x.endswith("id_/https://probe.example/w") for x in PATHS), PATHS


def test_check_narrowed_to_one_provider(server, fakes):
    p = run(server, fakes, "check", "--only", "jina-reader", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["ok"] is True and out["healthy"] == 1, p.stderr
    p = run(server, fakes, "check", "--only", "jina-reader", "--json",
            extra={"WEB_GET_JINA_READER_URL": "http://127.0.0.1:9/x"})
    assert p.returncode == 5 and "ALL PROVIDERS FAILED" not in p.stderr


def test_wayback_has_its_own_longer_timeout(server, fakes):
    MODES.update(r="http500", **{"wayback-web": "slow"})  # each archive request takes 3 s
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "wayback", "--timeout", "1",
            extra={"WEB_GET_WAYBACK_TIMEOUT": "20"})
    assert p.returncode == 0, p.stderr
    assert "wayback-direct" in p.stdout
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
    assert wg.provider_timeout("pdf", 45, 150, 120, 90) == 90
    assert wg.provider_timeout("pdf", 45, 150) == wg.DEFAULT_PDF_TIMEOUT == 120


def test_exa_cap_is_flagged_truncated(server, fakes):
    # Every later rung is shorter, so the capped copy is the longest and comes back flagged.
    MODES["exa"] = "capped"
    p = run(server, fakes, "fetch", "https://site.example/a", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 6 and out["provider"] == "exa-mcp"  # exit 6: not yet fetched
    assert out["truncated"] is True and out["truncated_by"] == "exa-mcp"
    assert out["truncated_to"] == wg.EXA_MAX_CHARS == 200000
    assert "exa-mcp returned its 200000-character cap" in p.stderr
    assert [a["provider"] for a in out["attempts"]][-1] == "wayback"  # walked the whole ladder
    p = run(server, fakes, "fetch", "https://site.example/a")
    assert p.returncode == 6 and "exa-mcp returned its 200000-character cap" in p.stderr
    assert "exit 6" in p.stderr and p.stdout.strip()  # the best copy is still printed


def test_exa_below_cap_not_truncated(server, fakes):
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    assert out["provider"] == "exa-mcp" and out["truncated"] is False and "truncated_by" not in out


def test_max_bytes_does_not_shrink_exa_request(server, fakes):
    # Exa always gets its full cap: a small --max-bytes must not make Exa's reply near-empty.
    p = run(server, fakes, "fetch", "https://site.example/a", "--max-bytes", "100", "--json")
    out = json.loads(p.stdout)
    assert out["provider"] == "exa-mcp" and out["truncated_by"] == "max-bytes"
    assert [a["maxCharacters"] for a in ARGS if a["tool"] == "web_fetch_exa"] == [200000]
    # a --max-bytes cut is the caller's choice: the ladder stops at the first full copy
    assert [a["provider"] for a in out["attempts"]] == ["exa-api", "exa-mcp"]


def test_exa_body_chars():
    assert wg.exa_body_chars("# t\nURL: u\nPublished: d\n\n" + "x" * 50) == 50
    assert wg.exa_body_chars("no header " * 3) == 30


def test_wayback_timeout_usage_error(server, fakes):
    assert run(server, fakes, "fetch", "https://a.example", "--wayback-timeout", "0").returncode == 2


# ------------------------------------------------------------------ 2026-10-11 ladder fixes A-D
# A: Exa REST API with the key (exa-api), keyless MCP (exa-mcp) next.


def test_exa_api_fetch_with_key(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", exa_key=True)
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "exa-api", p.stderr
    assert "exa-api-fetch" in out["content"] and out["truncated"] is False
    assert "web-get: provider=exa-api url=https://site.example/a" in p.stderr
    assert [a["provider"] for a in out["attempts"]] == ["exa-api"]
    assert not any(h.startswith("exa:") for h in HITS)  # no MCP call after a full REST reply
    (req,) = EXA_SEEN
    assert req["path"] == "/contents" and req["key"] == EXA_KEY and req["auth"] == ""
    assert req["body"] == {"urls": ["https://site.example/a"], "text": {"maxCharacters": 1000000}}
    assert EXA_KEY not in req["raw_path"]


def test_exa_api_search_with_key_one_call(server, fakes):
    p = run(server, fakes, "search", "agents", "--n", "3", "--json", exa_key=True)
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "exa-api", p.stderr
    assert out["content"].count("URL: https://exa-api.example/") == 3
    assert "highlight 0 about the query" in out["content"]
    (req,) = EXA_SEEN  # billing: one /search call, highlights inline, no /contents call
    assert req["path"] == "/search" and req["key"] == EXA_KEY
    assert req["body"] == {"query": "agents", "numResults": 3, "type": "auto",
                           "contents": {"highlights": True}}
    assert "web-get: provider=exa-api query=agents" in p.stderr


@pytest.mark.parametrize("mode,why", [("http401", "HTTP 401"), ("http402", "NO_MORE_CREDITS"),
                                      ("statuserror", "CRAWL_NOT_FOUND (HTTP 404)")])
def test_exa_api_failure_falls_to_exa_mcp(server, fakes, mode, why):
    MODES["exaapi"] = mode
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", exa_key=True)
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "exa-mcp"
    assert why in out["attempts"][0]["error"] and out["attempts"][0]["provider"] == "exa-api"


def test_exa_api_search_failure_falls_to_exa_mcp(server, fakes):
    MODES["exaapi"] = "http401"
    out = json.loads(run(server, fakes, "search", "q", "--json", exa_key=True).stdout)
    assert out["provider"] == "exa-mcp" and "Invalid API key" in out["attempts"][0]["error"]


def test_no_exa_key_uses_keyless_mcp(server, fakes):
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    assert out["provider"] == "exa-mcp"
    assert out["attempts"][0]["error"] == "no Exa key (WEB_GET_NO_SECRETSPEC set)"
    assert EXA_SEEN == []  # no REST call without a key


def test_only_exa_alias_and_exa_api(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "exa-api", exa_key=True)
    assert p.returncode == 0 and "provider=exa-api" in p.stderr
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "exa-api")
    assert p.returncode == 5 and "no Exa key" in p.stderr


def test_keys_read_once_through_sudo_secretspec(server, fakes):
    e = _env(server, fakes, key=False)
    e.pop("WEB_GET_NO_SECRETSPEC")
    e["WEB_GET_SECRETSPEC"] = str(Path(fakes["vault_dir"]) / "sudo-secretspec")
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "search", "q", "--only", "exa-api,jina-mcp",
                        "--json"], env=e, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["provider"] == "exa-api"
    assert EXA_SEEN[0]["key"] == EXA_KEY
    calls = (fakes["tmp"] / "vault.calls").read_text()
    assert calls.count("run --reason ") == 1  # one sudo-secretspec run for both keys
    assert calls.startswith("run --reason ") and KEY not in calls and EXA_KEY not in calls
    assert '"${JINA_API_KEY:-}" "${EXA_API_KEY:-}"' in calls
    assert KEY not in p.stdout + p.stderr and EXA_KEY not in p.stdout + p.stderr


# B: truncation is not success.


def test_capped_exa_mcp_walks_on_to_fuller_copy(server, fakes):
    MODES.update(exa="capped", parallel="iserror", r="long")
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", "--verbose")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "jina-reader", p.stderr
    assert out["truncated"] is False and "truncated_by" not in out
    assert len(out["content"]) > 300000
    capped = out["attempts"][1]
    assert capped["provider"] == "exa-mcp" and capped["ok"] and capped["truncated"] is True
    assert "TRUNCATED" in p.stderr and "walking on for a fuller copy" in p.stderr
    assert "truncated:" not in p.stderr


def test_capped_exa_api_skips_exa_mcp(server, fakes):
    # exa-mcp's 200000 cap cannot beat a 1000000-character exa-api copy: no MCP call is made.
    MODES.update(exaapi="capped", parallel="iserror", r="long")
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", exa_key=True)
    out = json.loads(p.stdout)
    assert p.returncode == 6
    assert not any(h.startswith("exa:") for h in HITS)
    assert out["attempts"][1]["provider"] == "exa-mcp" and "skipped" in out["attempts"][1]["error"]
    # nothing longer exists (jina's long copy is ~310000), so the exa-api copy is returned, flagged
    assert out["provider"] == "exa-api" and out["truncated"] is True
    assert out["truncated_by"] == "exa-api" and out["truncated_to"] == 1000000
    assert "exa-api returned its 1000000-character cap" in p.stderr
    assert "not yet fetched" in p.stderr


def test_shorter_complete_copy_does_not_beat_capped_one(server, fakes):
    MODES["exa"] = "capped"
    out = json.loads(run(server, fakes, "fetch", "https://site.example/a", "--json").stdout)
    par = out["attempts"][2]
    assert par["provider"] == "parallel" and par["ok"] and "shorter than the held capped copy" in par["note"]
    assert out["provider"] == "exa-mcp" and out["truncated"] is True
    # the shorter complete copy is not thrown away silently: --json names it
    assert {"provider": "parallel", "chars": par["chars"], "truncated": False} in out["held"]


def test_run_ladder_prefers_first_full_copy():
    def mk(n, meta=None):
        return lambda url, dl, mc: ("x" * n, url, meta) if meta else ("x" * n, url)
    ladder = [("exa-mcp", mk(200000, {"truncated_by": "exa-mcp", "truncated_to": 200000})),
              ("parallel", mk(170000)), ("jina-reader", mk(150000))]
    res = wg.run_ladder(ladder, lambda fn, dl: fn("u", dl, 0), 5, False, want_full=True)
    assert res["provider"] == "parallel" and "truncated_by" not in res  # 170000 >= 0.8 x 200000
    res = wg.run_ladder(ladder, lambda fn, dl: fn("u", dl, 0), 5, False, want_full=False)
    assert res["provider"] == "exa-mcp"  # search-style: the first answer wins


# C: PDFs.


def test_pdf_rung_by_extension(server, fakes):
    p = run(server, fakes, "fetch", "https://pdf.example/papers/system-card.pdf", "--only", "pdf", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "pdf", p.stderr
    assert "fake pdf text page two line 5" in out["content"] and "\f" not in out["content"]
    assert out["pdf_pages"] == 2 and out["pdf_bytes"] == len(PDF_BYTES)
    assert out["url"] == "https://pdf.example/papers/system-card.pdf"
    argv = (fakes["tmp"] / "pdftotext.argv").read_text().split()
    assert argv[:3] == ["-enc", "UTF-8", "-q"] and argv[-1] == "-"
    assert "/web-get-pdf-" in argv[3] and argv[3].endswith("/doc.pdf")
    assert not list(fakes["tmp"].glob("web-get-pdf-*"))  # the temp dir is removed
    assert not any(x.startswith("/pdfsrv") and "HEAD" in x for x in PATHS)


def test_pdf_rung_by_content_type(server, fakes):
    url = "https://pdf.example/download?id=pdfnoext"
    p = run(server, fakes, "fetch", url, "--only", "pdf", "--json")
    out = json.loads(p.stdout)
    assert out["provider"] == "pdf" and "fake pdf text" in out["content"], p.stderr
    assert len([x for x in PATHS if x.startswith("/pdfsrv/")]) == 2  # probe, then the download


def test_pdf_rung_rejects_non_pdf(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/page", "--only", "pdf")
    assert p.returncode == 5 and "pdf: not a PDF (no .pdf path" in p.stderr
    p = run(server, fakes, "fetch", "https://pdf.example/loginwall.pdf", "--only", "pdf")
    assert p.returncode == 5 and "pdf: not a PDF (Content-Type text/html)" in p.stderr
    assert not list(fakes["tmp"].glob("web-get-pdf-*"))


def test_pdf_rung_http_error(server, fakes):
    MODES["pdfsrv"] = "http500"
    p = run(server, fakes, "fetch", "https://pdf.example/a.pdf", "--only", "pdf")
    assert p.returncode == 5 and "pdf: curl rc=22 (HTTP error)" in p.stderr


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler pdftotext not installed")
def test_pdf_rung_real_pdftotext(server, fakes):
    out = json.loads(run(server, fakes, "fetch", "https://pdf.example/card.pdf", "--only", "pdf",
                         "--json", extra={"WEB_GET_PDFTOTEXT": shutil.which("pdftotext")}).stdout)
    assert out["provider"] == "pdf" and out["pdf_pages"] == 2
    assert "System card page one line 7 about model evaluations." in out["content"]
    assert "Page two line 0: welfare, alignment and safeguards." in out["content"]


def test_pdf_ladder_skips_crawl4ai(server, fakes):
    MODES.update(exa="iserror", parallel="iserror", r="http500", pdfsrv="http500")
    p = run(server, fakes, "fetch", "https://pdf.example/a.pdf", "--json")
    out = json.loads(p.stdout)
    crawl = [a for a in out["attempts"] if a["provider"] == "crawl4ai"][0]
    assert "skipped, a PDF" in crawl["error"] and crawl["ms"] < 1000
    assert not (fakes["tmp"] / "crwl.calls").exists()  # crwl never started
    MODES.pop("pdfsrv")
    out = json.loads(run(server, fakes, "fetch", "https://pdf.example/a.pdf", "--json").stdout)
    assert out["provider"] == "pdf"


def test_pdf_found_by_content_type_skips_crawl4ai(server, fakes):
    MODES.update(exa="iserror", parallel="iserror", r="http500")
    out = json.loads(run(server, fakes, "fetch", "https://pdf.example/get?pdfnoext=1", "--json",
                         "--skip", "pdf").stdout)
    # with the pdf rung skipped nothing has probed the URL: crawl4ai runs (and the fake answers)
    assert out["provider"] == "crawl4ai"
    wg._known_pdf.add("https://pdf.example/get?pdfnoext=1")
    try:
        with pytest.raises(wg.ProviderError, match="skipped, a PDF"):
            wg.fetch_crawl4ai("https://pdf.example/get?pdfnoext=1", wg.Deadline(5), 0)
    finally:
        wg._known_pdf.clear()


def test_crwl_raw_markdown_crash_explained(server, fakes):
    p = run(server, fakes, "fetch", "https://js.example/report", "--only", "crawl4ai",
            extra={"CRWL_MODE": "pdfcrash"})
    assert p.returncode == 5 and "no markdown for this page (a PDF or other non-HTML" in p.stderr


def test_is_pdf_url():
    assert wg.is_pdf_url("https://x.org/a/Card.PDF")
    assert wg.is_pdf_url("https://www-cdn.anthropic.com/x/Claude%20Fable%205.1%20System%20Card.pdf")
    assert wg.is_pdf_url("https://arxiv.org/pdf/1706.03762v7")
    assert not wg.is_pdf_url("https://arxiv.org/abs/1706.03762")
    assert not wg.is_pdf_url("https://x.org/pdf-guide.html")


# D: the wrong-page check on every rung that reports a URL or a title.


@pytest.mark.parametrize("mode", ["zillowcity", "wrongtitle"])
def test_jina_reader_wrong_page_fails(server, fakes, mode):
    MODES["r"] = mode
    url = "https://www.zillow.example/homedetails/1-Main-St/1_zpid/"
    p = run(server, fakes, "fetch", url, "--only", "jina-reader")
    assert p.returncode == 5 and "jina-reader: wrong page (title 'Anchorage AK Real Estate" in p.stderr
    p = run(server, fakes, "fetch", url, "--only", "jina-reader", "--no-page-check")
    assert p.returncode == 0 and "Homes for sale" in p.stdout


def test_exa_rungs_wrong_page_fail(server, fakes):
    MODES.update(exa="soft404", exaapi="wrongpage")
    url = "https://www.zillow.example/homedetails/1-Main-St/1_zpid/"
    out = json.loads(run(server, fakes, "fetch", url, "--json", exa_key=True).stdout)
    assert out["provider"] == "jina-reader"  # parallel's stub page is titled "P": wrong page too
    assert "parallel: wrong page" in out["attempts"][2]["error"]
    assert "exa-api: wrong page (title 'Anchorage AK Real Estate" in out["attempts"][0]["error"]
    assert "exa-mcp: wrong page (soft-404 title 'Page Not Found')" in out["attempts"][1]["error"]


def test_header_field_and_first_heading():
    t = "Title: \nURL Source: https://a.example/x\n\nMarkdown Content:\n# Big Heading\n\nbody"
    assert wg.header_field(t, ("Title",)) == "" and wg.header_field(t, ("URL Source",)) == "https://a.example/x"
    assert wg.first_heading(t) == "Big Heading" and wg.first_heading("no heading here") is None
    menu = "* [Buy](https://x/)\n    *   ###### Homes for sale\n" * 130  # live zillow 404 page
    assert wg.first_heading(menu + "# Uh oh,\n\n### Error 404 - page not found.") == "Uh oh,"


# Review fixes (web-ladder-review.md, 2026-10-11).


def test_provider_cap_survives_max_bytes(server, fakes):
    # 1.1: a --max-bytes cut must not hide the provider cap (the "not yet fetched" rule).
    MODES["exa"] = "capped"
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", "--max-bytes", "2000")
    out = json.loads(p.stdout)
    assert p.returncode == 6
    assert out["truncated_by"] == "exa-mcp" and out["truncated_to"] == 200000
    assert out["max_bytes_cut"] == 2000 and len(out["content"].encode()) <= 2000
    assert "exa-mcp returned its 200000-character cap" in p.stderr
    assert "truncated to 2000 bytes (--max-bytes)" in p.stderr


def test_max_bytes_alone_exits_0(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--json", "--max-bytes", "100")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["truncated_by"] == "max-bytes" and out["max_bytes_cut"] == 100


@pytest.mark.parametrize("url,title", [
    ("https://www.gutenberg.org/cache/epub/2701/pg2701-images.html",
     "Moby Dick; or The Whale | Project Gutenberg"),
    ("https://blog.example/wp-content/uploads/2024/05/annual-report.html", "Annual Report 2024"),
    ("https://site.example/sites/default/files/media/brochure.html", "Spring Brochure"),
    ("https://github.com/owner/project/blob/main/README.md", "project/README.md at main"),
])
def test_page_check_ignores_infrastructure_path_words(url, title):
    # 1.3: storage/CMS path segments name no page; the live Gutenberg URL failed 4 rungs.
    assert wg.page_mismatch(url, url, title, "") is None


def test_page_check_still_catches_wrong_title():
    url = "https://www.zillow.com/homedetails/1-Main-St/1_zpid/"
    assert "shares no word" in wg.page_mismatch(url, url, "Anchorage AK Real Estate | Zillow", "")


def test_hung_vault_is_killed_outside_rung_budget(server, fakes):
    # 2.1: a hung broker is bounded by its own timeout, killed with its tree, and every keyed
    # rung reports why it has no key (not "timeout (hard guard)" on the first rung).
    vault = fakes["tmp"] / "hung-vault"
    pidf = fakes["tmp"] / "hung-vault.pid"
    vault.write_text(f"#!/bin/sh\necho $$ > {pidf}\nexec sleep 30\n")
    vault.chmod(0o755)
    e = _env(server, fakes, key=False)
    e.pop("WEB_GET_NO_SECRETSPEC")
    e.update(WEB_GET_SECRETSPEC=str(vault), WEB_GET_SECRETSPEC_TIMEOUT="1")
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "search", "q", "--only", "exa-api,jina-search",
                        "--timeout", "10", "--json"], env=e, capture_output=True, text=True, timeout=60)
    assert time.monotonic() - t0 < 8
    out = json.loads(p.stdout)
    assert p.returncode == 5
    errs = {a["provider"]: a["error"] for a in out["attempts"]}
    assert errs["exa-api"] == "no Exa key (sudo-secretspec run timed out after 1 s)"
    assert errs["jina-search"] == "no Jina key (sudo-secretspec run timed out after 1 s)"
    pid = int(pidf.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the broker's process was killed, not orphaned


def test_no_vault_read_when_no_keyed_rung(server, fakes):
    e = _env(server, fakes, key=False)
    e.pop("WEB_GET_NO_SECRETSPEC")
    e["WEB_GET_SECRETSPEC"] = str(Path(fakes["vault_dir"]) / "sudo-secretspec")
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "fetch", "https://site.example/a", "--only",
                        "exa-mcp"], env=e, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert not (fakes["tmp"] / "vault.calls").exists()


def test_sigterm_removes_pdf_temp_dir(server, fakes):
    # 2.2: os._exit skips the pdf rung's finally; the signal handler removes the temp dir.
    e = _env(server, fakes, extra={"PDFT_MODE": "slow"})
    p = subprocess.Popen([sys.executable, "-I", str(SCRIPT), "fetch", "https://pdf.example/big.pdf",
                          "--only", "pdf"], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if (fakes["tmp"] / "pdftotext.argv").exists():
                break
            time.sleep(0.1)
        assert list(fakes["tmp"].glob("web-get-pdf-*"))  # the download is in place
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=15)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 128 + signal.SIGTERM
    assert not list(fakes["tmp"].glob("web-get-pdf-*"))


def test_children_never_get_keys(server, fakes):
    # 2.6: keys exported in the environment are not passed to untrusted-input children.
    p = run(server, fakes, "fetch", "https://pdf.example/a.pdf", "--only", "pdf", exa_key=True)
    assert p.returncode == 0, p.stderr
    assert (fakes["tmp"] / "pdftotext.env").read_text().strip() == "clean"


def test_crawl4ai_tries_pdf_looking_url_that_is_html(server, fakes):
    # 2.7: the pdf rung proved the .pdf URL serves HTML, so crawl4ai renders it.
    p = run(server, fakes, "fetch", "https://pdf.example/loginwall.pdf", "--only", "pdf,crawl4ai", "--json")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["provider"] == "crawl4ai", p.stderr
    assert "not a PDF" in out["attempts"][0]["error"]
    p = run(server, fakes, "fetch", "https://pdf.example/loginwall.pdf", "--only", "crawl4ai")
    assert p.returncode == 5 and "skipped, a PDF" in p.stderr  # no pdf rung ran: still skipped


def test_walk_budget_stops_the_truncation_walk():
    # 2.4: no rung starts after the walk budget; the capped copy comes back flagged.
    def capped(url, dl, mc):
        return ("x" * 200000, url, {"truncated_by": "exa-mcp", "truncated_to": 200000})
    def slow_fail(url, dl, mc):
        time.sleep(0.3)
        raise wg.ProviderError("nope")
    def never(url, dl, mc):
        raise AssertionError("must not run")
    ladder = [("exa-mcp", capped), ("parallel", slow_fail), ("jina-reader", never)]
    res = wg.run_ladder(ladder, lambda fn, dl: fn("u", dl, 0), 5, False, want_full=True,
                        walk_budget=0.1)
    assert res["provider"] == "exa-mcp" and res["truncated_by"] == "exa-mcp"
    assert "walk budget" in res["attempts"][2]["error"]


def test_walk_budget_flag_validated(server, fakes):
    p = run(server, fakes, "fetch", "https://site.example/a", "--walk-budget", "0")
    assert p.returncode == 2 and "--walk-budget" in p.stderr


def test_jina_rejected_key_retries_keyless(server, fakes):
    # 3.6: a revoked JINA_API_KEY must not fail r.jina.ai, which also works keyless.
    MODES["r"] = "badkey"
    p = run(server, fakes, "fetch", "https://site.example/a", "--only", "jina-reader")
    assert p.returncode == 0 and "jina-reader" in p.stdout, p.stderr
    assert AUTH_SEEN[-2].startswith("Bearer ") and AUTH_SEEN[-1] == ""


def test_exa_cap_slack_is_tight():
    # 2.9c: a complete page of 990000-998999 characters is not "at the cap".
    assert int(wg.EXA_API_MAX_CHARS * wg.EXA_CAP_SLACK) == 999000


def test_pypdf_fallback_pin_is_patched():
    # 2.5: GHSA-7hfw-26vp-jp8m and later advisories are fixed in 6.x (6.15.0 the newest seen).
    pin = __import__("re").search(r"pypdf==(\d+)\.(\d+)", SCRIPT.read_text()).groups()
    assert tuple(int(x) for x in pin) >= (6, 15)


def test_http_exception_is_a_network_error(monkeypatch):
    # 3.6: IncompleteRead (seen live from parallel) is a transient network error, not a bug.
    import http.client

    def boom(*a, **k):
        raise http.client.IncompleteRead(b"partial")
    monkeypatch.setattr(wg.urllib.request, "urlopen", boom)
    with pytest.raises(wg.ProviderError, match=r"^network error: IncompleteRead$"):
        wg.http("GET", "https://x.example/", wg.Deadline(5))
