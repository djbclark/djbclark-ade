#!/usr/bin/env bash
# d1-02-card-option
# CONTRACT: D1.2/B3: a parent can answer a question card's OPTION (not only allow/deny) through the surface a parent has
# EXPECT:   the agent's next turn shows the chosen option's text
# ON-FAIL:  B3 and G4 are redesigned: question cards go to the operator, never to a parent
# SCOPE:    second daemon only
# HOW:      bash tests/paseo-acceptance/d1-02-card-option.sh   (creates one claude agent on the isolated daemon)
# NEEDS:    isolated daemon; claude logged in; MCP respond_to_permission is exercised by hand in step (b) (printed, not automated)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-02-card-option
. "$here/lib/common.sh"
ON_FAIL=B3\ and\ G4\ are\ redesigned:\ question\ cards\ go\ to\ the\ operator\,\ never\ to\ a\ parent
isolated_up card; trap isolated_down EXIT
id=$(pj run -q --no-wait --provider claude --mode default --title card-probe \
  "Use the AskUserQuestion tool once: ask 'Pick a colour' with exactly two options, 'red' and 'blue'. Then say which you got.") || fail "create failed"
card=""
for i in $(seq 1 60); do card=$(pj permit ls --json 2>/dev/null); [ "$card" != "[]" ] && [ -n "$card" ] && break; sleep 2; done
[ "$card" = "[]" ] && fail "no question card appeared" "{\"agent\":\"$id\"}"
printf '%s' "$card" > "$ACC_BASE/card.json"
keys=$(printf '%s' "$card" | python3 -c "import json,sys; print(json.dumps(sorted(json.load(sys.stdin)[0])))")
req=$(printf '%s' "$card" | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d.get('id') or d.get('requestId') or '')")   # UNVERIFIED key
# (a) CLI: allow with modified input carrying the chosen option. UNVERIFIED answer shape: adjust from card.json.
pj permit allow --input '{"answers":{"Pick a colour":"blue"}}' "$id" "$req" >/dev/null 2>&1
pj wait --timeout 120 "$id" >/dev/null 2>&1
log=$(pj logs "$id" 2>/dev/null)
if printf '%s' "$log" | grep -qi 'blue'; then pass "{\"surface\":\"permit allow --input\",\"cardKeys\":$keys}"; fi
echo "(a) CLI answer did not show 'blue'. Step (b), by hand: from a second agent on this daemon call MCP respond_to_permission with the same input; then rerun the grep on 'paseo logs $id'." >&2
fail "CLI path did not carry the option" "{\"cardKeys\":$keys,\"cardFile\":\"$ACC_BASE/card.json\"}"
