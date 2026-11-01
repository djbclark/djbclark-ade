#!/usr/bin/env bash
# bigteam-inboxes
# CONTRACT: D0.2: no unanswered lead message sits in a bigteam jobs inbox
# EXPECT:   every '## MSG N' has a REPLY N, exit 0
# ON-FAIL:  an unanswered inbox message exists: answer it before disabling bigteam's inbox path
# SCOPE:    read-only (reads launchd, relay and git state; changes nothing)
# HOW:      bash tests/paseo-acceptance/drain/bigteam-inboxes.sh
# NEEDS:    ~/.local/state/bigteam
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=bigteam-inboxes
. "$here/lib/common.sh"
ON_FAIL=an\ unanswered\ inbox\ message\ exists:\ answer\ it\ before\ disabling\ bigteam\'s\ inbox\ path
root="${BIGTEAM_STATE:-$HOME/.local/state/bigteam}"
[ -d "$root" ] || skip "no $root"
held=0; ev=""
for inbox in "$root"/*/jobs/*.inbox.md; do
  [ -f "$inbox" ] || continue
  rep="${inbox%.inbox.md}.replies.md"
  for n in $(ggrep -o '^## MSG [0-9]*' "$inbox" | awk '{print $3}'); do
    ggrep -q "^REPLY $n:" "$rep" 2>/dev/null || { held=$((held+1)); ev="$ev $inbox#$n"; }
  done
done
printf '{"tool":"bigteam-inboxes","held":%s,"evidence":"%s"}\n' "$held" "$ev"
[ "$held" = 0 ]
