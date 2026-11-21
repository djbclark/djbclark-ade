### Fixed

- Antigravity stays off Pi, now with a guard that is tested and case-insensitive (PR 881 review LOWs): `route_agent.pi_excluded()` compares the model namespace case-insensitively, `provider_models("pi")` and `bin/pi_defaults.py` both use it, and `tests/test_pi_defaults.py` exercises the skip with a Pi pool whose model is an `antigravity/*` id. (#PR)
