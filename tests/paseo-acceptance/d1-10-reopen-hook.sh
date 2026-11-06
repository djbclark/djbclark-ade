#!/usr/bin/env bash
# d1-10-reopen-hook
# CONTRACT: V3 (adversary r7): agent.open.before fires again when an archived agent is reopened or an idle agent resumed, so the tool catalog is recomputed
# EXPECT:   the probe plugin logs one agent.open.before per open, reopen and resume of the same agent id
# ON-FAIL:  G1's orchestrator registration flow (create, merge id, reopen) cannot work; G1 must read config/orchestrators at jobs.submit time instead
# SCOPE:    second daemon only (installs fixtures/origin-probe-plugin into the TEST home only)
# HOW:      bash tests/paseo-acceptance/d1-10-reopen-hook.sh   (about 4 min; 3 one-word turns on ORIGIN_PROVIDER, see lib/origin-probe.sh)
# NEEDS:    isolated daemon; the antigravity provider (or PROBE_PROVIDER=provider/model; never the Claude pool, cline or opencode-go)
# STEPS:    S0 create; S1 idle follow-up send (no reload); S2 `paseo agent reload` (refresh_agent_request, the wire request the
#           reopen-archived plugin sends after restoring a workspace); S3 archive then reload (the reopen-archived leg for an archived
#           agent); S4 `paseo plugin reload origin-probe` then send (docs: sessions become stale and reopen before the next idle prompt);
#           S5 daemon worker restart then send (resume). reopen-archived itself cannot run here: it refuses a Unix-socket listener,
#           and the workspace-restore request has no CLI form (recorded, not scripted).
# STATUS:   RUN 2026-11-02 on Paseo 0.15.0-beta.1 (docs/d1-implementation-plan.md T11 "Checked")
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-10-reopen-hook
. "$here/lib/common.sh"; . "$here/lib/origin-probe.sh"
ON_FAIL=G1\'s\ orchestrator\ registration\ flow\ \(create\,\ merge\ id\,\ reopen\)\ cannot\ work\;\ G1\ must\ read\ config/orchestrators\ at\ jobs.submit\ time\ instead
live_before=$(live_config_sha)
base_tmp="${TMPDIR:-/tmp}"; base_tmp="${base_tmp%/}"
export ORIGIN_LOG="$base_tmp/ade-reopen-$$.log" ORIGIN_TRIGGER=""
: > "$ORIGIN_LOG"
isolated_up reopen; trap 'isolated_down' EXIT
mkdir -p "$ACC_BASE/work"
origin_setup "$here" || skip "origin-probe plugin did not start (see $ACC_BASE/plugin-install.out)"

steps="[]"
# opens_for ID: the reasons of every agent.open.before logged for ID so far, in order, as a JSON array.
opens_for() {
  python3 -c '
import json, sys
log, agent = sys.argv[1], sys.argv[2]
out = []
for line in open(log):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    r = e.get("payload", {}).get("request", {}) if e.get("hook") == "agent.open.before" else {}
    if r.get("agentId") == agent:
        out.append("%s/%s" % (r.get("reason"), r.get("purpose")))
print(json.dumps(out))' "$ORIGIN_LOG" "$1"
}
# record_step NAME COMMAND-RESULT: appends {step, opens: all opens so far, newOpens: count since the previous step}.
prev=0
record_step() {
  local name="$1" now n
  now=$(opens_for "$id"); n=$(python3 -c 'import json, sys; print(len(json.loads(sys.argv[1])))' "$now")
  steps=$(python3 -c 'import json, sys; s = json.loads(sys.argv[1]); s.append({"step": sys.argv[2], "newOpens": int(sys.argv[3]) - int(sys.argv[4]), "opens": json.loads(sys.argv[5]), "note": sys.argv[6]}); print(json.dumps(s))' "$steps" "$name" "$n" "$prev" "$now" "${2:-}")
  prev=$n
}
settle() { sleep 4; pj wait --timeout 120 "$id" >/dev/null 2>&1; sleep 3; }

id=$(pj run --no-wait -q --provider "$ORIGIN_PROVIDER" --cwd "$ACC_BASE/work" --title reopen "reply with the single word OK" 2>"$ACC_BASE/run.err" | tail -1)
[ -n "$id" ] || fail "paseo run returned no agent id (see $ACC_BASE/run.err)" "$(versions_json)"
settle; record_step S0-create

pj send "$id" "reply with the single word OK again" >"$ACC_BASE/s1.out" 2>&1; settle; record_step S1-idle-send

pj agent reload "$id" >"$ACC_BASE/s2.out" 2>&1; echo "rc=$?" >> "$ACC_BASE/s2.out"; settle; record_step S2-agent-reload "$(tail -1 "$ACC_BASE/s2.out")"

pj archive "$id" >"$ACC_BASE/s3a.out" 2>&1; sleep 3
pj agent reload "$id" >"$ACC_BASE/s3b.out" 2>&1; echo "rc=$?" >> "$ACC_BASE/s3b.out"; settle
archived_after=$(pj inspect "$id" --json 2>/dev/null | python3 -c 'import json, sys; d = json.load(sys.stdin); print(json.dumps(d.get("archivedAt") if isinstance(d, dict) else None))' 2>/dev/null || echo null)
record_step S3-archive-then-reload "reload $(tail -1 "$ACC_BASE/s3b.out"); archivedAt after reload: $archived_after"

pj plugin reload origin-probe >"$ACC_BASE/s4a.out" 2>&1; sleep 3
pj send "$id" "reply with the single word OK, third time" >"$ACC_BASE/s4b.out" 2>&1; settle; record_step S4-plugin-reload-then-send

pj restart >"$ACC_BASE/s5a.out" 2>&1; echo "rc=$?" >> "$ACC_BASE/s5a.out"
for i in $(seq 1 30); do pj status --json 2>/dev/null | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("connectedDaemon") == "reachable" else 1)' && break; sleep 2; done
sleep 8
pj send "$id" "reply with the single word OK, fourth time" >"$ACC_BASE/s5b.out" 2>&1; settle; record_step S5-daemon-restart-then-send "$(tail -1 "$ACC_BASE/s5a.out")"

cp "$ORIGIN_LOG" "$ACC_BASE/origin.log"; rm -f "$ORIGIN_LOG"
[ "$(live_config_sha)" = "$live_before" ] || die "the LIVE config hash changed during the probe"
ev=$(python3 - "$steps" "$id" <<'PY'
import json, sys
steps = json.loads(sys.argv[1])
by = {s["step"]: s for s in steps}
fires = lambda n: by[n]["newOpens"] >= 1
ev = {"agent": sys.argv[2], "steps": steps,
      "refiresOnReload": fires("S2-agent-reload"),
      "refiresOnArchivedReload": fires("S3-archive-then-reload"),
      "refiresOnPluginReload": fires("S4-plugin-reload-then-send"),
      "refiresAfterDaemonRestart": fires("S5-daemon-restart-then-send"),
      "refiresOnIdleSend": fires("S1-idle-send")}
ev["catalogRecomputedOnReopen"] = ev["refiresOnArchivedReload"] and ev["refiresOnReload"]
print(json.dumps(ev, sort_keys=True))
PY
)
echo "evidence: $ACC_BASE (origin.log, s*.out)" >&2
echo "catalog recomputed on reopen: $(python3 -c 'import json, sys; print("yes" if json.loads(sys.argv[1])["catalogRecomputedOnReopen"] else "no")' "$ev")" >&2
full=$(python3 -c 'import json, sys; d = json.loads(sys.argv[1]); d.update(json.loads(sys.argv[2])); print(json.dumps(d))' "$ev" "$(versions_json)")
python3 -c 'import json, sys; sys.exit(0 if json.loads(sys.argv[1])["catalogRecomputedOnReopen"] else 1)' "$ev" && pass "$full"
fail "agent.open.before did not fire again on reload or archived reopen" "$full"
