### Fixed

- `claude/hooks/bash_habits_gate.py`: the `paseo send` backtick check (gs-03, #733) also reads a send after `sudo-secretspec run --`, `doas`, `genv`, `gnohup`, `gstdbuf`, `gnice`, `unbuffer`, `chronic`, `mosh host` and `uv run` (the second wrapper batch of #733, which the changelog fragment of that PR did not list); `genv`, `gstdbuf`, `chronic` and `mosh` now have deny rows in `tests/test_bash_habits_gate.py`, so dropping one fails a test (#737).
