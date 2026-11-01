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

# isolated_up NAME: fresh home, Unix-socket listener (open question 1), no plugins, saved PID.
# UNVERIFIED against 0.14/0.15: the exact `daemon config set` keys; read `paseo daemon config get` in a fresh
# home first and fix the two lines marked KEY. `daemon config` has no --home flag in the help: it may need PASEO_HOME.
isolated_up() {
  local name="$1" base="${TMPDIR:-/tmp}/ade-acc-$name-$$"
  mkdir -p "$base" && chmod 700 "$base"
  export PASEO_HOME="$base/home"; mkdir -m 700 "$PASEO_HOME"
  echo fresh > "$PASEO_HOME/.ade-acceptance-home"
  paseo daemon config set daemon.listen "unix://$base/paseo.sock" >/dev/null   # KEY
  paseo daemon config set pluginsEnabled false >/dev/null                      # KEY: no janitor, no herald
  nohup paseo daemon run --home "$PASEO_HOME" > "$base/daemon.out" 2>&1 &
  echo $! > "$base/daemon.pid"; export ACC_BASE="$base"
  local i; for i in $(seq 1 30); do pj status >/dev/null 2>&1 && return 0; sleep 1; done
  die "isolated daemon did not come up; see $base/daemon.out"
}

# isolated_down: kills exactly the saved PID (never by name).
isolated_down() {
  [ -n "${ACC_BASE:-}" ] && [ -f "$ACC_BASE/daemon.pid" ] || return 0
  local pid; pid=$(cat "$ACC_BASE/daemon.pid")
  kill "$pid" 2>/dev/null; sleep 2; kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
  return 0
}

live_snapshot() { paseo status 2>/dev/null | awk -F': ' '/^(pid|startedAt|serverId)/{printf "%s=%s;",$1,$2}'; }
