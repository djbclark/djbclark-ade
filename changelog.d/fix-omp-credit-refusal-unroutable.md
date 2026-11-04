### Fixed

- `bin/acp-dispatch` classifies Anthropic's "credit balance is too low" API refusal as `credit` and records the pool exhausted via `aiuse note-exhausted` (reset from the row's `resets_at` / `expires_at` / `available_at` / `credits` stamp, else a fixed 6 h back-off), so `route_agent.py` stops offering omp until the reset instead of re-choosing it after a preflight exit 5 (#287).
