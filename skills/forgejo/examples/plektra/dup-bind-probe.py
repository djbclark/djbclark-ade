#!/usr/bin/env python3
"""dup-bind-probe.py: does a second bind()+listen() on a port that already has a listener fail with EADDRINUSE?

On Linux it must, with or without SO_REUSEADDR (only SO_REUSEPORT lets two listeners share a port). Under libkrun TSI
it does not, and the kernel-less "second listener" then silently never receives anything: connections go to the first
one. Cases: same process, with/without SO_REUSEADDR, and a second PROCESS. For each: the bind/listen result of the
second listener, and which listener (first or second) accepts a connection made to the port.
"""
import os, select, socket, subprocess, sys, time
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 31950

def listener(reuse, port):
    s = socket.socket()
    if reuse: s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(5); return s

def who_accepts(first, second):
    c = socket.create_connection(("127.0.0.1", first.getsockname()[1]), timeout=3)
    time.sleep(0.2); got = []
    for name, s in (("first", first), ("second", second)):
        if s is None: continue
        r, _, _ = select.select([s], [], [], 0.3)
        if r: got.append(name)
    c.close(); return got or ["NEITHER"]

def case(label, reuse1, reuse2, port):
    first = listener(reuse1, port)
    try:
        second = listener(reuse2, port); res = "second bind+listen SUCCEEDED"
    except OSError as e:
        second = None; res = f"second bind/listen failed: {e.strerror} (errno {e.errno})"
    acc = who_accepts(first, second) if second else ["(n/a)"]
    print(f"{label}: {res}; connection accepted by: {', '.join(acc)}")
    first.close()
    if second: second.close()

if len(sys.argv) > 1 and sys.argv[1] == "child":   # second process: bind the port, report, exit
    port, reuse = int(sys.argv[2]), sys.argv[3] == "1"
    try: s = listener(reuse, port); print("SUCCEEDED"); time.sleep(0.5)
    except OSError as e: print(f"failed ({e.strerror})")
    sys.exit(0)

print(f"{'first':>10} {'second':>10}  {'same process':<46} second process")
port = PORT
for r1 in (0, 1):
    for r2 in (0, 1):
        first = listener(bool(r1), port); port += 1
        try:
            second = listener(bool(r2), port - 1); res = "second bind+listen SUCCEEDED"
            res += "; accepted by " + ", ".join(who_accepts(first, second)); second.close()
        except OSError as e: res = f"failed ({e.strerror})"
        out = subprocess.run([sys.executable, __file__, "child", str(port - 1), str(r2)], capture_output=True, text=True).stdout.strip()
        print(f"{'REUSEADDR' if r1 else 'none':>10} {'REUSEADDR' if r2 else 'none':>10}  {res:<46} {out}")
        first.close()
