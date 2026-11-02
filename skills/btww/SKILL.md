---
name: btww
description: >-
  Remind the user which native side-question command this TUI has (Claude
  Code /btw, Codex /side, and so on), or say that it has none. Use for /btww,
  "btww", "btw", "side question", "what is the btw command here". Reply only;
  never answers the question itself.
---

# btww — which native side-question command does this TUI have?

A real side question (Claude Code's `/btw`) runs in a fork: it answers while
the main turn keeps streaming and stays out of the transcript. A skill cannot
do that, because it is an ordinary turn. So `/btww` does not answer the
question. It names the native command for the TUI you are running in.

## Rules

1. Identify your TUI from your own system prompt and harness (not by running a
   command). Look it up in the table.
2. Reply with **one or two lines, no tool calls**: the native command with
   its usage, plus the user's own question quoted back so it can be pasted
   (`/btw <question>`). If the TUI has none, say `No native side-question
   command in <TUI>; ask it as a normal message.`
3. Do not answer the question, edit anything, or change the task in progress.
   If a task was running, carry on with it.
4. Quote only your own TUI's row: its command spelling, alias and notes. Never borrow a note from another row (Muse's native command is `/side`, with `/btw` as the alias).
5. TUI not in the table: say it is not covered and that no native side-question
   command is known there.

## Table (verified 2026-11-01)

| TUI | Native command | Notes |
|---|---|---|
| Claude Code | `/btw <question>` | forked query, tools off |
| Codex | `/side` | ephemeral side conversation in a temporary fork; needs a started thread; Ctrl+C returns to the main thread |
| Antigravity `agy` | `/btw <question>` | one at a time (a second waits for the first) |
| Cursor `cursor-agent` | `/btw <question>` | tools disabled |
| Grok | `/btw <question>` | also works mid-message: `fix the loop. /btw what does WBC stand for?` |
| omp | `/btw <question>` | bare `/btw` opens side-question history. In omp, `/btww <question>` already runs it (`~/.omp/agent/commands/btww.md`, `side: true`); you only see this text through `/skill:btww` |
| Hermes | `/btw <question>` | CLI: `/btww <question>` is a `quick_commands` alias for it. Telegram and gateways: use `/btw` |
| Copilot | `/btw [question]` (alias `/ask`) | answer in a dialog, off the history, works mid-task, no tools; Esc dismisses; bare `/btw` reopens the last answer; not in remote sessions |
| opencode | `/btw <question>` | one-shot answer from session context, not added to the conversation |
| Qwen Code | `/btw <question>` or `?btw <question>` | separate API call on the last 20 messages; answer shown above the composer; main turn keeps going |
| Muse | `/side` (alias `/btw`) | starts a side conversation |
| zcode | none found | |
| Cline | none found | the SDK has a side-question call but 3.0.74 has no slash command for it |
| goose | none found | |
| Grok Bot | none found | |
| Devin | not installed, not checked | |

Canonical copy: `~/src/djbclark-ade/skills/btww/`. Wrappers: `zcode/commands/btww.md`, `omp/commands/btww.md`; the Hermes alias is in `agents/hermes/config.yaml.tmpl`.
