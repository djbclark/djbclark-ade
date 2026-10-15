# Firecrawl: commercial API vs self-hosted on SIPB Hyades (2026-10-14)

**Recommendation: use both, self-hosted first.** The self-hosted instance matched the
commercial API on content (15 of 16 pages each, different single failures) with no rate
limit and no credits. The commercial API is the scarce resource: its free plan allows
about 10 requests a minute and 1000 credits a month, and the first account was already
overdrawn (−997 credits) before this test. So the order should be the reverse of
"commercial, with self-hosted when rate-limited": **self-hosted primary, commercial as
the fallback** for the three things self-hosting cannot do (below).

## Setup

1. **Commercial:** `https://api.firecrawl.dev` v2, a fresh free-plan key
   (`FIRECRAWL_API_KEY` in sudo-secretspec; 1025 credits at the start, 988 at the end).
2. **Self-hosted:** Firecrawl 2.11.519 on Hyades as six microVMs on one shared network
   (Redis hub, RabbitMQ, NuQ Postgres, Playwright, the API harness with its workers, a
   Caddy bearer-token gate) at `https://djbclark-firecrawl.sipb.cloud`
   (`FIRECRAWL_SELFHOST_API_KEY`). Deploy files and notes:
   `skills/hyades-docker/examples/firecrawl/` (`deploy apply|up|down|status`).
3. **Shared MCP server ("the universal proxy"):** `firecrawl-mcp` 3.23.7 on
   `127.0.0.1:18804/mcp` (site-djbclark `roles/shared_mcp`, `just
   shared-mcp-apply-secrets`), pointed at the self-hosted instance and registered in
   Claude Code, Codex, Cursor, opencode and agy. Tested with scrape, search and crawl
   calls through it.
4. **Suite:** `bench/firecrawl/fc-bench`: 16 single-page scrapes (`maxAge: 0`, so the
   commercial cache cannot help), 5 parallel scrapes, map, a 5-page crawl, a 5-result
   search. Raw results in `bench/firecrawl/results/`.

## Results

| Page | Category | Commercial | Self-hosted |
|---|---|---|---|
| static | static HTML | ok, 0.8 s, 959 chars | ok, 0.7 s, 958 chars |
| python-docs | docs | ok, 1.1 s, 42,122 chars | ok, 1.9 s, 43,612 chars |
| wikipedia | wiki | ok, 0.6 s, 52,343 chars | ok, 2.4 s, 71,156 chars |
| github | app page | ok, 6.3 s, 36,250 chars | ok, 4.5 s, 35,607 chars |
| hn | news list | ok, 1.0 s, 15,398 chars | ok, 2.2 s, 18,103 chars |
| bbc | news site | ok, 8.3 s, 17,111 chars | ok, 5.3 s, 19,789 chars |
| books | e-commerce | ok, 1.9 s, 9,116 chars | ok, 1.2 s, 9,222 chars |
| js-render | client-side JS | ok, 0.9 s, 1,505 chars | ok, 1.2 s, 1,574 chars |
| js-delayed | JS, 10 s delay | ok, 13.0 s, 1,505 chars | ok, 13.1 s, 1,574 chars |
| stackoverflow | Q&A, Cloudflare bot check | ok, 6.2 s, 161,404 chars | **fail** (500: all engines failed, Cloudflare challenge) |
| reddit | bot-guarded | **fail** (403: "we do not support this site") | ok, 4.2 s, 64,117 chars |
| medium | paywall/JS | ok, 2.9 s, 20,774 chars | ok, 3.4 s, 21,479 chars |
| cloudflare | CDN-fronted | ok, 1.7 s, 3,372 chars | ok, 3.7 s, 3,396 chars |
| whatwg | very large page | ok, 1.9 s, 559,976 chars | ok, 3.9 s, 660,752 chars |
| pdf | PDF (4 pages) | ok, 1.0 s, 25,054 chars | ok, 0.8 s, 25,145 chars |
| http-404 | error page | ok, 0.6 s | ok, 0.8 s |

| Test | Commercial | Self-hosted |
|---|---|---|
| Scrapes passed | 15/16 | 15/16 |
| Median time, pages both passed (14) | 1.4 s | 2.3 s |
| 5 parallel scrapes | **0/5: all HTTP 429** | 5/5 in 1.9 s |
| Rate limit hit during the suite | yes, after 10 requests (~10/min) | none |
| map (books.toscrape.com) | 156 links | **0 links** (sitemap only) |
| crawl, 5 pages | 6.8 s | 13.5 s |
| search, 5 results | 0.8 s | 2.0 s (DuckDuckGo scraping) |
| Cost of this suite | 32 credits | none (Hyades is free) |

Notes on the table:

1. The commercial scrapes after the 10th request needed a second, paced run (the 429
   message says "retry after 20s"). Its PDF parse dropped the form's title line; the
   self-hosted one kept it.
2. Self-hosted Markdown is often longer for the same page (Wikipedia 71k against 52k):
   its main-content extraction keeps more page furniture. Quality was otherwise
   equivalent on every page that both fetched.
3. Self-hosted latency includes the trip through Hyades' Caddy and our gate; the API and
   Playwright run on 4 shared vCPUs.

## What self-hosting cannot do

1. **Cloudflare challenge pages** (Stack Overflow here): the commercial service has a
   proxy network and a stealth engine ("fire-engine"); ours fetches from an MIT
   datacenter address with no proxy.
2. **map** on a site without a sitemap: the commercial service answers from its own URL
   index; self-hosted map reads sitemaps only (its log says so).
3. **Availability:** Hyades aims for at most 5 minutes of downtime a month, applies
   updates every Monday at 4:20, and runs on one server.

Search worked on both; the self-hosted one scrapes DuckDuckGo, which can block a busy
IP. Firecrawl's self-hosting guide recommends a SearXNG instance instead (one more
microVM plus `SEARXNG_ENDPOINT`), worth adding if search starts failing.

## Problems found and fixed on the way

1. **Playwright never worked at first:** its anti-SSRF proxy listens on port 0, which
   libkrun's TSI networking makes unreachable (libkrun#818); every page failed with
   `ERR_PROXY_CONNECTION_FAILED` and fell back to plain fetch (no JavaScript). Fixed with
   our `loopback-port-shim` in a derived image (`build-playwright-image`).
2. **One Cloudflare-fronted page wedged Playwright for good:** Chromium's network thread
   called `getsockopt(SOL_IPV6, ...)` on a UDP socket and the guest kernel oopsed in
   `tsi_stream_getsockopt` (open upstream: libkrun/libkrunfw#140). Every later page timed
   out (the first self-hosted run, `results/selfhost-20261015T000004Z.json`, shows it:
   12/16 with 30 s stalls). Fixed in the shim (problem 5, commit b5f2cd3); the second run
   is the one in the tables.
3. Skill fixes made during the work: `hyades-registry` gained `HYADES_ENGINE=crane|skopeo`
   (VM-free pushes from this Mac); `hyades -` sends console commands on stdin so secrets
   stay out of the shared host's process list, and drops blank lines (the console repeats
   the previous command on an empty line); the `tmprun` stdin pitfalls (commands eat the
   script, 4 KB line limit) are written down.

## Recommendation in detail

1. **Primary: self-hosted**, through the shared `firecrawl` MCP server, as now. No rate
   limit, no credits, Reddit works, JavaScript rendering works, and it is one shared
   instance for every agent.
2. **Fallback: commercial**, for Cloudflare-challenge pages, `map`, and outages of the
   Hyades stack. Keep the claude.ai Firecrawl connector and `FIRECRAWL_API_KEY` for this.
3. **Automatic fallback is not built yet.** `firecrawl-mcp` talks to one API. The clean
   way is a small router on the shared port that sends each request to the self-hosted
   API and retries on the commercial one on a 5xx, a timeout, a Cloudflare 403 or an
   empty map, and never the other way round for a 429. That is a new tool, so where it
   lives is djbclark's call.
4. **Watch the outward-facing side:** the crawler fetches from MIT's address space on a
   free SIPB service that excludes commercial use. Keep agent volume modest; heavy crawls
   belong on the commercial API.
5. **Resource cost on Hyades:** about 7 GB RAM of the 32 GiB quota (API 4.1 GB,
   Playwright 1.2 GB, the rest under 0.6 GB each) and 4.4 GB of images of 40 GiB, with
   six of the ten microVM slots.
