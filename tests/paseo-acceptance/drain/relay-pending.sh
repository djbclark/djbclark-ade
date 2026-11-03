#!/usr/bin/env bash
# relay-pending
# CONTRACT: D0.2 item b: no queued, sending or unanswered relay message exists before session-finder is disabled
# EXPECT:   no deferred message in a non-final state and no open ack expectation, exit 0
# ON-FAIL:  an unsent or unacked message exists: deliver and verify it (AGENTS.md order 10), or retire it with a reason, before disabling
# SCOPE:    read-only for messages. `relay.py --pending --json` runs the same bounded (3 s) ack collection every listing runs
#           (it closes expectations whose reply is already in a transcript); it never sends, cancels or retires anything.
#           `--status ID` (one record, changes nothing) is for the operator once a held id is known.
# HOW:      bash tests/paseo-acceptance/drain/relay-pending.sh
# NEEDS:    python3; RELAY_PY overrides ~/src/djbclark-ade/skills/session-finder/relay.py (the main checkout, on master)
# OUTPUT:   {"tool":"relay.py","held":N,"evidence":[...],"notes":[final-state counts]}; exit 0 / 1 / 77
# STATUS:   run live 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 - "$here" "${RELAY_PY:-$HOME/src/djbclark-ade/skills/session-finder/relay.py}" <<'PY'
import collections, json, os, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
relay = sys.argv[2]
TOOL = "relay.py"
FINAL = {"delivered", "cancelled", "expired", "failed"}   # relay.py DEFER_FINAL; "failed" is final but listed in the notes
if not os.path.isfile(relay):
    sys.exit(dc.cannot(TOOL, f"no {relay}"))
rc, out, err = dc.run([sys.executable, relay, "--pending", "--json"], 45)
if rc != 0:
    sys.exit(dc.cannot(TOOL, f"relay.py --pending --json rc={rc}: {err.strip()[:120]}"))
try:
    rows = json.loads(out)
    assert isinstance(rows, list)
except (ValueError, AssertionError):
    sys.exit(dc.cannot(TOOL, "relay.py --pending --json printed something other than a JSON list"))
def tgt(r):
    t = r.get("target")
    return (t.get("name") or t.get("id") or "?") if isinstance(t, dict) else str(t or "?")
ev, counts = [], collections.Counter()
for r in rows:
    if not isinstance(r, dict):
        continue
    kind = r.get("kind") or "message"
    counts[(kind, r.get("state"))] += 1
    age = int(r.get("age_s") or 0) // 60
    if kind == "expect":
        if r.get("state") == "open":
            flag = "ASSUMED LOST" if r.get("assumed_lost") else ("OVERDUE" if r.get("overdue") else "waiting")
            ev.append(f"expect-ack {r.get('id')} open {flag} to {tgt(r)} {age}m old")
    elif r.get("state") not in FINAL:
        look = r.get("look") if isinstance(r.get("look"), dict) else {}
        ev.append(f"message {r.get('id')} {r.get('state')} to {tgt(r)} {age}m old {look.get('why') or ''}")
notes = ["not held (final or settled): " + ", ".join(f"{k}/{s}={n}" for (k, s), n in sorted(counts.items(), key=str) if (k == "message" and s in FINAL) or (k == "expect" and s != "open"))]
sys.exit(dc.emit(TOOL, len(ev), ev, notes))
PY
exit $?
