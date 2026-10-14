# Moved: https://forgejo.mit.edu/djbclark/loopback-port-shim

Everything that used to live in this directory (the libkrun TSI loopback shim, its probes, the Forgejo probe workflows and
tooling, the investigation notes and the SIPB and libkrun ticket texts) moved on 2026-10-14 to a public repository on
forgejo.mit.edu, MIT-licensed:

**https://forgejo.mit.edu/djbclark/loopback-port-shim** (local clone `~/src/loopback-port-shim`)

Edit it there. Tickets filed before the move (libkrun #818, #819, #860, #924, #926, #929, SIPB/hyades #2) link to files in this
directory; use the table below to find them. History before the move is in this repository's git log (every commit up to `530d417` still has the files; for example commit
`da6d68f` is the one the CI image's Dockerfile pins).

Still here: `local-timings.md` (Mac-side timings, not about the shim). The agent skill is `skills/forgejo-ci`, a symlink to
`~/src/loopback-port-shim/skills/forgejo-ci`.

| Old file here | Now in the new repo |
|---|---|
| `Sd3.java` | `ci/tools/Sd3.java` |
| `accept-probe.c` | `ci/tools/accept-probe.c` |
| `comparison.md` | `docs/comparison.md` |
| `derive-forgejo-ci.py` | `ci/tools/derive-forgejo-ci.py` |
| `disk-experiments.sh` | `ci/tools/disk-experiments.sh` |
| `disk-probe.py` | `ci/tools/disk-probe.py` |
| `dup-bind-probe.py` | `tests/dup-bind-probe.py` |
| `duplex-probe.c` | `tests/duplex-probe.c` |
| `forgejo-ci.yml` | regenerate with `ci/tools/derive-forgejo-ci.py` (`DERIVE_IMAGE=...` for our CI image) |
| `heartbeat.sh` | `ci/tools/heartbeat.sh` |
| `hyades-disk-research.md` | `docs/hyades-disk-research.md` |
| `java-churn/` | `tests/java-churn/` |
| `keepalive-repro.py` | `ci/tools/keepalive-repro.py` |
| `libkrun-819-comment.md` | `docs/tickets/libkrun-819-comment.md` |
| `libkrun-860-comment.md` | `docs/tickets/libkrun-860-comment.md` |
| `libkrun-926-comment.md` | `docs/tickets/libkrun-926-comment.md` |
| `libkrun-issue.md` | `docs/tickets/libkrun-issue.md` |
| `libkrun-stale-listener-issue.md` | `docs/tickets/libkrun-stale-listener-issue.md` |
| `libkrun-tsi-shutdown-issue.md` | `docs/tickets/libkrun-tsi-shutdown-issue.md` |
| `limits-probe.sh` | `ci/tools/limits-probe.sh` |
| `listener-churn-repro.py` | `ci/tools/listener-churn-repro.py` |
| `loopback-port-shim.c` | `loopback-port-shim.c` |
| `probe-accept.yml` | `ci/probes/probe-accept.yml` |
| `probe-churn.yml` | `ci/probes/probe-churn.yml` |
| `probe-containers.yml` | `ci/probes/probe-containers.yml` |
| `probe-curl-dax.yml` | `ci/probes/probe-curl-dax.yml` |
| `probe-disk.yml` | `ci/probes/probe-disk.yml` |
| `probe-dupbind.yml` | `ci/probes/probe-dupbind.yml` |
| `probe-duplex.yml` | `ci/probes/probe-duplex.yml` |
| `probe-javachurn.yml` | `ci/probes/probe-javachurn.yml` |
| `probe-keepalive.yml` | `ci/probes/probe-keepalive.yml` |
| `probe-labels.yml` | `ci/probes/probe-labels.yml` |
| `probe-loopback.yml` | `ci/probes/probe-loopback.yml` |
| `probe-ownimage.yml` | `ci/probes/probe-ownimage.yml` |
| `probe-resources.yml` | `ci/probes/probe-resources.yml` |
| `probe-reuse.yml` | `ci/probes/probe-reuse.yml` |
| `probe-shim.yml` | `ci/probes/probe-shim.yml` |
| `probe-shutdown.yml` | `ci/probes/probe-shutdown.yml` |
| `probe-shutdown2.yml` | `ci/probes/probe-shutdown2.yml` |
| `push-bench.sh` | `ci/tools/push-bench.sh` |
| `push-probe.sh` | `ci/tools/push-probe.sh` |
| `resource-probe.sh` | `ci/tools/resource-probe.sh` |
| `reuse-probe.c` | `tests/reuse-probe.c` |
| `run-matrix.sh` | `ci/tools/run-matrix.sh` |
| `shim-by-default.md` | `docs/shim-by-default.md` |
| `sipb-hyades-2-comment.md` | `docs/tickets/sipb-hyades-2-comment.md` |
| `sipb-hyades-2-comment2.md` | `docs/tickets/sipb-hyades-2-comment2.md` |
| `sipb-hyades-issue.md` | `docs/tickets/sipb-hyades-issue.md` |
| `sipb-hyades-shim-request-draft.md` | `docs/tickets/sipb-hyades-shim-request-draft.md` |
| `sipb-loopback-report.md` | `docs/sipb-loopback-report.md` |
| `wait-run.sh` | `ci/tools/wait-run.sh` |
