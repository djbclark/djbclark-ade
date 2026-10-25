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
opencode, zcode, Grok, Qwen, Devin, Cline, Muse, Antigravity and Hermes,
plus Grok Bot (`grokbot`, a rendered copy `ade-<name>` in
`~/agent-data/workflows/` on its Linux box, 2026-10-23):

```sh
~/src/djbclark-ade/bin/skill-everywhere --all
~/src/djbclark-ade/bin/skill-everywhere --check --all
~/src/djbclark-ade/bin/skill-everywhere <skill-name>...
~/src/djbclark-ade/bin/skill-everywhere --check <skill-name>...
```

## Default: reconcile the whole shared catalog

With no skill names, or when asked to make all skills available, use `--all`
(2026-10-25). It discovers every readable `*/SKILL.md` directly below the public
and private roots, including linked skill directories, once per name; public
wins a duplicate. Hidden/helper directories are excluded. It never discovers
skills from a TUI's destination tree or copies private skills into the public repo.

Run `--check --all`, then `--dry-run --all`, apply `--all`, and finish with
`--check --all`. Save the complete reports outside the repo and summarize any
missing/blocked target rows. The all-mode check exits 1 for any installed target
that is not directly linked/currently copied; non-installed targets are skipped.
Existing unrelated files and links remain untouched. `--all --remove` is refused.
For explicit names, keep the existing named check/apply/check flow.

For Codex, verify every discovered skill is readable through `~/.agents/skills/`
and resolves to its expected source, not just the named example. Compare the
current session's skill catalog when available; filesystem coverage does not
prove a running client's catalog refreshed. Never claim a missing skill when
it is already listed: read the listed `SKILL.md` and use it. A `/steps` chooser
limitation is separate from skill discovery and must be reported as such.

Add `--dry-run` (`-n`) to print what link or `--remove` would change, and
`SKILL_EVERYWHERE_ONLY=<bin>,...` to touch only those targets.

**On the Grok Bot box** (`/home/box`), `/skills-everywhere` means: run
`/home/box/agent-data/shared/skills-sync/sync.sh` (add `--dry-run` first),
which pulls `origin/master` and mirrors the skills chosen for Grok Bot. To
handle one skill by hand, use
`SKILL_EVERYWHERE_ONLY=grokbot bin/skill-everywhere <name>`. Never write into
an `ade-*` folder by hand; the next sync overwrites it.

The requested skill must already exist under
`~/src/djbclark-ade/skills/<skill-name>/SKILL.md` or the private tree.
The compatibility command `~/ops/site-private/bin/skill-everywhere` points
at this same canonical script.
Run `--check` first when diagnosing a missing client, and preserve links owned
by another installer. In link mode any chained link (same realpath, different
readlink) is collapsed to the direct link. A link being present does not prove
that a running TUI has reloaded its skills; start a new session when needed.

## Codex access diagnosis

Check the current skill catalog and read the listed `SKILL.md` before declaring
access broken. On this machine, Codex skills link through `~/.agents/skills/`
to the canonical ADE directory. If `/name` reaches the agent as literal text,
load that named skill and follow it; resolve a missing catalog entry at
`~/src/djbclark-ade/skills/<name>/SKILL.md` before asking for a restart.
Loading a named skill to diagnose access does not execute its workflow.

Also check `~/.codex/AGENTS.md` (or `$CODEX_HOME/AGENTS.md` when set), following
all symlinks. A healthy skills directory can coexist with a dangling global
instruction link. The shared home instructions live at
`~/ops/site-djbclark/home-agents.md`; repair a stale runtime link to that file.
Verify readability through the original Codex path after the repair. A running
session can read it immediately; automatic startup loading needs a new session.
