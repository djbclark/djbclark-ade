# deadline: a registered maximum run time, enforced from outside

2026-11-01. A deadline is a rule every agent and script follows, whatever it runs, so it has its own page that AGENTS-level
text can link.

## The rule

**Before any command or wait that may run longer than ~2 min, register a deadline, or use `deadline run`.**
Hours were lost on 2026-11-01 to waits with no bound (`load-watch admit --wait` up to 2 h, a review wait of 2 h, a PR waiter unbounded,
a lead blocked in a wait). A deadline names the maximum, an owner who is told when it passes, and what happens then.

## Commands (`bin/deadline`; `deadline --help` is the reference)

```sh
deadline run --budget 20m --heartbeat 5m --owner "$PASEO_AGENT_ID" -- gh pr checks 123 --watch --required   # register, run, deregister
deadline start review-123 --budget 2h --owner "$PASEO_AGENT_ID" --on-expire relay          # a wait with no process to kill
deadline beat review-123 --checkpoint /abs/path/state.json                                  # heartbeat + latest checkpoint
deadline extend review-123 --by 30m --reason "reviewer still running"                       # BEFORE expiry only; capped (default cap = budget)
deadline done review-123                                                                     # deregister (run does this itself)
deadline ls [--agents]                                                                      # records; --agents shows the Paseo idle reading
deadline sweep [--dry-run] [--json]                                                         # the enforcer; launchd or a systemd user timer runs it every 60 s
deadline install [--ade DIR] [--dry-run] [--backend auto|launchd|systemd|cron] [--agents auto|on|off] [--allow-no-linger]  |  deadline uninstall [--backend ...]   # the sweep job
```

`--on-expire`: `kill` (default: SIGTERM to the process group, SIGKILL after `--grace`, default 60 s; Hermes is pinged), `notify` (owner and Hermes
only, nothing killed), `relay` (kill, then tell the owner through `relay.py` with the name, budget, overrun and checkpoint), `reroute:RECORD`
(kill, then `acp-dispatch reroute RECORD --escalate --detach --no-wait`; deadline never names a model; the reroute is waited on up to 120 s
and never killed if slower. Since 2026-11-07 the acp-dispatch shim retires `reroute` (exit 2) and route_agent's `[escalation]` ladder is gone,
so this mode kills and pings "reroute FAILED": re-dispatch the slice on the next rung by hand, `model-routing` D2).
**A budget is enforced, never only announced.** The one named exception is the announce-only wait: a record with no `--pid`/`--pgid` has
nothing to kill, so `start` refuses the default `kill` for it (exit 2) and it must say `--on-expire notify`, `relay` or `reroute:RECORD`
explicitly; `--on-expire notify` with a pid is likewise the operator's explicit choice.
**`--holder PID` (2026-11-02; announce-only `notify`/`relay` records, so no `--pid`/`--pgid`: exit 2 otherwise, or for a pid that is not running).** An announce-only record has
no process of its own, so nothing tells the sweep that the party meant to heartbeat it has died. `--holder` names that party: the process whose
beats keep the record. If the holder is gone (same pid AND start time, the same verification as every pid here; a zombie is gone) and `done` was
never called, the record was **abandoned**, not overdue: the sweep retires it as state `abandoned` (terminal, pruned after 7 days), prints one
`abandoned (holder N gone)` line to `sweep.log`, and tells nobody: no owner notice, no Hermes ping, no recovery. This wins over an expired
budget on the same pass. The holder is **never signalled**, so the registration refusal for a pid that is the caller's own ancestor (which exists to
stop a process from killing itself) does not apply to it: `bg`'s watcher and `bg` itself are legal holders. A record without `--holder` behaves
exactly as before; an announce-only wait with no heartbeating process is legitimate and still announces when it expires.
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
5. A watched process that is gone without `done` becomes `lost` and the owner is told. A `--holder` that is gone without `done` makes the record `abandoned`, silently (above).
6. Terminal records are pruned after 7 days, with orphan lock files. State: `~/.local/state/deadlines/` (`DEADLINE_STATE_DIR`), one JSON file per name.

## Waiters register themselves (2026-11-02)

`bin/load-watch admit --wait S` (S > 0; a pure check waits for nothing) and `bin/acp-dispatch-wait` register a deadline for their own
wait by default, through `deadline run` (B9 rule 2; budgets are the plan's B9 rule 3). A waiter holds no work, so on expiry the action is `kill` of
**its own process group** and nothing else: nothing is lost, and the caller sees exit 124 (re-run it).
Two exceptions. `acp-dispatch-wait` exits **76**, never 124: 124 already means "the record's `wait_timeout` passed" (the slice timed out), and a lead that
read a deadline stop as that would re-task a slice that is still running; 76 means only the waiter was stopped, so re-arm with the same line. It tells the
two apart by the record's state (`expired`) after `deadline run` returns 124. And `load-watch admit`: its callers (`acp-dispatch`, `bg`) fail OPEN on an exit they do not know, so a deadline stop is
answered as **exit 75, "still too hot"** (with a stderr line), the answer the wait would have given had it run out.

|waiter|name|budget|heartbeat|
|---|---|---|---|
|`load-watch admit --wait S`|`admit-wait-<pid>`|min(S, 30 min) + 60 s (the admission class maximum)|per poll; timeout 5 min|
|`acp-dispatch-wait RECORD DONE`|`dispatch-wait-<record file name>-<pid>`|min(the record's `wait_timeout` read at arm time, 2 h) + 60 s (2 h when 0 or unreadable; 2 h is the longest a lead's tool holds a waiter, so a longer slice is covered by re-arming on 76)|per 60 s pass; timeout 10 min|

The 60 s margin lets the waiter's own timeout path (it writes its result files) finish before the enforcer can fire; a registered waiter therefore
never outlives its own `--timeout`/`--wait` by more than the margin plus the sweep's worst overrun (about two minutes). Owner: the caller's
`PASEO_AGENT_ID`, else none (`-`: the sweep pings Hermes). The record is the same `kind: run` record as any `deadline run`.

1. **Why a supervisor.** `deadline start --pid` refuses the registrar's own parent (safety rule 3), so a process cannot register itself. The waiter
   runs *itself* under `deadline run --name N --budget B --heartbeat H --on-expire kill -- SELF ARGS` and returns its exit code; the inner copy
   waits. `bin/deadline` is unchanged, and `done` on every exit path (success, failure, signals: the supervisor forwards SIGTERM/SIGINT/SIGHUP
   once) is `deadline run`'s own bounded stop. `bin/deadline_wait.py` is the Python waiter's code (the PR waiter that shared it was removed 2026-11-06, slim-down E8); `acp-dispatch-wait` does the
   same in bash. The price is one resident `deadline run` Python process per registered waiter (`acp-dispatch-wait` was bash-only by design on
   2026-10-18; `--no-deadline` restores that; whether this waiter should be opt-in is the operator's call).
   Names carry the supervisor's pid (each run leaves one terminal record file until `prune` removes it after 7 days), so a second waiter for the same PR (another repo, a new head) or record (a re-arm) is never refused as "name already live".
2. **Opt out and nesting.** `--no-deadline` on each. A waiter started under `deadline run` (env `DEADLINE_NAME` set, even empty) does not register
   again and does not beat the caller's record; the inner copy of a supervised waiter sees the same variable, which is also what stops a loop. The inner
   copy removes `DEADLINE_WAIT_NAME/MARK/SUPERVISOR` from its environment on entry (it keeps its identity in process state), so what it starts
   inherits only `DEADLINE_NAME`: its waiters skip registration and can neither beat this record nor touch the start mark.
3. **Never costs the wait.** The inner copy touches `$DEADLINE_WAIT_MARK` on its way in. If the supervised run never got there (the deadline tool is
   missing or not executable, crashed, or refused: the name is already live) the supervisor warns ONCE on stderr and waits in its own process,
   unregistered. A failing heartbeat (3 misses in a row) is one warning and no more beats; the wait goes on. Test seams: `DEADLINE_BIN`,
   `DEADLINE_WAIT_BEAT_EVERY`. The start mark lives in a private `mkdtemp` directory (0700), removed on every path.
   **Signals.** SIGTERM/INT/HUP to the supervisor stop the wait with the bounded stop of `deadline run`; the bash supervisor starts `deadline run` in its
   own process group (`set -m`), so a signal sent to the whole caller group reaches it once, never twice (a second signal means SIGKILL without grace).
   `done` holds for every *catchable* exit; a SIGKILLed supervisor cannot stop its child, so the supervised copy checks the supervisor's pid on every
   poll (beat; the bash waiter every 10 s tick) and ends itself with 143: no orphaned wait. The enforcer still bounds it.
4. **Tests** (`tests/test_deadline_wrappers.py`) run each waiter against a temp `DEADLINE_STATE_DIR`; `tests/conftest.py` exports an empty
   `DEADLINE_NAME` so no other test registers in the real state directory.

## Known gaps (follow-ups, `docs/queue.md`)

`bin/review-pr` and `gh pr checks --watch` do not register a deadline of their own (2026-11-06): run them under `deadline run` (the example
above); `bin/review-launch` bounds its own run with `--timeout` (default 900 s) and kills the run's process group at the end. `bg` registers since
2026-11-01 (below).

## `bg` records and the holder (2026-11-02)

`bg` (`~/ops/site-private-djbclark/bin/bg`, alert-only) registers two `--on-expire notify` records, each with a `--holder`: `bg-wait-PID-T` for the load/slot
wait (holder: `bg` itself, which beats it) and `bg-run-PID-T` for the run (holder: the detached watcher, which beats it). The run record is registered
only once the run has started: `bg` writes a private marker file just before it execs the command, and the watcher registers when it sees it; if `bg` is
gone first, nothing is registered. Before the holder existed, a watcher killed with its process group (or a `bg` SIGKILLed, so its EXIT trap never ran)
left a record nobody would ever close, and 30 min later the sweep told the owner "expired ... Recover: rerun the unfinished part" for work that never
ran (seen 2026-11-02, about 17 such records). Now the sweep retires such a record as `abandoned`, silently. `bg` cannot use `--pid` for this:
`deadline start` refuses a pid that is its own caller's ancestor (it would be signalled), and a holder is never signalled.

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

`deadline install` reads `config/launchd/com.djbclark.deadline-sweep.plist`, fills `__ADE__`, `__HOME__` and `__STATE__` into the parsed plist and installs
it through the shared scheduler (`bin/ade_sched.py`, [scheduling.md](scheduling.md)); it refuses from a linked worktree unless `--ade DIR` names the
canonical checkout. The lead installs it after review. Options:

- `--backend auto|launchd|systemd|cron` (default `auto`: launchd on macOS, a systemd user timer on Linux, cron when there is no systemd).
- `--agents auto|on|off` (default `auto`): `off` appends `--no-agents` to the sweep argv. `auto` is `on` only if `paseo` is found on the PATH the *job*
  runs with (the plist's `PATH` plus `~/.local/bin`), else `off`; the install prints which it chose and why.
- `--allow-no-linger` (systemd): install although `loginctl` reports `Linger=no`. Without it that is exit 69, because a user manager without linger stops
  its timers at the last logout.
- `--dry-run`: print every file and command, change nothing.

Exit codes: 0 done; 1 an activation command failed; 2 a bad job, a linked worktree, or a bad plist; 69 no usable scheduler (none found, the systemd user
manager unreachable, `Linger=no` without `--allow-no-linger`, or cron asked to do what it cannot). `deadline uninstall [--backend ...]` removes the job
(not installed is exit 0); records are kept.

### Linux (2026-11-04)

macOS: `~/Library/LaunchAgents/com.djbclark.deadline-sweep.plist`, as before. Linux: `com.djbclark.deadline-sweep.service` and `.timer` in
`~/.config/systemd/user` (`OnUnitActiveSec=60s`, `KillMode=process` so the detached workers survive the sweep, `DEADLINE_STATE_DIR` in the environment),
activated with `systemctl --user daemon-reload` and `enable` of the timer. Check with `bin/ade-sched status com.djbclark.deadline-sweep` and
`systemctl --user list-timers`.

**The bot box today** runs `deadline sweep --no-agents` from monit every 5 minutes. After `deadline install` on that box, remove the monit entry by
hand: two schedulers are safe (every record is under its own flock) but they double the agent scan. `deadline` never edits monit configuration.

## Delivery and ownership details (PR 223 review, 2026-11-01)

1. The owner notice is tracked apart from the at-most-once kill and reroute: a relay that exits non-zero stays `notice.done = false` in the record and later
   sweeps retry it (at most 5 times, 60 s x attempt apart; `deadline ls --json` shows it). Recovery is marked done when the kill and reroute ran, not
   when the owner was reached.
2. `deadline run` reserves its name (a `starting` placeholder, left alone by the sweep for 60 s) BEFORE it starts the command, so a refused name never
   ran the command; and it only advances or finishes the record carrying its own `reg_id`, so an old `run` whose terminal name was registered again
   cannot mark the new registration done.
3. The owner relay reads delivery proof from the relay shim (2026-11-06, docs/slim E3: `relay.py OWNER --message-file -`, which reads `paseo send
   --json`'s `.status`: exit 0 only for `sent` or `completed`, which a sourceless send such as deadline's gets; 2 not delivered (`queued`, `timeout`,
   `permission`, `error`, or a target `paseo agent inspect` does not show idle or running with no card), 1 paseo failed, 3 not a Paseo agent and 4 no
   sender stay pending and are retried) and declares its sender (`RELAY_SENDER_NAME`, `deadline-sweep` in the launchd plist, `deadline` otherwise),
   which the shim names in a `[relay from NAME]` prefix, since a launchd job has no Paseo id.
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
14. Cancelling `deadline run` keeps going until the whole process group is gone (also after the leader exited, bounded 10 s after SIGKILL), and
    a cancellation during an expiry stop is recorded (`cancelled`, grace clock kept) so no recovery or reroute runs. A terminal name whose owner notice
    is undelivered (retries left) or whose recovery order is unfinished cannot be registered again until settled (work untouched for 30 min no longer
    pins it). Corrupt records are quarantined only after a fresh read under their lock.
15. Start times are compared for zombies too (a recycled pid or leader that is already an unreaped zombie is `reused`, never an authorisation to
    `killpg` its live children). `extend` and `beat` are refused (exit 2) once the heartbeat timeout has elapsed, like the budget: a late call
    does not revive an expired deadline between sweeps.
16. `deadline run` does not mark a record `done` while members of the command's process group outlive its leader: the budget keeps binding them
    (stopped with 124 on expiry); once the group is empty it is `done` with the leader's rc. Registration records the start time it verified and refuses
    (exit 2) a target that vanished or changed meanwhile, never crashes.
17. A process group whose leader has exited is signalled only with a verified member: one seen alive earlier (`anchor`, pid + start time, refreshed on
    every pass while the leader is verified, and still in the group) or a live `deadline run` registrar; otherwise it is `unverified` (a recycled group id
    cannot be told from the original survivors). Start times differ after a reboot, so stale records never match. A `run` cancelled after its record was
    persisted but before the command was released removes that record (the command never ran: no lost-process notice).
18. On Linux the process identity token is `<boot_id>:<start tick>` (`/proc/sys/kernel/random/boot_id`), so a record from before a reboot never matches a
    new process with the same pid and tick. macOS `ps -o lstart=` is an absolute time and needs no boot id.
19. `deadline install` renders the state directory it was run with (`DEADLINE_STATE_DIR` or the default) into the job's environment and log paths, so the job
    sweeps the same records the registrations wrote. A `kill-failed` record queues its notice retry and still retries SIGKILL in the same pass.
20. `start` records a live non-leader member as the group's anchor at registration (not only on the first pass), so a leader that exits before the first
    sweep does not turn the registration into `lost`. When the owner stays unreachable through all 5 notice attempts, one Hermes ping says so (`notice.escalated`).
21. Names are compared case-insensitively (reserved `agents`, and two names differing only in case are refused: one file on a case-insensitive volume). The sweep
    advances only the record it re-reads under the lock; one deleted since its snapshot is skipped, never resurrected from the stale copy.
22. A failed automatic reroute (`acp-dispatch reroute` exits non-zero) is never silent: the worker queues a tracked owner notice (retried like any other) and
    pings the operator once; the dispatch itself stays at-most-once. `deadline ls --json` shows the recovery outcome and whether the owner notice was delivered.
23. A reroute still running when the worker's wait ends (`DEADLINE_REROUTE_WAIT`, default 900 s; the worker is detached) is reported as outcome UNKNOWN, never as a
    failure: the owner notice and operator ping say so and tell the reader to check `acp-dispatch` before rerouting again. The dispatch is never killed.
