#!/usr/bin/env bash
# ro-permit-ls: Can pending permission cards be listed (and does an empty list parse)?
# CONTRACT: B3: cards are visible to a parent or G4 through 'paseo permit ls'; question and OMP ask cards are listed too
# EXPECT:   rc 0 and a JSON array (possibly empty)
# ON-FAIL:  B3 and G4's input is unreadable: cards would only reach the operator
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-permit-ls.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-permit-ls
. "$here/../lib/common.sh"
ON_FAIL="B3 and G4's input is unreadable: cards would only reach the operator"
out=$(timeout 30 paseo permit ls --json 2>/dev/null); rc=$?
n=$(printf "%s" "$out" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null) || fail "unparseable (rc=$rc)"
pass "{\"pending\":$n}"
