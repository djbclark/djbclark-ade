## Summary

Inside a Hyades microVM, `getsockopt(fd, level, ...)` with any `level` other than
`SOL_SOCKET` on a UDP socket that TSI has moved to its vsock proxy (any UDP socket
that has connected or sent to a non-loopback address) calls a NULL function
pointer in the guest kernel. The calling task oopses and dies ("exited with irqs
disabled"); a single-threaded process never finishes exiting, so the microVM stays
up (a `tmprun` never returns), and in a multi-threaded process (Chromium) the
thread that made the call is gone and the rest of the process stalls on it.

Upstream: https://github.com/libkrun/libkrunfw/issues/140 (open since 2026-09-04,
no fix merged as of 2026-10-14). Guest-only: the crash stays inside the guest
kernel. It is a denial of service a workload can only inflict on itself, so it is
not a host security issue.

## Environment (2026-10-14)

1. Hyades console from SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`;
   podman 5.8.8 rootless, `engine.runtime = "krun"`, crun `1.30.1-sipb`, libkrun
   "2.0-sipb".
2. Guest kernel `6.12.109 #1` (libkrunfw), the same in both reproductions below.
3. User `djbclark`, SSH key login.

## Minimal reproduction (2026-10-14, about 20:40 EDT)

`tmprun docker.io/library/python:3-alpine` (its default command is the Python
REPL; the lines below were sent on stdin):

```
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1", 53)); s.send(b"x"); print("sent")
print("SO_TYPE", s.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE))
print("IP_TOS", s.getsockopt(socket.IPPROTO_IP, socket.IP_TOS))
print("still alive")
exit()
```

Output (terminal echo removed):

```
sent
SO_TYPE 2
[    1.648368] BUG: kernel NULL pointer dereference, address: 0000000000000000
[    1.648544] #PF: supervisor instruction fetch in kernel mode
[    1.648688] #PF: error_code(0x0010) - not-present page
[    1.648795] PGD 0 P4D 0
[    1.648870] Oops: Oops: 0010 [#1] PREEMPT SMP PTI
[    1.648989] CPU: 3 UID: 0 PID: 496 Comm: python3 Not tainted 6.12.109 #1
[    1.649130] RIP: 0010:0x0
[    1.649517] RAX: 0000000000000000 RBX: ffff88810087c000 RCX: 00007ffe24befd50
[    1.649699] RDX: 0000000000000001 RSI: 0000000000000000 RDI: ffff888100730680
[    1.650855] Call Trace:
[    1.650904]  <TASK>
[    1.650953]  ? tsi_stream_getsockopt+0x61/0xa0
[    1.651091]  ? do_sock_getsockopt+0x116/0x200
[    1.651249]  ? __sys_getsockopt+0x5e/0xb0
[    1.651328]  ? __x64_sys_getsockopt+0x16/0x30
[    1.651433]  ? do_syscall_64+0x47/0x120
[    1.651556]  ? entry_SYSCALL_64_after_hwframe+0x76/0x7e
[    1.651660]  </TASK>
[    1.653540] note: python3[496] exited with irqs disabled
```

`still alive` never printed and the `tmprun` did not return; the container stayed
`running` in `df` until stopped with `stop libpod-<id>*` (three such orphans were
stopped during this investigation). `RSI = 0` (`SOL_IP`/`IPPROTO_IP`) and
`RDX = 1` (`IP_TOS`) are the level and option name. The `SOL_SOCKET` call is
handled by `do_sock_getsockopt()` itself and never reaches TSI.

## Where it hit a real service

Firecrawl's `playwright-service` (headless Chromium) as a Hyades microVM
(`djbclark-fc-playwright`, deploy files in djbclark-ade
`skills/hyades-docker/examples/firecrawl/`). Scraping
`https://stackoverflow.com/questions/11227809/...` (Cloudflare-fronted) logged, at
2026-10-14 20:08:45 EDT, through the quadlet unit's journal:

```
[   32.934306] BUG: kernel NULL pointer dereference, address: 0000000000000000
[   32.935532] CPU: 0 UID: 0 PID: 577 Comm: Chrome_ChildIOT Not tainted 6.12.109 #1
[   32.935768] RIP: 0010:0x0
[   32.936372] RDX: 0000000000000001 RSI: 0000000000000000 RDI: ffff88815a850d00
[   32.938182]  ? tsi_stream_getsockopt+0x61/0xa0
```

Same registers (`SOL_IP`, `IP_TOS`). After it, every navigation in that Chromium
timed out (Firecrawl scrapes went from about 2 s to 30 s timeouts, 12 of 16 test
pages passing) until the microVM was restarted. The upstream report saw the same
crash from `Chrome_ChildIOT` with `SOL_IPV6`/`IPV6_V6ONLY` (`RSI = 0x29`,
`RDX = 0x1a`).

## Code reading (from the upstream issue; not re-verified against Hyades' build)

1. libkrunfw `patches/0011-Transparent-Socket-Impersonation-implementation.patch`
   (at `4d5fc498b012424f92ccf791e625c62f3ea748f7`, lines 1155-1166):
   `tsi_stream_getsockopt()` calls `isocket->ops->getsockopt` or
   `vsocket->ops->getsockopt` with no NULL check.
2. `tsi_dgram_ops.getsockopt` also points at `tsi_stream_getsockopt`, so TSI UDP
   sockets take this path. Once a datagram socket has fallen back to the vsock
   proxy (`tsk->status = S_VSOCK`), the call goes to `vsock_dgram_ops.getsockopt`,
   which `net/vmw_vsock/af_vsock.c` leaves NULL: `call 0x0`, matching
   `RIP: 0x0`, `RAX: 0` and `#PF: supervisor instruction fetch`.
3. The sibling `tsi_*_setsockopt` handlers already guard the ops pointer.
4. Latent variant per upstream: with `tsi_hijack_unix`, a non-`SOL_SOCKET`
   `getsockopt()` on a hijacked `AF_UNIX` socket reaches the NULL
   `unix_*_ops.getsockopt` the same way.

## Fix options

1. **Carry the upstream proposal in Hyades' libkrunfw build**: guard both indirect
   calls in `tsi_stream_getsockopt()` and return `-EOPNOTSUPP`, which is what a
   native kernel returns for these socket types (`do_sock_getsockopt()` checks
   `!ops->getsockopt`). Sketch (hypothesis, untested against the SIPB tree):

   ```c
   if (!sock->ops->getsockopt)
           return -EOPNOTSUPP;
   return sock->ops->getsockopt(sock, level, optname, optval, optlen);
   ```

   applied to each of the `isocket`/`vsocket` branches.
2. Rebuild with an upstream libkrunfw once #140 is fixed.

## Workaround in use

`LD_PRELOAD` shim https://forgejo.mit.edu/djbclark/loopback-port-shim, problem 5
(commit `b5f2cd304bc602d9ecd1d25cee8482bc8d097b80`): its `getsockopt()` wrapper
returns `EOPNOTSUPP` for any level but `SOL_SOCKET` on a `SOCK_DGRAM` socket whose
peer is not loopback (or that is unconnected), without entering the kernel. With
it baked into the Playwright image (`forgejo.mit.edu/djbclark/firecrawl-playwright:shim-b5f2cd3`),
the same Stack Overflow scrape fails cleanly (Cloudflare block) and the next pages
load normally: 15 of 16 pages, no further oops in the journal. It cannot help
statically linked programs or ones that make the syscall directly.

## Impact

Any headless Chromium (Playwright, Puppeteer, Selenium) on Hyades, and anything else
that queries IP-level options on UDP sockets (QUIC stacks, DNS libraries), can take
down its own process and wedge the microVM; for `tmprun` it also leaves an orphan
that keeps using the user's quota (see SIPB/hyades#8).
