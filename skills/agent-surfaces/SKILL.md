---
name: agent-surfaces
description: >-
  Locate and drive an agent across the two surfaces, Paseo and herdr, and know
  which to use. Use whenever a task says "in tab xyz", "the worker in pane N",
  "another agent", or needs to find, message or run a command in a session that
  is not this one. Check Paseo workspaces/agents/tabs AND herdr
  workspace/tab/pane names together; then route by harness. Not for dispatching
  new work (fan-out), tidying Paseo windows (tidy), or GUI screenshots
  (paseo-screen).
---

# agent-surfaces — find and drive an agent across Paseo and herdr

"in tab xyz" is ambiguous: the name may be a Paseo workspace/window/tab or a
herdr workspace/tab. Resolve against BOTH, then pick the harness that actually
holds the session.

## Resolve the name

1. **Paseo** — `paseo workspace ls --json` (name, project), `paseo ls -a -g
   --json` (agents), `paseo agent inspect <id> --json` (status, cwd, model).
   A Paseo agent's window is its workspace; there is no separate window/tab
   field in the CLI.
2. **herdr** — `herdr workspace list`, `herdr tab list`, `herdr pane list`
   (labels and ids). A terminal agent (Claude Code) lives in a pane with an
   `agent_session.value` = its session id.
3. **Same name in both?** A "LEAD <repo>" tab in herdr and a Paseo workspace
   can share a label. Check which one holds the agent id you actually mean.

## Route by harness

- **To a Paseo agent**: `paseo send --json --no-wait <id> --prompt '…'`. Ask
  for `ack <your id>`; the queue is acceptance, not proof.
- **To a herdr terminal agent**: `herdr pane run <pane-id> -- <command>` to run
  a command in its pane, or drop a mailbox file
  (`~/.local/state/agent-reports/<session-id>/inbox/<anything>.msg`, written
  atomically) to message it. Cross-harness details: docs/cross-harness-messaging.md
  and `bin/xmsg`.
- **Which to drive**: drive the session on its own harness. Do not ask Paseo to
  message a herdr session or herdr to message a Paseo agent; neither has the
  other's id.

## The skills

- `herdr` — control the terminal multiplexer (tabs, panes, workspaces).
- `paseo` — control Paseo (agents, workspaces, permissions).
- This skill is the thin resolver between them; it does not re-document either.
