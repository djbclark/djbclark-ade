### Added

- `antigravity-neon` service: route Gemini 4 Neon through Paseo's antigravity provider on the shared Gemini 5-hour/weekly window, as a frontier fallback (behind gpt-6-astra and Fable) and last-resort research pool; `[dispatch].frontier_models` now names `gemini-4-neon`. `bin/route_agent.py` maps `gemini-4-neon*` to the `gemini` pool family (Neon is not Argon's separate weekly window). (#815)
