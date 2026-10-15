Same oops here on 6.12.109, with a smaller trigger that needs no Chromium: IPv4 UDP and `SOL_IP`, so it isn't IPv6-specific.

```python
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1", 53)); s.send(b"x")
s.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)   # oops; SOL_SOCKET options work
```

```
BUG: kernel NULL pointer dereference, address: 0000000000000000
CPU: 3 UID: 0 PID: 496 Comm: python3 Not tainted 6.12.109 #1
 ? tsi_stream_getsockopt+0x61/0xa0
```

Supporting the proposed `-EOPNOTSUPP` fix: as a stopgap we return `EOPNOTSUPP` from an `LD_PRELOAD` shim for non-`SOL_SOCKET` `getsockopt()` on such UDP sockets, and Chromium (Playwright) then loads pages normally.
