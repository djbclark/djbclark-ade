---
description: close idle Orca terminals safely (herdr-tidy --host orca scan → handoff → close, ledger)
---

Follow section 6 of the mounted `herdr-tidy` skill exactly, with `tidy.py --host orca`:
run `tidy.py --host orca scan`, perform the precondition for each `handoff-then-close`
terminal (`tidy.py --host orca handoff`), close every `close` verdict
(`tidy.py --host orca close`; an exit 1 after "ledger written" means the terminal
survived, say so), and report every terminal with the action taken or the one-line
decision the operator has to make. Canonical copy:
`~/ops/site-private/skills/herdr-tidy/SKILL.md` (skill-everywhere hub).

Arguments, if any (a terminal handle, pane key or handle prefix to limit the pass to, or
`--dry-run`): $ARGUMENTS
