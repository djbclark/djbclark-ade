### Changed

- Decoupled Paseo workspace, window, and tab display names from machine metadata across ADE per the 2026-11-25 operator ruling (Carried #126): `bin/ade_ws_names.py` now generates concise human-readable tab names (`worker <slice> [wt: ...]`) without embedding the 36-char lead UUID and stores structured window metadata (`entries`: `box`, `repo`, `lead`, `cwd`, `work`) in `<lead>.windows.json`, `bin/ade-worker-run` emits `ade.box` and `ade.repo` labels and resolves `--placement lead`, box reuse, and `archive-window` from structured metadata instead of display names, `bin/ade_self_session.py` records durable `retired` state and `ade.retired`/`ade.retired_to` labels on retired predecessors, and `bin/ade-tidy`, `bin/ade_ws_autoname.py`, `plugins/ade-window-name`, `bin/ade-archive-retired`, `bin/ade-pin-interactive`, and `bin/ade-pin-workspaces` classify from structured labels and state records first (#PR)

### Fixed

- Fixed `bin/ade-worker-run --placement lead`, worker box reuse, `archive-window`, `bin/ade-tidy`, `bin/ade-archive-retired`, `bin/ade-pin-interactive`, and `bin/ade-pin-workspaces` losing ownership or refusing/misclassifying windows and tabs renamed by a human (#PR)
