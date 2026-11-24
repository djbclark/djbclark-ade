### Added

- Added `bin/mcp-lazy`, a stdlib-only lazy stdio MCP wrapper (Phase 2b part 2, queue #89) that serves `initialize`, `tools/list`, `prompts/list`, and `resources/list` from a hardened `0600`/`0700` discovery cache without spawning the wrapped server, spawns on demand for tool calls with `notifications/tools/list_changed` refresh, reaps idle children when nothing is in flight or subscribed, recovers cleanly from child crashes, and enforces Adversary L3 path/`$HOME`/cache hardening (#PR).
- Wired `bin/ade-update` (step 3e) to install `bin/mcp-lazy` as a standalone `0755` copy at `~/.local/libexec/ade/mcp-lazy` (never a symlink into the checkout) from the authorized `origin/master` revision (#PR).
