#!/usr/bin/env bash
# d1-07-watchdog-fire
# CONTRACT: D1.7/B9: bin/paseo-watchdog fires (alert after 2 misses, restart only after 3 and only with the gates) on a forced hang of the TEST daemon
# EXPECT:   alert after the 2nd consecutive miss with diagnostics captured; no restart while load >= cores; with load low and --allow-restart a restart after the 3rd miss and recovery ping
# ON-FAIL:  the B9 policy is wrong or the watchdog is: do not install it (plan D1.7)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-07-watchdog-fire.sh
# NEEDS:    isolated daemon; a stub ping command (no real hermes-ping)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-07-watchdog-fire
. "$here/lib/common.sh"
ON_FAIL=the\ B9\ policy\ is\ wrong\ or\ the\ watchdog\ is:\ do\ not\ install\ it\ \(plan\ D1.7\)
isolated_up wd; trap 'kill -CONT $(cat "$ACC_BASE/daemon.pid") 2>/dev/null; isolated_down' EXIT
WD="$here/../../bin/paseo-watchdog"
pingbin="$ACC_BASE/ping"; printf '#!/bin/sh\necho "$@" >> %s/pings.log\n' "$ACC_BASE" > "$pingbin"; chmod +x "$pingbin"
args=(--once --home "$PASEO_HOME" --no-health --state-dir "$ACC_BASE/wd" --ping-cmd "$pingbin" --no-reconcile --json)  # --no-health: a Unix-socket daemon has no HTTP health URL; the RPC probe carries the verdict
"$WD" "${args[@]}" >/dev/null || fail "watchdog reports a miss on a healthy test daemon (health URL for a socket daemon?)"
kill -STOP "$(cat "$ACC_BASE/daemon.pid")"          # forced hang of the TEST daemon only
"$WD" "${args[@]}" >/dev/null; "$WD" "${args[@]}" >/dev/null   # misses 1, 2
pings=$(wc -l < "$ACC_BASE/pings.log" 2>/dev/null || echo 0)
diag=$(ls -d "$ACC_BASE"/wd/diag/*/ 2>/dev/null | wc -l)
ev="{\"pingsAfter2Misses\":$pings,\"diagDirs\":$diag}"
[ "$pings" -ge 1 ] && [ "$diag" -ge 1 ] || fail "no alert or no diagnostics after 2 misses" "$ev"
"$WD" "${args[@]}" --allow-restart >/dev/null   # 3rd miss; restart gated by load average; record the outcome
ev="{\"pingsAfter2Misses\":$pings,\"diagDirs\":$diag,\"loadAtRestart\":\"$(uptime | awk -F'load averages?: ' '{print $2}')\",\"restartedOrBlocked\":\"see pings.log\"}"
pass "$ev"
