#!/usr/bin/env bash
# d1-09-deadman
# CONTRACT: D1.9: the dead-man check pages on a daemon killed while awake and on a network cut while awake, never on sleep, and a failed wake hook does not silence it
# EXPECT:   four scenarios give: sleep no page; heartbeat reports failing page; heartbeat stale with no marker page; sleep marker, failed wake hook (a later stale heartbeat clears the old marker) then stale, page
# ON-FAIL:  the dead-man design is wrong: do not deploy it (plan D1.9)
# SCOPE:    second daemon only (pure local: temp dirs, a stub ping, no daemon, no network)
# HOW:      bash tests/paseo-acceptance/d1-09-deadman.sh   (uses a fake clock via --now; the real ssh forced-command path is checked on vps-primary by hand)
# NEEDS:    python3
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-09-deadman
. "$here/lib/common.sh"
ON_FAIL=the\ dead-man\ design\ is\ wrong:\ do\ not\ deploy\ it\ \(plan\ D1.9\)
export DEADMAN_DIR="$(mktemp -d)"; trap 'rm -rf "$DEADMAN_DIR"' EXIT
W="$here/deadman/write-heartbeat"; C="$here/deadman/deadman-check"
hb() { printf '{"kind":"heartbeat","ts":%s,"health":%s,"rpc":%s,"misses":0}' "$1" "${2:-true}" "${3:-true}" | "$W"; }
mk_ping="$DEADMAN_DIR/ping.sh"; printf '#!/bin/sh\necho "$@" >> %s/pings\n' "$DEADMAN_DIR" > "$mk_ping"; chmod +x "$mk_ping"
chk() { rm -f "$DEADMAN_DIR/paged.json"; "$C" --now "$1" --ping-cmd "$mk_ping" >/dev/null; echo $?; }
t0=1000000
hb $t0
printf '{"kind":"sleep","ts":%s}' $((t0+60)) | "$W"
r1=$(chk $((t0+3600)))                          # asleep an hour: no page
printf '{"kind":"wake","ts":%s}' $((t0+7200)) | "$W"; hb $((t0+7200))
r2=$(chk $((t0+7200+60)))                       # healthy after wake: no page
hb $((t0+7300)) false true
r3=$(chk $((t0+7400)))                          # daemon failing while awake: page
hb $((t0+7500)); printf '{"kind":"sleep","ts":%s}' $((t0+7600)) | "$W"; hb $((t0+7700))   # wake hook failed; a later heartbeat clears the marker
r4=$(chk $((t0+7700+3600)))                     # network cut while awake: stale, no marker: page
ev="{\"sleep\":$r1,\"healthyAfterWake\":$r2,\"daemonFailing\":$r3,\"failedWakeThenCut\":$r4}"
[ "$r1" = 0 ] && [ "$r2" = 0 ] && [ "$r3" = 1 ] && [ "$r4" = 1 ] && pass "$ev"
fail "dead-man scenarios differ from D1.9" "$ev"
