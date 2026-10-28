---
name: watch
description: >-
  Bring up every watcher session: run `bin/watch` so each domain (CFEngine upstream PRs, Paseo contributions,
  machine load) has one live registered watcher agent, all in one shared `watch` Paseo workspace and titled `watch <domain> <n>`, starting only missing ones,
  with model, effort and context chosen from quota and recent event load. Idempotent. Use for /watch, "start
  the watchers", "bring up the watchers", "make sure the watchers are running". Not for becoming a watcher
  yourself.
---

# watch: make sure each watcher domain has a live watcher

`~/src/djbclark-ade/bin/watch` is the engine (no model; usage text and header are the reference);
`config/watch.toml` is the table, one row per domain. This skill is the operator pressing the button.

## Run

```sh
W=~/src/djbclark-ade/bin/watch
$W status                 # per domain: holder, reachable, and the plan `up` would launch; sends nothing
$W up --dry-run           # the same decisions `up` will make, no side effects
$W up                     # start what is missing; verify each registration
```

1. Run `status`, then `up --dry-run`, show the plan as a table (domain, holder, decision, provider / model /
   thinking / context, the reasons printed under it), then run `up`. The operator invoked this, so no extra
   confirmation. Report each domain's final line: `already watched`, `registered`, `claimed`,
   `not registered: <reason>`, or `not launched: <reason>`.
2. Exit 0 all good; 1 a launch did not register (the agent is left running: look at it, `paseo ls`);
   3 no eligible route (say why: the plan prints route_agent's reason).
3. A live holder is never replaced. `up --force DOMAIN` replaces one only when the operator says so; the replaced agent is renamed `x …`
   and left running (never archived), so it stays a tab.
   `up --probe` also sends the channel test line to live Paseo holders (costs each a turn).
4. `watch down DOMAIN` drops the role (`--relay-off <agent>` / `watcher clear <agent>`: clears only if that
   agent still holds it) and archives the agent `watch` started; an agent it did not start is never touched.
5. A domain with no row is added in `config/watch.toml`: skill, cwd, chain, `holder_cmd` (exit 1 = nobody),
   `test_cmd`, `off_cmd`, task kind, event signals. Nothing else changes.

## How a plan is chosen (printed with every decision)

1. Kind: `kind_idle` (cheapest, `bulk`) when the domain had no events in 14 days, else `kind` (`code`).
   Events: relayed events and touched threads (fleet-watch state), incidents (load-watch).
2. `route_agent.py plan --kinds K --json`: policy, `aiuse --available --json` headroom, the Claude-tight
   governor hold, `--exclude`. A route whose Paseo provider is not `available` or does not offer the model is
   skipped and the plan re-asked with that service excluded; no route left: the domain is not launched.
3. Effort: medium; high when anything is pending, more than 5 events, a brief over 20 KB, or `calibrate`
   shows the kind failing 25% or more of 3+ recent dispatches. Never above `route_agent`'s own effort, never
   above high, never Fable.
4. Context: standard; the `[1m]` variant only when chain log plus largest brief need over ~120k tokens.
5. The launched agent is created through `bin/paseo-new-seat` (auto-accept on from the first tool call) in
   the one shared workspace `watch` (`[defaults] workspace`, found again on re-runs, created once under
   `workspace_cwd`; Paseo runs every agent in that cwd, so the prompt names the domain's own checkout from `cwd`), first prompt the domain's skill.
6. Title: `watch <domain> <n>`, `n` the next base-36 number (`0-9a-z`, so `…9`, `…a`, … `…z`, `…10`) per domain: one
   past every numbered title Paseo still lists (retired and archived included) and past `~/.local/state/watch/<domain>.seq`,
   so a number is never reused; an unnumbered `watch <domain>` counts as 0. The prompt tells the agent to register under
   that same name. After the new agent is registered and its channel test passes, every other live `watch <domain> <n>` and
   the holder it replaced gets `x ` put before its title (`x watch paseo 2`), via `paseo agent update --name`; a launch
   that does not register retires nothing.

## Registration is verified

After the launch `up` polls the domain's own holder command until the NEW agent is the holder and the channel
test passes (300 s). Otherwise it prints `not registered: <reason>`, keeps the record `unregistered`, leaves
the agent running, exits 1, and the next `up` reports it as claimed instead of starting another. A record
whose agent no longer exists is dropped, never trusted. Concurrent runs: a per-domain `flock`; the loser
prints `claimed`. State: `~/.local/state/watch/` (`<domain>.json`, `watch.log`).

## launchd tick (installed 2026-10-25 on this Mac; item 13 allows a script, never a model loop)

`watch up` is cheap when everything is watched (one read per domain, no model, no message). A login plus
15-minute tick also restarts a watcher after a crash or a reboot. The job is installed from this
template as `~/Library/LaunchAgents/com.djbclark.watch.plist`; its first tick exited 0 and launched nothing:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.djbclark.watch</string>
  <key>ProgramArguments</key>
  <array><string>/Users/djbclark/src/djbclark-ade/bin/watch</string><string>up</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/Users/djbclark/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>/Users/djbclark/.local/state/watch/launchd.out</string>
  <key>StandardErrorPath</key><string>/Users/djbclark/.local/state/watch/launchd.err</string>
</dict>
</plist>
```

To reinstall elsewhere (after `mkdir -p ~/.local/state/watch`): `cp <that file> ~/Library/LaunchAgents/com.djbclark.watch.plist &&
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.djbclark.watch.plist`; remove with
`launchctl bootout gui/$(id -u)/com.djbclark.watch`. launchd never overlaps a `StartInterval` job, and the
per-domain lock covers a manual run racing a tick.

## What this is not

1. Not a watcher: it never registers itself and never calls `--relay-to`, `watcher set` or `--force`
   implicitly. A domain's own skill does the registering, in the agent `watch` starts.
2. Not a scheduler: no `/loop`, no CronCreate. Not a quota tool: the choice reads `route_agent.py`, it never
   re-implements it.
