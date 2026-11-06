#!/usr/bin/env bash
# d1-01-steer
# CONTRACT: D1.1/B2: a send with --behavior steer to a RUNNING agent queues as the next input instead of killing its turn, per provider
# EXPECT:   per provider: turn survives, the marker arrives as input to the same turn or the next, no interrupt entry in the timeline
# ON-FAIL:  that provider is 'queue only' in G3's table (plan D1.1)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      PROVIDERS='omp codex' bash tests/paseo-acceptance/d1-01-steer.sh   (default: the C2 'available' list minus antigravity
#           and the protected pools claude, cline, opencode: djbclark 2026-11-02, those pools must not run out)
# NEEDS:    isolated daemon (lib/common.sh isolated_up), the provider logged in under the real $HOME, about one short paid turn each
# STATUS:   run 2026-11-02 (CLI 0.15.0-beta.1); results in docs/d1-implementation-plan.md T4 and steer-matrix.json
# Output:   $ACC_RESULTS/steer-matrix.json (provider -> steers/queues/interrupts/evidence), per-provider evidence in $ACC_BASE/ev-<p>/
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-01-steer
. "$here/lib/common.sh"
ON_FAIL="that provider is 'queue only' in G3's table (plan D1.1)"
PROVIDERS=${PROVIDERS:-"codex copilot omp grok cursor glm-acp-agent hermes qwen-code"}
SLEEP_S=${SLEEP_S:-60}
# Providers a fresh home does not know (they live in the live config's agents.providers): copied without credentials.
ACC_PROVIDER_IDS="" ; for p in $PROVIDERS; do case "$p" in omp|grok|cursor|glm-acp-agent|hermes|qwen-code) ACC_PROVIDER_IDS="$ACC_PROVIDER_IDS $p";; esac; done
export ACC_PROVIDER_IDS

# cheapest model and mode per provider (decision 2026-11-02; `paseo provider models P`). Empty mode = the provider's default.
model_of() { case "$1" in
  codex) echo gpt-6-luna;; copilot) echo gemini-3.8-flash;; omp) echo anthropic/claude-haiku-5-5;;
  grok) echo grok-4.7-build-fast;; cursor) echo composer-2.5;; glm-acp-agent) echo glm-5.3-flash;;
  hermes) echo nous:openai/gpt-6-luna;; qwen-code) echo 'qwen3.5-plus(openai)';; *) echo "";; esac; }
mode_of() { case "$1" in codex) echo full-access;; *) echo "";; esac; }

for p in $PROVIDERS; do case "$p" in claude|cline|opencode) die "provider $p is a protected pool (djbclark 2026-11-02): refused";; esac; done
isolated_up steer; trap isolated_down EXIT

allow_pending() {   # approve whatever the isolated daemon is waiting on (unknown yolo mode ids per ACP provider)
  local ids
  ids=$(pj permit ls --json 2>/dev/null | python3 -c 'import json,sys
for x in json.load(sys.stdin): print(x.get("id") or x.get("requestId") or "")' 2>/dev/null) || return 0
  for i in $ids; do [ -n "$i" ] && pj permit allow "$i" >/dev/null 2>&1; done
}

results="$ACC_BASE/rows.jsonl"; : > "$results"
for p in $PROVIDERS; do
  ev="$ACC_BASE/ev-$p"; mkdir -p "$ev"
  marker="MARKER$RANDOM$RANDOM"; echo "$marker" > "$ev/marker"; mode=$(mode_of "$p")
  model=${STEER_MODEL:-$(model_of "$p")}   # STEER_MODEL overrides, for a one-provider retry
  mkdir -p "$ACC_BASE/work"
  args=(run -q --no-wait --provider "$p" --title "steer-$p" --label "acc=d1-01" --cwd "$ACC_BASE/work")
  [ -n "$model" ] && args+=(--model "$model"); [ -n "$mode" ] && args+=(--mode "$mode")
  prompt="Run exactly one shell command: sleep $SLEEP_S. Wait for it to finish. Then reply with the single word FIRST and nothing else."
  id=$(pj "${args[@]}" "$prompt" 2>"$ev/run.err" | tail -n 1); rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ] || [ -z "$id" ]; then
    printf '{"provider":"%s","verdict":"create-failed","steers":false,"queues":false,"interrupts":false,"evidence":{"dir":"%s"}}\n' "$p" "$ev" >> "$results"; continue
  fi
  echo "$id" > "$ev/agent.id"
  # wait (max 120 s) until a shell tool call is on the timeline, i.e. the turn is really inside the sleep
  tool=0
  for i in $(seq 1 60); do
    allow_pending
    pj logs "$id" --json > "$ev/pre.json" 2>/dev/null
    if python3 "$here/lib/steer_analyze.py" intool "$ev/pre.json"; then tool=1; break; fi
    sleep 2
  done
  date +%s > "$ev/steer.t"
  if [ $tool = 1 ]; then
    pj send --behavior steer --no-wait "$id" "Also: after you answer, on a new line, reply with the exact token $marker." >"$ev/send.out" 2>"$ev/send.err"; echo "$?" > "$ev/send.rc"
  else
    echo "no-tool" > "$ev/send.rc"
  fi
  # let the turn(s) finish: stop when the marker is answered, or when the log has not changed for 30 s after the sleep has ended
  t0=$(cat "$ev/steer.t"); stable=0; prev=""; loops=150; [ "$tool" = 1 ] || loops=1   # no tool call: nothing was sent, one look is enough
  for i in $(seq 1 "$loops"); do
    allow_pending
    sleep 2
    pj logs "$id" --json > "$ev/post.json" 2>/dev/null
    python3 "$here/lib/steer_analyze.py" settled "$ev/post.json" "$marker" && break
    cur=$(cksum < "$ev/post.json")
    if [ "$cur" = "$prev" ]; then stable=$((stable + 1)); else stable=0; fi
    prev="$cur"
    [ $(( $(date +%s) - t0 )) -gt $((SLEEP_S + 20)) ] && [ "$stable" -ge 15 ] && break
  done
  pj inspect "$id" --json > "$ev/inspect.json" 2>/dev/null
  pj ls --json -a > "$ev/ls.json" 2>/dev/null
  python3 "$here/lib/steer_analyze.py" verdict "$p" "$ev" "$marker" "$(cat "$ev/send.rc")" >> "$results"
  pj agent archive --force "$id" >/dev/null 2>&1 || pj archive --force "$id" >/dev/null 2>&1 || true
done

mkdir -p "$ACC_RESULTS/d1-01-evidence"   # /var/folders is reaped by the OS: keep the transcripts with the results (2026-11-06: run 1's were emptied)
for d in "$ACC_BASE"/ev-*; do rm -rf "$ACC_RESULTS/d1-01-evidence/${d##*/ev-}"; cp -R "$d" "$ACC_RESULTS/d1-01-evidence/${d##*/ev-}"; done
python3 "$here/lib/steer_analyze.py" matrix "$results" "$ACC_RESULTS/steer-matrix.json" "$ACC_BASE" || fail "matrix could not be written" "{\"rows\":\"$results\"}"
bad=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(",".join(p for p,v in m["providers"].items() if v.get("verdict") in ("interrupts","lost","unanswered")))' "$ACC_RESULTS/steer-matrix.json")
gone=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(",".join(p for p,v in m["providers"].items() if v.get("verdict") in ("provider-error","no-tool","create-failed")))' "$ACC_RESULTS/steer-matrix.json")
[ -z "$bad" ] || fail "the steer interrupted the turn or the marker never arrived (interrupts, lost or unanswered): $bad" "{\"matrix\":\"$ACC_RESULTS/steer-matrix.json\",\"notSurviving\":\"$bad\",\"notProbed\":\"$gone\"}"
[ -z "$gone" ] || { record_result skip "{\"matrix\":\"$ACC_RESULTS/steer-matrix.json\",\"notProbed\":\"$gone\"}" >/dev/null; skip "no verdict for (provider error, quota, auth or no tool call): $gone"; }
pass "{\"matrix\":\"$ACC_RESULTS/steer-matrix.json\"}"
