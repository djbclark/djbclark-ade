---
schema_version: 1
handoff_id: 93fa
parent_handoff_ids: []
lineage: none
chain: [load-spike-monitor-t]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 9a64617e8a5d5c64453f996b6072cd02c874c859
created_at: 2026-10-24T10:57:00-04:00
writer: claude-code
---
# Handoff — load watcher, memory gate, App Tamer A/B

## The Goal
This Paseo agent (96a17744, workspace `loadwatch-p`, wks_d7ef123a8fdc01c5) is the registered load watcher
(`/loadwatch`): investigate load incidents and notices, `ack` incidents, ping Hermes, keep the Tier 1 log of chain
`load-spike-monitor-t` current. Beyond that, this session built the memory-churn gate and ran the relay/Hermes and
App Tamer work below.

## Where We Are
Done and pushed (djbclark-ade): memory gate in `load-watch admit` (limit 60000 pages/s, `--max-mem-churn`), churn
alert in `load-watch sample` (180 s sustained), loadwatch skill updates (auto Tier 1, Grok Bot/Chrome standing
exception), `bin/app-tamer-ab` (+ fix cbd94b2). site-djbclark: `bin/bg` also asks `admit` (f370ad7, 98e47f7, c82d47b).
relay.py `hermes` route: built by agent 24f5b849 (workspace `paseo-workspace-navigation-plugins-pw`,
wks_5363dce7237adb53), tested on the real Telegram topic inbox-ops (hermes:16790ed2), fleet.py fix 4572876; Hermes
installed `peer-relay` itself (symlink in ~/.hermes/skills); Hermes -> peer direction verified. The coordinator
(6ebd939d, workspace `djbclark-ade-rework-p`, wks_f70e3a0b7088d428) folded my follow-ups (naming rule, session-finder
lookup, push-on-completion, load planning) into docs/queue.md (434254f, b876dc5) and added dispatch-footer rule 16
(tests/builds only via bg, one pytest at a time; b86e0d8).

Load incidents handled today, all without killing anything: 2026-10-23 evening Basic Memory restart re-sync
(djbclark: deliberate bulk task, ignore; see memory `project_basic_memory_bulk_task_2026-10-23`); coordinator's
adversary round 62 (parallel pytest, told it, rule 16 followed); 2026-10-24 ~10:14 AM an omp session (herdr pane
w2N:pW, "BREW: Unpin ops software") building `lamda==10.9` from source (load 97), relayed a note.

App Tamer experiment (djbclark's question: does it cost more than it saves?). Currently running:
phase `with-trimmed-day` since 2026-10-24T14:44:01Z (10:44 AM EDT), App Tamer pid 66037 on the TRIMMED list (38
entries: 18 Apple daemons removed; backup of the original: `~/.local/state/load-watch/app-tamer-ab/AppTamer.plist.before-2026-10-23`).
Sampler: `bin/app-tamer-ab run` pid 16679 (one row every 60 s) into `~/.local/state/load-watch/app-tamer-ab/samples.csv`.
First read (6 h window, after the sampler fix): without n=247 load/core 1.03 p90 1.74; with-trimmed-day n=103
load/core 1.30 p90 2.06; App Tamer's own cost ~0.03 cores. Not conclusive: different stretches of the day.

## What We Tried
1. `bin/app-tamer-ab` first version dropped admit's JSON when admit exited 75 (hot), so every hot sample was recorded
   blank (182 of 1125 rows at the time). Fixed in cbd94b2; the earlier `with-trimmed` (1 h) and early `without` rows
   are biased toward calm periods: treat as provisional.
2. Relay to a Hermes session from this session failed once with "not sent: that is this session": the nested relay
   sees this session as the caller. Artifact of testing from here, not a real-use bug.
3. The omp pane id `w2N:tV` is the tab; the pane is `w2N:pW` (found with `session-find.py BREW unpin`).
4. First `with-full` phase (original 56-entry list, 14:38Z) lasted 6 minutes; djbclark then agreed trimmed is the
   better thing to run for the day. Leave `with-full` out of comparisons.

## Key Decisions
1. Churn limit stays 60000 (recomputed on 482 samples: calm p99 55k, load 8-16 p90 57k, p99 73k; 70000 would pass a
   third of load-16-25 moments). Recalibrate only after a few calm days of samples.
2. Run the day on the trimmed list: it is the config that would be kept (our guard covers the Apple daemons).
   Rejected: original list (answers a question nobody will act on; throttling mds/cloudd may itself cause load).
3. Basic Memory CPU: ignore unless still happening on the morning of 2026-10-24 (it was calm at 10:14 AM today).
4. Never kill/throttle other sessions' work; ask via relay.py instead. Never a recurring model prompt.

## Evidence & Data
Churn data: `~/.local/state/bigteam/loadgate-followup-2026-10-23/churn.csv` (10 s, 360 rows) and the app-tamer-ab CSV.
Hermes real-topic test evidence: `~/.local/state/bigteam/relay-hermes-route/real/`. Memory notes added:
`reference_paseo_agent_to_workspace_lookup`, `project_basic_memory_bulk_task_2026-10-23`.

## Operator Feedback
Name workspaces by human name AND id; warn about Grok Bot/Chrome only if abnormal or slow; push-on-completion
instead of polling; tier logs may be updated freely; use /session-finder to find owners.

## Where We're Going
1. THE NEXT ACTION: when djbclark says the half/whole day is done (or a load spike gives a data point), run
   `~/src/djbclark-ade/bin/app-tamer-ab summary 24` and report `with-trimmed-day` against `without` to djbclark
   (load/core mean and p90, swap, churn, App Tamer cores). Then ask whether to keep trimmed, restore the original
   list, or remove App Tamer.
2. Answer load-watch notices as they arrive (investigate per skill; `load-watch ack` any incident; Hermes is pinged
   by the job). Basic Memory is back to normal; a future notice naming it needs a real look.
3. Open on others: coordinator reply on push-on-completion scoping; the omp BREW session building from source (let
   it finish; if load stays > 30 for long, look again); optional churn limit recalibration later.
4. Not mine: untracked `.agents/skills/fastino-glide/` in djbclark-ade.

## Detached jobs
Job records still open for this session (all finished, reports already read; nothing to re-arm):
`~/.local/state/bigteam/loadgate-followup-2026-10-23/jobs/{bgtest,churn,design}.json`. The App Tamer sampler (pid
16679) is a nohup process, not a job record; it may die with a machine restart: restart with
`nohup ~/src/djbclark-ade/bin/app-tamer-ab run > ~/.local/state/load-watch/app-tamer-ab/run.log 2>&1 &`.

## Quick Start
```
~/src/djbclark-ade/bin/load-watch watcher show     # this agent should be the watcher
~/src/djbclark-ade/bin/load-watch status
~/src/djbclark-ade/bin/app-tamer-ab summary 24
cat ~/.local/state/load-watch/app-tamer-ab/phases.log
```
