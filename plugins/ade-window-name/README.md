# ade-window-name (Paseo plugin)

Names every new window (Paseo workspace) on this host `<KIND> <repo> (<work>)` ([docs/workspace-layout.md](../../docs/workspace-layout.md)),
so no agent has to remember. Before this, only `bin/ade-worker-run` (our own launches) and `bin/ade-tidy` (one repo, manual) applied the
scheme; a lead in another repo, the operator's own new chat and a plain `paseo run` kept Paseo's default names (operator, 2026-11-14).

## Hooks

| Hook (Paseo 0.16.0-beta.2 names) | Behaviour |
|---|---|
| `agent.create.after` | Gather facts for the agent's window, ask `bin/ade_ws_autoname.py`, and `workspaces.ref(id).setTitle(name)` on a `rename` answer. |
| `agent.turn.after` | The retry: same handler. A window still unnamed because the agent had no title at creation is named at the next turn; a decided window is remembered, so later turns cost nothing. |

Why not `workspace.create.before`: `paseo run --new-workspace` creates the window **before** the agent and sends no prompt, label or
title with it (`resolveRunWorkspace` in `packages/cli/src/commands/agent/run.ts`), so KIND and `<work>` are unknown there. Both hooks
are notifications (`waits: false`): a failure here can never block or delay an agent.

## Rules (decided in `bin/ade_ws_autoname.py`, on `bin/ade_ws_names.py`, the builder `ade-worker-run` and `ade-tidy` share)

1. **Default name = no title.** Paseo's workspace `title` is the user-set override; null (or blank) means the name is derived from the
   branch or directory (`master`, `my-repo`). Any title at all (a human's, `ade-worker-run`'s, Paseo's own generator's, ours) is never touched.
   The title is read again right before the write, so a name given in the meantime wins.
2. **First agent only.** The agent must be the earliest-created live, non-background agent in the window (`createdAt`); an agent joining a
   window does not name it. Background agents and windows are skipped.
3. **KIND.** `WORKERS` when the agent has a parent (`parentAgentId`) or an `ade.lead` label; otherwise `MAIN`. The `ade.placement` label
   (`main`, `workers`, `user`) overrides; **`USER` is never guessed**: it is what a lead connects the operator's agents into (tidy skill).
4. **`<repo>`** is the main checkout's name via git (a linked worktree `my-repo-x-wt` reads `my-repo`), else the directory's basename.
   A name that is not a valid window-name part (a space in the directory) leaves the window alone.
5. **`<work>`** is the agent's title, at most 50 characters at a word boundary, one line, no parentheses: a `worker <slice> <lead id>`
   title reduces to the slice, `LEAD|MAIN <repo> <work>` to the work, a leading `<repo> ` is dropped. No title yet: wait for the retry.

`bin/ade-worker-run` names its own windows right after the launch with an explicit `paseo workspace rename`: if this plugin named the
window first, that rename replaces the name; if `ade-worker-run` was first, rule 1 leaves its name alone.

## Install and configuration

`paseo plugin install /absolute/path/to/djbclark-ade/plugins/ade-window-name` (a plugin reload is enough; no daemon restart).
Dry run: `ADE_WINDOW_NAME_DRY_RUN=1` in the daemon's environment logs `would-rename` and renames nothing. `ADE_WS_AUTONAME_PY`
and `ADE_PYTHON` override the decision script and the interpreter (default: `<plugin dir>/../../bin/ade_ws_autoname.py`, `python3`).
Logs: `paseo plugin logs ade-window-name`, one line per event with `outcome` `renamed`, `would-rename`, `skip` (with `reason`) or `error`.

## Tests

`node --test server/name-lib.test.mjs` (also run by `tests/test_ade_ws_autoname.py`, with the decision script's own tests).

## Limit

A window created by Paseo's app with a first prompt gets an LLM-generated title asynchronously; if that lands before the first agent
exists the window already has a title (rule 1) and stays as generated. `ade-tidy --apply` still renames such a window.
