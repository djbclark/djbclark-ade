---
description: close idle herdr panes safely (herdr-tidy scan → handoff → close, ledger)
---

Follow the mounted `herdr-tidy` skill exactly: run `tidy.py scan`, perform the
precondition for each `handoff-then-close` pane (`tidy.py handoff`), close every
`close` verdict (`tidy.py close`), and report every pane with the action taken or
the one-line decision the operator has to make. Canonical copy:
`~/src/djbclark-ade/skills/herdr-tidy/SKILL.md`.

Arguments, if any (a pane id to limit the pass to, or `--dry-run`): $ARGUMENTS
