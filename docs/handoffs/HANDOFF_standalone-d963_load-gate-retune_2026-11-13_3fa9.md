---
schema_version: 1
handoff_id: 3fa9
parent_handoff_ids: []
lineage: none
chain: [standalone-d963]
repo: djbclark-ade
workspace: wks_9061125847f43414
branch: master
head_sha: 8c2cbbf3ac17d81391d9bd8e969dc168d03cbaaf
created_at: 2026-11-13T14:10:00-05:00
writer: claude-code
---
# Handoff — load-gate retune and GUI-hog dialog (build queued), Tart/Orchard/container cleanup done

## The Goal

djbclark's 2026-11-13 requests, in order: (1) `/watch load` triage; (2) research and suggest more reasonable `load-watch`
admission-gate numbers for the new Mac (MacBook Pro M1 Pro, 10 cores = 8P+2E, 32 GB RAM, ~1 TB SSD), to maximise work per
unit time without diminishing returns and without builds holding off forever; plus a dialog when non-build GUI apps hog
the machine (header: load triplet and 5-minute average as `btm-mt` does; GUI apps with CPU/load/RAM numbers; per-row Quit and
Force Quit; bottom row Wait (default no-op), Ignore, Quit All, in the style of `sudo-ask`); also whether GUI apps can be
safely stopped or hibernated; (3) keep Tart VMs and Apple containers from running constantly, after polling all live agents.

## Where We Are

Done and verified:
- `/watch load` triage (admit refused only on `pageins`; machine not thrashing).
- Research, measurements and a proposal (numbers below and in memory
  `project_load_gate_retune_proposal_2026-11-13.md`). **Nothing is implemented; no repo was edited.**
- Operator rulings on the dialog and the build (below).
- Polled all 22 live agents: 19 answered, none depends on Tart/Orchard/containers except agent `18463dd` (Orchard owner) and the
  CFEngine Linux gate (Apple containers on demand).
- `container system stop` run (rc 0, no container was running). Tart: 0 VMs running (agent `18463dd` deleted the two GHA VMs
  in its Orchard restart; `ubuntu-22.04`/`ubuntu-24.04` clones and OCI images are stopped). Orchard controller+worker
  (`com.djbclark.orchard-dev`, ~70 MB, `127.0.0.1:6120` only) left up on purpose (operator's choice).

Not done: the 3-PR build (queued), the load-watcher registration check (below), 3 handoff-writer acks.

Git state: `~/src/djbclark-ade` shared checkout on `master`, head `8c2cbbf3` (origin/master at handoff time), dirty entries are not
this session's (` M skills/graft/SKILL.md`, untracked `.adal/`, `.agents/skills/fastino-glide/`, `.gemini/`, `.kiro/`, `.windsurf/`).
This handoff is committed on branch `handoff-d963` in `~/src/djbclark-ade-handoff-d963-wt` (no PR, `master` is PR-only).
Files changed this session: this document; memory `project_load_gate_retune_proposal_2026-11-13.md`,
`project_tart_orchard_container_state_2026-11-13.md` and two `MEMORY.md` index lines. No repo source file changed.
Tests run: none (nothing implemented). Blockers / BLOCKED reports: none; no dispatched slices.
Operator-side open: nothing waits on djbclark except the questions in Where We're Going items 1 (`bg` base) and 3 (watcher).

## What We Tried

- First web searches via `firecrawl_search` returned mostly irrelevant results (company sites, Wikipedia); the useful sources were
  [Mole on memory pressure](https://mole.fit/blog/mac-memory-pressure-explained), an [HN throttling thread](https://news.ycombinator.com/item?id=33405359)
  and [Frost](https://github.com/Yessi-cmd/Frost). `yanxiangrong/app-pauser` returned 404. Search gave no numeric thresholds
  ("no universal numeric thresholds"), so the numbers are calibrated from this Mac's own samples.
- Hooks rejected two commands (bare `sed`; `cmd | tail` followed by `$?`): use `gsed`, and write output to a file with `echo "rc=$?"`.
- I miscounted agents twice (said 18, were 22; said 16 answered/4 waiting, were 17/5) and gave `launchctl bootout gui/501/...` from a
  peer's chat message: the job lives in **`gui/502`** (this user's uid is 502). All corrected in chat and memory.
- Unverified from memory, treat as assumed: `Virtualization.framework` can save a VM's RAM (macOS 14+); Chrome Memory Saver
  discards tabs; E-core worth ~0.4 P-core; App Tamer itself uses SIGSTOP (only Frost documents it).

## Key Decisions

Gate numbers were chosen from measurement, not from web thresholds. Page-ins is a poor thrash signal here (it counts file reads and
1000 pages x 16 KB = 16 MB/s), swap-ins is the real one. The load limits stay mostly as they are because the 30% idle CPU at load ~10
shows load reflects memory and kernel time on this machine, and the runaway events (load 222-411) need the 4.0/core backstop.
Rejected: automatic SIGSTOP freezing (the 2026-10-24 App Tamer A/B made this Mac worse: load/core 1.09 vs 0.73, swap 9.4 vs 4.8 GB,
churn 26k vs 6.8k pages/s, see memory `project_siriinferenced_disabled_apptamer_quit.md`) in favour of explicit, user-clicked Freeze.
The dialog must be a native Swift window: AppleScript `display dialog` has at most 3 buttons and no per-row buttons (`swiftc`
exists, PyObjC does not). Orchard left up for `orchard ssh` (agent `18463dd` said the operator's own requirement was Orchard available).

## Decisions

- [decision] Retune page-ins limit 1000 -> 4000/s, old limit only when corroborated by swap-ins or low free memory; rejected: keep 1000; because the live median is 689/s with zero swap-outs and 1000 pages/s is 16 MB/s
- [decision] Add a swap-ins gate at about 300/s; rejected: rely on page-ins and churn alone; because swap-ins are the real thrash signal and live sit near 0 (max 226)
- [decision] Raise the compressor churn admit limit 20000 -> 30000 and keep the 60000 hard limit; rejected: raise the hard limit; because live p90 is 13k and the 2026-11-01 starvation needs the hard stop
- [decision] Free-memory floor 300 -> 1000 MB (`LW_MIN_FREE_MB`); rejected: leave 300; because one rustc or Gradle job takes 1-3 GB
- [decision] `bg` base 2.5 -> 3.0 per core, `admit` default 1.5 -> 2.0, boost 4.0 kept, agent cap 14 -> 20; rejected: higher per-core limits; because CPU is ~30% idle at load ~10 so load is not the binding resource
- [decision] Add a starvation valve: soft gates yield after 5 min of refusal, hard gates never, at most one forced admit per 2 min machine-wide; rejected: yield all gates; because the 2026-11-01 oscillation came from every dip admitting a job
- [decision] Dialog trigger: a build waited 3 min and non-build GUI apps use at least 0.75 core (5-min average) or 2 GB; at most once per 30 min; Ignore snoozes 60 min
- [ruling] "Yes, that reading" for header = 1/5/15 triplet + 5-minute sliding average, per-app unnormalized cores (djbclark, 2026-11-13)
- [ruling] "Go ahead, in that order": PR 1 env-var retune + stale-comment fix, PR 2 swap-ins gate + starvation valve + tuning log, PR 3 native Swift dialog (djbclark, 2026-11-13)
- [ruling] "2 plus also have indefinite freeze and resume buttons": per-row Quit, Force Quit, timed Freeze, indefinite Freeze, Resume (djbclark, 2026-11-13)
- [ruling] "We don't want that up constantly. Ditto with apple containers." (djbclark, 2026-11-13)
- [ruling] "1. Stop container system only (Recommended)": container system stopped, Orchard left up (djbclark, 2026-11-13)
- [ruling] "2. It is genuine — find out where it came from": the "Herald summary" message `d173c384` is a real, closed Haiku Paseo agent in `~/src/djbclark-ade` (one of many "Herald summary" helpers); nothing to act on (djbclark, 2026-11-13)

## Relations

- continues [[HANDOFF_standalone-d963_load-gate-retune_2026-11-13_3fa9]]
- decided_in [[HANDOFF_standalone-d963_load-gate-retune_2026-11-13_3fa9]]

## Evidence & Data

Live 60 s sample (24 x 2.5 s, 2026-11-13, min/p50/p90/max): load 8/10/12/13; churn 542/7337/13288/25076 pages/s; page-ins
272/689/1280/1916 /s; swap-ins 0/1/8/226 /s; swap-outs 0; page-outs 0; CPU 41% user, 26-31% sys, 27-33% idle. Swap 11.7 of 13.3 GB used
(cold pages); 12 GB in the compressor; ~104 MB unused, 4.3 GB "available". 48 historical `admit` snapshots
(`~/.local/state/load-watch/admit-*.json`, 2026-11-07..10, 10 cores): load p50 22, p90 62, max 411; page-ins p50 419, p90 3219, max 4187;
refusals: load alone 19, page-ins alone 6, load+page-ins 8, load+compressor+page-ins 2, none 11. Thin data: tune from a log.
Gate code: `bin/load-watch` (defaults near lines 1805-1860; docstring ~30-150), tests `tests/test_load_watch_admit.py`
(asserts limits, e.g. `test_pageins_limit_is_1000_per_second` ~line 291). Stale comments saying "16 GB, 8-core" at about lines
31, 133, 1828, 1849. `bg` (base 2.5/core) lives in `~/ops/site-private-djbclark/bin/bg`, NOT in this repo.
`sudo-ask` dialog pattern: `~/ops/site-private-djbclark/bin/sudo-ask` (default "Wait" no-op, leftmost, Enter/Esc never decide).
`btm-mt` is `~/.local/bin/btm-mt`, a patched `bottom` (F8 sliding window 5s/5m/34h, unnormalized CPU).

## Operator Feedback

Wants more work per unit time on the bigger machine, no build starvation, and non-build GUI hogs surfaced with a decision dialog
instead of silent waiting. Wants Tart VMs and Apple containers not left running. Chose to keep Orchard up. Wants freeze/resume
available, including indefinite.

## Where We're Going

1. **THE next action:** dispatch PR 1 through `fan-out` (`skills/fan-out`, `route_agent.py plan --kinds KIND`) in a claimed
   djbclark-ade worktree: change the defaults in `bin/load-watch` (not only env vars) to the Decisions above, update
   `tests/test_load_watch_admit.py` and the docstring, and fix the "16 GB, 8-core" comments to "32 GB, 10-core (8P+2E)". Tests via
   `~/ops/site-private-djbclark/bin/bg`, CI first; add a CHANGELOG fragment and run `changelog-fold --check`; adversary verdict in the PR body.
   `bg`'s base (2.5 -> 3.0) is in site-private-djbclark: **ask djbclark before changing it** (order 11).
2. PR 2: swap-ins gate (same 2 s `vm_stat` window), starvation valve, admit tuning log (decision, wait time, swap-ins, sys%). Then PR 3: native Swift
   dialog with the rulings above. Freeze needs: persisted PID + process start time (validated before SIGCONT), SIGCONT on startup,
   crash and reboot, a visible frozen-apps list with Resume, whole-process-tree freeze (Chrome/Electron helpers), a protected list
   (Paseo, terminals, Finder, Hermes, VPN/proxy, the build itself, WindowServer/Dock/loginwindow).
3. Check the load watcher registration: `~/src/djbclark-ade/bin/load-watch watcher show` names `1fcbe407-7623-4aed-a09c-abc3ecf473f9`, which
   `paseo ls -a -g --json` lists as **closed**. Alerts may reach nobody. Re-register a live watcher (`load-watch watcher set --name ...`)
   after asking djbclark whether to; do not run `watcher test` against a closed agent without saying so.
4. Handoff writers `6004533`, `86e9678`, `7ccbcb2` did not answer the Tart/Orchard question (sent the morning of 2026-11-13, before 2 PM ET).
   They block nothing. Re-route or drop after 6 h.
5. If asked to stop Orchard: `launchctl bootout gui/502/com.djbclark.orchard-dev` (also stops the route watcher thread and `orchard ssh`);
   start again with `launchctl bootstrap gui/502 ~/Library/LaunchAgents/com.djbclark.orchard-dev.plist`. The CFEngine Linux gate needs
   `container system start` before its next run.

## Detached jobs

none

## Quick Start

```bash
cd ~/src/djbclark-ade && git fetch -q origin master && git log -3 --oneline origin/master
rg -n "ADMIT_PAGEINS_S|ADMIT_CHURN_PAGES_S|ADMIT_MIN_FREE_MB|ADMIT_MAX_AGENTS|ADMIT_PER_CORE" bin/load-watch
~/src/djbclark-ade/bin/load-watch admit --json
~/src/djbclark-ade/bin/load-watch watcher show
paseo ls -a -g --json   # find agent ids; 1fcbe407 should be closed
cat ~/.claude/projects/-Users-djbclark-src-djbclark-ade/memory/project_load_gate_retune_proposal_2026-11-13.md
cat ~/.claude/projects/-Users-djbclark-src-djbclark-ade/memory/project_tart_orchard_container_state_2026-11-13.md
```
