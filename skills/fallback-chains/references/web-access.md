# Web access chain

Verified 2026-10-11. This is a dated snapshot. Before relying on it, re-read
the live configs in section 5 and run `web-get check`. If they differ, update
this file in the same turn and set its date.

This chain is separate from the six model layers in `inventory.md`. It decides
which provider answers a web search or a page fetch, not which model runs.
`scripts/check.py` does not read it.

## 1. Pause rule (operator, 2026-10-11)

> "if we have issues with web fetching/searching and our failover doesn't
> work we should pause rather than continuing without the web pages/web
> searches."

1a. **When it applies.** A search or page the task needs has failed on every
rung of the ladder for that client (section 3), including `web-get` and the
archive rungs. One rung failing is not a pause: if a later rung returns the
page or the results, carry on and note which rung served it.

1b. **What "pause" means.** All of these, in order:

1b.1. Stop scheduling new steps that depend on the missing page or search.
   Steps that do not depend on it may finish. Running work is not killed
   (never throw away paid work).
1b.2. Checkpoint: write what is done so far (run folder, `plan.md`, handoff or
   report file) so the same step can resume later.
1b.3. Report each failed URL or query, every rung tried and its verbatim error
   (HTTP status, "Payment Required", rate limit, timeout, empty body). In an
   `acp-dispatch` slice this is the report `BLOCKED: web access: <url or
   query>: <errors>` (exit 4). From a shell, `web-get` exit 5 is the same
   signal.
1b.4. Wait for the operator or for the provider to recover (a reset time, a
   restored key, credits). Then resume the same step, not a new one.

1b.5. Before pausing on "command not found" for `web-get`, use its full path
`~/src/djbclark-ade/bin/web-get`: a missing PATH entry is not a failed
ladder.

1c. **Never** do any of these instead: continue without the source,
summarize the page from memory or from a search snippet, drop the source
silently, swap in a weaker source without saying so, or proceed to synthesis
with the source missing.

1d. Related rulings: quota exhaustion means wait for the reset and resume the
same step (`feedback_quota_wait_dont_lose_work`). The research skill's step P
already stops a run that has no live search at all; this rule extends that to
a single needed page or query. Memory note:
`~/ops/site-private/memory/feedback_web_failover_pause.md`.

## 2. Shell ladder: `web-get`

`~/src/djbclark-ade/bin/web-get` is the one shell entry point, linked as
`~/.local/bin/web-get` (on PATH). Use it from any agent that has a shell, and
as the last automated rung for every client below. The script's docstring is
authoritative; this is its contract as of 2026-10-11.

2.1. `web-get search '<query>' [--n 8]`: exa (`web_search_exa`) → parallel
   (`web_search`) → jina-mcp (`search_web`, key) → jina-search (`s.jina.ai`,
   key) → composio (`COMPOSIO_SEARCH_DUCK_DUCK_GO`).
2.2. `web-get fetch '<url>' [--max-bytes N]`: exa (`web_fetch_exa`) →
   parallel (`web_fetch`) → jina-reader (`r.jina.ai`, key if available) →
   crawl4ai (`crwl`, renders JavaScript) → wayback (snapshot via `r.jina.ai`,
   then direct). The URL is normalised once (IDNA host, percent-encoded path),
   so IRIs such as `https://de.wikipedia.org/wiki/Köln` work. A `--max-bytes`
   cut prints `web-get: truncated to N bytes` on stderr and sets
   `"truncated": true` in `--json`: quote such a page as an excerpt.
2.3. A rung fails on a network error, HTTP ≥ 400, an MCP or JSON-RPC error, a
   timeout, near-empty content, a block page, or a rate-limit or quota notice
   returned as content (Exa's free tier answers "You've hit Exa's free MCP rate
   limit" with a normal reply). The next rung is then tried.
2.4. Timeouts are wall-clock per attempt: `--timeout` (default 45 s) for the
   HTTP rungs, `--crwl-timeout` (default 150 s, or `$WEB_GET_CRWL_TIMEOUT`) for
   crawl4ai, whose cold Chromium start took 30-120 s at load 30-38. Worst case a
   fetch walks for about 5.5 minutes before exit 5.
2.5. `web-get check`: probes every provider once, in parallel, and exits 0
   when at least 3 are healthy with one search and one fetch provider among
   them, else 5. It makes real calls, including Parallel's (billed per request
   on their side, free to us today) and a crawl4ai launch.
2.6. `--only`/`--skip` take provider names (`jina` means every jina-* rung,
   `crwl` is crawl4ai). `--json` prints `{ok, provider, url, attempts,
   content, truncated}`.
2.7. Exit 0: a provider answered (stderr names it: `web-get:
   provider=<p> url=<u>`). Exit 2: usage error. **Exit 5: every provider
   failed. Pause (section 1).** SIGTERM, SIGINT or SIGHUP kill any running
   crwl and its Chromium before web-get exits 128+n.
2.8. A success can still be the wrong page: Parallel has returned a site's
   search page for a missing listing. Check that the title matches the page you
   asked for before quoting it.

Firecrawl is not on the shell ladder: there is no API key on the machine, only
the claude.ai connector.

## 3. Per-client ladder

Try the rungs in order. Move to the next rung on an error, an empty result or
a page that is clearly not the content (login wall, bot check, cookie page).

| Client | Search rungs | Fetch rungs | Config |
|---|---|---|---|
| 3a. Claude Code | `exa` `web_search_exa`; `parallel-search` `web_search`; `jina` `search_web`; built-in WebSearch; Firecrawl connector `firecrawl_search` (low credits, billed: 6.1); Composio search toolkit; `web-get search` | `exa` `web_fetch_exa`; `parallel-search` `web_fetch`; `jina` `read_url`; built-in WebFetch; `crawl4ai` `scrape {targets}` (JavaScript); Firecrawl `firecrawl_scrape` (6.1); Composio `FETCH_URL_CONTENT`; `web-get fetch` | `~/.claude.json` (user scope; `jina` uses a `headersHelper`) |
| 3b. Codex | built-in web search; `exa`; `parallel-search`; `jina`; `web-get search` | `exa`; `parallel-search`; `jina` `read_url`; `crawl4ai` `scrape {targets}`; `web-get fetch` | `~/.codex/config.toml` (`jina` uses `http_headers_helper`; `crawl4ai` has `startup_timeout_sec = 120`) |
| 3c. opencode | `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `web-get fetch` | `~/.config/opencode/opencode.json` |
| 3d. Cursor | `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `web-get fetch` | `~/.cursor/mcp.json` |
| 3e. agy (only via `acp-run agy`) | `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `web-get fetch` | `~/.gemini/config/mcp_config.json` |
| 3f. Hermes | its web plugin: `ddgs`, then keyless Exa, Parallel, Keenable | `jina-reader` extract backend; the `blocked-page-recovery` / `web-research` skill script `recover_page.py` (Jina Reader with the key is its tier 3) | `~/.hermes/config.yaml` `web.search_backend`, `web.extract_backend`; plugin `~/.hermes/plugins/web/jina_reader/` |

3g. Composio search toolkit tools: `WEB`, `DUCK_DUCK_GO`, `EXA_ANSWER`,
`TAVILY`, `FETCH_URL_CONTENT` (see the `composio-cli` skill).

3h. Any other agent with a shell and none of these MCP servers: its own
built-in tools, then `web-get`.

3i. Last-resort recovery for a dead or blocked page, on every client: the
Wayback Machine (`https://archive.org/wayback/available?url=<url>`, then
`https://web.archive.org/web/2026/<url>`) and archive.today. Say in the notes
that the copy is an archive snapshot and give its date.

## 4. Providers

| Provider | Endpoint | Auth | Tools or form | Notes |
|---|---|---|---|---|
| 4a. Exa remote MCP | `https://mcp.exa.ai/mcp` | none | `web_search_exa {query, numResults}`, `web_fetch_exa {urls: [...]}` | Streamable HTTP: POST `initialize`, keep the `Mcp-Session-Id` header, then `tools/call` with it. Replies are SSE `data: {...}` lines. |
| 4b. Parallel remote MCP | `https://search.parallel.ai/mcp` | none | `web_search {objective, search_queries: [...]}`, `web_fetch` | Plain JSON replies; also returns `Mcp-Session-Id`. |
| 4c. Jina remote MCP | `https://mcp.jina.ai/v1` | `Authorization: Bearer $JINA_API_KEY` | `read_url {url}`, `search_web {query}`, `search_arxiv`, `search_ssrn`, `extract_pdf` and more | |
| 4d. Jina Reader | `https://r.jina.ai/<url>` | none (lower rate limit) or the key | GET | |
| 4e. Jina Search | `https://s.jina.ai/?q=<query>` | key required (401 without) | GET | |
| 4f. Crawl4AI | local, `crwl <url> -o markdown` | none | CLI (uv tool, version 0.9.4, Python 3.13) | Renders JavaScript (checked on typesafe.ai and moltbook.com). The package ships no MCP server; see 4g. A cold Chromium start under load takes 30-120 s. |
| 4g. Crawl4AI MCP | local stdio, `~/.local/bin/crawl4ai-mcp` (server name `crawl4ai` in all five clients) | none | `scrape {targets}` (a URL or a list of 1-20; `url` is rejected), `crawl`, `close_session`, `get_artifact` | Third-party wrapper `mcp-crawl4ai` 0.3.1: `uv tool install --python 3.13 'mcp-crawl4ai==0.3.1' --with crawl4ai==0.9.4 --with fastmcp==4.0.10 --with mcp==2.2.0 --with playwright==1.63.0`. Reuses the installed Playwright Chromium. First start 26 s, later 1.4-2.7 s. |
| 4h. Firecrawl | claude.ai connector (OAuth) | connector login | `firecrawl_search`, `firecrawl_scrape`, `firecrawl_research_*` | Claude Code only. Billed per request. |
| 4i. Built-in | Claude Code WebSearch/WebFetch; Codex built-in web search | client login | | |
| 4j. Composio | `composio` CLI | Composio login | search toolkit (3g) | |
| 4k. Archives | Wayback Machine, archive.today | none | GET | Recovery only (3i). |

## 5. Where config and keys live

Names and paths only. Never print or copy a key.

5.1. Key source of truth: `sudo-secretspec` entry `JINA_API_KEY`. Use it with
   `sudo-secretspec run --reason '<why>' -- <cmd>`; the child sees
   `$JINA_API_KEY`.
5.2. Claude Code (`~/.claude.json`) and Codex (`~/.codex/config.toml`) read the
   key from the vault on each connect through a headers helper. Neither file
   holds it.
5.3. Plaintext copies of the key, all mode 0600, none in a git repo. Rotation
   must replace each one:
   5.3.1. `~/.hermes/.env`
   5.3.2. `~/.config/opencode/opencode.json`
   5.3.3. `~/.cursor/mcp.json`
   5.3.4. `~/.gemini/config/mcp_config.json`
5.4. To rotate: `sudo-secretspec set JINA_API_KEY`, replace the four files in
   5.3 (temp file, then `mv -f`, keep 0600), restart Hermes, reconnect the
   MCP servers, run `web-get check`.
5.5. Exa, Parallel and Crawl4AI are keyless. Firecrawl has no key on the
   machine.

## 6. Known limits (2026-10-11)

6.1. Firecrawl: the account is low on credits and rate limited (about 11-16
   requests a minute, and "Payment Required" errors), so it sits after the
   free rungs in 3a. Expect it to fail and fall through to the next rung. It
   is not reachable from a shell script.
6.2. Jina: the key is a free trial key not attached to an account. It may run
   out or expire; a 401 or 402 from Jina means rotate (section 5).
6.3. opencode: `opencode mcp list` prints "No MCP servers configured" for every
   server, including ones that predate this chain. This is a pre-existing
   listing bug; `opencode debug config` does resolve them. Not verified live.
6.4. Cursor and agy: configured but not verified live. Codex lists `exa` as
   "Not logged in" (`parallel-search` "Unsupported", `jina` "Unknown"); a live
   `codex exec` call to `web_search_exa` has not been made yet.
6.5. Hermes: needs a restart to load `JINA_API_KEY` from `~/.hermes/.env`. Its
   `jina_reader` plugin sends no key, so only `recover_page.py` uses it.
6.6. reddit.com refused both WebFetch and Firecrawl scrape on 2026-10-09. Try
   Jina Reader, Crawl4AI and the archives before pausing.
6.7. Exa's keyless tier rate-limits (twice on 2026-10-11). Its notice arrives
   as normal content; `web-get` treats it as a failed rung, and an MCP client
   should do the same and move on.
6.8. The Wayback rung can be slow (54 s for one dewiki page at load 18 on
   2026-10-11, over the 45 s default). Retry it with `--only wayback
   --timeout 120` before pausing on an archive-only page.

## 7. Updating this file

A web chain change means any of: an MCP server added, removed or re-pointed in
one of the configs in section 3; a key rotated or moved; a provider dropped
from or added to `web-get`; a client gaining or losing a built-in web tool.
After one, re-read the configs, run `web-get check`, update this file and its
date, and update `SKILL.md` if the order of rungs changed.
