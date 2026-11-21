# Agent identity — always name an agent you mention

Standing rule (operator, 2026-11-20): whenever an agent mentions another agent
to a human, it must give enough for the human to find that agent, every time,
not just a nickname.

## Required fields

Always give:

- **agent id** — the full Paseo id (or the session id) of the agent.
- **workspace name** — Paseo `workspace ls` `name`, or the herdr workspace
  `label`.

Then give the placement fields for the harness the agent actually runs in:

- A **Paseo** agent (a Paseo GUI/window agent): the window name (its workspace
  name) and the tab name it lives in.
- A **herdr** terminal agent (Claude Code in a herdr pane): the herdr workspace
  label, the tab label, and the pane id.

A field that does not apply or cannot be resolved is written `?`, never invented
and never omitted silently.

## Why the two harnesses differ

Paseo's CLI exposes workspaces (by name) and agents, but no separate
window/tab fields; a Paseo agent's "window" is its workspace. herdr exposes
workspace label, tab label and pane id for terminal sessions, and its
`agent_session.value` carries the Claude session id, not a Paseo agent id. So a
Paseo agent is not a herdr pane and a herdr Claude pane is not a Paseo agent.
Name the fields the agent's own harness has; do not force all four onto an
agent that has only two.

## The command

`bin/agent-id <AGENT_ID> [--json]` prints the resolved fields (read-only:
`paseo workspace ls`, `paseo agent inspect`, `herdr workspace/tab/pane list`).
Unresolvable fields print `?`.

## Examples

```
agent  : 892094ff-bfad-4f16-b9b8-f2bf45e699e1
workspace : ?
window (Paseo) / tab (herdr): ?
tab (Paseo) / pane (herdr): ?
```

An agent whose workspace is `?` is one whose workspace was archived or never
assigned; say so rather than omitting the field.
