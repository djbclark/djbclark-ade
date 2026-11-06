#!/usr/bin/env bash
# lib/origin-probe.sh: helpers shared by d1-07b-create-origin.sh and d1-10-reopen-hook.sh (plan T11). Source it after
# lib/common.sh. Functions only. Second daemon only: every call goes through pj or the isolated daemon's own socket.
# Hook names and the plugin shape CONFIRMED 2026-11-02 against https://paseo.sh/docs/plugins/hooks.md (Paseo >= 0.14).

# Cheapest paid turn available without touching the protected pools (Claude subscription, cline, opencode-go):
# Antigravity's Gemini 3.8 Flash (Low) (aiuse 2026-11-02: Gemini weekly 62% headroom). Override with PROBE_PROVIDER.
ORIGIN_PROVIDER="${PROBE_PROVIDER:-antigravity/gemini-3.8-flash-low}"

# origin_setup: ORIGIN_LOG and ORIGIN_TRIGGER must be exported BEFORE isolated_up (the plugin process inherits the daemon's
# environment); then enable plugins on the isolated daemon only (isolated_up leaves pluginsEnabled=false), install the
# probe plugin from the repo fixture, reload it and wait until it reports `running`. Returns 1 with a reason on stderr.
origin_setup() {
  local here="${1:?usage: origin_setup TESTS_DIR}" i st
  require_isolated
  paseo daemon config set pluginsEnabled true --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/plugin-enable.err" \
    || { echo "config set pluginsEnabled failed: $(cat "$ACC_BASE/plugin-enable.err")" >&2; return 1; }
  pj plugin install "$here/fixtures/origin-probe-plugin" >"$ACC_BASE/plugin-install.out" 2>&1 \
    || { echo "plugin install failed: see $ACC_BASE/plugin-install.out" >&2; return 1; }
  pj plugin reload origin-probe >/dev/null 2>&1
  for i in $(seq 1 20); do
    st=$(pj plugin ls --json 2>/dev/null | python3 -c 'import json, sys; print(next((p.get("status") for p in json.load(sys.stdin) if p.get("id") == "origin-probe"), ""))')
    [ "$st" = running ] && return 0
    sleep 1
  done
  echo "origin-probe never reached running (last status: ${st:-none})" >&2; return 1
}

# origin_wait_hook PATTERN [SECONDS]: wait until the log has a line matching the fixed string PATTERN.
origin_wait_hook() {
  local pat="$1" n="${2:-60}" i
  for i in $(seq 1 "$n"); do ggrep -qF -- "$pat" "$ORIGIN_LOG" 2>/dev/null && return 0; sleep 1; done
  return 1
}

# origin_mcp TOOL ARGS_JSON [CALLER_AGENT_ID]: call one Paseo MCP tool on the isolated daemon over its unix socket
# (/mcp/agents; the password is read from a 0600 header file, never argv). Prints the raw JSON-RPC response (SSE data
# line or JSON) to stdout; a non-2xx status makes it return 1. A caller id is the query parameter the daemon injects for
# its own agents' MCP clients: it is how an agent-originated create (a subagent) is made without a paid turn.
origin_mcp() {
  local tool="$1" args="$2" caller="${3:-}" url="http://localhost/mcp/agents" hdr="$ACC_BASE/mcp.hdr" body
  [ -s "$hdr" ] || (umask 077; printf 'Authorization: Bearer %s\n' "$(cat "$ACC_BASE/password")" > "$hdr")
  [ -z "$caller" ] || url="$url?callerAgentId=$caller"
  body=$(python3 -c 'import json, sys; print(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])}}))' "$tool" "$args") || return 1
  timeout 60 curl -sS --fail-with-body --unix-socket "$ACC_BASE/paseo.sock" -H "@$hdr" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d "$body" "$url"
}

# origin_agent_id_from_mcp RESPONSE: the agentId in a create_agent response (structuredContent or text), empty if none.
origin_agent_id_from_mcp() {
  python3 -c '
import json, re, sys
raw = sys.stdin.read()
m = re.search(r"\"agentId\"\s*:\s*\"([^\"\\\\]+)\"", raw)
print(m.group(1) if m else "")' <<<"$1"
}
