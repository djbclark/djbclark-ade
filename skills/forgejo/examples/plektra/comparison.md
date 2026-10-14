# Plektra compile-time comparison: github.com vs forgejo.mit.edu vs local

Snapshot 2026-10-13. Rule from djbclark: do not start new github.com or local
builds just to test. Source for the local column: 94 recorded builds mined from
`~/.cache/gradle/daemon/8.13/daemon-*.out.log` and Claude transcripts (all
2026-10-12 to 10-13, StableDebug variant only).

| Measure | github.com (`ci.yml`, ubuntu-latest, JDK 17) | forgejo.mit.edu (`ubuntu`, JDK 17) | local Mac (JDK 21) |
|---|---|---|---|
| Cold compile + configure (compile-only step) | no run yet | 4 m 23 s (run 177, 2026-10-13, with the port-0 shim) | 4 m 30 s (cold daemon, 27/28 tasks) |
| Targeted test steps (core modifier / router E2E / forward-delete / IME) | no run yet | 59 s / 11 s / 11 s / 25 s (Gradle's own times, run 177) | not recorded per step |
| Cold full `testStableDebugUnitTest`, fresh tree | no run yet | 3 m 27 s test step after compile (run 203, 2026-10-14, 1,417 tests, 7 failed: known `CornerButtonThemeTest` plus about 6 flaky MockWebServer tests); job total about 12 min | 8 m 34 s best; 11 m 53 s; 13 m 53 s (load 156) |
| Warm full `testStableDebugUnitTest` | no run yet | not measured | 2 m 17 s to 3 m 56 s (about 3 min is the tests) |
| `lintStableDebug` | no run yet | not reached | 2 m 48 s warm to 6 m 31 s fresh tree |
| Toolchain setup (JDK + Android SDK) | preinstalled | about 80 s (apt + sdkmanager), measured in run 170 | n/a |

## Why two columns are empty

1. **github.com:** the fork has never run a workflow. `ci.yml` fires only on
   `pull_request`; `debug.yml`, `play.yml`, `release.yml` are `workflow_dispatch`
   only; upstream PR runs from the fork sit at `action_required`. The first number
   will come from the next real PR's CI: then
   `scripts/ci-step-times github djbclark/plektra-djbclark RUN_ID`.
2. **forgejo.mit.edu:** loopback was refused inside the runner microVM (libkrun#818) until the
   port-0 `LD_PRELOAD` shim (`loopback-port-shim.c`, preloaded through `/etc/ld.so.preload`)
   went in; since run 177 Gradle compiles and passes the targeted tests there. The full
   `testStableDebugUnitTest` step then hung (runs 177, 183, 185-194, 201) because `shutdown()` blocks in the
   libkrun guest while another thread waits on the socket (okhttp MockWebServer); the shim now wraps it (run 203
   finished). Branch `bench/mit-ci` carries the workflow.
   Per-job resources and the disk comparison with the Mac: SKILL.md item 7.

## Confounds to state with any number

1. Local daemon is capped at `-XX:ActiveProcessorCount=2` and the Mac runs at
   load 12-175 on 8 cores; Gradle's printed time includes the machine-wide Gradle
   slot wait, so use the net-of-slot figure (one "1 h 11 m" run was 3 m 56 s of work).
2. Local uses JDK 21 and a local plus remote build cache; CI uses JDK 17 and, on
   GitHub, `cache: gradle` for dependencies only.
3. MIT job hardware is a shared 16-vCPU microVM (2.0x the Mac's cores, 0.85x one-thread compute, 3.9x RAM), but its disk is virtiofs: small-file operations run at 0.034x to 0.23x of the Mac; `/dev/shm` tmpfs is 29-33x faster than that disk. Repeat runs for a spread.

## Storage variants (same commit, one run each, 2026-10-14; the jobs share a host, treat under 20% as noise)

| step (s) | root fs (as-is) | guest tmpfs | ext4 loop image |
|---|---|---|---|
| install JDK + SDK | 69.3 | 49.1 | 44.9 |
| compile | 276.4 | 202.8 | 182.7 |
| four targeted test steps | 112.0 | 138.6 | 88.8 |
| total | 458 | 393 | 324 |

Workspace 300 MiB, Gradle home 1.7 GiB, SDK 600 MiB; tmpfs used 2.5 GiB, RAM in use up to 11.7 GiB.

