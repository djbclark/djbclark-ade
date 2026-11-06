#!/usr/bin/env bash
# d1-07b-create-origin
# CONTRACT: D1.7b/G2.8: does agent.create.before tell a plugin-SDK create from an MCP or CLI create?
# EXPECT:   the logged create payloads differ in a field that names the origin; the answer is written down either way
# ON-FAIL:  G2.8's herald-label refusal is dropped; the deleteHelpers:false assertion stays the only control
# SCOPE:    second daemon only (installs fixtures/origin-probe-plugin into the TEST home only)
# HOW:      bash tests/paseo-acceptance/d1-07b-create-origin.sh   (about 3 min; 3 one-word turns on ORIGIN_PROVIDER, see lib/origin-probe.sh)
# NEEDS:    isolated daemon; curl; the antigravity provider (or PROBE_PROVIDER=provider/model; never the Claude pool, cline or opencode-go)
# PATHS:    cli (`paseo run`), mcp-top (create_agent, no caller), mcp-sub (create_agent with callerAgentId, i.e. an agent's
#           own MCP client), sdk (the plugin calls paseo.agents.create, the same daemonClient.createAgent the app uses).
#           The Desktop/mobile UI create cannot be scripted: recorded N/A (the app sends the same create_agent_request as the CLI/SDK).
# STATUS:   RUN 2026-11-02 on Paseo 0.15.0-beta.1 (docs/d1-implementation-plan.md T11 "Checked")
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-07b-create-origin
. "$here/lib/common.sh"; . "$here/lib/origin-probe.sh"
ON_FAIL=G2.8\'s\ herald-label\ refusal\ is\ dropped\;\ the\ deleteHelpers:false\ assertion\ stays\ the\ only\ control
live_before=$(live_config_sha)
base_tmp="${TMPDIR:-/tmp}"; base_tmp="${base_tmp%/}"
export ORIGIN_LOG="$base_tmp/ade-origin-$$.log" ORIGIN_TRIGGER="$base_tmp/ade-origin-$$.trigger"
: > "$ORIGIN_LOG"; rm -f "$ORIGIN_TRIGGER"
isolated_up origin; trap 'isolated_down; rm -f "$ORIGIN_TRIGGER"' EXIT
mkdir -p "$ACC_BASE/work"
origin_setup "$here" || skip "origin-probe plugin did not start (see $ACC_BASE/plugin-install.out)"
# The agent-scoped MCP catalog (callerAgentId) is empty unless injection is on (docs/mcp: daemon.mcp.injectIntoAgents, default false):
# without it the mcp-sub call answers "Method not found". Isolated home only; set before any agent is created.
paseo daemon config set daemon.mcp.injectIntoAgents true --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/inject.err" || skip "cannot set daemon.mcp.injectIntoAgents on the test home"
pj reload >/dev/null 2>&1; sleep 2
prompt="reply with the single word OK"
ids="{}"
add_id() { ids=$(python3 -c 'import json, sys; d = json.loads(sys.argv[1]); d[sys.argv[2]] = sys.argv[3]; print(json.dumps(d))' "$ids" "$1" "$2"); }

# A. CLI
a=$(pj run --no-wait -q --provider "$ORIGIN_PROVIDER" --cwd "$ACC_BASE/work" --title cli-create "$prompt" 2>"$ACC_BASE/cli-run.err" | tail -1)
[ -n "$a" ] || fail "paseo run returned no agent id (see $ACC_BASE/cli-run.err)" "$(versions_json)"
add_id cli "$a"
pj wait --timeout 120 "$a" >/dev/null 2>&1

# B. MCP, top-level caller
r=$(origin_mcp create_agent "$(python3 -c 'import json, sys; print(json.dumps({"provider": sys.argv[1], "cwd": sys.argv[2], "title": "mcp-top", "initialPrompt": sys.argv[3]}))' "$ORIGIN_PROVIDER" "$ACC_BASE/work" "$prompt")" 2>"$ACC_BASE/mcp-top.err")
printf '%s\n' "$r" > "$ACC_BASE/mcp-top.out"
b=$(origin_agent_id_from_mcp "$r"); [ -n "$b" ] && add_id mcp-top "$b"

# C. MCP, as the agent's own MCP client (callerAgentId = A): a subagent create
# (no cwd: an agent-scoped call that names one is parsed as the legacy relationship/workspace shape and refused; it inherits the caller's workspace)
r=$(origin_mcp create_agent "$(python3 -c 'import json, sys; print(json.dumps({"provider": sys.argv[1], "title": "mcp-sub", "initialPrompt": sys.argv[2]}))' "$ORIGIN_PROVIDER" "$prompt")" "$a" 2>"$ACC_BASE/mcp-sub.err")
printf '%s\n' "$r" > "$ACC_BASE/mcp-sub.out"
c=$(origin_agent_id_from_mcp "$r"); [ -n "$c" ] && add_id mcp-sub "$c"

# D. plugin SDK create (no prompt: no turn)
python3 -c 'import json, sys; json.dump({"provider": sys.argv[1], "cwd": sys.argv[2], "title": "sdk-create"}, open(sys.argv[3], "w"))' "$ORIGIN_PROVIDER" "$ACC_BASE/work" "$ORIGIN_TRIGGER"
origin_wait_hook '"sdkCreate":"' 30 || true
sleep 1
for x in "$b" "$c"; do [ -z "$x" ] || pj wait --timeout 120 "$x" >/dev/null 2>&1; done
sleep 3
cp "$ORIGIN_LOG" "$ACC_BASE/origin.log"
python3 "$here/lib/origin-diff.py" "$ACC_BASE/origin.log" cli=cli-create mcp-top=mcp-top mcp-sub=mcp-sub sdk=sdk-create > "$ACC_BASE/origin-diff.json" \
  || fail "origin-diff.py failed" "$(versions_json)"
[ "$(live_config_sha)" = "$live_before" ] || die "the LIVE config hash changed during the probe"
missing=$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1]))["paths"]; print(" ".join(sorted(f"{n}:{h}" for n, p in d.items() for h, ok in p["found"].items() if not ok)))' "$ACC_BASE/origin-diff.json")
[ -z "$missing" ] || fail "no hook payload logged for: $missing (evidence in $ACC_BASE)" "$(versions_json)"
sdk_state=$(ggrep -o '"sdkCreate":"[a-z]*"' "$ORIGIN_LOG" | tail -1)
verdict=$(python3 - "$ACC_BASE/origin-diff.json" "$sdk_state" "$ids" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
ev = {"diff": d, "sdkCreate": sys.argv[2], "agents": json.loads(sys.argv[3]), "uiCreate": "N/A: cannot be scripted; the app and plugin SDK use the same daemon createAgent path as the CLI"}
peers = sorted(d["originFieldsPeers"])
subs = sorted(k for k in d["originFields"] if k not in d["originFieldsPeers"])
ev["peerOriginFields"] = peers
ev["agentOriginFields"] = subs
ev["answer"] = (("signal exists between cli/mcp-top/sdk: " + ", ".join(peers)) if peers
                else "none: cli, mcp-top and sdk creates are indistinguishable in agent.create.before and agent.open.before") \
    + ("; an agent-originated (subagent) create differs in: " + ", ".join(subs) if subs else "")
print(json.dumps(ev, sort_keys=True))
PY
)
echo "G2.8 answer: $(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["answer"])' "$verdict")" >&2
echo "evidence: $ACC_BASE (origin.log, origin-diff.json)" >&2
pass "$(python3 -c 'import json, sys; d = json.loads(sys.argv[1]); d.update(json.loads(sys.argv[2])); print(json.dumps(d))' "$verdict" "$(versions_json)")"
