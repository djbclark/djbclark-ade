#!/usr/bin/env bash
# acp-dispatch-auto-resume
# CONTRACT: D0.2: no auto-resume job of acp-dispatch is pending
# EXPECT:   no unclosed record with auto_resume.state in (scheduled, waiting-headroom, resuming), exit 0
# ON-FAIL:  a resume is pending: let it finish or cancel it (`acp-dispatch` record `closed`) before disabling
# SCOPE:    read-only: reads the dispatch records and asks `launchctl print` whether a pending label is loaded
# HOW:      bash tests/paseo-acceptance/drain/acp-dispatch-auto-resume.sh
# NEEDS:    python3; ACP_DISPATCH_STATE overrides ~/.local/state/bigteam (bin/acp-dispatch STATE_ROOT)
# OUTPUT:   {"tool":"acp-dispatch-auto-resume","held":N,"evidence":[...]}; exit 0 / 1 / 77
# STATUS:   run live 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 - "$here" "${ACP_DISPATCH_STATE:-$HOME/.local/state/bigteam}" <<'PY'
import glob, json, os, shutil, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
root = sys.argv[2]
TOOL = "acp-dispatch-auto-resume"
PENDING = ("scheduled", "waiting-headroom", "resuming")   # bin/acp-dispatch AUTO_RESUME_PENDING
if not os.path.isdir(root):
    sys.exit(dc.cannot(TOOL, f"no state root {root}"))
# the same record set bin/acp-dispatch record_paths() reads: jobs/*.json and */jobs/*.json
paths = sorted(set(glob.glob(os.path.join(root, "jobs", "*.json"))) | set(glob.glob(os.path.join(root, "*", "jobs", "*.json"))))
uid = os.getuid()
have_lc = shutil.which("launchctl") is not None
ev, unreadable = [], 0
for p in paths:
    try:
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        unreadable += 1
        continue
    ar = rec.get("auto_resume") if isinstance(rec, dict) else None
    if not isinstance(ar, dict) or ar.get("state") not in PENDING or rec.get("closed"):
        continue
    label = ar.get("label") or ""
    loaded = "launchctl unavailable"
    if have_lc and label:
        rc, _o, _e = dc.run(["launchctl", "print", f"gui/{uid}/{label}"], 10)
        loaded = "label loaded" if rc == 0 else ("label NOT loaded (reap would resubmit)" if rc is not None else "launchctl check failed")
    ev.append(f"{os.path.relpath(p, root)} state {ar.get('state')} attempt {ar.get('attempt')} not_before {ar.get('not_before_iso') or '?'} {loaded}")
notes = [f"scanned {len(paths)} records under {root}"]
if unreadable:
    notes.append(f"{unreadable} records unreadable as JSON (not counted; they predate or are not dispatch records)")
sys.exit(dc.emit(TOOL, len(ev), ev, notes))
PY
exit $?
