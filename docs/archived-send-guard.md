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

`ADE_ALLOW_ARCHIVED_SEND=1` in the command's environment (`ADE_ALLOW_ARCHIVED_SEND=1 paseo send ...`) is the deliberate
override that resumes an archived agent on purpose. It never overrides a redirect or a cycle. Only an agent that was
**handed off** has a successor; a finished worker that `ade-tidy` archived is plain archived, so a send to it is refused
until the override is given (it is a resurrection, which the operator must mean).

CLI: `python3 bin/ade_send_guard.py TARGET` prints the decision as JSON and exits 4 for `refuse`, 0 otherwise.

## Who calls it

1. `claude/hooks/archived_send_gate.py`, a Claude Code PreToolUse hook (matcher `Bash|mcp__.*send_agent_prompt`, in
   `agents/claude/settings.json.tmpl`). It parses `paseo [agent] send` simple commands (`--` and value flags such as
   `--behavior`/`--prompt-file`; chains with `;`, `&&`, `|`, newlines; an `env`/`VAR=` prefix) and the MCP tool's `agentId`. A
   `redirect` or `refuse` is **denied** with the successor named; the hook never rewrites the target. A target built by the shell
   (`$VAR`, a substitution, a glob) is not judged. Any error or missing module allows the call.
2. `bin/completion-notice --send` (exit 4 `BLOCKED` on a refusal, redirect to the successor otherwise), `bin/fable-wait fire`
   (a refused lead is reported `refused` and the items stay open; the chain redirect of #669 is unchanged) and `bin/deadline`
   (redirects the owner; its own inspect gate already refuses an archived owner).
3. Not guarded: other TUIs' own tools (no hook there: this page and AGENTS.md are the rule), `bin/load-watch`, `bin/ade-tidy`
   and `bin/ade-net-resume` (they message live agents they just listed), and `ade_self_session` (it messages its own live
   predecessor before the archive).

## Limits

1. The hook sees only the target text. A name or id prefix is resolved by `paseo agent inspect`; a target Paseo cannot resolve
   is allowed (the send then reports its own error).
2. A send from a script or a TUI without the hook is not stopped; only the in-repo senders above call the guard.
3. A send racing a `finish` can still reach the predecessor; the next send is redirected.
4. Upstream: Paseo itself should not un-archive on a message (getpaseo/paseo issue, linked in the PR).

Tests: `tests/test_archived_send_guard.py` (decision table, parser, hook end to end against a fake `paseo`).
