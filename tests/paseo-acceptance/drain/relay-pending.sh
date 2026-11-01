#!/usr/bin/env bash
# relay-pending
# CONTRACT: D0.2 item b: no queued or stuck relay message (PR 177 makes this a query)
# EXPECT:   relay.py --status reports zero queued and zero stuck, exit 0
# ON-FAIL:  an unsent or unacked message exists: deliver and verify it (AGENTS.md order 10) before disabling
# SCOPE:    read-only (reads launchd, relay and git state; changes nothing)
# HOW:      bash tests/paseo-acceptance/drain/relay-pending.sh
# NEEDS:    PR 177 merged (relay.py --status); before it, only --pending is read
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=relay-pending
. "$here/lib/common.sh"
ON_FAIL=an\ unsent\ or\ unacked\ message\ exists:\ deliver\ and\ verify\ it\ \(AGENTS.md\ order\ 10\)\ before\ disabling
R="${RELAY_PY:-$HOME/src/djbclark-ade/skills/session-finder/relay.py}"
[ -f "$R" ] || skip "no $R"
if python3 "$R" --help 2>&1 | ggrep -q -- '--status'; then
  out=$(python3 "$R" --status 2>&1); rc=$?
else
  out=$(python3 "$R" --pending 2>&1); rc=$?; echo "NOTE: PR 177 not merged: only --pending read" >&2
fi
[ "$rc" = 0 ] || skip "relay rc=$rc"
n=$(printf '%s\n' "$out" | ggrep -ci 'queued\|stuck\|pending' )
printf '{"tool":"relay.py","held":%s,"evidence":%s}\n' "$n" "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[:2000]))')"
[ "$n" = 0 ]
