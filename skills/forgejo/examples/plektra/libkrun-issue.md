## Summary

With a virtiofs root (crun-krun / `krun_add_virtiofs2(ctx, "/dev/root", "/", ...)`), file-metadata operations in the guest are 10-30x slower than in-guest tmpfs, and writes are write-through (the same speed with and without `fsync`). From the code, the virtiofs device has one request queue, one worker thread and `writeback: false` with no way to change any of them through the C API. We hit this running CI builds (Android/Gradle) on SIPB's Hyades runner; builds are dominated by small-file work, so the root filesystem is the bottleneck. Related reports below (#655, #667, #414) point the same way. I am asking whether this is intended and what direction would be accepted; I can test patches on this setup.

Measurements and write-up were prepared with an AI coding assistant (Claude Code) from the CI job logs; I reviewed the numbers.

## Setup

1. Forgejo Runner + rootless Podman + `crun` with the krun handler (`engine.runtime = "krun"`); the SIPB forks of libkrun ("2.0-sipb", rev `bd369ebb4fb2`) and crun do not touch the fs code as far as I can tell. Config: https://forgejo.mit.edu/SIPB/hyades (see `overlays.nix`, `sipbphus/default.nix`).
2. Guest: libkrunfw kernel 6.12.91, 16 vCPU (AMD EPYC, KVM), 62.8 GiB RAM (`krun.ram_mib=65536`), job runs as root.
3. `/proc/self/mountinfo`: `virtiofs /dev/root / rw,relatime` (no `dax`), although the kernel log reports `virtiofs virtio3: Cache len: 0x20000000` (a 512 MiB DAX window exists). `rootfstype=virtiofs rw quiet no-kvmapf init=/init.krun`. `/dev/shm` is a guest tmpfs.
4. I have not re-run this outside the Hyades runner, so I cannot say how much depends on the host's backing store. The numbers below come from one job; a 2-pass repeat varied by under 5 percent.

## Measurements (same script on each filesystem, 5000 files of 4 KiB, 1 GiB sequential)

| | virtiofs root | ext4 on a loop device whose image file sits on that virtiofs | in-guest tmpfs |
|---|---|---|---|
| create 4 KiB files / s | 1,621 | 27,687 | 64,161 |
| stat / s | 13,078 | 352,878 | 345,908 |
| open+read / s | 4,170 | 120,726 | 112,522 |
| unlink / s | 4,646 | 59,168 | 154,056 |
| sequential write, no fsync (MiB/s) | 189 | 855 | 1,878 |
| sequential write, fsync at end (MiB/s) | 178 | 133 | 1,316 |
| sequential read (MiB/s) | 824 | 7,169 | 4,941 |

1. Write throughput does not depend on `fsync` on virtiofs (189 vs 178 MiB/s): consistent with write-through, no guest write coalescing.
2. fio on virtiofs (buffered, psync, 4 jobs): random 4k read 51,946 IOPS (75 us), random 4k write 50,426 IOPS (78 us), 4k write plus fsync 1,063 IOPS (148 us). Cold random 4k reads through the loop device are worse (10,169 IOPS), so a loop image is no free lunch for read-heavy cold data.
3. 16 processes in parallel on virtiofs: 108,751 stat/s (about 8x one process), 9,916 creates/s: latency-bound rather than saturated.
4. Realistic: unzip of a 137 MB zip 2.79 s vs 1.31 s on loop-ext4; extracting a 120 MB repo tarball 3.59 s vs 0.29 s; `git status` 0.84 s vs 0.43 s; `rm -rf` 0.75 s vs 0.26 s.

Repro (run inside any krun container; compare `/tmp` on virtiofs with `/dev/shm`):

```python
import os, sys, time
d = sys.argv[1]; os.makedirs(d, exist_ok=True); n = 5000; body = b"x" * 4096
ps = [f"{d}/f{i}" for i in range(n)]
def t(f):
    a = time.perf_counter(); f(); return n / (time.perf_counter() - a)
def create():
    for p in ps: open(p, "wb").write(body)
print("create/s", int(t(create)))
print("stat/s", int(t(lambda: [os.stat(p) for p in ps])))
print("open+read/s", int(t(lambda: [open(p, "rb").read() for p in ps])))
print("unlink/s", int(t(lambda: [os.unlink(p) for p in ps])))
buf = os.urandom(1 << 20)
for sync in (False, True):
    a = time.perf_counter()
    with open(f"{d}/big", "wb") as f:
        for _ in range(1024): f.write(buf)
        f.flush()
        if sync: os.fsync(f.fileno())
    print("write MiB/s fsync=%s" % sync, int(1024 / (time.perf_counter() - a))); os.unlink(f"{d}/big")
```

## What I found in the code (main, v1.19.6)

1. `src/devices/src/virtio/fs/device.rs`: `config.num_request_queues = 1;` and the `passthrough::Config` is built with `..Default::default()` (only `root_dir`, `semantics` and `attr_timeout` are set).
2. `src/devices/src/virtio/fs/linux/passthrough.rs`: the defaults are `cache_policy: Default::default()` (Auto) and `writeback: false`; the field documentation says writeback "can improve performance as it allows the FUSE client to cache and coalesce multiple writes" when the host has exclusive access to the directory.
3. `src/devices/src/virtio/fs/worker.rs`: `FsWorker::run` spawns a single thread that serves all queues.
4. No setter for any of these in the libkrun C API (`krun_add_virtiofs2`..`4` take tag, path, DAX window size and permission semantics). I may well have missed something; please correct me.

For a private, disposable root filesystem (every CI job's container rootfs), the exclusive-access condition for writeback holds, so this looks like a reasonable thing to offer as an option.

## Questions

1. Are one queue, one worker thread and `writeback: false` intentional defaults for the Linux passthrough backend, or just where it started?
2. Would you accept an API to set `writeback` and `cache_policy` for a virtiofs device (for example through an extension of `krun_add_virtiofs4`), and, separately, a multi-queue or worker-pool server? I can prototype the first and benchmark on this setup.
3. For CI-style workloads (many small files), is a virtio-blk root the recommended answer? #655 suggests it is (maintainer comment, 2026-05-04), but crun has no annotation to attach a disk outside the SEV variant (see #667 item 4).

## Related

1. #655 (closed): `make -j16` 11.22 s on virtiofs root vs 6.05 s on libvirt; same speed with virtio-blk root.
2. #667 (open): CI runner use case, asks for a block device key in `.krun_vm.json`.
3. #414 (open): podman build performance versus vfkit, attributed to virtio-fs mounts.
4. #824 (open): virtio-blk services one request at a time per disk.
5. #515 and containers/crun#1952: `--tmpfs` under crun-krun is host-side and goes through virtiofs; only `/dev/shm` is a guest tmpfs.
6. SIPB's Hyades README TODO lists "virtiofs performance tweaks (or just use tmpfs?)".
