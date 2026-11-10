# Paseo Telegram plugin — re-probe 2026-11-10

Queue Carried #18 (SF-Q16). Upstream draft: `docs/upstream-issues.md` §4
(Daaaaave/paseo-telegram#1, filed 2026-10-19 against npm `0.2.0`).

## Probe (Linux-safe, no live plugin install)

| Check | Result (2026-11-10) |
|---|---|
| npm `paseo-telegram@latest` | **0.2.3** (published 2026-10-21) |
| `paseo-plugin.json` `requirements.paseo` on 0.2.0 | `>=0.11.2 <0.12.0` (the install refusal) |
| `paseo-plugin.json` `requirements.paseo` on 0.2.3 | `*` (gate lifted; README: "does not restrict … by Paseo version") |
| `@getpaseo/client` / `@getpaseo/plugin` pins on 0.2.3 | still **0.11.2** |
| Daaaaave/paseo-telegram#1 | **OPEN**, 0 comments, last updated 2026-10-19 |
| Local `paseo` CLI / live daemon install | not available in this environment — no `paseo plugin add` attempted |

## Still blocked on the operator (order 11)

The version-range refusal that stopped the 2026-10-19 install looks fixed in npm 0.2.3,
but Carried #18's remaining work is outside this repo:

1. Live install on the operator's Paseo daemon (`paseo plugin add daaaaave/telegram` or npm).
2. Re-point `hermes-ping` and the approval buttons; keep Hermes's relay as rollback.
3. 2fado Telegram fallback waits on (1)–(2).

Do not install or re-point from an agent without an explicit yes.
