**Why:** the playwright service's SSRF proxy listens on port 0. In some sandboxes a port-0 listener can't be connected to; in a libkrun microVM (containers/libkrun#818) every page load fails with `ERR_PROXY_CONNECTION_FAILED` and Firecrawl falls back to plain fetch. A fixed port avoids it.

**What changed:** optional `SSRF_PROXY_PORT` env var for that proxy. Unset or `0` keeps today's behavior (any free port, `127.0.0.1` only).

**Checks run** (`apps/playwright-service-ts`, macOS, Node 26):

- `pnpm install --frozen-lockfile`, `pnpm build` (tsc), `prettier --check api.ts`
- `SSRF_PROXY_PORT=39123 PORT=39124 node dist/api.js`: `lsof` shows the proxy on `127.0.0.1:39123`; `POST /scrape {"url":"https://example.com"}` returns `pageStatusCode` 200, title "Example Domain"; `POST /scrape {"url":"http://127.0.0.1:39124/health"}` is still blocked with 403 ("resolves to a private/internal address").
- Without the variable the proxy gets a random port as before (`127.0.0.1:55567`).

**Impact:** none unless the variable is set. No security change: the proxy still binds to loopback and the private-address check is unchanged.

_Prepared with an AI coding assistant; reviewed by me._
