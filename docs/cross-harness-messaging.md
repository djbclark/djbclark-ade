# Cross-harness messaging — reach an agent on another harness

The one verified two-way path between a Paseo agent (Pi included) and a local
Claude Code session in herdr (or any non-Paseo terminal). There is no common
message bus across Paseo, herdr, Hermes, Grok Bot and cloud agents today
(Carried 112); this page is the pair of channels that do work, so neither side
reaches for a broken one.

## To a Paseo agent (from any shell, herdr pane included)

```
paseo send --json --no-wait <agent-id> --prompt 'message…'
```

- The id is positional (or a unique shortId prefix — never a title).
- Delivery is **accepted**, not proven: an agent-to-agent send reports no later
  delivery, so only the peer's `ack <your id>` proves it. Put
  `Please reply: ack <your id>` in the text and read your own inbox for it.
- `paseo send`'s exit code is never delivery; read JSON `.status`
  (`sent`/`completed` for a sourceless send, `queued` = accepted).
- A busy target needs `--behavior steer` to interrupt a steerable turn.

## To a local Claude Code session (from a Paseo/Pi agent)

A Paseo agent has no `SendMessage`/`ListAgents` tool for a local Claude
session. The working channel is a **mailbox file**:

```
<home>/.local/state/agent-reports/<claude-session-id>/inbox/<anything>.msg
```

Write the file to a temp name outside the directory first, then `mv` it in
(never a half-written file). A watcher wakes the session within ~10 s while it
runs; between turns the result arrives as its next turn. Start the content
with your agent id.

The session must tell you its report dir / session id for this to work; there
is no reverse directory lookup.

## Falling back

- Urgent relay to a human: `hermes-ping "<repo>: <one line>"`.
- An untested relay (Claude-provider Paseo agent running `SendMessage` to a
  named listing) exists but is not verified — try once, tell the operator the
  result.

## Do not use

- `paseo send` from a Paseo agent to a local Claude session: there is no such
  target id.
- `claude -p --session-id <id>` to reach a live session: it errors "already in
  use".
- The deleted `ln` session-finder relay shim: gone 2026-11-14.
