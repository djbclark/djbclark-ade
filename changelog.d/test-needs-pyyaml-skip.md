### Fixed

- `tests/test_ade_client_wiring.py`: the four tests that name Hermes' per-server MCP rows skip with a reason when PyYAML
  is absent (`needs_yaml`), instead of failing on the documented `hermes/*` `unknown` fallback; CI keeps installing
  PyYAML (`uv run --with pytest --with pyyaml`), so nothing is skipped there and the fallback stays covered by
  `test_mcp_hermes_unknown_without_pyyaml`. (#808)
