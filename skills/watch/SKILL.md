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
   and left running (never archived, its id is recorded in `kept.json`), so it stays a tab. If `kept.json` cannot be read, `up` archives nothing and does not rename a `--force`-replaced holder, rather than guess.
   `up --probe` also sends the channel test line to live Paseo holders (costs each a turn).
   **A collected holder is a live holder** (2026-10-31): Paseo's idle-runtime collector (`Collected idle agent runtime` in
   `~/.paseo/daemon.log`) closes an idle agent's runtime after a while but keeps it listed, un-archived, with its persisted
   session, so `paseo agent ls -g --background` shows it as `closed` and the next message to it resumes the same conversation. `watch`
   treats `closed` as alive: no replacement, no new title number, no test line (so no model turn per tick), its record is kept,
   and the status line says `status closed: idle runtime collected`. Dead means `error`, archived (absent from `ls -g --background`,
   present in `ls -g -a`) or absent from both; those get a replacement as before. If `paseo agent ls` itself fails (daemon
   down or timing out), the holder is neither alive nor gone: `up` prints `not launching blind` and exits 1, `--force`
   and `--dry-run` included, so a transient failure never starts a duplicate. `--probe` on a collected holder wakes it
   (the test line resumes the session); if that test fails `up` exits 1 with `not starting a duplicate` and only
   `--force` replaces it. A retired `x …` agent that is `closed` is archived like an idle one (no turn in flight).
    Background workspace holders count as live too (2026-10-31): liveness and retirement sweeps use
    `ls -g --background`, which excludes archived agents; numbering uses `ls -g -a`, including both.
    A forced live holder keeps its tab and `kept.json` protection even when its old-only probe fails.
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
5. The launched agent is created through `bin/paseo-new-seat` (auto-accept on from the first tool call; a claude
   watcher starts in `bypassPermissions` unless `--mode ID` says otherwise, and `--no-auto-accept` or `--mode default|plan`
   gives one that prompts, labelled `perm=ask` so `bin/paseo-bypass-watch` leaves it alone; a codex watcher gets
   `--mode full-access`). A watcher reads public upstream replies, so a prompt injection there would run with the operator's
   permissions and no prompt: that exposure is accepted (operator, 2026-10-28, every agent runs yolo) and the briefs fence
   outside text as untrusted. `bin/watch` has no per-domain switch for a prompting watcher yet; `paseo-new-seat --mode default` by hand is the only way) in
   the one shared workspace `watch` (`[defaults] workspace`, found again on re-runs, created once under
   `workspace_cwd`; Paseo runs every agent in that cwd, so the prompt names the domain's own checkout from `cwd`), first prompt the domain's skill.
6. Title: `watch <domain> <n>`, `n` the next base-36 number (`0-9a-z`, so `…9`, `…a`, … `…z`, `…10`) per domain: one
   past every numbered title Paseo still lists (retired and archived included) and past `~/.local/state/watch/<domain>.seq`,
   so a number is never reused; an unnumbered `watch <domain>` counts as 0. The prompt tells the agent to register under
   that same name. After the new agent is registered and its channel test passes, every other live `watch <domain> <n>` and
   the holder it replaced gets `x ` put before its title (`x watch paseo 2`), via `paseo agent update --name`; a launch
   that does not register retires nothing. Each retired `x` agent that is idle is then archived, except a `--force`-replaced holder (the role,
   the Tier 1 chain log and the channel registration are already the new agent's); one with a turn in flight is
   left and archived by a later `watch up` once idle, so no work is thrown away (2026-10-28).

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
