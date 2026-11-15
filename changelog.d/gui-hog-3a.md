### Added

- GUI-hog dialog, PR 3a (data and a dry-run trigger, no window; docs/gui-hog-dialog.md section M): `bin/gui_hog.py` and `bin/gui-hog status`. `load-watch admit --wait S` keeps a hold file under `~/.local/state/load-watch/held/` while it is refused (best effort, never changes the verdict or exit code); the 20 s sampler keeps a 5-minute per-app window (from `lsappinfo`, build subtrees and protected apps left out, `config/gui-hog.toml`) and, when a hold has lasted 3 minutes and desktop apps use 0.75 cores or 2 GB in sum, logs "would-show" to `gui-hog/dry-run.jsonl` at most once per 30 minutes. `load-watch admit-log summary` counts those lines; `LW_GUI_HOG=0` turns it off. Nothing is quit, frozen or signalled. (#722)

### Changed

- `skills/fan-out/SKILL.md` says what exit 2 means from a `load-watch` older than `--refused-since`, and the `release` exit-66 wording reads "released over 30 s ago, or expired" (#722).
