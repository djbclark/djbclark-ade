#!/usr/bin/env bash
# ro-inspect: Does 'paseo agent inspect' return structured detail for one agent?
# CONTRACT: D1.3/D1.4 evidence reads agent state through inspect (status, cwd, lineage fields)
# EXPECT:   rc 0 and JSON for the first listed agent; prints only the key names, never values
# ON-FAIL:  probes D1.3 and D1.4 need another way to read lineage and workspace
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-inspect.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-inspect
. "$here/../lib/common.sh"
ON_FAIL="probes D1.3 and D1.4 need another way to read lineage and workspace"
id=${1:-$(timeout 30 paseo ls --json 2>/dev/null | python3 -c "import json,sys; a=json.load(sys.stdin); print(a[0][\"id\"] if a else \"\")")}
[ -n "$id" ] || skip "no agent to inspect"
out=$(timeout 30 paseo agent inspect --json "$id" 2>/dev/null) || fail "inspect failed for $id"
keys=$(printf "%s" "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(sorted(d)[:40]))") || fail "unparseable"
pass "{\"keys\":$keys}"
