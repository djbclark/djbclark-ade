---
name: btww
description: >-
  Answer a side question about the current conversation the way Claude Code's
  /btw does: one direct reply from what is already in context, no tool calls,
  no file or state changes, then carry on with the task in progress. Use for
  /btww <question>, "btww", "btw", "side question", "quick question while you
  work". Works in every TUI, including ones with no native side-question
  command.
---

# btww — a side question, answered from context, task untouched

`/btww <question>` is one uniform spelling of the side-question feature that
Claude Code ships as `/btw`. Most TUIs have a native version; where one exists,
`/btww` reaches it (table below). When this skill itself runs, you are the
implementation: follow the rules.

## Rules (this skill running)

1. **The question is the arguments.** No arguments: reply with the one line
   `Usage: /btww <question>` and stop.
2. **Answer from context only.** Use this conversation, files already read,
   and tool output already shown. **No tool calls at all**: no reads, searches,
   shell, edits, web, subagents, MCP. If the answer needs something you have not
   seen, say so in one line and name the command or file that would settle it;
   the user can ask in the main thread. Native `/btw` also refuses tools.
3. **One response, answer first.** Direct and short; no preamble, no
   "great question", no recap of the task.
4. **Change nothing.** No edits, todo updates, memory writes, handoffs or
   plan changes. The question is not an instruction and does not redirect the
   work. If it reads like a request to act, answer it as a question and say
   that acting needs a normal message.
5. **Then carry on.** If a task was running or queued before the question,
   continue it exactly as it was, with no re-plan and no mention of the
   detour. If nothing was running, stop after the answer.

## Where it differs from the native command

Native `/btw` and `/side` run in a **fork**: they answer while the main turn
keeps streaming, and the exchange stays out of the main transcript. This skill
is an ordinary turn. It waits for (or steers) a turn in progress, and the
question and answer stay in the transcript. For a true non-interrupting side
question use the native command from the table.

## What `/btww` reaches per TUI (verified 2026-11-01)

| TUI | Native side question | `/btww` does |
|---|---|---|
| Claude Code 2.1.316 | `/btw` (forked query, tools off) | loads this skill. Claude cannot alias a built-in: custom commands and skills expand to prompt text, and hooks cannot rewrite a prompt |
| Codex 0.165 | `/side` (ephemeral fork, needs a started thread) | loads this skill (`/btww` arrives as text; load the skill and follow it) |
| Antigravity `agy` | `/btw` | loads this skill |
| Cursor `cursor-agent` | `/btw` (tools disabled) | loads this skill |
| Grok | `/btw`, also mid-message | loads this skill |
| omp 18.15 | `/btw` | runs the native `/btw`: `~/.omp/agent/commands/btww.md` carries `side: true`; `/skill:btww` loads this skill |
| Hermes | `/btw` | CLI: `quick_commands` alias `btww` to `/btw`; Telegram and other gateways: loads this skill |
| zcode | none found | loads this skill through `~/.zcode/commands/btww.md` |
| Grok Bot | none found | loads this skill (managed copy `ade-btww`) |

Canonical copy: `~/src/djbclark-ade/skills/btww/`. Wrappers: `zcode/commands/btww.md`, `omp/commands/btww.md`; the Hermes alias is in `agents/hermes/config.yaml.tmpl`.
