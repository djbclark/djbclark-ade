---
schema_version: 1
handoff_id: 743e
parent_handoff_ids: [93fa]
lineage: deterministic
chain: [load-spike-monitor-t]
repo: kool-ade
workspace: main
branch: master
head_sha: 7b6434d
created_at: 2026-10-25T11:50:00-04:00
writer: claude-code
---
# Handoff — load watcher: litellm repair, /diskfree, calm boost, herdr wrapper

## The Goal
Be the machine's load watcher (Paseo bb2a32df, relay id ea221c4f, Sonnet), investigate load-watch incidents, and run /diskfree with low load.

## Where We Are
Watcher registered 2026-10-24 7:52 PM, channel tested. Done and pushed this session (2026-10-25):
1. litellm crash loop (guard trip 3:53 AM): the uv tool env lost the extra_proxy extra (prisma) at ~3:22 AM; fixed by `uv tool install --force --editable ~/src/litellm[proxy,caching,extra_proxy]`, `prisma generate` with the venv bin on PATH, `load-watch guard reset`. Running. Who reinstalled at 3:22 is unknown.
2. /diskfree: free space 25 -> 45 GiB. Deleted: npm cache, Downloads installers (C1-C9), cargo target-shared, litellm-cargo-target, cargo registry, Gradle cache (then `gradle-limits link` re-linked init.d). Compression pass ran. `~/Library` is 82 GiB (excl. iCloud/CloudStorage/Group Containers): Application Support 41, Android 17, Caches 10, pnpm 6.4.
3. skills/diskfree/SKILL.md: low-load rules (one named dir via `bg nice -n 19 dust -d 1`, from /tmp, admit gate, never scan ~), Gradle relink note, ~/Library exclusions (this commit).
4. load-watch admit "calm boost": limit 2.0/core while churn <= 25k pages/s (4faf6b1); bg defers to admit (site-djbclark 9668d42).
5. dev.herdr.server guard trip: cause = server handoff then launchd relaunch loop ("already running", exit 1). bin/herdr-server-run + config/launchd/dev.herdr.server.plist (d31547c); live plist swapped by file only (backup dev.herdr.server.plist.bak-2026-10-25); server pid 33427 untouched.
6. Chrome runaway notice in load-watch sample step (20aac9c): one Chrome process >= 0.9 cores for 5 min tells the watcher, warn only.

## What We Tried
1. Pre-calm-boost plan was swap-aware; wrong: load-watch's own calibration says swap sits at 86-92% in calm hours. Switched to churn.
2. A whole-~ `dust` ran 30+ min and added to a load of 24; an unexcluded ~/Library dust hung 1.5 h in iCloud Drive (0% CPU).
3. `apfs-compress --help` ran the whole manual pass (it has no flags); harmless. `herdr server --help` broke the live-service-CLI rule (printed usage only).
4. `nc -U -z` does not probe herdr.sock (rc 1 on a live socket), so the wrapper reads the server's own "already running" message instead.

## Key Decisions
1. Boost signal = churn, limit 2.0, churn line 25k. Rejected: swap, flat higher limit.
2. App Tamer was uninstalled 2026-10-24 (A/B trimmed day worse); do not reinstall. B8 (com.apple.container 8.6 GiB) kept: Apple containers in use. B9 (Chrome OptGuideOnDeviceModel 4 GiB) skipped by djbclark.
3. Chrome: Memory Saver is at Maximum; Auto Tab Discard is the one enabled tab extension; removing the disabled ones is djbclark's job in chrome://extensions.
4. No Gradle move: the shared remote cache on vps-primary (since 2026-10-13) holds only 4.2 MiB; vps-primary has 12 GB free on a 31 GB root and a 15 GB sdb at /home/djbclark. djbclark mentioned a "new larger disk"; none found.

## Evidence & Data
Load 69 at 9:04 AM = memory exhaustion (swap 13.5/14 GiB, ~33 MB free, churn 52k), not a build; Chrome main process at 97% on account.dyn.com. Tests: test_load_watch_admit.py 23 pass, test_load_watch_chrome_alert.py 2 pass, test_herdr_server_run.py 4 pass; site-djbclark test_bg_load_gate.py 8 pass. The admit/bg tests run via `bg uv run --no-project --with pytest python -m pytest` from /tmp.

## Operator Feedback
"Taking longer is fine" for diskfree; "make absolutely sure we do not disrupt any TUIs in herdr"; wants relay.py to always carry reverse contact info and refuse without it.

## Where We're Going
1. Answer load-watch notices (`load-watch status`, `incidents -n 5`, `ack`). The guard re-tests dev.herdr.server at 12:02 PM: expect the wrapper to exit 0, no loop; verify with `load-watch guard status | rg herdr` and `launchctl list | rg herdr`.
2. D2: run tests/test_acp_dispatch_load_gate.py only after PR 65 (https://github.com/djbclark/djbclark-ade/pull/65) is merged and its agent (Codex w2F:p45) is done.
3. relay.py: the LEAD (Paseo e934e0e, relay id b42e43f2) owns feat/relay-verified-delivery (~/src/djbclark-ade-relay-verified-wt) and is adding refuse-when-no-sender. I do not edit relay.py. Unknown senders so far: Codex w2F:p45 and "collie-native" (probably the omp session in ~/src/djbclark-ade-relay-dispatch-wt).
4. Open /diskfree items if wanted: ~/Library/Application Support (Cursor 4.9, Google 9.7 incl. the Chrome model 4.0, container 8.6), Android SDK 17 GiB, pnpm 6.4 GiB; CCC snapshot was gone at last check. Record any new deletes; ask before each.
5. Pending message to Codex w2F:p45 (queued then failed delivery; needs no reply). Plektra session 0434ba3d is waiting on djbclark (Sitting A step A1.1).
6. Drop the role when done: `load-watch watcher clear paseo bb2a32df-81a6-4370-927a-d61717b6e985`.

## Detached jobs
none

## Quick Start
```
cd ~/src/djbclark-ade && bin/load-watch status && bin/load-watch incidents -n 5
bin/load-watch admit --json
bin/load-watch guard status | rg 'herdr|litellm'
```
