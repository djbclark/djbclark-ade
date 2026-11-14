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

`ADE_ALLOW_REPLACED_SEND=<the agent's full id>` (ls-06, 2026-11-14) is the second, narrower override: for an agent a self-handoff
replaced that is **still live**, it turns the `redirect` into a `pass`, so the operator can message the replaced agent itself.
It applies only when the value equals the target's full id (`1`, a prefix, another id or the successor's id change nothing),
the target's inspect record reads `Archived: false` (a send cannot un-archive it) and the ledger chain is sound: an archived
target is still redirected (only `ADE_ALLOW_ARCHIVED_SEND` resumes one, and not one a handoff replaced), a cyclic ledger and an
archived successor are still refused. Every use appends one JSON line (UTC timestamp, target, successor, pid, ppid, `source`,
argv[0] basename; no message text) to `$ADE_SEND_GUARD_LOG`, else `~/.local/state/djbclark-ade/send-guard-overrides.jsonl`
(directory created 0700, file created 0600; an existing directory keeps its mode). `source` is `send` where the send happens (the
shim, an in-repo sender) and `hook-precheck` for the Claude hook, which runs before the command and cannot know it was sent or
declined. The writer never blocks the send and never follows a planted symlink or waits on a FIFO (`O_NOFOLLOW`, `O_NONBLOCK`,
regular files only); a log that cannot be written is skipped. Both variables are read from the environment of the command that
sends: the shim and the in-repo senders read their own process environment; the hook reads only an assignment written before the
command (`ADE_ALLOW_REPLACED_SEND=<id> paseo send ...`), never its own environment and never text in a form it could not parse
(the backstop takes no `ADE_ALLOW_REPLACED_SEND`). The override is per id, not per send: exported in a long-lived shell or set in
`os.environ`, it covers every later send to that id from that process tree, so set it for the one command.

CLI: `python3 bin/ade_send_guard.py TARGET` prints the decision as JSON and exits 4 for `refuse`, 3 for `redirect` (send to the printed `target`, never to the one you asked for: `guard X && paseo send X` stops), 0 for `pass`.

## Who calls it

1. `claude/hooks/archived_send_gate.py`, a Claude Code PreToolUse hook (matcher `Bash|mcp__.*send_agent_prompt`, in
   `agents/claude/settings.json.tmpl`, timeout 30 s). It finds a `paseo [agent] send` word pair anywhere in a simple command
   (so `timeout 30`, `env -u X`, `nohup`, `sudo`, `xargs`, `{ }`, `if` need no special case), re-parses `bash|sh|zsh -c STRING`,
   skips heredoc bodies and `echo`/`printf` text, reads the target after `--` or after the value options (`--prompt`,
   `--prompt-file`, `--image`, `--behavior`, `-o`, `--format`; a short cluster ending in `o`, `-qo json`, takes a value), accepts the
   global options before `agent`, between `agent` and `send` and after `send`, and judges the MCP tool's `agentId`. A send with an
   explicit daemon selector (`--host`, `--home`, anywhere in option position, the local home included) is not judged; an MCP `send_agent_prompt` is always judged (a remote agent's id is unknown here, so it passes). The hook is inert until `~/.claude/hooks/archived_send_gate.py` is linked
   (`[ -f ... ] || exit 0`) and `~/.claude/settings.json` is re-rendered from the template. A
   `redirect` or `refuse` is **denied** with the successor named; the hook never rewrites the target. A target built by the shell
   (`$VAR`, a substitution, a glob) is not judged, nor a send inside a heredoc fed to a shell (`bash <<EOF`). Any error or missing module allows the call.
2. **The `paseo` PATH shim** (ls-06, 2026-11-14): `libexec/agent-bin/paseo` (POSIX `sh`) and its helper `bin/ade-paseo-guard` (python3, no
   third-party modules). The hook sees only Claude's Bash and MCP tool calls and skips heredoc bodies, so a send made from Python
   `subprocess.run(["paseo", "send", ...])`, a script or a heredoc'd program was not guarded (an operator-lead report of 2026-11-14:
   a send to a replaced ex-lead went through that way). The shim enforces the same decision in the send path, like
   `ade-git-guard` does for git (docs/git-guard.md): it finds the real `paseo`: `ADE_REAL_PASEO`, else the first
   `paseo` on PATH that is an executable regular file and **not a copy of the shim** (every copy carries a marker line, so two
   checkouts' `libexec/agent-bin` on one PATH, or a symlink to the shim, are skipped; a re-entry counter, `ADE_PASEO_SHIM_DEPTH`, cap 8,
   exits 127 for a wrapper that runs a shim again; it counts only an exec chain, valid when `ADE_PASEO_SHIM_PID` is the shim's own pid or its
   parent's, so a value a daemon started through the shim hands to its agents counts from zero; a second counter, `ADE_PASEO_SHIM_HOPS`, always inherited,
   cap 32, ends a wrapper that forks between two shims (`( paseo "$@" )`, `sh -c`, `timeout`); the real paseo's path is named
   to the helper alone and removed before the helper execs the real paseo; a call with a `daemon` word gets none of the three counters, because a daemon hands its
    environment to every agent it spawns and the hop count would otherwise grow by one per daemon generation until every call exits 127; if one ever does, `env -u ADE_PASEO_SHIM_HOPS paseo ...` recovers), runs the helper only when a `send` word is on the command line (every other call is one `exec`),
   and the helper parses `paseo [global opts] [agent [global opts]] send [opts] TARGET` with the hook's own parser
   (`archived_send_gate.locate_send`, imported, not copied; global options `--json`, `-o/--format X`, `-qo X`, `-q`, `--no-headers`,
   `--no-color` may stand before `agent`, after it and after `send`; an explicit `--host`/`--home` is not judged). Then: `pass` execs the real paseo with the argv as
   given; `redirect` rewrites only the target word to the successor (the shim owns the argv, so unlike the hook it can), prints
   `ade-paseo-guard: X was replaced by Y; sending to Y` and execs; `refuse` prints the reason and the override names and exits 4
   without sending (also a redirect that would be a send to the caller itself, `PASEO_AGENT_ID`: a successor's goodbye to its predecessor
   would queue a turn to itself). A pass-through is `os.execv`, so exit codes, signals and stdio are the real paseo's. The probe
   `paseo agent inspect` is made with the real paseo's absolute path, so it never re-enters the shim. **Fails open**: no python3,
   no helper beside the shim, or any error inside the helper runs the real paseo unguarded with one stderr line; only a refusal
   stops a command. The message text is never judged: an id inside `--prompt "ack X"` is no target.
   **Installation is not done by this repo.** The shim guards a send only where `paseo` resolves to `libexec/agent-bin`:
   a. Put the directory first on PATH. The `ade-claim` plugin's W4 `agent.open.before` hook prepends it to an agent's PATH
      (`ADE_AGENT_BIN`, docs/git-guard.md) only when the plugin is installed, enabled **and in `enforce` mode**
      (`~/.local/state/djbclark-ade/ade-claim.mode` reads `enforce`); its default, observe mode, changes no PATH. By hand:
      `PATH="$HOME/src/djbclark-ade/libexec/agent-bin:$PATH" python3 sender.py`. Nothing is linked into `~/.local/bin`.
   b. **What PATH reaches**: a Python `subprocess.run(["paseo", "send", ...])` (execvp uses the inherited PATH) and any program that
      keeps its PATH. **A bash child does not keep it on the operator's Mac** (verified 2026-11-14): agents inherit
      `BASH_ENV=~/.bashrc`, which puts `~/.local/bin` and `/opt/homebrew/bin` in front of the PATH of every non-interactive bash, so
      `bash -c 'paseo send ...'`, a `#!/usr/bin/env bash` script and `bash <<EOF` reach the real paseo unguarded (a send typed
      in a Claude Bash tool call is still the hook's). Ways around it: call the shim by its path
      (`<checkout>/libexec/agent-bin/paseo send ...`, which needs no PATH), run the child with `env -u BASH_ENV`, or, with the
      operator's yes (order 11, a file outside this repo), keep `libexec/agent-bin` ahead of `~/.local/bin` in `~/.bashrc`. This change
      does none of them. A Python sender that runs bash is as exposed as the bash script.
   c. Not seen at all: an absolute path to the real paseo, and any process that does not inherit the PATH.
3. `bin/completion-notice --send` and `--lead-ack` (exit 4 `BLOCKED` on a refusal, redirect to the successor otherwise; an ack
   to an archived worker is skipped), `bin/fable-wait fire` (a refused lead, including one with a cyclic ledger, is reported
   `refused` and its items stay open; a lead the guard finds replaced, e.g. one filed by an id prefix, is sent to its successor; the chain redirect of #669 is unchanged) and `bin/deadline` (redirects the owner; a
   refused owner gets exit 2 `not sent`).
4. Not guarded by their own code: other TUIs' own tools (no hook there: this page and AGENTS.md are the rule), `bin/load-watch`, `bin/ade-tidy`
   and `bin/ade-net-resume` (they message live agents they just listed; with the shim first on their PATH a bare `paseo send`
   is judged like any other, and a live replaced target is redirected to its successor), and `ade_self_session` (it messages its own live
   predecessor before the archive).

## Limits

1. The hook sees only the target text. A name or id prefix is resolved by `paseo agent inspect`; a target Paseo cannot resolve
   is allowed (the send then reports its own error).
2. A send from a script or a TUI without the hook is stopped only when `paseo` resolves through the shim directory on PATH
   (above): an absolute path to the real `paseo`, a PATH without `libexec/agent-bin`, an operator's own shell, any process that
   does not inherit the agent's PATH and, on the operator's Mac, every bash child of an agent (`BASH_ENV`, item 2b above) are not seen.
   The shim is installed nowhere by default, and the plugin wiring is off unless in `enforce` mode. The shim is an accident guard, not a sandbox. The in-repo senders call the guard
   directly. A refusal in the shim and a denial in the hook are the same decision; the hook stays as the early warning.
3. A send racing a `finish` can still reach the predecessor; the next send is redirected.
4. Only a **send** is guarded. Paseo also un-archives on `paseo agent reload`, a resume request and an import
   (`agent-prompt.ts`, `session.ts` resume/refresh handlers); none of those is checked here. `paseo agent inspect` itself does not
   un-archive, so the guard's probe is safe.
5. The hook strips shell comments (a `#` that starts a word, outside quotes: not after an escaped blank, a continuation or a
   closing quote) before it looks for a send, so a leading comment line never hides a later send. A `$(...)` or backtick is a
   command outside quotes and inside double quotes (`"x $(paseo send A)"` is a send) but text inside single quotes (a markdown
   `code span` in a message is no send). A heredoc fed to a shell (`bash <<EOF`) is still not parsed, nor are the shell's rarer
   quoting forms (`$'it\'s'`, a ` #` inside `${x:- #y}`): such a line may hide a later send on it.
   **Backstop:** when the command text, quoted message text aside, names more `paseo ... send` than the parser found judgeable
   targets for (a lone trailing backslash, an ANSI-C quote, a target the shell builds, `"$LEAD"`, `{}`, `$id`, or a string run
   by `eval`, `watch`, `su -c`, `-c`/`-e`/`--run=`/`--command=`, or a shell left outside quotes: `| sh`, `<<< ` to `bash`, `$SHELL`,
   `source <(...)`, so `echo '...' | sh` is seen), every full agent id written in the command is judged too (at most 5). Quoted
   text is blanked, so a `paseo send` or an id inside a message is text, unless it is a quoted id or list of ids, a
   `"${VAR:-id}"` expansion, a `$(...)` or backtick body, the argument of such a runner (not after `echo`, `printf`, `grep`,
   `rg`; `awk` and `sed -e` do run their strings), or the command has a shell word outside quotes (then nothing is blanked; a shell word inside message text does not count).
   A false denial needs an archived agent's id in a command that mentions `paseo send` outside quotes, or one shell word
   (`bash x.sh`) anywhere outside quotes, which un-blanks every string in the command (accepted: the denial says how to get out). The denial then says the hook could not parse the form (and names the successor when there is one), not `Re-send to`.
   Known limits of the backstop (adversary r5, ls-04 r1, accepted): only **full** ids are judged, so a prefix or a name inside
   such a form is not (write the full id); the cap of 5 follows text order, so five other ids written before a hidden send can
   push it out; `ADE_ALLOW_ARCHIVED_SEND=<id>` anywhere in the text is honoured for that id; a command that merely *talks
   about* `paseo send` unquoted (`rg paseo send`) with an archived agent's id in it is denied; a runner not on the list
   (`eval watch su fish script parallel ssh at tmux osascript`, `-c`/`-e`/`--command`/`--run`) that takes a quoted command string is not seen;
   a `case ... in a) ...` pattern inside a `$(...)` (zsh only) desynchronises the parser and can hide a send in it or glue a following `#`; a quoted runner word (`'eval' '...'`) is not recognised; a command text built for `eval` by `printf` (`eval "$(printf 'paseo send %s' A)"`, the format string is
   text after `printf`) and `source FILE` / `. FILE` of a file that holds a send are not seen (`sh FILE` is); an fd-numbered redirect before the agent (`2>x`) is skipped, but an agent prefix of one or two digits directly followed by a redirect word is taken for the fd (`paseo send 2 >x A` judges `A`, the shell sends to `2`), as is a quoted `'>'` for a redirect (the lexer drops the quotes; `paseo send '>' A hi` judges `hi`): both read the wrong word in the false-deny direction. A redirect after `--` is skipped like one before it. In an ANSI-C `$'...'` list of ids, `\n \t \r \v \f`, `\xHH`, `\uHHHH` and octal escapes that make a blank (`\x0a`, `\012`) split the ids; any other escape leaves the string masked.
6. Upstream: Paseo itself should not un-archive on a message (getpaseo/paseo/issues/9684).

Tests: `tests/test_archived_send_guard.py` (decision table, parser, hook end to end against a fake `paseo`) and
`tests/test_ade_paseo_guard.py` (the shim and helper end to end, including a Python `subprocess.run(["paseo", "send", ...])`
with the shim directory first on PATH, the `BASH_ENV` case (kept on purpose, with the documented result), two shim copies on one PATH,
the re-entry cap, option placement, the recursion probe, fail-open and both overrides).
