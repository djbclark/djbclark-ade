# agent-radar (djbclark fork)

One live line above the Claude Code prompt per running **subagent**, **background Bash command** and
**detached `acp-dispatch` job**. `/radar` opens a pane with all of them.

```text
/plugin marketplace add djbclark/djbclark-ade
/plugin install agent-radar@djbclark-ade
```

Or, from the shell: `claude plugin marketplace add djbclark/djbclark-ade && claude plugin install agent-radar@djbclark-ade`.
Disable the upstream copy (`agent-radar@claude-code-mods`) first: both register `/radar`.

## What it shows

| Kind (tag) | Source | Band line | Pane detail |
|---|---|---|---|
| subagent (`sub`) | `agent.spawn`, `turn.complete` | description, time, tool count, current tool | the agent's last messages (unchanged from upstream) |
| shell (`sh`) | a Bash call with `run_in_background: true` (or one Claude Code moved to the background) | the agent CLI and `--model` if the command runs one (`acp-run`, `acp-dispatch`, `codex exec`, `opencode run`, `cursor-agent`, `agy`, `crush`, `copilot`, `qwen`, `cline`, `omp`, `hermes`), else the Bash description, else the first 50 characters; the last non-empty output line | the command, the output path and the last 8 output lines |
| job (`acp`) | `<state>/<task>/jobs/<name>.json` records whose `owner` is this session | `agent model - name`, status and the last log event | agent, model, effort, status, exit, report path and the last log events |

* A toast says when a shell or job ends. A job that ends with any status but `done` (`no-report`, `blocked`,
  `partial`, ...) is red and the toast says which.
* `/radar` answers `N running, M finished`, counting all three kinds.
* A shell that is the `rearm` waiter of a job, or an `acp-dispatch ... --name N` whose record exists, is shown
  once, as the job.

### How a shell is followed

Claude Code writes a background command's output to `.../tasks/<id>.output` and keeps it open until the
command ends, and there is no exit-code file. Every 5 seconds one `lsof -Fn` asks which of the shells' output
files are still open; two polls in a row that find one closed end it (it is always shown as done: the exit
code is not recorded anywhere). Without a working `lsof` nothing is guessed done. A background command whose
result names no output file is not tracked.

### How a job is followed

The records are scanned only in a session that needs it: after its Bash hook has seen a command containing
`acp-dispatch` or `bigteam`, until no tracked job runs and 60 s have passed since the last such command, plus
once at the first `/radar` (for jobs launched before the mod loaded). A session that never dispatches does no
scan at all. When scanning, one `sh -c` per poll lists the records under `$ACP_DISPATCH_STATE` (default `~/.local/state/bigteam`, written
by `bin/acp-dispatch`) that changed in the last 3 days and name this session's id; one more reads the tail of
the logs of the running ones. Only records this session launched (`owner` = the session id) and that are running,
or ended after the session started, are shown.

## Fork

Forked from `agent-radar` 0.1.3 by Hamza Zafar (MIT), <https://github.com/hamzafer/claude-code-mods>
(`mods/agent-radar`). Version here: `0.2.0-djb.3`. Upstream's license text and author are kept
([LICENSE](LICENSE), `plugin.json`).

What changed:

1. `hooks/register.tsx`: background Bash tracking (`tool.call` on `Bash`), a 5 s poll for shells and job
   records, three kinds in one list with a kind tag, shell and job views in the pane, toasts for both.
   The subagent code paths are upstream's.
2. `hooks/watch.ts` (new): the pure parts (agent CLI and model from a command, output path from the tool
   result, job record parsing, log summary, the two poll scripts).
3. `types/index.d.ts`: `kind`, `AcpJob` and the shell and job fields on `RadarAgent`.
4. `tests/agent-radar.test.tsx`: upstream's three tests plus twenty-four for the above and the hardening below.
5. Hardening (`-djb.2`, `-djb.3`), the behaviour of the fixes from the adversary review of upstream's background-shell PR
   (<https://github.com/hamzafer/claude-code-mods/pull/129>), applied to every place the fork shows or reads
   external data, the `acp-dispatch` job records included, which upstream lacks:
   * Escape sequences are stripped from everything shown (CSI, OSC such as the clipboard write, DCS, the 8-bit
     forms, `ESC c` and the other two-byte escapes, C0/C1 control characters except tab and line breaks) and so
     are the bidi controls (U+061C, U+200E/F, U+202A-E, U+2066-9). That covers command text, the Bash
     description, output tails, log events, subagent descriptions, messages and tool-call labels, and every
     text field of a job record. Shown labels are single lines.
   * A command is cut at 4096 characters before any regex runs (agent label, `--model`, `--name`, the
     dispatch check).
   * A path the radar hands to `lsof` or `tail` (a shell's output file, a job's `log`) must be absolute, free of
     whitespace, control characters and `..` segments; a shell's must also end in `.output`. A job record's
     `report`, `done` and `record` must pass the same check or are dropped. Paths shown are cleaned.
   * The tail and record scripts pipe through `LC_ALL=C tr -d '\001'`, so no log or record can forge another
     file's block (`LC_ALL=C` because BSD `tr` rejects invalid UTF-8).
   * Job record numbers must be finite; text fields are cut (name 100, others 64) and an empty name drops the record.
   * `-djb.3` (adversary review of `-djb.2`): a record is accepted only at `<out>/jobs/<name>.json`, and its
     `log`, `report` and `done` must lie inside that `<out>` (`done` ends in `.done`); `record` is the file the
     scan found, whatever the record claims. The tail script tails regular files only (no FIFO, no device such as
     `/dev/zero`) and kills each tail after 3 s, so a dispatched agent cannot make the radar leak a process. A job
     is matched to a shell by identity (the record path or `.done` marker as a whole word, or `--name`), never by a
     short `includes()`; `rearm` is not kept. A carriage return in a log line is dropped. The record scan reads
     only regular files under 64 KiB, at most 64 KiB of each, keeps a file name with a newline whole, and refuses
     a relative `ACP_DISPATCH_STATE`.

The generic part (background shells) is meant for upstream; the `acp-dispatch` part is specific to this
toolchain and is not.

## Test

```sh
claude plugin validate plugins/agent-radar
CLAUDE_CONFIG_DIR=$(mktemp -d) claude plugin test plugins/agent-radar
```
