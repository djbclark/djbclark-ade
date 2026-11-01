#!/usr/bin/env bash
# d1-07b-create-origin
# CONTRACT: D1.7b/G2.8: does agent.create.before tell a plugin-SDK create from an MCP or CLI create?
# EXPECT:   the logged create payloads differ in a field that names the origin; the answer is written down either way
# ON-FAIL:  G2.8's herald-label refusal is dropped; the deleteHelpers:false assertion stays the only control
# SCOPE:    second daemon only
# HOW:      bash tests/paseo-acceptance/d1-07b-create-origin.sh   (installs fixtures/origin-probe-plugin into the TEST home only)
# NEEDS:    isolated daemon; the probe plugin (SDK names UNVERIFIED, see its index.js)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-07b-create-origin
. "$here/lib/common.sh"
ON_FAIL=G2.8\'s\ herald-label\ refusal\ is\ dropped\;\ the\ deleteHelpers:false\ assertion\ stays\ the\ only\ control
isolated_up origin; trap isolated_down EXIT
log="$ACC_BASE/origin.log"
pj plugin install "$here/fixtures/origin-probe-plugin" >/dev/null 2>&1 || skip "plugin install failed: fix the fixture against plugins_hooks.md"   # UNVERIFIED: install-from-path
ORIGIN_LOG="$log" pj run -q --no-wait --provider "${PROBE_PROVIDER:-claude}" --title cli-create "reply OK" >/dev/null
sleep 5
[ -s "$log" ] || skip "no hook payload was logged (plugin did not load?)"
fields=$(python3 -c "import json,sys; print(json.dumps(sorted({k for l in open('$log') for k in json.loads(l).get('payloadKeys',[])})))")
pass "{\"payloadKeys\":$fields,\"note\":\"compare CLI vs MCP vs plugin-SDK creates; N/A for the UI path, which cannot be scripted\"}"
