Two small follow-up measurements on the runner (2026-10-14, run 237):

1. **Download speed is not a bottleneck.** With `curl -sSL` (the earlier test lacked `-L` and returned nothing): the 137 MB Gradle distribution in 1.47 to 1.49 s (about 92 MB/s), the 154 MB Android command-line tools in 1.5 to 1.6 s (96 to 102 MB/s), a 60 MB Kotlin jar from Maven Central in 0.73 to 0.76 s (79 to 82 MB/s); three runs each.
2. **Remounting the root virtiofs with `dax` does nothing from inside the guest.** `mount -o remount,dax=always /` and `mount -o remount,dax /` both return 0, but `/proc/self/mountinfo` shows the same `rw,relatime` options afterwards, so DAX is not enabled (the kernel log does show a 512 MiB cache window: `virtiofs virtio3: Cache len: 0x20000000`). The small-file benchmark before and after differed by 20 to 40% (create 1,621 to 2,249 files/s, stat 12,814 to 15,653/s), which is within what this shared host's noise allows and cannot be credited to DAX.

So the disk numbers above stand: the lever for small-file speed is on the host side (virtiofs queues or workers, or a different root disk), not something a job can switch on.
