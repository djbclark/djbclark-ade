# Authenticated fork qualification evidence

`bin/ade_fork_ci.py` is the GitHub read/retention adapter for the release core.
It installs nothing, runs no candidate code, and grants no merge, publication,
channel or runtime activation permission. It does not provision an App token.
Existing `gh` authentication supplies the API credential without exposing it.

`Evaluation` holds expectations from protected enrollment: evaluator repository
slug and numeric ID, workflow ID/path and exact reviewed commit, run/attempt,
triggering actor, event, required job names, exact artifact ID/name/ZIP digest
and exact qualification receipt digest. Candidate-provided JSON is not a source
of these expectations. A real evaluator must use protected tests/recipes and a
credential-free candidate build. New reviewed evaluator revisions require new
trusted expectations; this is provenance, not an indefinite software freeze.

`validate_metadata` only checks consistency of mappings; it does **not**
authenticate caller-supplied mappings. `GitHubEvaluation.verify` reads run,
attempt-specific paginated jobs and artifact metadata from GitHub, requires all
expected jobs completed/success at the exact SHA and attempt, rejects expired
or mismatched artifacts, downloads the ZIP and verifies SHA256 itself. The
artifact name ends in `-RUN_ID-ATTEMPT` so rerun artifacts cannot silently stand
in for another attempt. Expected names must come from the trusted evaluator's
own upload step, not a candidate build's chosen filename.

Run/artifact metadata is rechecked after downloading. The bounded archive is
published content-addressed with atomic no-overwrite linking and fsync; retries
retain existing matching archives and refuse corruption rather than overwrite
it. Archive expiry in GitHub does not delete locally retained recovery bytes.
ZIPs are never extracted or executed by this module. Admission and storage quotas
for the protected archive directory remain the operator's responsibility.

The returned `VerifiedArtifact.authenticates(receipt)` can implement the release
core's evidence-authentication callback for that exact protected receipt identity.
It does not replace `validate`'s source/dependency/feature/payload checks, current
policy and permission checks, group reservation, or runtime verification. A caller
must read the payload from the retained archive safely and independently verify
its digest before staging; the ZIP transport digest is not the payload digest.

The adapter returns no success on failed CLI requests, pending/skipped checks,
missing/duplicate jobs, reruns, wrong repositories/workflows/actors or digest
mismatches. Errors are `ContractError` with bounded stable messages; raw CLI
output and credentials are never included. Trusted test runners are injectable
for CI only; no candidate-controlled subprocess or shell command is accepted.

Primary references: [workflow runs API](https://docs.github.com/en/rest/actions/workflow-runs),
[workflow jobs API](https://docs.github.com/en/rest/actions/workflow-jobs),
[artifacts API](https://docs.github.com/en/rest/actions/artifacts).
