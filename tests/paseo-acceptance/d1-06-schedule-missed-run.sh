#!/usr/bin/env bash
# d1-06-schedule-missed-run
# CONTRACT: D1.6/F2: what a Paseo schedule does when its due time passes while the Mac sleeps (run once on wake, never, or many times)
# EXPECT:   a schedule due during sleep runs exactly once after wake; the result is recorded either way
# ON-FAIL:  schedules that would be lost stay on launchd (F2)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      SEMI-MANUAL: the script creates the schedule, prints when to sleep the Mac (pmset sleepnow) and the wake time, then you rerun it with --after-wake
# NEEDS:    isolated daemon; a human at the Mac for the sleep; djbclark's yes to sleep the machine (it may host other sessions)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-06-schedule-missed-run
. "$here/lib/common.sh"
ON_FAIL=schedules\ that\ would\ be\ lost\ stay\ on\ launchd\ \(F2\)
isolated_up sleep; trap isolated_down EXIT
if [ "${1:-}" != "--after-wake" ]; then
  due=$(date -v+3M +%H:%M 2>/dev/null || gdate -d '+3 min' +%H:%M)
  pj schedule create --cron "$(date -v+3M '+%M %H * * *' 2>/dev/null || gdate -d '+3 min' '+%M %H * * *')" "reply SLEEP-SCHED-RAN" >/dev/null 2>&1   # UNVERIFIED flags
  echo "Schedule due at $due. Sleep the Mac NOW (pmset sleepnow), wake it after $(date -v+6M +%H:%M 2>/dev/null), then run: $0 --after-wake" >&2
  trap - EXIT; echo "$PASEO_HOME" > "${TMPDIR:-/tmp}/ade-acc-sleep.home"; exit 77
fi
skip "after-wake half is UNIMPLEMENTED: count 'paseo schedule logs' entries for the missed slot; one entry is the expected outcome"
