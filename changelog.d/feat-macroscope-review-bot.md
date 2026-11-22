### Added

- `config/review-bots.toml` lists Macroscope (`macroscopeapp[bot]`, type `Bot`) as a must-triage reviewer like CodeRabbit; only its `Macroscope - Correctness Check` run is a pending signal, and a head with no Macroscope check never waits or blocks (#PR)
- `skills/macroscope-review`: how to request one `@macroscope-app review` and triage it under the operator's US$100 non-renewable per-KB budget (manual only, spend recorded), with the per-KB price table, the settings that stop automatic reviews, and the upstream CLI skills (not installed) (#PR)
- `tests/test_review_bots.py` covers Macroscope identity, spoofs, the check-run states and a scan that no repo tool contains the trigger comment (#PR)
