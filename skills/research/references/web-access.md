# Web access (2026-11-12)

Use the shared Firecrawl MCP first. `bin/ade-web` is the small shell fallback
when the host lacks a suitable tool; it does not replace the router or restore
retired `web-get`/`web-digest`.

```sh
bin/ade-web search 'query' --json
bin/ade-web fetch https://example.com --json
bin/ade-web check --json
```

Fetch order: Firecrawl via loopback router `http://127.0.0.1:18805`, keyless
Jina Reader, keyed Jina if `JINA_API_KEY` exists, direct PDF download and
`pdftotext` when PDF magic matches, Wayback latest raw `id_`, CDX latest successful
capture and raw `id_`, then optional `--crwl` (requires `crwl` on PATH).
Archived copies are historical evidence; cite the provider and verify freshness.
Search uses Firecrawl `/v2/search`, then keyed Jina Search only if configured.
No commercial Firecrawl, Exa or Parallel account is created by this tool.

Plain stdout is the body; stderr records `provider=... status=...` for each rung.
`--json` emits `body`, `provider`, `truncated`, `attempts` and `exit_code`.
Empty, short block/soft-404 pages, page HTTP errors and malformed responses fail
the rung. Explicit truncation and the byte cap keep the ladder walking.
Exit 0 means a usable copy; exit 5 means all rungs failed; exit 6 returns the
longest truncated copy when no complete copy was found. **Both 5 and 6 mean
pause dependent research, report the attempts, and recover access before synthesis.**
Heuristics cannot prove that a provider silently returned the entire source.

`--timeout` (default 15 seconds, maximum 300) bounds each network or subprocess
operation. `--max-bytes` (default 2000000, range 1024..20000000) bounds response
reads and output bodies. `check` walks every fetch rung using `--url` (default
`https://example.com`); absent PDF support for a non-PDF is expected. Exit 0 means
at least one usable copy, not that every provider is healthy.

Provider bases can be overridden with `ADE_WEB_FIRECRAWL_URL`,
`ADE_WEB_JINA_URL`, `ADE_WEB_JINA_SEARCH_URL`, `ADE_WEB_WAYBACK_URL`.
Bases require HTTPS or loopback HTTP, without userinfo/query/fragment.
The Firecrawl router's open loopback listener needs no key; a token-gated listener
can use `ADE_WEB_FIRECRAWL_KEY`. Keys come only from existing environment variables
or an operator-configured `sudo-secretspec` invocation; never put them in argv.
Keyed requests refuse redirects and provider error bodies are never logged.
