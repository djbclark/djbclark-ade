---
name: skills-everywhere
description: >-
  Make a shared djbclark-ade skill available to every installed agent TUI, or
  check the current links. Use for /skills-everywhere and when a universal
  skill is missing from one client.
---

# skills-everywhere

Links a skill into every agent TUI. Content lives in exactly one place —
`~/src/djbclark-ade/skills/<name>/` for public skills (the default),
`~/ops/site-private/skills/<name>/` for private ones (only `1password`) —
and every TUI gets a **direct symlink** to it; no hub, no chains (collapsed
2026-10-14). Clients covered (the `targets` table in the script): Claude
Code, Codex, omp (oh-my-pi, `~/.omp/agent/skills`), Copilot, Cursor,
opencode, zcode, Grok, Qwen, Devin, Cline, Muse, Antigravity and Hermes:

```sh
~/src/djbclark-ade/bin/skill-everywhere <skill-name>...
~/src/djbclark-ade/bin/skill-everywhere --check <skill-name>...
```

The requested skill must already exist under
`~/src/djbclark-ade/skills/<skill-name>/SKILL.md` or the private tree.
The compatibility command `~/ops/site-private/bin/skill-everywhere` points
at this same canonical script.
Run `--check` first when diagnosing a missing client, and preserve links owned
by another installer. In link mode any chained link (same realpath, different
readlink) is collapsed to the direct link. A link being present does not prove
that a running TUI has reloaded its skills; start a new session when needed.
