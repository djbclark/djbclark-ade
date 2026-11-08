# Workspace and tab naming (Paseo)

Trimmed 2026-11-06 (slim-down E4, ruling 12) from `skills/autorename/workspace-layout.md`. The herdr workspace/tab/pane layout pass
(`-t`/`-p` labels, `/autorename all`, `herdr_place.py`, configured workspaces, sleeper cycling) is gone; `git log -- skills/autorename/workspace-layout.md`
has it. Paseo is the only harness.

Operator hierarchy (2026-11-07): a **Project** groups one repo or a deliberately named repo set; a **Workspace**
is one claimed task worktree tabset (`paseo workspace ls --json`: `workspaceId`, `project`, `cwd`, …); an **agent tab**
is a Paseo agent in that workspace. Git worktree isolation and one writer per claimed checkout stay mandatory (AGENTS.md
order 9).

## Naming

1. **One workspace per genuine new isolated writing task** — create it with `paseo workspace create` or
   `paseo run --new-workspace …`, not per advisor, review round, or report folder.
2. **Reuse the task workspace** for implementer, reviewer, and advisor tabs on that worktree (`paseo run --workspace wks_…`
   or `acp-dispatch` with `--workspace` / `PASEO_WORKSPACE_ID` validated against `workspace ls`).
3. **Agent titles** stay short and identifiable; `paseo agent update ID --name "…"` or `paseo run --title T` at launch.
4. **Closing a tab** you mean to end: archive that agent (`paseo agent archive ID`).

The name shortener (`bin/seat-name`) was deleted 2026-11-06 (slim-down E2); keep names readable without an automatic cap.

## Renaming

- Workspace title: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<topic>-pw"`.
- Agent title: `paseo agent update "$PASEO_AGENT_ID" --name "<name>"` (read in the Paseo 0.15.3 source,
  `packages/cli/src/commands/agent/index.ts`, 2026-11-06; not run against a daemon), or set it at launch with `paseo run --title T`.
