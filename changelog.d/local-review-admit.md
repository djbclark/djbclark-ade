### Changed
- `bin/local-review` asks `load-watch admit --wait` before it starts Codex (`--load-wait SECONDS`, default 1800, env `LOCAL_REVIEW_LOAD_WAIT`; `--no-load-gate` skips it): a machine still too hot after the wait exits 75 and files no result, so `pr-wait --local-codex` reads `local-codex-missing`; a gate that cannot run warns and the review starts; the result records `load_gate` (#242)
