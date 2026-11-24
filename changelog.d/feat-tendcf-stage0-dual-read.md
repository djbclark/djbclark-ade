### Added
- Added `bin/ade_ops_paths.py` implementing Stage 0 dual-read resolution for the locked-in `tendcf` multi-site workspace contract (`~/tendcf-ops`, `TENDCF_OPS_ROOT`, `TENDCF_SITE` > XDG `active-site`, strict fail-closed slug validation with no sole-directory glob) alongside legacy `~/ops/site-*` fallback (#PR)

### Changed
- Updated `bin/lsp-root-guard` and `config/lsp-roots.toml` to include `~/tendcf-ops` (and custom `TENDCF_OPS_ROOT`) as LSP container roots (#PR)
- Updated `bin/skill-everywhere`, `bin/load-watch`, `bin/verifycmd`, `bin/bm-lint`, `bin/ops-post-checkout-guard`, `claude/hooks/bg_test_gate.py`, `claude/hooks/precompact_handoff.py`, `claude/hooks/adversary_marker_gate.py`, `claude/hooks/upstream_review_gate.py`, and `opencode-plugins/bg-cargo-gate.js` to dual-read `~/.local/bin/bgrun`, active `tendcf-{public,private}-<slug>` paths, and legacy `~/ops/site-*` paths without breaking existing `~/ops` layouts (#PR)
