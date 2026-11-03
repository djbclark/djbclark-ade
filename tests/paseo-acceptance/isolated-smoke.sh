#!/usr/bin/env bash
# isolated-smoke: Does isolated_up start a second daemon that is really separate from the live one, and does isolated_down leave nothing?
# CONTRACT: D1.7/B10: a test daemon has its own home, serverId and socket; starting and stopping it never touches the live daemon
# EXPECT:   test serverId differs from the live one; live pid, startedAt, serverId, agent count and config sha256 unchanged; no process or socket left
# ON-FAIL:  no D1 probe marked "second daemon only" may run (T4 to T10 blocked) until isolated_up/down are fixed (plan T2)
# SCOPE:    second daemon only
#           Reads the live daemon (status, ls) and hashes its config; writes nothing there. Starts and stops one daemon of its own.
# HOW:      bash tests/paseo-acceptance/isolated-smoke.sh   (KEEP=1 keeps $TMPDIR/ade-acc-smoke.* for inspection)
# NEEDS:    paseo on PATH, python3, openssl, shasum; no provider credential (no agent is created)
# STATUS:   run 2026-11-02 against live daemon 0.15.0-beta.1
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=isolated-smoke
. "$here/lib/common.sh"
ON_FAIL="no 'second daemon only' probe may run (T4 to T10 blocked) until isolated_up/down are fixed (plan T2)"
LIVE_SERVER_ID=srv_3QHQeiJniWBD   # plan T2 Accept; the live snapshot below is compared too

snap0=$(live_snapshot) && [ -n "$snap0" ] || skip "live daemon status unreadable"
count0=$(live_agent_count) || skip "live paseo ls unreadable"
sha0=$(live_config_sha)

isolated_up smoke
trap 'isolated_down' EXIT
iso=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(json.dumps({k: d.get(k) for k in ("serverId", "pid", "listen", "home", "daemonVersion", "connectedDaemon")}, separators=(",", ":")))' "$ACC_BASE/status.json")
iso_id=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1]).get("serverId") or "")' "$iso")
iso_agents=$(pj ls --json 2>/dev/null | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))')
plugins_running=$(python3 -c 'import json, sys; print(sum(p.get("status") == "running" for p in json.load(open(sys.argv[1]))))' "$ACC_BASE/plugins.json")
tree=$(_acc_tree "$(cat "$ACC_BASE/daemon.pid")" | tr '\n' ' ')
ps_tree=$(ps -o pid=,ppid= -p "$(printf '%s' "$tree" | tr ' ' ',' | gsed 's/,$//')" | awk '{printf "%s<-%s ", $1, $2}')
# connectedDaemon as `paseo status` sees it with a given PASEO_PASSWORD (env only, never argv).
reach() { PASEO_PASSWORD="$1" pj status --json 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin).get("connectedDaemon"))' 2>/dev/null || echo error; }
pw_right=$(reach "$(cat "$ACC_BASE/password")")
pw_wrong=$(reach "wrong-$RANDOM$RANDOM")
# Speech: dictation must be requested off, and no model download may start (run 1 began a ~600 MB download).
read -r downloads dictation_on < <(python3 - "$ACC_BASE/daemon.out" <<'PY'
import json, sys
dl = on = 0
for line in open(sys.argv[1], errors="replace"):
    try:
        d = json.loads(line)
    except ValueError:
        continue
    dl += d.get("component") == "model-downloader"
    on += bool(((d.get("requestedProviders") or {}).get("dictationStt") or {}).get("enabled"))
print(dl, on)
PY
)

ACC_CLEAN=0 isolated_down; down_rc=$?
left=""; for p in $tree; do kill -0 "$p" 2>/dev/null && left="$left $p"; done
sock_left=$([ -e "$ACC_BASE/paseo.sock" ] && echo true || echo false)

snap1=$(live_snapshot); count1=$(live_agent_count); sha1=$(live_config_sha)
ev=$(python3 -c '
import json, sys
a = sys.argv
print(json.dumps({"isolated": json.loads(a[1]), "isolatedAgents": int(a[2] or -1), "pluginsRunning": int(a[3]),
  "processTree": a[4].split(), "leftAlive": a[5].split(), "socketLeft": a[6] == "true", "downRc": int(a[7]),
  "liveBefore": a[8], "liveAfter": a[9], "liveAgentsBefore": int(a[10]), "liveAgentsAfter": int(a[11] or -1),
  "liveConfigSha256Before": a[12][:16], "liveConfigSha256After": a[13][:16], "base": a[14],
  "pidPpid": a[15].split(), "rightPassword": a[16], "wrongPassword": a[17], "modelDownloaderLines": int(a[18]),
  "dictationRequestedLines": int(a[19])},
  separators=(",", ":")))' \
  "$iso" "$iso_agents" "$plugins_running" "$tree" "$left" "$sock_left" "$down_rc" "$snap0" "$snap1" "$count0" "$count1" "$sha0" "$sha1" "$ACC_BASE" \
  "$ps_tree" "$pw_right" "$pw_wrong" "$downloads" "$dictation_on")

[ -n "$iso_id" ] || fail "isolated daemon reported no serverId" "$ev"
[ "$iso_id" != "$LIVE_SERVER_ID" ] && case "$snap0" in *"serverId=$iso_id;"*) false;; *) true;; esac \
  || fail "isolated daemon has the live serverId" "$ev"
[ "$plugins_running" = 0 ] || fail "a plugin runs on the isolated daemon" "$ev"
[ "$pw_right" = reachable ] && [ "$pw_wrong" != reachable ] || fail "the daemon password is not enforced (or the right one is refused)" "$ev"
[ "$downloads" = 0 ] && [ "$dictation_on" = 0 ] || fail "the isolated daemon requested dictation or started a speech-model download" "$ev"
[ "$snap0" = "$snap1" ] || fail "live daemon pid/startedAt/serverId changed" "$ev"
[ "$count0" = "$count1" ] || fail "live agent count changed ($count0 -> $count1; another session may have created or archived one: rerun)" "$ev"
[ "$sha0" = "$sha1" ] || fail "live config hash changed" "$ev"
[ -z "$left" ] && [ "$sock_left" = false ] && [ "$down_rc" = 0 ] || fail "isolated_down left a process or the socket" "$ev"
# On a pass, remove the test home once `pass` has recorded the result (record_result reads its status.json).
[ "${KEEP:-0}" = 1 ] || trap 'rm -rf "$ACC_BASE"' EXIT
pass "$ev"
