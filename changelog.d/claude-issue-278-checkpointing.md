### Added

- Added `plugins/ade-recovery` (2026-11-04), a passive Paseo plugin that records recovery evidence for interrupted agents: identity, a sha256 of the native handle, the last 20 turns' outcome codes, read-only git evidence (head, base, tracked and untracked fingerprints) and interruption history, under `<state base>/ade/<serverId>/ade-recovery/recovery/v1/`. It registers five notification hooks only and never sends, reloads, archives, creates or interrupts an agent (issue 278, [docs/checkpoint.md](docs/checkpoint.md) section G). (#290)
- Added `bin/paseo-checkpoint` (2026-11-04), a read-only `list` and `show` of those records with the verdicts `resumable-native`, `needs-review` and `do-not-resume` and their exit codes, cross-checked read-only against Paseo's own agent records and server id (issue 278). (#290)

### Changed

- Changed `docs/checkpoint.md` sections F and G (2026-11-04): F5 item (3) now names `plugins/ade-recovery`, and section G records the interim ade-recovery v1 implementation, what it captures and never does, its hooks and record location, its verdicts, and the D1 probes it depends on (issue 278). (#290)
- Changed `acp-dispatch --checkpoint` to be frozen until D5 replaces `acp-dispatch`, with no new features (2026-11-04; its resume ladder is superseded by checkpoint F5) (issue 278). (#290)

### Fixed

- Fixed `plugins/ade-recovery` evidence gaps found by adversarial review before merge (2026-11-04): renames, submodule commits and working-tree edits, mode and symlink changes, and file names with a newline, leading quote or trailing CR now change the tracked fingerprint; host comparison uses a stable machine id; `bin/paseo-checkpoint` cross-checks Paseo's own agent record (`paseo-archived`, `paseo-record-newer`, `paseo-record-missing`, `other-server`) and activity Paseo saw while the plugin was down or dropping events (compared by `lastActivityAt`, else `updatedAt`) is a sticky `unobserved-activity` interruption; uninitialised gitlinks no longer exhaust the submodule scan budget, and an unsafe filter-driver name fails closed (issue 278). (#290)
