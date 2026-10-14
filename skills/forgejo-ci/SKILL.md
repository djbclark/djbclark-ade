---
name: forgejo-ci
description: >-
  Run CI jobs on SIPB's Hyades runner (forgejo.mit.edu, label `ubuntu`, libkrun
  microVMs): choose the job image, use the loopback LD_PRELOAD shim for libkrun
  TSI bugs (Gradle daemon, okhttp MockWebServer, WebSocket tests hang or flake),
  run probe workflows, read logs, and file SIPB/libkrun tickets properly. Use
  when a job on forgejo.mit.edu hangs, flakes, is slow, or needs Java/Android,
  or when a task mentions Hyades, `runs-on: ubuntu`, libkrun, TSI or the shim.
---

# Forgejo CI on SIPB Hyades

Written 2026-10-14 from runs 168-240 on the private test repo `djbclark/plektra-djbclark`.
Canonical source `skills/forgejo-ci/` in `~/src/djbclark-ade`. Token, API and git helpers are the `forgejo` skill
(`forgejo-api`, `git-forgejo`; **never `--help` on them**). Long-form evidence with run numbers: `runner-notes.md`
(here) and `skills/forgejo/examples/plektra/*.md`.

## 1. Runner facts

1. `runs-on: ubuntu` (also `alpine`, `rocky`), never `ubuntu-latest`; workflows in `.forgejo/workflows/`; actions need a full
   URL (`uses: https://github.com/actions/checkout@v4`); `upload-artifact@v4` is unsupported.
2. **One libkrun microVM per job** (rootless podman, krun; "2.0-sipb", guest kernel 6.12.91), `capacity = 4` jobs at once on a
   shared host that has **one loopback port space** for TSI sockets. Per job: 16 vCPU (EPYC 3.0 GHz), 62.8 GiB RAM, root,
   disk is virtiofs (slow for small files; `/dev/shm` tmpfs is 29-33x faster; a remount with `dax` does nothing).
   Download speed is fine (79-102 MB/s).
3. Label images are `forgejo.mit.edu/sipb/ci-images:<label>` (Dockerfiles in `SIPB/ci-images`: ubuntu 26.04, alpine 3.24,
   rocky 10): git, curl, python3, node, podman, go; **no gcc, JDK or Android SDK**. Images are never re-pulled, so pin a
   job image by digest. A job-level `container: image:` replaces the label's image (verified, run 239).
4. Node actions (`actions/checkout`) need `node` in the job image (node 18 is enough: run 240).
5. Job logs: only the first `⭐ Run` marker survives; print your own `BENCHSTEP` markers (`scripts/ci-step-times`).

## 2. Choosing the job image

| Image | Has | Lacks | Use |
|---|---|---|---|
| stock `ubuntu` label | git, node, python3, podman | gcc, JDK, SDK | scripts and non-Java jobs |
| **`ghcr.io/djbclark/ci-image-plektra@sha256:<digest>`** (ours, public, amd64; source `github.com/djbclark/ci-image-plektra`) | android-sdk 36, JDK 17, node 18, gcc, git, python3, **`/usr/local/lib/portshim.so`** | nothing Plektra needs | Gradle/Robolectric/Android jobs: no install, no compile |
| `ghcr.io/cirruslabs/android-sdk:36` | SDK 36, JDK 21, gcc | node, JDK 17 | base of ours; 47 s first pull, cached after |
| `eclipse-temurin:17-jdk-noble` | JDK 17 | gcc, git, SDK, node | saves nothing |
| `mingc/android-build-box` | everything | (5.9 GB) | too big |

Our image's digest is printed by its GitHub Actions run (`gh run list -R djbclark/ci-image-plektra`; the digest is in the
"Verify the pushed image" step). To change the image, edit its Dockerfile and push; update the digest in the workflow. The
shim source is pinned there by commit (`SHIM_SHA`): bump it when `loopback-port-shim.c` changes.

## 3. The shim (libkrun TSI workarounds)

Source `skills/forgejo/examples/plektra/loopback-port-shim.c` (232 lines); **public home since 2026-10-14: https://forgejo.mit.edu/djbclark/loopback-port-shim**
(MIT; the shim, `make check`, probes, `docs/`, snapshots of these skills, probe workflows and tooling; local clone `~/src/loopback-port-shim`;
SIPB/hyades#3 points at it). **Four problems, one `LD_PRELOAD` library:**

1. A listener bound to **port 0 is unreachable** (libkrun#818). The shim rewrites `bind(port 0)` to a random port in
   20000-32000 (nanosecond seed, mutex, ring of the last 4096 ports).
2. **A thread blocked in `recv()`/`read()`/`accept()` holds the socket lock**, so `send()`, `shutdown()` and `getpeername()`
   from other threads block (libkrun#819, #926). The shim waits in `poll()` (which holds no lock) before blocking reads and
   runs `shutdown()` in a helper thread with a 300 ms wait (no-op on listeners).
3. **A listener closed during a blocked `accept()` is not released**: a new listener on that port loses connections, stale
   ones drain in about 60 s (libkrun#929). Cure: never reuse a port soon (the ring).
4. TSI host sockets always have `SO_REUSEPORT`, so a duplicate `listen()` succeeds (libkrun#860).

Also: `SO_RCVTIMEO` is not honoured under TSI (use `poll`); `getsockopt(SO_ACCEPTCONN)` says 0 for a listener.

**Use it opt-in.** In a job on our image: `echo /usr/local/lib/portshim.so >> /etc/ld.so.preload` (root; reaches Gradle's
daemon and test workers) or `LD_PRELOAD=/usr/local/lib/portshim.so` for one process. **An `LD_PRELOAD` written to
`$GITHUB_ENV` does not reach Gradle's daemon.** On a stock label: `apt-get install gcc libc6-dev` (about 30 s), fetch the
source, `gcc -shared -fPIC -O2 -pthread -o /usr/local/lib/portshim.so shim.c -ldl` (works on glibc and musl).
**Not covered:** Go and other static binaries (no dynamic loader); programs depending on `SA_RESTART`/`EINTR` (untested
prediction), so it is **not** enabled globally. Do not set it for jobs without loopback servers.

## 4. Probing and measuring

1. `examples/plektra/push-probe.sh WORKFLOW.yml probe/NAME [EXTRA_FILE...]` pushes a probe workflow as a throwaway branch on
   top of `bench/mit-ci` (extra files land at the repo root); `wait-run.sh SHA OUT` waits (`WAIT_MAX`, `RP`) and saves the
   log; `push-bench.sh asis|tmpfs|loop BRANCH` derives and pushes the full workflow (`DERIVE_IMAGE=ghcr.io/...@sha256:...`
   uses our image); `run-matrix.sh` does unattended matrices. Run them with `run_in_background`; read `summary.md` only.
2. Probe sources: `duplex-probe.c` (blocked recv vs send), `reuse-probe.c` (listener reuse, `REUSE_PORT`, modes
   jdk/close/kill/none), `dup-bind-probe.py`, `accept-probe.c`, `java-churn/` (okhttp loop), `keepalive-repro.py`,
   `listener-churn-repro.py`, `heartbeat.sh` (jstack of the stuck worker). `probe-*.yml` run them.
3. **Use a fresh port per probe run**: stale listeners from an earlier no-shim run on the same port drain over about a minute
   and look like shim failures (that mistake cost a day; libkrun#929 corrected).
4. Normal-Linux controls: Apple `container` CLI (Ubuntu 24.04, kernel 6.18) shows what a non-TSI kernel does.
5. Timings on a shared host: repeat; under 20% is noise.

## 5. Tickets (etiquette learned)

1. **Search the upstream tracker first** (`gh search issues --json`), with several phrasings: I filed #926 before finding
   #819 and #860 and had to say so.
2. **File only after testing finishes**; show the draft to djbclark first; label it "prepared with an AI coding assistant,
   results reviewed by me"; correct your own errors in the ticket in the same breath.
3. Build the body with `jq -Rs`/`--rawfile`, check `[ -s file ]` before posting (an empty body once went out through a BSD `sed`
   failure in a pipeline); never read results through a pipe. Use GNU tools (`gsed`, `ggrep`).
4. Ticket map: SIPB/hyades#2 (disk and hang report), **#3 (ask: ship the shim precompiled, opt-in, in the ci-images)**;
   libkrun #818 (port 0), #819 (blocked recv), #860 (always `SO_REUSEPORT`), #924 (virtiofs speed), #926 (`shutdown`/`getpeername`
   hang), #929 (stale listener). Replies are not watched: check with `gh issue view N -R libkrun/libkrun --comments` and
   `forgejo-api GET /repos/SIPB/hyades/issues/N/comments`.

## 6. Results to date

1. **Without the shim** (runs 189-205): the test step hangs forever on okhttp MockWebServer, or 7 tests fail per run, a different
   flaky set each time. Disk speed was not the cause (as-is, tmpfs, loop storage all hung identically).
2. **With the shim** (runs 229, 230, and 241 on our image): 1,417 tests, **1 failure, `CornerButtonThemeTest`**, which also fails
   on GitHub Actions and on a laptop (an upstream bug); test step about 3 minutes. An okhttp MockWebServer loop: 800 iterations in
   1 s with the shim vs 150 s per 150 and about 30% failures without.
3. **Our image** (run 241): setup step 0.2 s instead of about 100 s (JDK + SDK install 69 s, gcc, shim compile); compile 4 m 25 s
   unchanged (virtiofs-bound); job otherwise as before. Run 240: `actions/checkout`, toolchain and shim verified.
4. Still open: whether SIPB wants to host the image or ship the shim in the label images (SIPB/hyades#3, no reply yet); making the
   shim safe to preload globally (needs `SA_RESTART`/`EINTR` tests, per-job port ranges, Go/static-binary answer).

Reference files, all in `skills/forgejo/examples/plektra/`: `shim-by-default.md` (how to get the shim into jobs, six ways,
risks), `sipb-hyades-shim-request-draft.md` (the filed #3), `libkrun-*.md` and `sipb-hyades-*.md` (ticket texts),
`comparison.md`, `hyades-disk-research.md`, `derive-forgejo-ci.py`.
