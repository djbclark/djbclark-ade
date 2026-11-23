# Agent identity — always name an agent you mention

Standing rule (operator, 2026-11-20): whenever an agent mentions another agent
to a human, it must give enough for the human to find that agent, every time,
not just a nickname.

## Required fields

Always give:

- **agent id** — the full Paseo id (UUID, never a bare short ID such as `5023c6fe`) or the session id of the agent.
- **workspace ID** (`wks_…`, added by operator ruling 2026-11-23 for Paseo agents) and **workspace name** — Paseo `workspace ls` `name`, or the herdr workspace `label`.

Then give the placement fields for the harness the agent actually runs in:

- A **Paseo** agent (a Paseo GUI/window agent): **full agent ID, workspace ID (`wks_…`), window name** (its workspace name), and **tab name** (operator ruling 2026-11-23; see [docs/ref-labels.md](ref-labels.md) and `AGENTS.md` Standing Order 5).
- A **herdr** terminal agent (Claude Code in a herdr pane): the herdr workspace label, the tab label, and the pane id.

A field that does not apply or cannot be resolved is written `?`, never invented
and never omitted silently.

## Why the two harnesses differ

Paseo has workspaces (the sidebar window, named by `paseo workspace ls --json`
`name`) and agents (the tab, titled with the agent's `Name`). herdr exposes
workspace label, tab label and pane id for terminal sessions, and its
`agent_session.value` carries the Claude session id, not a Paseo agent id. So a
Paseo agent is not a herdr pane and a herdr Claude pane is not a Paseo agent.
Name the fields the agent's own harness has; do not force all four onto an
agent that has only two.

## Where each field comes from

| Field | Paseo agent | herdr pane |
|---|---|---|
| workspace ID | `workspaceId` (`wks_…`) from `paseo ls -g --json` or `~/.paseo/agents/<cwd-slug>/<id>.json` | — |
| workspace / window | `name` from `paseo workspace ls --json` for that `workspaceId` (the Paseo window name) | herdr workspace `label` / tab `label` |
| tab / pane | `Name` from `paseo agent inspect <id> --json` (the tab title) | herdr `pane_id` |

`paseo agent inspect --json` carries no workspace field (its keys are `Archived`,
`Cwd`, `Id`, `Name`, `Status`, `Worktree`, ...), which is why the workspace id is
read from the state file. See also docs/workspace-layout.md.

A **local Claude Code session outside Paseo** (a plain-terminal session, found by
its session UUID) has no Paseo id; `bin/agent-id <SESSION_ID or unique prefix>`
reads `~/.claude/sessions/<pid>.json` (skipping an entry whose pid is dead) and
prints a fifth line, `SendMessage name (ListAgents): <name>` (for example
`src-00`): the address `ListAgents` shows and `SendMessage` takes
(docs/orchestration-practices.md 5a item 6).

## The command

`bin/agent-id <AGENT_ID> [--json]` prints the resolved fields. `AGENT_ID` is a
full UUID or a hex prefix of at least 4 characters (a unique prefix resolves to
the full id); anything else, including a leading `-`, exits 2 before any command
runs. It is read-only: `paseo workspace ls`, `paseo agent inspect`,
`herdr workspace/tab/pane list` and one read of the state file, each with a
15 s timeout. A missing `paseo` or `herdr` binary, a timeout or an unexpected
JSON shape prints `?` for the affected fields, never a traceback.

## Examples

A resolved Paseo agent:

```
agent  : a7664646-ab64-4495-b667-d47ea05d71ef
workspace : LEAD djbclark-ade (Wave 7)
window (Paseo) / tab (herdr): LEAD djbclark-ade (Wave 7)
tab (Paseo) / pane (herdr): Do a handoff to yourself from b0b47ad8-8801-4780-a8e0-08824c
```

An all-`?` answer is a failed lookup, not a property of the agent: the id has no
state file under `~/.paseo/agents/` (a typo, an archived-and-pruned agent, another
host), its workspace id is not in `paseo workspace ls`, or `paseo` and `herdr`
are not on `PATH`. Say so rather than omitting the field.
