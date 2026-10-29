# Cargo builds through bg

Added 2026-10-28 after an OpenCode agent retried a refused release build as bare
`cargo build -p sudo-secretspec-cli --release` during sustained load. A release
does not waive admission, QoS or concurrency limits.

`bg-cargo-gate.js` uses OpenCode V2's native `permission.evaluate` hook to deny
direct Cargo compile/test commands, including release builds, aliases, toolchain
selection, common wrappers and quoted executable paths. Its denial tells the
agent to use the full `~/ops/site-private/bin/bg` path. If bg refuses or waits,
use the repository's CI route or resolve that refusal; never retry the build bare.
The plugin does not rewrite command text or turn native ask/deny rules into allows.
Help/version/metadata queries and already wrapped commands retain native rules.

This prevents common accidental bypasses, not arbitrary execution in scripts,
Python, command substitutions or another interpreter. It is not a sandbox.

Install the reviewed file atomically at
`~/.config/opencode/plugins/ade-bg-cargo-gate.js` (respect `OPENCODE_CONFIG_DIR`
when set). Preserve a different existing file for review. No config edit is
needed: OpenCode discovers immediate JS files in its global plugins directory.
Do not restart a busy server. Watched plugin changes reload automatically; check
native loader records and a fresh-location shell canary before claiming activation.
Rollback removes just this installed file and waits for native reload.

Contract: [OpenCode V2 permission hooks](https://opencode.ai/v2/docs/build/plugins/server#permissions-1).
Regression: `tests/test_bg_cargo_gate.py` exercises the original release command,
wrapped admission and preservation of native resources/effects without compiling.
