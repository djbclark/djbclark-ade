### Removed
- Moved the non-ADE skills and tools to site-djbclark with their history (`gmail-search`, `ovhcloud-api`, `aws-rules`, `terminus-kira`, `diskfree`, `bottom-config`, `setup-modern-cli`, `teach`, `todo`, `report`, `greptile`, `coderabbit-feeder`, `firecrawl`, `barnowl`, `bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`, `bin/codium-ai`, `bin/change-hermes`; `book-to-kb` stays there as `tools/book-to-kb`), unlinked the six symlinked skills (`forgejo`, `forgejo-ci`, `hyades-docker`, `sipb-llm-bench`, `sudo-secretspec`, `jevlike`), and deleted the vendored `siyuan*` skills; `bin/skill-everywhere` gained `~/ops/site-public-djbclark/skills` as its third root and warns on an absent root (slim-down E1) (#0).
- Deleted the dead and retired pieces: `bin/ade-scan-state*`, `bin/seat-name`, `bin/jev`, `bin/jev-eval` and the Jev shadow in `route_agent.py`, `claude/hooks/jev_effort_hook.py`, `skills/ralph-tui-orchestration`, `skills/skillopt-sleep-learned`, `plugins/herdr-sleeper` (Paseo's `agents.idleRuntimeCleanup` replaces it), `skills/cow-workspaces` and `bin/cow-pasture` (Paseo worktrees plus the committed `.worktreeinclude`), `vendor/gate-scripts` with the `openrouter` and `deepseek` routing rows; moved the `docs/ade-everywhere-*` series and `docs/apply-toolchain-prompt.md` to `docs/history/` (slim-down E2) (#0).
- Slim-down E9, the unconditional TUI retirements (agy, crush, pi, zcode, venicecode, qwen-code, goose, aider, kiro-cli, devin, muse, dsh, cline, copilot CLI):
  deleted `bin/agy-linux`, `bin/crush-context-check`, `bin/web-digest-mcp`, `bin/pi-skill-dedup`, `bin/zcode-key-auth` with its launchd plist and
  `tools/acp-run/zcode-denylist-shim.cjs`, the three Pi docs and `pi/prompts/hand.md`, the session-finder adapters for cline, copilot, crush, goose, muse,
  qwen and zcode, `skills/session-finder/nested_pty.py` (Kiro's terminal shim), and their tests. (#0)
- `acp-run` no longer drives copilot, qwen, devin, cline, pi, goose, zcode, agy, crush or kiro: their `AGENTS`/`YOLO_*`/`DENY_*` rows, strip and deny
  machinery and the per-agent effort and context branches are gone, `acp-run --list` shows claude, codex, opencode, cursor, hermes, omp and grok. (#0)
- `config/routing.toml` dropped the `pi`, `antigravity`, `antigravity-claude`, `antigravity-argon`, `zai`, `alibaba`, `crush`, `devin` and `copilot` services; the
  retired accounts are `never_route` in discovery, so an aiuse account for one is never surfaced as a dispatchable service. The `github` kind now has no pool. (#0)
- `bin/skill-everywhere` no longer links goose, pi, agy, copilot, qwen, devin, cline, muse or zcode. (#0)
- Removed `bin/proc-cpu-watch`, `bin/session-load-watch`, `bin/rumination-watch`, `bin/routing-recalibrate`, the `loadwatch` skill and the proc-cpu-watch, rumination-watch, routing-recalibrate, session-history-update and context-budget launchd plists (slim-down E5) (#0).

### Changed
- `bin/route_agent.py` and `bin/acp-dispatch` lost the Pi capacity gate, the `agy` model-family mapping, the agy report-path and resume special cases and the
  copilot, cline and zcode provider-map entries. (#0)
- Changed `load-watch`: it attributes a spike to a Paseo agent from `paseo ls -g --background --json` by working directory (the walk up stopping at the agent's own CLI), tells it with `paseo send --no-wait --json` (reading `.status`; `queued` is not delivered), sends work that several agents share or that it cannot attribute to the operator, and drops the relay.py channel and `watcher set --relay`/`--sid` (slim-down E5) (#0).
- Changed `context-budget-check`: `install`/`uninstall` removed (exit 2); it runs as a nightly Paseo schedule (J3) (#0).
- Changed `context-watch`: it no longer imports session-finder's `fleet.py` (slim-down E5) (#0).
