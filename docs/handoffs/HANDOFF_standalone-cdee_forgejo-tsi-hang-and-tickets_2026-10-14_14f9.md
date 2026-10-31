---
schema_version: 1
handoff_id: 14f9
parent_handoff_ids: [0cc7]
lineage: deterministic
chain: [standalone-cdee]
repo: kool-ade
workspace: main
branch: master
head_sha: f8643f5aa114c967ca6a04b947194abc5bce2ff9
created_at: 2026-10-14T07:00:00-04:00
writer: claude-code
---
# Handoff — Forgejo CI: TSI hang root-caused, tickets filed

## The Goal
Get the private Plektra repo's full CI (Gradle compile plus about 1,400 Robolectric unit tests) working on SIPB's Hyades libkrun runner (forgejo.mit.edu, label `ubuntu`), compare it with GitHub and the local M1 Air, and give SIPB and libkrun real data about the runner's slow disk and a test hang.

## Where We Are
1. **Done and filed (2026-10-14):** SIPB/hyades#2 (https://forgejo.mit.edu/SIPB/hyades/issues/2, measurements, three storage variants, suggestions, hang write-up), libkrun/libkrun#926 (TSI hang in `shutdown()`/`getpeername()` while another thread is blocked in `accept()`/`read()`), libkrun/libkrun#924 (virtiofs speed, body rewritten with links). All three link to each other. I cannot watch them for replies: check with `gh issue view 926 -R libkrun/libkrun --comments`, `gh issue view 924 -R libkrun/libkrun --comments`, `skills/forgejo/scripts/forgejo-api GET /repos/SIPB/hyades/issues/2/comments`.
2. **The hang is fixed.** It was never disk speed (as-is, tmpfs and loop storage all hung identically, runs 189-191). Under libkrun TSI, `shutdown()` and `getpeername()` block while another thread sits in `accept()`/`read()` on the same socket (`getsockopt(SO_ACCEPTCONN)` returns at once but says 0 for a listener, verified in probe run 206). Java's `Socket.close()`/`ServerSocket.close()` call `shutdown()` first, so okhttp MockWebServer tests froze the Gradle test worker; a signal does wake `accept()`. The shim `skills/forgejo/examples/plektra/loopback-port-shim.c` now also tracks listener fds (`listen`/`close`/`dup2`/`dup3`) and wraps `shutdown()` (no-op on listeners, else real call in a helper thread with a 300 ms wait; `SHIM_SHUTDOWN=passthrough|noop` for experiments). Run 203: full suite finishes, 1,417 tests, test step 3 m 27 s, job about 12 min.
3. **Still failing on the runner (7 tests):** the known upstream `CornerButtonThemeTest` plus about six MockWebServer tests (`OpenAiLiveSpeechClientTest`, `SpeechApiClientTest`) with "unexpected end of stream" or timeouts, a different subset each run (runs 203-205), also with `SHIM_SHUTDOWN=noop`. They pass locally. Probably a second TSI loopback data-path bug; no repro yet.
4. **Disk and storage numbers** (same commit, one run each; shared host, under 20% is noise): install 69/49/45 s, compile 276/203/183 s, four targeted test steps 112/139/89 s, total 458/393/324 s for root fs / tmpfs / ext4 loop image. Resources: runner 16 vCPU, 62.8 GiB; vs M1 Air cores 2.0x, RAM 3.9x, all-thread compute 2.6x, one-thread 0.85x, small-file disk 0.034x-0.23x (SKILL.md item 7).

## What We Tried
1. LD_PRELOAD via `$GITHUB_ENV` for the port-0 shim: did not reach the Gradle daemon. `/etc/ld.so.preload` does.
2. First matrix runs (184-187) died at once: my heartbeat EXIT trap ran `kill $HB` with `HB` empty (exit 2 under `set -e`); then a push failed (non-fast-forward on reused branch names; `push-bench.sh` now force-pushes throwaway branches).
3. Thread dumps of the hung worker (heartbeat v2/v3, runs 192-194) showed about 970 idle `queued-work-looper` threads and a worker with no running test; the real stack was `MockWebServer.shutdown` in `Net.shutdown`.
4. First shim fix (`shutdown()` no-op on `SO_ACCEPTCONN` sockets) failed: `SO_ACCEPTCONN` reads 0 on a TSI listener and `getpeername` blocks, so the shim cannot ask the socket. Fix: remember listener fds in `listen()`.
5. After that the worker hung in `Socket.close()` of an okhttp client with a blocked reader: made `shutdown()` run in a helper thread with a 300 ms wait.
6. I claimed `getsockopt` also blocks (in #926, SIPB#2, SKILL.md): wrong, caught by the `/loose` sweep, probe run 206 verified, corrections made and pushed.
7. I filed #926 with an empty body (a BSD `sed` failure in a pipeline went unnoticed); fixed a minute later. I also filed #926 without first searching existing issues; searched afterwards ("shutdown accept", "TSI hang", "getpeername", "tsi blocking accept lock": nothing nearer than #818 and #924), and noted that in #926.

## Key Decisions
1. Libkrun `krun.use_passt=1` was rejected by SIPB (nested passt), so the fix is a userspace shim; mention in tickets that `use_passt=1` or a TSI fix would remove the need for it.
2. Tickets were filed only after testing finished (memory `feedback_filing_tickets_after_testing.md`); the draft was shown, and the user approved with "yes".
3. Rejected: asking SIPB for a physical SSD alone (host SSD under virtiofs would still be write-through and single-threaded; only a virtio-blk disk helps, and crun has no annotation for it, libkrun#667).
4. Deleted the 15 throwaway branches on `djbclark/plektra-djbclark` (kept `bench/mit-ci`), regenerated `examples/plektra/forgejo-ci.yml` from the deriver, removed the never-sent `sipb-matrix-post.md`.

## Evidence & Data
1. Matrix results (logs in `/tmp/matrix*/`, may be gone): run 189-191 as-is/tmpfs/loop full suite (hung); run 203 `/tmp/matrix7/summary.md`: 1,417 tests, 7 failed, 3 m 27 s; run 205 variant comparison (`async` 6/11 fail, `passthrough` hangs, `noop` 5/11 fail) in `/tmp/matrix9/`.
2. Probe results: runs 195, 196, 198-200 (shutdown, accept wake-ups), 202 (client socket with blocked reader: close returns after 302 ms with shim, hangs without), 206 (`getsockopt` returns 0, `getpeername` hangs).
3. Files (all under `skills/forgejo/`): `SKILL.md` item 5 (both TSI bugs) and item 7 (resources, disk); `examples/plektra/` has `loopback-port-shim.c`, `derive-forgejo-ci.py`, `heartbeat.sh`, `run-matrix.sh`, `push-bench.sh`, `push-probe.sh`, `accept-probe.c`, `Sd3.java`, `probe-*.yml`, `comparison.md`, `sipb-hyades-issue.md`, `libkrun-issue.md`, `libkrun-tsi-shutdown-issue.md`, `hyades-disk-research.md`.
4. Commits this session (latest first): `f8643f5` queue entry, `704e4ba`, `85a0bcb`, `21c087a`, `0d0c53a`, `5f95b1c`. Memory: `project_forgejo_ci_matrix_state.md`, `feedback_filing_tickets_after_testing.md`.

## Operator Feedback
1. Ratios as `N.Nx`; numbered lists; script-driven runs where cheaper than AI thinking; wait for testing before filing tickets; "second time I've seen the sed failure" (queued); may consult Fable briefly if stuck (not needed).

## Where We're Going
1. **Next action (optional, when replies arrive):** check the three tickets for replies (commands above) and answer them; nothing is blocking.
2. The `sed` failure investigation, queued last in `docs/queue.md` ("Why the `sed` edit failed twice"): find which `sed`, why a failing last pipeline stage still counted as success, add an `[ -s file ]` guard before any `--body-file`, fix the instructions (`~/CLAUDE.md` items 11 and 33), say what changed.
3. Find a minimal repro for the flaky MockWebServer tests (queued in `docs/queue.md`), file it upstream, link it from #926 and SIPB#2.
4. Optional: re-measure download speed (`curl -L`, the earlier test returned 0.0 without `-L`), try `mount -o remount,dax` on the virtiofs root, and consider adding `gcc`-free precompiled shim to the base image request.
5. Dirty files in the repo that are not mine: `skills/autorename/*`, `skills/helm/*`, `tests/test_autorename_tab_label.py`, `tests/test_helm_question_status.py` (another session's work; leave them).

## Detached jobs
none (no bigteam job records owned by this session; no background process is running).

## Quick Start
```bash
cd ~/src/djbclark-ade && git log --oneline -6
gh issue view 926 -R libkrun/libkrun --comments | tail -20
skills/forgejo/scripts/forgejo-api GET /repos/SIPB/hyades/issues/2/comments | jq -r '.[]|.user.login+": "+.body' | tail -20
# run a probe workflow on the runner (private test repo, base branch bench/mit-ci):
skills/forgejo/examples/plektra/push-probe.sh skills/forgejo/examples/plektra/probe-accept.yml probe/accept skills/forgejo/examples/plektra/accept-probe.c
# or the full suite with thread dumps:
MATRIX_MODE=diag DIAG_STEP_MIN=30 skills/forgejo/examples/plektra/run-matrix.sh /tmp/matrixN   # run_in_background, read only summary.md
```
