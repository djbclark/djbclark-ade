---
name: watch
description: >-
  Inspect machine load, memory churn, and active incidents from your terminal with minimal token use, or manage
  system watchers. Use for `/watch load`, `/watch`, `/loadwatch`, "watch load", "check load", "triage load spikes",
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

### Step 2: Evaluate whether load or churn is abnormal

Investigate further (Step 3) **only** if one of these is true:
1. The 1-minute load per core is $> 2.5$ (`admit` reports `hot`) **and** the 5- or 15-minute average agrees.
2. `status` reports a sustained hot streak (`hot for N/300 s`).
3. Compressor churn is sustained above the alert line ($50\text{k}$ pages/s, from `admit --json`).
4. An incident is listed in `incidents -n 3` without an `ack`.

**If none of the above are true:**
Report a concise 1-line status summary and stop immediately:
> "System is calm: load is normal (<per-core> per core), compressor churn is <churn> pages/s, and no unacknowledged incidents are open."

### Step 3: Deep inspection (only if abnormal)

If load or churn is genuinely abnormal:
1. Inspect top CPU consumers:
   ```sh
   /bin/ps -axo pid,ppid,%cpu,state,etime,command -r | head -15
   ```
2. Inspect top memory consumers:
   ```sh
   /bin/ps -axo pid,rss,command -m | head -10
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
