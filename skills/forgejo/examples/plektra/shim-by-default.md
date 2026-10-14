# Using the loopback shim on forgejo.mit.edu: options, risks, alternative images (2026-10-14)

Facts checked on 2026-10-14. "Verified" means a probe run on the runner (run numbers in brackets); "documented" means read in
upstream docs or SIPB's repos, not tested here; "untested" is a prediction.

## 1. How jobs run (SIPB/hyades `sipbphus/default.nix`, SIPB/ci-images)

1. One `forgejo-runner` instance, `capacity = 4`: up to 4 jobs at once, each in its own libkrun microVM started by rootless podman.
   Networking is the default TSI (no `krun.use_passt`), so the 4 VMs share the host's loopback port space (libkrun#860).
2. Labels `ubuntu`, `ubuntu-26.04`, `alpine`, `alpine-3.24`, `rocky`, `rocky-10` map to `forgejo.mit.edu/sipb/ci-images:<label>`
   (Dockerfile.ubuntu: ubuntu:26.04; Dockerfile.alpine: alpine:3.24, musl; Dockerfile.rocky: rockylinux 10). None has `gcc` or a JDK.
3. The runner never re-pulls an image once downloaded (documented; a weekly `podman-pull` timer refreshes `ci-images`).
   `container.force_pull` exists in the runner config (documented).
4. A workflow can replace the label's image per job with `jobs.<id>.container.image` (documented; verified, run 239).

## 2. The shim works the same on all three labels (verified, run 238)

Built from the same source with `gcc -shared -fPIC -O2 -pthread ... -ldl` on ubuntu (glibc 2.43), alpine (musl) and rocky (glibc 2.39).
On each: a port-0 listener is unreachable without it and reachable with it; `send()` stalls 3004 ms behind a parked `recv()` without it and
takes 1 ms with it; `reuse-probe` 20 of 20 with it against 1 to 2 of 10 without it.

## 3. Ways to make the shim available

| | How | Cost to SIPB | Per-job cost | Notes |
|---|---|---|---|---|
| A | Job builds it (today) | none | `apt-get install gcc` (about 30 s) + 1 s build | works everywhere, nothing to maintain |
| B | Precompiled `/usr/local/lib/portshim.so` in each ci-images Dockerfile, opt-in (`LD_PRELOAD=` or one line into `/etc/ld.so.preload`) | a build stage per image (glibc for ubuntu and rocky, musl for alpine) | about 0 | recommended ask |
| C | B plus `/etc/ld.so.preload` baked into the image | same | 0 | affects every process in every job on that label: see risks |
| D | Runner config: `runner.envs: LD_PRELOAD=...` plus a bind mount via `container.options` (needs the path in `container.valid_volumes`) | edit sipbphus/default.nix | 0 | global for all labels; documented keys, untested here |
| E | Our own image used with `container: image:` (no SIPB change at all) | none | 0 after the first pull | see section 5 |
| F | Fix libkrun's TSI driver (#818, #819, #860, #929): no shim needed | upstream work | 0 | the real fix |

## 4. Why not global (C, D) yet

1. **EINTR semantics (untested prediction).** The shim waits in `poll()` before blocking reads. A signal interrupts `poll()` even for a
   handler installed with `SA_RESTART`, where a plain `read()` would restart. A program that relies on `SA_RESTART` and does not retry
   `EINTR` could see spurious failures. The shim could track handler flags by wrapping `sigaction`, or restrict itself to JVMs, before
   it goes global.
2. **Go and other static binaries are not covered** (`LD_PRELOAD` only reaches dynamically linked libc users; Go uses raw syscalls).
   The images ship `golang`, `podman`, `buildah`, `hugo`: Go tests that listen on port 0 and connect over loopback still hit libkrun#818.
3. **Cross-job port sharing (#860, inference).** With capacity 4, two VMs picking the same port from the shim's 20000-32000 range both
   succeed at `listen()` and connections go to either. The shim could pick per-job sub-ranges (hash of the hostname) to make that unlikely.
4. **Overhead.** An `fcntl` and a `poll` per blocking read; negligible for tests, not measured for I/O-heavy jobs.

## 5. Alternative job images (verified, run 239; both ran the shim fine)

| Image | Pull | Has | Lacks | Verdict |
|---|---|---|---|---|
| stock `ubuntu` label | cached | git, curl, python3, podman, nix, go, cargo | gcc, JDK, Android SDK | today's baseline: the job installs JDK + SDK (69 s) + gcc |
| `ghcr.io/cirruslabs/android-sdk:36` (1.1 GB compressed, Ubuntu 24.04) | 47 s once, cached afterwards | **Android platform 36, build-tools 36.0.0, sdkmanager**, JDK **21**, gcc, git, python3, curl, unzip | `node` (so `actions/checkout`, a node action, cannot run in it; clone with git instead), JDK 17 | removes the 69 s install; needs JDK 17 for Plektra (install `openjdk-17` or build our own) |
| `docker.io/library/eclipse-temurin:17-jdk-noble` (200 MB) | 12 s | JDK 17 | gcc (29 s to install), git, python3, unzip, SDK, node | saves nothing over the stock image |
| `docker.io/mingc/android-build-box` | 5.9 GB | everything Android | | too big |

**Best alternative: our own image** `FROM ghcr.io/cirruslabs/android-sdk:36` (or the stock ubuntu image) plus `openjdk-17-jdk-headless`, `nodejs`,
and the precompiled shim at `/usr/local/lib/portshim.so` (preloaded only where wanted), published to a registry the runner can pull from
(forgejo.mit.edu's package registry, if enabled for our user, or ghcr.io) and pinned by digest as the Forgejo docs recommend. A job would then
start with JDK, SDK and shim ready and spend about 0 s on setup. Not built yet.

## 6. Recommendation

1. Now: keep A in the derived workflows; build our own image (E) for Plektra if the 70 to 100 s per job matters.
2. Ask SIPB for B only (precompiled `.so` in each image, opt-in), with the evidence and libkrun links; say plainly that C and D are not
   requested until the risks in section 4 are handled, and that the real fix is F.
3. Before any global use: handle `SA_RESTART`, per-job port ranges, and test a Go binary and a musl static binary.
