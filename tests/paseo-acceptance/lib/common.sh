#!/usr/bin/env bash
# lib/common.sh: shared helpers for the D1 acceptance probes (DRAFT; plan B10, docs/d1-implementation-plan.md section 3).
# Source it; it defines functions only and runs nothing.
#
# Isolation rule: every probe whose SCOPE is not "READ-ONLY live" calls `require_isolated` first. It refuses
# (exit 2) unless PASEO_HOME is a fresh directory created by `isolated_up` (marker file) and is not the live home.

ACC_LIVE_HOME="${HOME}/.paseo"
ACC_RESULTS="${ADE_ACCEPTANCE_RESULTS:-$HOME/.local/state/ade/acceptance/$(date -u +%Y-%m-%d)}"
ACC_PROBE="${ACC_PROBE:-$(basename "${0:-probe}" .sh)}"
EMPTY_JSON='{}'

die() { printf '%s: %s\n' "$ACC_PROBE" "$*" >&2; exit "${DIE_RC:-2}"; }

versions_json() {
  local cli daemon
  cli=$(paseo -v 2>/dev/null | head -1)
  daemon=$(paseo ${PASEO_HOME:+--home "$PASEO_HOME"} status 2>/dev/null | awk -F': ' '/^daemonVersion/{print $2}')
  # A probe records its result after isolated_down: fall back to the status isolated_up saved.
  [ -n "$daemon" ] || [ ! -s "${ACC_BASE:-/nonexistent}/status.json" ] \
    || daemon=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("daemonVersion") or "")' "$ACC_BASE/status.json" 2>/dev/null)
  printf '{"cliVersion":"%s","daemonVersion":"%s"}' "${cli:-unknown}" "${daemon:-unknown}"
}

# record_result VERDICT(pass|fail|skip) 'JSON-object-evidence'; writes atomically, prints one bounded line.
record_result() {
  local verdict="$1" evidence="${2:-$EMPTY_JSON}" out tmp
  mkdir -p "$ACC_RESULTS" && chmod 700 "$ACC_RESULTS"
  out="$ACC_RESULTS/$ACC_PROBE.json"; tmp="$out.tmp.$$"
  printf '{"probe":"%s","verdict":"%s","at":"%s","versions":%s,"evidence":%s}\n' \
    "$ACC_PROBE" "$verdict" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(versions_json)" "$evidence" > "$tmp" && mv -f "$tmp" "$out"
  head -c 1500 "$out"
}

# pass / fail / skip: exit 0, 1, 77. `fail` prints the plan's named consequence (ON_FAIL, set in the probe).
pass() { record_result pass "${1:-$EMPTY_JSON}"; exit 0; }
fail() { echo "CONSEQUENCE: ${ON_FAIL:-see the probe header}" >&2; record_result fail "${2:-$EMPTY_JSON}"; echo "FAIL: $1" >&2; exit 1; }
skip() { echo "SKIP (precondition): $1" >&2; exit 77; }

require_isolated() {
  [ -n "${PASEO_HOME:-}" ] || die "PASEO_HOME unset: run under isolated_up (B10)"
  [ "$(cd "$PASEO_HOME" 2>/dev/null && pwd -P)" != "$(cd "$ACC_LIVE_HOME" && pwd -P)" ] || die "PASEO_HOME is the live home"
  [ -f "$PASEO_HOME/.ade-acceptance-home" ] || die "PASEO_HOME has no .ade-acceptance-home marker: refusing a home this library did not create"
  [ "$(cat "$PASEO_HOME/.ade-acceptance-home")" = "fresh" ] || die "marker is not 'fresh': refusing a copied home (it would inherit another server id)"
}

# pj ARGS...: the paseo CLI pointed at the isolated daemon only.
pj() { require_isolated; paseo --home "$PASEO_HOME" "$@"; }

# The live daemon's config file. isolated_up hashes it before and after setup and refuses on any change (plan T2 Hazard).
ACC_LIVE_CONFIG="$ACC_LIVE_HOME/config.json"
live_config_sha() { shasum -a 256 "$ACC_LIVE_CONFIG" 2>/dev/null | awk '{print $1}'; }

# _acc_tree PID...: each PID and all its descendants (a pgrep -P walk). Used only on the PID isolated_up started.
_acc_tree() {
  local p c
  for p in "$@"; do echo "$p"; for c in $(pgrep -P "$p" 2>/dev/null); do _acc_tree "$c"; done; done
}

# _acc_refuse MSG: tear down whatever isolated_up started, keep ACC_BASE for evidence, exit 2.
_acc_refuse() { ACC_CLEAN=0 isolated_down; die "isolated_up refused: $1 (evidence kept in ${ACC_BASE:-?})"; }
# Agent MCP (create_agent, send_agent_prompt, ...) is injected into agents only when the daemon listens on TCP: the daemon's
# createAgentMcpBaseUrl returns null for a Unix listener (checked 2026-11-02 in the 0.15.0-beta.1 bundle, and by a codex agent on a
# Unix-socket isolated daemon answering "create_agent isn't available"). A probe that needs MCP sets ACC_TCP_PORT=N, a loopback
# port already claimed in site-djbclark/registry/ports.yml (refused otherwise, and refused if something already listens there).
#
# isolated_up NAME: fresh home under $TMPDIR/ade-acc-NAME.XXXXXX, Unix-socket listener (decision 1), plugins off
# (no session-janitor, herald or telegram), dictation off (its first start downloads a ~600 MB local speech model),
# a random password, `paseo daemon run` under a saved PID.
# Checked 2026-11-02 (CLI 0.15.0-beta.1): `paseo daemon config set KEY VALUE --home H` writes H/config.json only (live
# sha256 unchanged after each call); the keys come from the server's PersistedConfigSchema.
# The password is not a config key (daemon.auth.password is a bcrypt hash `config set` refuses; set-password needs a
# TTY), so it reaches the daemon as PASEO_PASSWORD in its environment only; the CLI authenticates over the socket with
# the home's local-credential. Every inherited PASEO_* variable is dropped for the daemon (PASEO_LISTEN would override
# the configured listener). Sets ACC_BASE and PASEO_HOME. ACC_BASE holds daemon.pid (the process started here, the
# root of the tree isolated_down stops), status.pid (the pid `paseo status` reports: the DaemonRunner child of
# daemon.pid; the server worker that logs is its child), status.json, daemon.out, password and paseo.sock.
isolated_up() {
  local name="${1:?usage: isolated_up NAME}" tmp="${TMPDIR:-/tmp}" base sock live_sha i kv up=0 listen ports="${ACC_PORTS_YML:-$HOME/ops/site-djbclark/registry/ports.yml}"
  tmp="${tmp%/}"
  live_sha=$(live_config_sha); [ -n "$live_sha" ] || die "cannot hash the live config $ACC_LIVE_CONFIG"
  base=$(mktemp -d "$tmp/ade-acc-$name.XXXXXX") || die "mktemp failed under $tmp"
  chmod 700 "$base"; sock="$base/paseo.sock"
  export ACC_BASE="$base" PASEO_HOME="$base/home"
  [ "${#sock}" -lt 104 ] || _acc_refuse "socket path is ${#sock} bytes, over sun_path's 104: use a shorter TMPDIR"
  listen="unix://$sock"
  if [ -n "${ACC_TCP_PORT:-}" ]; then
    case "$ACC_TCP_PORT" in ''|*[!0-9]*) _acc_refuse "ACC_TCP_PORT=$ACC_TCP_PORT is not a port number";; esac
    ggrep -q -E "port: *$ACC_TCP_PORT[,} ]" "$ports" 2>/dev/null || _acc_refuse "port $ACC_TCP_PORT is not claimed in $ports (rule 17: claim through the lead first)"
    ! lsof -nP -iTCP:"$ACC_TCP_PORT" -sTCP:LISTEN >/dev/null 2>&1 || _acc_refuse "something already listens on 127.0.0.1:$ACC_TCP_PORT"
    listen="127.0.0.1:$ACC_TCP_PORT"
  fi
  { mkdir -m 700 "$PASEO_HOME" && echo fresh > "$PASEO_HOME/.ade-acceptance-home"; } || _acc_refuse "cannot create $PASEO_HOME"
  for kv in "daemon.listen=$listen" pluginsEnabled=false features.dictation.enabled=false; do
    paseo daemon config set "${kv%%=*}" "${kv#*=}" --home "$PASEO_HOME" >/dev/null 2>>"$base/config.err" \
      || _acc_refuse "config set ${kv%%=*} failed"
    [ "$(live_config_sha)" = "$live_sha" ] \
      || _acc_refuse "the LIVE config hash changed after 'config set ${kv%%=*}'; restore $ACC_LIVE_CONFIG from a backup now"
  done
  python3 - "$PASEO_HOME/config.json" "$listen" <<'PY' || _acc_refuse "fresh config.json lacks the listener, pluginsEnabled=false or dictation off"
import json, sys
c = json.load(open(sys.argv[1]))
ok = (c.get("daemon", {}).get("listen") == sys.argv[2] and c.get("pluginsEnabled") is False
      and c.get("features", {}).get("dictation", {}).get("enabled") is False)
sys.exit(0 if ok else 1)
PY
  (umask 077; openssl rand -hex 24 > "$base/password") || _acc_refuse "cannot generate the password"
  (
    for v in $(compgen -A export -X '!PASEO_*'); do unset "$v"; done
    PASEO_PASSWORD=$(cat "$base/password")
    export PASEO_PASSWORD
    exec nohup paseo daemon run --home "$base/home" > "$base/daemon.out" 2>&1 < /dev/null
  ) &
  echo $! > "$base/daemon.pid"
  for i in $(seq 1 60); do
    kill -0 "$(cat "$base/daemon.pid")" 2>/dev/null || _acc_refuse "isolated daemon exited during start-up; see $base/daemon.out"
    if { [ -n "${ACC_TCP_PORT:-}" ] || [ -S "$sock" ]; } && pj status --json > "$base/status.json" 2>/dev/null \
      && python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if d.get("connectedDaemon") == "reachable" and d.get("serverId") else 1)' "$base/status.json"; then
      up=1; break
    fi
    sleep 1
  done
  [ "$up" = 1 ] || _acc_refuse "isolated daemon did not come up in 60 s; see $base/daemon.out"
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["pid"])' "$base/status.json" > "$base/status.pid"
  [ "$(live_config_sha)" = "$live_sha" ] || _acc_refuse "the LIVE config hash changed while the isolated daemon started; restore $ACC_LIVE_CONFIG from a backup now"
  pj plugin ls --json > "$base/plugins.json" 2>/dev/null || _acc_refuse "plugin ls failed on the isolated daemon"
  python3 - "$base/plugins.json" <<'PY' || _acc_refuse "a plugin is running on the isolated daemon (B10: no janitor, herald or telegram)"
import json, sys
sys.exit(1 if [p.get("id") for p in json.load(open(sys.argv[1])) if p.get("status") == "running"] else 0)
PY
  return 0
}

# isolated_down [NAME]: stops exactly the process tree isolated_up started (saved PID and its descendants, never by
# name): TERM, up to 15 s, then KILL. Removes the socket; keeps ACC_BASE (logs, evidence) unless ACC_CLEAN=1.
# Limit: a grandchild that detached from the tree (reparented to launchd) is not found.
isolated_down() {
  [ -n "${ACC_BASE:-}" ] && [ -f "$ACC_BASE/daemon.pid" ] || return 0
  case "$ACC_BASE" in */ade-acc-*) ;; *) echo "isolated_down: refusing ACC_BASE=$ACC_BASE" >&2; return 1;; esac
  local pid pids left p
  pid=$(cat "$ACC_BASE/daemon.pid")
  pids=$(_acc_tree "$pid" | tr '\n' ' ')
  kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 1 15); do
    left=""; for p in $pids; do kill -0 "$p" 2>/dev/null && left="$left $p"; done
    [ -z "$left" ] && break; sleep 1
  done
  if [ -n "$left" ]; then
    kill -TERM $left 2>/dev/null; sleep 2
    left=""; for p in $pids; do kill -0 "$p" 2>/dev/null && left="$left $p"; done
    [ -n "$left" ] && kill -KILL $left 2>/dev/null && sleep 1
  fi
  wait "$pid" 2>/dev/null
  left=""; for p in $pids; do kill -0 "$p" 2>/dev/null && left="$left $p"; done
  printf '%s\n' "$pids" > "$ACC_BASE/daemon.tree"; mv -f "$ACC_BASE/daemon.pid" "$ACC_BASE/daemon.pid.stopped"
  rm -f "$ACC_BASE/paseo.sock"
  [ -z "$left" ] || { echo "isolated_down: still alive after KILL:$left" >&2; return 1; }
  # A claimed TCP port must be free again (never kill whatever holds it: report only).
  if [ -n "${ACC_TCP_PORT:-}" ] && lsof -nP -iTCP:"$ACC_TCP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "isolated_down: 127.0.0.1:$ACC_TCP_PORT still has a listener after the daemon tree stopped" >&2; return 1
  fi
  if [ "${ACC_CLEAN:-0}" = 1 ] && [ "$(cat "$ACC_BASE/home/.ade-acceptance-home" 2>/dev/null)" = fresh ]; then
    rm -rf "$ACC_BASE"
  fi
  return 0
}

# isolated_restart_guard / isolated_restart_now / isolated_restart [TIMEOUT_S]: `paseo --home <isolated home> restart` of the
# ISOLATED daemon only (T8, D1.5). The command can never resolve to ~/.paseo: the guard asserts, on physical paths, that
# PASEO_HOME is exactly $ACC_BASE/home (the directory isolated_up created, marker 'fresh'), is not a symlink, is not the live
# home or inside it, and that the daemon answering on it has the serverId isolated_up saved and not the live daemon's.
# `isolated_restart_now` repeats the path assertions (no CLI calls, so it adds no latency) and then runs the restart with an
# explicit --home; PASEO_HOST and PASEO_LISTEN are dropped for the call (an inherited endpoint must not redirect it).
# `isolated_restart` = guard + now; a probe that needs the restart within milliseconds of another call runs the guard
# first and `_now` last. `paseo restart` restarts the worker and keeps its supervisor (`paseo daemon run`, daemon.pid), so
# isolated_down still stops the whole tree. Writes ACC_BASE/restart.json and status-after.json; sets RESTART_PID_BEFORE/AFTER
# (the supervisor pid `paseo status` reports; restart.json carries previousWorkerPid and workerPid) and RESTART_RC.
_acc_restart_home() {
  local real live base
  require_isolated
  [ ! -L "$PASEO_HOME" ] || die "isolated_restart: PASEO_HOME is a symlink"
  real=$(cd "$PASEO_HOME" && pwd -P); live=$(cd "$ACC_LIVE_HOME" && pwd -P); base=$(cd "${ACC_BASE:?}" && pwd -P)
  [ "$real" != "$live" ] || die "isolated_restart: PASEO_HOME resolves to the live home"
  case "$real" in "$live"/*) die "isolated_restart: $real is inside the live home";; esac
  [ "$real" = "$base/home" ] || die "isolated_restart: $real is not \$ACC_BASE/home ($base/home)"
  ACC_RESTART_HOME="$real"
}
isolated_restart_guard() {
  local saved now live_id
  _acc_restart_home
  saved=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["serverId"])' "$ACC_BASE/status.json") || die "isolated_restart: no saved serverId"
  now=$(env -u PASEO_HOST -u PASEO_LISTEN paseo --home "$ACC_RESTART_HOME" status --json 2>/dev/null \
    | python3 -c 'import json, sys; print(json.load(sys.stdin).get("serverId") or "")')
  [ -n "$now" ] && [ "$now" = "$saved" ] || die "isolated_restart: daemon on $ACC_RESTART_HOME has serverId '$now', expected the saved '$saved'"
  live_id=$(live_snapshot | ggrep -o 'serverId=[^;]*' | gsed 's/^serverId=//')
  [ -z "$live_id" ] || [ "$live_id" != "$saved" ] || die "isolated_restart: the isolated serverId equals the live daemon's"
  RESTART_GUARDED="$ACC_RESTART_HOME"
}
isolated_restart_now() {
  local tmo="${1:-120}"
  _acc_restart_home
  [ "${RESTART_GUARDED:-}" = "$ACC_RESTART_HOME" ] || die "isolated_restart_now: run isolated_restart_guard first"
  RESTART_PID_BEFORE=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("pid") or "")' "$ACC_BASE/status.json" 2>/dev/null)
  RESTART_T0=$(gdate +%s%3N)
  env -u PASEO_HOST -u PASEO_LISTEN paseo --home "$ACC_RESTART_HOME" restart --json --timeout "$tmo" > "$ACC_BASE/restart.json" 2> "$ACC_BASE/restart.err"
  RESTART_RC=$?
  RESTART_T1=$(gdate +%s%3N)
  env -u PASEO_HOST -u PASEO_LISTEN paseo --home "$ACC_RESTART_HOME" status --json > "$ACC_BASE/status-after.json" 2>/dev/null
  RESTART_PID_AFTER=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("pid") or "")' "$ACC_BASE/status-after.json" 2>/dev/null)
  return "$RESTART_RC"
}
isolated_restart() { isolated_restart_guard && isolated_restart_now "$@"; }

# live_snapshot: pid, startedAt and serverId of the LIVE daemon (explicit --home: PASEO_HOME may point at a test home).
live_snapshot() {
  paseo --home "$ACC_LIVE_HOME" status --json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("pid=%s;startedAt=%s;serverId=%s;" % (d.get("pid"), d.get("startedAt"), d.get("serverId")))'
}

# live_agent_count: number of agents `paseo ls --json` lists on the LIVE daemon (read-only).
live_agent_count() {
  paseo --home "$ACC_LIVE_HOME" ls --json 2>/dev/null | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))'
}
