### Added

- `bin/ade-pin-interactive` tags non-worker (human-interaction) agents `ade.interactive=1` so `paseo ls --label ade.interactive=1` finds them. (#839)
- `bin/ade-pin-workspaces` applies Paseo's native sidebar pin to every non-worker window (`LEAD`/`MAIN`/`OTHER` and operator-started windows; `WORKER`/`WORKERS` boxes excluded) by driving the UI's own `workspace.pin.set` RPC through the bundled CLI client — the same mechanism as `bin/paseo-set-model`, since the `paseo` CLI and plugin SDK expose no pin command (upstream draft 23). (#839)
