#!/usr/bin/env bash
# d1-01-steer
# CONTRACT: D1.1/B2: a send with --behavior steer to a RUNNING agent queues as the next input instead of killing its turn, per provider
# EXPECT:   per provider: turn survives, the marker arrives as input to the same turn or the next, no interrupt entry in the timeline
# ON-FAIL:  that provider is 'queue only' in G3's table (plan D1.1)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      PROVIDERS='claude codex omp' bash tests/paseo-acceptance/d1-01-steer.sh   (default: the C2 'available' list minus antigravity)
# NEEDS:    isolated daemon (lib/common.sh isolated_up), one logged-in cheapest model per provider (open question 2), about one short paid turn each
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-01-steer
. "$here/lib/common.sh"
ON_FAIL=that\ provider\ is\ \'queue\ only\'\ in\ G3\'s\ table\ \(plan\ D1.1\)
PROVIDERS=${PROVIDERS:-"claude codex copilot opencode omp cline grok cursor glm-acp-agent hermes qwen-code"}
isolated_up steer; trap isolated_down EXIT
rows=""
for p in $PROVIDERS; do
  marker="MARK-$RANDOM"
  id=$(pj run -q --no-wait --provider "$p" --mode bypass --title "steer-$p" \
    "Run the shell command 'sleep 45', then reply with the single word FIRST." 2>/dev/null) || { rows="$rows{\"p\":\"$p\",\"verdict\":\"create-failed\"},"; continue; }
  for i in $(seq 1 30); do pj ls --json | grep -q "\"$id\".*" && pj ls --json | python3 -c "import json,sys; a=[x for x in json.load(sys.stdin) if x['id']=='$id']; sys.exit(0 if a and a[0]['status']=='running' else 1)" && break; sleep 2; done
  pj send --behavior steer --no-wait "$id" "When you finish, also reply with the exact token $marker." >/dev/null 2>&1
  pj wait --timeout 240 "$id" >/dev/null 2>&1
  log=$(pj logs "$id" 2>/dev/null)
  has_marker=$(printf '%s' "$log" | grep -c "$marker")
  interrupted=$(printf '%s' "$log" | grep -ciE 'interrupt|cancel|aborted')   # UNVERIFIED: timeline wording
  first=$(printf '%s' "$log" | grep -c FIRST)
  v=queues; [ "$first" = 0 ] && v=interrupts; [ "$has_marker" = 0 ] && v=lost
  rows="$rows{\"p\":\"$p\",\"verdict\":\"$v\",\"marker\":$has_marker,\"interruptWords\":$interrupted},"
done
ev="{\"providers\":[${rows%,}]}"
case "$ev" in *interrupts*|*lost*|*create-failed*) fail "some providers do not queue a steer" "$ev";; esac
pass "$ev"
