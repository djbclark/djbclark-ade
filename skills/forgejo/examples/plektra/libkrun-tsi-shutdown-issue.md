<!-- Draft for https://github.com/libkrun/libkrun/issues . NOT FILED. Title: "TSI: shutdown() and getpeername() block while another thread is blocked in accept() or read() on the same socket (hangs Java ServerSocket.close())" -->

## Summary

In a krun guest with TSI networking, `shutdown(2)` on a TCP socket never returns while another thread of the process is blocked in `accept()` (listener) or `read()` (connected client) on that same socket. `getpeername()` on the listener blocks the same way. (`getsockopt(SO_ACCEPTCONN)` does not block, but returns 0 for a socket that is listening.) On a normal Linux kernel `shutdown()` on a listener wakes the blocked `accept()`; it is how Java (`ServerSocket.close()`, `Socket.close()`), okhttp's MockWebServer and many other runtimes unblock an accept thread. Here the closing thread hangs forever, so for example a Gradle test JVM stops with a thread stuck in `sun.nio.ch.Net.shutdown` and the CI job runs until its timeout. Related to the port-0 problem in #818, found while working around it.

Prepared with an AI coding assistant (Claude Code) from probe runs on SIPB's Hyades CI runner (libkrun "2.0-sipb", guest kernel 6.12.91, root and loopback through TSI); I reviewed the results. I have not tried upstream main outside that runner.

## Repro (inside a krun container)

```python
import socket, threading, time
s = socket.socket(); s.bind(("127.0.0.1", 31337)); s.listen(5)
threading.Thread(target=lambda: s.accept(), daemon=True).start(); time.sleep(0.3)
s.shutdown(socket.SHUT_RDWR)   # never returns
```

Also: `ServerSocket s = new ServerSocket(31340)` with a thread in `s.accept()`, then `s.close()` from another thread: hangs. A client `Socket` with a thread blocked in `getInputStream().read()`, then `close()`: hangs.

## What I measured (C probe `accept-probe.c`, thread blocked in `accept()` on a loopback listener)

| action from the other thread | result |
|---|---|
| `pthread_kill(SIGUSR1)` | `accept` returns `EINTR` (works) |
| `dup2(/dev/null, fd)` then `pthread_kill` | `accept` returns `EINTR` (works; this is what the JDK does after `shutdown`) |
| `close(fd)` alone | `accept` stays blocked (same as a normal kernel, where close does not wake accept) |
| `shutdown(fd, SHUT_RD)` | never returns |
| `shutdown(fd, SHUT_RDWR)` | never returns |
| `getpeername(fd)` | never returns |
| `getsockopt(fd, SOL_SOCKET, SO_ACCEPTCONN)` | returns at once, value 0 (the socket is listening, so this looks wrong) |
| `shutdown(fd, SHUT_RDWR)` on a listener with no thread in `accept()` | fails with `ENOTCONN` (a normal kernel returns 0) |

So the blocked `accept()` seems to hold a lock that some other socket operations need. Probe workflows and logs: https://github.com/djbclark/djbclark-ade/tree/master/skills/forgejo/examples/plektra (`probe-shutdown*.yml`, `probe-accept.yml`, `accept-probe.c`).

## Workaround in use

An `LD_PRELOAD` shim records listening fds in `listen()` (forgotten in `close`/`dup2`/`dup3`), makes `shutdown()` a no-op on them, and runs `shutdown()` on other sockets in a helper thread with a 300 ms wait. The JDK's `dup2` plus signal then wakes the blocked reader. With it a 1,417-test Gradle/Robolectric suite completes. Roughly six MockWebServer tests still fail with `unexpected end of stream` (a different subset each run), also with `shutdown()` made a no-op, so there may be a second TSI loopback issue; I do not have a minimal repro for it yet.

## Questions

1. Is the blocking intended (a socket-wide lock held during `accept`/`read`), or a bug? A fix that lets `shutdown` and `getpeername` proceed concurrently with a blocked `accept` would match Linux behavior.
2. For CI users, would `krun.use_passt=1` avoid TSI for loopback entirely? SIPB prefers not to enable it (nested passt), which is why I am asking about a TSI fix.

## Related

1. #818: listeners bound to port 0 are unreachable under TSI.
2. #924: virtiofs performance on the same runner.
