### Added

- `[[service]] allow_repos` / `allow_seats` in `config/routing.toml` scope a routing pool to named repos and seats; `opencode-go` is scoped to the `techno-euphora` repo and the `hermes` seat. Elsewhere `route_agent.py route|plan` skip it as repo-scoped (never a primary or an alternative) and `acp-dispatch` exits 2 even with `ACP_OPERATOR_APPROVED=route-override`. New `--seat` flag and `ROUTE_SEAT` variable name the calling seat; `policy --md` shows the scope. (#260)
- `[[service]] lifeline_floor_percent` and `min_headroom`: `clinepass` (cline) is re-enabled scoped to the `techno-euphora` repo and the `hermes` seat and refused while its headroom is under 40% or unmeasured, `route-override` included. (#260)

### Changed

- djbclark 2026-11-02, "fine if we run out of quota on agy omp codex zcode cursor grok, just not claude ocgo cline": those pools are spent down to empty. `[routing].plenty_min` 50 to 0, the codex and `antigravity-claude` estimate floors to 0, `frontier2_min_left` 60 to 0, per-service `min_headroom = 0.0`; the tendcf/nix2cf astra override is removed. The knob table is in `skills/model-routing/SKILL.md`. (#260)

### Removed

- cline is out of `[discovery].never_route` and the `operator_gated` lists, and acp-run no longer asks for `ACP_OPERATOR_APPROVED=cline`. (#260)
