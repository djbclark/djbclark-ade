#!/usr/bin/env bash
# d1-10-reopen-hook
# CONTRACT: V3 (adversary r7): agent.open.before fires again when an archived agent is reopened or an idle agent resumed, so the tool catalog is recomputed
# EXPECT:   the probe plugin logs one agent.open.before per open, reopen and resume of the same agent id
# ON-FAIL:  G1's orchestrator registration flow (create, merge id, reopen) cannot work; G1 must read config/orchestrators at jobs.submit time instead
# SCOPE:    second daemon only
# HOW:      bash tests/paseo-acceptance/d1-10-reopen-hook.sh
# NEEDS:    isolated daemon; the probe plugin; the reopen path (reopen-archived plugin or the CLI)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-10-reopen-hook
. "$here/lib/common.sh"
ON_FAIL=G1\'s\ orchestrator\ registration\ flow\ \(create\,\ merge\ id\,\ reopen\)\ cannot\ work\;\ G1\ must\ read\ config/orchestrators\ at\ jobs.submit\ time\ instead
isolated_up reopen; trap isolated_down EXIT
log="$ACC_BASE/origin.log"
pj plugin install "$here/fixtures/origin-probe-plugin" >/dev/null 2>&1 || skip "plugin install failed"
id=$(ORIGIN_LOG="$log" pj run -q --no-wait --provider "${PROBE_PROVIDER:-claude}" --title reopen "reply OK") || fail "create failed"
pj wait --timeout 120 "$id" >/dev/null 2>&1
n1=$(grep -c '"hook":"agent.open.before"' "$log")
pj archive "$id" >/dev/null 2>&1
echo "UNIMPLEMENTED reopen step: use the reopen-archived plugin's path, or 'paseo agent reload $id'; then 'paseo send $id hi'" >&2
pj agent reload "$id" >/dev/null 2>&1; pj send "$id" "reply OK again" >/dev/null 2>&1; pj wait --timeout 120 "$id" >/dev/null 2>&1
n2=$(grep -c '"hook":"agent.open.before"' "$log")
ev="{\"opensAfterCreate\":$n1,\"opensAfterReload\":$n2}"
[ "$n2" -gt "$n1" ] && pass "$ev"
fail "agent.open.before did not fire again" "$ev"
