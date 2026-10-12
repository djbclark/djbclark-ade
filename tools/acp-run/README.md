# acp-run

Run one prompt through a coding agent over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP), headless, and get
the agent's final message on stdout. It is how one agent on this machine hands a
self-contained task to another vendor's agent: Claude Code, Codex, Copilot,
opencode, Cursor, Qwen Code, Devin, Cline, Hermes, Antigravity (`agy`), Grok and
zcode (through the third-party `zcode-acp-server`, whose `model` option refuses
every switch, so it is the one agent run without `--model`; its README pins a
model only at startup with the env pair `ZCODE_PROVIDER` + `ZCODE_MODEL`, which
was refused as well; both checked 2026-10-11 while the z.ai weekly limit was
exhausted, so recheck after it resets; `--set thought=low|high|max`).

A single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) on the
official Python SDK (`agent-client-protocol`); no daemon, no state beyond its
logs. MIT licensed. The SDK is pinned below 1.0 until 1.0 is tested.

```sh
acp-run --list                                  # agents and the command each runs
acp-run claude --info                           # modes, config options, auth methods
acp-run codex -C ~/src/repo --add-dir ~/.local/state/bigteam/task -p 'Reply with exactly: OK' --model gpt-6-astra
acp-run copilot -C ~/src/repo -f brief.md --perm deny --timeout 1200 > report.md
acp-run codex -C ~/src/repo --interactive --inbox /tmp/codex-in   # a session you keep prompting
```

## What it adds over a bare ACP client

1. **A per-agent table**: the launch command for each agent, per-agent default
   config options (`DEFAULT_SET`), each agent's own auto-approve mode (`YOLO_SET`),
   and environment set-up where an agent needs it.
2. **A permission policy** answering every `session/request_permission`:
   - `all` (default): allow everything.
   - `deny`: refuse everything (read-only review).
   - `scoped:P1,P2`: allow reads, searches, fetches, thinking and commands; allow
     edit/delete/move only when every path the tool call names is under one of
     the listed paths (relative to `-C`). This is an approval policy, not a
     sandbox: an allowed shell command can still write anywhere.
3. **`--add-dir DIR` (repeatable)**: add extra workspace roots sent as
   `additionalDirectories` in `session/new`. If advertised in `initialize` (in
   `agentCapabilities` or `sessionCapabilities`), it is sent directly; if
   unadvertised, it is still sent, falling back with a one-line log to a retry
   without it if rejected. Lets an agent whose file tools are confined to its
   workspace roots read and write outside `-C` (such as `acp-dispatch` report
   folders). **agy ignores it** (2026-10-11): agy_acp_server 1.3.0 accepts the
   field but never passes it to its allowed-directory list, so agy's file tools
   still refuse paths outside `-C`.
4. **`--model`, `--mode` and `--set ID=VALUE`** for any config option `--info`
   lists.
5. **An audit trail**: every ACP event is logged as JSONL (default
   `~/.local/state/acp-run/`), ending with a `result` record (summary and exit
   code), and one summary line goes to stderr: stop reason, seconds, tool calls,
   permissions allowed/denied, tokens, cost, failure class, log path.
6. **Timeouts that cancel the turn** (`session/cancel`), and a bounded handshake
   with retries (`--handshake-tries`), falling back to `claude -p` for the
   `claude` agent when its ACP session never starts (`--no-fallback` to disable).
   The fallback runs as a known conversation (`claude -p --session-id`: the
   `--session-id UUID` you pass, else a fresh one) and logs it as `new_session`,
   so a later `--resume` reaches exactly that conversation. Over ACP,
   claude-agent-acp chooses the id and gives it to Claude as `--session-id`, so
   the logged `new_session` id is already Claude's own.
   `--handshake-timeout` (env `ACP_RUN_HANDSHAKE_TIMEOUT`) bounds `initialize`
   and `session/new` each: 40 s by default, 90 s for `claude`, whose
   `session/new` takes 13 s on an idle machine and 17-24 s under heavy load.
   `--wrapup-grace S` (off by default; `acp-dispatch` passes 300) sends one more
   prompt after the timeout cancel (`--wrapup TEXT`, default "time is up, write
   your final report now") and waits up to S seconds, so a slice cut off in a
   hung command still writes its report; the run still exits 124 and the summary
   says `wrapup=<stop reason|timeout|skipped|error>`. Added 2026-10-10 after an
   opencode slice with verified work lost its report to a `git commit` whose
   pre-commit Gradle hook queued on the machine-wide Gradle slot.
   `--timeout 0` removes the turn deadline and disables the wrap-up turn;
   handshake limits still apply. While waiting, acp-run checks `<log>.extend`
   at intervals of at most 30 seconds. Write a nonnegative whole number of
   seconds there to add to the current deadline, or `0` to remove it. Positive
   extensions leave an unlimited turn unlimited. The file is consumed and
   deleted; malformed input is logged and ignored. `deadline_extended` records
   carry the old and new monotonic deadlines (`null` means unlimited).
7. **Safe permission answers**: only an offered `allow_once` or `reject_once`
   option is ever selected. Never an `*_always` option, which an agent may save
   beyond this run (Hermes writes `allow_always` to a permanent allowlist), and
   never `cancelled`, which cancels the whole turn. An allow with no
   `allow_once` offered becomes a `reject_once`; with neither offered the agent
   gets a JSON-RPC error. Under `scoped:`, a tool call with no kind gets one
   inferred from its title (`Edit ...` is an edit, as acpx does); one that cannot
   be inferred needs in-scope paths, like an edit.
8. **Delivery checks.** Agents report some provider failures as a normal answer
   (`end_turn`). acp-run fails such a turn (exit 1, a `FAILED <class>` line on
   stderr, `"failure"` in `--json`) when the whole short reply is a refusal
   (`Upgrade your plan to continue`), when it is the model declining the task
   (`Sorry, I cannot fulfill your request ...`: class `refused`, never retried, and
   acp-dispatch records it as NO-REPORT), or when the reply ends in a provider or
   transport error line (`Error: RetriableError: [unavailable] PING timed out`),
   reported as "reply truncated; edits may be present". ACP errors are classified
   the same way: `quota`, `plan`, `auth` or `transient`. The patterns are a short
   table at the top of the script (`FAILURE_CLASSES`, `REPLY_REFUSALS`,
   `MODEL_REFUSALS`, `TAIL_ERROR`).
9. **Opt-in prompt retry** (`--prompt-retries N`, default 0): a prompt that fails
   with a transient error before any tool call or permission request is retried
   with backoff (1, 2, 4 s, at most 10 s). Quota, plan and auth failures are not
   retried.
10. **Opt-in machine-load guard** (`--max-load L`, env `ACP_RUN_MAX_LOAD`): refuse
   to start (exit 75) while the 1-minute load average per CPU core is above `L`;
   `--load-wait SECS` (env `ACP_RUN_LOAD_WAIT`) waits up to that long for the
   load to drop first. Off by default.
11. **Clean interrupts**: SIGINT/SIGTERM send `session/cancel`, stop the agent
    and exit 130/143, so a killed run does not leave the agent running.
12. **An interactive mode** (`--interactive`, below): one ACP session that stays
    open for more prompts, from a terminal, a pipe or a drop directory.
13. **Verify-and-retry (`--verify CMD`)**: an opt-in verify loop for models that end
    their turn early (`end_turn`) before finishing work. Runs `CMD` as a shell command
    with `-C DIR` as cwd (exit 0 = pass). If `CMD` fails, acp-run sends a follow-up
    prompt into the same session with the exit code and truncated output (last 40
    lines, max 3000 chars), instructing the agent to fix the problem and retry.
    Retries up to `--verify-retries N` times (default 2), with `--verify-timeout SECS`
    (default 180) per check run. Respects the overall `--timeout` deadline.
    The run summary (stderr line, `--json`, and JSONL log `result` record) records
    `verify=pass|fail` and `verify_attempts=<n>`. A final failed verification prints
    a warning on stderr and preserves exit 0 (off by default; callers decide).

    ```sh
    acp-run crush -C dir -p '...' --verify 'python3 -m unittest' --verify-retries 2
    ```

## Dispatch slice controls (2026-10-11)

`acp-dispatch <agent> ... --timeout 0` starts a slice without a time limit.
Its record-based rearm waiter and detached wait have no deadline, even with an
explicit `--wait-timeout`. For finite slices, the existing default remains
timeout + wrap-up grace + 300 seconds; `--wait-timeout 0` makes just the waiter
unlimited. Already-running record-based waiters follow later extensions.

`acp-dispatch extend <out>/jobs/<name>.json 3600` adds an hour to a running
slice. Use `0` to remove its deadline. The command atomically writes the control
file and records the requested total limit; acp-run's log confirms application.
Pending positive extensions accumulate. Finished slices are refused.

`acp-dispatch resume <out>/jobs/<name>.json --timeout 14400` continues a
finished slice in its original ACP session. Optional `-p TEXT` or `-f FILE`
replaces the continuation prompt; `--detach --no-wait` uses the normal runner
and rearm contract. Without a new timeout it reuses the recorded limit. The
record stores the session id as soon as it is observed, and legacy records
recover it from the log's `new_session` event. Agents advertising neither
load nor resume are refused with exit 2. The previous report is preserved as
`<name>-r1-report.md`, then `-r2`, and so on; each revision also keeps its brief,
log, final text and stderr. Normal output and `.done` paths remain stable.

For `agy`, the footer instead names
`<-C>/.acp-dispatch/<task>-<name>-report.md` and its `.done`. Dispatch adds
`.acp-dispatch/` once to the workspace repository's local Git exclude file
(non-Git workspaces need no exclude). Finalize moves the report to the normal
out folder before publishing its `.done`. Records retain both pairs of paths.

## Interactive mode

`acp-run <agent> --interactive` (`-i`) keeps the ACP connection, which is the
session, open and reads prompt after prompt in one process. The one-shot contract
is unchanged without it: stdout is the final message, stderr one summary line.

```sh
acp-run claude -C ~/src/repo -i                              # type at the prompt
acp-run claude -C ~/src/repo -i -p 'Read AGENTS.md first.'   # first prompt from -p/-f
acp-run codex -C ~/src/repo -i --inbox /tmp/codex-in         # also take files dropped there
acp-run claude -C ~/src/repo -i --resume SESSION_ID          # reopen an earlier session
```

1. **Output.** Agent text streams to stdout as it arrives; each tool call is one
   `⚙ <title>` line and a failed one a `✗` line. Thoughts show only with
   `--show-thinking`. After each turn it prints the stop reason, seconds and tool
   count, then waits for the next prompt.
2. **Prompt sources**, whichever comes first. A line on stdin is one prompt. A
   `*.txt` or `*.md` file dropped into `--inbox DIR` (polled every second, taken in
   name order, deleted once read) is one prompt, whole file. The first prompt
   comes from `-p` or `-f`; without either it starts at the prompt. A prompt that
   arrives during a turn queues as the next one. `--timeout` applies to each turn.
3. **Commands.** `/exit` (or EOF) ends the session; typed at the terminal during
   a turn it cancels that turn first, while from a pipe or the inbox it waits
   behind the prompts already queued. `/cancel` cancels the running turn
   (`session/cancel`) and returns to the prompt.
4. **Ctrl-C** cancels the running turn, or exits when idle. The agent runs in its
   own process group, so the terminal's interrupt does not hit it directly.
   SIGHUP exits 129.
5. **Delivery checks per turn.** Each turn gets the checks above; a failed one
   prints `FAILED <class>` and returns to the prompt rather than ending the
   session. On exit the stderr summary carries `turns=N` (or `--json` the last
   turn's text), and the exit code is the last turn's (0 when no turn ran).
6. **`--perm ask`** (interactive only) prints each permission request and waits
   for `y` or `n`, typed or written to the inbox. Parallel requests are asked one
   at a time, and `/cancel` or Ctrl-C answers an open question as cancelled. The
   answer is still only an offered `allow_once` or `reject_once`. The agent must
   actually send requests: `claude` needs `--perm ask --set mode=default`, or
   its own settings can auto-allow and nothing is asked.
7. **`--resume ID`** reopens an ACP session with `session/load` (history is
   replayed to the log only, not printed) or `session/resume`, whichever the agent
   advertises in `initialize` (`--info` shows `loadSession` and
   `sessionCapabilities`). It exits 2 if the agent advertises neither.
8. **herdr reports.** In a herdr pane (`HERDR_PANE_ID` set; `HERDR_BIN_PATH` or
   `herdr` on `PATH`) it reports `working`, `idle` and `blocked` (a pending
   permission question) as source `acp-run`, with a resume command
   (`acp-run <agent> -C DIR --interactive --resume ID ...`), and releases the
   pane on exit. Reports run in the background and never hold up the session.
   herdr before 0.9.2 rejects the resume command, so on 0.9.1 it is dropped.
   The agent process is started without `HERDR_PANE_ID` and `HERDR_ENV`, so its
   own herdr hooks (Claude Code's report as `herdr:claude`) do not compete for
   the pane.
9. **Sending a prompt from outside.** On herdr 0.9.1 `herdr agent prompt <pane>
   TEXT` cannot reach an acp-run session, so a caller uses the inbox (write a
   `.txt` file into `--inbox DIR`; write to a temporary name and rename it, so a
   half-written file is not picked up) or `herdr pane run <pane> TEXT`, which
   sends a line to the pane's terminal, where acp-run reads it from stdin.
10. **The log gets a `turn` record per turn** (`n`, `stop_reason`, `seconds`,
    `exit`, and `failure`, `error` or `warning` when set), written before the
    final `result` record, which carries `turns`. A one-shot run writes one `turn`
    record too.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | `end_turn` with some output |
| 1 | another stop reason, an agent error, an empty reply (no text and no tool calls; or no text under `--perm deny` or after a denied permission), or a delivery-check failure (quota, plan, auth, provider error, truncated reply) |
| 2 | usage error |
| 5 | empty reply and every permission request was denied (the code acpx uses) |
| 75 | refused to start by `--max-load` |
| 124 | timed out (`session/cancel` sent first, then the agent is killed) |
| 130, 143 | interrupted by SIGINT, SIGTERM (with `--interactive` also 129 on SIGHUP; Ctrl-C cancels a running turn instead of exiting) |

A reply with text exits 0 even when every permission was denied (a `--perm
deny` review can still deliver its report); the summary line then carries a
`warning=`.

Run `acp-run --help` for every flag.

## Install

Needs [uv](https://docs.astral.sh/uv/) and the agents' own CLIs/adapters.

It is a single self-contained script (a `uv run --script` header pulls its
dependencies). On this machine it lives in djbclark-ade at `tools/acp-run/acp-run`
and is reached as `~/.local/bin/acp-run` → `~/ops/site-private/bin/acp-run` →
`~/ops/site-djbclark/tools/acp-run` → here. Elsewhere, copy the script onto
your PATH:

```sh
install -m 755 tools/acp-run/acp-run ~/.local/bin/acp-run
acp-run --list
```

The agent table reflects the machine it was written on (for example Cline is
pinned to the `cline-pass` provider, and `agy` runs Google's first-party ACP
server from `~/.local/share/agy-acp-server/`); edit `AGENTS`, `DEFAULT_SET` and
`YOLO_SET` at the top of the script for yours.

`agy` notes (verified 2026-10-09): YOLO is the session config option
`mode=yolo` (`default | auto_edit | yolo`), set automatically. agy runs
commands in whichever of its workspaces sorts first, often its own skills
dir rather than `-C`, so acp-run names the working directory at the top of
the prompt. It also drops `HTTPS_PROXY` for agy (Claude Code's opencodex
proxy answers it with 407).

**The clientInfo gate (2026-10-10).** agy_acp_server 1.3.0 offers its
non-Gemini models (`claude-opus-5-5-*`, `claude-sonnet-5-5-*`,
`gpt-oss-120b-medium`) only to clients whose ACP `clientInfo.name` it
recognises as Zed, Xcode or JetBrains; any other name gets the `gemini-*`
models alone, and `--model claude-...` fails with "no model". acp-run
therefore sends `zed` for agy (`CLIENT_NAME` in the script). Upstream:
google-antigravity/antigravity-cli#1168, pingdotgg/t3code#16489. If
`acp-run agy --info` lists no `claude-*` value, check that first.

**Which server (compared 2026-10-10).** acp-run keeps Google's own
`agy_acp_server.par` 1.3.0, the newest release (ACP registry
`antigravity-acp` and dl.google.com; agy CLI 1.3.3 ships no newer ACP
server). The alternatives and why not:

1. simonepri/refined-antigravity-acp 1.4.2 wraps the same binary, so it
   inherits the gate (our opt-in `REFINED_AGY_CLIENT_NAME`,
   simonepri/refined-antigravity-acp#49, is unmerged); it replaces the
   `mode` option and renames models to base id plus `thought_level`,
   injects steering prompts and rewrites the session SQLite. Its hang,
   crash-recycle and loop fixes are the reason to revisit it if those
   show up in agy runs.
2. shubzkothekar/antigravity-acp (Bun) spawns the `agy` CLI per prompt,
   the path with the hidden burst limit, and downloads its own `agy`.
3. An `agy -p` adapter of our own: the same burst-limit problem.

To try another server for one run, set `ACP_RUN_AGY_SERVER` to its
command (one path, `~` expanded), for example a newer server unpacked to
`~/.local/share/agy-acp-server/<version>/agy_acp_server.par`, or
`$(command -v refined-antigravity-acp)` once #49 lands (it needs
`REFINED_AGY_ACP_BIN` pointing at the 1.3.0 binary and its
`REFINED_AGY_CLIENT_NAME`). Unset it to go back. Check `--info` for the
`mode` option and model ids before relying on it: `YOLO_SET` and
`--model` use the stock server's names.

## Why not acpx?

[acpx](https://github.com/openclaw/acpx) is the maintained general-purpose ACP CLI
and is the better choice for most people. On 2026-10-05 it lacked two things this
script exists for: permission rules scoped to file paths, and per-agent
environment and default config options. If acpx gains those, a thin wrapper over
it would replace this script.

Several of the ideas above come from acpx (MIT): exit code 5, prompt retries on
transient errors, tool-kind inference from titles, cooperative interrupts.
