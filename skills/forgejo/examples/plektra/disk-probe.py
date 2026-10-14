#!/usr/bin/env python3
"""disk-probe.py DIR... — what a build's disk traffic costs in each directory (small files, writes, mount type).
Same script on the MIT runner and on a Mac. Gradle is mostly small-file create/stat/read, so ops/s matters more than MiB/s."""
import os, sys, time, tempfile, shutil, subprocess

def t(fn):
    a = time.perf_counter(); fn(); return time.perf_counter() - a

def probe(d):
    os.makedirs(d, exist_ok=True)
    w = tempfile.mkdtemp(dir=d, prefix="dp-")
    try:
        mnt = subprocess.run(["sh", "-c", f"df -T {w} 2>/dev/null | tail -1 || df {w} | tail -1"], capture_output=True, text=True).stdout.split()
        print(f"== {d}  fs={mnt[1] if len(mnt) > 1 else '?'}")
        n = 5000; body = b"x" * 4096
        paths = [os.path.join(w, f"f{i}") for i in range(n)]
        def create():
            for p in paths:
                with open(p, "wb") as f: f.write(body)
        def stat():
            for p in paths: os.stat(p)
        def read():
            for p in paths:
                with open(p, "rb") as f: f.read()
        def unlink():
            for p in paths: os.unlink(p)
        for name, fn in (("create_4KiB_files", create), ("stat", stat), ("open_read", read), ("unlink", unlink)):
            s = t(fn); print(f"  {name}_per_s {n / s:.0f}")
        if os.environ.get("DP_SMALL"): return
        buf = os.urandom(1 << 20); big = os.path.join(w, "big")
        def seq(sync):
            def run():
                with open(big, "wb") as f:
                    for _ in range(1024): f.write(buf)
                    f.flush()
                    if sync: os.fsync(f.fileno())
            return run
        print(f"  seq_write_1GiB_nosync_MiB_per_s {1024 / t(seq(False)):.0f}")
        print(f"  seq_write_1GiB_fsync_MiB_per_s {1024 / t(seq(True)):.0f}")
        def rd():
            with open(big, "rb") as f:
                while f.read(1 << 20): pass
        print(f"  seq_read_1GiB_MiB_per_s {1024 / t(rd):.0f}")
    finally:
        shutil.rmtree(w, ignore_errors=True)

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--small":      # metadata ops only, for parallel-scaling runs
        os.environ["DP_SMALL"] = "1"; args = args[1:]
    for d in args: probe(d)
