#!/bin/bash
# relocate-pane.sh — wake a herdr-sleeper pane, move/relabel it, sleep it again.
#
#   relocate-pane.sh <pane-id> <workspace-id|-> <tab-label> <topic>
#
# <workspace-id> "-" relabels in place (tab + pane + agent) without moving.
# Pane label becomes "<topic>-p", agent name "<topic>"; the sleeper records
# the new label and the terminal_id so the record follows later moves.
# Live (non-sleeping) panes: skip the wake/sleep steps by hand; this script
# is for panes in the sleeper journal. See references/workspace-layout.md.
set -u
S=${HERDR_SLEEPER:-$HOME/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper}
pane=$1 ws=$2 tab=$3 base=$4
test "${HERDR_ENV:-}" = 1 || { echo "not inside herdr" >&2; exit 1; }
echo "== $pane -> ws=$ws tab=$tab topic=$base"
"$S" wake "$pane" || { echo "WAKE FAILED $pane" >&2; exit 1; }
st=
for _ in $(seq 1 30); do
  st=$(herdr agent get "$pane" 2>/dev/null | python3 -c 'import sys,json; a=json.load(sys.stdin)["result"]["agent"]; print(a.get("agent"),a["agent_status"])' 2>/dev/null)
  case "$st" in "claude idle"|"claude done") break;; esac
  sleep 2
done
echo "state: $st"
if [ "$ws" != "-" ]; then
  pane=$(herdr pane move "$pane" --new-tab --workspace "$ws" --label "$tab" --no-focus \
         | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["move_result"]["pane"]["pane_id"])') \
    || { echo "MOVE FAILED" >&2; exit 1; }
  echo "moved to $pane"
else
  tabid=$(herdr pane get "$pane" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["pane"]["tab_id"])')
  herdr tab rename "$tabid" "$tab" >/dev/null
fi
herdr pane rename "$pane" "$base-p" >/dev/null
herdr agent rename "$pane" "$base" >/dev/null
sleep 2
"$S" sleep-pane "$pane" || { echo "SLEEP FAILED $pane" >&2; exit 1; }
echo "done: $pane"
