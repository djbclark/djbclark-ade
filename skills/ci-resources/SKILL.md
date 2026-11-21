---
name: ci-resources
description: >-
  Pick and operate every VM and CI resource on this machine: Apple container,
  tart VMs, Forgejo/Hyades CI, GitHub Actions, WarpBuild, and the local Linux
  gate scripts. Use when choosing where a heavy build or test runs, when a
  container apiserver or tart VM is down, when a route breaks after a container
  starts, or to confirm a run actually ran (not just exited 0). Do not use for
  the load/slot admission rules themselves; those are loadwatch.
---

# ci-resources — pick and operate a VM or CI runner

Operator request (2026-11-20). This page is the single place that says which
resource to pick for a heavy build, how to start and check each, the container
route trap, and how to confirm a run really ran.

## Pick first

| Need | Pick | Why |
| --- | --- | --- |
| Linux gate / root acceptance (CFEngine, ~2.5 min) | local Apple container `cfengine-build:u24-xml`, `--network none` | fork CI cannot run it; needs root + debug |
| macOS arm64 heavy build (bottle, desktop) | WarpBuild `warp-macos-26-arm64-6x` (if org+key set) else GitHub `macos-latest` | GitHub's arm64 Mac pool is the scarce one (see docs/ci-runners.md) |
| Linux x64 CI (general) | GitHub `ubuntu-latest` or WarpBuild `warp-ubuntu-2404-x64-4x` | fastest; no local load |
| MIT-hosted container site | Forgejo/Hyades (see the hyades-docker skill) | MIT hosting, not this Mac |
| Full VM (nested kernel, macOS VM) | tart VM | Apple Virtualization; do NOT run while a container is up |

Rule: heavy/full tests run CI-first, but a focused local run is still required
before any PR (bgrun, `load-watch ci decide DIR local`). CI is an extra gate,
never a substitute for the focused run.

## Apple container (the `container` CLI)

- Start the apiserver (it is not auto-started): `container system start`.
- Check: `container system status` must print `status running`; the line
  "apiserver is not running and not registered with launchd" means start it
  first. Nothing keeps it running across reboot — check before every gate.
- Never start a container while a tart VM is running (its bridge disappears and
  both lose network). `tart list` shows all VMs; all must be `stopped`.
- Network trap: a networked container gets DNS but no TCP while a Tailscale exit
  node with "Allow local network access" is on. After any networked container
  start, wait ~5 s and run `~/src/cfengine-all/linuxgate/fix-route.sh`. Gate
  lanes use `--network none` and need none of this.

## tart VMs

- `tart list` shows source, name, state. Only run one while no container is up.
- `tart run <name>` starts; the macOS VM harness has no CI equivalent (no
  Apple-Silicon nested virt), so CI-first cannot apply to it.

## The local Linux gate (CFEngine)

- `cd ~/src/cfengine-all` first (that directory has a recorded `local` CI
  decision); then `bgrun container run --rm --network none ...` per
  ~/src/cfengine-all/AGENTS.md "Linux gate".
- Output lands in `linuxgate/out/<sha>/`. A gate that fails to launch (XPC
  error) leaves the previous sha's output in place — check the log timestamp,
  not just the directory.

## Confirm a run really ran

- `bgrun` exit 0 does NOT prove the command ran. An `container run` XPC failure
  ("Connection invalid") can still exit 0. Confirm the artifact: for the gate,
  a fresh `linuxgate/out/<sha>/progress.log` or `acceptance.log` newer than the
  run start; for CI, the workflow run's `conclusion`, not just `status`.

## Starting a VM or container

Always: `tart list` first (no running VM) for a container; `container system
status` first for a tart VM. Do not start one over the other.

## References

- docs/ci-runners.md — runner label mapping and timings.
- ~/src/cfengine-all/AGENTS.md "Linux gate" — the gate commands and the route
  trap in full.
- ~/src/cfengine-all/docs/local-ci-containers-vs-tart.md — container vs tart.
