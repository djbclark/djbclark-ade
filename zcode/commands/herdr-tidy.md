---
description: close idle herdr panes safely (herdr-tidy scan → handoff → close, ledger)
skills: herdr-tidy
argument-hint: [pane id | --dry-run]
---

Follow the mounted `herdr-tidy` skill exactly: run `tidy.py scan`, perform the
precondition for each `handoff-then-close` pane (`tidy.py handoff`), close every
`close` verdict (`tidy.py close`), and report every pane with the action taken or
the one-line decision the operator has to make.

Arguments, if any (a pane id to limit the pass to, or `--dry-run`): $ARGUMENTS
