#!/usr/bin/env python3
"""Context peaks and compaction stats from Claude Code transcripts.

Scans ~/.claude/projects/*/*.jsonl (or --root) for sessions modified in the
last --days days; prints per-day compaction counts by trigger with
preTokens median/max, a session context-peak histogram, and the top-10
peaks. Promoted 2026-11-05 from the 2026-10-27 one-off
transcript-context-peaks.py.
"""
import argparse
import collections
import json
import statistics
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="mtime window (default 7)")
    ap.add_argument("--root", default=str(Path.home() / ".claude/projects"))
    args = ap.parse_args()

    root = Path(args.root)
    cut = time.time() - args.days * 86400
    comp = collections.defaultdict(list)   # day -> [(trigger, preTokens)]
    peaks = []                             # (peak, model, session, mtime)
    nfiles = 0
    for p in root.glob("*/*.jsonl"):
        try:
            if p.stat().st_mtime < cut:
                continue
        except OSError:
            continue
        nfiles += 1
        peak = 0
        model = None
        with p.open(errors="replace") as f:
            for line in f:
                if '"compact_boundary"' in line:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    cm = o.get("compactMetadata") or {}
                    comp[(o.get("timestamp") or "")[:10]].append(
                        (cm.get("trigger"), cm.get("preTokens")))
                elif '"usage"' in line and '"assistant"' in line:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("isSidechain"):
                        continue
                    m = o.get("message") or {}
                    u = m.get("usage") or {}
                    t = ((u.get("input_tokens") or 0)
                         + (u.get("cache_read_input_tokens") or 0)
                         + (u.get("cache_creation_input_tokens") or 0))
                    if t > peak:
                        peak, model = t, m.get("model")
        if peak:
            peaks.append((peak, model, p.stem[:8], p.stat().st_mtime))

    print("files", nfiles, "sessions with usage", len(peaks))
    for d in sorted(comp):
        c = comp[d]
        pre = [x[1] for x in c if x[1]]
        print(d, "compactions", len(c), dict(collections.Counter(x[0] for x in c)),
              "preTokens median", int(statistics.median(pre)) if pre else None,
              "max", max(pre) if pre else None)
    bins = collections.Counter()
    for pk, _, _, _ in peaks:
        bins["<100k" if pk < 100e3 else "100-200k" if pk < 200e3
             else "200-270k" if pk < 270e3 else "270-400k" if pk < 400e3
             else ">=400k"] += 1
    print(dict(bins))
    print("top peaks:")
    for pk, mo, sid, mt in sorted(peaks, reverse=True)[:10]:
        print(f"  {pk:>9,} {mo} {sid} "
              f"{time.strftime('%m-%d %H:%M', time.localtime(mt))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
