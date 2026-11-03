#!/usr/bin/env bash
# bigteam-inboxes
# CONTRACT: D0.2: no unanswered lead message sits in a bigteam jobs inbox
# EXPECT:   every `## MSG N` in a jobs/NAME.inbox.md has a `REPLY N:` line in jobs/NAME.replies.md, exit 0
# ON-FAIL:  an unanswered inbox message exists: its slice answers it (or the lead retires it) before bigteam's inbox path is disabled
# SCOPE:    read-only: reads inbox and replies files only
# HOW:      bash tests/paseo-acceptance/drain/bigteam-inboxes.sh
# NEEDS:    python3; BIGTEAM_STATE overrides ~/.local/state/bigteam
# OUTPUT:   {"tool":"bigteam-inboxes","held":N,"evidence":["PATH#N", ...]}; exit 0 / 1 / 77
# STATUS:   run live 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 - "$here" "${BIGTEAM_STATE:-$HOME/.local/state/bigteam}" <<'PY'
import glob, os, re, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
root = sys.argv[2]
TOOL = "bigteam-inboxes"
if not os.path.isdir(root):
    sys.exit(dc.cannot(TOOL, f"no {root}"))
inboxes = sorted(set(glob.glob(os.path.join(root, "*", "jobs", "*.inbox.md"))) | set(glob.glob(os.path.join(root, "jobs", "*.inbox.md"))))
ev, unreadable = [], 0
for ib in inboxes:
    rep = ib[: -len(".inbox.md")] + ".replies.md"
    try:
        with open(ib, encoding="utf-8", errors="replace") as fh:
            msgs = re.findall(r"^## MSG (\d+)", fh.read(), re.M)
        replied = set()
        if os.path.exists(rep):
            with open(rep, encoding="utf-8", errors="replace") as fh:
                replied = set(re.findall(r"^REPLY (\d+):", fh.read(), re.M))
    except OSError:
        unreadable += 1
        ev.append(f"{os.path.relpath(ib, root)} unreadable")
        continue
    for n in msgs:
        if n not in replied:
            ev.append(f"{os.path.relpath(ib, root)}#{n}")
notes = [f"scanned {len(inboxes)} inboxes under {root}"]
sys.exit(dc.emit(TOOL, len(ev), ev, notes))
PY
exit $?
