---
schema_version: 1
handoff_id: 65c2
parent_handoff_ids: [e07b]
lineage: deterministic
chain: [load-spike-monitor-t]
repo: djbclark-ade
workspace: handoff-65c2-wt
branch: handoff-65c2
head_sha: e94b8dc4b49ce6f6e9464d6f75a96e065b6a2051
created_at: 2026-10-26T09:00:00-04:00
writer: claude-code
---
# Handoff — load watcher bb2a32df: net-watch repaired, moving to site-djbclark; tunnel capped near 10 Mbps

## The Goal
Keep this Paseo agent (bb2a32df, the registered load watcher) healthy and finish **net-watch**: a launchd watch that checks download speed on BOTH paths (Tailscale exit-node path via utun4 to `pastebin`, and the direct path out of en0), notifies once at episode start and once at its end, collects debug data, and reboots the Deco only under the agreed rule (direct path slow; a tunnel-only collapse alerts and captures evidence, no reboot).

## Where We Are
1. net-watch lives on branch `feat/net-watch` in `/Users/djbclark/src/site-private-netwatch-wt`, pushed head **cb9dab3** (129 tests pass, 58/58 mutants killed; two adversary rounds, both BLOCK, all findings repaired). `reboot.trigger = "direct"` by default. Nothing is installed in launchd; no real Deco reboot or ping was ever sent.
2. Move slice `net-watch-move` is RUNNING (omp Sonnet): moves net-watch into public site-djbclark (worktree `~/src/site-djbclark-netwatch-wt`, branch `feat/net-watch`), leaves symlinks in site-private (fleet-watch convention), drops the 4 added lines in site-private `.githooks/private-paths`, keeps the real gateway MAC/host in a private config only.
3. `--yes` fix for `secrets-collect.py`: branch `fix/secrets-collect-yes` in `/Users/djbclark/src/sudo-secretspec-collect-yes-wt`, pushed head **2b0ac6f** (26 tests, 18/18 mutants). Adversary round 2 (`secrets-collect-yes-adv2`) is RUNNING. Merge target `sudo-main` of fork frdminc/sudo-secretspec.
4. Deco login works: username must be the literal `admin`, password is the owner TP-Link ID password; both are stored via sudo-secretspec (`DECO_ADMIN_USER` length 5, `DECO_ADMIN_PASSWORD` length 23). Python gets EHOSTUNREACH to the LAN Deco on macOS 27, so `bin/net-watch-deco` routes the library's HTTP through `/usr/bin/curl`.
5. Network state (2026-10-26): Deco firmware 1.7.5 Build 26081412, double NAT behind 192.168.1.1; direct en0 about 111 Mbps; the tunnel path caps near 10 Mbps in both directions (receiver-timed ssh tests 10.3-15.7 Mbps), 0% loss, 28 ms. Not Wi-Fi bandwidth (direct TCP 111-146 Mbps in the same minutes), not pastebin's uplink (about 275 Mbps to Cloudflare). Root cause unresolved.
6. Load: 7.2 on 8 cores, hot 0/300 s, no incident (09:00).

## What We Tried
1. Told djbclark a Deco reboot would not help; the reboot did (retracted).
2. Claimed an inbound-only tunnel collapse from an ssh test that returned before the receiver finished (a fake 670 Mbps); retracted after receiver-timed tests.
3. `secrets-collect.py --clipboard` aborted with no terminal; stored the password with a one-process script (pbpaste to `sudo-secretspec set`), then wiped the clipboard; the `--yes` fix is the durable repair.
4. Deco login: first failure was the Python LAN restriction (curl transport), then 403 from the wrong username (email instead of `admin`).
5. Public iperf3 server (iperf.he.net) refused all four modes (inconclusive); pastebin accepts only tailnet ports 22/80/443 and has no passwordless sudo, so no server was set up there; direct ssh to its public address timed out.
6. `acp-dispatch omp --perm read-only` is refused (omp has no verified read-only mode): use `--perm all` with a read-only brief.

## Key Decisions
Reboot rule: after the frontier consult, a tunnel-only slowdown is a `tunnel_degraded` episode (one start ping, one end ping, evidence snapshot) and never reboots, because a Deco reboot cannot fix an exit-node or upstream problem. Alert rule from the consult: 3 consecutive valid pairs with D>=0.60*D0, T<=0.25*T0, T/D<=0.20; a gateway ICMP non-reply is never evidence (the Deco does not answer pings). Probe budget about 57.6 GB/day for two 20 MB probes per minute. net-watch goes in the public repo with private config separate; merging the `--yes` fix waits for an adversary APPROVE.

## Decisions
- [decision] net-watch moves to public site-djbclark with symlinks from site-private; rejected: keeping it in site-private; because it follows the fleet-watch convention and the real MAC/host live in a private config.
- [decision] Reboot only when the direct path is slow; rejected: rebooting on tunnel-only slowness; because the frontier consult ranked Deco per-flow state, MIT-to-home transit and the Mac Tailscale extension above anything a reboot fixes, and the false-reboot cost is a 2-3 minute home outage.
- [decision] The Deco client routes HTTP through /usr/bin/curl; rejected: the library's urllib transport; because every Python build gets EHOSTUNREACH to the LAN host on macOS 27.
- [ruling] "Both: throughput test now, then frontier consult" (djbclark, 2026-10-25)
- [ruling] "Direct-only reboot; tunnel-only slowness alerts and captures evidence (Recommended)" (djbclark, 2026-10-26)
- [ruling] "Move to public site-djbclark, symlinks from site-private" (djbclark, 2026-10-26)
- [ruling] "Not yet; decide after the PR merges and the Deco secrets are set (Recommended)" for adding net-watch to docs/apply-toolchain-prompt.md (djbclark, 2026-10-26)
- [ruling] "Adversary round first, then merge (Recommended)" for the `--yes` fix (djbclark, 2026-10-26)
- [ruling] "actually hand it off to be fixed now" for the secrets-collect gap (djbclark, 2026-10-26)

## Relations
- continues [[HANDOFF_load-spike-monitor-t_net-watch-build_2026-10-25_e07b]]
- decided_in [[HANDOFF_load-spike-monitor-t_net-watch-slow-tunnel_2026-10-26_65c2]]

## Evidence & Data
1. Tests: net-watch 129 passed, 58/58 mutants killed (cb9dab3); secrets-collect 26 passed, 18/18 mutants (2b0ac6f). Both run by slices, not re-run by me this session.
2. Speeds: direct en0 60 to 108 to 111 Mbps over the day; exit-node path 1.0, 41.5, then 9.8 Mbps; user's browser tests 0.41/11.6, then 37.9/32.1 after a Deco reboot, then about 10/10 after a firmware update.
3. Reports (under `~/.local/state/bigteam/net-watch/`): `net-watch-build-report.md`, `net-watch-adv-r1-report.md`, `net-watch-repair-r1-report.md`, `net-watch-adv-r2-report.md`, `net-watch-repair-r2-report.md`, `net-watch-frontier-report.md` (43 KB, ranked causes), briefs `frontier-brief.md`, `repair-r2-brief.md`, `move-brief.md`. For the `--yes` fix under `~/.local/state/bigteam/secrets-collect-yes/`: `adv-report.md`, repair report, `adv2-brief.md`.
4. Scratch (disposable): `/tmp/tun-test2.py`, `/tmp/direct-test.py`, `/tmp/lan-probe*.py`. iperf3 3.22 installed with brew; `~/.ssh/known_hosts` has a `pastebin` HostKeyAlias.

## Operator Feedback
1. Asked what a wired connection would gain: answered that wired gains little (0% loss); Wi-Fi bandwidth and Mac slowness are ruled out by direct TCP of 111-146 Mbps. Not fully ruled out: UDP-specific Wi-Fi behaviour and the Mac's Tailscale extension.
2. Said we may install any tools needed (iperf3 done).

## Where We're Going
1. **Next action:** re-arm the two waiters (Detached jobs), then read `net-watch-move-report.md` (the file is 225 bytes now, so the slice may still be writing it; check `.done`) and run `bin/acp-dispatch check` on its record.
2. Adversary round 3 on net-watch in the new public worktree (`acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high --perm all`, read-only brief; re-review every repair). Then PRs with the verdict and head SHA quoted: public site-djbclark first, site-private symlink PR second. Also an adversary verdict is required before any PR (CLAUDE.md item 28).
3. `--yes` fix: read `secrets-collect-yes-adv2-report.md` (the brief names `adv2-report.md`; check both). APPROVE: fast-forward `sudo-main` with `fix/secrets-collect-yes` (djbclark approved merging after an adversary round) and, per CLAUDE.md item 38, open the upstream PR/issue on sudo-secretspec after a dupe search. BLOCK: another repair round.
4. djbclark's own actions (do not do for them): confirm `net-watch install` (launchd) and any real Deco reboot (drops the home network 2-3 minutes); optionally the phone-hotspot test with the same exit node, or a second device on the same Deco, which is the decisive test for the tunnel cap.
5. After the PR merges and the Deco secrets are set, ask again about `docs/apply-toolchain-prompt.md`.
6. Watch duties: `bin/load-watch status`, `bin/load-watch guard status`, answer notices with `load-watch ack <id>`. Never `self-slash --finish` here (exit 12 for the watch holder).
7. Loose: `tests/test_acp_dispatch_load_gate.py` still open until PR 65 merges and Codex `w2F:p45` is idle; relay `ac705b` to `w2F:p45` failed (the dialog is djbclark's). `~/ops/site-private/bin/git-commit-own` does not exist (the slice used `~/.local/bin/git-commit-own`): tell djbclark, do not fix unasked.

## Detached jobs
1. Job `/Users/djbclark/.local/state/bigteam/net-watch/jobs/net-watch-move.json`; report `/Users/djbclark/.local/state/bigteam/net-watch/net-watch-move-report.md`; done `/Users/djbclark/.local/state/bigteam/net-watch/net-watch-move-report.md.done` (does not exist at 09:00, still running); rearm `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/net-watch/jobs/net-watch-move.json /Users/djbclark/.local/state/bigteam/net-watch/net-watch-move-report.md.done`. Moves net-watch to public site-djbclark; read the report, run `acp-dispatch check`, then adversary round 3.
2. Job `/Users/djbclark/.local/state/bigteam/secrets-collect-yes/jobs/secrets-collect-yes-adv2.json`; report `/Users/djbclark/.local/state/bigteam/secrets-collect-yes/secrets-collect-yes-adv2-report.md`; done `.../secrets-collect-yes-adv2-report.md.done` (not yet at 09:00); rearm `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/secrets-collect-yes/jobs/secrets-collect-yes-adv2.json /Users/djbclark/.local/state/bigteam/secrets-collect-yes/secrets-collect-yes-adv2-report.md.done`. Adversary round 2 on 2b0ac6f; act per Where We're Going 3.

## Quick Start
```bash
cd ~/src/djbclark-ade
bin/acp-dispatch check ~/.local/state/bigteam/net-watch/jobs/net-watch-move.json
bin/acp-dispatch check ~/.local/state/bigteam/secrets-collect-yes/jobs/secrets-collect-yes-adv2.json
git -C ~/src/site-private-netwatch-wt log -3 --oneline
git -C ~/src/sudo-secretspec-collect-yes-wt log -3 --oneline
bin/load-watch status
```
Tests: inside the worktree, `~/ops/site-private/bin/bg uv run --with pytest python -m pytest tests/test_net_watch.py`.
