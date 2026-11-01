#!/usr/bin/env bash
# ro-plugins: Is 'plugin ls --json' parseable, and do the B4.3 conditions hold today?
# CONTRACT: B4.3 and adversary r7 V1/V2/V4: janitor disabled or its three settings false; herald cleanup.deleteHelpers exactly false; empty output only on 0.13
# EXPECT:   an array with id, enabled, status; bin/paseo-watchdog --b43-only exits 0
# ON-FAIL:  the janitor or herald could archive-and-delete agents: alert djbclark before anything else runs
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-plugins.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-plugins
. "$here/../lib/common.sh"
ON_FAIL="the janitor or herald could archive-and-delete agents: alert djbclark before anything else runs"
out=$(timeout 30 paseo plugin ls --json 2>/dev/null) || fail "plugin ls failed"
ev=$(printf "%s" "$out" | python3 -c "
import json,sys
a=json.load(sys.stdin)
print(json.dumps({\"plugins\":len(a),\"running\":[p[\"id\"] for p in a if p.get(\"status\")==\"running\"],\"disabled\":[p[\"id\"] for p in a if not p.get(\"enabled\")]}))") || fail "unparseable plugin ls"
b=$("$here/../../../bin/paseo-watchdog" --b43-only 2>&1); rc=$?
[ "$rc" = 0 ] && pass "{\"list\":$ev,\"b43\":$b}"
fail "B4.3 assertion rc=$rc: $b" "{\"list\":$ev}"
