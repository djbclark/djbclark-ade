#!/usr/bin/env bash
# ro-ls: Can the agent list be read as JSON, with the fields the toolchain relies on?
# CONTRACT: B1: the daemon is the only fleet registry; ls --json carries id, shortId, name, provider, status, cwd
# EXPECT:   a JSON array whose items have id, status, provider; counts running and idle
# ON-FAIL:  djbclark-ade tools that parse ls --json (paseo-bypass-watch, G1 reconcile) must be re-pointed
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-ls.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-ls
. "$here/../lib/common.sh"
ON_FAIL="djbclark-ade tools that parse ls --json (paseo-bypass-watch, G1 reconcile) must be re-pointed"
out=$(timeout 30 paseo ls --json 2>/dev/null) || fail "paseo ls failed"
ev=$(printf "%s" "$out" | python3 -c "
import json,sys,collections
a=json.load(sys.stdin)
need={\"id\",\"status\",\"provider\"}
bad=[x.get(\"id\") for x in a if not need<=set(x)]
c=collections.Counter(x[\"status\"] for x in a)
print(json.dumps({\"agents\":len(a),\"byStatus\":c,\"missingFields\":len(bad)},separators=(\",\",\":\")))") || fail "unparseable output"
case "$ev" in *\"missingFields\":0*) pass "$ev";; *) fail "items lack required fields" "$ev";; esac
