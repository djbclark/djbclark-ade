---
name: loadwatch
description: >-
  Make this agent session the machine's one load watcher: register it with the
  launchd load-watch job (bin/load-watch, every 20 s) so every load incident,
  unexplained sustained load and launchd job-guard trip is sent here, replace any
  previous watcher, then investigate at once if the load is abnormally high. Use
  for /loadwatch, "watch the load", "you handle the load spikes", "why is the
  machine slow/hot", a load-watch brief or job-guard notice, or on resuming the
  load-spike-monitor-t chain.
---

# loadwatch: own the machine's load loop

Two halves that work together:

1. **`~/src/djbclark-ade/bin/load-watch`** (launchd `com.djbclark.load-watch`, every 20 s, no model). It
   samples load and `ps`, attributes sustained load (4.0 per core for 5 min; 2.0 until 2026-11-01) to agent sessions, writes a
   brief and relays it to the session it blames, guards launchd jobs (hangs, crash loops, CPU/memory), and
   pings Hermes. Its usage text is the reference for everything it does.
2. **The watcher: this session.** `load-watch watcher set` registers one session. From then on, every
   incident, every sustained load that no agent explains (stuck I/O, swap, background-QoS piles), and every
   job-guard trip is also sent here. This is the session with a model that investigates and fixes things.
   There is only ever one watcher: `set` replaces the old one and tells it so.

Chain: `load-spike-monitor-t` (`/baton load-spike-monitor-t`). It is a side-workspace chain, so the
`djbclark-ade` pointer stays with its own chain (djbclark, 2026-10-20).

## 1. Become the watcher (default action)

```sh
~/src/djbclark-ade/bin/load-watch watcher show          # who has it now (exit 1: nobody)
~/src/djbclark-ade/bin/load-watch watcher set --name "<this session's title>" --chain load-spike-monitor-t
~/src/djbclark-ade/bin/load-watch watcher test          # one line must arrive in this session
```

1. `set` with no flags registers the process's own session. A Paseo agent is registered by
   `$PASEO_AGENT_ID` and reached by `paseo send --behavior steer`, because relay.py has no pane to type
   into for one. Anything else is registered by `$CLAUDE_CODE_SESSION_ID` and reached by
   `skills/session-finder/relay.py`. For another TUI, pass `--relay <id|name|herdr pane>`.
2. If `set` printed `replaced ...`, the old watcher has been told. Say in your reply which session it was.
3. `test` exits 0 only when the channel reports the line was delivered or queued (relay.py's `queued: <id>` for a watcher that is busy and cannot steer counts here, and only here: the registration check is not time-critical, and the line arrives when the watcher is idle). An incident brief, a job-guard line and the "you are no longer the watcher" line are time-critical, so load-watch sends them with `--no-defer`: a busy watcher that cannot take one now is "could not reach it" and the existing fixer path runs, never "queued". If `test` exits 1, or the
   line never shows up, the watcher cannot be reached. Fix the channel (relay.py's refusal reasons, or
   `paseo ls`) before claiming the role. Never leave a watcher registered that cannot be reached.
4. **Record the role in the chain's Tier 1 log in the same turn, unasked** (djbclark, 2026-10-23: "update the
   skill to do that automatically"; never offer it as a question). Read
   `~/.local/state/handoffs/chains/load-spike-monitor-t/SESSION_LOG.md` first (a write replaces Current State
   and `workspaces` wholesale, so carry over any open blocker), then pipe a JSON payload to
   `~/.claude/hooks/handoff-tools/.venv/bin/python ~/.claude/hooks/handoff-tools/session_log.py write
   --state-root ~/.local/state/handoffs` (stdin from a file, `> out.log 2>&1; echo "rc=$?" > out.rc`). Payload:
   chain `["load-spike-monitor-t"]`, `active_work` naming this session's ids and the replaced watcher,
   `next_steps` with the `ack` and `watcher clear <target>` commands, and
   `workspaces: [{"repo":"djbclark-ade","task":"main","dir":"/Users/djbclark/src/djbclark-ade","side":true}]`.
   Update it again when the watcher is cleared or an incident is left open.
5. **On Paseo, a daemon restart (`paseo restart`, `daemon stop`, a crash) keeps your agent id and provider session
   but kills your process and drops the turn in flight** (2026-10-23, read from the daemon source; app quit and
   app updates leave this machine's daemon alone). You come back idle, and the next `paseo send` (the next
   incident) resumes you, so there is nothing to re-register. Keep state on disk and re-derive it on every
   wake. A line sent while the daemon is down is lost unless the gap is short (`send_to` retries a
   `paseo send` whose `--json` error code is exactly DAEMON_UNREACHABLE, DAEMON_CONNECTION_LOST, DAEMON_NOT_READY or
   DAEMON_NOT_RUNNING twice, 5 s apart, inside 30 s, 2026-10-23; once one send has given up, the other sends of
   that sample make one attempt each; the relay channel and other failures get one attempt; Hermes still gets the
   ping), so after any restart you see, read `load-watch incidents -n 5` for what you missed. A retry after
   DAEMON_CONNECTION_LOST (or a retry killed by its timeout) can deliver the line twice, and a timed-out retry can
   leave `last_fail` stamped though the line arrived: investigate idempotently from `incidents.jsonl`. Never run
   `paseo restart` yourself while other agents are working.

## 2. Is the load abnormal?

```sh
uptime
~/src/djbclark-ade/bin/load-watch admit --json      # per_core, plus streak and hot_for_s when sampling
~/src/djbclark-ade/bin/load-watch status            # hot window, top consumers, cooldowns
~/src/djbclark-ade/bin/load-watch incidents -n 5    # recent incidents and whether each was acked
gtail -n 5 ~/.local/state/load-watch/sample.log
gtail -n 10 ~/.local/state/load-watch/guard.jsonl
```

Investigate (section 3) when any of these holds. Otherwise report the numbers in one line and stop.

1. The 1-minute load per core is above **2.5** (`admit` says `hot`; that is 20 on 8 cores, `bg`'s base since 2026-11-01, was 1.5; the limit is **4.0** (32) while the compressor churn is at most 20k pages/s and the machine has been calm for 10 minutes (§2a; 25k and no hysteresis until 2026-11-01; 2.0 from 2026-10-25 to 2026-11-01; djbclark: 3.5 per core "is actually not too bad for this system", the real constraints are memory pressure and process churn), `max_per_core` in `admit --json` is the one in force; the same limit
   `bg` and `acp-dispatch` use) **and** the 5- or 15-minute average agrees. A 1-minute spike over a
   falling 15-minute average is agents starting up, not a problem: report it and move on.
2. `status` shows a hot streak (`hot for N/300 s`), or `sample.log` has a `sustained load` line from the
   last hour.
3. An incident has no `ack`, or `guard.jsonl` shows a trip or a `disabled` event from the last day.
4. A `load-watch: compressor churn ~Nk pages/s for 3+ min (limit 20k); top: ...` line arrived (2026-10-23, limit 60k until 2026-11-01;
   `status` shows `compressor churn` and the `churn` / `churn-watcher` cooldowns). The sample step reads the
   `vm_stat` compressor delta each 20 s; it is sent when churn stays above the `admit` limit for 180 s
   (`LW_CHURN_SUSTAIN_S`), to you at most hourly and to Hermes every 6 h. `admit` already holds new
   `bg`/`acp-dispatch` work, so the churn is from running or bypass work: find the top memory users with
   `/bin/ps -axo pid,rss,command -m | head` (not only the CPU list in the line), then section 3 as usual. The
   alert opens no incident and kills nothing; the Standing exceptions below only change the advice (the line
   says so when Grok, Chrome or WindowServer is in its top 3), never whether you investigate.

## 2a. The admit memory gates and the agent cap (2026-11-01)

Why: the load watcher's d8891c91 measured a sustained load of 35-70 on this 8-core, 16 GB Mac that was **memory
starvation, not CPU**: ~64 MB free, ~12k compressions+decompressions/s, ~1760 pageins/s, kernel_task 57% and sys 25-39% of
CPU, 31+ live agent processes (omp 20, copilot 11, claude 8, agy 3). The 4.0 calm boost let a slice start in every brief dip
and each start pushed memory back over: an oscillation. So `load-watch admit` (what `bg` and `acp-dispatch` call) fails
toward waiting: it refuses (exit 75) while **any** of these holds, and `--json` / the line name each in `refused`:

| gate (`refused` name) | default | flag | env |
|---|---|---|---|
| free + speculative memory below the floor (`free_mem`) | 600 MB | `--min-free-mb` | `LW_MIN_FREE_MB` |
| compressions + decompressions per second above (`compressor`) | 20000 (was 60000) | `--max-mem-churn` | `LW_MAX_COMPRESSOR_S` |
| pageins per second above (`pageins`) | 1000 | `--max-pageins` | `LW_MAX_PAGEINS_S` |
| live `acp-run` slices machine-wide at or above the cap (`agents`), **only for a caller that passes `--max-agents`** | 14 (bare `--max-agents`) | `--max-agents [N]` | `LW_MAX_AGENTS` (0 = off) |

**The cap gates only NEW agent starts.** `acp-dispatch` always passes `--max-agents`; `bg` never does, because a test run
starts no agent and gating it would starve the very slices the cap counts (at the cap each slice's `bg` test would be
refused, so the slice could never end and the count never fall; found by the adversary on PR 210). A plain `admit` runs no
`ps` and ignores the cap.

**`LW_MAX_AGENTS` is the knob djbclark tunes**: how many `acp-run` slices may be alive when a new one starts (not
interactive TUIs or Paseo agents, which `acp-run` does not own). Set it in the environment of the `acp-dispatch` run:
acp-dispatch drops every other `LW_*` variable (test hooks and import-time settings) but reads `LW_MAX_AGENTS`,
`LW_MIN_FREE_MB`, `LW_MAX_COMPRESSOR_S` and `LW_MAX_PAGEINS_S` itself and passes them to `admit` as flags (`--max-agents=N` ...),
and passes `LW_BOOST_CALM_S` through as an environment variable; a bad value is warned about and ignored. A refusal
prints `refused=agents` (or the other gate) in acp-dispatch's exit-75 line and in `load_gate.refused` of the record.
Raise the cap when memory has headroom (the other gates still hold); lower it when `vm_stat` shows free memory under 600 MB
with the cap not yet reached. The count is one `ps`, an exact argv match of the process running the script named `acp-run`
(never `pgrep -f`; `uv run --script` wrappers and mentions do not count).
**Reservations:** an admission under the cap is recorded in `~/.local/state/load-watch/agent-reservations.json` (under an
flock, the live `acp-run` count re-read inside the lock) and counted with the live agents until it is **released** or expires, so
dispatchers that read 13 of 14 at the same moment cannot all be admitted, and a runner queued in `wait_for_capacity` (up to
900 s) still holds its place. `admit --json` prints the `reservation` id (the text line prints `reservation=ID` too; a human who only wants to look uses `--no-reserve`, else `load-watch release ID`); acp-dispatch runs `load-watch release ID` once the
agent is countable (its process tree holds the `acp-run` process, not just the `uv run --script` wrapper; checked every 5 s, at most
10 min; the entry then lives 30 s more), when the agent ends, or on any exit after admission (`die()`, a refusal, an exception). With `--detach` the dispatching
process hands the reservation to the detached runner after a successful launchctl submit (the id stays in the job record's
`load_gate.reservation`) and does not release it on its own exit, so a `--wait-timeout` expiry cannot shorten it while the runner is
still waiting for capacity; the countable check also looks at the spawned process itself, not only its children.
The dispatch also runs `load-watch renew ID` every 60 s while it waits for capacity or for its agent to become countable (each renewal extends the entry by `LW_RESERVE_S`, never shortens it, never revives a lapsed one), so waits longer than `LW_RESERVE_S` (`ACP_DISPATCH_GATE_MAX`) keep the place. `LW_RESERVE_S` (1200 s, 0 = off) is only the backstop for a dispatcher that died; `--no-reserve` records none but still counts those held (a pure capacity check)
`admit --max-agents` a pure check. acp-dispatch validates the knobs once (a churn or pageins limit of 0 is ignored with a
warning, since admit exits 2 on it) and records them in the job record (`load_knobs`), so a `--detach --no-wait` runner under
launchd uses the same ones. An `admit` that exits 2 refuses the launch (exit 75), never admits it.
Rates come from two `vm_stat` reads 2 s apart. **A reading that fails where the tool exists** (vm_stat or ps times out,
exits non-zero, prints nonsense; likeliest exactly when the machine is starving) **refuses**: `refused=memory_unreadable` or
`agents_unreadable`. Only an absent tool (no `vm_stat` and no `/proc/meminfo`, no `ps`) leaves its gate open, listed in
`unreadable`. Linux reads `/proc/meminfo` MemAvailable and `/proc/vmstat` pswpin+pswpout and pgmajfault: uncalibrated (swap
pages/s against a line set for the macOS compressor, so that gate rarely trips there). Caveat: macOS `Pageins` also counts
file-backed reads, so read-heavy work (rg, git, builds) can trip the 1000/s gate with memory to spare; that errs toward
waiting, and `--max-pageins` / `LW_MAX_PAGEINS_S` raises it.

Hysteresis: the 4.0 per-core calm boost applies only after the machine has stayed calm (churn at most the compressor
limit, free memory above the floor, pageins under their limit) for `LW_BOOST_CALM_S` (600 s) without a break. Any hot
reading by `admit` (whatever its own `--boost-per-core`) or by the 20 s sampler resets the clock (`~/.local/state/load-watch/calm.json`); `status` shows
`calm boost: calm for N/600 s` and `admit --json` carries `calm_for_s`.

## 3. Investigate

Verify against the processes themselves, not against memory or the brief's guess (standing order 4).

1. **Who uses the CPU: call `/bin/ps` and `/usr/bin/top` by full path, never bare `ps`/`top`.** In some agent
   harnesses (omp, 2026-11-01) bare `ps` and `top` are shell builtins with wrong numbers: builtin `ps` showed 11 s
   of CPU and ~0% for an `opencode serve` that `/bin/ps` showed at 7 min 42 s and 60%, and it hid `mds` (87%),
   Finder (61%) and a semgrep hook (130%), so a watcher reported "nothing heavy" during a load of 50 (`type -a ps`
   tells). And `%cpu` from `ps` is a decaying average: measure a window with
   `/usr/bin/top -l 2 -s 5 -o cpu -n 30 -stats pid,command,cpu,th,state,time` (read the second sample) and add
   `kernel_task` plus the `sys` share. High `sys` with a busy `kernel_task` is a lead, not a diagnosis: confirm
   memory compression before calling it that, with `load-watch admit --json` (`mem_churn_pages_s`) or two
   `vm_stat` reads a few seconds apart (Compressions, Decompressions and Pageins deltas). `kernel_task` also takes
   CPU on purpose to cool the machine (`pmset -g therm` then shows a thermal or performance warning level; with none
   it prints "No thermal warning level has been recorded") and for other kernel work, and none of these rules out a
   build or test: still read the process list below for one.
   Then `/bin/ps -axo pid,ppid,%cpu,state,etime,time,command -r | ghead -20` for parents and ages. Map each heavy
   process to a session: `~/src/djbclark-ade/skills/session-finder/fleet.py list`, and `fleet.py show <id>`.
2. **Load without CPU:** processes in state `U` (stuck in disk or network wait, unkillable: the AFS case on
   2026-10-18), swap (`sysctl vm.swapusage`), and processes runnable at background priority (2026-10-18's
   load 110 was orphaned scans). `sample.log`'s `sustained load` line already counts all three.
3. **An agent's build or test:** it should have gone to CI. Read the incident brief
   (`~/.local/state/load-watch/briefs/<id>.md`). Make sure the blamed session got it (`relayed=True`);
   if not, relay it with `skills/session-finder/relay.py`, or `paseo send` for a Paseo agent. Check the
   repo's CI decision with `load-watch ci check <repo>`. A targeted test run in a `ci` repo stays on this Mac
   only while the load gate lets it: held past `BG_OFFLOAD_AFTER` (60 s, 2026-10-23) `bg` runs it on CI through
   the repo's tracked `scripts/bg-offload-run` or `scripts/github-ci-run` (`bin/bg-offload` in site-djbclark), so such a run
   waiting an hour means: the repo has no tracked route (or is a linked worktree), `gh` or a GNU tool is missing, `BG_OFFLOAD=0`,
   the tree has unpublished work (a modified tracked file, a commit or `ci/base` that the push target's `git ls-remote <remote>`
   does not show, history rewritten by a graft file, a remote with a separate pushurl or several urls, or an unreachable remote),
   a partial clone missing objects of HEAD's or `ci/base`'s tree that cannot be fetched, a named test path is missing or untracked,
   or the runner failed after a push attempt (bg prints which): fix that, do not work around the gate. `bg-offload` publishes
   nothing that is not already on the remote and has no opt-in (six review rounds, 2026-10-23), so the dev flow is: commit and
   push, then `bg` offloads. Exits: 1 CI failed, 76 CI still running, 77 no verdict (`bg` header).
4. **A launchd job:** `load-watch guard status`. A tripped job has already been booted out and cooled
   down. Find out why from its logs, never by re-enabling it blind. Check `site-private/memory/` before
   "repairing" a stopped or disabled service (`~/CLAUDE.md` item 18).
5. **Never kill or throttle another session's work** (`~/CLAUDE.md` items 9 and 34). The levers are:
   ask the session to offload (`bin/session-load-watch`, or one relay line), steer future runs to CI
   (`load-watch ci decide`), and guard a job (`load-watch guard add`). Anything that stops paid-for work
   needs djbclark's yes.
6. **Close the loop:** answer each incident with `load-watch ack <id> "<what you found and did>"`, then
   tell djbclark in one line and with `~/.local/bin/hermes-ping "load-watch: <one line>"`.

## 4. Hand the role over or drop it

1. A new session runs this skill: its `set` replaces you and tells you. Stop any load follow-up you are
   running.
2. Ending the session with no successor: `load-watch watcher clear <your target>`, so the job stops
   sending to a dead session. A failed send is never fatal (the record gets a `last_fail` stamp, and
   Hermes still gets every ping), but a stale watcher means nobody investigates.
3. `/handoff` or `/loose` at the end: list the role, and any un-acked incident, as open.

## Standing exceptions (djbclark, 2026-10-23)

1. **Grok Bot and Chrome: warn only if out of line or if the machine is slow.** Their renderers and GPU
   helpers routinely use 0.3-0.7 cores each (2026-10-23: Grok Bot renderer 50-70%, Chrome renderers 17-27%,
   with `WindowServer` at 74% and swap 92%). Do not ping Hermes or ask djbclark to quit or reload them for
   that alone. Warn only when (a) their use is well above that range (compare earlier `sample.log` top lines
   and `ps`), or (b) load, memory pressure or CPU is visibly slowing the machine (stuck `U` processes, rising
   pageouts with low free memory, agents timing out). Still investigate and `ack` as usual; the exception
   only silences the "quit this app" advice.

Chrome CPU alerts must match the alerted PID to its Task Manager row (2026-10-29). A Browser, GPU,
or utility-process alert does not establish a busy tab: report the task name and CPU percentage
without guessing a tab. A renderer can host a tab or extension; only an identified tab and the
operator's choice justify ending/reloading that tab. Never kill or restart Chrome yourself.

## What this is not

1. Not a scheduler. Never `/loop` or CronCreate a load check: it is a poll whose firings mostly find nothing
   (`~/CLAUDE.md` item 13). The launchd job is the periodic part, and this session reacts to what it sends. For
   the same reason there is no heartbeat to wake you after a Paseo restart (item 13's "recurring wake nothing
   else can do" does not apply: the next incident's `paseo send` already resumes you).
2. Not a licence to fix the load by stopping work. See section 3 item 5.
