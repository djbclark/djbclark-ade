# Plektra compile-time comparison: github.com vs forgejo.mit.edu vs local

Snapshot 2026-10-13. Rule from djbclark: do not start new github.com or local
builds just to test. Source for the local column: 94 recorded builds mined from
`~/.cache/gradle/daemon/8.13/daemon-*.out.log` and Claude transcripts (all
2026-10-12 to 10-13, StableDebug variant only).

| Measure | github.com (`ci.yml`, ubuntu-latest, JDK 17) | forgejo.mit.edu (`ubuntu`, JDK 17) | local Mac (JDK 21) |
|---|---|---|---|
| Cold compile + configure (a 4-test run) | no run yet | blocked, see below | 4 m 30 s (cold daemon, 27/28 tasks) |
| Cold full `testStableDebugUnitTest`, fresh tree | no run yet | blocked | 8 m 34 s best; 11 m 53 s; 13 m 53 s (load 156) |
| Warm full `testStableDebugUnitTest` | no run yet | blocked | 2 m 17 s to 3 m 56 s (about 3 min is the tests) |
| `lintStableDebug` | no run yet | blocked | 2 m 48 s warm to 6 m 31 s fresh tree |
| Toolchain setup (JDK + Android SDK) | preinstalled | about 80 s (apt + sdkmanager), measured in run 170 | n/a |

## Why two columns are empty

1. **github.com:** the fork has never run a workflow. `ci.yml` fires only on
   `pull_request`; `debug.yml`, `play.yml`, `release.yml` are `workflow_dispatch`
   only; upstream PR runs from the fork sit at `action_required`. The first number
   will come from the next real PR's CI: then
   `scripts/ci-step-times github djbclark/plektra-djbclark RUN_ID`.
2. **forgejo.mit.edu:** the build gets as far as starting Gradle (checkout, JDK 17
   and Android SDK install work, about 80 s) and then fails with "Could not connect
   to the Gradle daemon": loopback TCP is refused inside the runner microVM. Draft
   report for SIPB: `sipb-loopback-report.md`. When fixed, push to branch
   `bench/mit-ci` (it carries `.forgejo/workflows/ci.yml`, the marker version in
   `forgejo-ci.yml`), then `scripts/ci-step-times forgejo djbclark/plektra-djbclark RUN_ID`.

## Confounds to state with any number

1. Local daemon is capped at `-XX:ActiveProcessorCount=2` and the Mac runs at
   load 12-175 on 8 cores; Gradle's printed time includes the machine-wide Gradle
   slot wait, so use the net-of-slot figure (one "1 h 11 m" run was 3 m 56 s of work).
2. Local uses JDK 21 and a local plus remote build cache; CI uses JDK 17 and, on
   GitHub, `cache: gradle` for dependencies only.
3. MIT job hardware is a shared 16-vCPU microVM; repeat runs for a spread.
