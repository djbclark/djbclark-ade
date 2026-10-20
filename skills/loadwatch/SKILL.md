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
   samples load and `ps`, attributes sustained load (2.0 per core for 5 min) to agent sessions, writes a
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
3. `test` exits 0 only when the channel reports the line was delivered or queued. If it exits 1, or the
   line never shows up, the watcher cannot be reached. Fix the channel (relay.py's refusal reasons, or
   `paseo ls`) before claiming the role. Never leave a watcher registered that cannot be reached.
4. Record the role in the chain's Tier 1 log (`session-handoff` writer protocol, chain
   `load-spike-monitor-t`, every workspace `"side": true`) with this session's ids, so the next session
   knows who holds it.

## 2. Is the load abnormal?

```sh
uptime
~/src/djbclark-ade/bin/load-watch admit --json      # per_core, plus streak and hot_for_s when sampling
~/src/djbclark-ade/bin/load-watch status            # hot window, top consumers, cooldowns
~/src/djbclark-ade/bin/load-watch incidents -n 5    # recent incidents and whether each was acked
tail -n 5 ~/.local/state/load-watch/sample.log
tail -n 10 ~/.local/state/load-watch/guard.jsonl
```

Investigate (section 3) when any of these holds. Otherwise report the numbers in one line and stop.

1. The 1-minute load per core is above **1.5** (`admit` says `hot`; that is 12 on 8 cores, the same limit
   `bg` and `acp-dispatch` use) **and** the 5- or 15-minute average agrees. A 1-minute spike over a
   falling 15-minute average is agents starting up, not a problem: report it and move on.
2. `status` shows a hot streak (`hot for N/300 s`), or `sample.log` has a `sustained load` line from the
   last hour.
3. An incident has no `ack`, or `guard.jsonl` shows a trip or a `disabled` event from the last day.

## 3. Investigate

Verify against the processes themselves, not against memory or the brief's guess (standing order 4).

1. **Who uses the CPU:** `ps -axo pid,ppid,%cpu,state,command -r | head -20`. Map each heavy process to a
   session: `~/src/djbclark-ade/skills/session-finder/fleet.py list`, and `fleet.py show <id>`.
2. **Load without CPU:** processes in state `U` (stuck in disk or network wait, unkillable: the AFS case on
   2026-10-18), swap (`sysctl vm.swapusage`), and processes runnable at background priority (2026-10-18's
   load 110 was orphaned scans). `sample.log`'s `sustained load` line already counts all three.
3. **An agent's build or test:** it should have gone to CI. Read the incident brief
   (`~/.local/state/load-watch/briefs/<id>.md`). Make sure the blamed session got it (`relayed=True`);
   if not, relay it with `skills/session-finder/relay.py`, or `paseo send` for a Paseo agent. Check the
   repo's CI decision with `load-watch ci check <repo>`.
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

## What this is not

1. Not a scheduler. Never `/loop` or CronCreate a load check (`~/CLAUDE.md` item 13). The launchd job is
   the periodic part, and this session reacts to what it sends.
2. Not a licence to fix the load by stopping work. See section 3 item 5.
