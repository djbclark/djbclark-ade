#!/usr/bin/env bash
# watchdog-selftest
# CONTRACT: V1/V2/V4 (adversary r7) carried by bin/paseo-watchdog's B4.3 assertion; B9 restart gates
# EXPECT:   six cases: b43-fail-blocks-restart; herald-absent-passes; herald-flag-true-alerts; herald-file-missing-alerts; plugin-ls-empty-014-alerts; plugin-ls-empty-013-passes
# ON-FAIL:  the watchdog could restart a daemon with the destructive cleanup flags on, or hide a failed check: do not install it
# SCOPE:    hermetic (fake paseo on a temp path; no daemon touched)
# HOW:      ~/ops/site-private/bin/bg bash tests/paseo-acceptance/watchdog-selftest.sh
# NEEDS:    python3, bin/paseo-watchdog
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=watchdog-selftest
. "$here/lib/common.sh"
ON_FAIL=the\ watchdog\ could\ restart\ a\ daemon\ with\ the\ destructive\ cleanup\ flags\ on\,\ or\ hide\ a\ failed\ check:\ do\ not\ install\ it
WD="$here/../../bin/paseo-watchdog"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home/plugin-data/herald"
cat > "$T/bin/paseo" <<'FAKE'
#!/bin/sh
# fake paseo: FAKE_PLUGINS (file with the plugin ls --json text), FAKE_VERSION, FAKE_LS_RC
while [ "$1" = "--home" ] || [ "$1" = "--host" ]; do shift 2; done
case "$1 $2" in
  "plugin ls") cat "$FAKE_PLUGINS"; exit 0;;
  "status --json") printf '{"daemonVersion":"%s"}' "$FAKE_VERSION"; exit 0;;
  "ls --json") [ "${FAKE_LS_RC:-0}" = 0 ] && echo '[]'; exit "${FAKE_LS_RC:-0}";;
esac
exit 0
FAKE
chmod +x "$T/bin/paseo"
export FAKE_PLUGINS="$T/plugins.json" FAKE_VERSION=0.14.0
b43() { python3 "$WD" --b43-only --paseo "$T/bin/paseo" --home "$T/home" --state-dir "$T/st" --ping-cmd true; }
res=""; bad=0
chk() { # name expected_rc actual_rc
  res="$res\"$1\":$3,"; [ "$2" = "$3" ] || bad=1; }
echo '[{"id":"herald","enabled":true,"status":"running"}]' > "$FAKE_PLUGINS"
echo '{"cleanup":{"deleteHelpers":true}}' > "$T/home/plugin-data/herald/config.json"; b43 >/dev/null; chk herald-flag-true-alerts 1 $?
rm "$T/home/plugin-data/herald/config.json"; b43 >/dev/null; chk herald-file-missing-alerts 1 $?
echo '[{"id":"other","enabled":true,"status":"running"}]' > "$FAKE_PLUGINS"; b43 >/dev/null; chk herald-absent-passes 0 $?
echo -n '' > "$FAKE_PLUGINS"; FAKE_VERSION=0.14.0 b43 >/dev/null; chk plugin-ls-empty-014-alerts 1 $?
FAKE_VERSION=0.13.4 b43 >/dev/null; chk plugin-ls-empty-013-passes 0 $?
# V1: assertion failing + 3 misses + load permitting: the restart command must not run
echo '[{"id":"herald","enabled":true,"status":"running"}]' > "$FAKE_PLUGINS"
echo '{"cleanup":{"deleteHelpers":true}}' > "$T/home/plugin-data/herald/config.json"
mkdir -p "$T/st"; echo '{"consecutiveMisses":2,"alerted":true}' > "$T/st/state.json"
rm -f "$T/restarted"
FAKE_LS_RC=1 python3 "$WD" --once --no-health --allow-restart --no-reconcile --paseo "$T/bin/paseo" --home "$T/home" --state-dir "$T/st" --ping-cmd true --restart-cmd touch "$T/restarted" >/dev/null
[ -e "$T/restarted" ] && chk b43-fail-blocks-restart 0 1 || chk b43-fail-blocks-restart 0 0
# control (only when load allows a restart): with the assertion passing the same state does restart
cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)
if awk -v l="$(uptime | awk -F'load average[s]*: ' '{print $2}' | cut -d, -f1 | tr -d ' ')" -v c="$cores" 'BEGIN{exit !(l+0<c)}'; then
  echo '{"cleanup":{"deleteHelpers":false}}' > "$T/home/plugin-data/herald/config.json"
  echo '{"consecutiveMisses":2,"alerted":true}' > "$T/st/state.json"
  FAKE_LS_RC=1 python3 "$WD" --once --no-health --allow-restart --no-reconcile --paseo "$T/bin/paseo" --home "$T/home" --state-dir "$T/st" --ping-cmd true --restart-cmd touch "$T/restarted" >/dev/null
  [ -e "$T/restarted" ] && chk control-restarts-when-clean 0 0 || chk control-restarts-when-clean 0 1
else res="$res\"control\":\"skipped-high-load\","; fi
ev="{${res%,}}"
[ "$bad" = 0 ] && pass "$ev"
fail "a watchdog assertion case differs" "$ev"
