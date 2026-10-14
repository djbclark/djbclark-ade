#!/usr/bin/env python3
"""keepalive-repro.py: loopback HTTP keep-alive stress, shaped like okhttp + MockWebServer.

Server threads answer 1-4 requests per connection, announce `Connection: close` on the last one and then
close() the socket (with or without shutdown first); client threads reuse a connection until told to close
and report short reads, resets, timeouts and unexpected EOF. A correct stack reports zero errors. Usage: keepalive-repro.py [seconds] [clients] [mode]
mode: plain | shutdown (server calls shutdown() before close()) | mixed (default). REPRO_PORT=N binds a fixed port
(port 0 needs the loopback-port shim on the runner). Exit 1 if any error.
"""
import socket, sys, threading, time, collections
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 20
CLIENTS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
MODE = sys.argv[3] if len(sys.argv) > 3 else "mixed"
BODY = b"x" * 3000
RESP = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nContent-Type: text/plain\r\n\r\n" % len(BODY) + BODY
RESP_LAST = RESP.replace(b"Content-Type", b"Connection: close\r\nContent-Type", 1)  # well-behaved: announce the close
errs = collections.Counter(); ok = [0]; lock = threading.Lock(); stop = time.time() + DUR

def serve(conn, per_conn, use_shutdown):
    try:
        conn.settimeout(5)
        for i in range(per_conn):
            buf = b""
            while b"\r\n\r\n" not in buf:
                d = conn.recv(4096)
                if not d: return
                buf += d
            conn.sendall(RESP_LAST if i == per_conn - 1 else RESP)
    except OSError: pass
    finally:
        try:
            if use_shutdown: conn.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        conn.close()

def acceptor(ls):
    n = 0
    while True:   # never stops early: a client that connects at the deadline must still be served
        try: c, _ = ls.accept()
        except OSError: return
        n += 1
        threading.Thread(target=serve, args=(c, 1 + n % 4, MODE == "shutdown" or (MODE == "mixed" and n % 2)), daemon=True).start()

def read_resp(s):
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d: raise EOFError("unexpected end of stream (headers)")
        buf += d
    head, _, rest = buf.partition(b"\r\n\r\n")
    n = int([l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")][0].split(b":")[1])
    closing = b"connection: close" in head.lower()
    while len(rest) < n:
        d = s.recv(4096)
        if not d: raise EOFError("unexpected end of stream (body)")
        rest += d
    return closing

def client(port):
    s = None
    while time.time() < stop:
        phase = "connect"
        try:
            if s is None:
                s = socket.create_connection(("127.0.0.1", port), timeout=5)
            phase = "send"
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            phase = "recv"
            closing = read_resp(s)
            with lock: ok[0] += 1
            if closing: s.close(); s = None
        except (EOFError, ConnectionError, socket.timeout, OSError) as e:
            with lock: errs[phase + " " + type(e).__name__ + ": " + str(e)[:60]] += 1
            try: s.close()
            except Exception: pass
            s = None
            time.sleep(0.01)  # reconnect after any error
            continue
        time.sleep(0.001)

ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ls.bind(("127.0.0.1", int(__import__("os").environ.get("REPRO_PORT", "0")))); ls.listen(128)
port = ls.getsockname()[1]
threading.Thread(target=acceptor, args=(ls,), daemon=True).start()
ts = [threading.Thread(target=client, args=(port,)) for _ in range(CLIENTS)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"mode={MODE} clients={CLIENTS} secs={DUR} ok={ok[0]} errors={sum(errs.values())}")
for k, v in errs.most_common(): print(f"  {v:6d}  {k}")
sys.exit(1 if errs else 0)
