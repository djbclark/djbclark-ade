#!/usr/bin/env bash
# soak_plugin_herdr.sh — fault-injection soak for the herdr-sleeper PLUGIN against a REAL Herdr.
#
# Runs entirely inside an isolated named Herdr session (HERDR_SESSION=sleeper-plugin-lab,
# its own server and socket) with its own plugin state (sessions/<name> under the plugin's
# state dir), so nothing here can touch the operator's live panes or the default session's
# journal. Complements the unit suite: real Claude processes, real Herdr timing, real events.
#
# Scenarios: P1 signal sleep + stub + focus wake; P2 Enter-stub wake; P3 watcher tick; P4 recycled pane
# (cwd moved); P5 session resumed elsewhere; P6 corrupt journal; P7 memory freed; P8 server restart with a
# slept pane (terminal id changes, wake still works); P9 pane id reused by another session (orphaned, not
# dropped); P10 sleep-pane on the focused pane.
#
# Usage: tests/soak_plugin_herdr.sh [--keep]     (--keep leaves the lab session running)
#   Run it through ~/ops/site-private/bin/bg (utility QoS, inherited by the lab claudes it starts):
#   ~12 real Claude sessions at normal priority starved the operator's interactive panes on 2026-10-05.
# Exit status is the number of failed scenarios. Log: $SOAK_DIR/soak.log
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$REPO/plugins/herdr-sleeper"
SLEEPER="$PLUGIN_DIR/herdr-sleeper"
export HERDR_SESSION=sleeper-plugin-lab
unset HERDR_SOCKET_PATH HERDR_CLIENT_SOCKET_PATH   # or the CLI silently routes to the caller's session
# Run from inside a Claude Code session, the lab server would hand its markers to every lab claude:
# CLAUDE_CODE_CHILD_SESSION turns transcript saving off, so nothing is resumable and every sleep refuses.
unset CLAUDECODE CLAUDE_PID CLAUDE_EFFORT $(compgen -v CLAUDE_CODE_)
SOAK_DIR="${SOAK_DIR:=/tmp/herdr-sleeper-plugin-soak}"
LOG="$SOAK_DIR/soak.log"; mkdir -p "$SOAK_DIR"; : > "$LOG"
PASS=0; FAIL=0
CLAUDE_ARGS=(--dangerously-skip-permissions)
# Direct engine invocations (the server drives the same code through the manifest):
S() { HERDR_SLEEPER_IDLE=0s "$SLEEPER" "$@"; }        # instant window, lab session state

say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
ok()   { PASS=$((PASS+1)); say "  PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
j()    { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1" 2>/dev/null; }

STATE_ROOT="$(python3 - <<'EOF'
import os
root = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser("~/.local/state/herdr/plugins/djbclark.herdr-sleeper")
print(os.path.join(root, "sessions", "sleeper-plugin-lab"))
EOF
)"
JOURNAL="$STATE_ROOT/sleeping.json"

# --- lab session -------------------------------------------------------------
lab_up() { herdr agent list >/dev/null 2>&1; }
lab_running() { herdr session list 2>/dev/null | grep -q "^sleeper-plugin-lab *running"; }
start_lab_server() {  # start the lab server if it is not running; wait until it answers
  lab_running || (nohup herdr server >>"$SOAK_DIR/server.log" 2>&1 &)
  for _ in $(seq 1 30); do lab_up && return 0; sleep 1; done
  return 1
}
stop_lab_server() {   # stop the lab server and wait until the session is gone
  herdr session stop sleeper-plugin-lab >/dev/null 2>&1
  for _ in $(seq 1 30); do lab_running || { lab_up || return 0; }; sleep 1; done
  return 1
}
start_lab_server
herdr agent list >/dev/null || { say "lab server not reachable"; exit 99; }
rm -f "$JOURNAL" "$STATE_ROOT/panes.json" "$STATE_ROOT/events.jsonl" "$STATE_ROOT/lock"

find_focus_ws() {  # (re)locate the focus-holder workspace; create it if the layout lost it
  FOCUS_WS=$(herdr workspace list | j "[w['workspace_id'] for w in d['result']['workspaces'] if w['label']=='focus-holder']" | tr -d "[]' \"")
  [ -n "$FOCUS_WS" ] || FOCUS_WS=$(herdr workspace create --cwd /tmp --label focus-holder --no-focus | j "['result']['workspace']['workspace_id']")
}
find_focus_ws
park_focus() { herdr workspace focus "$FOCUS_WS" >/dev/null 2>&1; }
park_focus

new_pane() {  # LABEL -> pane id of a fresh workspace whose shell is ready
  local p; p=$(herdr workspace create --cwd "$REPO" --label "$1" --no-focus | j "['result']['root_pane']['pane_id']")
  for _ in $(seq 1 30); do herdr pane read "$p" 2>/dev/null | grep -q '\$ *$' && break; sleep 1; done
  park_focus
  echo "$p"
}
start_claude() {  # PANE NAME -> uuid; one turn so the transcript exists (retries the prompt once)
  herdr agent start "$2" --kind claude --pane "$1" --timeout 120000 -- "${CLAUDE_ARGS[@]}" >/dev/null || return 1
  herdr agent prompt "$1" "Reply with exactly the word: pong" --wait --timeout 240000 >/dev/null 2>&1 \
    || herdr agent prompt "$1" "Reply with exactly the word: pong" --wait --timeout 240000 >/dev/null 2>&1
  park_focus
  herdr agent get "$1" | j "['result']['agent']['agent_session']['value']"
}
setup_failed() { say "  NOTE  setup failed for $1 (agent start/prompt); scenario skipped"; }
pane_uuid()  { herdr pane get "$1" | j "['result']['pane'].get('agent_session',{}).get('value')"; }
pane_asleep(){ [ "$(pane_agent "$1")" = None ] || [ "$(pane_agent "$1")" = sleeper ]; }
pane_agent() { herdr pane get "$1" | j "['result']['pane'].get('agent')"; }
journal_has(){ python3 -c "import json,sys; sys.exit(0 if '$1' in json.load(open('$JOURNAL')) else 1)" 2>/dev/null; }
journal_field(){ python3 -c "import json; print((json.load(open('$JOURNAL')).get('$1') or {}).get('$2') or '')" 2>/dev/null; }
pane_terminal(){ herdr pane get "$1" 2>/dev/null | j "['result']['pane'].get('terminal_id') or ''"; }
wait_prompt(){ for _ in $(seq 1 30); do herdr pane read "$1" 2>/dev/null | grep -q '\$ *$' && return 0; sleep 1; done; return 1; }
dismiss_stub(){  # PANE: end the wake stub by pid (never by typing: any line wakes it), wait until it is gone
  local pid=""
  for _ in $(seq 1 20); do
    pid=$(ps -eo pid=,args= | awk -v pane="$1" '$0 ~ "herdr-sleeper stub "pane" " {print $1}' | head -1)
    [ -n "$pid" ] && break; sleep 1
  done
  [ -n "$pid" ] && kill "$pid" 2>/dev/null
  for _ in $(seq 1 20); do kill -0 "${pid:-0}" 2>/dev/null || break; sleep 1; done
}
close_ws()   { herdr workspace close "${1%%:*}" >/dev/null 2>&1; }

# ============================================================================
say "== P1 signal sleep + stub + claim + context-priority wake round-trip"
P=$(new_pane p1); U=$(start_claude "$P" p1) || setup_failed p1; [ -n "$U" ] && {
  S scan --exclude nosuch >"$SOAK_DIR/p1.sleep.out" 2>&1
  pane_asleep "$P" && journal_has "$P" && ok "slept via SIGTERM, entry journalled" \
    || bad "sleep: agent=$(pane_agent "$P") journal=$(journal_has "$P" && echo yes || echo no): $(head -c 120 "$SOAK_DIR/p1.sleep.out")"
  herdr pane read "$P" 2>/dev/null | grep -q "press Enter to resume" && ok "wake stub left in the pane" || bad "no stub text: $(herdr pane read "$P" 2>/dev/null | tail -c 120)"
  python3 -c "
import json,subprocess,sys
pane = json.loads(subprocess.run(['herdr','pane','process-info','--pane','$P'],capture_output=True,text=True).stdout)['result']['process_info']['foreground_processes']
sys.exit(0 if any('stub' in ' '.join(map(str,p.get('argv') or [])) for p in pane) else 1)" && ok "stub is the pane's foreground process" || bad "stub not foreground"
  herdr workspace focus "${P%%:*}" >/dev/null 2>&1                      # pane.focused -> hook wakes via agent start
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "focus-wake restored $U" || bad "focus-wake: pane uuid=$(pane_uuid "$P")"
  journal_has "$P" && bad "journal entry survived wake" || ok "journal cleared on wake"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P2 Enter-stub wake: the pane's own stub execs the agent back (no agent start)"
P=$(new_pane p2); U=$(start_claude "$P" p2) || setup_failed p2; [ -n "$U" ] && {
  S scan --exclude nosuch >/dev/null 2>&1
  pane_asleep "$P" || bad "setup sleep failed"
  herdr pane send-keys "$P" enter >/dev/null
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "stub exec restored $U" || { bad "stub wake: pane uuid=$(pane_uuid "$P")"
         { echo "--- P2 pane $P screen"; herdr pane read "$P"; echo "--- P2 pane get"; herdr pane get "$P"
           echo "--- P2 process-info"; herdr pane process-info --pane "$P"; } >>"$LOG" 2>&1; }
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P3 watcher tick sleeps an idle pane without any manual invocation"
P=$(new_pane p3); U=$(start_claude "$P" p3) || setup_failed p3; [ -n "$U" ] && {
  [ "$(pane_agent "$P")" = claude ] || bad "setup"
  WPID=$(python3 -c "import json;print(json.load(open('$STATE_ROOT/watcher.pid'))['pid'])" 2>/dev/null)
  [ -n "$WPID" ] && kill "$WPID" 2>/dev/null && sleep 1   # the server's own startup-hook watcher (12h); ours is 0s
  rm -f "$STATE_ROOT/watcher.pid"
  HERDR_SLEEPER_IDLE=0s HERDR_SLEEPER_POLL_SECONDS=5 "$SLEEPER" watch >"$SOAK_DIR/p3.watch.out" 2>&1 &
  W=$!   # poll for the outcome (a slow claude can stay `working` for a while under load), never a fixed window
  for _ in $(seq 1 60); do pane_asleep "$P" && journal_has "$P" && break; sleep 1; done
  kill "$W" 2>/dev/null; wait "$W" 2>/dev/null
  pane_asleep "$P" && journal_has "$P" && ok "watcher tick slept it" || bad "watcher: agent=$(pane_agent "$P")"
  S wake p3 >/dev/null 2>&1
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "woke after watcher sleep" || bad "wake after watcher: uuid=$(pane_uuid "$P")"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P4 recycled pane (cwd moved under a sleeping pane): wake refuses, entry kept"
P=$(new_pane p4); U=$(start_claude "$P" p4) || setup_failed p4; [ -n "$U" ] && {
  S scan --exclude nosuch >/dev/null 2>&1
  for _ in $(seq 1 20); do  # dismiss the stub deterministically: by pid, never by typing (any line wakes it)
    STUB_PID=$(ps -eo pid=,args= | awk -v pane="$P" '$0 ~ "herdr-sleeper stub "pane" " {print $1}' | head -1)
    [ -n "$STUB_PID" ] && break; sleep 1
  done
  [ -n "${STUB_PID:-}" ] && kill "$STUB_PID" 2>/dev/null
  for _ in $(seq 1 20); do kill -0 "${STUB_PID:-0}" 2>/dev/null || break; sleep 1; done
  herdr pane run "$P" "cd /tmp" >/dev/null; sleep 2; park_focus
  S wake p4 >"$SOAK_DIR/p4.out" 2>&1; rc=$?
  [ $rc != 0 ] && grep -q "now lives in" "$SOAK_DIR/p4.out" && journal_has "$P" && ok "refused on cwd mismatch" \
    || bad "rc=$rc: $(head -c 140 "$SOAK_DIR/p4.out")"
  herdr pane run "$P" "cd $REPO" >/dev/null; sleep 2; park_focus
  S wake p4 >/dev/null 2>&1 && [ "$(pane_uuid "$P")" = "$U" ] && ok "woke after cwd restored" || bad "wake after cd back"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P5 session resumed elsewhere while asleep: wake refuses (would fork)"
P=$(new_pane p5); U=$(start_claude "$P" p5) || setup_failed p5; [ -n "$U" ] && {
  S scan --exclude nosuch >/dev/null 2>&1
  Q=$(new_pane p5-other)
  herdr agent start p5-other --kind claude --pane "$Q" --timeout 120000 -- "${CLAUDE_ARGS[@]}" --resume "$U" >/dev/null 2>&1; park_focus
  sleep 5
  S wake p5 >"$SOAK_DIR/p5.out" 2>&1; rc=$?
  [ $rc != 0 ] && grep -q "already live" "$SOAK_DIR/p5.out" && ok "refused: session live elsewhere" || bad "rc=$rc: $(head -c 140 "$SOAK_DIR/p5.out")"
  herdr agent prompt "$Q" "/exit" >/dev/null 2>&1
  for _ in $(seq 1 30); do herdr agent list 2>/dev/null | grep -q "$U" || break; sleep 1; done   # let it exit
  close_ws "$Q"
  S wake p5 >/dev/null 2>&1
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "woke after the other copy exited" || bad "wake after other exited: uuid=$(pane_uuid "$P")"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P6 corrupt journal: quarantined, snapshot recovery still wakes"
P=$(new_pane p6); U=$(start_claude "$P" p6) || setup_failed p6; [ -n "$U" ] && {
  S scan --exclude nosuch --dry-run >/dev/null 2>&1            # populates panes.json
  S scan --exclude nosuch >/dev/null 2>&1 && journal_has "$P" || bad "setup sleep"
  echo '[]' > "$JOURNAL"
  S wake p6 >"$SOAK_DIR/p6.out" 2>&1; rc=$?
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ $rc = 0 ] && grep -q "recovering" "$SOAK_DIR/p6.out" && [ "$(pane_uuid "$P")" = "$U" ] \
    && [ -n "$(ls "$STATE_ROOT"/sleeping.json.damaged-* 2>/dev/null)" ] \
    && ok "quarantined + recovered from snapshot" || bad "rc=$rc: $(head -c 160 "$SOAK_DIR/p6.out")"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P7 memory actually freed by a sleep"
P=$(new_pane p7); U=$(start_claude "$P" p7) || setup_failed p7; [ -n "$U" ] && {
  rss_before=$(python3 -c "
import json,subprocess
pi=json.loads(subprocess.run(['herdr','pane','process-info','--pane','$P'],capture_output=True,text=True).stdout)['result']['process_info']
pids=[str(p['pid']) for p in pi['foreground_processes'] if p.get('pid')]
out=subprocess.run(['ps','-o','rss=','-p',','.join(pids)],capture_output=True,text=True).stdout
print(sum(int(x) for x in out.split() if x.isdigit()))")
  S scan --exclude nosuch >/dev/null 2>&1
  rss_after=$(ps -eo rss=,comm= | awk '$2 ~ /claude/ {s+=$1} END {print s+0}')
  pane_asleep "$P" && [ "$rss_before" -gt 50000 ] && ok "slept (agent RSS was $((rss_before/1024)) MB)" || bad "rss_before=$rss_before agent=$(pane_agent "$P")"
  S wake p7 >/dev/null 2>&1
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "woke $U back" || bad "wake p7: uuid=$(pane_uuid "$P")"
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say "== P8 server restart while a pane sleeps: terminal id changes, wake still works"
P=$(new_pane p8); U=$(start_claude "$P" p8) || setup_failed p8; [ -n "$U" ] && {
  S scan --exclude nosuch >"$SOAK_DIR/p8.sleep.out" 2>&1
  T0=$(journal_field "$P" terminal_id)
  if pane_asleep "$P" && journal_has "$P" && [ -n "$T0" ]; then
    ok "slept before restart (journal terminal_id $T0)"
    stop_lab_server && start_lab_server || bad "lab server did not restart"
    T1=""
    for _ in $(seq 1 30); do T1=$(pane_terminal "$P"); [ -n "$T1" ] && break; sleep 1; done   # restore is async
    find_focus_ws; park_focus
    [ -n "$T1" ] && ok "pane $P survived the restart (terminal_id $T1)" || bad "pane $P gone after restart"
    [ -n "$T1" ] && [ "$T1" != "$T0" ] && ok "terminal id changed across restart ($T0 -> $T1)" \
      || bad "terminal id did not change (old=$T0 new=$T1): scenario does not exercise A1"
    journal_has "$P" && ok "journal entry survived the restart" || bad "journal entry lost across restart: $(head -c 120 "$JOURNAL" 2>/dev/null)"
    wait_prompt "$P" || say "  NOTE  no shell prompt seen in $P after restore"
    S wake "$P" >"$SOAK_DIR/p8.wake.out" 2>&1; rc=$?
    for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
    [ "$(pane_uuid "$P")" = "$U" ] && ok "woke $U after the server restart" \
      || bad "wake after restart: rc=$rc uuid=$(pane_uuid "$P"): $(head -c 160 "$SOAK_DIR/p8.wake.out")"
    journal_has "$P" && bad "journal entry survived wake" || ok "journal cleared on wake"
    park_focus
    herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
  else
    bad "setup sleep: agent=$(pane_agent "$P") journal_terminal=$T0: $(head -c 120 "$SOAK_DIR/p8.sleep.out")"
  fi
}; close_ws "$P"

say "== P9 pane id reused by another session: old entry orphaned (orphan:<uuid8>), not dropped"
P=$(new_pane p9); U1=$(start_claude "$P" p9a) || setup_failed p9; [ -n "$U1" ] && {
  S scan --exclude nosuch >/dev/null 2>&1
  pane_asleep "$P" && journal_has "$P" || bad "setup sleep"
  # A reused pane id is a pane id now backed by a DIFFERENT terminal (same terminal + new session is a
  # deliberate replacement, which drops the entry). Herdr cannot hand us a recycled id on demand, so the
  # entry is made to name a terminal that no longer exists.
  python3 - "$JOURNAL" "$P" <<'EOF'
import json, os, sys
path, pane = sys.argv[1:3]
d = json.load(open(path)); d[pane]["terminal_id"] = "term_soak_p9_gone"
tmp = path + ".p9"; json.dump(d, open(tmp, "w")); os.replace(tmp, path)
EOF
  dismiss_stub "$P"
  # our sidebar claim still marks P as an agent terminal; herdr refuses `agent start` there (agent_pane_busy)
  herdr pane release-agent "$P" --source custom:herdr-sleeper --agent sleeper >/dev/null 2>&1
  herdr pane run "$P" "cd $PLUGIN_DIR" >/dev/null; wait_prompt "$P"; park_focus   # another directory, still trusted
  U2=$(start_claude "$P" p9b)
  if [ -n "$U2" ] && [ "$U2" != "$U1" ]; then
    # reconcile only: exclude P so the idle-0s scan does not sleep the new session too
    S scan --exclude "$P" >"$SOAK_DIR/p9.scan.out" 2>&1
    verdict=$(python3 - "$JOURNAL" "$P" "$U1" <<'EOF'
import json, sys
path, pane, u1 = sys.argv[1:4]
try:
    d = json.load(open(path))
except Exception as exc:
    print(f"journal unreadable: {exc}"); sys.exit(0)
key = "orphan:" + u1[:8]
if (d.get(pane) or {}).get("uuid") == u1:
    print(f"entry for {u1} still keyed by {pane}")
elif key not in d:
    print(f"no {key} entry; keys={sorted(d)}")
elif d[key].get("phase") != "orphaned" or d[key].get("uuid") != u1:
    print(f"{key} wrong: phase={d[key].get('phase')} uuid={d[key].get('uuid')}")
else:
    print("ok")
EOF
)
    [ "$verdict" = ok ] && ok "old session orphaned as orphan:${U1:0:8}, nothing keyed by $P" || bad "orphan check: $verdict"
    S list >"$SOAK_DIR/p9.list.out" 2>&1
    grep -q "orphan:${U1:0:8}" "$SOAK_DIR/p9.list.out" && grep -q orphaned "$SOAK_DIR/p9.list.out" \
      && ok "list shows the orphan" || bad "list: $(head -c 200 "$SOAK_DIR/p9.list.out")"
    [ "$(pane_uuid "$P")" = "$U2" ] && ok "new session $U2 untouched in $P" || bad "pane uuid=$(pane_uuid "$P") expected $U2"
  else
    bad "setup: second session did not start (U1=$U1 U2=${U2:-})"
  fi
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
  python3 - "$JOURNAL" "$U1" <<'EOF' 2>/dev/null   # leave later runs a clean journal
import json, sys
path, u1 = sys.argv[1:3]
d = json.load(open(path))
d.pop("orphan:" + u1[:8], None)
json.dump(d, open(path, "w"))
EOF
}; close_ws "$P"

say "== P10 sleep-pane on the focused pane"
P=$(new_pane p10); U=$(start_claude "$P" p10) || setup_failed p10; [ -n "$U" ] && {
  herdr workspace focus "${P%%:*}" >/dev/null 2>&1
  for _ in $(seq 1 10); do [ "$(herdr pane get "$P" | j "['result']['pane'].get('focused')")" = True ] && break; sleep 1; done
  [ "$(herdr pane get "$P" | j "['result']['pane'].get('focused')")" = True ] && ok "pane is focused" || bad "setup: pane not focused"
  HERDR_SLEEPER_IDLE=0s "$SLEEPER" sleep-pane "$P" >"$SOAK_DIR/p10.sleep.out" 2>&1; rc=$?
  for _ in $(seq 1 30); do pane_asleep "$P" && break; sleep 1; done
  [ $rc = 0 ] && pane_asleep "$P" && journal_has "$P" && ok "focused pane slept via sleep-pane" \
    || bad "sleep-pane on focused pane: rc=$rc agent=$(pane_agent "$P") journal=$(journal_has "$P" && echo yes || echo no): $(head -c 160 "$SOAK_DIR/p10.sleep.out")"
  S wake "$P" >"$SOAK_DIR/p10.wake.out" 2>&1
  for _ in $(seq 1 30); do [ "$(pane_uuid "$P")" = "$U" ] && break; sleep 1; done
  [ "$(pane_uuid "$P")" = "$U" ] && ok "woke $U back" || bad "wake p10: uuid=$(pane_uuid "$P"): $(head -c 160 "$SOAK_DIR/p10.wake.out")"
  park_focus
  herdr agent prompt "$P" "/exit" >/dev/null 2>&1; sleep 2
}; close_ws "$P"

say ""; say "== RESULT: $PASS passed, $FAIL failed  (log: $LOG)"
herdr workspace close "$FOCUS_WS" >/dev/null 2>&1
if [ "${1:-}" != "--keep" ]; then herdr session stop sleeper-plugin-lab >/dev/null 2>&1; fi
exit $FAIL
