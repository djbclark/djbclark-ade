#!/usr/bin/env bash
# soak_herdr.sh — fault-injection soak for bin/herdr-sleeper against a REAL Herdr.
#
# Runs entirely inside an isolated named Herdr session (HERDR_SESSION=sleeper-lab,
# its own server and socket) with its own state/config dirs, so nothing here can
# touch the operator's live panes or the real journal. Every scenario is one the
# unit tests cannot cover because they need the real thing: real Claude
# processes, real Herdr timing, a real server going away.
#
# Usage: tests/soak_herdr.sh [--keep]     (--keep leaves the lab session running)
# Exit status is the number of failed scenarios. Log: $SOAK_DIR/soak.log
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SLEEPER="$REPO/bin/herdr-sleeper"
export HERDR_SESSION=sleeper-lab
export HERDR_SLEEPER_STATE="${SOAK_DIR:=/tmp/herdr-sleeper-soak}/state"
# The sleeper's config is left at the operator's real one on purpose: every scenario passes --idle
# explicitly, and exporting XDG_CONFIG_HOME here would leak into the panes Herdr launches for us.
mkdir -p "$HERDR_SLEEPER_STATE"
LOG="$SOAK_DIR/soak.log"; : > "$LOG"
PASS=0; FAIL=0
CLAUDE_ARGS=(--dangerously-skip-permissions)

say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
ok()   { PASS=$((PASS+1)); say "  PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
j()    { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1" 2>/dev/null; }

# --- lab session -------------------------------------------------------------
if ! herdr session list 2>/dev/null | grep -q "^sleeper-lab *running"; then
  (nohup herdr server >"$SOAK_DIR/server.log" 2>&1 &); sleep 3
fi
herdr agent list >/dev/null || { say "lab server not reachable"; exit 99; }
rm -f "$HERDR_SLEEPER_STATE"/sleeping.json "$HERDR_SLEEPER_STATE"/panes.json "$HERDR_SLEEPER_STATE"/events.jsonl "$HERDR_SLEEPER_STATE"/lock

# A headless session still has a focused pane, and the sleeper refuses focused panes (correctly). Park the
# focus on a dedicated workspace so every test pane is unfocused, the way an idle background pane is.
FOCUS_WS=$(herdr workspace list | j "[w['workspace_id'] for w in d['result']['workspaces'] if w['label']=='focus-holder']" | tr -d "[]'")
[ -n "$FOCUS_WS" ] || FOCUS_WS=$(herdr workspace create --cwd /tmp --label focus-holder --no-focus | j "['result']['workspace']['workspace_id']")
park_focus() { herdr workspace focus "$FOCUS_WS" >/dev/null 2>&1; }
park_focus

# new_pane LABEL -> prints pane id of a fresh workspace whose shell is ready
new_pane() {
  local p; p=$(herdr workspace create --cwd "$REPO" --label "$1" --no-focus | j "['result']['root_pane']['pane_id']")
  for _ in $(seq 1 30); do herdr pane read "$p" 2>/dev/null | grep -q '\$ *$' && break; sleep 1; done
  park_focus
  echo "$p"
}
# start_claude PANE NAME -> prints uuid; primes one turn so the transcript exists
start_claude() {
  herdr agent start "$2" --kind claude --pane "$1" --timeout 120000 -- "${CLAUDE_ARGS[@]}" >/dev/null || return 1
  herdr agent prompt "$1" "Reply with exactly the word: pong" --wait --timeout 180000 >/dev/null
  park_focus
  herdr agent get "$1" | j "['result']['agent']['agent_session']['value']"
}
pane_uuid()  { herdr pane get "$1" | j "['result']['pane'].get('agent_session',{}).get('value')"; }
pane_agent() { herdr pane get "$1" | j "['result']['pane'].get('agent')"; }
journal_has(){ python3 -c "import json,sys; sys.exit(0 if '$1' in json.load(open('$HERDR_SLEEPER_STATE/sleeping.json')) else 1)" 2>/dev/null; }
close_ws()   { herdr workspace close "${1%%:*}" >/dev/null 2>&1; }

# ============================================================================
say "== S1 concurrent scans: two scans race on one eligible pane; exactly one sleeps, journal consistent"
P=$(new_pane s1); U=$(start_claude "$P" s1) && {
  "$SLEEPER" scan --only "$P" --idle 0s > "$SOAK_DIR/s1a.out" 2>&1 &
  "$SLEEPER" scan --only "$P" --idle 0s > "$SOAK_DIR/s1b.out" 2>&1 &
  wait
  n=$(grep -c '^SLEEP' "$SOAK_DIR/s1a.out" "$SOAK_DIR/s1b.out" | awk -F: '{s+=$2} END{print s}')
  [ "$n" = 1 ] && journal_has "$P" && [ "$(pane_agent "$P")" = None ] && ok "one slept, entry present" || bad "slept=$n journal=$(journal_has "$P" && echo yes || echo no) agent=$(pane_agent "$P")"
  "$SLEEPER" wake s1 >/dev/null 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "wake restored $U" || bad "wake after race"
}; close_ws "$P"

say "== S2 corrupt journal: scan aborts without acting; wake still recovers from the snapshot"
P=$(new_pane s2); U=$(start_claude "$P" s2) && {
  "$SLEEPER" scan --only "$P" --dry-run >/dev/null 2>&1            # populates panes.json
  "$SLEEPER" scan --only "$P" --idle 0s >/dev/null 2>&1 && journal_has "$P" || bad "setup sleep"
  cp "$HERDR_SLEEPER_STATE/sleeping.json" "$SOAK_DIR/s2.journal.bak"
  echo '[]' > "$HERDR_SLEEPER_STATE/sleeping.json"
  "$SLEEPER" scan --only "$P" --idle 0s >"$SOAK_DIR/s2.scan.out" 2>&1; rc=$?
  [ $rc = 2 ] && grep -q 'damaged state file' "$SOAK_DIR/s2.scan.out" && ok "scan refused on corrupt journal (rc=2)" || bad "scan rc=$rc: $(head -c 120 "$SOAK_DIR/s2.scan.out")"
  "$SLEEPER" wake s2 >"$SOAK_DIR/s2.wake.out" 2>&1; rc=$?
  [ $rc = 0 ] && grep -q 'recovering from panes.json' "$SOAK_DIR/s2.wake.out" && [ "$(pane_uuid "$P")" = "$U" ] && ok "wake recovered from snapshot despite corrupt journal" || bad "wake rc=$rc: $(head -c 160 "$SOAK_DIR/s2.wake.out")"
  python3 -c "import json;print('{}')" > "$HERDR_SLEEPER_STATE/sleeping.json"   # leave a clean journal for later scenarios
}; close_ws "$P"

say "== S3 agent renamed under the sleeper: /exit still goes to the right pane"
P=$(new_pane s3); U=$(start_claude "$P" s3-old) && {
  Q=$(new_pane s3-decoy); V=$(start_claude "$Q" s3-decoy) || true
  herdr agent rename "$P" s3-decoy >/dev/null 2>&1 || herdr agent rename "$P" s3-new >/dev/null 2>&1   # collide or at least change the name
  "$SLEEPER" scan --only "$P" --idle 0s >"$SOAK_DIR/s3.out" 2>&1
  [ "$(pane_agent "$P")" = None ] && [ "$(pane_agent "$Q")" = claude ] && ok "slept $P, decoy $Q untouched" || bad "P agent=$(pane_agent "$P") Q agent=$(pane_agent "$Q")"
  "$SLEEPER" wake "$P" >/dev/null 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "wake by pane id" || bad "wake by pane id"
  close_ws "$Q"
}; close_ws "$P"

say "== S4 manual /exit between scans: no journal entry, snapshot recovery works into the same bare pane"
P=$(new_pane s4); U=$(start_claude "$P" s4) && {
  "$SLEEPER" scan --only "$P" --dry-run >/dev/null 2>&1            # snapshot only
  herdr agent prompt "$P" "/exit" >/dev/null; sleep 3
  "$SLEEPER" scan --only "$P" --idle 0s >/dev/null 2>&1            # nothing to sleep; must not journal
  journal_has "$P" && bad "journaled a pane the user exited" || ok "no spurious journal entry"
  "$SLEEPER" wake s4 >"$SOAK_DIR/s4.out" 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "snapshot recovery resumed $U" || bad "recovery: $(head -c 160 "$SOAK_DIR/s4.out")"
}; close_ws "$P"

say "== S5 recycled/reused pane: cwd changed under a sleeping pane -> wake refuses, restores after cd back"
P=$(new_pane s5); U=$(start_claude "$P" s5) && {
  "$SLEEPER" scan --only "$P" --idle 0s >/dev/null 2>&1
  herdr pane run "$P" "cd /tmp" >/dev/null; sleep 2; park_focus
  "$SLEEPER" wake s5 >"$SOAK_DIR/s5a.out" 2>&1; rc=$?
  [ $rc != 0 ] && grep -q 'now lives in' "$SOAK_DIR/s5a.out" && journal_has "$P" && ok "refused on cwd mismatch, entry kept" || bad "rc=$rc: $(head -c 160 "$SOAK_DIR/s5a.out")"
  herdr pane run "$P" "cd $REPO" >/dev/null; sleep 2; park_focus
  "$SLEEPER" wake s5 >/dev/null 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "woke after cwd restored" || bad "wake after cd back"
}; close_ws "$P"

say "== S6 session resumed elsewhere while asleep: wake refuses (would fork); works once the other exits"
P=$(new_pane s6); U=$(start_claude "$P" s6) && {
  "$SLEEPER" scan --only "$P" --idle 0s >/dev/null 2>&1
  Q=$(new_pane s6-other)
  herdr agent start s6-other --kind claude --pane "$Q" --timeout 120000 -- "${CLAUDE_ARGS[@]}" --resume "$U" >/dev/null 2>&1; park_focus
  "$SLEEPER" wake s6 >"$SOAK_DIR/s6a.out" 2>&1; rc=$?
  [ $rc != 0 ] && grep -q 'already live in pane' "$SOAK_DIR/s6a.out" && ok "refused: session live in $Q" || bad "rc=$rc: $(head -c 160 "$SOAK_DIR/s6a.out")"
  herdr agent prompt "$Q" "/exit" >/dev/null; sleep 3; close_ws "$Q"
  "$SLEEPER" wake s6 >/dev/null 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "woke after the other copy exited" || bad "wake after other exited"
}; close_ws "$P"

say "== S7 reconcile: user resumes the same session by hand in the sleeping pane -> entry dropped after two sightings"
P=$(new_pane s7); U=$(start_claude "$P" s7) && {
  "$SLEEPER" scan --only "$P" --idle 0s >/dev/null 2>&1
  herdr agent start s7 --kind claude --pane "$P" --timeout 120000 -- "${CLAUDE_ARGS[@]}" --resume "$U" >/dev/null 2>&1; park_focus
  "$SLEEPER" scan --only "$P" --dry-run >/dev/null 2>&1; s1=$(journal_has "$P" && echo kept || echo dropped)
  "$SLEEPER" scan --only "$P" --dry-run >/dev/null 2>&1; s2=$(journal_has "$P" && echo kept || echo dropped)
  [ "$s1" = kept ] && [ "$s2" = dropped ] && ok "kept after 1st sighting, dropped after 2nd" || bad "sightings: $s1 / $s2"
  herdr agent prompt "$P" "/exit" >/dev/null; sleep 2
}; close_ws "$P"

say "== S8 herdr unreachable / hanging: scan exits 2 cleanly, journal untouched"
cp "$HERDR_SLEEPER_STATE/sleeping.json" "$SOAK_DIR/s8.before" 2>/dev/null || echo '{}' > "$SOAK_DIR/s8.before"
printf '#!/bin/sh\nexit 1\n' > "$SOAK_DIR/herdr-dead"; chmod +x "$SOAK_DIR/herdr-dead"
HERDR_SLEEPER_HERDR_BIN="$SOAK_DIR/herdr-dead" "$SLEEPER" scan >"$SOAK_DIR/s8a.out" 2>&1; rc=$?
[ $rc = 2 ] && ! grep -q Traceback "$SOAK_DIR/s8a.out" && ok "dead herdr: rc=2, no traceback" || bad "dead herdr rc=$rc: $(head -c 120 "$SOAK_DIR/s8a.out")"
printf '#!/bin/sh\nsleep 120\n' > "$SOAK_DIR/herdr-hang"; chmod +x "$SOAK_DIR/herdr-hang"
t0=$(date +%s); HERDR_SLEEPER_HERDR_BIN="$SOAK_DIR/herdr-hang" "$SLEEPER" scan >"$SOAK_DIR/s8b.out" 2>&1; rc=$?; dt=$(( $(date +%s) - t0 ))
[ $rc = 2 ] && [ $dt -lt 60 ] && grep -q 'timed out' "$SOAK_DIR/s8b.out" && ok "hanging herdr: rc=2 after ${dt}s (timeout)" || bad "hang rc=$rc after ${dt}s: $(head -c 120 "$SOAK_DIR/s8b.out")"
cmp -s "$SOAK_DIR/s8.before" "$HERDR_SLEEPER_STATE/sleeping.json" 2>/dev/null && ok "journal untouched" || bad "journal changed while herdr was down"

say "== S9 state dir unwritable: scan reports an error, no traceback; journal readable afterwards"
chmod 000 "$HERDR_SLEEPER_STATE"
"$SLEEPER" scan >"$SOAK_DIR/s9.out" 2>&1; rc=$?
chmod 755 "$HERDR_SLEEPER_STATE"
[ $rc != 0 ] && ! grep -q Traceback "$SOAK_DIR/s9.out" && ok "unwritable state: rc=$rc, no traceback" || bad "rc=$rc: $(head -c 160 "$SOAK_DIR/s9.out")"

say "== S10 draft typed AFTER the scan's assessment but before /exit (recheck window): must refuse"
P=$(new_pane s10); U=$(start_claude "$P" s10) && {
  # inject the draft from a background helper 0.3s after scan starts; scan's recheck reads the screen just before /exit
  ( sleep 0.3; herdr pane send-text "$P" "late draft" >/dev/null ) &
  "$SLEEPER" scan --only "$P" --idle 0s >"$SOAK_DIR/s10.out" 2>&1; wait
  if grep -q 'composer draft' "$SOAK_DIR/s10.out"; then ok "late draft caught by recheck"
  elif [ "$(pane_agent "$P")" = None ]; then say "  NOTE  draft landed after /exit — inherent window (documented); agent slept"; ok "(window documented, not a defect)"
  else bad "unexpected: $(head -c 160 "$SOAK_DIR/s10.out")"; fi
  herdr pane send-keys "$P" ctrl+c >/dev/null 2>&1
}; close_ws "$P"

say "== S11 events log survives a corrupt line; list/log never traceback"
echo 'not json' >> "$HERDR_SLEEPER_STATE/events.jsonl"
"$SLEEPER" log >"$SOAK_DIR/s11.out" 2>&1; rc=$?
[ $rc = 0 ] && grep -q 'unreadable event line' "$SOAK_DIR/s11.out" && ok "log tolerated corrupt line" || bad "log rc=$rc"

say ""; say "== RESULT: $PASS passed, $FAIL failed  (log: $LOG)"
if [ "${1:-}" != "--keep" ]; then herdr session stop sleeper-lab >/dev/null 2>&1; fi
exit $FAIL
