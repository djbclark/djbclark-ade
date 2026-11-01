#!/usr/bin/env bash
# ro-health: Is the daemon's health endpoint up, and does a real RPC answer in time?
# CONTRACT: B9: both signals are measured, because health can answer while RPCs starve (#2753)
# EXPECT:   GET /api/health returns {status:ok} in under 5 s and 'paseo ls --json' returns a JSON array in under 20 s
# ON-FAIL:  the watchdog's two probes are wrong or the daemon is wedged: do not build on the live daemon until understood
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-health.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-health
. "$here/../lib/common.sh"
ON_FAIL="the watchdog's two probes are wrong or the daemon is wedged: do not build on the live daemon until understood"
url="${PASEO_HEALTH_URL:-http://127.0.0.1:7263}/api/health"
h=$(curl -s -m 5 -o /dev/null -w "%{http_code} %{time_total}" "$url") || h="000 0"
s=$(date +%s); timeout 20 paseo ls --json > "${TMPDIR:-/tmp}/ro-health.$$.json" 2>/dev/null; rc=$?; e=$(( $(date +%s) - s ))
valid=$(python3 -c "import json,sys; print(isinstance(json.load(open(sys.argv[1])),list))" "${TMPDIR:-/tmp}/ro-health.$$.json" 2>/dev/null || echo False)
rm -f "${TMPDIR:-/tmp}/ro-health.$$.json"
ev=$(printf "{\"health\":\"%s\",\"rpcRc\":%s,\"rpcSeconds\":%s,\"rpcIsList\":\"%s\"}" "$h" "$rc" "$e" "$valid")
case "$h" in 200*) [ "$rc" = 0 ] && [ "$valid" = True ] && pass "$ev";; esac
fail "health=$h rpc rc=$rc" "$ev"
