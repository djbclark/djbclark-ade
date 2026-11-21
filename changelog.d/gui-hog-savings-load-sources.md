### Added

- `bin/gui-hog suggest`: reads the history of measured freezes and the dialog's would-show lines and proposes apps for the never-auto list (`[freeze.auto] skip`: a `[freeze.depends]` note such as Beeper's MCP API or CodexBar's aiuse readings, or negligible savings) and for the new always-freeze list; read-only, it prints its evidence and edits nothing. (#872)
- GUI-hog measured savings: every freeze records the app's freeable cores and RSS and the system window just before it, and its resume writes a `freeze-result` event (load, compressor, pageins, swapins over the freeze against the window before). A SIGSTOP frees CPU, not RSS; the docs say so (`docs/gui-hog-dialog.md` Q1). (#872)
- `[freeze.auto] always` (ships empty): apps frozen without asking, with no dialog row; Resume stays in the Frozen list and menu, the never-auto list wins, and a protected app or one hosting a build or terminal is never quiet. (#872)
- The dialog and `gui-hog status` list the real load sources (builds and test jobs, agent sessions, apps, system processes) with cores, RSS and share, a build's tree grouped under its root and owner; display only, never a Freeze button for a build or a protected app. (#872)

### Fixed

- GUI-hog keep-running rules name one exact executable (matched on the kernel path, never as a prefix; an absolute directory is refused), the auto-freeze reads its start times in one batch call and only while a build is held and leaves out an app that started after the table was read, and the stale `config/gui-hog.toml` comments are corrected (the #859 adversary lows). (#872)
