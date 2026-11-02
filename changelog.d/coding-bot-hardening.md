### Added

- `coding-bot` got a hardened protocol: a per-message nonce the bot must echo, claim files and a scheduled-sweep heartbeat, exit 5 (not picked up) and 6 (stale heartbeat, `--force`), one Hermes ping per id and kind, `status ade-N` and `bootstrap --sweep`. (#TBD)
