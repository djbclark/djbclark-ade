#!/usr/bin/env bash
# d1-05-restart-persistence
# CONTRACT: D1.5: a daemon restart loses no queued prompt, no pending notifyOnFinish and no schedule
# EXPECT:   after 'paseo restart' of the TEST daemon: the queued send is delivered once, the notification arrives once, the schedule exists and run-once works
# ON-FAIL:  G1 and G3 persist those records themselves and reconcile after every restart (they already assume so)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-05-restart-persistence.sh
# NEEDS:    isolated daemon; one cheap provider
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-05-restart-persistence
. "$here/lib/common.sh"
ON_FAIL=G1\ and\ G3\ persist\ those\ records\ themselves\ and\ reconcile\ after\ every\ restart\ \(they\ already\ assume\ so\)
isolated_up restart; trap isolated_down EXIT
P=${PROBE_PROVIDER:-claude}
a=$(pj run -q --no-wait --provider "$P" --mode bypass --title busy "Run 'sleep 90' then reply BUSY-DONE.") || fail "create failed"
pj send --no-wait --behavior steer "$a" "Then also reply QUEUED-MARK." >/dev/null 2>&1
sid=$(pj schedule create --every 10m "reply SCHED-RAN" -q 2>/dev/null)   # UNVERIFIED flag names: read 'paseo schedule create --help'
pj restart >/dev/null 2>&1                                           # the TEST daemon only (pj pins --home)
sleep 15
pj status >/dev/null 2>&1 || fail "test daemon did not come back"
pj wait --timeout 240 "$a" >/dev/null 2>&1
q=$(pj logs "$a" 2>/dev/null | grep -c QUEUED-MARK)
sc=$(pj schedule ls --json 2>/dev/null | grep -c "$sid")
ev="{\"queuedMarkerSeen\":$q,\"scheduleListed\":$sc,\"notifyOnFinish\":\"MANUAL: needs an MCP create_agent with notifyOnFinish; record the parent's inbox\"}"
[ "$q" -ge 1 ] && [ "$sc" -ge 1 ] && pass "$ev"
fail "state lost across restart" "$ev"
