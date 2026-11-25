# Cross-harness messaging — reach an agent on another harness

The verified two-way path between a Paseo agent (Pi included) and a local
Claude Code session in herdr (or any non-Paseo terminal). There is no common
message bus across Paseo, herdr, Hermes, Grok Bot and cloud agents today
(Carried 112); this page is the pair of channels that do work, so neither side
reaches for a broken one.

Two rules make this work:

1. **The reply path is always explicit in the message, never guessed.** A local
   Claude Code session names the exact file it is watching (its scratchpad);
   `bin/xmsg` appends it to the text as `Reply via: xmsg ack <path> …`.
2. **An ack file is written only by its receiver, never by the sender's own
   status** (adversary review of #847: a `queued` line in the ack file read as a
   delivery proof). The sender's send status goes to `<path>.status`, a file no
   watcher waits on.

A session outside Paseo keeps **two working reply routes**: `SendMessage` (its
name from `ListAgents`) and the atomic reply file. `xmsg to-paseo` from a
sender with no `PASEO_AGENT_ID` therefore refuses unless both `--reply-name` and
`--reply-file` are given.

## To a Paseo agent (from any shell, herdr pane included)

```
xmsg to-paseo --reply-file /path/to/fresh-reply.md --reply-name <my SendMessage name> <agent-id> 'message…'
```

(or plain `paseo send --json --no-wait <agent-id> --prompt 'message…'` from a
Paseo agent, asking for `ack <your id>`.)

- The id is positional (or a unique shortId prefix, never a title); xmsg puts
  `--` before it.
- Delivery is **accepted**, not proven: an agent-to-agent send reports no later
  delivery, so only the peer's ack proves it. xmsg exits **0** when paseo
  reports `sent`/`completed` (delivered), **5** when `queued` (accepted: wait
  for the ack), **1** on a failed send, **2** on bad usage, **3** when the
  reply path already exists (use a fresh path: a stale ack must not pass for a
  new one). `paseo send`'s own exit code is never read as delivery.
- xmsg never writes the reply path. It writes `<path>.status`
  (`xmsg-status: queued`); the ack arrives at `<path>` from the peer.
- **Practical note (2026-11-25):** a Herdr / non-Paseo Claude session messaging
  a Paseo lead must send via `bin/xmsg to-paseo` with `--reply-file <path>` (not
  bare `paseo send` without a reply path) so the Paseo lead can reply atomically
  via `bin/xmsg ack <path> …` instead of falling back to the operator's
  clipboard (`clip`).

## To a local Claude Code session (from a Paseo/Pi agent)

A Paseo agent has no `SendMessage`/`ListAgents` tool for a local Claude
session. The working channel is the session's own file, which it names in its
message (e.g. `/private/tmp/claude-502/.../scratchpad/lead-reply.md`). The
receiver writes it:

```
xmsg ack /private/tmp/claude-502/.../scratchpad/lead-reply.md 'ack <session-id> …'
```

(`xmsg to-claude` is the same write for a longer message.) The write goes to a
temp file beside the target (fsynced), then a hard link that fails if the name
exists, so the watcher never reads a half-written file and an earlier ack is
never silently replaced (`--replace` overrides, exit 3 otherwise). The file's
first line must start with the ack.

Do NOT guess the path. The `~/.local/state/agent-reports/<id>/inbox/` layout
was a mistake that cost two failed exchanges on 2026-11-21: different sessions
poll different scratchpads. Always use the path the other side names.

## Typing into a herdr pane is not messaging

Do not type into a terminal agent's pane as a message: `herdr agent prompt`,
`send-keys` and `pane run` show up as operator keystrokes, prove no delivery,
and `pane run` has no blocked-dialog check (its text answers a permission
card). Use SendMessage or the reply file above. Typing is for a pane the
operator names; answering an approval card stays the operator's call.

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
