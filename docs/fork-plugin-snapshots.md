# ADE plugin snapshot recipe v1

This offline library stages source; it never installs, loads, enables, rewrites
configuration, moves plugin registrations, grants authority or executes candidate
build commands. Master remains the channel. Each release uses the exact currently
qualified master commit; a snapshot is retention, not a permanent version freeze.
The first controlled pilot is ade-yolo; ade-window-name and ade-claim follow only
with their own complete qualification evidence.

## Source and storage

`produce(repo, master_commit)` accepts a full immutable commit identity. Trusted
integration must establish that identity is currently eligible master independently;
this API deliberately does not interpret a mutable branch name as eligibility.
It reads `ls-tree` and `cat-file` object bytes with replace refs and lazy fetching disabled. Reads use a selector deadline and byte cap; timeout/overflow kills and reaps only the exact child. Dirty
and untracked files, Git archive export substitutions and candidate build commands
are never used. The canonical bounded JSON payload includes commit/tree identities
and every tracked path's source mode/object, materialized target/object, sealed
mode, SHA256 and base64 content. Limits are 20,000 files and 64 MiB payload.
Non-ASCII/control paths, traversal, duplicates, overlapping paths, gitlinks and
special modes fail. Transport ZIP extraction belongs outside this adapter; feed
only an independently authenticated exact payload, never arbitrary archive paths.

The protected recipe preserves the whole tracked ADE graph, including parent
helpers, config dependencies and Git hooks. Only CLAUDE.md → AGENTS.md and
libexec/agent-bin/git → bin/ade-git-guard may be materialized, and only when exact
Git link bytes resolve to those tracked regular targets. No output symlinks exist.
The recipe cannot be supplied by candidate metadata. Adding a new source symlink
requires protected recipe review. `plugins/ID` paths preserve existing relative
helper discovery. This alone does not prove environment overrides select them.

`payload_tree_hash` predicts sealed tree bytes; `stage` checks that prediction,
writes only after complete validation, fdatasyncs/fsyncs regular files, seals files
0444/0555 and directories 0555, syncs directories bottom-up and publishes using
native atomic no-replace rename (Linux renameat2 or Darwin renamex_np). Existing
identities are rehashed, never overwritten. The destination name is payload SHA256;
no manifest is added inside the hashed source root. Failed private staging remains
inspectable. Admission quotas, cleanup and administrator-enforced immutability are
integration responsibilities; read-only modes are not a same-user security sandbox.
The private owned store must not be manipulated concurrently outside this adapter.

Native hash compatibility was inspected in Paseo activation-policy.ts:45–63 at
0da09a63a505198b08cef6af1aa3a6dcd34ef0af: sorted depth-first JSONL directory records,
file records with relative path/mode/size, raw file bytes and newline. ASCII-only
paths make Python ordering/encoding identical to Node here. Helpers belong in the
snapshotRoot; sourcePath points at its plugins/ID child. A different native hash
algorithm requires reviewed integration changes and fresh evidence. Native stable
traversal/race repairs remain the Paseo worker's responsibility.

## Qualification boundary

`qualify` reuses release-core receipt validation and separately supplied
`VerifiedArtifact.authenticates`. It grants no merge, publication, channel,
activation or recovery authority. The protected expected receipt toolchain is a canonical JSON **string** encoding
`{"plugin_snapshot_evidence":"<sha256(canonical(trusted_evidence))>"}`.
This preserves the release core string schema while binding structured evidence.
The protected evaluator evidence must bind Python, Git, Node and Paseo compiler
identities, helper bindings, cold compatibility, native tree SHA256, exact compiled
server bundle SHA256 and master commit. Candidate evidence must exactly match;
missing helper paths or missing/mismatched evidence returns HOLD. Receipts bind
actual payload bytes and predicted actual sealed tree hash. The controller must
retain authenticated payload and reverify the actual staged tree before use.

Protected evaluator ownership is essential: nonempty evidence values are not
self-authenticating proof of closure. Integration must define complete toolchain
identity schemas and helper/environment binding assertions outside candidate
control. The source graph preserves claim's ade_claims.py, ade-git-guard, agent-bin
Git shim and Git hooks, and window-name's ade_ws_autoname.py + ade_ws_names.py.
Transitive external tools and compiler/runtime modules are not proven by a source
or server bundle hash. Cold daemon/compiler compatibility, native rehash parity,
helper override rejection and independently authenticated evaluator provenance are
required before any production QUALIFIED call. The CI workflow here provides
source/retention and cold Node library behavior coverage, not that live evidence.

## CI and remaining gates

The Linux workflow builds temporary fixture repositories only in CI and runs
plugin behavior libraries against the sealed entire tracked graph. It does not
start Paseo or compile/install plugins. No local tests/builds/npm installs were
run for this slice. Adversary review, CI results, protected master selection,
complete external dependency evidence, native lifecycle fixes, controller
reservation/enrollment and separately authorized cutover remain integration gates.
See fork-release-contract.md and fork-ci-evidence.md for the authentication and
authorization separation; matching locally constructed receipts grant nothing.
