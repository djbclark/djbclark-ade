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

1e. **Every needed page is eventually fetched (operator, 2026-10-11, later
the same day).**

> "We need to eventually get all of the web pages you are interested in
> getting, don't accept errors meaning we never get something, we always
> want to fallback or fix or stop and notify me so we can work together to
> fix."

A fetch error is never a final state. There are three moves, and only three:

1e.1. **Fall back.** The next rung, `web-get`, then `web-get --only
   <provider>` for each rung, then other URL forms: arXiv abs, PDF and HTML;
   `raw.githubusercontent.com` or `gh api`; the PDF itself; a publisher
   mirror; archive copies (3i).
1e.2. **Fix the tool** in `~/src/djbclark-ade` when the gap is ours (a rung
   that cannot read a page type, a wrong check), then fetch again.
1e.3. **Stop and notify.** Pause as in 1b and run `~/.local/bin/hermes-ping
   "<repo>: web access: <urls>: <errors>"` so the operator and the agent fix
   it together.

A truncated body counts as not yet fetched: Exa's cap, any provider limit, or
`web-get`'s `truncated: ... not yet fetched` line and exit 6 (2.10). A `--max-bytes` cut
the caller asked for is not truncation. Never record a source as
"unverified" or "could not fetch" and move on. A workflow's failed fetches
are a list to clear before its synthesis counts as final, and the rule
applies retroactively: past work whose fetches failed gets its pages fetched
now, and the deliverables that lacked them are revised where the page
changes them.

## 2. Shell ladder: `web-get`

`~/src/djbclark-ade/bin/web-get` is the one shell entry point, linked as
`~/.local/bin/web-get` (on PATH). Use it from any agent that has a shell, and
as the last automated rung for every client below. The script's docstring is
authoritative; this is its contract as of 2026-10-11.

2.1. `web-get search '<query>' [--n 8]`: firecrawl (the self-hosted
   Firecrawl's `/v2/search` at `djbclark-firecrawl.sipb.cloud`, bearer
   `FIRECRAWL_SELFHOST_API_KEY`, backed by SearXNG on Hyades; free, added
   2026-10-14) → exa-api (`api.exa.ai/search`, key;
   one call, highlights inline) → exa-mcp (keyless `web_search_exa`) →
   parallel (`web_search`) → jina-mcp (`search_web`, key) → jina-search
   (`s.jina.ai`, key) → composio (`COMPOSIO_SEARCH_DUCK_DUCK_GO`).
   **SearXNG shortcuts (2026-10-14):** Firecrawl sends SearXNG no category, so a
   plain query asks only the general engines (Bing, Yahoo, DuckDuckGo, Google
   Programmable Search, Wikipedia, Wikidata, and since 2026-10-14 Grokipedia, `!gp`,
   which is AI-generated, uses an undocumented keyless API and is weighted down to
   0.3). From Hyades, DuckDuckGo is often captcha-blocked; Google answers through a
   proxy on vps-primary (2026-10-16). A `!shortcut` in the query picks a specialist
   engine instead: `web-get search --only firecrawl '!st git rebase onto'`, or
   the same text to `firecrawl_search`. Pin firecrawl: any other rung gets the
   literal `!st`. Enabled: `!st` Stack Overflow, `!su` Super User, `!ubuntu`
   Ask Ubuntu, `!gh` GitHub repositories, `!arx` arXiv, `!se` Semantic Scholar,
   `!pub` PubMed, `!pypi` PyPI, `!dh` Docker Hub, `!al` Arch wiki, `!ge` Gentoo
   wiki, `!mdn` MDN, `!man` ManKier man pages; since 2026-10-14 (image `-r2`)
   also `!hn` Hacker News, `!npm` npm, `!crates` crates.io, `!lrs` lib.rs, `!pgo`
   pkg.go.dev, `!hf` Hugging Face, `!cb` Codeberg, `!gl` GitLab, `!oa` OpenAlex
   (polite pool), `!cr` Crossref, `!nixw` NixOS wiki. `!lo` (lobste.rs) was
   dropped in image `-r6` (2026-10-17): lobste.rs answers SearXNG with a "not a
   bot" challenge page, so `!lo` is now plain query text. A shortcut that finds
   nothing does this too, so check that the URLs come from the engine's site. The keyless APIs behind them are
   metered per IP, and the microVMs most likely share the Hyades host's (assumed,
   not measured): Stack Exchange allows about 300 requests a day without a key (a
   third-party figure; its throttle page gives none), GitHub search 10 a minute
   (GitHub's docs). Use them for targeted lookups, not loops.
2.2. `web-get fetch '<url>' [--max-bytes N] [--no-page-check] [--walk-budget S]`: exa-api
   (`api.exa.ai/contents`, key, full text up to 1000000 characters) → exa-mcp
   (keyless `web_fetch_exa`, 200000-character cap) → parallel (`web_fetch`) →
   jina-reader (`r.jina.ai`, key if available) → pdf (PDF URLs only, 2.9) →
   crawl4ai (`crwl`, renders JavaScript; skips PDFs) → firecrawl-mcp (the
   shared Firecrawl MCP server's `firecrawl_scrape` at `127.0.0.1:18804`:
   self-hosted, and `firecrawl-router` retries a bot-walled page on the
   commercial API, which gets through Cloudflare; same budget as crawl4ai;
   added 2026-10-14) → wayback (the newest
   capture, read raw from `web.archive.org`; 2.11). With no Exa key the exa-api rung fails at once
   (`no Exa key`) and exa-mcp answers. stderr and `--json` name the rung that
   served the page (`provider=exa-api` or `provider=exa-mcp`). The URL is
   normalised once (IDNA host, percent-encoded path), so IRIs such as
   `https://de.wikipedia.org/wiki/Köln` work. A `--max-bytes` cut prints
   `web-get: truncated to N bytes` on stderr and sets `"truncated": true` and
   `"max_bytes_cut": N` in `--json`: quote such a page as an excerpt. A
   provider cap is different (2.10), and a `--max-bytes` cut never hides one.
2.3. A rung fails on a network error, HTTP ≥ 400, an MCP or JSON-RPC error, a
   timeout, near-empty content, a block page, or a rate-limit or quota notice
   returned as content (Exa's free tier answers "You've hit Exa's free MCP rate
   limit" with a normal reply). A fetch rung also fails when it returns the
   wrong page (2.8). The next rung is then tried.
2.4. Timeouts are wall-clock per attempt: `--timeout` (default 45 s) for the
   HTTP rungs, `--crwl-timeout` (default 150 s, or `$WEB_GET_CRWL_TIMEOUT`) for
   crawl4ai, whose cold Chromium start took 30-120 s at load 30-38, and
   `--wayback-timeout` (default 120 s, or `$WEB_GET_WAYBACK_TIMEOUT`) for
   wayback, whose capture read plus a CDX lookup and re-read take 15-60 s
   (2.11, 6.8), and `--pdf-timeout` (default 120 s, or
   `$WEB_GET_PDF_TIMEOUT`) for the pdf rung's download and extraction (a
   16 MB, 212-page system card took 7.4 s). Unless set by flag or environment,
   the crawl4ai, wayback and pdf budgets are never below `--timeout`. All four
   must be finite and > 0; a bad value (`nan`, a non-number in the
   environment) is a usage error, exit 2. `check` uses the same budgets. Worst
   case a fetch walks for about 11 minutes before exit 5. After a
   provider-capped copy (2.10) no rung starts more than `--walk-budget`
   seconds later (default 300, or `$WEB_GET_WALK_BUDGET`; skipped rungs say
   "walk budget ... spent"). The vault read (5.6.4) runs before the ladder,
   outside every rung's budget.
2.5. `web-get check`: probes every provider once (15 probes: 7 search, 8
   fetch), in parallel, and exits 0 when at least 3 are healthy with one
   search and one fetch provider among them, else 5. Narrowed with
   `--only`/`--skip`, it exits 0 only when every selected provider is
   healthy, else 5 without the pause message (one sick provider is not an
   outage). It makes real calls: two billed Exa REST calls (one search, one
   contents page), Parallel's (billed per request on their side, free to us
   today), a crawl4ai launch, and a download of a small PDF (the IRS W-9,
   `$WEB_GET_CHECK_PDF_URL`) for the pdf rung.
2.6. `--only`/`--skip` take provider names (`exa` means both exa-* rungs,
   `jina` every jina-* rung, `crwl` is crawl4ai, `pdftotext` is pdf).
   `--json` prints `{ok, provider, url, attempts, content, truncated}`, plus
   `truncated_by` (`exa-api` or `exa-mcp` for a provider cap, else
   `max-bytes`) and `truncated_to` when `truncated` is true, `max_bytes_cut`
   when `--max-bytes` cut the body, `held` (the copies that did not win:
   provider, chars, truncated), `"snapshot": true` for a wayback copy, and
   `pdf_pages` and `pdf_bytes` for a pdf reply. Each successful attempt
   carries `chars`, a capped one `"truncated": true`, a shorter held one a
   `note`.
2.7. Exit 0: a provider answered (stderr names it: `web-get:
   provider=<p> url=<u>`). Exit 2: usage error. **Exit 5: every provider
   failed. Pause (section 1).** **Exit 6 (fetch): the best copy is cut at a
   provider's cap.** It is printed, but it is not fetched (1e): try other URL
   forms, fix the tool, or pause. A script that checks only for exit 0 treats
   it as a failure, which is the point. SIGTERM, SIGINT or SIGHUP kill any
   running crwl and its Chromium, curl, pdftotext or vault client and remove
   the pdf rung's temp dirs before web-get exits 128+n.
2.8. Providers return soft-404 and redirect pages as ordinary results (a
   missing zillow listing came back from Parallel as the site's "Anchorage AK
   Real Estate" page, under the requested URL, and from Jina Reader as the
   same page with an empty title, or as zillow's "Uh oh, Error 404" page).
   `web-get` checks the page on every fetch rung that reports a final URL or
   a title: exa-api (the result's `url` and `title`), exa-mcp (the `# title`
   and `URL:` header), parallel (`url`, `title`) and jina-reader (`Title:` and
   `URL Source:`; an empty title falls back to the first `# ` heading in the
   first 20000 characters). It fails the rung (`<rung>: wrong page
   (<reason>)`) on a redirect to another site or to the site root, a soft-404
   title in page-chrome form ("Page not found", "404", "Error 404", "404 Not
   Found", "That page can't be found"; skipped when the path itself mentions
   404 or "not found"), or a title sharing no word with a URL path of two or
   more words when the body's first 5000 characters (URLs removed) do not
   name the path either. Path words that name storage, a CMS or a repository
   rather than the page (`cache`, `epub`, `images`, `uploads`, `files`,
   `sites`, `static`, `assets`, `media`, `download(s)`, `public`,
   `resources`, `dist`, `blob`, `tree`, `refs`, `heads`, `attachment(s)`) do
   not count: on 2026-10-11 `gutenberg.org/cache/epub/2701/pg2701-images.html`
   ("Moby Dick; or The Whale | Project Gutenberg") failed exa-api (billed),
   exa-mcp and jina-reader as a wrong page and only crawl4ai served it, 36 s
   instead of 1 s. A title matches when a path word's first five
   letters are in it or a title word is in the path ("Built-in Types" for
   `stdtypes.html`); the body vouches for a Wikipedia redirect
   (`/wiki/Samuel_Clemens`, titled "Mark Twain"). http→https, `www.`, a
   trailing slash, `/index.html`, same-site redirects (another path, or
   another host of the same domain such as `en.m.wikipedia.org`), redirector
   links (`doi.org`, `youtu.be`, `t.co`, `bit.ly`) and twitter.com↔x.com
   pass; on `github.io`, `pages.dev` and similar shared hosts each subdomain
   is its own site. The pdf rung is not checked (a valid PDF after a CDN or S3
   redirect is the document; a login page is not a PDF and fails anyway), nor
   is wayback (no title or final URL). crawl4ai is checked on its first
   level-1 heading, plus Wikipedia's "does not have an article with this exact
   name" page: on 2026-10-11 `crwl` exited 0 on lawcom.gov.uk's "Page not
   found", a Vercel "This page doesn't exist", openai.com's "# 404" and a
   missing Wikipedia title, and web-get used to serve each as the page. The
   block list also covers Akamai's "Powered and protected by" challenge
   (mdpi.com) and Cloudflare's "received a high number of requests" throttle
   (cochranelibrary.com), and since 2026-10-14 the challenge pages of
   Cloudflare's newer interstitial ("Performing security verification"),
   DataDome, HUMAN/PerimeterX ("Press & Hold"), Imperva Incapsula, Vercel
   Attack Mode, AWS WAF and F5 (`firecrawl-router` keeps the same list). This is a heuristic and
   it misses cases: a realistic zillow path naming the city
   (`1-Main-St-Anchorage-AK/`) matches the city page's title. It can also
   reject a correct page whose title shares no word with its URL (a slug in
   another language); for a page you have checked yourself, `--no-page-check`
   turns it off. So still check the title matches the page you asked for
   before quoting it.
2.9. PDFs. The pdf rung handles URLs that are PDFs: a `.pdf` path or an arXiv
   `/pdf/` link, or otherwise a URL whose headers (`Content-Type`) or first
   bytes (`%PDF-`) say PDF, read with one GET of the headers and the first
   1 KB. It downloads
   with `curl` (`--fail`, 200 MB `--max-filesize`, http/https only) into a
   fresh `mkdtemp` directory, checks the `%PDF-` magic, extracts the text with
   `pdftotext -enc UTF-8` (poppler 26.10.0, `/opt/homebrew/bin`; `pypdf`
   6.19.0 through `uv run` when pdftotext is missing; 5.1.0 was affected by
   GHSA-7hfw-26vp-jp8m), and removes the directory, on a signal too. No child
   process (curl, pdftotext, pypdf, crwl, composio) inherits `EXA_API_KEY`,
   `JINA_API_KEY` or `FIRECRAWL_SELFHOST_API_KEY`, even when they are exported. crawl4ai skips a PDF (`crwl`
   0.9.4 dies with "'NoneType' object has no attribute 'raw_markdown'"), but
   tries a `.pdf` URL that the pdf rung downloaded and found to be HTML (a
   viewer or landing page), and a `crwl` crash with that message is
   reported as "no markdown for this page (a PDF or other non-HTML
   document?)". Exa, Parallel and Jina read most PDFs themselves; the pdf rung
   is the local, exact copy when they fail or truncate.
2.10. **Truncation is not success.** A fetch rung whose body comes back at
   its provider's cap is held and the ladder walks on for a fuller copy:
   exa-api at its 1000000-character `text.maxCharacters`, exa-mcp at its
   200000-character `maxCharacters` (Exa cuts silently: a War and Peace fetch
   came back with exactly 200000 body characters and no marker). The first
   complete body at least 0.8 times as long as the longest capped one wins;
   a shorter complete body is held too (`"note": "shorter than the held capped
   copy"`). If none beats it, the longest body is returned with `"truncated":
   true`, `"truncated_by": "exa-api"` or `"exa-mcp"`, a stderr line
   ending "not yet fetched (operator rule 2026-10-11, exit 6): try other URL
   forms, fix the tool, or pause" (1e), and **exit 6**. A `--max-bytes` cut of
   such a copy keeps `truncated_by`, both stderr lines and exit 6. A rung
   whose own cap is no larger than the held copy is skipped without a call
   (no exa-mcp call after a capped exa-api reply). `--json` `held` lists the
   copies that lost, so a shorter complete copy (or, with the 0.8 slack, a
   capped one longer than the winner) is never dropped silently. The walk
   stops starting rungs `--walk-budget` seconds after the first capped copy
   (2.4); a wayback copy that wins is marked `"snapshot": true` and stderr
   says it is not the live page. `EXA_CAP_SLACK` is 0.999: a body within
   0.1% of the cap counts as capped. On 2026-10-11 the 212-page Fable 5.1 system card came
   back complete from exa-api (371113 characters); with exa-api skipped,
   exa-mcp was capped at 200000 and parallel then served the full 371489. A
   `--max-bytes` cut is the caller's choice and never makes the ladder walk
   on.
2.11. **The wayback rung** (fixed 2026-10-11; 6.9 has the evidence). It reads
   straight from `web.archive.org`, in up to three steps:
   2.11a `/web/<now>id_/<url>`. Wayback redirects this to the nearest
         capture, and `id_` returns the page as archived, with no replay
         toolbar. One read, about 1-3 s.
   2.11b If that capture is missing (404), a block page, or near-empty, the
         CDX API is asked for the newest three captures that answered 200, and
         each one not yet tried is read. A 5xx from CDX is retried once.
   2.11c Only with a Jina key, and only when some capture exists: r.jina.ai on
         the replay URL, which renders JavaScript. Keyless calls get 403
         there, so this step is skipped without a key.
   The result's `url` is the replay URL (`/web/<ts>/<url>`). The content
   starts `[web-get: Wayback Machine snapshot <ts> of <url>]`, `--json` marks
   it `"snapshot": true`, and stderr says it is not the live page. `check`
   probes wayback with `https://www.iana.org/help/example-domains`
   (`$WEB_GET_CHECK_WAYBACK_URL`), because a raw example.com capture is
   shorter than the 200-character floor. A failure lists every step, e.g.
   `latest: no capture (HTTP 404: page 'Wayback Machine'); CDX: no 200
   capture: not archived`.

Firecrawl is not on the `web-get` ladder. Since 2026-10-14 every MCP client has the
shared self-hosted `firecrawl` server (4h); its router falls back to the
commercial API by itself (4h); the claude.ai connector (OAuth) is a further manual
rung in Claude Code.

## 3. Per-client ladder

Try the rungs in order. Move to the next rung on an error, an empty result or
a page that is clearly not the content (login wall, bot check, cookie page).

| Client | Search rungs | Fetch rungs | Config |
|---|---|---|---|
| 3a. Claude Code | shared `firecrawl` `firecrawl_search` (self-hosted SearXNG on Hyades, free, first since 2026-10-14; the router retries an empty or failed search on commercial Firecrawl); `exa` `web_search_exa`; `parallel-search` `web_search`; `jina` `search_web`; built-in WebSearch; Firecrawl connector `firecrawl_search` (commercial, billed: 6.1); Composio search toolkit; `web-get search` | `exa` `web_fetch_exa`; `parallel-search` `web_fetch`; `jina` `read_url`; built-in WebFetch; `crawl4ai` `scrape {targets}` (JavaScript); shared `firecrawl` `firecrawl_scrape` (self-hosted, JavaScript, 4h); Firecrawl connector `firecrawl_scrape` (commercial: Cloudflare-guarded pages, 6.1); Composio `FETCH_URL_CONTENT`; `web-get fetch` | `~/.claude.json` (user scope; `jina` uses a `headersHelper`) |
| 3b. Codex | `firecrawl` `firecrawl_search` (SearXNG, as 3a); built-in web search; `exa`; `parallel-search`; `jina`; `web-get search` | `exa`; `parallel-search`; `jina` `read_url`; `crawl4ai` `scrape {targets}`; `firecrawl` `firecrawl_scrape`; `web-get fetch` | `~/.codex/config.toml` (`jina` uses `http_headers_helper`; `crawl4ai` has `startup_timeout_sec = 120`) |
| 3c. opencode | `firecrawl` `firecrawl_search` (SearXNG, as 3a); `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `firecrawl` `firecrawl_scrape`; `web-get fetch` | `~/.config/opencode/opencode.json` |
| 3d. Cursor | `firecrawl` `firecrawl_search` (SearXNG, as 3a); `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `firecrawl` `firecrawl_scrape`; `web-get fetch` | `~/.cursor/mcp.json`; each server also needs a per-project approval, keyed to a hash of its config, so changing a server's entry voids it and needs a fresh `cursor-agent mcp enable <name>` (2026-10-12) (`cursor-agent mcp enable <name>`, 6.4) |
| 3e. agy (only via `acp-run agy`) | `firecrawl` `firecrawl_search` (SearXNG, as 3a); `exa`; `parallel-search`; `jina`; `web-get search` | same servers' fetch tools; `crawl4ai` `scrape {targets}`; `firecrawl` `firecrawl_scrape`; `web-get fetch` | `~/.gemini/config/mcp_config.json` |
| 3f. Hermes | its web plugin: `web.search_backend: firecrawl` (since 2026-10-14) with `FIRECRAWL_API_URL=http://127.0.0.1:18805` in `~/.hermes/.env`, which is `firecrawl-router` (4h): SearXNG on Hyades first, commercial Firecrawl when self-hosted fails. Hermes picks one backend and never reroutes a failed call, so the router is its fallback. Was keyed Exa (2026-10-11 to 2026-10-14; `EXA_API_KEY` stays for `web.extract_backend: exa`) | `jina-reader` extract backend; the `blocked-page-recovery` / `web-research` skill script `recover_page.py` (Jina Reader with the key is its tier 3) | `~/.hermes/config.yaml` `web.search_backend`, `web.extract_backend`; plugin `~/.hermes/plugins/web/jina_reader/` |

3g. Composio search toolkit tools: `WEB`, `DUCK_DUCK_GO`, `EXA_ANSWER`,
`TAVILY`, `FETCH_URL_CONTENT` (see the `composio-cli` skill).

3h. Any other agent with a shell and none of these MCP servers: its own
built-in tools, then `web-get`.

3i. Last-resort recovery for a dead or blocked page, on every client: the
Wayback Machine. Fetch `https://web.archive.org/web/<YYYYMMDDhhmmss>id_/<url>`
directly, which redirects to the nearest capture, or run `web-get fetch --only
wayback '<url>'` (2.11). Not the availability API, and not through r.jina.ai
without a key (6.9). archive.today was unreachable from this machine on
2026-10-11 (6.9). Say in the notes that the copy is an archive snapshot and
give its date.

## 4. Providers

| Provider | Endpoint | Auth | Tools or form | Notes |
|---|---|---|---|---|
| 4a. Exa remote MCP | `https://mcp.exa.ai/mcp` | none | `web_search_exa {query, numResults}`, `web_fetch_exa {urls: [...]}` | Streamable HTTP: POST `initialize`, keep the `Mcp-Session-Id` header, then `tools/call` with it. Replies are SSE `data: {...}` lines. |
| 4b. Parallel remote MCP | `https://search.parallel.ai/mcp` | none | `web_search {objective, search_queries: [...]}`, `web_fetch` | Plain JSON replies; also returns `Mcp-Session-Id`. |
| 4c. Jina remote MCP | `https://mcp.jina.ai/v1` | `Authorization: Bearer $JINA_API_KEY` | `read_url {url}`, `search_web {query}`, `search_arxiv`, `search_ssrn`, `extract_pdf` and more | |
| 4d. Jina Reader | `https://r.jina.ai/<url>` | none (lower rate limit) or the key | GET | |
| 4e. Jina Search | `https://s.jina.ai/?q=<query>` | key required (401 without) | GET | |
| 4f. Crawl4AI | local, `crwl <url> -o markdown` | none | CLI (uv tool, version 0.9.4, Python 3.13) | Renders JavaScript (checked on typesafe.ai and moltbook.com). The package ships no MCP server; see 4g. A cold Chromium start under load takes 30-120 s. |
| 4g. Crawl4AI MCP | one shared local server over HTTP, `http://127.0.0.1:18798/mcp` (launchd `com.djbclark.crawl4ai-mcp`, site-djbclark `roles/shared_mcp`, since 2026-10-12; was a stdio copy per session). Server name `crawl4ai` in all five clients | none | `scrape {targets}` (a URL or a list of 1-20; `url` is rejected), `crawl`, `close_session`, `get_artifact` | Third-party wrapper `mcp-crawl4ai` 0.3.1: `uv tool install --python 3.13 'mcp-crawl4ai==0.3.1' --with crawl4ai==0.9.4 --with fastmcp==4.0.10 --with mcp==2.2.0 --with playwright==1.63.0`. Reuses the installed Playwright Chromium. First start 26 s, later 1.4-2.7 s. |
| 4h. Firecrawl | (a) self-hosted, shared: `http://127.0.0.1:18804/mcp` (launchd `com.djbclark.firecrawl-mcp`, site-djbclark `roles/shared_mcp`, since 2026-10-14), server name `firecrawl` in all five clients (agy through `mcp-proxy --transport streamablehttp`); backend `https://djbclark-firecrawl.sipb.cloud` on SIPB Hyades. (b) commercial: claude.ai connector (OAuth) | (a) none from the client; the shared server holds `FIRECRAWL_SELFHOST_API_KEY` (5.5). (b) connector login | `firecrawl_scrape`, `firecrawl_search`, `firecrawl_crawl` + `firecrawl_check_crawl_status` (tested on (a) 2026-10-14), `firecrawl_map`; (a) also lists the cloud-only `firecrawl_agent*`, `firecrawl_monitor_*`, `firecrawl_research_*` and `firecrawl_interact*`, which need (b) | (a) `firecrawl-mcp` 3.23.7 over Firecrawl 2.11.519, no rate limit, no credits, renders JavaScript, fetches reddit.com. `firecrawl_search` is SearXNG on Hyades (since 2026-10-14; Bing and Yahoo (since 2026-10-16), DuckDuckGo (often captcha-blocked from Hyades), Google's keyless Programmable Search (SearXNG's `google cse`, sent through the vps-primary tinyproxy since image r5, 2026-10-16: site-djbclark `docs/google-proxy-vps-primary.md`; the plain `google` engine is off, it gets 403 from every address, searxng#6835), Wikipedia, Wikidata and Grokipedia (weight 0.3), plus the `!shortcut` engines in 2.1; Startpage and Mojeek are inactive by default, and our image disables Brave, which refuses SearXNG). The router also listens on `127.0.0.1:18805` without a token (`--open`) for Hermes' firecrawl backend. It fails on Cloudflare challenge pages (Stack Overflow) and its `map` reads sitemaps only, so `bin/firecrawl-router` (the server's parent process) retries those, 5xx answers, an unreachable backend and empty searches on the commercial API (`FIRECRAWL_API_KEY`) automatically; the response header `X-Firecrawl-Backend` and one log line in `~/Library/Logs/shared-mcp/firecrawl-mcp.log` name the backend used. Deploy: `hyades-docker` skill, `examples/firecrawl/`. Comparison: `docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md`. (b) Claude Code only. Billed per request. |
| 4i. Built-in | Claude Code WebSearch/WebFetch; Codex built-in web search | client login | | |
| 4j. Composio | `composio` CLI | Composio login | search toolkit (3g) | |
| 4k. Archives | Wayback Machine, archive.today | none | GET | Recovery only (3i). |
| 4l. Exa REST API | `https://api.exa.ai` | `x-api-key: $EXA_API_KEY` (5.6) | POST `/search {query, numResults, type: auto, contents: {highlights: true}}`, POST `/contents {urls: [...], text: {maxCharacters}}` | Billed per call (about $0.001 a contents page; a search of up to 10 results is the base price, highlights included, and `web-get search --n 11-25` costs more). Errors are `{error, tag}` (`INVALID_API_KEY`, `NO_MORE_CREDITS`, ...); a per-URL failure is in `statuses[]` (`CRAWL_NOT_FOUND`). `text.maxCharacters` is documented with a maximum of 10000 but 1000000 is accepted and returned 370913 characters on 2026-10-11. Docs: `https://exa.ai/docs/llms.txt`, `reference/search.md`, `reference/get-contents.md`. |
| 4m. PDF rung | local `curl` + `pdftotext` (poppler) | none | `web-get fetch --only pdf` | 2.9. |

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
5.5. Parallel and Crawl4AI are keyless. Exa's MCP has a keyless tier (6.7);
   its REST API needs `EXA_API_KEY` (5.6). Firecrawl (2026-10-14):
   `sudo-secretspec` entries `FIRECRAWL_SELFHOST_API_KEY` (the bearer token of
   the self-hosted gate) and `FIRECRAWL_API_KEY` (commercial free plan: the
   router's fallback and `bench/firecrawl/fc-bench`). The shared server gets
   both at `just shared-mcp-apply-secrets`, into its 0600 plist; the
   `firecrawl-mcp` child sees neither, only a per-process router token.
5.6. **`EXA_API_KEY` (added 2026-10-11)**, `sudo-secretspec` entry
   `EXA_API_KEY` (name only here; 36 characters). Wiring, verified 2026-10-11
   with values masked:
   5.6.1. Claude Code (`~/.claude.json`, `mcpServers.exa.headersHelper`) and
      Codex (`~/.codex/config.toml`, `[mcp_servers.exa]
      http_headers_helper`): a header helper that runs `sudo-secretspec run`
      and prints `{"x-api-key": ...}` on each connect. Neither file holds the
      key.
   5.6.2. opencode (`~/.config/opencode/opencode.json`, `mcp.exa.headers`),
      Cursor (`~/.cursor/mcp.json`, `mcpServers.exa.headers`) and agy
      (`~/.gemini/config/mcp_config.json`, `mcpServers.exa.headers`): a
      plaintext `x-api-key` header, files mode 0600.
   5.6.3. Hermes (search moved to `firecrawl` on 2026-10-14, 3f; extract is
      still Exa): `EXA_API_KEY` in `~/.hermes/.env` (0600) and, in
      `~/.hermes/config.yaml`, `web.search_backend: exa` (until 2026-10-14) with
      `web.provider_tier.exa: paid` (always keyed, never the free tier);
      `web.extract_backend` stays `jina-reader` (set it to `exa` to move
      extraction too). `exa-py` 2.10.2 was installed through Hermes's own
      `tools.lazy_deps.ensure("search.exa")`; Hermes would otherwise install
      it on first use. `config.yaml` is not generated by any Ansible role: it
      is a plain file tracked by the `~/.hermes` git repo (the switch is
      commit a3e2f94 there, which holds only that hunk). Verified 2026-10-11:
      a non-model `web_search_tool` call in the Hermes venv returned Exa
      results with `keyless? False`, and the gateway was restarted
      (`launchctl kickstart -k gui/$(id -u)/com.stayturgid.hermes-gateway`,
      11:09:57) and reconnected Discord and Telegram.
   5.6.4. `web-get`: `$EXA_API_KEY` if set, else read with `$JINA_API_KEY` and
      `$FIRECRAWL_SELFHOST_API_KEY` in one `sudo-secretspec run` per
      invocation, kept in memory and sent only as the `x-api-key` header to
      `api.exa.ai` (the Firecrawl one only as the gate's bearer token; never
      argv, never printed).
      The read runs before the ladder and only when a selected rung can use
      a key, through `/usr/local/bin/sudo-secretspec` when present (a PATH
      entry could shadow it), bounded by `$WEB_GET_SECRETSPEC_TIMEOUT`
      (default 30 s; the client's process tree is killed after). A failed
      read names its reason on every keyed rung (`no Exa key (sudo-secretspec
      run timed out after 30 s)`). r.jina.ai retries once keyless when it
      rejects the Jina key (401/403).
   5.6.5. To rotate: `sudo-secretspec set EXA_API_KEY`, replace the three
      plaintext copies in 5.6.2 and the `~/.hermes/.env` line (temp file,
      then `mv -f`, keep 0600), restart Hermes, reconnect the MCP servers, run
      `web-get check`.

## 6. Known limits (2026-10-11)

6.1. Firecrawl commercial: the free plan allows about 10 requests a minute (5
   parallel requests all got 429 on 2026-10-14) and 1000 credits a month, so
   it sits after the free rungs in 3a. Expect it to fail and fall through to
   the next rung. The self-hosted shared server (4h) has neither limit but
   depends on SIPB Hyades being up, and fetches from MIT's address space:
   keep crawls modest.
6.2. Jina: the key is a free trial key not attached to an account. It may run
   out or expire; a 401 or 402 from Jina means rotate (section 5).
6.3. opencode (v2.0.26): the earlier "No MCP servers configured" from
   `opencode mcp list` was a stale background service (`opencode serve
   --service`), not the config; on 2026-10-11 it lists all six servers
   connected. The service re-reads `opencode.json` but keeps an MCP
   connection made before a header change, so after adding or rotating a key
   reconnect that server: `opencode api POST
   /api/experimental/mcp/<name>/disconnect`, then `.../connect` (`opencode
   api` takes an operation id such as `mcp.list` or `METHOD /path`), or
   `opencode service restart` when no other session's work runs under the
   service. Verified live 2026-10-11 through `acp-run opencode`: its
   `execute` tool called `tools.exa.web_search_exa` and
   `tools.jina.search_web`, both answering.
6.4. Live status per client, 2026-10-11 (`web-clients-live-report`):
   6.4.1. Claude Code: `exa` and `jina` connected; a `claude -p` call used
      `mcp__exa__web_search_exa` and `mcp__jina__search_web`. PASS.
   6.4.2. Codex: `codex app-server` `mcpServerStatus/list` loads `exa` with
      the key header (`agent_run` listed) and `jina` (12 tools). A
      model-driven `codex exec` call is still to do: the 5-hour pool was
      exhausted.
   6.4.3. opencode: PASS (6.3).
   6.4.4. Cursor: it was loading none of the web servers. `cursor-agent mcp
      list` showed exa, jina, parallel-search and crawl4ai "not loaded (needs
      approval)": approvals are per project directory
      (`~/.cursor/projects/<dir>/mcp-approvals.json`). Fixed for `~` with
      `cursor-agent mcp enable <name>` for the four; a run from another
      directory may need the same. `mcp list-tools exa` then showed
      `agent_run`. A live model call is still to do (plan exhausted to
      2026-11-02).
   6.4.5. agy: `mcp_config.json` matches the documented schema (`serverUrl`,
      `headers`) and the vault values; a live `acp-run agy` call is still to
      do (it hit its usage limit; aiuse had shown the pool as 88% left).
      2026-10-12: live `acp-run agy` calls show agy under ACP loads only
      stdio servers (its session `brain/<id>/mcp/` held only graft and
      token-savior); `serverUrl` entries (basic-memory, exa, jina,
      parallel-search) never load. crawl4ai works through a stdio bridge to
      the shared server: `mcp-proxy --transport streamablehttp
      http://127.0.0.1:18798/mcp` (scrape of example.com returned the title).
      Same day, djbclark chose to bridge all four `serverUrl` servers the same
      way (exa and jina pass their key with `-H`, so it shows in `ps`); after it
      agy's session loaded all 7 servers and an exa `web_search_exa` call
      answered. Backup `mcp_config.json.bak-2026-10-12-agy-bridges`.
   6.4.6. A no-model sign that a client sends the Exa key: Exa's `tools/list`
      adds `agent_run` only when an `x-api-key` header is present (any key;
      the vault key's validity was checked separately: a bogus key gets
      "web_search_exa error (401): Invalid API key").
   6.4.7. Older note: Codex lists `exa` as
   "Not logged in" (`parallel-search` "Unsupported", `jina` "Unknown"). That is
   cosmetic: Exa publishes OAuth protected-resource metadata
   (`https://mcp.exa.ai/.well-known/oauth-protected-resource`, optional
   sign-in through `auth.exa.ai`), so Codex reports a missing token, but the
   keyless endpoint answers. On 2026-10-11 Codex 0.162.1's own MCP client
   (`codex app-server`, `mcpServerStatus/list`) connected to `exa` with no
   login and listed `web_fetch_exa` and `web_search_exa`. A model-driven
   `codex exec` tool call was not made: the Codex 5-hour pool was exhausted.
   No config change is needed; `codex mcp login exa` would only attach an Exa
   account.
6.5. Hermes: needs a restart to load a key from `~/.hermes/.env` (it was
   restarted for `EXA_API_KEY` on 2026-10-11, 5.6.3). Its `jina_reader`
   plugin sends no key, so only `recover_page.py` uses `JINA_API_KEY`.
   Unrelated and older: its Signal adapter fails because signal-cli at
   127.0.0.1:18765 is unreachable.
6.6. reddit.com refused both WebFetch and Firecrawl scrape on 2026-10-09. Try
   Jina Reader, Crawl4AI and the archives before pausing. Since 2026-10-14 the
   self-hosted `firecrawl_scrape` (4h) fetches it (the commercial API still
   refuses: "we do not support this site").
6.7. Exa's keyless tier rate-limits (twice on 2026-10-11). Its notice arrives
   as normal content; `web-get` treats it as a failed rung, and an MCP client
   should do the same and move on. Since 2026-10-11 `web-get` uses the keyed
   REST API first (exa-api) and the keyless MCP only as its fallback; the
   client MCP configs send the key (5.6).
6.8. The Wayback rung can be slow (54 s, then 57 s, for one dewiki page on
   2026-10-11, over the 45 s HTTP default), so it has its own 120 s budget
   (`--wayback-timeout`, `$WEB_GET_WAYBACK_TIMEOUT`; 2.4). If it still times
   out on an archive-only page, retry with `--only wayback --wayback-timeout
   300` before pausing.
6.9. Archive routes found dead on 2026-10-11 (live probes; 2.11 has the fix):
   6.9a `archive.org/wayback/available` answers `{"archived_snapshots": {}}`
        for every URL, example.com included, with or without `timestamp=`.
        The CDX API (`web.archive.org/cdx/search/cdx`) and the `/web/<ts>id_/`
        redirect still work.
   6.9b r.jina.ai refuses web.archive.org to keyless callers: 403
        `AbuseAlleviationError`, "Anonymous access to domain web.archive.org
        blocked until Sun Sep 30 2035".
   6.9c An `id_` capture is served exactly as archived, gzip included, even to
        a client that sent no Accept-Encoding. `web-get` decodes gzip and
        deflate since 2026-10-11. Before that, every direct read came back as
        mojibake.
   6.9d Wayback rate-limits. After about 30 requests in five minutes, TCP
        connections to web.archive.org were refused for several minutes, and
        once the CDX API answered 503 "Temporarily Offline". Do not loop
        `--only wayback` over many URLs back to back.
   6.9e archive.today (`archive.ph`, `.today`, `.is`): the local proxy answers
        CONNECT 408, and a direct TCP connection to 107.189.8.227 times out. So
        `web-get` has no archive.today rung.
   6.9f A Wayback 404 is usually true. The g10 Reddit thread and the tailnet
        URLs have no capture: CDX lists none. The rung now says `no capture`
        and `not archived`.

## 7. Updating this file

A web chain change means any of: an MCP server added, removed or re-pointed in
one of the configs in section 3; a key rotated or moved; a provider dropped
from or added to `web-get`; a client gaining or losing a built-in web tool.
After one, re-read the configs, run `web-get check`, update this file and its
date, and update `SKILL.md` if the order of rungs changed.
