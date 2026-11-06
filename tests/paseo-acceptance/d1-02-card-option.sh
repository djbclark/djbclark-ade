#!/usr/bin/env bash
# d1-02-card-option
# CONTRACT: D1.2/B3: a parent can answer a question card's OPTION (not only allow/deny) through the surface a parent has
# EXPECT:   the agent's next turn shows the chosen option's text (option 2, never option 1)
# ON-FAIL:  B3 and G4 are redesigned: question cards go to the operator, never to a parent
# SCOPE:    second daemon only
# HOW:      bash tests/paseo-acceptance/d1-02-card-option.sh   (about 2 min, two short omp/haiku turns, API credits)
#           PROVIDER=omp MODEL=anthropic/claude-haiku-4-5 are the defaults; the Claude subscription pool is NEVER used
#           (djbclark 2026-11-02), so the claude provider is not probed here (exit 77 if PROVIDER=claude is asked for).
# NEEDS:    isolated daemon (lib/common.sh); omp installed and logged in under the real home (read-only reference)
# STATUS:   run 2026-11-02, PASS (docs/d1-implementation-plan.md T5); answer shape for omp: updatedInput.answers["Response"]
# Steps:    (a) CLI: a plain `paseo permit allow AGENT REQ --input '{"answers":{"Response":"<option 2>"}}'` answers agent A's card.
#           (b) MCP: the paseo MCP tool respond_to_permission (lib/mcp_call.py, over the socket) answers agent B's card.
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-02-card-option
. "$here/lib/common.sh"
ON_FAIL='B3 and G4 are redesigned: question cards go to the operator, never to a parent'
PROVIDER="${PROVIDER:-omp}"
MODEL="${MODEL:-anthropic/claude-haiku-4-5}"
[ "$PROVIDER" != claude ] || skip "claude pool protected (djbclark 2026-11-02): use PROVIDER=omp, whose Claude models bill API credits"
OPT1=crimson-7; OPT2=teal-9

isolated_up card; trap isolated_down EXIT
work="$ACC_BASE/work"; mkdir -m 700 "$work"

# omp is not enabled in a fresh home; the config hot-reloads (checked 2026-11-02). Keys come from PersistedConfigSchema.
paseo daemon config set agents.providers '{"omp":{"enabled":true}}' --home "$PASEO_HOME" >/dev/null 2>"$ACC_BASE/config-omp.err" \
  || die "enabling the omp provider failed (see $ACC_BASE/config-omp.err)"
ready=0
for i in $(seq 1 45); do
  pj provider ls --json 2>/dev/null | python3 -c '
import json, sys
p = [x for x in json.load(sys.stdin) if x.get("provider") == sys.argv[1]]
sys.exit(0 if p and p[0].get("enabled") == "Enabled" and p[0].get("status") not in ("loading", "unavailable") else 1)' "$PROVIDER" && { ready=1; break; }
  sleep 2
done
pj provider ls --json > "$ACC_BASE/provider-ls.json" 2>/dev/null
[ "$ready" = 1 ] || skip "provider $PROVIDER never became ready on the isolated daemon (see $ACC_BASE/provider-ls.json)"

# json_field FILE PYEXPR: print one value from a JSON file (the parsed object is `d`).
json_field() { python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$1" "$2" 2>/dev/null; }

# start_asker NAME: agent that raises a question card with two options; prints its id.
start_asker() {
  local name="$1" out="$ACC_BASE/$1-run.json"
  pj run --json --no-wait --provider "$PROVIDER" --model "$MODEL" --cwd "$work" --title "card-$name" \
    "Call the ask tool exactly once: one question, 'Which token?', with exactly two options labelled '$OPT1' and '$OPT2'. After you receive the answer, reply with exactly one line: the word PICKED, a colon, then the label you were given, and nothing else." \
    > "$out" 2>"$ACC_BASE/$name-run.err" || return 1
  json_field "$out" 'd.get("agentId") or d.get("id")'
}

# wait_card ID: poll `permit ls` until the agent has a pending permission; print its request id, save the lists.
# (`inspect --json` prints capitalised keys, PendingPermissions[].{id,tool}; `permit ls --json` has {id,agentId,name}.)
wait_card() {
  local id="$1" i req
  for i in $(seq 1 60); do
    pj permit ls --json > "$ACC_BASE/$id-permit-ls.json" 2>/dev/null
    req=$(python3 -c '
import json, sys
for p in json.load(open(sys.argv[1])):
    if p.get("agentId") == sys.argv[2]:
        print(p["id"]); break' "$ACC_BASE/$id-permit-ls.json" "$id" 2>/dev/null)
    [ -n "$req" ] && { pj inspect "$id" --json > "$ACC_BASE/$id-inspect.json" 2>/dev/null; printf '%s' "$req"; return 0; }
    sleep 2
  done
  return 1
}

# picked ID: wait for the agent's turn to end, then print the PICKED line from its text log (empty if none).
picked() {
  local id="$1" i line
  for i in $(seq 1 45); do
    pj logs "$id" > "$ACC_BASE/$id-logs.txt" 2>/dev/null
    line=$(ggrep -oE '^PICKED: ?[A-Za-z0-9-]+$' "$ACC_BASE/$id-logs.txt" | tail -1)
    [ -n "$line" ] && { printf '%s' "$line"; return 0; }
    sleep 2
  done
  return 1
}

# ---- (a) CLI surface -------------------------------------------------------------------------------------------
ida=$(start_asker a) || fail "creating agent A failed" "{\"stderr\":\"$ACC_BASE/a-run.err\"}"
[ -n "$ida" ] || fail "agent A id not parsed" "{\"run\":\"$ACC_BASE/a-run.json\"}"
reqa=$(wait_card "$ida") || fail "no question card appeared for agent A" "{\"agent\":\"$ida\",\"inspect\":\"$ACC_BASE/$ida-inspect.json\"}"
pj permit ls --json > "$ACC_BASE/permit-ls-a.json" 2>/dev/null
cardkind=$(json_field "$ACC_BASE/$ida-inspect.json" 'd["PendingPermissions"][0]["tool"]')
pj permit allow "$ida" "$reqa" --input "{\"answers\":{\"Response\":\"$OPT2\"}}" > "$ACC_BASE/permit-allow-a.out" 2>&1
rca=$?
linea=$(picked "$ida"); [ -n "$linea" ] || linea=""
case "$linea" in *"$OPT2") a_ok=true;; *) a_ok=false;; esac
case "$linea" in *"$OPT1") a_wrong=true;; *) a_wrong=false;; esac

# ---- (b) MCP surface: the paseo MCP tool a parent agent would call, respond_to_permission, on agent B's card -----
# A real parent agent cannot be used here: the daemon injects the `paseo` MCP server into agents only for a TCP listener
# (bootstrap.js createAgentMcpBaseUrl), and the isolated daemon listens on a Unix socket (a first run on 2026-11-02 had
# an omp parent with no MCP tools: it fell back to `paseo permit allow` through bash). lib/mcp_call.py therefore calls
# the same /mcp/agents endpoint over the socket; both surfaces end in agentManager.respondToPermission.
idb=$(start_asker b) || fail "creating agent B failed" "{\"a\":$a_ok}"
reqb=$(wait_card "$idb") || fail "no question card appeared for agent B" "{\"agent\":\"$idb\",\"a\":$a_ok}"
sock="$ACC_BASE/paseo.sock"
python3 "$here/lib/mcp_call.py" "$sock" "$ACC_BASE/password" list_pending_permissions '{}' > "$ACC_BASE/mcp-list.json" 2>"$ACC_BASE/mcp-list.err"
mcp_lists=false; ggrep -q "$reqb" "$ACC_BASE/mcp-list.json" && mcp_lists=true
python3 "$here/lib/mcp_call.py" "$sock" "$ACC_BASE/password" respond_to_permission \
  "{\"agentId\":\"$idb\",\"requestId\":\"$reqb\",\"response\":{\"behavior\":\"allow\",\"updatedInput\":{\"answers\":{\"Response\":\"$OPT2\"}}}}" \
  > "$ACC_BASE/mcp-respond.json" 2>"$ACC_BASE/mcp-respond.err"
rcb=$?
lineb=$(picked "$idb"); [ -n "$lineb" ] || lineb=""
case "$lineb" in *"$OPT2") b_ok=true;; *) b_ok=false;; esac
case "$lineb" in *"$OPT1") b_wrong=true;; *) b_wrong=false;; esac

ev="{\"provider\":\"$PROVIDER\",\"model\":\"$MODEL\",\"cardKind\":\"${cardkind:-}\",\"answerShape\":\"updatedInput.answers[Response]=<option label>\",\"cli\":{\"ok\":$a_ok,\"wrongOption\":$a_wrong,\"permitAllowRc\":$rca,\"line\":\"$linea\"},\"mcp\":{\"ok\":$b_ok,\"wrongOption\":$b_wrong,\"listedCard\":$mcp_lists,\"respondRc\":$rcb,\"line\":\"$lineb\"},\"evidence\":\"$ACC_BASE\"}"
if { [ "$a_ok" = true ] && [ "$a_wrong" = false ]; } || { [ "$b_ok" = true ] && [ "$b_wrong" = false ]; }; then
  { [ "$a_ok" = true ] && [ "$b_ok" = true ]; } || echo "NOTE: only one surface carried the option (cli=$a_ok mcp=$b_ok): see $ACC_BASE" >&2
  pass "$ev"
fi
fail "neither the CLI nor the MCP path carried option 2" "$ev"
