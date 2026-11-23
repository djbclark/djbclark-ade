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

### Step 4: Automatic Load-Reduction Actions (Standing Operator Grant)

Operator ruling, 2026-11-21 (load watcher, ref 56dc3fc1): `/watch load` may coordinate archiving unneeded agents to reduce load. This step narrows that grant to what is safe. `~/CLAUDE.md` item 9 and `skills/tidy/SKILL.md` are unchanged for every other agent, and Step 3.5 ("ask the operator before killing, stopping, or throttling") still holds for everything except the archive coordination in item 3.

**One trigger, here and in the watcher's `WATCHER_HOWTO`:** `load-watch admit --json` refuses on a memory reason (`free_mem`, `swapins` or `compressor`). A calm machine, or CPU load without memory pressure, never starts item 3, however many agents are resident.

**Send rules (items 1 and 3; no exception):** send only from a Paseo session, that is `$PASEO_AGENT_ID` is set, because a sourceless `paseo send` defaults to interrupt (`skills/tidy` D, `bin/ade-tidy`, `docs/threat-model.md` 4): a local session outside Paseo running `/watch load` lists the agents and leads for djbclark and sends nothing. A sourced session is necessary, not sufficient: any send to a running agent can still replace its turn (Paseo's steer falls back to interrupt when the provider cannot steer, for example an ACP provider, or Claude while compacting), and every sourced agent-message clears pending permissions. So send only to an idle agent with no card: a fresh `paseo agent inspect ID --json` must read `Status == "idle"`, `Archived: false` and `PendingPermissions == []` right before the send; otherwise list the agent for djbclark and retry at the next incident. Use exactly `paseo send --no-wait --json ID "..."`, never a `--behavior` flag. A send is not delivery (AGENTS.md order 10): read `.status`, `queued` is not delivered.

1. **Steer future heavy runs to CI or `bgrun`**: message the blamed Paseo agent (send rules above) to route future builds/tests to CI (`load-watch ci decide`) or through `~/ops/site-private-djbclark/bin/bgrun`, only when a fresh `paseo agent inspect ID --json` reads `Status == "idle"`, `Archived: false` and `PendingPermissions == []` (the same gate as item 3). A blamed agent that is running is not messaged: list it for djbclark and retry at the next incident (load-watch itself messages a blamed agent only on a CPU-attributed load incident, and that send can queue or fail, so a running agent may or may not have been told; either way it is not this step's to interrupt). Never ask it to stop its current step. Ask djbclark before creating a CI copy of a repo.
2. **Guard a misbehaving launchd job**: register it with `load-watch guard add`.
3. **Coordinate archiving unneeded Paseo agents.** Closed agents hold little RAM, so this targets live idle provider processes only. `paseo ls -g --json` and `paseo agent inspect ID --json` carry no role or label, so read the label from the agent's state record, as `bin/ade-tidy` does: `labels["ade.lead"]` in `${PASEO_HOME:-~/.paseo}/agents/*/ID.json` (the live workers of one lead: `paseo ls -g --label ade.lead=L --json`). Read `Archived`, `Status` and `PendingPermissions` from `paseo agent inspect ID --json`.
   - **The watcher never runs `paseo agent archive` itself for load reduction.** The two direct archive paths are: (a) `~/src/djbclark-ade/bin/ade-tidy prune` (observe first; `--apply` only from the watcher's own top-level session, never from a sub-agent), which archives only idle, finished Baton `[Handoff writer]` helpers under its own checks (`--min-idle`, exclude file) and stops orphan provider processes of already-archived agents (its own `--max-kills` cap and `--orphan-grace`, matching its 30-minute launchd job); and (b) fulfilling explicit self-initiated archive requests submitted through `bin/ade-request-archive` (Section 3a below; operator directive 2026-11-23). Read the observe-only plan first.
   - **No `ade.lead` label** (every top-level LEAD, every operator-started agent, anything else, and any agent whose state record you cannot read): list it for djbclark in one line; never archive it and never message it about archiving. `closed` alone proves nothing finished: Paseo marks every agent interrupted by a daemon restart or a provider crash `closed` (the `D#u` rule of `skills/tidy`), so such an agent is only listed.
   - **Has `ade.lead=<L>` (a worker)**: the owning lead decides, never the watcher. Resolve `<L>` to its current holder with `effective_lead` of `bin/ade_lead_succession.py` (`python3 -I -c 'import sys; sys.path.insert(0, "/Users/djbclark/src/djbclark-ade/bin"); import ade_lead_succession as s; print(s.effective_lead(sys.argv[1]))' L`, or the lead's latest takeover message). **No current holder** (tell djbclark in one line, send nothing, archive nothing): the call raises (`SuccessionError`, a cyclic ledger), or the returned id is not found, or `paseo agent inspect CURRENT --json` reads `Archived: true` (an id with no handoff record comes back unchanged, so this check is the one that matters). Otherwise re-read `paseo agent inspect CURRENT --json` right before the send: it must read `Status == "idle"`, `Archived: false` and `PendingPermissions == []`, and the lead must not be waiting on a question card (`paseo permit ls`). A lead that is not idle (running, or in error) is listed for djbclark and retried at the next incident, never sent to; never message an agent waiting on a card or an archived one (a send un-archives it). Then send that lead one message (send rules above) naming its idle workers (closed ones hold little RAM and are not named) and the memory reading, asking it to archive those `bin/ade-tidy` G proves finished and reported (report ends `DONE`, `.done` acked, no card pending) and keep the rest, ending `Please reply: ack <watcher id>`.
   - **Rate limit:** at most one such message per lead per hour, and none while an earlier one is unacked and under 6 hours old. The record is `${LW_STATE_DIR:-~/.local/state/load-watch}/archive-asks.jsonl`: read it before each send, and after each send append one JSON line `{"lead": CURRENT, "ts": <epoch seconds>, "status": <.status>}`; a later incident inside the hour lists the lead for djbclark instead. The read-then-append is not locked, so two watcher sessions could both pass the check: only one session at a time sends these messages (the standing watcher when one runs; any other `/watch load` session lists the lead for djbclark and sends nothing). No ack after 6 hours: tell djbclark in one line.
   - **"Finished and reported" is the owning lead's call**, on ade-tidy G's evidence. An agent whose report was never read is paid work and is never a target.
   - **Hard boundaries**: never archive a `running` agent, a LEAD, an agent with a pending permission or question, or one interrupted by a restart; never kill, SIGSTOP or throttle active work without djbclark's yes (`ade-tidy prune`'s capped stop of archived agents' orphans is not active work); when in doubt, do not archive: ask the owning lead or djbclark.

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

### 3a. Fulfilling explicit `ade-request-archive` requests (operator directive, 2026-11-23)

When a finishing session has no live owning lead (for example a top-level lead finishing via `/loose`), `bin/ade-request-archive` records a pending request under `~/.local/state/djbclark-ade/archive-requests/<id>.json` and messages the standing watch lead (`docs/self-session.md` section G). Handle inbound `ade-request-archive` requests by running:

```sh
~/src/djbclark-ade/bin/ade-request-archive sweep          # observe first
~/src/djbclark-ade/bin/ade-request-archive sweep --apply  # archive idle/closed requesters without --force
```

(Pass `--all` with `sweep` only when the standing watch lead also needs to sweep pending requests whose original target lead is no longer handling them.) If fulfilling one manually instead of via `sweep --apply`, verify exact ID presence in `paseo ls -g --json` (guards against `getpaseo/paseo#9668`), confirm `paseo agent inspect <id> --json` reads `Status` in (`idle`, `closed`), `Archived: false`, and `PendingPermissions == []`, run `paseo agent archive <id>` without `--force`, verify `Archived: true` readback, and mark the request fulfilled.

**Explicit scope boundary:** this exception to "never runs `paseo agent archive` itself" applies **only** to agents that explicitly requested their own archive via `bin/ade-request-archive`. Unsolicited load-reduction archiving under Step 4 still never runs `paseo agent archive` directly.

## 4. GUI-hog Freeze: never run it yourself

`bin/gui-hog freeze` SIGSTOPs a GUI app's whole process tree and is an **operator click** (docs/gui-hog-dialog.md B6, F8-16): an agent never runs `gui-hog freeze`, never
freezes or quits an app on its own judgment, and does not call `gui_hog_freeze.freeze`. Resuming is always allowed: `bin/gui-hog frozen` lists what is stopped, `bin/gui-hog thaw --all`
resumes it, and `bin/gui-hog thaw --all --stopped-apps` is the last resort for a lost state file. Every freeze and thaw is logged with `by` in `~/.local/state/load-watch/gui-hog/events.jsonl`.

## 5. `/watch stuck` — Pi agents out of tokens, and agents in `error`

`/watch stuck` runs `bin/ade-pi-stuck` (read-only): it lists the Pi agents Paseo
reports (closed ones carry their status; Paseo does not list archived ones at all), maps
each to its billing account (from the `pi/<account>/<model>` provider), and flags the
live ones — not closed or archived — whose account is quota-exhausted. For each stuck
Pi agent it prints a comparable healthy alternative model under a different, not-exhausted
account (or `no healthy alternative found`) — never the account that just ran dry.
An agent in `error` is flagged too, **on every provider** (Pi, Codex, Claude, …) and for any
agent, not just leads: `paseo ls --json` carries no role, so the script cannot tell a lead from a
worker, and an errored worker is as dead (the notice goes to the lead, who decides). A Pi agent in
`error` (queue item 82: a 402 on `xai-oauth`) keeps its Pi alternative. **A Codex or Claude agent in
`error` gets no alternative** (`family` names its provider, `alternative` is null): the Pi candidates are
DeepSeek models on other vendors' accounts, so offering one would hand a frontier agent's task and context
to a weaker model and another vendor. Restart it or re-hand it within its own provider family.
`aiuse` exits 3 when every pool is unusable and still prints its JSON, so that read is
accepted: a failed quota read keeps the known-empty accounts stuck instead of clearing them.

```sh
~/src/djbclark-ade/bin/ade-pi-stuck          # human table
~/src/djbclark-ade/bin/ade-pi-stuck --json    # machine-readable
```

The re-handoff itself (archive the exhausted agent, relaunch the same task on the
healthy alternative, and tell the new agent to continue) is a separate gated
action — the supervisor agent owns it, not `ade-pi-stuck` (read-only), and only for an entry whose
`family` is `pi`.

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
