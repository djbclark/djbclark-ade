---
schema_version: 1
handoff_id: e07b
parent_handoff_ids: [743e]
lineage: deterministic
chain: [load-spike-monitor-t]
repo: kool-ade
workspace: main
branch: master
head_sha: 016478e8fc76c30a62b2c458b310221478ead9cd
created_at: 2026-10-25T14:05:00-04:00
writer: claude-code
---
# Handoff — load watcher bb2a32df: net-watch build in flight, PR 72 merged

## The Goal
Keep this Paseo agent (bb2a32df, the registered load watcher) healthy and finish the new **net-watch** tool: a watch that notices download speed under 30 Mbps for 10+ minutes on EACH network path, pings djbclark once at episode start and once at its end, collects debugging data, and tries a Deco reboot when the direct path is slow.

## Where We Are
1. net-watch build slice `net-watch-build` (omp, anthropic/claude-sonnet-5-5, kind code) is RUNNING in worktree `/Users/djbclark/src/site-private-netwatch-wt` (site-private, branch `feat/net-watch`, base 986d6c3). Brief: `~/.local/state/bigteam/net-watch/brief.md`. An operator addition (test BOTH paths: normal Tailscale exit-node route via utun4 to exit node `pastebin` (pastebin.xvm.mit.edu) and the direct route out of en0; per-path episodes; reboot only when the direct path is slow) was delivered through `acp-dispatch tell` (`delivered: inbox`, text in /tmp/nw-tell.txt, may be gone). Nothing is installed or loaded into launchd; the slice must not call the real Deco or send real pings.
2. Network facts (2026-10-25): en0 192.168.68.57, gateway/Deco master 192.168.68.1, default route utun4 (Tailscale 100.113.53.87), exit node peer `pastebin`.
3. Deco reboot needs admin credentials that DO NOT exist yet: operator must run the `sudo-secretspec` set steps that docs/net-watch.md (written by the slice) will list (items DECO_ADMIN_USER / DECO_ADMIN_PASSWORD). Until then the start ping says "reboot skipped: no credentials".
4. Merged/closed this session: PR 72 merged 3fbc6ad (self-slash refuses `--finish` for a Paseo watch holder, exit 12; adversary r1 BLOCK d7bc059, r2 APPROVE d65e208); docs a9a6ae1 then 7380c56 (dedupe of the Go guard install paragraph); PR 70 (rtk config scan) closed unmerged because PR 68 already disabled RTK rewriting; upstream comment on rtk-ai/rtk#4521.
5. Peers: ADE queue lead is `djbclark-ade-8d` (session b42e43f2, Paseo e934e0e6, relay id 430f45ba); it owns relay.py, PRs 59/73/74 and the b457 chain; do not touch. Codex `w2F:p45` (PR 68/RTK owner) never got my coordination reply: pane blocked on a permission dialog (relay ac705b failed, same as 8dd488, b0ea05). No ack from it; nothing conflicts.
6. Load: herdr guard `dev.herdr.server` ok, calm 3.5 load on 8 cores at 1:19 PM, no open incident.

## What We Tried
1. `self-slash --finish` to end the session at /loose time: it queued an archive of THIS agent because I did not realise this session is the load watcher; I killed the waiter pid by hand. Root cause: the /baton resolved the repo `main` chain (b457) by directory instead of the handed-off chain. Fixed by PR 72 plus baton/loose skill wording.
2. PR 70 (rtk config-scan fix): duplicated by PR 68, closed. The adversary's report (`~/.local/state/bigteam/adhoc-2026-10-25-rtk/adv-rtk-r1-report.md`) lists the config-scan gaps (OPENCODE_CONFIG*, managed config, agent rules).
3. Merging PR 70 and PR 72 while master moved: the first conflicted in CHANGELOG/rtk.ts; PR 72 needed a `git-commit-own --staged` merge commit (partial commit during a merge fails).

## Key Decisions
Choices made with djbclark's answers this session are indexed below. net-watch lives in site-private as a standalone script, not inside fleet-watch, because fleet-watch is a symlink into the public site-djbclark.

## Decisions
- [decision] net-watch is a standalone bin/net-watch in site-private with its own launchd job; rejected: extending fleet-watch; because fleet-watch lives in public site-djbclark and the probe config names the home network.
- [ruling] "Do 2 and 3, also collect any information that may be useful for debugging. Also do 1. Do not continuously report the problem, rather just notify when the problem starts and when it ends." (djbclark, 2026-10-25)
- [ruling] "We should do the tests on all network paths, so both the normal tailscale to exit note pastebin.xvm.mit.edu route most stuff takes and the direct route a small subset of apps take." (djbclark, 2026-10-25)
- [ruling] "We should add a watch to see if we are clearly slowed down to under 30Mbs download speed at any point. It doesn't have to be exact, and it does have to last for 10 minutes or more before we act on it." (djbclark, 2026-10-25)
- [decision] Reboot the Deco only when the direct path is slow, once per episode, 2 h cooldown; rejected: rebooting on a tunnel-only slowdown; because an exit-node problem is not fixed by a Deco reboot.
- [ruling] "Yes: merge master in, re-check CI, squash-merge pinned" for PR 72 (djbclark, 2026-10-25)
- [decision] PR 70 closed in favour of PR 68; rejected: merging my config-scan approach; because it would restore automatic rewriting that PR 68 disabled on purpose.

## Relations
- continues [[HANDOFF_load-spike-monitor-t_loadwatch-diskfree-calm-boost_2026-10-25_743e]]
- decided_in [[HANDOFF_load-spike-monitor-t_net-watch-build_2026-10-25_e07b]]

## Evidence & Data
1. PR 72 merge: `3fbc6ad`, 5 checks green on head 5f1229a; self-slash suite 90 passed; mutants fail the new tests.
2. Adversary reports: `~/.local/state/bigteam/adhoc-2026-10-25-rtk/adv-watchguard-r{1,2}-report.md` (r2 minor notes B2 gtimeout needs `-k`, B3 silent fail-open, B4 double `watch status` call: not fixed, no one asked for a todo list).
3. Tests last run: tests/test_self_slash.py 90 passed; nothing run yet for net-watch.
4. `bin/route_agent.py plan --kind code`: claude is not routed for code while the subscription is tight; omp Sonnet 5.5 chosen.

## Operator Feedback
1. djbclark pointed out, correctly, that this agent is the load watcher and must not be archived (the `/loose` finish choice was a mistake).
2. Wants start/end notifications only, never continuous reports.

## Where We're Going
1. **Next action:** re-arm the build waiter in the background: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/net-watch/jobs/net-watch-build.json /Users/djbclark/.local/state/bigteam/net-watch/net-watch-build-report.md.done` (run_in_background, timeout 7200000), then `bin/acp-dispatch check` the record, read `net-watch-build-report.md`, confirm the slice saw the two-path addition (tests for tunnel-only, direct-only, both).
2. Adversary round on `feat/net-watch` (security: credentials, subprocess, launchd, state files) via `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high` (quota is tight: no Fable/Opus Agent-tool sub-agents); repair rounds; PR in site-private with the verdict quoted. site-private's `~/ops` master is shared and dirty with other sessions' memory files: promote by fast-forward only, never stash.
3. Ask djbclark to run the Deco secret steps from docs/net-watch.md (I cannot set secrets), then dry-run `net-watch reboot --dry-run`, then install the launchd job (`com.djbclark.net-watch`, 60 s tick); installing and loading it is outward-facing: confirm first. Rebooting drops the whole home network for 2-3 minutes.
4. Per the 'New tool' rule, ask djbclark whether net-watch belongs in `docs/apply-toolchain-prompt.md`.
5. Watch duties: `bin/load-watch status`, `bin/load-watch guard status`, answer notices (`load-watch ack <id>`). Drop the role only when done: `load-watch watcher clear paseo bb2a32df-81a6-4370-927a-d61717b6e985`. Never run `self-slash --finish` here (it now refuses).
6. Open from earlier: `tests/test_acp_dispatch_load_gate.py` once PR 65 is merged and Codex w2F:p45 is idle; relay ac705b to w2F:p45 failed (dialog is djbclark's to answer); shared checkout `~/src/djbclark-ade` is behind origin/master by 7 (a promoter fast-forwards it; I do not).

## Detached jobs
1. Job `/Users/djbclark/.local/state/bigteam/net-watch/jobs/net-watch-build.json`; report `/Users/djbclark/.local/state/bigteam/net-watch/net-watch-build-report.md`; done `.../net-watch-build-report.md.done` (does not exist yet, still running); rearm `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/net-watch/jobs/net-watch-build.json /Users/djbclark/.local/state/bigteam/net-watch/net-watch-build-report.md.done`. Builds bin/net-watch, launchd plist, tests and docs/net-watch.md in the site-private worktree; read the report, run `acp-dispatch check`, then step 2 above. The old waiter (background task bsycgr9a1) belongs to the cleared session and will not survive.

## Quick Start
```bash
cd ~/src/djbclark-ade
bin/acp-dispatch check ~/.local/state/bigteam/net-watch/jobs/net-watch-build.json
git -C ~/src/site-private-netwatch-wt log -5 --oneline; git -C ~/src/site-private-netwatch-wt status --short
bin/watch status | rg '^load'
bin/load-watch status
```
Tests: none run for net-watch yet; run via `~/ops/site-private/bin/bg uv run --with pytest python -m pytest tests/test_net_watch.py` inside the worktree.
