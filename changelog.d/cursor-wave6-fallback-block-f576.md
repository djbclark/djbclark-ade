### Added

- `bin/route_agent.py` enforces Argon `fallback_block` on native `paseo run` emit (`Choice.emit_dispatch`) and launch (`admit --provider … --kind …`, exit 2); shim delete can drop the dispatch-time re-check (#415).
