# deadline: a registered maximum run time, enforced from outside

2026-11-01. Why a new doc and not a section in `skills/loadwatch/SKILL.md`: loadwatch is the load watcher's role card; a deadline is
a rule every agent and script follows, whatever it runs, so it needs its own page that AGENTS-level text can link.

## The rule

**Before any command or wait that may run longer than ~2 min, register a deadline, or use `deadline run`.**
Hours were lost on 2026-11-01 to waits with no bound (`load-watch admit --wait` up to 2 h, a review wait of 2 h, `pr-wait` unbounded,
a lead blocked in a wait). A deadline names the maximum, an owner who is told when it passes, and what happens then.

## Commands (`bin/deadline`; `deadline --help` is the reference)

```sh
deadline run --budget 20m --heartbeat 5m --owner "$PASEO_AGENT_ID" -- bin/pr-wait 123      # register, run in its own group, deregister
deadline start review-123 --budget 2h --owner "$PASEO_AGENT_ID" --on-expire relay          # a wait with no process to kill
deadline beat review-123 --checkpoint /abs/path/state.json                                  # heartbeat + latest checkpoint
deadline extend review-123 --by 30m --reason "reviewer still running"                       # BEFORE expiry only; capped (default cap = budget)
deadline done review-123                                                                     # deregister (run does this itself)
deadline ls [--agents]                                                                      # records; --agents shows the Paseo idle reading
deadline sweep [--dry-run] [--json]                                                         # the enforcer; launchd runs it every 60 s
deadline install [--ade DIR] [--dry-run]  |  deadline uninstall                             # the launchd job (macOS)
```

`--on-expire`: `kill` (default: SIGTERM to the process group, SIGKILL after `--grace`, default 60 s; Hermes is pinged), `notify` (owner and Hermes
only, nothing killed), `relay` (kill, then tell the owner through `relay.py` with the name, budget, overrun and checkpoint), `reroute:RECORD`
(kill, then `acp-dispatch reroute RECORD --escalate --detach --no-wait`: route_agent climbs one rung of `[escalation]` in `config/routing.toml`;
deadline never names a model; the reroute is waited on up to 120 s and never killed if slower).
**A budget is enforced, never only announced.** The one named exception is the announce-only wait: a record with no `--pid`/`--pgid` has
nothing to kill, so `start` refuses the default `kill` for it (exit 2) and it must say `--on-expire notify`, `relay` or `reroute:RECORD`
explicitly; `--on-expire notify` with a pid is likewise the operator's explicit choice.
A record expires on its budget plus granted extensions, or, with `--heartbeat`, on that long without a `beat`. Recovery runs once; it is
written `started` before it runs, so a pass that dies midway never repeats it.
**A stop that did not happen is never recorded as a stop.** If the process is alive and the signal could not be delivered (the OS refused it,
the target is unsafe) or it survives SIGKILL plus a 2 s wait, the record goes to `kill-failed`: not terminal, the owner is relayed
"COULD NOT BE STOPPED" whatever the action (and nothing is rerouted: the work is still running), the sweep retries SIGKILL silently every pass, and
it becomes `expired` if the process finally dies. `deadline done NAME` acknowledges it and frees the name.

`deadline run` returns the command's rc (a signal death as 128+N), or 124 when the enforcer stopped the command (whoever did it, `run` or
the sweep), and enforces its own budget as a backstop; if the `run` process itself is killed, the sweep still enforces the record. A child that
exits between two `run` polls is not `lost`: while its `run` registrar is alive the sweep leaves the record for it to close. It exports
`DEADLINE_NAME` so the command can `deadline beat "$DEADLINE_NAME"`.

## Safety

1. A pid is signalled only if its start time (`ps -o lstart=`, or `/proc/PID/stat` on Linux) equals the one recorded at registration; a
   different start time is `lost` (pid reuse), never signalled. `start` refuses (exit 2) a pid that is not running or whose start time cannot be
   read, and a record that somehow has a pid but no start time is `lost (unverified)`, never signalled.
2. The group is signalled only when the registered pid leads its own group (or `--pgid` was given and `--pid` is in it); otherwise only the pid.
   Never pid 1, never the sweep's own group. A `--pgid` whose leader has already exited is anchored on a live member (its pid and start time are
   recorded as the record's pid); once that anchor is gone the record is `lost (unverified)`, because a bare group id could be recycled.
3. A top-level agent session is the operator's: `start` refuses (exit 2) any `--pid` that is the caller's own parent or an ancestor, and any
   group that is the caller's group or session or contains the caller or an ancestor, so an agent cannot register its own TUI or shell
   for a kill. (Fails closed: if `ps` cannot be read, it refuses.)
4. A record with a missing or non-numeric required key, or invalid JSON, is moved aside to `NAME.json.corrupt` and reported ONCE (the launchd log
   would otherwise grow every minute; `deadline ls` still lists it, and it is removed after 7 days). Each subprocess the sweep runs has a timeout; a
   record being advanced by another enforcer (`run` loop) is skipped (per-record `flock`). `sweep.log` is truncated past 1 MB. Names must match
   `[A-Za-z0-9_][A-Za-z0-9._-]{0,99}` and not be `agents` (the agent-check state file).
5. A watched process that is gone without `done` becomes `lost` and the owner is told.
6. Terminal records are pruned after 7 days, with orphan lock files. State: `~/.local/state/deadlines/` (`DEADLINE_STATE_DIR`), one JSON file per name.

## Known gaps (follow-ups, `docs/queue.md`)

The long-running wrappers (`pr-wait`, `load-watch admit --wait`, `acp-dispatch-wait`) do not yet register their own deadline by default (B9 rule 1),
and Linux has no systemd unit for the sweep (`install` is macOS launchd only; `sweep` itself runs on both).

## Agent-session no-progress check (alert only)

Every sweep (throttled to one scan per 5 min) lists running Paseo agents, background workspaces included (`paseo ls -g --background --json`), and reads each one's `UpdatedAt` from
`paseo inspect ID --json` (the `paseo logs` timeline carries no timestamps; `UpdatedAt` moved on every observed turn of a live agent). An
agent idle more than `DEADLINE_AGENT_IDLE` (default 30 min) that owns no live deadline record gets ONE `hermes-ping` and one relay, at most once
per agent per hour (`agents.json` in the state dir). It is never stopped: only a registered budget stops a process. An agent whose last
activity cannot be read is skipped, and `deadline ls --agents` says so; nothing is guessed. Limit: a single model turn longer than the threshold
that emits nothing reads as idle, so the message asks, not accuses.

## Prior art

Temporal Start-To-Close and Heartbeat timeouts with the checkpoint in the heartbeat; systemd `RuntimeMaxSec`, `WatchdogSec` and
`EXTEND_TIMEOUT_USEC`; Celery soft then hard time limits; enforcement, not notification (deepseek-harness discussion 11258); respect the
declared budget, no global staleness guess (Trinity issue 869); the enforcer lives outside what it watches. Links in the `bin/deadline` docstring.
This is the interim piece: the plan's B9 launchd watchdog absorbs it (`docs/paseo-only-rearchitecture.md`).

## Install

`deadline install` writes `~/Library/LaunchAgents/com.djbclark.deadline-sweep.plist` from `config/launchd/` and bootstraps it. It refuses from a
linked worktree unless `--ade DIR` names the canonical checkout. The lead installs it after review.

## Delivery and ownership details (PR 223 review, 2026-11-01)

1. The owner notice is tracked apart from the at-most-once kill and reroute: a relay that exits non-zero stays `notice.done = false` in the record and later
   sweeps retry it (at most 5 times, 60 s x attempt apart; `deadline ls --json` shows it). Recovery is marked done when the kill and reroute ran, not
   when the owner was reached.
2. `deadline run` reserves its name (a `starting` placeholder, left alone by the sweep for 60 s) BEFORE it starts the command, so a refused name never
   ran the command; and it only advances or finishes the record carrying its own `reg_id`, so an old `run` whose terminal name was registered again
   cannot mark the new registration done.
3. The owner relay asks for delivery proof (`relay.py ... --ack --wait 20`: exit 0 only when delivered; 1 not delivered and 3 unverified stay pending and
   are retried) and declares its sender (`RELAY_SENDER_NAME`, `deadline-sweep` in the launchd plist, `deadline` otherwise), since a launchd job has no
   session identity and relay.py refuses an unidentified sender with exit 4.
4. A stop is confirmed only when the target is `gone` (or its pid was recycled). `unverified` (a leaderless group whose anchor exited while other
   members may still run) is never a confirmed stop: the record goes to `kill-failed`, the owner is told, nothing is rerouted. An empty group is `gone`.
5. `deadline run` keeps enforcing after its command's leader exits: while the process group has survivors it sends SIGKILL after the grace and runs the
   recovery itself before returning 124.
6. Lock files are unlinked by `prune` only while it holds them; every acquirer re-checks that its locked inode is still the file on disk and retries
   otherwise, so two registrars never hold different inodes of "the same" lock. Terminal records are deleted under their lock after a fresh reload.
7. Recovery I/O (hermes-ping, owner relay up to 90 s, reroute up to 120 s) runs in a detached `deadline _work NAME` process, never inside the 60 s
   enforcement pass: the record is saved with the recovery order (`recovery.claimed` makes it at-most-once, and the worker claims it under the record lock
   before any call) and later records and SIGKILL escalations stay on schedule. `DEADLINE_INLINE_WORKER=1` runs the worker inline (tests).
8. `deadline run` starts its command behind a handshake: the command is exec'd only after its record (pid and start time) is persisted. If `run` dies or is
   interrupted in between, the pipe closes without "go" and the held child exits 111 without having run the command.
9. A live pid vouches for its process group only while `getpgid(pid)` still equals the recorded group; a process that left it makes the target
   `unverified` (never signalled). A failed `ps` read (non-zero exit other than the normal "no such pid", or stderr text) is `ProcUnknown`, never "gone".
10. The idle-agent alerts (ping + relay per agent) also go to a detached worker (`deadline _alert`), never inline in the enforcement pass. Workers
    and every relay call run without any inherited session identity (`PASEO_AGENT_ID`, `HERDR_PANE_ID`, `CLAUDE_CODE_SESSION_ID`, `HERMES_SESSION_ID`
    removed, `RELAY_SENDER_NAME=deadline` declared) and double-fork, so an owner that is the very agent that ran `deadline run` still receives its notice.
11. A recycled NON-leader anchor pid never confirms its group gone: the group is re-checked (`unverified` while other members live). A worker's
    result is merged only into the record carrying the `reg_id` it started from.
12. Interrupting `deadline run` (SIGTERM, SIGINT, SIGHUP) is a bounded stop: the record goes to `stopping` (`cancelled`), the command's group gets SIGTERM, then
    SIGKILL after `--grace` (a second signal escalates to SIGKILL at once). Nothing is announced or rerouted; `run` exits 128+signal.
13. The agent scan (`paseo ls` + `paseo inspect` per running agent) runs in a detached `deadline _agents` worker (throttled to one per 5 min, stamped at
    dispatch, one scan at a time by a lock), never inside the enforcement pass; `deadline ls --agents` still reads it synchronously.
    `--on-expire reroute:PATH` stores PATH resolved against the registering shell's directory. Interrupting `deadline run` after a notify-only
    expiry still stops the command (SIGTERM, then SIGKILL after `--grace`).
