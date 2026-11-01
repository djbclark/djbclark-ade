#!/usr/bin/env bash
# d1-03b-teardown-failure
# CONTRACT: D1.3/B4.2: with the push refused, the local rescue still exists; record whether a failing teardown stops Paseo removing the worktree
# EXPECT:   local rescue present; teardown exit non-zero or zero recorded; worktree removed or kept recorded
# ON-FAIL:  if the local rescue is missing: no slice moves into Paseo workspaces
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-03b-teardown-failure.sh
# NEEDS:    same as d1-03 plus a remote that rejects pushes (pre-receive hook exit 1)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-03b-teardown-failure
. "$here/lib/common.sh"
ON_FAIL=if\ the\ local\ rescue\ is\ missing:\ no\ slice\ moves\ into\ Paseo\ workspaces
RESCUE=${ADE_RESCUE_BIN:-$here/../../bin/ade-rescue-worktree}
[ -x "$RESCUE" ] || skip "bin/ade-rescue-worktree does not exist yet (T6)"
skip "UNIMPLEMENTED: copy d1-03-archive-rescue.sh and install a rejecting pre-receive hook in \$remote; record 'worktreeRemovedAfterFailedTeardown' and the teardown exit code from daemon.out"
