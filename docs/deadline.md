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

`--on-expire`: `kill` (default: SIGTERM to the process group, SIGKILL after `--grace`, default 60 s; Hermes is pinged; with no pid to kill the
owner is told instead), `notify` (owner and Hermes only, nothing killed), `relay` (kill, then tell the owner through `relay.py` with the
name, budget, overrun and checkpoint), `reroute:RECORD` (kill, then `acp-dispatch reroute RECORD --agent omp --model anthropic/claude-sonnet-5-5 --detach --no-wait`).
A record expires on its budget plus granted extensions, or, with `--heartbeat`, on that long without a `beat`. Recovery runs once; it is
written `started` before it runs, so a pass that dies midway never repeats it.

`deadline run` returns the command's rc, or 124 when it stopped the command (like `timeout`), and enforces its own budget as a backstop; if
the `run` process itself is killed, the sweep still enforces the record. It exports `DEADLINE_NAME` so the command can `deadline beat "$DEADLINE_NAME"`.

## Safety

1. A pid is signalled only if its start time (`ps -o lstart=`, or `/proc/PID/stat` on Linux) equals the one recorded at registration; a
   different start time is `lost` (pid reuse), never signalled.
2. The group is signalled only when the registered pid leads its own group (or `--pgid` was given); otherwise only the pid, so a shell shared
   with the caller is never taken down. Never pid 1, never the sweep's own group.
3. One bad or corrupt record is reported and skipped; each subprocess the sweep runs has a timeout; a record being advanced by another
   enforcer (`run` loop) is skipped (per-record `flock`).
4. A watched process that is gone without `done` becomes `lost` and the owner is told.
5. Terminal records are pruned after 7 days. State: `~/.local/state/deadlines/` (`DEADLINE_STATE_DIR`), one JSON file per name.

## Agent-session no-progress check (alert only)

Every sweep (throttled to one scan per 5 min) lists running Paseo agents (`paseo ls -g --json`) and reads each one's `UpdatedAt` from
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
