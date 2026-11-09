# `hand`: one name for the handoff skill in every TUI (2026-11-04; Pi sole-TUI 2026-11-09)

Why the short name: retired **omp**'s built-in `/handoff` (`BUILTIN_SLASH_COMMAND_DEFS`, "Summarize the session into a
handoff document and compact in place") took the name before any skill or command file, so typing `/handoff` in omp
compacted the context and never ran [`skills/handoff`](../skills/handoff/SKILL.md): no Tier 2 document, no Tier 1
pointer, no successor. On 2026-11-04 the operator typed it twice and the journal shows two `compaction` entries with
`method: handoff` and no skill run. `hand` is not a built-in anywhere checked below. omp and OpenCode are **retired as
live TUIs** under the Pi sole-TUI policy (2026-11-09); their `/hand` wrappers stay in-repo as archived artifacts only
(`omp/commands/hand.md`, `opencode/commands/hand.md`). Prefer Paseo's `paseo-handoff` for a fresh agent; `/hand` remains
the ADE compatibility alias ([old way versus new way](old-way-new-way.md)).

## Mechanism

One thin skill, [`skills/hand`](../skills/hand/SKILL.md), reads and follows `handoff`. Installed on every current local
TUI by `bin/skill-everywhere hand` (Claude Code, Codex, Pi, Cursor, Hermes; see [skill-everywhere.md](skill-everywhere.md)).
Pi shares `~/.agents/skills` with Codex: the installer links that dir when `pi` (or `codex`) is on `PATH`
(PR restoring the Pi target). omp/OpenCode are no longer skill-everywhere targets.
Where a TUI does not make a skill a bare `/name`, a wrapper file named `hand` calls it.

| TUI | You type | How | Built-in `hand`? |
|---|---|---|---|
| Claude Code | `/hand` | skill | none: official command reference, 121 commands, no `hand*` |
| Pi | `/hand` | skill via `~/.agents/skills` (shared with Codex; sole third-party TUI since 2026-11-09) | none found for the short name |
| Cursor | `/hand` | skill | none (official lists) |
| Hermes | `/hand` | skill route (read in code, not run live) | exact lookup: no. It has built-in `/handoff` (`hermes_cli/commands.py:106`), so Tab may complete `/hand` to it; type the full word |
| Codex | `$hand` | skill (`/prompts:hand` is deprecated, not installed) | none |
| Grok Bot | UNVERIFIED | Grok Bot is not on this Mac | none found, lists incomplete |

### Retired TUI rows (history only; not skill-everywhere targets)

| TUI | You typed | How (archived) | Built-in `hand`? |
|---|---|---|---|
| omp (retired 2026-11-09) | `/hand` | `omp/commands/hand.md` linked to `~/.omp/agent/commands/` | none: only `handoff`, no aliases of it — the collision that forced the short name |
| opencode (retired 2026-11-09) | `/hand` | `opencode/commands/hand.md` linked to `~/.config/opencode/commands/` | none found in the binary |

`hand` with a focus or `paseo` behaves as `handoff` does, since the arguments pass through.
