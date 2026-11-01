#!/usr/bin/env bash
# d1-04-archive-parent-child
# CONTRACT: D1.4/C1: archiving a parent whose child is running leaves the child running (so successors need not stay top-level)
# EXPECT:   the child is still running 20 s after the parent's archive, and finishes; repeat after 'paseo agent detach'
# ON-FAIL:  successors stay top-level permanently (plan D1.4, C1)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-04-archive-parent-child.sh
# NEEDS:    isolated daemon; one cheap provider
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-04-archive-parent-child
. "$here/lib/common.sh"
ON_FAIL=successors\ stay\ top-level\ permanently\ \(plan\ D1.4\,\ C1\)
isolated_up lineage; trap isolated_down EXIT
P=${PROBE_PROVIDER:-claude}
parent=$(pj run -q --no-wait --provider "$P" --mode bypass --title parent \
 "Using the create_agent MCP tool, start a child agent (provider $P) whose task is: run 'sleep 60' then reply CHILD-DONE. Then stop without waiting.") || fail "parent create failed"
pj wait --timeout 180 "$parent" >/dev/null 2>&1
child=$(pj ls --json | python3 -c "import json,sys; print(next((x['id'] for x in json.load(sys.stdin) if x['id']!='$parent'),''))")
[ -n "$child" ] || skip "parent did not create a child (MCP create_agent unavailable?)"
pl=$(pj agent inspect --json "$child" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ParentAgentId'))")
[ "$pl" = "$parent" ] || skip "child lineage not set (ParentAgentId=$pl)"
pj archive "$parent" >/dev/null 2>&1; sleep 20
st=$(pj ls --json | python3 -c "import json,sys; print(next((x['status'] for x in json.load(sys.stdin) if x['id']=='$child'),'gone'))")
pj wait --timeout 120 "$child" >/dev/null 2>&1
done_=$(pj logs "$child" 2>/dev/null | grep -c CHILD-DONE)
ev="{\"childStatusAfter20s\":\"$st\",\"childFinished\":$done_}"
[ "$st" = running ] && [ "$done_" -ge 1 ] && pass "$ev"
fail "child did not survive its parent's archive" "$ev"
