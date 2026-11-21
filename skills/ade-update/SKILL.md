---
name: ade-update
description: >-
  Keep this machine's djbclark-ade checkout current: fast-forward pull, relink
  missing skills, check CLAUDE.md and ~/.claude links, print the CHANGELOG
  delta. Use for /ade-update, "update the ADE", "pull the toolchain", "are my
  skills current", or after a new skill or changelog entry lands upstream.
---

# ade-update

Runs `~/src/djbclark-ade/bin/ade-update`, the one command that replaces the
hand-run "Update (this machine)" steps in the README. It changes nothing
outside the documented update steps: checkout fast-forward, skill links, the canonical
`~/.claude/helpers/graft-hooks.cjs` regular-file copy (0755) and its exclusive
`*.bak-<UTC stamp>` backups, plus the settings, GUI bundle and state steps described
in `bin/ade-update`. The helper comes from the committed target revision on `master`
at fetched `origin/master`; local helper edits, another branch, empty or invalid
source prevent installation. Node validates syntax without executing the helper.

## Steps

1. Read-only first: `~/src/djbclark-ade/bin/ade-update --check` (add `--json`
   for a machine-readable report). It fetches and changes nothing else.
2. Apply: `~/src/djbclark-ade/bin/ade-update`. It pulls with `--ff-only` of the
   commit it checked, relinks missing skills with `skill-everywhere`,
   creates or repairs the `~/.local/bin/<tool>` links of `BIN_LINKS` (`git-commit-own`, `load-watch`,
   `agent-id`; only a missing link or a stale one into a djbclark-ade checkout, never a regular file or a
   foreign symlink),
   installs the validated helper copy atomically with a backup, and prints
   the CHANGELOG entries new since `~/.local/state/ade/applied`.
3. Read the exit code and the report, not the prose: `0` current, `10` behind
   (under `--check`) or a skill, `CLAUDE.md`, `~/.claude` or `~/.local/bin` tool link still wrong, helper copy drift or refused helper source,
   `2` usage or a local modification blocks the pull, `3` the branch cannot
   fast-forward, `4` git, network, skill-everywhere, the helper validation tool or file I/O, or the state file failed.
4. Run it yourself, in the background when a fetch may be slow
   (`run_in_background: true`); never read its result through a pipe.
   Write `cmd > out.log 2>&1; echo "rc=$?" > out.rc` and read those files.

## Handling each exit

- `10` with skill rows: `~/src/djbclark-ade/bin/skill-everywhere --check NAME`
  shows the missing client; a row the script leaves alone is a real directory or
  another installer's link, so report it and do not overwrite it.
- `10` with a bin-link row: a regular file or foreign symlink sits at `~/.local/bin/<tool>`; report
  it with the printed fix, never overwrite it. A tool listed as skipped is not in this checkout yet.
- `2` or `3`: a local modification or diverged branch is the operator's work.
  Say which path or branch, and do not stash, reset or merge it. Ask the owner.
- `4`: fix the cause the message names, then re-run `--check`.

Outside the canonical checkout (a pasture, a second clone) `ade-update` is
report-only for skill links and the helper copy (no live writes or fix commands). Do not point it at another checkout to "fix" links.

## Done means

Re-run `ade-update --check` and expect exit `0`. Report the new HEAD and any
CHANGELOG lines. If an agent TUI still lacks a new skill, start a new session;
a present link does not prove a running TUI reloaded its catalog.

Docs: README "Update (this machine)"; `bin/ade-update` (usage text at the top);
`bin/skill-everywhere` (usage text at the top) for the link step.
