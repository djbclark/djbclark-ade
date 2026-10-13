# Draft: loopback TCP refused inside the forgejo.mit.edu CI runner

Not sent. For djbclark to send (to the Hyades admins, sipb-hyades-root@mit.edu, or
as an issue on `SIPB/ci-images`) once reviewed. Evidence is from runs 169-172 of
`djbclark/plektra-djbclark`, 2026-10-13, label `ubuntu`, image
`forgejo.mit.edu/sipb/ci-images:ubuntu`, runner `sipbphus` (Forgejo Runner v13.1.0).

## Symptom

In a CI job, a process that listens on 127.0.0.1 cannot be connected to by
another socket in the same container. Anything that talks to itself over
localhost fails: the Gradle daemon (build fails with "Could not connect to the
Gradle daemon"), Gradle test workers, the Kotlin compiler daemon, local dev
servers, `docker`-less integration tests.

## Minimal reproduction (stdlib Python, run as a workflow step)

```python
import socket, threading, time
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(5)
threading.Thread(target=lambda: s.accept(), daemon=True).start()
time.sleep(0.2)
socket.create_connection(("127.0.0.1", s.getsockname()[1]), timeout=5)
# -> ConnectionRefusedError: [Errno 111] Connection refused
```

Results, bind -> connect, same process:

| bind | connect | result |
|---|---|---|
| 127.0.0.1 | 127.0.0.1 | refused |
| ::1 | ::1 | refused |
| 0.0.0.0 | 127.0.0.1 | refused |
| 0.0.0.0 | 10.89.0.2 (container IP) | refused |
| 203.0.113.1 (dummy0) | 203.0.113.1 | OK |
| 0.0.0.0 | 203.0.113.1 | refused |

Java agrees (`ServerSocket` on `InetAddress.getLoopbackAddress()`, then
`Socket.connect`: `ConnectException: Connection refused`). `ip link show lo`
reports `UP,LOWER_UP`; `ip link set lo up` changes nothing. `systemd-detect-virt`
says `docker`, `uname -r` is 6.12.91, `dmesg` shows a microVM boot. Inside the
job `unshare -n` hung until the job was cancelled.

## Likely cause

The runner is a libkrun microVM (see `SIPB/hyades` README). libkrun enables its
socket-proxy networking (TSI) automatically when the VM has no network interface
(libkrun docs: TSI and virtio-net+passt/gvproxy are mutually exclusive). Under
TSI, guest AF_INET sockets are proxied through the host VMM, and
https://github.com/libkrun/libkrun/issues/818 describes this exact symptom:
`bind(port 0)` + `listen()` makes the VMM bind a different ephemeral port in its
own netns, so the listener is unreachable, even for the process that created it.
Related: https://github.com/libkrun/libkrun/issues/510 (guest-internal sockets
intercepted by TSI). The probe above and Gradle's daemon both bind port 0. This
is inferred from the symptom and the issue text, not verified on your host.

## Fix and workarounds (from the issue)

libkrun issue https://github.com/libkrun/libkrun/issues/818 (open, no fix PR as of
2026-10-13; latest libkrun release v1.19.6) says:

1. **Host fix:** boot the microVM with a real virtio-net NIC through passt, which
   disables TSI entirely. With crun-krun: `--annotation krun.use_passt=1`
   (podman: `--runtime=krun`). The reporter confirms the same repro then passes.
   (libkrun API: `krun_add_net_unixstream` / `krun_add_net_unixgram`.)
2. **Fixed ports work.** Only port-0 (ephemeral) listeners diverge, which matches
   my probe; so a listener on a fixed port should connect here too (prediction).
3. **Userspace workaround** (not published): an `LD_PRELOAD` shim that rewrites
   port-0 binds to concrete ports. It would help Gradle only if it covers every
   JVM it spawns, so (1) is the practical fix.
4. A kernel-side patch for libkrunfw's 6.12.91 was announced in the issue
   (2026-08-24); no PR was found. The job kernel here is 6.12.91.

## Question

Is a working loopback in `ubuntu` jobs possible (a runner or microVM network
setting), or is a workaround expected? Also useful to know: the CPU and memory
share one job gets (the VM reports 16 CPUs and 62 GB), and whether there is a
job time limit.
