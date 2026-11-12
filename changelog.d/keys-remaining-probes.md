### Added

- `ade-install verify-key`: three more fixed metadata probes — cursor `GET /v1/me`, telegram `getMe` (documented token path) and github `GET /rate_limit`, whose probe reports the token expiry date GitHub returns via the allowlisted expiring marker; catalog rows `CURSOR_API_KEY`, `TELEGRAM_BOT_TOKEN` and `FIRECRAWL_GITHUB_PUBLIC_TOKEN` now carry `verify_argv`, while ZAI/Exa/Jina/Greptile stay deliberately probe-less with dated reasons (#580).
