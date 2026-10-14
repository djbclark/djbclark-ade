<!-- Research by a sub-agent, 2026-10-13; [V]=verified in source, [I]=inferred, [?]=unknown. Sources inline. -->

# SIPB Hyades CI runner: virtiofs disk speed research (2026-10-13)

Legend: [V] = verified by reading the cited source text; [I] = inferred (reasoning from verified facts, not stated by a source); [?] = could not confirm.
All code was read from raw files fetched 2026-10-13. Commit pins: sipb/libkrun `bd369ebb4fb2...` and sipb/crun `391b866dd41b...` are the exact revs the Hyades flake uses (see 1.3).

## Summary (read this first)

1. [V] The CI runner ("sipbphus") is Podman (rootless, user `gitea-runner`) + a SIPB fork of crun with the libkrun handler (`engine.runtime = "krun"`) + a SIPB fork of libkrun + libkrunfw 5.6.2 with a Linux 6.12.109 kernel. Each job container is a libkrun microVM whose root filesystem is ONE virtiofs device (tag `/dev/root`, host path = the container rootfs), mounted by the kernel with `rootfstype=virtiofs rw`.
2. [V] The libkrun virtiofs server (in the SIPB fork) is hardwired to: 1 request queue, 1 worker thread, `writeback = false`, cache policy `Auto`, none of which is exposed through the libkrun C API, crun annotations, or `.krun_vm.json`. This explains write-through (177 MiB/s with or without fsync) and a low small-file op rate. [V] for the code; [I] that it fully explains your numbers.
3. [V] SIPB's own README TODO already lists "virtiofs performance tweaks (or just use tmpfs?)" and "CI caching". So the ticket should be framed as "here are measurements and concrete knobs for an item already on your TODO".
4. [V] There is NO crun annotation or `.krun_vm.json` key that attaches a virtio-blk disk (only the SEV flavor calls `krun_set_root_disk`). libkrun itself supports it (`krun_add_disk/2/3`). SIPB already maintains forks of both crun and libkrun, so adding it is feasible but is real work.
5. [V] Important gotcha: under crun-krun, `podman --tmpfs /x` and tmpfs-type mounts are NOT guest tmpfs; they are set up on the host and exported through the same virtiofs (crun issue #1952). Only `/dev/shm` (mounted by the guest init) is a true guest tmpfs. Your "tmpfs ~30x faster" result is `/dev/shm`.
6. Published numbers: your numbers are in the normal range for virtiofs (see item 4), but 10-30x slower than native/tmpfs on metadata ops is also what upstream says to expect, and virtio-blk root removes the gap (libkrun #655).

---

## Item 1. How the Hyades CI runner is built

### 1.1 Repos and component list [V]
Source: https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/README.md (fetched; repo page https://forgejo.mit.edu/SIPB/hyades is public, 103 commits, last 2026-10-12).

Quotes:
- "Hyades runs workloads as [libkrun](https://github.com/libkrun/libkrun) microVMs, which combine the security of VMs with the low overhead of containers."
- "Hyades consists of four components: 1. hyades: A very large server for running the microVMs ... 2. forgejo: A container registry server (currently forgejo.mit.edu) 3. sipbphus: A CI server using the Forgejo Runner 4. A server for disk backups, currently on the Proxmox cluster."
- "The Hyades console translates this into Quadlet which systemd then translates into service units."
- TODO list: "- CI caching", "- **virtiofs performance tweaks (or just use tmpfs?)**", "- Upstream the crun and libkrun patches".
- Hosting of Forgejo itself: README only says forgejo is "A container registry server (currently forgejo.mit.edu)" as a separate component from "hyades: A very large server for running the microVMs". [?] No file in the repo says the Forgejo instance (Forgejo 16.0.5 per the ci-images page footer) runs ON hyades.mit.edu; the CI runner host is a separate machine (sipbphus, 18.4.60.85) from the Hyades host (18.4.60.84). [I] Forgejo is therefore probably its own deployment; ask SIPB.
- `docs/inessential.md` (https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/docs/inessential.md) section "Building an app using the Forgejo CI" shows `runs-on: ubuntu`. Its tech background says Hyades "does *not* use containers" but microVMs from OCI images.

### 1.2 Runner host config [V]
Source: https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/sipbphus/default.nix and /configuration.nix

- Runner: `services.gitea-actions-runner` with `package = pkgs.forgejo-runner`, instance `sipbphus`, `capacity = 4` (four concurrent jobs), labels `ubuntu, ubuntu-26.04, alpine, alpine-3.24, rocky, rocky-10`, each `docker://forgejo.mit.edu/sipb/ci-images:<label>`.
- Runtime flags/annotations: `virtualisation.containers.containersConf.settings.containers.annotations = [ "krun.ram_mib=65536" ];` (only RAM is set; no `krun.cpus`, no `krun.use_passt`). Matches your 62.8 GiB guest.
- crun default for vCPUs when `krun.cpus` unset: min(host affinity CPU count, 16): crun `krun.c` has `#define LIBKRUN_MAX_VCPUS 16` and the `cpus <= 0` branch uses `MIN (CPU_COUNT (&set), LIBKRUN_MAX_VCPUS)` [V] (https://raw.githubusercontent.com/sipb/crun/391b866dd41b2aac93ced07975fb210fa26982af/src/libcrun/handlers/krun.c). So your 16 vCPU is that cap [V]; libkrunfw x86_64 is built with `CONFIG_NR_CPUS=16` [V] (https://raw.githubusercontent.com/containers/libkrunfw/v5.6.2/config-libkrunfw_x86_64 line 363).
- Podman runtime: `configuration.nix` (https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/configuration.nix): "# Use the libkrun microVM runtime instead of crun" `engine.runtime = "krun";` and `network.pasta_options = [ "-4" ]`. So networking is pasta/TSI via podman, not `krun.use_passt`. [V]
- Rootless: `users.users.gitea-runner ... isNormalUser = true; linger = true; uid = 1001` and `DOCKER_HOST=unix:///run/user/1001/podman/podman.sock` ("rootless Podman"). [V] The runner talks to rootless Podman through the Docker-compat socket.
- `cache = { enabled = true; proxy_port = 4000; actions_cache_url_override = "http://host.containers.internal:4000"; }`: actions/cache is served by the runner on the host. [V]
- A weekly `podman pull forgejo.mit.edu/sipb/ci-images --all-tags` timer. [V]

### 1.3 SIPB forks of crun, libkrun, libkrunfw [V]
Source: https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/overlays.nix
- `libkrunfw` 5.6.2 with `kernelSrc = linux-6.12.109.tar.xz` and Landlock enabled (your guest reports libkrunfw kernel 6.12.91 in the job; the flake pins 6.12.109, so the runner may not yet be on the latest flake: [I] not important).
- `libkrun` "2.0-sipb" from github.com/sipb/libkrun rev `bd369ebb4fb263d1ce281c09d1981caf6141c79a`; `crun` "1.30.1-sipb" from github.com/sipb/crun rev `391b866dd41b2aac93ced07975fb210fa26982af`.
- What the forks change (GitHub compare API, commit titles): sipb/libkrun: "vsock SSH server", "Special handler for podman stop", "Set timeout for send()...", "Make sendmsg add to pending_tx...", "Run tiny SSH server in separate thread...", "Disable inactivity_timeout...", "Prevent EventSet::OUT from being unset to fix rsync stalls". sipb/crun: "Support libkrun 2.0", "Connect to vsock SSH server", "Support podman stop via a custom kill handler", "Ugly hack to wait until SSH server is up". [V] None touch virtiofs/fs code (I diffed the virtiofs files at the sipb rev: same single-queue/writeback=false code as upstream). So virtiofs tuning is untouched by SIPB today.

### 1.4 How the VM rootfs is provided [V]
Source: sipb/crun `src/libcrun/handlers/krun.c` at the pinned rev (https://raw.githubusercontent.com/sipb/crun/391b866dd41b2aac93ced07975fb210fa26982af/src/libcrun/handlers/krun.c):

```
// Default to a conservative DAX size of 512MB, just like krun_set_root() does.
uint64_t virtiofs_shm_size = 512 * 1024 * 1024ULL;
...
if (virtiofs_tag == NULL) virtiofs_tag = "/dev/root";
ret = krun_add_virtiofs2 (ctx_id, virtiofs_tag, "/", virtiofs_shm_size);
```
crun runs inside the container's mount namespace, so "/" is the container rootfs, i.e. whatever Podman assembled (overlay of image layers + bind-mounted volumes). [I] Therefore the job workspace (a Podman volume/bind mount) is also under that single virtiofs share, not a separate device.
Guest kernel command line (sipb/libkrun `src/vmm/src/vmm_config/kernel_cmdline.rs`, lines 8-11 of the default cmdline): `rootfstype=virtiofs rw quiet no-kvmapf`. [V] Matches your /proc/cmdline. No `rootflags=`, so no `dax` mount option. Kernel 6.12 virtiofs default DAX mode is not "always" (`fs/fuse/virtio_fs.c`: bare `dax` option => `FUSE_DAX_ALWAYS`; otherwise default) [V for the option parsing, I for "DAX effectively unused for root"]; verify in guest with `grep ' / ' /proc/mounts` (look for `dax`).

### 1.5 Where the host stores container data [partly V, partly I]
- Runner host sipbphus (https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/sipbphus/hardware-configuration.nix): `fileSystems."/" = { device = "/dev/disk/by-uuid/0d0bd1a1-...; fsType = "btrfs"; }`; initrd modules include `nvme` and `ahci`/`sd_mod`; AMD (`kvm-amd`); two mirrored EFI boot disks (`/boot`, `/boot1`) [V]. The rootless Podman storage is under `/var/lib/gitea-runner/.local/share/containers/storage` (home `/var/lib/gitea-runner`) on that btrfs root [I: default rootless graphroot; no storage.conf override seen in the repo]. Disk type of the root device (NVMe vs SATA SSD) is [?] not stated; `nvme` in `availableKernelModules` is suggestive only.
- Hyades main server (not the CI host): `fileSystems."/"` btrfs on `/dev/disk/by-id/wwn-0x5002538f55419343-part2` (WWN = SATA SSD style IDs, two disks in `boot.loader.grub.devices`), mount option `compress=zstd` [V]. `hyades/console.py` creates `~/.local/share/containers/storage/overlay` as a separate btrfs subvolume "to exclude them from backups". [V]
- `boot.tmp.useTmpfs = true` on both ("We have plenty of RAM for this") [V].
- Host RAM, CPU count and the real disk model of sipbphus: [?] not in the repos. Ask SIPB.

### 1.6 The ci-images repo [V]
Source: https://forgejo.mit.edu/SIPB/ci-images (Dockerfile.ubuntu/.alpine/.rocky, `.forgejo/workflows`, built weekly and pushed to the Forgejo registry; "All checks were successful ... Successful in 9m56s"). Not read in depth; no `.krun_vm.json` file was listed in the repo root (file listing via API: `.forgejo, Dockerfile.alpine, Dockerfile.rocky, Dockerfile.ubuntu, LICENSE`). [V] So `virtiofs_shm_size`/`virtiofs_tag` have never been customized per image.

---

## Item 2. libkrun / crun-krun options that affect virtiofs performance

### 2.1 Exact settings that exist
1. DAX window size: [V] crun reads `virtiofs_shm_size` (integer, bytes, default 512 MiB) and `virtiofs_tag` from `.krun_vm.json` at the ROOT OF THE IMAGE, not from an annotation. Source: crun `krun.1.md` (https://raw.githubusercontent.com/containers/crun/main/krun.1.md): "**virtiofs_shm_size** (integer): VirtioFS DAX shared memory size in bytes (defaults to 512 MiB)." and "Consider using virtio-fs optimization options in a **.krun_vm.json** file" (under "Performance issues"). The page also says the file "can be placed at the root of the container image" and "OCI annotations take precedence"; only `cpus`, `ram_mib` and the custom-kernel keys are also annotations. Added by crun PR #2076 (merged 2026-04-24, "krun: allow configuring the virtiofs device") https://github.com/containers/crun/pull/2076. libkrun API: `krun_add_virtiofs2(ctx, tag, path, shm_size)`: "shm_size - size of the DAX SHM window in bytes." (libkrun v1.19.6 `include/libkrun.h`). Whether the window helps a root mounted without `dax` is [?]/[I: probably no effect]; upstream virtio-fs RFC data say DAX mostly helps mmap, not small-file creates (see item 4.2).
2. Cache mode / writeback cache / thread pool / queue count: [V] NOT configurable through any public interface. In libkrun (upstream v1.19.6 and the sipb rev) `src/devices/src/virtio/fs/device.rs`:
   - `config.num_request_queues = 1;` (line 77)
   - `let fs_cfg = shared_dir.map(|root_dir| passthrough::Config { root_dir, semantics, attr_timeout, ..Default::default() });` (lines 87-91)
   - In `linux/passthrough.rs` the defaults are `cache_policy: Default::default()` (= `CachePolicy::Auto`), `writeback: false`, `entry_timeout: 5 s`, `attr_timeout: 5 s`. The struct fields exist (`pub cache_policy`, `pub writeback`) and the doc comment says writeback "can improve performance as it allows the FUSE client to cache and coalesce multiple writes ... callers should only enable this option when they can guarantee that: 1) the file system has exclusive access to the directory and 2) the file system has read permissions for all files in that directory." So the code supports it; there is simply no setter in the C header [V] (I grepped `libkrun.h` v1.19.6 and main: no cache/writeback/queue/thread knob on virtiofs).
   - `fs/worker.rs` (`FsWorker::run` spawns one `thread::Builder`... `.spawn(|| self.work())`, one worker serving all queues) [V]. So all virtiofs requests of a microVM (rootfs + workspace + node_modules + ...) are serviced by one host thread.
   - [I] Consequence: `writeback=false` means the guest page cache is write-through: every write() becomes a FUSE WRITE round trip; this matches your "177 MiB/s with or without fsync". One worker thread also caps parallel metadata ops (16 vCPUs share one server thread).
3. Is write-through a libkrun limitation? [V] It is libkrun's default (hard-coded `writeback: false`), not a protocol limitation; virtiofsd (QEMU) has an option for it. Upstream 2019 kernel patch text: "If writeback is enabled, then writes may be cached in the guest until the file is closed or an fsync(2) performed." (https://lkml.iu.edu/hypermail/linux/kernel/1908.2/05325.html summary; and QEMU virtiofsd docs https://qemu.googlesource.com/qemu/+/4301acd7d7d455792ea873ced75c0b5d653618b1/docs/tools/virtiofsd.rst for `--cache=always`, `--thread-pool-size` "Restrict the number of worker threads per request queue to NUM. The default is 64.", which libkrun does not have.)
4. Guest kernel supports it: [V] libkrunfw `config-libkrunfw_x86_64` has `CONFIG_FUSE_FS=y`, `CONFIG_VIRTIO_FS=y`, `CONFIG_FUSE_DAX=y`, `CONFIG_VIRTIO_BLK=y`, `CONFIG_OVERLAY_FS=y`.

### 2.2 Known issues in libkrun (GitHub), all fetched via the GitHub API
1. https://github.com/libkrun/libkrun/issues/655 (closed 2026-05-19) "poorer performance than a VM created by libvirt": `make -j 16` of crun: libvirt VM 6.05 s vs krun (virtiofs root) 11.22 s elapsed (System time 2.71 s vs 16.65 s); "Moving the source code on a tmpfs does not affect the Elapsed time" (because tmpfs is host-side, see 2.3). Maintainer slp (2026-05-04): "I've set up two instances, one with QEMU/KVM and the other with libkrun/KVM, but both with virtio-blk as root and the same kernel. With them, I'm getting roughly the same numbers on both ... the main suspect being using virtio-fs as root". [V] Direct upstream confirmation that virtiofs root is the cost and that virtio-blk root removes it.
2. https://github.com/libkrun/libkrun/issues/414 (open) "Investigate podman build performance versus vfkit": libkrun 12.62 s vs applehv 9.99 s after a fix; jakecorrenti (2025-10-23): "This issue is still present even after #428. It appears to be related to mounted directories with virtio-fs". [V]
3. https://github.com/libkrun/libkrun/issues/667 (open, 2026-05-06) "GitLab CI runner use case/RFE(s)": same use case as yours (CI runners using podman + krun). Requests "4. The krun_vm.json file should include a way to specify a block device the VM should use"; a later comment (2026-10-07) says "I/O performance better than virtiofs" and points to `krun_add_disk3()`. slp: "most of those changes need to happen in podman/crun". [V] Not implemented as of 2026-10-13 (no such key in `krun.1.md`).
4. https://github.com/libkrun/libkrun/issues/824 (open) "virtio-blk services one request at a time per disk, so guest I/O cannot scale beyond a single host thread"; related #864/#865 (parallel reads PRs). [V] So a virtio-blk disk is better for metadata/seq but is not multi-queue either; fine for per-job use.
5. https://github.com/libkrun/libkrun/issues/505 "virtiofs/PassthroughFs can open too many file descriptors" (open): possible secondary limit under many-small-file workloads. [V title only]
6. I found NO libkrun issue titled specifically about small-file create/write throughput or about exposing writeback/queues/threads (searched titles: virtiofs, performance, slow, writeback, DAX, fsync, threads, multiqueue). [V search; absence is not proof]

### 2.3 podman/crun facts that matter for mitigations
- crun issue #1952 (open) https://github.com/containers/crun/issues/1952: output of `podman --runtime=krun run --tmpfs /test ... mount` shows `/dev/root on / type virtiofs (rw,relatime)` and only `tmpfs on /dev/shm type tmpfs`; reporter: "the tmpfs seems to be handled by host (my guess, setup a rootfs structure with the tmpfs on host and pass the tree as a whole with virtfs) But this causes a performance loss (tmpfs now needs to go through the VMM and host not guest internal)". Tracked in libkrun #515. [V] (reporter's "guess" is a guess; consistent with #655 where "Moving the source code on a tmpfs does not affect the Elapsed time".)
- libkrun init (sipb rev `init/src/fs.rs`) mounts `tmpfs` on `/dev/shm` itself in the guest: `mount_or_busy(Some("tmpfs"), "/dev/shm", Some("tmpfs"), base_flags)` with no size option (=> half of guest RAM: your 32 GiB of 62.8 GiB). [V code; I for the size reasoning]
- crun PR #2273 (open) "Add configuration for additional virtiofs devices" through `.krun_vm.json` / annotation `krun.virtiofs`: more virtiofs devices, still virtiofs. [V]

---

## Item 3. Infrastructure-level mitigations and what each needs

| # | Mitigation | What it needs | Status of support |
|---|---|---|---|
| 3.1 | Job-side: put scratch (build dirs, node_modules, caches, TMPDIR) in `/dev/shm` or a guest-mounted tmpfs | Nothing in infra. `/dev/shm` is guest tmpfs [V]. A `mount -t tmpfs` done inside the guest by a root job step is guest-internal [I: needs root + CAP_SYS_ADMIN in the guest; your measurement context should confirm]. | Works today. Costs guest RAM (`krun.ram_mib=65536`, capacity 4). |
| 3.2 | `podman run --tmpfs` / `type=tmpfs` volumes at /tmp or /workspace | Config only | [V] NOT guest-internal under crun-krun (crun #1952); do not expect speedup. |
| 3.3 | Fast host dir (NVMe) as a Podman volume at /workspace or /tmp | Config only (runner `container.options`/`valid_volumes`, or containers.conf `volumes`) | Still served through the same virtiofs share and single worker thread [I from krun.c: only one virtiofs device is added, root "/"]; only improves the backing store (btrfs->NVMe/ext4/xfs), which matters only if the host side is the bottleneck. Measure host-native speeds of the same ops first (they were not provided). |
| 3.4 | Host backing store: move rootless Podman graphroot/volumes off btrfs (CoW, optional compression) to ext4/xfs on NVMe, or `chattr +C` | host `storage.conf`/NixOS | [I] sipbphus root is btrfs (verified); the effect on virtiofs ops is unmeasured. Cheap to test on the host. |
| 3.5 | Writeback caching in libkrun virtiofs for CI VMs | Patch sipb/libkrun `device.rs` to set `passthrough::Config.writeback = true` (and maybe `cache_policy = Always`) for the root device; build via `overlays.nix` | Code path exists upstream (`Config.writeback`), no setter; SIPB already carries a libkrun fork. Safe condition per the code comment: host must not modify the dir behind the guest's back (true for a private container rootfs [I]); guest-side data loss on VM crash is the trade-off (CI jobs are disposable). |
| 3.6 | More request queues / worker threads | libkrun code change (`num_request_queues = 1`, one worker thread) | Not available upstream; a real engineering task. |
| 3.7 | virtio-blk disk (raw/qcow2 image on host NVMe) for scratch or root | libkrun side: `krun_add_disk`, `krun_add_disk2`, `krun_add_disk3(ctx, block_id, path, format, read_only, direct_io, sync_mode)`, `krun_set_root_disk`, `krun_set_data_disk` [V in libkrun.h v1.19.6]. crun side: [V] the krun handler (sipb rev and upstream main) calls `krun_set_root_disk` ONLY for the SEV flavor (`/disk.img`), and has no annotation/`.krun_vm.json` key for disks (annotations listed in `krun.1.md`: `krun.cpus, krun.ram_mib, krun.gpu_flags, krun.use_passt, krun.tap_name, krun.nested_virt, krun.custom_kernel, krun.variant`). | So: libkrun yes; podman/crun exposure NO. Needs a patch to the sipb/crun fork (they already patch `krun.c`) plus a per-job lifecycle: create a sparse image, attach, format (mkfs) and mount in the guest (libkrun init only auto-mounts a block device for SEV/TDX via `mount_tee_block_device`; a job step as root could `mkfs.ext4 /dev/vdX && mount`), delete afterwards. Upstream request for exactly this: libkrun #667 item 4. |
| 3.8 | Bigger/other DAX window via `.krun_vm.json` `virtiofs_shm_size` in each ci-images image | Add `/.krun_vm.json` to ci-images Dockerfiles | [V] knob exists; [?] benefit for root mounted without `dax`: unproven, probably small for metadata ops. |

---

## Item 4. Is 177 MiB/s write, 1.2 GiB/s read, 1.6k creates/s, 13k stat/s, 4k open+read/s, 4.7k unlink/s normal?

Published reference points (no source gives a libkrun small-file number; I found none, [?]):
1. Original virtio-fs RFC (Vivek Goyal, 2018; host: Fedora 28, PCIe SSD, 16 vCPU guest), `smallfile`, 8 threads, 1 KiB files, 2048 files per thread: "virtio-fs none create 714" files/s, "virtio-fs always create 685", "virtio-9p none create 194"; `ls-l` 4615 files/s (virtio-fs none). Source: https://lkml.iu.edu/hypermail/linux/kernel/1812.1/01577.html (text retrieved through the search/fetch ladder; table columns paraphrased from the extracted text). [V as quoted] Your 1,600 creates/s and 13,000 stat/s are the same order of magnitude or better (modern kernel/hardware), so [I] your numbers look normal for virtiofs, not broken.
2. Same RFC, fio mmap: "virtio-fs always 235 MB/s / 858 MB/s" vs "virtio-fs always + dax 121 MB/s / 487 MB/s", i.e. DAX was not a clear win and the thread note that "DAX was not as fast as we were expecting" (secondhand via search summary; treat as [I]).
3. Red Hat Bugzilla 1924337 "RFE: virtiofs performs worse than nfs" (https://bugzilla.redhat.com/show_bug.cgi?id=1924337): kernel build `time make O=/tmp/build -j16`: "(a) 2 min [local fs on raw image on nvme] (b) 5 min (+3 min ~ 150%) [virtiofs on host ext4, same nvme] (c) 3.5 min [nfs]". [V] About 2.5x slower than virtio-blk-on-raw for a metadata+data build workload, with a regular virtiofsd.
4. libkrun #655: krun virtiofs root `make -j16` 11.22 s vs libvirt 6.05 s (1.85x), system time 6x higher; virtio-blk root removes the difference. [V]
5. Vivek Goyal (virtio-fs list, 2022-07-26; via Wayback snapshot https://listman.redhat.com/archives/virtio-fs/2022-July/005069.html): "My impression in general is that virtio-blk is much faster than virtiofs." and "kernel compilation is a good macro benchmark sort of workload which stresses filesystem both for data and metadata operations." [V]
6. virtiofsd issue #66 (https://gitlab.com/virtio-fs/virtiofsd/-/work_items/66): with `--cache=always`, "virtio-blk costs only half time to finish the job than virtio-fs" for a read-only `require(koa)` load. [V]
7. Not found: a published virtiofs-vs-native number for `stat`/`unlink`/write MiB/s with a single-queue libkrun server. So "tmpfs is ~30x faster on small files" is expected: each metadata op on virtiofs is a guest->host FUSE round trip through one host thread, vs a pure in-guest page-cache op. [I]

Assessment [I]: your seq read 1.2 GiB/s is guest-cached/host-page-cache speed; seq write 177 MiB/s with identical results with/without fsync is the write-through signature of `writeback=false`; metadata rates are in the range of other published virtiofs results. Nothing suggests a misconfiguration; it is the design default.

---

## Ranked suggestions for the ticket (cheapest first)

1. [no infra change] Document and encourage job-side scratch on `/dev/shm`: set `TMPDIR=/dev/shm/...` or a workspace-on-tmpfs recipe in the ci-images README and in `SIPB/hyades-action`; mention that `podman --tmpfs` and `type=tmpfs` mounts are NOT faster here (crun #1952). Mention the RAM cost against `krun.ram_mib=65536` x `capacity = 4`. (Verified mechanism; effect measured by us: ~30x on small files.)
2. [host-only, minutes] Measure the same micro-benchmark directly on the runner host in `/var/lib/gitea-runner/.local/share/containers/storage` to separate "host btrfs" cost from "virtiofs" cost. If the host is slow, move graphroot/volumes to ext4/xfs on NVMe or mark it NOCOW (`chattr +C`). (Inferred benefit; sipbphus root fs is btrfs per `hardware-configuration.nix`.)
3. [fork patch, small] In sipb/libkrun `src/devices/src/virtio/fs/device.rs` (lines 87-91: `passthrough::Config { root_dir, semantics, attr_timeout, ..Default::default() }`), set `writeback: true` (field name `writeback`) and optionally `cache_policy: CachePolicy::Always` (field name `cache_policy`) for the CI root device, ideally behind an env var or a new C-API setter, and benchmark. Rationale: fields exist, doc comment gives the safety conditions, CI rootfs is private and disposable. Expect better write throughput; effect on creates/stat unknown. SIPB already builds libkrun from a fork in `overlays.nix`.
4. [per-image, trivial but speculative] Add `/.krun_vm.json` with `{"virtiofs_shm_size": <bytes>}` to the ci-images (documented key; default 512 MiB). Weak expected benefit because the root is mounted without `dax`; include only as a cheap experiment. Do NOT guess other keys: none exist for cache/queues/threads.
5. [fork patch, medium/large] virtio-blk scratch or root disk: add an annotation or `.krun_vm.json` key in sipb/crun `krun.c` that calls libkrun `krun_add_disk3(ctx, "scratch", path, KRUN_DISK_FORMAT_RAW, false, <direct_io>, <sync_mode>)` (libkrun API exists; crun has no annotation for it today, upstream request is libkrun #667 item 4), plus a per-job image create/delete step and an in-guest mkfs+mount. Upstream evidence it fixes the gap: libkrun #655 (virtio-blk root = parity with QEMU/libvirt). Note #824 (virtio-blk is single-threaded per disk).
6. [libkrun engineering, large] Multi-queue/multi-thread virtiofs server (`num_request_queues = 1` and a single `FsWorker` thread today). No upstream issue found; would be a new upstream contribution; coordinate with libkrun maintainers (slp, mtjhrc, jakecorrenti).

Also useful to mention in the ticket: SIPB's own README TODO items "virtiofs performance tweaks (or just use tmpfs?)" and "CI caching" (https://forgejo.mit.edu/SIPB/hyades/raw/branch/main/README.md), and that the workflow uses `capacity = 4`, so concurrent jobs share the host disk and each VM has its own single virtiofs worker thread.

## Open questions / not found
1. Host RAM/CPU/disk model of sipbphus and whether Forgejo itself runs on hyades.mit.edu: [?] not in the repos.
2. Whether `/` in the guest is actually mounted with `dax` and whether libkrun's passthrough implements DAX mapping for regular files in this rev: [?] not verified (check `/proc/mounts` in a job).
3. Whether jobs run as root in the guest (needed for `mount -t tmpfs` suggestion): [?] from your side.
4. Default `PermissionSemantics` used for the crun-created virtiofs root (affects `attr_timeout`: code sets `0` for `LinuxSimplified`, else 5 s): [?] not determined.
5. Firecrawl search was unavailable (out of credits); web research used WebSearch, `web-get` (Wayback/Exa fallback for listman.redhat.com and bugzilla), GitHub API and raw files.

