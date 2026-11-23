### Added

- Mac-side MIT Libraries scrape bridge (`bin/firecrawl_mit_bridge.py`, wired into `bin/firecrawl-router` via `FIRECRAWL_ROUTER_MIT_BRIDGE=pdf|all`, default `off`) for exact enrolled hosts on `POST /v1/scrape` and `POST /v2/scrape`, supporting both the `fetch.py --enrolled-only` + `pdftotext`/`pdfinfo` PDF lane and the `browserfetch.py` + `pandoc --sandbox`/`page.txt` Cloudflare/HTML lane with fail-closed Hyades fallback, scrubbed subprocess environments, concurrency caps, tunnel pre-flight, and 60 s botwall cooldown (#949)
- Configurable LLM extractor rung ordering via `FIRECRAWL_ROUTER_LLM_ORDER` (`default`, `oneshot-first`, `litellm,sipb`) in `bin/firecrawl-router` (#949)

### Fixed

- Restricted HTTP `202` bot-wall detection in `bin/firecrawl-router` `fallback_reason()` to missing or short markdown (`< 5000` chars) so full-length hydrated `202` pages (e.g. IEEE Xplore) stay on primary (#949)
