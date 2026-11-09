### Changed

- Ported `skills/loose` upstream-issue reader off `acp-run --perm deny` onto Claude CLI `-p` with no tools (Wave 6 follow-up) (#333).

### Fixed

- Hardened the `/loose` zero-tool reader: `--setting-sources ""` plus `disableAllHooks` so a hostile checkout's project hooks cannot run (#333).
