#!/usr/bin/env python3
"""listener-churn-repro.py: many short-lived loopback listeners, each checked end to end (shaped like a test
suite that starts one okhttp MockWebServer per test).

Each iteration: bind a listener (port 0, so the loopback-port shim picks a random port 20000-32000), start an
accept thread, connect a client by HOST (127.0.0.1 or localhost), send a unique token, expect the same token echoed
back by *this* server, close the listener. Reports bind errors, connect errors, short reads (EOF before the
reply), and replies carrying another server's token. A correct stack reports zero of each.
Usage: listener-churn-repro.py [iterations] [threads] [host]    (host default 127.0.0.1)
CHURN_BASE=N makes thread k bind port N+k every time (distinct ports, no sharing); CHURN_RANDOM=1 picks a
random port 20000-32000 in Python (no shim needed); CHURN_PINGPONG=1 with CHURN_PORT=N: the threads take strict turns on that one port (thread A closes it, thread B binds
it next); CHURN_GAP_MS=M sleeps M ms between turns. CHURN_PORT=N binds that one port every time (back-to-back reuse of the same port number) instead of port 0.
On a failure it prints the recent history of that port number (which thread held it, bind/close times).
"""
import collections, os, socket, sys, threading, time, uuid
N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
T = int(sys.argv[2]) if len(sys.argv) > 2 else 1
HOST = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
errs = collections.Counter(); ok = [0]; ports = collections.Counter(); lock = threading.Lock()
FIXED = int(os.environ.get("CHURN_PORT", "0")); BASE = int(os.environ.get("CHURN_BASE", "0")); RANDPORT = os.environ.get("CHURN_RANDOM") == "1"; import random; hist = collections.defaultdict(list); T0 = time.time()
def note(port, what):
    with lock: hist[port].append((round((time.time() - T0) * 1000, 1), threading.current_thread().name, what))

def one(k):
    token = uuid.uuid4().hex.encode()
    ls = socket.socket()
    if os.environ.get("CHURN_NOREUSE") != "1": ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # CHURN_NOREUSE=1: like MockWebServer on port 0
    try:
        ls.bind(("127.0.0.1", BASE + k if BASE else (random.randint(20000, 32000) if RANDPORT else FIXED))); ls.listen(50)
    except OSError as e:
        with lock: errs["bind " + str(e)[:50]] += 1
        ls.close(); return
    port = ls.getsockname()[1]; note(port, "bound")
    def serve():
        try:
            c, peer = ls.accept(); note(port, f"srv accepted from {peer[1]}"); c.settimeout(5); d = b""
            while b"\n" not in d:
                x = c.recv(256)
                if not x: note(port, f"srv recv EOF after {len(d)} bytes"); break
                d += x
            if d:
                c.sendall(b"echo:" + d); note(port, "srv replied")
            c.close()
        except OSError as e: note(port, f"srv OSError {e}")
    th = threading.Thread(target=serve, daemon=True); th.start()
    try:
        s = None; last = None
        for fam, typ, proto, _, addr in socket.getaddrinfo(HOST, port, type=socket.SOCK_STREAM):
            try: s = socket.socket(fam, typ, proto); s.settimeout(5); s.connect(addr); break
            except OSError as e: last = e; s.close(); s = None
        if s is None: raise last
        s.sendall(token + b"\n"); got = b""
        while True:
            x = s.recv(256)
            if not x: break
            got += x
        s.close()
        if got == b"": raise EOFError("EOF before any reply")
        if got.strip() != b"echo:" + token:
            with lock: errs["wrong reply (another server?) " + got[:20].decode("latin1")] += 1
        else:
            with lock: ok[0] += 1
    except Exception as e:
        with lock: errs[f"client {type(e).__name__}: {str(e)[:50]}"] += 1
        with lock: ports[port] += 1
        note(port, "CLIENT FAILED " + type(e).__name__)
    finally:
        note(port, "close-start")
        try: ls.close()
        except OSError: pass
        note(port, "closed")

PING = os.environ.get("CHURN_PINGPONG") == "1"; GAP = float(os.environ.get("CHURN_GAP_MS", "0")) / 1000
turn = [0]; cv = threading.Condition()
def worker(k):
    for i in range(N // T):
        if PING:
            with cv:
                cv.wait_for(lambda: turn[0] % T == k)
            one(k)
            if GAP: time.sleep(GAP)
            with cv:
                turn[0] += 1; cv.notify_all()
        else:
            one(k)

t0 = time.time(); ts = [threading.Thread(target=worker, args=(k,)) for k in range(T)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"host={HOST} threads={T} iterations={N} ok={ok[0]} errors={sum(errs.values())} secs={time.time()-t0:.1f}")
for k, v in errs.most_common(): print(f"  {v:5d}  {k}")
for pt in sorted(ports)[:6]:
    h = hist[pt]; i = max(j for j, e in enumerate(h) if "CLIENT FAILED" in e[2])
    print(f"  port {pt}: events around the failure (ms since start, thread, event):")
    for e in h[max(0, i - 7):i + 4]: print("    ", e)
sys.exit(1 if errs else 0)
