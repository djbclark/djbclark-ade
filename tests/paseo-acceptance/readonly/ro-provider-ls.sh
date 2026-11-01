#!/usr/bin/env bash
# ro-provider-ls: Which providers are available on this daemon (C2's table)?
# CONTRACT: C2: provider availability decides which agents acp-run can be replaced for
# EXPECT:   rc 0; the table is saved for the T4 steer matrix; the set differs from C2 only by a dated note
# ON-FAIL:  C2 is stale: refresh it before D1.1 picks its providers
# SCOPE:    READ-ONLY live (safe against the live daemon; sends nothing, creates nothing, restarts nothing)
# HOW:      bash tests/paseo-acceptance/readonly/ro-provider-ls.sh   (set ADE_ACCEPTANCE_RESULTS to keep results out of ~/.local/state)
# NEEDS:    paseo on PATH, python3
# STATUS:   DRAFT
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=ro-provider-ls
. "$here/../lib/common.sh"
ON_FAIL="C2 is stale: refresh it before D1.1 picks its providers"
out=$(timeout 30 paseo provider ls 2>&1) || fail "provider ls failed"
n=$(printf "%s\n" "$out" | awk "tolower(\$0) ~ /available/ {c++} END{print c+0}")
pass "{\"availableLines\":$n}"
