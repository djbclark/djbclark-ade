#!/usr/bin/env bash
# d1-04-archive-parent-child
# CONTRACT: D1.4/C1: archiving a parent whose child is running leaves the child running (so successors need not stay top-level)
# EXPECT:   a child made by the parent's MCP create_agent keeps running after 'paseo archive <parent>' and finishes; same for a child detached first
# ON-FAIL:  successors stay top-level permanently (plan D1.4, C1)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      ACC_TCP_PORT=<claimed loopback port> bash tests/paseo-acceptance/d1-04-archive-parent-child.sh
#           PROBE_PROVIDER (default codex), PROBE_MODEL (default gpt-6-luna, the cheapest codex model), PROBE_MODE (default full-access);
#           claude-family only through omp: PROBE_PROVIDER=omp PROBE_MODEL=anthropic/claude-haiku-4-5 PROBE_MODE=full, never the Claude subscription
# NEEDS:    isolated daemon on a claimed TCP loopback port (agent MCP is injected only for a TCP listener and with daemon.mcp.injectIntoAgents=true,
#           which this probe sets in the TEST home only); one cheap provider; one parent turn (it makes two 60 s children)
# STATUS:   run 2026-11-06 on 127.0.0.1:18809 (docs/d1-implementation-plan.md T7): exit 1 by design of the Accept line: the attached child is
#           archived with its parent (cascade, never ran), the detached child survived and finished.
#
# One parent turn creates two children, A and B, both through MCP create_agent (agent-scoped, so lineage is set). A is detached
# ('paseo agent detach') before the parent is archived, B is not: one paid parent turn answers both halves of the task.
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-04-archive-parent-child
. "$here/lib/common.sh"
ON_FAIL='successors stay top-level permanently (plan D1.4, C1)'
[ -n "${ACC_TCP_PORT:-}" ] || skip "no ACC_TCP_PORT: agent MCP (create_agent) is injected only when the isolated daemon listens on a claimed TCP loopback port"
P=${PROBE_PROVIDER:-codex}
M=${PROBE_MODEL:-gpt-6-luna}
MODE=${PROBE_MODE:-full-access}
SPEC="$P/$M"
isolated_up lineage; trap isolated_down EXIT
# Agent MCP tools reach an agent only with daemon.mcp.injectIntoAgents=true (default false, T8) AND a TCP listener (Unix: no URL).
live_sha=$(live_config_sha)
paseo daemon config set daemon.mcp.injectIntoAgents true --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/config-mcp.err" || die "enabling mcp.injectIntoAgents failed ($ACC_BASE/config-mcp.err)"
[ "$(live_config_sha)" = "$live_sha" ] || die "the LIVE config hash changed after enabling mcp.injectIntoAgents; restore $ACC_LIVE_CONFIG from a backup now"
EV="$ACC_BASE/evidence"; mkdir -p "$EV"

# snap LABEL: save 'paseo ls -a --json' as $EV/ls-LABEL.json. field LABEL ID KEY: one field of that snapshot ('gone' if absent).
snap() { pj ls -a --json > "$EV/ls-$1.json" 2>"$EV/ls-$1.err"; }
field() {
  python3 - "$EV/ls-$1.json" "$2" "$3" <<'PY'
import json, sys
path, aid, key = sys.argv[1:4]
try:
    rows = json.load(open(path))
except (OSError, ValueError):
    print("unreadable"); sys.exit(0)
for r in rows:
    if r.get("id") == aid:
        v = r.get(key)
        print("" if v is None else v); sys.exit(0)
print("gone")
PY
}
# child_id LABEL NAME: id of the agent named NAME in snapshot LABEL ('' if none).
child_id() {
  python3 - "$EV/ls-$1.json" "$2" <<'PY'
import json, sys
try:
    rows = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    rows = []
print(next((r["id"] for r in rows if r.get("name") == sys.argv[2]), ""))
PY
}
# parent_of ID: the value of any key named like *parent* (any depth) in 'paseo agent inspect --json ID', plus the key path; saves the raw JSON.
parent_of() {
  pj agent inspect --json "$1" > "$EV/inspect-$1-$2.json" 2>"$EV/inspect-$1-$2.err"
  python3 - "$EV/inspect-$1-$2.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    print("unreadable"); sys.exit(0)
hits = []
def walk(x, path):
    if isinstance(x, dict):
        for k, v in x.items():
            if "parent" in k.lower():
                hits.append("%s.%s=%s" % (path, k, v))
            walk(v, path + "." + k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, "%s[%d]" % (path, i))
walk(d, "")
print(";".join(hits) if hits else "no-parent-key")
PY
}

parent=$(pj run -q --no-wait --provider "$SPEC" --mode "$MODE" --title t7-parent \
 "Call the create_agent MCP tool exactly twice, one call after the other. Both calls: provider \"$SPEC\", notifyOnFinish false. Call 1: title \"t7-child-A\", initialPrompt \"Run the shell command: sleep 60. When it ends, reply with exactly CHILD-A-DONE.\". Call 2: title \"t7-child-B\", initialPrompt \"Run the shell command: sleep 60. When it ends, reply with exactly CHILD-B-DONE.\". If the tool accepts a mode setting, use $MODE. After both calls return, reply with exactly PARENT-DONE and do not wait for the children.") || fail "parent create failed"
echo "parent=$parent"
pj wait --timeout 240 "$parent" >"$EV/parent-wait.out" 2>&1
pj logs "$parent" >"$EV/parent-logs.txt" 2>&1
snap created
a=$(child_id created t7-child-A); b=$(child_id created t7-child-B)
[ -n "$a" ] && [ -n "$b" ] || skip "parent did not create both children (A='$a' B='$b'); see $EV/parent-logs.txt"
lin_a=$(parent_of "$a" before); lin_b=$(parent_of "$b" before)
echo "lineage A: $lin_a"; echo "lineage B: $lin_b"
case "$lin_a$lin_b" in *"$parent"*"$parent"*) ;; *) skip "child lineage not set to the parent (A: $lin_a; B: $lin_b)";; esac
[ "$(field created "$a" status)" = running ] && [ "$(field created "$b" status)" = running ] || skip "children not both running after the parent's turn: A=$(field created "$a" status) B=$(field created "$b" status)"

det_out=$(pj agent detach --json "$a" 2>&1); det_rc=$?
lin_a2=$(parent_of "$a" afterdetach)
echo "detach A rc=$det_rc; lineage A after detach: $lin_a2"
t0=$(date +%s)
arc_out=$(pj archive --json "$parent" 2>&1); arc_rc=$?
echo "archive parent rc=$arc_rc: $(printf '%s' "$arc_out" | head -c 300)"
samples=""
for dt in 1 5 15 30; do
  while [ $(( $(date +%s) - t0 )) -lt "$dt" ]; do sleep 1; done
  snap "t$dt"
  sa=$(field "t$dt" "$a" status); sb=$(field "t$dt" "$b" status); sp=$(field "t$dt" "$parent" status)
  samples="$samples t+${dt}s:A=$sa,B=$sb,parent=$sp"
  echo "t+${dt}s A=$sa B=$sb parent=$sp"
done
# The children's tasks are 60 s; wait for both to finish and check the marker each wrote.
pj wait --timeout 150 "$a" >"$EV/wait-a.out" 2>&1; wa=$?
pj wait --timeout 150 "$b" >"$EV/wait-b.out" 2>&1; wb=$?
pj logs "$a" >"$EV/logs-a.txt" 2>&1; pj logs "$b" >"$EV/logs-b.txt" 2>&1
fa=$(grep -c CHILD-A-DONE "$EV/logs-a.txt"); fb=$(grep -c CHILD-B-DONE "$EV/logs-b.txt")
# A reply to the prompt itself contains the marker once ([User] line), so require >= 2 (prompt + the child's reply).
snap final
ev=$(python3 - "$parent" "$a" "$b" "$arc_rc" "$det_rc" "$lin_a" "$lin_b" "$lin_a2" "$samples" "$fa" "$fb" "$wa" "$wb" "$(field final "$a" status)" "$(field final "$b" status)" "$EV" <<'PY'
import json, sys
k = ["parent", "childA_detached", "childB_attached", "archiveRc", "detachRc", "lineageA_before", "lineageB_before", "lineageA_afterDetach",
     "samples", "markerHitsA", "markerHitsB", "waitRcA", "waitRcB", "finalStatusA", "finalStatusB", "evidenceDir"]
print(json.dumps(dict(zip(k, sys.argv[1:])), separators=(",", ":")))
PY
)
# Verdict: both children still running at t+30s (the tasks last 60 s), and both wrote their marker in a reply (the prompt holds it once).
[ "$sa" = running ] && [ "$sb" = running ] && [ "$fa" -ge 2 ] && [ "$fb" -ge 2 ] && pass "$ev"
fail "a child did not survive its parent's archive (t+30s: A=$sa B=$sb; markers A=$fa B=$fb)" "$ev"
