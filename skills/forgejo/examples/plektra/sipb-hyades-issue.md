<!-- Draft for https://forgejo.mit.edu/SIPB/hyades/issues . NOT POSTED. Title: "CI job root filesystem (libkrun virtiofs) is 4-30x slower than tmpfs for small-file work: data and suggestions" -->

## Summary

Jobs on the `sipbphus` runner (`ubuntu` label) are fast on CPU and RAM but slow on the root filesystem, which is libkrun's virtiofs. Android/Gradle builds, which are mostly small-file work, spend a large share of their time there. As suggested in chat, putting the workspace, Gradle home and SDK on a guest tmpfs works well: on the same commit the setup-plus-compile-plus-targeted-tests part of a job ran 1.2x faster on a tmpfs (compile 1.4x) and 1.4x faster on an ext4 image on a loop device (compile 1.5x) than on the root fs. This issue collects the numbers so that (1) the recipe can be documented for CI users and (2) you can decide whether a host-side change (a virtio-blk scratch disk, or libkrun virtiofs tuning) is worth it. The upstream libkrun side is in https://github.com/libkrun/libkrun/issues/924 (the cause is in libkrun's virtiofs server: one request queue, one worker thread, no writeback cache, and no API to change them).

I am not asking for anything urgent. Compile and the unit tests run; one hang and a few flaky loopback tests are described at the end. Measurements and text were prepared with an AI coding assistant (Claude Code) from CI logs; I reviewed the numbers.

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

## What it does to a real build (Plektra, an Android app: JDK 17, Android SDK, Gradle compile plus about 1,400 unit tests; same commit, three runs one after another)

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
4. **Loopback** (see the section below): jobs cannot listen on port 0 (libkrun#818) and cannot `shutdown()` a socket another thread is blocked on. We work around both with a small `LD_PRELOAD` shim loaded through `/etc/ld.so.preload`; it needs `gcc` in the job. A precompiled shim in the base image would save every user that, but fixing it in libkrun (or `krun.use_passt=1`) would remove the need for it.

## A test run that hangs, and flaky loopback tests

Related to the loopback bug I reported earlier (libkrun#818), but a different failure, and a worse one: **a test JVM hangs forever** and the job runs until its timeout (then the runner logs `context deadline exceeded ... podman.sock` while tearing the container down).

1. Cause: with libkrun's TSI networking, `shutdown(2)`, `getsockopt` and `getpeername` on a socket **block while another thread is blocked in `accept()` or `read()` on the same socket**. On a normal Linux kernel `shutdown()` on a listener wakes the blocked `accept()`. Java's `ServerSocket.close()` and `Socket.close()` call `shutdown()` first, so okhttp's MockWebServer (`MockWebServer.shutdown()`, `RealWebSocket.cancel()`) never returned and the Gradle test worker stopped, idle, with about 1,000 leftover threads. Thread dumps taken in the job show the worker in `sun.nio.ch.Net.shutdown` (native, runnable).
2. Minimal repro, run in any krun container (`bare` and `accepted_client` fail with ENOTCONN; `accept_blocked` never returns):

```python
import socket, threading, time
s = socket.socket(); s.bind(("127.0.0.1", 31337)); s.listen(5)
threading.Thread(target=lambda: s.accept(), daemon=True).start(); time.sleep(0.3)
s.shutdown(socket.SHUT_RDWR)   # hangs forever here
```

   Other wake-ups behave: `pthread_kill` interrupts a blocked `accept()` (EINTR), `dup2` over the fd plus a signal does too; `close()` alone and `shutdown(SHUT_RD)` do not. Probe workflows and results are in the repo linked below (`probe-shutdown*.yml`, `probe-accept.yml`).
3. Workaround: the same `LD_PRELOAD` shim now also wraps `listen`/`close`/`dup2`/`dup3` (to know which fds are listeners without asking the socket) and `shutdown()`, which becomes a no-op on listeners and otherwise runs in a helper thread with a 300 ms wait. With it the full suite (1,417 tests) completes: the test step takes about 3.5 minutes and the job about 12 minutes.
4. Still failing after that: six MockWebServer-based tests (`OpenAiLiveSpeechClientTest`, `SpeechApiClientTest`) fail with `unexpected end of stream` or timeouts, a different subset on different runs; they pass on a laptop and on GitHub's runners. They fail the same way with `shutdown()` turned into a no-op, so the shim is not the cause: the loopback data path is the suspect. I cannot tell more from inside the job.
5. Ask: either enable `krun.use_passt=1` for these jobs (I understand the nested-passt concern, and I would take any fix that makes loopback behave like a kernel loopback), or a TSI/libkrun fix. Upstream notes are in libkrun#924 and the repro above can be filed as its own libkrun issue if you prefer.


## Offer

I can run any benchmark or candidate configuration on the runner (the matrix script and probes are in https://github.com/djbclark/djbclark-ade/tree/master/skills/forgejo/examples/plektra).
