<!-- Draft for https://forgejo.mit.edu/SIPB/hyades/issues . NOT POSTED. Title: "CI job root filesystem (libkrun virtiofs) is 4-30x slower than tmpfs for small-file work: data and suggestions" -->

## Summary

Jobs on the `sipbphus` runner (`ubuntu` label) are fast on CPU and RAM but slow on the root filesystem, which is libkrun's virtiofs. Android/Gradle builds, which are mostly small-file work, spend a large share of their time there. As suggested in chat, putting the workspace, Gradle home and SDK on a guest tmpfs works well: on the same commit the setup-plus-compile-plus-targeted-tests part of a job ran 1.2x faster on a tmpfs (compile 1.4x) and 1.4x faster on an ext4 image on a loop device (compile 1.5x) than on the root fs. This issue collects the numbers so that (1) the recipe can be documented for CI users and (2) you can decide whether a host-side change (a virtio-blk scratch disk, or libkrun virtiofs tuning) is worth it. The upstream libkrun side is in https://github.com/libkrun/libkrun/issues/924 (the cause is in libkrun's virtiofs server: one request queue, one worker thread, no writeback cache, and no API to change them).

I am not asking for anything urgent. Our builds work. Measurements and text were prepared with an AI coding assistant (Claude Code) from CI logs; I reviewed the numbers.

## What a job gets (measured in a job; the local machine is an M1 MacBook Air)

| | CI job | M1 Air | CI relative to Air |
|---|---|---|---|
| CPU | 16 vCPU, AMD EPYC 3.0 GHz, steal 0.01% | 8 cores (4 perf + 4 eff) | 2.0x cores |
| all-thread compute | | | 2.6x |
| one-thread compute | | | 0.85x |
| RAM | 62.8 GiB, no cgroup limit | 16 GiB | 3.9x |
| memory copy, one thread / all threads | | | 0.42x / 2.2x |
| disk free | 902 GiB (virtiofs root) | 83 GiB | 10.9x |
| disk, create / stat / open+read / unlink (small files) | | | 0.14x / 0.034x / 0.075x / 0.23x |
| disk, sequential write / read | | | 0.072x / 0.17x |

No CPU, memory or pids cgroup limits are visible. Soft `nofile` 1024 (hard 4096), `pid_max` 16384, inotify instances 128: Gradle and Android tooling worked within them.

## The filesystem

`/proc/self/mountinfo`: `virtiofs /dev/root / rw,relatime`, kernel cmdline `rootfstype=virtiofs ... init=/init.krun`. Same script on three filesystems, 5000 files of 4 KiB and 1 GiB sequential (repro script in libkrun#924):

| | virtiofs root | ext4 on a loop device (image file on the root) | in-guest tmpfs |
|---|---|---|---|
| create 4 KiB files / s | 1,621 | 27,687 | 64,161 |
| stat / s | 13,078 | 352,878 | 345,908 |
| open+read / s | 4,170 | 120,726 | 112,522 |
| unlink / s | 4,646 | 59,168 | 154,056 |
| sequential write MiB/s (no fsync / fsync) | 189 / 178 | 855 / 133 | 1,878 / 1,316 |

Writes on virtiofs run at the same speed with and without `fsync`, so they are write-through. It is not the physical disks: a 1 GiB sequential read gets 824 MiB/s, and the metadata path is latency-bound (16 parallel processes reach about 8x the single-process stat rate).

## What it does to a real build (Plektra, an Android app: JDK 17, Android SDK, Gradle compile plus 1,251 unit tests, run locally; same commit, three runs one after another)

| step (seconds) | root fs (as-is) | guest tmpfs | ext4 loop image |
|---|---|---|---|
| install JDK and SDK (apt, unzip, sdkmanager) | 69.3 | 49.1 | 44.9 |
| Gradle compile | 276.4 | 202.8 | 182.7 |
| four targeted test steps, summed | 112.0 | 138.6 | 88.8 |
| total of the above | 458 | 393 | 324 |

1. The jobs ran next to other jobs on a shared host, so treat differences under about 20% as noise; tmpfs came out slower than the loop image on the test steps, which I cannot explain.
2. Space and memory the build actually used: workspace 300 MiB, Gradle home 1.7 GiB, Android SDK 600 MiB, 2.6 GiB in total, peak RAM in use 11.7 GiB. A 48 GiB tmpfs (`mount -t tmpfs -o size=48g`) is far more than this needs; 8 GiB would do for this project.
3. `/dev/shm` is 32 GiB and `noexec` (Android build tools must execute), and `--tmpfs` under crun-krun is host-side (it still goes through virtiofs: libkrun#515, crun#1952). A fresh `mount -t tmpfs` inside the job works because jobs run as root.

## Suggestions, cheapest first

1. **Document the recipe** in `ci-images` or the README: `mount -t tmpfs -o size=Ng tmpfs /mnt/fast`, then put the checkout, `~/.gradle`, `~/.npm`, build output there. A working example is in our workflow: [link to workflow in the test repo, or paste]. Optionally a `/usr/local/bin/fast-scratch` helper in the base image so jobs do not each write it.
2. **A virtio-blk scratch disk** (an SSD or an image on one) would help only if it is exposed to the VM as virtio-blk: libkrun maintainers say a virtio-blk root gets near parity with QEMU (libkrun#655, 2026-05-04: the same build took 11.2 s on virtiofs and 6.0 s with a virtio-blk root; with a virtio-blk root it matched libvirt). Today crun has no annotation to attach a disk outside the SEV variant (libkrun#667 item 4), so this needs a crun/runner change, not just hardware. A host SSD under `/tmp` exposed through virtiofs would still be write-through and single-threaded, so it would not help much by itself.
3. **libkrun virtiofs tuning** (writeback cache, more request queues or workers) would speed up every job without any workflow change, but it is an upstream change; see libkrun#924 where I ask whether they would accept it and offer to test patches here. Mounting with `dax` may also help; I have not tried it.
4. **Loopback bug note** (libkrun#818, which I reported earlier): jobs also cannot listen on port 0 and connect to it. We work around it with a small `LD_PRELOAD` shim loaded through `/etc/ld.so.preload`; it needs `gcc` in the job. If `krun.use_passt=1` is not wanted, a `gcc`-free fix would be a precompiled shim in the base image.

## A build step that hangs

TODO_HANG_SECTION

## Offer

I can run any benchmark or candidate configuration on the runner (the matrix script and probes are in https://github.com/djbclark/djbclark-ade/tree/master/skills/forgejo/examples/plektra).
