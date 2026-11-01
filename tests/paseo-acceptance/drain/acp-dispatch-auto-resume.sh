#!/usr/bin/env bash
# acp-dispatch-auto-resume
# CONTRACT: D0.2: no auto-resume job of acp-dispatch is pending
# EXPECT:   no pending resume record, exit 0
# ON-FAIL:  a resume is pending: let it finish or cancel it before disabling
# SCOPE:    read-only (reads launchd, relay and git state; changes nothing)
# HOW:      bash tests/paseo-acceptance/drain/acp-dispatch-auto-resume.sh
# NEEDS:    ~/.local/state/acp-dispatch (UNVERIFIED path: confirm in bin/acp-dispatch)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=acp-dispatch-auto-resume
. "$here/lib/common.sh"
ON_FAIL=a\ resume\ is\ pending:\ let\ it\ finish\ or\ cancel\ it\ before\ disabling
d="${ACP_DISPATCH_STATE:-$HOME/.local/state/acp-dispatch}"
[ -d "$d" ] || skip "no $d (UNVERIFIED state dir)"
n=$(find "$d" -type f \( -name '*resume*' -o -name '*.pending' \) 2>/dev/null | wc -l | tr -d ' ')
printf '{"tool":"acp-dispatch-auto-resume","held":%s,"evidence":"%s resume or pending files under %s"}\n' "$n" "$n" "$d"
[ "$n" = 0 ]
