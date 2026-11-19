# Coupled fixture checks

These files are infrastructure and components for disposable Linux CI. Passing
their source tests or authenticating a build archive does not qualify a runtime.
The complete `native-acceptance.mjs` and protected `evaluator-recipe.json` remain
required before the evaluator can emit a qualified artifact.

## A. Automatic checks

Push and pull-request jobs run the source/business/transport tests and inspect
the exact completed producer build selected by `native-build-input.json`.
Inspection authenticates run, attempt, actor, source, archive and payload bytes.
It executes no member of the acquired distribution.

`qualification: false` is deliberate. A successful automatic run is not evidence
that a namespace, daemon, model, full cohort or promotion transaction ran.

## B. Explicit namespace attempt

The workflow's typed `namespace_probe` input defaults to false. Root may dispatch
it true only after exact fixture/helper source review, a completed green producer
build, independent archive inspection and matching protected helper pins:

```sh
gh workflow run fork-coupled.yml --ref fork-maintenance-coupled -F namespace_probe=true
```

This runs `registration-smoke.mjs` in a disposable Ubuntu account. The current
scenario requires all fourteen ordinary builtin registrations and refuses
maintenance when profiles are missing. It is a negative fixture, not complete
runtime qualification. An unrequested or skipped attempt is outstanding proof,
never a passing assertion.

The privileged wrapper must use the exact helper identified by
`namespace-bootstrap-input.json`. A controller's closed set of reviewed read-only
helper identities does not authorize a privileged wrapper to choose either one.
Changed helper bytes require their own review and a matching measured archive.

On uncertain settlement, preserve backing and policies. Do not turn a timeout,
failed probe, PID disappearance or transport close into proof that work ended.
Never run this fixture against the operator's live daemon or on the Mac.

## C. Component limits

`native-roundtrip.mjs` requires an already provisioned, genuinely qualified daemon
and the complete protected cohort. It performs no enrollment or automatic repair.
`native-agent-metadata.mjs` uses the actual retained public client and same-channel
authority observations; its results do not prove catalogue initialization,
provider helpers, resume, claims or full-cohort quiescence. A ready catalogue may
contain fallback data after discovery fails.

The read-only sudo diagnostic remains available as separately reviewed historical
source. Its automatic invocation was removed after the actual topology was
recorded. It pins its reviewed helper bytes and supplies identity observations,
not namespace or execution authority. Do not change its imported helper or repeat
a privileged diagnostic without the corresponding source review and a concrete
diagnostic need.
