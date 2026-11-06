# `hand`: one name for the handoff skill in every TUI (2026-11-04)

Why: omp's built-in `/handoff` (`BUILTIN_SLASH_COMMAND_DEFS`, "Summarize the session into a handoff document and
compact in place") takes the name before any skill or command file, so typing `/handoff` in omp compacts the
context and never runs [`skills/handoff`](../skills/handoff/SKILL.md): no Tier 2 document, no Tier 1 pointer, no
successor. On 2026-11-04 the operator typed it twice and the journal shows two `compaction` entries with
`method: handoff` and no skill run. `hand` is not a built-in anywhere checked below.

## Mechanism

One thin skill, [`skills/hand`](../skills/hand/SKILL.md), reads and follows `handoff`. Installed everywhere by
`bin/skill-everywhere hand`. Where a TUI does not make a skill a bare `/name`, a wrapper file named `hand` calls it.

| TUI | You type | How | Built-in `hand`? |
|---|---|---|---|
| Claude Code | `/hand` | skill | none: official command reference, 121 commands, no `hand*` |
| omp | `/hand` | `omp/commands/hand.md` linked to `~/.omp/agent/commands/` | none: only `handoff`, no aliases of it |
| zcode | `/hand` | `zcode/commands/hand.md` linked to `~/.zcode/commands/` | none found in the install |
| opencode | `/hand` | `opencode/commands/hand.md` linked to `~/.config/opencode/commands/` | none found in the binary |
| Cursor, Copilot, Grok, Qwen, Cline, Antigravity | `/hand` | skill | none (official lists) |
| Hermes | `/hand` | skill route (read in code, not run live) | exact lookup: no. It has built-in `/handoff` (`hermes_cli/commands.py:106`), so Tab may complete `/hand` to it; type the full word |
| Codex | `$hand` | skill (`/prompts:hand` is deprecated, not installed) | none |
| Muse, goose, Grok Bot | UNVERIFIED | goose needs a `slash_commands` recipe entry in `~/.config/goose/config.yaml`; Muse's custom-command dir was not found; Grok Bot is not on this Mac | none found, lists incomplete |

`hand` with a focus or `paseo` behaves as `handoff` does, since the arguments pass through.
