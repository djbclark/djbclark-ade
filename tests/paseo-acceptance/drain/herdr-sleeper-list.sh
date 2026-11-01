#!/usr/bin/env bash
# herdr-sleeper-list
# CONTRACT: D0.2: no idle-agent sleeper entry holds work before herdr-sleeper is disabled
# EXPECT:   empty list, exit 0
# ON-FAIL:  a sleeping agent holds work: wake or finish it before disabling
# SCOPE:    read-only (reads launchd, relay and git state; changes nothing)
# HOW:      bash tests/paseo-acceptance/drain/herdr-sleeper-list.sh
# NEEDS:    bin/herdr-sleeper in the main checkout
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=herdr-sleeper-list
. "$here/lib/common.sh"
ON_FAIL=a\ sleeping\ agent\ holds\ work:\ wake\ or\ finish\ it\ before\ disabling
HS="${HERDR_SLEEPER:-$HOME/src/djbclark-ade/bin/herdr-sleeper}"
[ -x "$HS" ] || skip "no $HS"
out=$("$HS" list 2>&1); rc=$?
[ "$rc" = 0 ] || skip "herdr-sleeper list rc=$rc"
n=$(printf '%s\n' "$out" | ggrep -c '[^[:space:]]')
printf '{"tool":"herdr-sleeper","held":%s,"evidence":%s}\n' "$n" "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[:2000]))')"
[ "$n" = 0 ]
