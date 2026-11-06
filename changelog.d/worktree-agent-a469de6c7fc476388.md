### Removed

- Slim-down E9, the unconditional TUI retirements (agy, crush, pi, zcode, venicecode, qwen-code, goose, aider, kiro-cli, devin, muse, dsh, cline, copilot CLI):
  deleted `bin/agy-linux`, `bin/crush-context-check`, `bin/web-digest-mcp`, `bin/pi-skill-dedup`, `bin/zcode-key-auth` with its launchd plist and
  `tools/acp-run/zcode-denylist-shim.cjs`, the three Pi docs and `pi/prompts/hand.md`, the session-finder adapters for cline, copilot, crush, goose, muse,
  qwen and zcode, `skills/session-finder/nested_pty.py` (Kiro's terminal shim), and their tests. (#0)
- `acp-run` no longer drives copilot, qwen, devin, cline, pi, goose, zcode, agy, crush or kiro: their `AGENTS`/`YOLO_*`/`DENY_*` rows, strip and deny
  machinery and the per-agent effort and context branches are gone, `acp-run --list` shows claude, codex, opencode, cursor, hermes, omp and grok. (#0)
- `config/routing.toml` dropped the `pi`, `antigravity`, `antigravity-claude`, `antigravity-argon`, `zai`, `alibaba`, `crush`, `devin` and `copilot` services; the
  retired accounts are `never_route` in discovery, so an aiuse account for one is never surfaced as a dispatchable service. The `github` kind now has no pool. (#0)
- `bin/skill-everywhere` no longer links goose, pi, agy, copilot, qwen, devin, cline, muse or zcode. (#0)

### Changed

- `bin/route_agent.py` and `bin/acp-dispatch` lost the Pi capacity gate, the `agy` model-family mapping, the agy report-path and resume special cases and the
  copilot, cline and zcode provider-map entries. (#0)
