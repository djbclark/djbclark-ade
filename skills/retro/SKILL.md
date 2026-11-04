---
name: retro
description: >-
  Write a short retrospective for a date window from the facts in git and
  GitHub. Runs bin/ade-retro --since DATE (merged PRs, changelog entries,
  handoffs, gaps), then summarizes what shipped, what recurred, what to queue
  in docs/queue.md and which instruction-file rules are worth adding. Use for
  /retro, "retro since DATE", "what did we ship this week", "weekly review".
---

# retro — what shipped, what recurred, what to queue

Canonical copy: `~/src/djbclark-ade/skills/retro/` (git: `~/src/djbclark-ade`). Claude Code wrapper: `~/src/djbclark-ade/claude/commands/retro.md`.

1. Run `bin/ade-retro --since YYYY-MM-DD` (add `--until`, `--repo OWNER/NAME`, `--json` as needed). Default window when none is given: the last 7 days. Exit 3 means a source failed (usually `gh`); the partial report is still valid, so read its `D. Gaps` and say which source is missing.
2. Read the whole output: A merged PRs, B changelog entries, C handoffs, D gaps.
3. Write a short retrospective with these headings, each item labelled per standing order 5 (`A1`, `A2`, ...):
   - **What shipped**: grouped by theme, each with its PR number.
   - **What recurred**: the same failure, conflict or review finding in more than one PR or handoff.
   - **What to queue**: concrete items for `docs/queue.md` (check it first so nothing is duplicated).
   - **Instruction-file rules worth adding**: only rules a recurring problem justifies, each naming the file it belongs in.
4. Optionally format the result with the `report` skill.

Read-only: the tool writes nothing, and the skill writes nothing except the retro note the operator asks for. Queue entries and rule edits are proposals until he says yes (order 11 for anything outside djbclark-ade).
