#!/usr/bin/env bash
# d1-05-restart-persistence
# CONTRACT: D1.5: a daemon restart loses no queued prompt, no pending notifyOnFinish and no schedule
# EXPECT:   after `paseo --home <isolated> restart`: (1) a prompt steered into a busy agent is in its timeline exactly once;
#           (2) a prompt still inside the daemon's two-second in-memory delivery queue when the restart lands is delivered
#           exactly once (or the probe says the window was missed); (3) the finish notification of a child that was running at
#           the restart reaches its parent exactly once; (4) the schedule exists unchanged and fires after the restart
# ON-FAIL:  G1 and G3 persist those records themselves and reconcile after every restart (they already assume so)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). The restart goes through lib/common.sh isolated_restart_guard +
#           isolated_restart_now, which assert before calling `paseo --home X restart` that X is the fresh $ACC_BASE/home
#           (never ~/.paseo), that the daemon answering there is the one isolated_up started, and which refuse otherwise.
# HOW:      bash tests/paseo-acceptance/d1-05-restart-persistence.sh   (about 6 min; 6 short omp/haiku turns, API credits)
#           PROVIDER=omp MODEL=anthropic/claude-haiku-4-5 are the defaults; the Claude subscription, cline, clinepass and
#           opencode-go pools are NEVER used (djbclark 2026-11-02): PROVIDER=claude exits 77.
# NEEDS:    isolated daemon (lib/common.sh); omp installed and logged in; lib/mcp_call_as.py
# STATUS:   run 2026-11-02, see docs/d1-implementation-plan.md T8 for the verdict
# Setup facts (checked 2026-11-02, paseo 0.15.0-beta.1; docs/d1-implementation-plan.md T8):
#   - the isolated daemon needs `daemon.mcp.injectIntoAgents=true` before its agents are created, else an agent-scoped MCP call
#     (/mcp/agents?callerAgentId=ID) finds no tools ("Method not found"); config.json only, live config untouched (hash-guarded);
#   - notifyOnFinish exists only for an agent-scoped caller, so a parent agent P creates child C through lib/mcp_call_as.py;
#   - `paseo send` has no queue behaviour (steer|interrupt): "queued" means a steer into the running turn or the two-second
#     AgentMessageDelivery queue (in memory) that MCP send_agent_prompt/finish notifications use.
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-05-restart-persistence
. "$here/lib/common.sh"
ON_FAIL='G1 and G3 persist those records themselves and reconcile after every restart (they already assume so)'
PROVIDER="${PROVIDER:-omp}"
MODEL="${MODEL:-anthropic/claude-haiku-4-5}"
[ "$PROVIDER" != claude ] || skip "claude pool protected (djbclark 2026-11-02): use PROVIDER=omp, whose Claude models bill API credits"
SLEEP_S="${SLEEP_S:-170}"
M_STEER=T8-STEER-ONE-4417; M_WINDOW=T8-WINDOW-TWO-5528

live0=$(live_snapshot); livecnt0=$(live_agent_count); livesha0=$(live_config_sha)
isolated_up restart; trap isolated_down EXIT
work="$ACC_BASE/work"; mkdir -m 700 "$work"
S="$ACC_BASE/paseo.sock"; PW="$ACC_BASE/password"; MCP="$here/lib/mcp_call_as.py"
ev() { printf '%s\n' "$*" >> "$ACC_BASE/timeline.txt"; }   # one line per step, with a clock

paseo daemon config set daemon.mcp.injectIntoAgents true --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/config-mcp.err" || die "enabling mcp.injectIntoAgents failed ($ACC_BASE/config-mcp.err)"
paseo daemon config set agents.providers '{"omp":{"enabled":true}}' --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/config-omp.err" || die "enabling the omp provider failed"
ready=0
for i in $(seq 1 45); do
  pj provider ls --json 2>/dev/null | python3 -c '
import json, sys
p = [x for x in json.load(sys.stdin) if x.get("provider") == sys.argv[1]]
sys.exit(0 if p and p[0].get("enabled") == "Enabled" and p[0].get("status") not in ("loading", "unavailable") else 1)' "$PROVIDER" && { ready=1; break; }
  sleep 2
done
[ "$ready" = 1 ] || skip "provider $PROVIDER never became ready on the isolated daemon"

json_field() { python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$1" "$2" 2>/dev/null; }
# count_in_logs FILE MARKER: number of log blocks (a block starts at a "[Kind]" line) that contain MARKER and are not a Thought/Tool block
# (assistant text follows a Thought block, so an agent echoing MARKER is not counted; the prompts also ask it not to)
count_in_logs() {
  python3 - "$1" "$2" <<'PY'
import re, sys
blocks, cur = [], None
for line in open(sys.argv[1], errors="replace"):
    m = re.match(r"^\[([^\]]+)\]", line)
    if m:
        cur = [m.group(1), line]; blocks.append(cur)
    elif cur is not None:
        cur[1] += line
    else:
        cur = ["", line]; blocks.append(cur)
print(sum(1 for kind, text in blocks if sys.argv[2] in text and not re.match(r"(Thought|Tool|Assistant|Reasoning)", kind)))
PY
}
# count_notices FILE CHILD: lines "Agent CHILD (title) finished|errored|was closed|..." in the parent's log
count_notices() { ggrep -cE "^Agent $2 \(.*\) (finished|errored|was closed|is unavailable|needs permission)" "$1" 2>/dev/null; }
snap_logs() { pj logs "$1" > "$2" 2>/dev/null; }
agent_status() { pj inspect "$1" --json 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin).get("Status") or "")' 2>/dev/null; }

# ---- setup: parent P (idle), busy agent B, child C with notifyOnFinish -----------------------------------------------------
pj run --json --no-wait --provider "$PROVIDER" --model "$MODEL" --cwd "$work" --title t8-parent "Reply with exactly: PARENT-READY" \
  > "$ACC_BASE/p-run.json" 2>"$ACC_BASE/p-run.err" || fail "creating parent failed" "{\"stderr\":\"$ACC_BASE/p-run.err\"}"
P=$(json_field "$ACC_BASE/p-run.json" 'd.get("agentId")')
pj wait --timeout 120 "$P" >/dev/null 2>&1
pj run --json --no-wait --provider "$PROVIDER" --model "$MODEL" --cwd "$work" --title t8-busy \
  "Use your bash tool to run exactly: sleep $SLEEP_S . Wait for it to finish, then reply with exactly: BUSY-DONE" \
  > "$ACC_BASE/b-run.json" 2>"$ACC_BASE/b-run.err" || fail "creating busy agent failed" "{\"stderr\":\"$ACC_BASE/b-run.err\"}"
B=$(json_field "$ACC_BASE/b-run.json" 'd.get("agentId")')
python3 "$MCP" "$S" "$PW" create_agent "{\"title\":\"t8-child\",\"provider\":\"$PROVIDER/$MODEL\",\"initialPrompt\":\"Use your bash tool to run exactly: sleep $SLEEP_S . Wait for it to finish, then reply with exactly: CHILD-DONE\",\"notifyOnFinish\":true}" "$P" \
  > "$ACC_BASE/c-create.json" 2>"$ACC_BASE/c-create.err" || fail "create_agent via MCP failed" "{\"stderr\":\"$ACC_BASE/c-create.err\"}"
C=$(json_field "$ACC_BASE/c-create.json" 'd["structuredContent"]["agentId"]')
[ -n "$P" ] && [ -n "$B" ] && [ -n "$C" ] && [ "$C" != None ] || fail "an agent id is missing" "{\"parent\":\"$P\",\"busy\":\"$B\",\"child\":\"$C\"}"
ev "$(date -u +%T) setup P=$P B=$B C=$C"
# both long turns must be running a tool before anything is sent
for i in $(seq 1 30); do
  [ "$(agent_status "$B")" = running ] && [ "$(agent_status "$C")" = running ] && break; sleep 2
done
sleep 8
cp "$PASEO_HOME/finish-subscriptions.json" "$ACC_BASE/finish-subs-before.json" 2>/dev/null || echo '[]' > "$ACC_BASE/finish-subs-before.json"
subs_before=$(python3 -c 'import json, sys; print(sum(1 for r in json.load(open(sys.argv[1])) if r.get("childAgentId") == sys.argv[2] and r.get("callerAgentId") == sys.argv[3]))' "$ACC_BASE/finish-subs-before.json" "$C" "$P")

# ---- (1) steer into the busy turn ---------------------------------------------------------------------------------------
pj send --no-wait --behavior steer "$B" "Additional instruction: when you are done, also reply with the token $M_STEER (never repeat that token in a command)" > "$ACC_BASE/steer.out" 2>&1; steer_rc=$?
for i in $(seq 1 15); do
  snap_logs "$B" "$ACC_BASE/b-logs-before.txt"
  [ "$(count_in_logs "$ACC_BASE/b-logs-before.txt" "$M_STEER")" -ge 1 ] && break; sleep 2
done
steer_before=$(count_in_logs "$ACC_BASE/b-logs-before.txt" "$M_STEER")
b_status_before=$(agent_status "$B"); c_status_before=$(agent_status "$C")
ev "$(date -u +%T) steer rc=$steer_rc in-log=$steer_before B=$b_status_before C=$c_status_before"

# ---- (3) schedule: create right after a minute boundary so its next fire comes AFTER the restart finishes (~25 s) -----------
sec=$((10#$(date +%S))); [ "$sec" -ge 3 ] && sleep $((62 - sec))
sec=$((10#$(date +%S)))
pj schedule create --cron '* * * * *' --max-runs 4 --expires-in 30m --name t8-sched --provider "$PROVIDER/$MODEL" --cwd "$work" --json \
  "Reply with exactly: SCHED-RAN" > "$ACC_BASE/sched-create.json" 2>"$ACC_BASE/sched-create.err" || fail "schedule create failed" "{\"stderr\":\"$ACC_BASE/sched-create.err\"}"
SID=$(json_field "$ACC_BASE/sched-create.json" 'd.get("id")')
pj schedule inspect "$SID" --json > "$ACC_BASE/sched-before.json" 2>/dev/null
ev "$(date -u +%T) schedule $SID created at second $sec (cron * * * * *)"

# ---- (2)+(restart): window message through the in-memory queue, restart within the two-second window ------------------------
isolated_restart_guard
python3 "$MCP" "$S" "$PW" send_agent_prompt "{\"agentId\":\"$B\",\"prompt\":\"Late instruction: also reply with the token $M_WINDOW\",\"notifyOnFinish\":false,\"activeTurnBehavior\":\"steer\"}" "$P" \
  > "$ACC_BASE/window-send.json" 2>"$ACC_BASE/window-send.err"
win_rc=$?; T_SEND=$(gdate +%s%3N)
isolated_restart_now 180; restart_rc=$RESTART_RC
gap_ms=$((RESTART_T0 - T_SEND)); restart_ms=$((RESTART_T1 - RESTART_T0))
ev "$(date -u +%T) window send rc=$win_rc, restart rc=$restart_rc, restart began ${gap_ms} ms after the send returned, took ${restart_ms} ms; supervisor pid $RESTART_PID_BEFORE -> $RESTART_PID_AFTER"
[ "$restart_rc" = 0 ] || fail "restart of the isolated daemon failed (rc=$restart_rc)" "{\"restartJson\":\"$ACC_BASE/restart.json\",\"stderr\":\"$ACC_BASE/restart.err\"}"
sec_after=$((10#$(date +%S)))

# ---- diff, immediately after the restart ------------------------------------------------------------------------------------
cp "$PASEO_HOME/finish-subscriptions.json" "$ACC_BASE/finish-subs-after-restart.json" 2>/dev/null || echo '[]' > "$ACC_BASE/finish-subs-after-restart.json"
pj ls --json > "$ACC_BASE/ls-after.json" 2>/dev/null
pj schedule inspect "$SID" --json > "$ACC_BASE/sched-after-restart.json" 2>/dev/null; sched_rc=$?
snap_logs "$B" "$ACC_BASE/b-logs-after.txt"; snap_logs "$C" "$ACC_BASE/c-logs-after.txt"; snap_logs "$P" "$ACC_BASE/p-logs-after-restart.txt"
b_status_after=$(agent_status "$B"); c_status_after=$(agent_status "$C")
steer_after=$(count_in_logs "$ACC_BASE/b-logs-after.txt" "$M_STEER")
window_after=$(count_in_logs "$ACC_BASE/b-logs-after.txt" "$M_WINDOW")

# notification: poll the parent's timeline (the child's killed turn ends, the subscription fires)
notices=0
for i in $(seq 1 40); do
  snap_logs "$P" "$ACC_BASE/p-logs-final.txt"
  notices=$(count_notices "$ACC_BASE/p-logs-final.txt" "$C"); [ "${notices:-0}" -ge 1 ] && break; sleep 3
done
sleep 20   # a duplicate would arrive within seconds of the first; look again
snap_logs "$P" "$ACC_BASE/p-logs-final.txt"; notices=$(count_notices "$ACC_BASE/p-logs-final.txt" "$C")
ev "$(date -u +%T) notices for C in P's timeline: $notices"
cp "$PASEO_HOME/finish-subscriptions.json" "$ACC_BASE/finish-subs-final.json" 2>/dev/null || echo '[]' > "$ACC_BASE/finish-subs-final.json"
subs_final=$(python3 -c 'import json, sys; print(sum(1 for r in json.load(open(sys.argv[1])) if r.get("childAgentId") == sys.argv[2]))' "$ACC_BASE/finish-subs-final.json" "$C")

# schedule: wait for a run that started after the restart (next minute boundary, then the run itself)
sched_fired=0
for i in $(seq 1 45); do
  pj schedule inspect "$SID" --json > "$ACC_BASE/sched-final.json" 2>/dev/null
  sched_fired=$(python3 -c '
import json, sys
from datetime import datetime, timezone
d = json.load(open(sys.argv[1])); t0 = int(sys.argv[2]) / 1000.0
n = 0
for r in d.get("runs", []):
    ts = datetime.strptime(r["startedAt"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    if ts >= t0 and r.get("status") not in ("running", "failed"):
        n += 1
print(n)' "$ACC_BASE/sched-final.json" "$RESTART_T1" 2>/dev/null)
  [ "${sched_fired:-0}" -ge 1 ] && break; sleep 4
done
pj schedule pause "$SID" >/dev/null 2>&1
snap_logs "$P" "$ACC_BASE/p-logs-final.txt"
ev "$(date -u +%T) schedule runs started after the restart and not failed/running: $sched_fired"
# run-once still works on the restored schedule
pj schedule run-once "$SID" --json > "$ACC_BASE/sched-runonce.json" 2>"$ACC_BASE/sched-runonce.err"; runonce_rc=$?
sleep 25
pj schedule inspect "$SID" --json > "$ACC_BASE/sched-final.json" 2>/dev/null
pj schedule delete "$SID" >/dev/null 2>&1
snap_logs "$B" "$ACC_BASE/b-logs-final.txt"; snap_logs "$C" "$ACC_BASE/c-logs-final.txt"
steer_final=$(count_in_logs "$ACC_BASE/b-logs-final.txt" "$M_STEER")
window_final=$(count_in_logs "$ACC_BASE/b-logs-final.txt" "$M_WINDOW")
resume_b=$(ggrep -c 'Resume working' "$ACC_BASE/b-logs-final.txt"); resume_c=$(ggrep -c 'Resume working' "$ACC_BASE/c-logs-final.txt")
b_status_final=$(agent_status "$B"); c_status_final=$(agent_status "$C")

# schedule comparison: every field except runs/status/nextRunAt/updatedAt/lastRunAt must be unchanged by the restart
sched_same=$(python3 - "$ACC_BASE/sched-before.json" "$ACC_BASE/sched-after-restart.json" <<'PY'
import json, sys
try:
    a, b = (json.load(open(p)) for p in sys.argv[1:3])
except Exception:
    print("unreadable"); sys.exit(0)
keys = ("id", "name", "prompt", "cadence", "target", "createdAt", "maxRuns", "expiresAt")
print("same" if all(a.get(k) == b.get(k) for k in keys) else "differs")
PY
)
sched_runs=$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(json.dumps([{"status": r.get("status"), "scheduledFor": r.get("scheduledFor"), "agentId": bool(r.get("agentId")), "error": r.get("error")} for r in d.get("runs", [])]))' "$ACC_BASE/sched-final.json" 2>/dev/null || echo '[]')

# the live daemon was not touched
live1=$(live_snapshot); livecnt1=$(live_agent_count); livesha1=$(live_config_sha)
live_same=true
[ "$livesha0" = "$livesha1" ] || live_same=false
{ [ -z "$live0" ] || [ -z "$live1" ] || [ "$live0" = "$live1" ]; } || live_same=false
{ [ -z "$livecnt0" ] || [ -z "$livecnt1" ] || [ "$livecnt0" = "$livecnt1" ]; } || live_same=false

# restart outcome
rj=$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(json.dumps({k: d.get(k) for k in ("action", "supervisorPid", "previousWorkerPid", "workerPid", "acknowledged")}))' "$ACC_BASE/restart.json" 2>/dev/null || echo '{}')
boundary_in_restart=false
[ $((RESTART_T0 / 60000)) -ne $((RESTART_T1 / 60000)) ] && boundary_in_restart=true   # a cron fire fell inside the restart: that run is killed (T8 finding)
window_class=missed
[ "$gap_ms" -lt 1500 ] && window_class=inside-two-second-window

for v in steer_before steer_after steer_final window_after window_final notices subs_before subs_final sched_fired; do eval "[ -n \"\${$v:-}\" ] || $v=0"; done
verdict=pass; why=""
[ "$steer_before" -ge 1 ] || { verdict=skip; why="$why steer never appeared before the restart (precondition);"; }
[ "$steer_final" = 1 ] || { verdict=fail; why="$why steered prompt count after restart is $steer_final, expected 1;"; }
[ "$notices" = 1 ] || { verdict=fail; why="$why notifyOnFinish notices=$notices, expected exactly 1;"; }
[ "$sched_same" = same ] || { verdict=fail; why="$why schedule changed or unreadable ($sched_same);"; }
[ "${sched_fired:-0}" -ge 1 ] || { verdict=fail; why="$why schedule did not fire after the restart;"; }
[ "$runonce_rc" = 0 ] || { verdict=fail; why="$why schedule run-once rc=$runonce_rc;"; }
if [ "$window_class" = inside-two-second-window ]; then
  [ "$window_final" = 1 ] || { verdict=fail; why="$why two-second-queue prompt count after restart is $window_final, expected 1 (the restart landed ${gap_ms} ms after the send);"; }
fi
[ "$live_same" = true ] || { verdict=fail; why="$why LIVE daemon snapshot, agent count or config hash changed;"; }

e=$(python3 - <<PY
import json
print(json.dumps({
  "provider": "$PROVIDER", "model": "$MODEL", "evidence": "$ACC_BASE",
  "agents": {"parent": "$P", "busy": "$B", "child": "$C"}, "scheduleId": "$SID",
  "restart": json.loads('''$rj'''), "restartMs": $restart_ms, "supervisorPidBefore": "$RESTART_PID_BEFORE", "supervisorPidAfter": "$RESTART_PID_AFTER",
  "steer": {"sendRc": $steer_rc, "inTimelineBeforeRestart": $steer_before, "afterRestart": $steer_after, "final": $steer_final,
            "busyResumeWorkingPrompts": ${resume_b:-0}, "busyStatus": {"before": "$b_status_before", "afterRestart": "$b_status_after", "final": "$b_status_final"}},
  "windowQueue": {"class": "$window_class", "sendRc": $win_rc, "restartBeganMsAfterSend": $gap_ms, "afterRestart": $window_after, "final": $window_final},
  "notifyOnFinish": {"subscriptionsBefore": $subs_before, "subscriptionsFinal": $subs_final, "noticesInParentTimeline": $notices,
            "childResumeWorkingPrompts": ${resume_c:-0}, "childStatus": {"before": "$c_status_before", "afterRestart": "$c_status_after", "final": "$c_status_final"}},
  "schedule": {"unchangedByRestart": "$sched_same", "firedAfterRestart": $sched_fired, "runOnceRc": $runonce_rc, "runs": json.loads('''$sched_runs'''), "restartEndedAtSecond": $sec_after, "minuteBoundaryInsideRestart": '$boundary_in_restart' == 'true'},
  "liveDaemonUntouched": "$live_same", "verdictNotes": "${why# }"
}))
PY
)
[ "$verdict" = skip ] && { echo "SKIP (precondition):$why" >&2; record_result skip "$e" >/dev/null; exit 77; }
[ "$verdict" = pass ] && pass "$e"
fail "contract broken:$why" "$e"
