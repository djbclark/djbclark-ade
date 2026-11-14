# ade-window-name (Paseo plugin)

Names every default-named window (Paseo workspace) on this host, when its first agent is created (or next ends a turn): `<KIND> <repo> (<work>)` ([docs/workspace-layout.md](../../docs/workspace-layout.md)),
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

1. **Default name = no title, or Paseo's own prompt title.** Paseo's workspace `title` is the user-set override; null (or blank) means the
   name is derived from the branch or directory (`master`, `my-repo`). A window created with a first prompt (the app's new-workspace
   screen, a plain create) is pre-titled with the prompt's first line, which Paseo itself still treats as default (it replaces a title equal
   to that line with a generated one, `workspace-auto-name.ts`); so a title equal to the first agent's own title counts as default too, but only within five minutes of that agent's creation (a window and a
   tab given the same text on purpose, `paseo workspace rename X` plus `paseo agent update --name X`, stays as it is; no `createdAt`, or one more than a minute in the future, counts as old; the age is the agent's, so a window named on purpose long ago whose agents were all archived can be renamed when a new first agent carries the same title).
   A title already in the scheme (`<KIND> <repo> (<work>)`) is never re-wrapped, whatever the tab is called. Any other title (a human's, `ade-worker-run`'s, ours) is never touched. A launch with an explicit agent `--title` and a prompt keeps Paseo's prompt/generated window title (the two differ, so the window reads as named); name that one with `ade-tidy`. The title is read again right before the write, but Paseo has
   no compare-and-set: a name given in the few milliseconds after that read can still be overwritten.
2. **First agent only.** The agent must be the earliest-created (ties by id) non-archived, non-background agent in the window; an agent
   joining a window does not name it. A closed (not archived) first agent still counts as first. The agent list is read unpaged, so past
   the server's 200-agent default page an older agent could be missing (32 non-archived agents on 2026-11-14).
3. **KIND.** `WORKERS` when the agent has a parent (`parentAgentId`) or an `ade.lead` label; otherwise `MAIN`. The `ade.placement` label
   (`main`, `workers`, `user`) overrides; **`USER` is never guessed**: it is what a lead connects the operator's agents into (tidy skill).
4. **`<repo>`** is the main checkout's name via git (a linked worktree `my-repo-x-wt` reads `my-repo`), else the directory's basename.
   A name that is not a valid window-name part (a space in the directory) leaves the window alone.
5. **`<work>`** is the agent's title, at most 50 characters at a word boundary, one line, no parentheses: a `worker <slice> <lead id>`
   title reduces to the slice, `LEAD|MAIN <repo> <work>` (upper case, the tab names) to the work, a leading `<repo> ` is dropped. No title
   yet: wait for the retry.
6. **`bin/ade-worker-run` launches are skipped** (labels `slice` and `ade.lead`): it names its own windows right after the launch, and a
   plugin write landing between its read and its rename could otherwise win.

## Interplay and limits

1. **Backfill.** The plugin has no "new window" gate: after an install or reload, the next turn of the first agent of any default-named
   window names it, but only a window with no title at all: a prompt-titled window is named within five minutes of its agent's creation, or not
   at all (a window deliberately reset to its default name in the app is renamed at the next reload).
2. **The first guess sticks.** The name is a placeholder from the first prompt line. `ade-worker-run rename-main` is a no-op on a window
   that already has a MAIN name, and `ade-tidy` keeps an existing name's KIND and work; to change one, use `paseo workspace rename`.
   A lead started with a parent label (a sub-lead launched without `env -u PASEO_AGENT_ID`) gets WORKERS, not MAIN.
3. **Trust.** The daemon runs `bin/ade_ws_autoname.py` and `ade_ws_names.py` from the install path (the shared checkout, which order 9
   says may sit on another session's branch), as `python3 -I`; `ade-claim` has the same property. `ADE_PYTHON` and `ADE_WS_AUTONAME_PY`
   come from the daemon's environment. The plugin also checks the script's answer (a string in the scheme, at most 100 characters) before it
   writes a title.
4. **Name collisions.** A plugin-made `WORKERS <repo> (<work>)` name is looked up by exact name by `ade-worker-run --window-middle`; if a
   parent-labelled agent's first prompt line equals a lead's `--window-middle`, that lead is refused (ownership is checked, nothing is
   misplaced). Pick distinctive `--window-middle` values.
5. **One event per window, with a budget.** While a handler runs for a window, a second event for it is dropped (the next turn
   brings another), so nothing queues behind Paseo's 30 s hook timeout. Each run has a 25 s budget and an `AbortController`, aborted by the
   budget or by Paseo's hook cancel: the python child is killed and the run makes no further daemon call or title write (a call already in flight still completes).

## Install and configuration

`paseo plugin install /absolute/path/to/djbclark-ade/plugins/ade-window-name` (a plugin reload is enough; no daemon restart).
Dry run: `ADE_WINDOW_NAME_DRY_RUN=1` in the daemon's environment logs `would-rename` and renames nothing. `ADE_WS_AUTONAME_PY`
and `ADE_PYTHON` override the decision script and the interpreter (default: `<plugin dir>/../../bin/ade_ws_autoname.py`, `python3`).
Logs: `paseo plugin logs ade-window-name`, one line per event with `outcome` `renamed`, `would-rename`, `skip` (with `reason`) or `error`.

## Tests

`node --test server/name-lib.test.mjs` (also run by `tests/test_ade_ws_autoname.py`, with the decision script's own tests).
