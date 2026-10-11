---
name: skills-everywhere
description: >-
  Make a shared djbclark-ade skill available to every installed agent TUI, or
  check the current links. Use for /skills-everywhere and when a universal
  skill is missing from one client.
---

# skills-everywhere

Use the machine-wide linker; it points every client at the canonical skill
checkout and does not copy files:

```sh
~/src/djbclark-ade/bin/skill-everywhere <skill-name>...
~/src/djbclark-ade/bin/skill-everywhere --check <skill-name>...
```

The requested skill must already exist under
`~/src/djbclark-ade/skills/<skill-name>/SKILL.md` or the private skill tree.
The compatibility command `~/ops/site-private/bin/skill-everywhere` points at
this same canonical script.
Run `--check` first when diagnosing a missing client, and preserve links owned
by another installer. A link being present does not prove that a running TUI
has reloaded its skills; start a new session when needed.
