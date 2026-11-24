### Added

- Added shared stdlib-only zero-subprocess Paseo loopback HTTP/MCP and WebSocket client `bin/ade_paseo_client.py` (with opt-in atomic `SnapshotCache` and `docs/ram-relief-p3.md` audit and consolidation guide) (#PR)

### Changed

- Converted looping `djbclark-ade/bin/` pollers (`ade-auto-permit`, `ade-net-resume`, `load-watch`, `ade-pi-stuck`, `ade_send_guard.py`, `ade_subagent_stalls.py`, `ade-progress`, `ade-pin-interactive`, `ade-archive-retired`, `deadline`) to query Paseo's loopback daemon API directly via `bin/ade_paseo_client.py` instead of spawning `paseo` CLI Node subprocesses, and unified `bin/ade_approval_window.py`'s `McpDaemon` onto `ade_paseo_client.McpClient` (#PR)
