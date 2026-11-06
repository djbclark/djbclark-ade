#!/usr/bin/env bash
# d1-03b-teardown-failure
# CONTRACT: D1.3/B4.2: with the private remote refusing the push, the local rescue still exists (exit 0, pushed:false); record whether a failing teardown stops Paseo removing the worktree
# EXPECT:   rescue exit 0 with pushed false, local rescue complete and verified before any removal, no rescue ref on the remote; the teardown then exits 3 on purpose and the probe records worktreeRemoved
# ON-FAIL:  if the local rescue is missing: no slice moves into Paseo workspaces
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-03b-teardown-failure.sh   (runs d1-03-archive-rescue.sh with D1_03_REFUSE=1)
# NEEDS:    same as d1-03; the refusing remote is a second local bare repo with a pre-receive hook that exits 1
# STATUS:   run 2026-11-02 (see docs/d1-implementation-plan.md T6)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export D1_03_REFUSE=1 ACC_PROBE=d1-03b-teardown-failure
export ON_FAIL='if the local rescue is missing: no slice moves into Paseo workspaces'
exec bash "$here/d1-03-archive-rescue.sh" "$@"
