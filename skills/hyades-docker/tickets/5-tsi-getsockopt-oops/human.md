A `getsockopt()` below `SOL_SOCKET` on a UDP socket that has talked to an outside address oopses the guest kernel; the process dies and the microVM hangs instead of exiting:

```
$ ssh hyades tmprun docker.io/library/python:3-alpine
>>> import socket
>>> s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1", 53)); s.send(b"x")
>>> s.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)
BUG: kernel NULL pointer dereference, address: 0000000000000000
CPU: 3 UID: 0 PID: 496 Comm: python3 Not tainted 6.12.109 #1
 ? tsi_stream_getsockopt+0x61/0xa0
```

`SOL_SOCKET` calls work. Chromium does this routinely, so headless browsers (Playwright, Puppeteer) on Hyades stop loading pages after the first such call.

This is upstream libkrun/libkrunfw#140 (open), which proposes guarding the NULL `vsock_dgram_ops.getsockopt` call and returning `-EOPNOTSUPP`. Idea: carry that patch in Hyades' libkrunfw until it is merged. Until then, an `LD_PRELOAD` workaround: https://forgejo.mit.edu/djbclark/loopback-port-shim (problem 5).
