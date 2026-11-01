#!/usr/bin/env bash
# d1-07c-watchdog-soak
# CONTRACT: D1.7/B9: the watchdog does NOT restart a healthy daemon during one forced load incident (false-positive soak)
# EXPECT:   10 minutes with load above the core count and a healthy test daemon: zero restarts, at most one alert, no 'restarted' action
# ON-FAIL:  the watchdog's thresholds are wrong: do not enable --allow-restart (plan D1.7)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-07c-watchdog-soak.sh   (raises the Mac's load for 10 minutes: needs djbclark's yes, it slows every other session)
# NEEDS:    isolated daemon; a CPU burner of one process per core, killed by saved PID at the end
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-07c-watchdog-soak
. "$here/lib/common.sh"
ON_FAIL=the\ watchdog\'s\ thresholds\ are\ wrong:\ do\ not\ enable\ --allow-restart\ \(plan\ D1.7\)
isolated_up soak; trap 'kill $burners 2>/dev/null; isolated_down' EXIT
WD="$here/../../bin/paseo-watchdog"
cores=$(sysctl -n hw.ncpu 2>/dev/null || nproc)
burners=""; for i in $(seq 1 "$cores"); do ( while :; do :; done ) & burners="$burners $!"; done
restarts=0; end=$(( $(date +%s) + 600 ))
while [ "$(date +%s)" -lt "$end" ]; do
  out=$("$WD" --once --json --allow-restart --home "$PASEO_HOME" --no-health \
        --state-dir "$ACC_BASE/wd" --ping-cmd true --no-reconcile 2>/dev/null)
  case "$out" in *'"restarted"'*) restarts=$((restarts+1));; esac
  sleep 30
done
ev="{\"restarts\":$restarts,\"cores\":$cores}"
[ "$restarts" = 0 ] && pass "$ev"
fail "the watchdog restarted a healthy daemon" "$ev"
