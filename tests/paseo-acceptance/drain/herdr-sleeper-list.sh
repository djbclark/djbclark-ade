#!/usr/bin/env bash
# herdr-sleeper-list
# CONTRACT: D0.2: no idle-agent sleeper journal entry holds a session before herdr-sleeper is disabled
# EXPECT:   every journal is empty, exit 0
# ON-FAIL:  a sleeping agent holds a session UUID: wake it or resume it as a Paseo agent before disabling
# SCOPE:    read-only: reads the journal files only. It does NOT run `herdr-sleeper list`: that command calls
#           heal_watcher() first, which can start the watcher.
# HOW:      bash tests/paseo-acceptance/drain/herdr-sleeper-list.sh
# NEEDS:    python3; HERDR_SLEEPER_STATE overrides ~/.local/state/herdr-sleeper
# OUTPUT:   {"tool":"herdr-sleeper","held":N,"evidence":[one line per journal entry]}; exit 0 / 1 / 77
# STATUS:   run live 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 - "$here" "${HERDR_SLEEPER_STATE:-$HOME/.local/state/herdr-sleeper}" <<'PY'
import glob, json, os, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
root = sys.argv[2]
TOOL = "herdr-sleeper"
if not os.path.isdir(root):
    sys.exit(dc.emit(TOOL, 0, [], [f"no state dir {root}: nothing ever slept here"]))
# the default session keeps the root; named sessions live under sessions/<name>/ (plugins/herdr-sleeper/herdr-sleeper:149-155)
journals = [os.path.join(root, "sleeping.json")] + sorted(glob.glob(os.path.join(root, "sessions", "*", "sleeping.json")))
ev, held = [], 0
for j in journals:
    if not os.path.isfile(j):
        continue
    try:
        with open(j, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        sys.exit(dc.cannot(TOOL, f"journal {j} unreadable: {type(e).__name__}"))
    if not isinstance(data, dict):
        sys.exit(dc.cannot(TOOL, f"journal {j} is not an object"))
    sess = os.path.basename(os.path.dirname(j)) if j != journals[0] else "default"
    for pane, e in sorted(data.items()):
        held += 1
        e = e if isinstance(e, dict) else {}
        ev.append(f"{sess}:{pane} {e.get('name') or e.get('label') or '?'} {e.get('kind', 'claude')} {e.get('phase', 'asleep')} "
                  f"slept {e.get('slept_at') or '?'} uuid {str(e.get('uuid') or '?')[:8]} cwd {e.get('cwd') or '?'} '{(e.get('title') or '')[:40]}'")
sys.exit(dc.emit(TOOL, held, ev))
PY
exit $?
