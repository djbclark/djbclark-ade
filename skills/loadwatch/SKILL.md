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
   `paseo send` that fails naming DAEMON_UNREACHABLE, CONNECTION_LOST, NOT_READY or DAEMON_NOT_RUNNING twice, 5 s apart,
   inside 30 s, 2026-10-23; the relay channel and other failures get one attempt; Hermes still gets the
   ping), so after any restart you see, read `load-watch incidents -n 5` for what you missed. Never run
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

1. The 1-minute load per core is above **1.5** (`admit` says `hot`; that is 12 on 8 cores, the same limit
   `bg` and `acp-dispatch` use) **and** the 5- or 15-minute average agrees. A 1-minute spike over a
   falling 15-minute average is agents starting up, not a problem: report it and move on.
2. `status` shows a hot streak (`hot for N/300 s`), or `sample.log` has a `sustained load` line from the
   last hour.
3. An incident has no `ack`, or `guard.jsonl` shows a trip or a `disabled` event from the last day.
4. A `load-watch: compressor churn ~Nk pages/s for 3+ min (limit 60k); top: ...` line arrived (2026-10-23;
   `status` shows `compressor churn` and the `churn` / `churn-watcher` cooldowns). The sample step reads the
   `vm_stat` compressor delta each 20 s; it is sent when churn stays above the `admit` limit for 180 s
   (`LW_CHURN_SUSTAIN_S`), to you at most hourly and to Hermes every 6 h. `admit` already holds new
   `bg`/`acp-dispatch` work, so the churn is from running or bypass work: find the top memory users with
   `ps -axo pid,rss,command -m | head` (not only the CPU list in the line), then section 3 as usual. The
   alert opens no incident and kills nothing; the Standing exceptions below only change the advice (the line
   says so when Grok, Chrome or WindowServer is in its top 3), never whether you investigate.

## 3. Investigate

Verify against the processes themselves, not against memory or the brief's guess (standing order 4).

1. **Who uses the CPU:** `ps -axo pid,ppid,%cpu,state,command -r | ghead -20`. Map each heavy process to a
   session: `~/src/djbclark-ade/skills/session-finder/fleet.py list`, and `fleet.py show <id>`.
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

## What this is not

1. Not a scheduler. Never `/loop` or CronCreate a load check: it is a poll whose firings mostly find nothing
   (`~/CLAUDE.md` item 13). The launchd job is the periodic part, and this session reacts to what it sends. For
   the same reason there is no heartbeat to wake you after a Paseo restart (item 13's "recurring wake nothing
   else can do" does not apply: the next incident's `paseo send` already resumes you).
2. Not a licence to fix the load by stopping work. See section 3 item 5.
