#!/usr/bin/env python3
"""Per-day self-slash command and failure stats from self-slash.log.

Counts slash/$ commands sent, distinct agents active, and the top normalized
refusal/failure/timeout message shapes, per day over the last --days days.
Promoted 2026-11-05 from the 2026-10-27 one-off selfslash-log-by-day.py.
"""
import argparse
import collections
import re
from pathlib import Path

LINE_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (\S+) (\S+?): (.*)$")
SENT_RX = re.compile(r"sent (/\S+|\$\S+)")
ID_RX = re.compile(r"[0-9a-f]{8}-[0-9a-f-]{27}")
FAIL_RX = re.compile(
    r"refus|fail|NOT|exit|error|cooldown|stale|kept|abort|gave up|timeout|skip", re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="trailing days (default 7)")
    ap.add_argument("--log", default=str(Path.home() / ".local/state/self-slash.log"))
    args = ap.parse_args()

    try:
        lines = Path(args.log).read_text(errors="replace").splitlines()
    except OSError as e:
        print(f"cannot read {args.log}: {e}")
        return 1
    want = set()
    import datetime
    today = datetime.date.today()
    for i in range(args.days):
        want.add(str(today - datetime.timedelta(days=i)))

    sent = collections.defaultdict(collections.Counter)
    other = collections.defaultdict(collections.Counter)
    agents = collections.defaultdict(set)
    for line in lines:
        m = LINE_RX.match(line)
        if not m:
            continue
        d, _t, _host, pane, msg = m.groups()
        if d not in want:
            continue
        mm = SENT_RX.match(msg)
        if mm:
            sent[d][mm.group(1)] += 1
            agents[d].add(pane)
        else:
            key = ID_RX.sub("<id>", msg)[:70]
            if FAIL_RX.search(msg):
                other[d][key] += 1

    for d in sorted(want, reverse=True):
        if d not in sent and d not in other:
            continue
        print(d, dict(sent[d]), "distinct agents:", len(agents[d]))
        for k, v in other[d].most_common(8):
            print("   ", v, k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
