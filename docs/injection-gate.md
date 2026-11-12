# S5a injection gate (2026-11-12)

Operator OQ2 un-deferred S5a only on 2026-11-12. This PR ships the tool and
measurement harness. No reader adopts it; S5 apply and S6 canaries stay deferred.
The [2026-11-07 evaluation](security/injection-classifier-eval-2026-11-07.md)
is historical evidence, not measurement of this implementation. Its low recall
means a low score never establishes trust or authorizes an action.

## Contract

`bin/ade-injection-gate classify --surface pr < artifact.txt` emits one JSON
record. Supply `TYPESAFE_API_KEY` through `sudo-secretspec run --reason … --`
when making a live call. The fixed endpoint is TypeSafe `/v1/systemone`, model
`jev-latest`, one fixed Choice, raw artifact in state. No tools or generated
instructions run. The model alias can drift; results record the returned model.
The request/response contract was checked against the official
[System One API](https://docs.typesafe.ai/api/system-one.md) and
[Choice documentation](https://docs.typesafe.ai/primitives/choice.md) on 2026-11-12.

`decide` is injection at p >= 0.9, benign at p <= 0.1, otherwise escalate.
Every result retains `untrusted: true`, a content SHA-256, surface, probabilities,
latency and prompt version. The result omits artifact text. Callers retain the
original provenance (author, author_association, source URL, fetched time) beside
that digest; classification neither supplies nor upgrades provenance.
Exit 0 means a valid score, including uncertain scores; it is never approval.
Exit 3 means disabled/unavailable; malformed CLI/input returns 2. All errors
escalate. `--disabled` returns unverified with no request. `--max-ms` may lower
the five-second deadline. Empty or >96,000-byte text is unavailable: no silent
truncation. Bad, nonfinite, incomplete or reported-truncated responses escalate.
Network errors are suppressed rather than echoing content or keys. A subprocess
deadline bounds the whole network call; redirects and proxy inheritance are off.

Surfaces: pr, issue, comment, ci-log, dependabot and web receive tags only.
Jira additionally requests operator attention at p >= 0.9. Fleet-watch sets
`hold_dispatch` for p >= 0.9 or any unavailable/disabled result. Uncertain valid
scores retain the untrusted tag and do not independently hold dispatch, per S5a.
`operator_attention`, `shadow` and `hold_dispatch` are advisory fields; the tool
never posts, dispatches, writes a shadow log or releases a held notice. Peer
messages are excluded. There is no enabled config entry or installed service.

## Measurement before adoption

The harness consumes JSONL. Offline records contain `id`, `source`, `label`
(injection/benign), `surface`, `response` (the TypeSafe response envelope), and
`latency_ms`. `bin/ade-injection-gate measure --replay scores.jsonl` validates
probabilities and aggregates without network, keys or attack text. A replay
report is explicitly `offline-replay` and cannot be a classify verdict.

For a fresh live run, records replace response/latency with `text`:
`bin/ade-injection-gate measure --live --corpus private-corpus.jsonl`.
It sends each sample twice and emits scores plus aggregate recall/FP at 0.9,
escalation and unavailable counts, nearest-rank p90/median latency, per-source
and surface groups, returned model versions and paired decision stability.
Unavailable rows stay in the recall denominator. IDs/source must be short
alphanumeric/dot/dash/underscore identifiers; results never echo corpus text.
Synthetic score fixtures test plumbing only and are not classifier accuracy.
The harness reports `adoption_authorized: false` regardless of the metrics.
Completion exit 0 is not acceptance, especially if all requests are unavailable.

Use the evaluation's method: representative fresh own benign PR/issue/comment/
CI traffic plus authorized disclosed injection sets, with source/license/label
manifest, two runs, and per-surface reporting. Keep private corpora and result
artifacts outside Git. Fetch payloads only by deterministic scripts, never into
an agent context; do not recover the deleted historical payload/cache. The
historical container/no-network harness and credentialed allowlisted host proxy
remain the procedure for disclosed attack corpora; this CLI does not provision
that isolation or fetch corpora. Only classifier workers may see those payloads.
Use private output permissions and delete payload files after aggregation under
the original evaluation retention rules. No live attack corpus was run in this
PR. Report token usage/cost separately from provider accounting; the harness
makes no current price assumption.

Before any adoption: run and inspect that measurement, document misses/FP and
outages, then review the exact reader change. Refresh on fresh benign traffic
monthly and when the model/prompt changes. Each caller must define its durable
shadow log and unavailable behavior. Fleet-watch integration belongs in
site-public-djbclark and must prove that high scores and unavailable scores
queue operator notices without dispatch. S6 outage alerts/canaries, hardening
application, other readers and peer-message mediation are outside this PR.
