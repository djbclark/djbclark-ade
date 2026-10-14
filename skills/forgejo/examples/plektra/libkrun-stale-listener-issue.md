## Summary

In a krun guest with TSI networking, if a listening socket is closed while another thread is blocked in `accept()` on it (what the JDK does for `ServerSocket.close()`, and so okhttp's `MockWebServer.shutdown()`: it wakes the accept thread with `dup2` plus a signal, then closes), the listener is not really released. A new listener bound to the **same port** right afterwards gets `bind()`/`listen()` without error, but most connections to the port never reach it. A normal Linux kernel gives the new listener every connection. Related to #819 (accept holds the socket lock) and #860 (the host-side proxy socket always has `SO_REUSEPORT`), and probably a consequence of both.

Prepared with an AI coding assistant (Claude Code) from probe runs on SIPB's Hyades CI runner (libkrun "2.0-sipb", guest kernel 6.12.91, loopback through TSI); I reviewed the results. I searched libkrun issues (open and closed) for listener close, accept, EADDRINUSE and SO_REUSEADDR first; #819 and #860 are the nearest, and I have not tried upstream main outside that runner.

## Repro

[`reuse-probe.c`](https://github.com/djbclark/djbclark-ade/blob/236ba60/skills/forgejo/examples/plektra/reuse-probe.c), about 80 lines of C, `gcc -O2 -pthread -o reuse-probe reuse-probe.c && ./reuse-probe ROUNDS GAP_MS jdk`. Each round: listener L1 on a fixed port (`SO_REUSEADDR` on, the JDK default), a thread blocked in `accept(L1)`; the main thread wakes it as the JDK does (`dup2(/dev/null, fd)`, `pthread_kill(SIGUSR1)`, join) and closes it; after GAP_MS it opens a new listener L2 on the same port with an accept thread that echoes one message; a client connects, sends `ping`, and waits 2 s for the echo (with `poll`: `SO_RCVTIMEO` is not honoured under TSI).

## Results (20 rounds each)

| Where | Gap | Rounds where the new listener got the connection |
|---|---|---|
| TSI guest | 0 ms | 6 of 20 |
| TSI guest | 5 ms | 6 of 20 |
| TSI guest | 50 ms | 1 of 20 |
| TSI guest | 500 ms | 4 of 20 |
| TSI guest | 2000 ms | 8 of 20 |
| TSI guest, mode `none` (nobody was blocked in `accept` when L1 closed) | 0 ms | 20 of 20 |
| Ubuntu 24.04 container, Linux 6.18.15 (normal kernel), 100 rounds | 0 ms and 50 ms | 100 of 100 |

The failures do not depend on the gap up to 2 s, so this is not a short race: the old listener stays registered. The client's `connect()` and `send` succeed; the reply never comes.

## Possible cause (a guess from #819 and #860, not verified)

The blocked `accept()` holds the TSI socket lock across the vsock round trip (#819), so the close of L1 cannot complete the host-side teardown while it is pending; the host proxy socket of L1 keeps listening. Because the VMM sets `SO_REUSEPORT` on it (#860), L2's proxy joins the same reuse group instead of failing with `EADDRINUSE`, and the host kernel spreads connections across the old and the new listener. The scattered successes in the table (6 of 20, not 0 of 20) fit that picture.

## Impact and workaround

Test suites that start one okhttp MockWebServer per test fail with `unexpected end of stream` or time out when two consecutive servers get the same port number; on this runner that was about 30% of iterations in a standalone okhttp loop. Workarounds from userspace: never reuse a port number soon after closing it, and wait in `poll()` instead of a blocking `accept()` (parking in `poll()` does not hold the lock; with such an LD_PRELOAD shim the probe above gives 60 of 60 rounds at every gap from 0 to 50 ms, with the JDK wake and with a signal-only wake, on a port that has no leftovers from earlier runs). [`loopback-port-shim.c`](https://github.com/djbclark/djbclark-ade/blob/236ba60/skills/forgejo/examples/plektra/loopback-port-shim.c).

## The stale listeners drain (added later the same day)

They are not permanent. After a run without the workaround had leaked listeners on a port (2 of 10 rounds worked), a later run **with** the workaround on that same port failed only in its first 3 rounds and then every round worked; on an untouched port in the same job, 40 of 40; on the leaked port again 60 s later, 40 of 40, and 5 min later 40 of 40. So each stale listener seems to swallow one connection and then go away, which would fit its blocked `accept()` round trip still being pending in the VMM until a connection completes it. That is a guess. The wake method does not matter: a signal-only wake and `dup2` plus signal both fail 26 of 30 rounds at gap 0 without the workaround.

## Questions

1. Is the old host-side proxy socket expected to outlive a `close()` on the guest socket while `accept()` is blocked? Is there a way for `close()` to cancel the pending accept round trip?
2. Would giving the proxy socket `SO_REUSEPORT` only when the guest socket asked for it (as discussed in #860) also avoid this?
