### Fixed

- `bin/route_agent.py`: an unmeasured second account of a pool (an expired reading, or an account that lists no applicable window) no longer lets the measured account open the pool for the plenty gate: a window either account could not measure stays unknown when accounts are folded, so the pooled service stays closed; `remaining` and the Fable cap keep the known reading (#698).
- `bin/route_agent.py`: the standalone import guard (one stderr line, exit 2) now covers only a missing sibling module (`ade_config`, `ade_gates`, `model_tiers` absent beside the file); an ImportError raised inside the repo copy keeps its traceback (#698).
