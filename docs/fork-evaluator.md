# Protected evaluator-output producer

`bin/ade-fork-evaluate --source-sha FULL_SHA` is a producer, never consent or
a GitHub authentication seal. It accepts no measurement JSON, path, runner,
shell command, qualification flag, evaluator SHA or native override from a
candidate. Missing genuine evidence returns HOLD (exit 78), with no qualified
output. This source installs no evaluator recipe, timer or service.

## Independent reviewed source and fixed recipe

The evaluator runs its own checkout at the workflow's exact reviewed GITHUB_SHA,
independent of sibling `candidate`. HEAD and clean status are checked before
and after assessment. Immutable snapshots reuse produce/inspect/tree hash/stage.
Candidate npm scripts and candidate evaluator modules are never run.

Root integration owns fixed tracked files
`tests/fixtures/fork-coupled/evaluator-recipe.json` and
`tests/fixtures/fork-coupled/native-acceptance.mjs`. Neither exists in this slice.
Recipe bytes must be canonical and identical to the reviewed Git blob. Only
`@evaluator` at evaluator_commit and bindings.evaluator resolves from independently
checked HEAD, avoiding a circular self-commit literal. No CLI selects a recipe.
The schema is exactly schema_version=1, evaluator_commit, bindings (release-core
schema), policy, evidence, native, cohort, assertions. Complete catalog
paseo-runtime cohort/dependencies and protected features are required.

Native exact keys: source_sha, distribution_sha256, node_sha256, compiler_sha256,
entry_sha256, sdk_sha256, activity_sha256, helpers (map of exact helper SHA256s).
All compiler/helper/tool identities are protected template fields. Python/Git
binaries actually used are rehashed. Source reads run in isolated Python with
sanitized environment. The sealed distribution slot is sibling `qualified-native`:
runtime/node, role.cjs, compiler-code.mjs, with external
qualified-native.manifest.json. These bytes are checked before launch and after assessment; sealed candidate
source and Python/Git identities are also rechecked after the measurement wait.
Retained-root provisioning remains root integration work.

## Exact owned measurement handoff

The fixed reviewed harness runs under retained Node, fixed argv and an owned
private work directory. Its request binds launch_id, evaluator/source commits,
sealed source_root/native_root, native/cohort identities and assertion names.
Child environment excludes GitHub/Actions/cloud credentials, source loaders
and candidate overrides. This is an environment boundary, not OS confinement
for hostile code. Genuine enclosing daemon/activity/helper capabilities remain
required. The fixture must use the actual owned compiler worker, never a direct
arbitrary compiler or synthetic private brand.

`finish` is a trusted in-process consistency gate, not JSON authentication.
Protected orchestration must own the exact independently launched qualified
runtime. CLI handoff comes only from its fixed checked child after exit 0 and
an evaluator-source recheck. The root-owned harness supplies stdout with exactly:

1. schema_version=1, launch_id, evaluator_commit, source_commit.
2. native: exact protected distribution/source/tool/namespace identities.
3. compiler: source_sha, entry_sha256, server_bundle_sha256, cold_invocations=2,
   cold_bundle_sha256 (two equal output digests),
   two distinct worker_incarnations and two positive distinct worker_thread_ids.
   These must be actual owned worker observations, with identical output from
   both cold compiles. Fixed compiled-server-1.cjs and compiled-server-2.cjs bytes are independently rehashed.
4. runtime: distribution_sha256, node_sha256, entry_sha256, sdk_sha256,
   activity_sha256, positive pid, start_token, incarnation, from the actual
   enclosing execution owner. No phantom role aliases or PID-only proof.
5. helpers: exact protected helper identities; cohort: every protected expected
   catalog identity/enabled-state record, including unloaded members.

The harness writes compiler.xml, runtime.xml, helpers.xml, cohort.xml,
features.xml in its owned work root. assertions maps those domains to exact
nonempty unique testcase names; features names equal the protected feature set.
Suite counts must match actual leaves, with zero failure/error/skipped/disabled;
missing/extra/duplicate cases and partial counts reject. Group-only testsuites
wrappers may omit all counts; concrete suites cannot. DTD/entities and oversized
reports reject. No summary-only passed shortcut exists. Real hooks, state/cohort
preservation, helpers, namespace ownership and compiler assertions remain root's
genuine coupled fixture responsibility. Synthetic fixtures never authenticate.

## Exact output and downstream authentication

Only after all gates are receipt.json, snapshot.json, evaluator-evidence.json
created. ZIPs are deterministic, regular-only and bounded to 96 MiB compressed
and expanded. make_receipt/validate bind payload and protected feature results.
Artifact name: `ade-yolo-qualified-SOURCE_SHA-RUN_ID-ATTEMPT`. The workflow
uploads the three members, never a ZIP wrapped inside the artifact ZIP.

Evidence retains exactly python, git, node, paseo_compiler, helper_bindings,
cold_compatibility, native_tree_sha256, server_bundle_sha256, master_commit.
Only source/tree/compiled digest vary per the consumer contract. Toolchain is
canonical JSON string `{"plugin_snapshot_evidence":SHA256(canonical(evidence))}`.
All other identities/dependencies/policy/features remain protected recipe data.
GitHubEvaluation authenticates a separate COMPLETED run later. The producer
never authenticates its own running workflow or constructs a verification seal.

## CI and remaining integration

Linux workflow has cancel-in-progress=false, contents:read, nonpersistent checkout
credentials, no schedule, no deployment and no Mac work. Unit artifact name
`evaluator-unit-evidence` contains JUnit only and cannot match qualification
discovery. Positive runtime/compiler/cohort fixture observations are explicitly
synthetic; real Git snapshot, ZIP, actual Node JUnit, corruption/count checks and
subprocess bounds execute in CI. Missing genuine protected recipe, native
distribution or root coupled fixture causes HOLD and no qualified artifact.
No production archive, real runtime, helper/cohort qualification or promotion
acceptance is claimed by unit success.
