### Changed

- Rebased `docs/threat-model.md` onto native `paseo run` / `paseo send` /
  `Choice.dispatch` as today's entry points; marked `acp-dispatch` / `relay.py` /
  `acp-run` as Wave 6 transitional shims until ~2026-11-20; noted Pi as the sole
  general-purpose third-party TUI (#352).
- Rebased `docs/agent-guard-contract.md` the same way: native launch path first,
  shim `identity_refusal` / acp-run omp guard as transitional, omp/OpenCode not
  live launch targets (#352).
- Clarified `docs/review-boundary.md` read-only mode as Claude restricted tools
  (not a permanent acp-dispatch path) (#352).
