---
name: watch
description: >-
  Inspect machine load, memory churn, and active incidents from your terminal with minimal token use, or manage
  system watchers. Use for `/watch paseo`, `/watch load`, `/watch`, `/loadwatch`, "watch load", "check load", "triage load spikes",
  or when investigating machine slowness, compressor churn, and load-watch alerts.
---

# watch: low-token terminal load inspection and watcher triage

Use this skill when invoked with `/watch load` (or `/watch`, `/loadwatch`) to inspect machine load, memory churn,
and active incidents with minimal token consumption, or to run on-demand triage.

---

## 1. Zero-Token Terminal Commands (Run directly in any shell pane)

For direct observation in a terminal window without spending any LLM tokens:

```sh
# Core load, hot duration, sample count (instant, 0 tokens):
~/src/djbclark-ade/bin/load-watch status

# Memory gate, compressor churn, per-core load, headroom (instant, 0 tokens):
~/src/djbclark-ade/bin/load-watch admit --json

# Open unacknowledged incidents (instant, 0 tokens):
~/src/djbclark-ade/bin/load-watch incidents -n 5

# Check if a standing watcher is registered:
~/src/djbclark-ade/bin/load-watch watcher show

# Acknowledge an incident after inspection:
~/src/djbclark-ade/bin/load-watch ack <INCIDENT_ID> "explanation of cause and resolution"
```

---

## 2. On-Demand Triage (`/watch load` in an Agent Session)

When the operator types `/watch load` in an agent session, follow this step-by-step protocol.
**Goal:** Be concise. If the machine is calm, answer in 1–2 lines and stop to avoid wasting tokens.

### Step 1: Run fast diagnostics

Execute the three read-only probes:

```sh
~/src/djbclark-ade/bin/load-watch admit --json
~/src/djbclark-ade/bin/load-watch status
~/src/djbclark-ade/bin/load-watch incidents -n 3
```

### Step 2: Evaluate whether load, memory, or churn is abnormal

Investigate further (Step 3) **only** if one of these is true:
1. `admit --json` reports `"status": "hot"` or lists any `refused` gates (e.g. `load`, `compressor`, `free_mem`, `swapins`, `pageins`, or `memory_unreadable`).
2. The 1-minute load per core is $> 2.5$ **and** the 5- or 15-minute average agrees.
3. `status` reports a sustained hot streak (`hot for N/300 s`).
4. Compressor churn is sustained above the alert line ($50\text{k}$ pages/s, from `admit --json`).
5. An incident is listed in `incidents -n 3` without an `ack`.

**If none of the above are true:**
Report a concise 1-line status summary and stop immediately:
> "System is calm: admission gate passed, load is normal (<per-core> per core), compressor churn is <churn> pages/s, and no unacknowledged incidents are open."

### Step 3: Deep inspection (only if abnormal)

If load, memory, or churn is genuinely abnormal:
1. Inspect top CPU consumers:
   - On macOS:
     ```sh
     /bin/ps -axo pid,ppid,%cpu,state,etime,command -r | head -15
     ```
   - On Linux:
     ```sh
     ps -eo pid,ppid,%cpu,stat,etime,args --sort=-%cpu | head -15
     ```
2. Inspect top memory consumers:
   - On macOS:
     ```sh
     /bin/ps -axo pid,rss,command -m | head -10
     ```
   - On Linux:
     ```sh
     ps -eo pid,rss,args --sort=-rss | head -10
     ```
3. Map heavy processes to their Paseo agents or background jobs by working directory:
   ```sh
   paseo ls -g --background --json
   ```
4. If an incident has a brief, read its top lines:
   ```sh
   cat ~/.local/state/load-watch/briefs/<INCIDENT_ID>.md
   ```
5. Report findings in a short, structured summary:
   - What processes or agents are driving the load.
   - Whether it is expected build/test activity or a runaway process.
   - Ask the operator before killing, stopping, or throttling any work.
   - Offer to acknowledge the incident with `load-watch ack <ID> "..."`.

---

## 3. Standing Watcher Mode (Optional)

If the operator explicitly asks this session to become the standing watcher:
```sh
# Register this session (Paseo agent):
~/src/djbclark-ade/bin/load-watch watcher set --name "<session name>"

# Verify the channel:
~/src/djbclark-ade/bin/load-watch watcher test
```

To release the role when done:
```sh
~/src/djbclark-ade/bin/load-watch watcher clear
```

## 4. GUI-hog Freeze: never run it yourself

`bin/gui-hog freeze` SIGSTOPs a GUI app's whole process tree and is an **operator click** (docs/gui-hog-dialog.md B6, F8-16): an agent never runs `gui-hog freeze`, never
freezes or quits an app on its own judgment, and does not call `gui_hog_freeze.freeze`. Resuming is always allowed: `bin/gui-hog frozen` lists what is stopped, `bin/gui-hog thaw --all`
resumes it, and `bin/gui-hog thaw --all --stopped-apps` is the last resort for a lost state file. Every freeze and thaw is logged with `by` in `~/.local/state/load-watch/gui-hog/events.jsonl`.

## 5. `/watch stuck` — Pi agents out of tokens

`/watch stuck` runs `bin/ade-pi-stuck` (read-only): it lists the Pi agents Paseo
reports (closed ones carry their status; Paseo does not list archived ones at all), maps
each to its billing account (from the `pi/<account>/<model>` provider), and flags the
live ones — not closed, archived or in `error` — whose account is quota-exhausted. For each stuck
agent it prints a comparable healthy alternative model under a different, not-exhausted
account (or `no healthy alternative found`) — never the account that just ran dry.
`aiuse` exits 3 when every pool is unusable and still prints its JSON, so that read is
accepted: a failed quota read keeps the known-empty accounts stuck instead of clearing them.

```sh
~/src/djbclark-ade/bin/ade-pi-stuck          # human table
~/src/djbclark-ade/bin/ade-pi-stuck --json    # machine-readable
```

The re-handoff itself (archive the exhausted agent, relaunch the same task on the
healthy alternative, and tell the new agent to continue) is a separate gated
action — the supervisor agent owns it, not `ade-pi-stuck` (read-only).

The periodic `bin/ade-supervisor-scan` (every 300 s) also logs a dry-run re-handoff plan to
`~/.local/state/djbclark-ade/supervisor/supervisor.log`: one `re-handoff plan (dry-run) {...}` line, only when the plan
changes. `ADE_SUPERVISOR_REHANDOFF` picks the mode: unset or `dry-run` (default) moves nothing; `live` is recognized but
refused today (`bin/ade-supervisor-rehandoff` is a stub: it moves nothing and exits 1, and the log says
`re-handoff executor failed`), so a scan never relaunches an agent on its own. See docs/scheduling.md.

## 6. Paseo fork releases (`/watch paseo`)

Zero-token terminal status (no model, app launch or daemon restart):

```sh
~/ops/site-public-djbclark/bin/fleet-watch upstream-release --status
```

Prints the Paseo registry row's newest upstream tag, fork base tag from
`git -C ~/src/paseo-beta2-local-wt describe --tags --abbrev=0 --match 'v*'`,
installed app version from `plutil` and whether it matches the base, the last
watcher run, and the count and titles of open Paseo alert issues. It reads
`gh issue list --repo djbclark/upstream-releases --label radar --state open --json number,title,url`
(with a 1000-issue limit); it prints titles only, never issue bodies.
A missing registry fails visibly; generate the fork inventory first.

The zero-model watcher opens an alert for each new upstream tag, including betas.
Grok Bot Radar reads open alerts. Closing an alert issue is djbclark's act,
never the watcher's or Radar's. In an agent session, run the status command,
report the result briefly and stop.
