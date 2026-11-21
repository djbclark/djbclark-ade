# Cross-harness messaging — reach an agent on another harness

The verified two-way path between a Paseo agent (Pi included) and a local
Claude Code session in herdr (or any non-Paseo terminal). There is no common
message bus across Paseo, herdr, Hermes, Grok Bot and cloud agents today
(Carried 112); this page is the pair of channels that do work, so neither side
reaches for a broken one.

The single rule that makes this work: **the reply path is always explicit in
the message, never guessed.** A local Claude Code session names the exact file
it is watching (its scratchpad), and the Paseo recipient writes its ack there.
`bin/xmsg` encodes both directions and the ack.

## To a Paseo agent (from any shell, herdr pane included)

```
paseo send --json --no-wait <agent-id> --prompt 'message…'
```

or, naming the reply file so the ack is machine-checkable:

```
xmsg to-paseo <agent-id> 'message…' --reply-file /path/to/lead-reply.md
```

- The id is positional (or a unique shortId prefix — never a title).
- Delivery is **accepted**, not proven: an agent-to-agent send reports no later
  delivery, so only the peer's `ack <your id>` proves it. Put
  `Please reply: ack <your id>` in the text.
- `paseo send`'s exit code is never delivery; read JSON `.status`
  (`sent`/`completed` for a sourceless send, `queued` = accepted).
- A sourceless sender (a local session with no `PASEO_AGENT_ID`) MUST name the
  reply path: without it the recipient has nowhere to write an ack.

## To a local Claude Code session (from a Paseo/Pi agent)

A Paseo agent has no `SendMessage`/`ListAgents` tool for a local Claude
session. The working channel is the session's own scratchpad file, which it
names in its message (e.g. `/private/tmp/claude-502/.../scratchpad/lead-reply.md`):

```
xmsg to-claude /private/tmp/claude-502/.../scratchpad/lead-reply.md 'ack <session-id> …'
```

or the ack form:

```
xmsg ack /private/tmp/claude-502/.../scratchpad/lead-reply.md 'ack <session-id>'
```

Every write goes to a temp name beside the target then `mv`s in, so the watcher
never reads a half-written file. The file's first line must start with the ack.

Do NOT guess the path. The `~/.local/state/agent-reports/<id>/inbox/` layout
was a mistake that cost two failed exchanges on 2026-11-21: different sessions
poll different scratchpads. Always read the path the sender names.

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
