# Stalled sub-agent detector (2026-11-22)

`bin/ade-subagent-stalls` (module `bin/ade_subagent_stalls.py`) finds Agent-tool sub-agents that died mid-run and tells the operator and the
parent. It only reports and notifies: it never resumes, restarts, archives or kills anything. Zero model tokens.

## Why

Operator, 2026-11-22: "Build it in djbclark-ade instead", with fleet-watch calling it. On 2026-11-21/22 a background `adversary` sub-agent of
a parent session was killed mid-run (its last tool result was `Exit code 144`, no output, no later API request) while the parent sat idle, and
nobody noticed for about 14 hours. One `SendMessage` resumed it from its transcript and nothing was lost but the time. Who killed it is
unknown (the Paseo daemon logs had rotated); the evidence file is
`~/.local/state/agent-reports/1703aef2-a7df-47c4-89a1-9adc6102d2f5/subagent-abort-evidence-20261122.md`, whose "fix 1" is this tool. The same
day's first scan found 17 more sub-agents orphaned about 20 hours earlier, each with a tool result as its last record (for the one inspected,
`Exit code 137`), so this is not rare.

## What counts as stalled

A **stub** is an agent-report file `~/.local/state/agent-reports/<session>/<name>-report.md` whose first line is `STATUS: working` and that has
no `<report>.done` (the delivery footer, [dispatch-footer.md](dispatch-footer.md), makes every sub-agent write one first). A stub is
**stalled** when the transcript that writes it, `~/.claude/projects/<proj>/<session>/subagents/agent-<id>.jsonl`:

1. has not been written for more than `--stale-min` minutes (default 10), and
2. its last *message* record (a `user` or `assistant` record; attachments, `api-request` and the like are bookkeeping) is not a final assistant
   message (`stop_reason` `end_turn` or `stop_sequence`).

Stubs whose file is older than `--max-age-h` (default 48) are skipped.

**A pending tool call gets a grace period.** When the last message is an assistant `tool_use`, the tool may still be running (a 25-minute
`bgrun` test run, `wait-file --timeout 1500`), and the transcript does not grow while it does. That case waits `--tool-grace-min` (default 35,
just over the 30-minute foreground cap) or the call's own `timeout` plus 5 minutes, whichever is longer. A death while a tool runs is still
found, 35 minutes later instead of 10; a tool result as the last record (the 2026-11-22 case) is found at `--stale-min`.

## Linking a stub to its transcript (never a guess)

`agent_footer_gate.py` derives the report path from the launch (`<session>/<slug(description)>-report.md`, or a path the prompt labels), and
puts it in the prompt as the footer's delivery line. A stub is linked to a transcript when:

1. the transcript's first record (the sub-agent's prompt) names the stub's absolute path as its **own** report: the footer's
   ``deliverable to `<path>` `` line, a `Report path:` / `Report:` label, or the only `*-report.md` path in the prompt. A path mentioned as
   background next to another own report does not link; or
2. only when that prompt names no `*-report.md` path at all, the transcript is in the stub's session directory and the `description` in its
   `.meta.json` slugs (same `slug` as the hook; `tests/test_subagent_stalls.py` pins the parity) to the stub's name.

No link: the stub is reported as **unlinked** (a `paseo run` worker's stub, or a transcript that is gone). Several transcripts for one stub (a
resumed or relaunched agent): the stub is stalled only when every one of them is, and the newest is named.

## Output and exit codes

`ade-subagent-stalls [--json] [--stale-min N] [--max-age-h N] [--tool-grace-min N] [--home DIR]`

- Plain text, or `--json`: a list of `{report, session_id, agent_id, transcript, idle_min, parent_session, parent_paseo_agent_id,
  parent_live, last_record, link, suggested_action}`. `parent_paseo_agent_id` is the Paseo agent whose Claude session is the transcript's
  session (read from `~/.paseo/agents/*/*.json`; null when none). `suggested_action` is `SendMessage to <agent_id> from session <parent> to
  resume`, or, when the parent is a live (not archived) Paseo agent, `paseo send --json --no-wait <parent> "..."`.
- Exit 0 nothing stalled, 1 something is (unlinked stubs alone do not count), 2 error (bad option, hermes-ping missing with `--notify`).
- The resume itself is the lead's act: `SendMessage` to the sub-agent id, "resume from where you stopped" (the Agent tool's resume path;
  the footer hook's resume guard tells the same story at the next launch).

## `--notify`

For each **new** stall (state `~/.local/state/djbclark-ade/subagent-stalls/seen.json`, written atomically under a lock):

1. `hermes-ping "djbclark-ade: stalled sub-agent <agent_id> (report <path>), idle <n> min; parent <id>"`;
2. when the parent is a live Paseo agent: `paseo agent inspect <parent> --json`, and only when it reads `Archived: false` and `Status: idle`,
   `paseo send --json --no-wait <parent> "<the resume instruction>"`. A busy parent is never sent to (a sourceless send to a running agent
   interrupts its turn) and an archived one never woken; the send is retried on the next run until it goes through.

Each action repeats for the same stall at most once per `--repeat-h` (default 6). A failed ping or send is not recorded, so it is retried. A
stall that is no longer stalled is dropped from the state, so a recurrence pings as new. `--max-pings` (default 5) caps pings per run;
`--dry-run` prints what would be sent and writes nothing; **`--baseline`** records every stall found now as known and announces nothing, for
the run that switches the watcher on (otherwise the first run pings every orphan of the last 48 hours). Both tools are called by the absolute
paths `~/.local/bin/hermes-ping` and `~/.local/bin/paseo` (override: `--hermes-ping`, `--paseo`); nothing looks at PATH.

## Hook-in (site-private)

`fleet-watch` lives in `~/ops/site-private-djbclark/bin` (another repo; not edited from here: `~/CLAUDE.md` item 13 and AGENTS order 11, so
the hook-in waits for the operator's yes). Once, to start quiet:

```
~/src/djbclark-ade/bin/ade-subagent-stalls --notify --baseline
```

Then one line in fleet-watch's periodic pass (exit 1 means "stalls exist", not failure, hence `|| true`):

```
"$HOME/src/djbclark-ade/bin/ade-subagent-stalls" --notify >>"$HOME/.local/state/djbclark-ade/subagent-stalls.log" 2>&1 || true
```

The scan reads the 48-hour window of stubs and the matching transcripts; a run took 5 to 8 seconds on 2026-11-22 (30 working stubs in the window).

## Limits

- Detection is by silence: a sub-agent that is alive but blocked for more than the threshold in a non-tool wait (a very long single model
  response) reads as stalled. The ping says "idle <n> min"; the resume `SendMessage` to a live agent is harmless but unneeded.
- Only Agent-tool sub-agents are linked. A `paseo run` worker's stub is "unlinked"; those have their own tooling (`ade-tidy`,
  `bin/deadline`).
- A parent that is a Claude session outside Paseo has no `parent_paseo_agent_id`: only the hermes-ping goes out.
- It does not say who or what killed the sub-agent. The evidence file's fix 2 (a durable log of agent process exits, interrupts and cancels)
  is separate and not built here.
