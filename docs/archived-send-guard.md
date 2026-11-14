# Archived-send guard (ls-02, 2026-11-14)

Paseo un-archives and runs an archived agent that is sent a message. On 2026-11-14 the ex-lead 994234ba came back running
(`Archived=false`) after a message reached it, and could act as a stale lead. #669 made the ADE tools follow a
self-handoff's successor chain for the lead ids they pin; this guard covers the other path, a bare send to an id that a
self-handoff replaced. Operator/lead ruling: messages to an archived lead are redirected to the current lead (the handoff
record's successor chain) or refused, and never resurrect it.

## What decides: `bin/ade_send_guard.py`

`decide(target, inspect)` (and `guard(target)`, which calls `paseo agent inspect TARGET --json`) returns one of:

1. `pass`: the target is live, or unknown to Paseo, or Paseo cannot be read (a guard that blocks every message while the
   daemon restarts is worse than the bug; the send itself then fails on its own).
2. `redirect`: a completed self-handoff replaced the target (`ade_lead_succession.effective_lead`, the records
   `handoff-<id>.json`, `status: archived`). The decision names the chain's end. This applies even when the old agent is
   already running again: the ledger says it was replaced.
3. `refuse`: the target is archived and nothing replaced it; or its replacement is archived too; or the ledger is cyclic. The
   reason names what to do.

`ADE_ALLOW_ARCHIVED_SEND=<the agent's full id>` in the command's environment (`ADE_ALLOW_ARCHIVED_SEND=<id> paseo send ...<id>`)
is the deliberate override that resumes one archived agent on purpose: it names the agent, so a blanket `=1` (or one exported
earlier) never covers another send. The refusal text does not hand it over as a remedy: resuming needs the operator's
explicit instruction. It never overrides a redirect or a cycle, so an agent a handoff replaced cannot be messaged through a
guarded path at all (message its successor). Only an agent that was
**handed off** has a successor; a finished worker that `ade-tidy` archived is plain archived, so a send to it is refused
until the override is given (it is a resurrection, which the operator must mean).

CLI: `python3 bin/ade_send_guard.py TARGET` prints the decision as JSON and exits 4 for `refuse`, 3 for `redirect` (send to the printed `target`, never to the one you asked for: `guard X && paseo send X` stops), 0 for `pass`.

## Who calls it

1. `claude/hooks/archived_send_gate.py`, a Claude Code PreToolUse hook (matcher `Bash|mcp__.*send_agent_prompt`, in
   `agents/claude/settings.json.tmpl`, timeout 30 s). It finds a `paseo [agent] send` word pair anywhere in a simple command
   (so `timeout 30`, `env -u X`, `nohup`, `sudo`, `xargs`, `{ }`, `if` need no special case), re-parses `bash|sh|zsh -c STRING`,
   skips heredoc bodies and `echo`/`printf` text, reads the target after `--` or after the value options (`--prompt`,
   `--prompt-file`, `--image`, `--behavior`), and judges the MCP tool's `agentId`. A send aimed at another daemon (`--host`,
   `--home`) is not judged; an MCP `send_agent_prompt` is always judged (a remote agent's id is unknown here, so it passes). The hook is inert until `~/.claude/hooks/archived_send_gate.py` is linked
   (`[ -f ... ] || exit 0`) and `~/.claude/settings.json` is re-rendered from the template. A
   `redirect` or `refuse` is **denied** with the successor named; the hook never rewrites the target. A target built by the shell
   (`$VAR`, a substitution, a glob) is not judged, nor a send inside a heredoc fed to a shell (`bash <<EOF`). Any error or missing module allows the call.
2. `bin/completion-notice --send` and `--lead-ack` (exit 4 `BLOCKED` on a refusal, redirect to the successor otherwise; an ack
   to an archived worker is skipped), `bin/fable-wait fire` (a refused lead, including one with a cyclic ledger, is reported
   `refused` and its items stay open; a lead the guard finds replaced, e.g. one filed by an id prefix, is sent to its successor; the chain redirect of #669 is unchanged) and `bin/deadline` (redirects the owner; a
   refused owner gets exit 2 `not sent`).
3. Not guarded: other TUIs' own tools (no hook there: this page and AGENTS.md are the rule), `bin/load-watch`, `bin/ade-tidy`
   and `bin/ade-net-resume` (they message live agents they just listed), and `ade_self_session` (it messages its own live
   predecessor before the archive).

## Limits

1. The hook sees only the target text. A name or id prefix is resolved by `paseo agent inspect`; a target Paseo cannot resolve
   is allowed (the send then reports its own error).
2. A send from a script or a TUI without the hook is not stopped; only the in-repo senders above call the guard.
3. A send racing a `finish` can still reach the predecessor; the next send is redirected.
4. Only a **send** is guarded. Paseo also un-archives on `paseo agent reload`, a resume request and an import
   (`agent-prompt.ts`, `session.ts` resume/refresh handlers); none of those is checked here. `paseo agent inspect` itself does not
   un-archive, so the guard's probe is safe.
5. The hook strips shell comments (a `#` that starts a word, outside quotes) before it looks for a send, so a leading comment
   line never hides a later send; a heredoc fed to a shell (`bash <<EOF`) is still not parsed, nor are the shell's rarer quoting forms (`$'it\'s'`, a ` #` inside `${x:- #y}`): such a line may hide a later send on it.
   **Backstop:** when the command text names more `paseo ... send` than the parser found targets for (a send inside
   `"$(...)"`, a lone trailing backslash, an escaped space before a `#`), every full agent id written in the command is judged
   too (at most 5). A false denial needs an archived agent's id in a command that mentions `paseo send`.
6. Upstream: Paseo itself should not un-archive on a message (getpaseo/paseo/issues/9684).

Tests: `tests/test_archived_send_guard.py` (decision table, parser, hook end to end against a fake `paseo`).
