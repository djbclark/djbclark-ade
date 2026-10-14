**Update, 2026-10-14 (later): the test hang and the flaky tests are explained and worked around; the full Plektra suite now passes on the runner except for one test that also fails elsewhere.**

Short version: it was never the disk. Three behaviours of libkrun's TSI loopback networking, all measured with small probes, broke Java test suites that start a local okhttp `MockWebServer`; an `LD_PRELOAD` shim in the job works around all three.

1. **A thread blocked in `recv()`/`accept()` on a socket blocks `shutdown()`, `getpeername()` and even `send()` on that socket from other threads** (a normal kernel does not). `ServerSocket.close()` calls `shutdown()`, so the test worker hung forever (the earlier "hang"); a WebSocket client's writer thread stalled behind its reader thread (three tests timing out at 3 s). Same root cause as libkrun#819; details and probes in libkrun#926.
2. **A listener closed while a thread is blocked in `accept()` is not released**: a new listener on the same port mostly loses its connections, even 2 s later (libkrun#929). Consecutive MockWebServers in a test run get the same random port within a second, which was most of the "unexpected end of stream" failures.
3. **`SO_REUSEPORT` is always on for TSI host sockets (libkrun#860)**, so a second `listen()` on a used port succeeds. This also means VMs on the same host share one loopback port space.

| Plektra suite (1,417 tests) on the runner | failed | notes |
|---|---|---|
| run 189-191, as-is / tmpfs / loop storage, no shim | hung | identical on all three storages: not disk speed |
| run 203, shim with the 300 ms `shutdown()` wrapper | 7 | known `CornerButtonThemeTest` + about six flaky MockWebServer tests |
| run 222, + no repeated random ports | 4 | 3 WebSocket tests (the send-behind-recv stall) left |
| run 229 and 230, + wait in `poll()` before blocking reads | **1** | only `CornerButtonThemeTest`, which also fails on GitHub Actions and on a laptop; test step 3 m 4 s |

A standalone okhttp 4.11 MockWebServer loop: about 30% failures and 150 s per 150 iterations before, 0 of 800 failures and 1 s per 800 after. The shim, probes and numbers are in https://github.com/djbclark/djbclark-ade/tree/236ba60/skills/forgejo/examples/plektra (`loopback-port-shim.c`, `duplex-probe.c`, `reuse-probe.c`, `java-churn/`).

What this means for the runner: nothing is needed from SIPB for these builds to work, since the shim lives in the job. The disk and storage measurements above are unchanged. It would still be worth looking at the TSI behaviours if other users run Java or WebSocket test suites on the runner, and the shared loopback port space (point 3) is worth knowing if concurrent jobs ever run local servers on fixed ports. libkrun's `krun.use_passt=1` would avoid TSI for loopback altogether, but SIPB said no to that earlier, so I have not pursued it.
