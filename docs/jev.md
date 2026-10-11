# Jev: measure decisions before acting

`bin/jev` is a Python 3, standard-library-only client for TypeSafe's Jev.
It tests the typed-decision rung of [orchestration practices](orchestration-practices.md):
log answers next to existing decisions, review disagreements, then decide
whether a site merits promotion. It does not route agents or change models.

## Switch and credentials

`bin/jev mode` reads `JEV_MODE` when set, otherwise the first word of
`~/.config/jev/mode`, otherwise `off`. Invalid values fail closed to `off`.
`bin/jev mode shadow` atomically replaces that file; `off` and `act` work too.
An environment override still wins after writing the file. Installation does
not create the file or edit Claude settings. Off decisions exit 3 before
reading stdin, unlocking secrets, importing the HTTP client, or logging.

The credential is `TYPESAFE_API_KEY`. When absent, Jev re-executes itself via
`sudo-secretspec run --reason "jev decision" -- <jev> <args>` with
`JEV_REEXEC=1`. A supervising process bounds the unlock and child execution,
passes state on stdin, and appends the child's record once. It never uses
`get` or `export`, nor puts the key in argv. Errors contain class names only.
Do not enable the sites until this boundary works noninteractively within
their deadlines. For inspection, use `file` on a resolved executable before
opening it as text: `sudo-secretspec` may be a compiled binary.

## API contract (verified 2026-10-11)

The [documentation index](https://docs.typesafe.ai/llms.txt) points to
[Choice](https://docs.typesafe.ai/primitives/choice). Send a bearer-authenticated
POST to `https://api.typesafe.ai/v1/systemone`:

```json
{"state":"The deploy failed twice.","model":"jev-latest","questions":{"decision":{"type":"choice","instructions":"Is this urgent?","criteria":{"urgent":"urgent","not_urgent":"not_urgent"}}}}
```

The option-list field is **`criteria`**, a map from option names to descriptions;
the question text is **`instructions`**. Plain CLI options use their own names
as descriptions; prompt-effort supplies the descriptions below. Answers are
under `answers.decision`; usage includes `input_tokens` and `output_tokens`.
`confidence` is distribution-derived and is not the selected probability.
This tool's `prob` is `probabilities[choice]`, and `confident` compares that
probability against `--threshold` (default 0.8).

## Commands and records

```sh
JEV_MODE=shadow bin/jev decide --site smoke --state 'The deploy failed twice and customers see 500s.' --question 'Is this urgent?' --option urgent --option not_urgent --incumbent urgent
bin/jev report --site smoke
bin/jev report --since 7d --json
bin/jev disagreements --site dispatch-verdict --limit 20
bin/jev label UUID done
```

`decide` accepts `--state`, `--state-file`, or stdin, repeated `--meta k=v`,
and `--timeout` (default 5 seconds). Exit 0 means an answer, 2 means an error,
3 means off. A POSIX wall timer covers stdin, HTTP/DNS and credential lookup;
socket timeouts alone would not bound a trickling response. Scheduling and
local log/cleanup overhead can add a small amount to the deadline.

Answers and errors append one JSON line with a single `O_APPEND` write to
`~/.local/state/jev/decisions.jsonl`. Newly created directory/file permissions
are 0700/0600. Records retain a UUID, UTC timestamp, options and probabilities,
threshold, incumbent/agreement, latency, usage/cost, metadata, state length,
SHA-256, and the first 1500 characters. These excerpts can contain private
task text: keep this state directory out of git. The API key is redacted.
Label lines append `label_for` and `truth`; the latest label for an id wins.
An absent incumbent means `agree: null`, not disagreement.

`report` groups by site and excludes smoke unless explicitly selected. It
reports calls/errors, interpolated p50/p95 latency across all calls, input
tokens, cost and cost per call, paired-call agreement, incumbent × Jev
confusion counts, confident disagreements, and labelled accuracy. Errors do
not enter agreement or accuracy denominators. Labels apply regardless of
when they were added; `--since` filters decisions. Default window: seven days.
Default output is indented JSON; `--json` emits compact JSON.

Cost uses numeric API `usage.cost` (USD) when supplied, else the brief's
assumption of $0.042/million input tokens with free output. Unreported usage
on failed calls is treated as zero; the report prints this limitation.

Prompt-effort also reports an **upper bound**, counting confident mechanical
answers on Opus/Fable. It multiplies the count by `--tokens-per-turn` (default
4000) and `--price-difference` (default $10/million tokens, blended). These are
illustrative assumptions, not current model price quotes or measured savings.
The report prints both flags' values and limitations beside the estimate.
It ignores caching, subscriptions, retries and quality loss. Disagreements
are sorted by descending selected probability and include the excerpt and id
for review and labelling.

## Sites

### dispatch-verdict

`acp-dispatch.finalize()` calls the isolated `jev_shadow(rec)` function after
writing the final job record and touching `.done`. With a non-off mode it
launches `jev decide` in a new session with all output discarded and stdin
from a temporary anonymous file. It does not wait, modify a report/record,
or change dispatch's exit code. Launch errors are swallowed. This site stays
shadow even when the global mode is act.

State contains the last stderr summary line and final 4000 report characters,
falling back to the final message when the report is absent. Options are
`done`, `partial`, `blocked`, `refused`, `provider_error`, `no_report`.
Incumbents map `no-report` to `no_report`, a refusal failure to `refused`,
other recorded failures to `provider_error`, and DONE with a nonzero agent
exit to `partial`. Metadata carries agent, model, task and name. A removed
Jev executable is harmless to dispatch. Future edits to live `acp-dispatch`
must use a temporary candidate and an atomic rename.

### prompt-effort

`claude/hooks/jev_effort_hook.py` reads Claude's JSON stdin. It skips short
prompts (<20 characters), slash commands, standalone tool-result JSON/XML,
and standalone task notifications, including pasted-content wrappers.
Unmarked plain text cannot reliably be distinguished from a pasted tool
result, so it is treated as a prompt. Only the last 64 KiB of the transcript
is inspected for the most recent assistant's `message.model` (or top-level
`model`); missing entries produce `unknown`. Metadata includes model/session.
The first 4000 prompt characters become state. Options are:

1. `mechanical`: apply an already-made decision (edits, commits, docs, known commands).
2. `normal`: ordinary implementation with a clear shape.
3. `hard`: unclear shape, architecture, adjudication, or debugging already tried once.

Shadow emits nothing. Act emits a single `systemMessage` only for confident
mechanical decisions on Opus/Fable, suggesting `/model sonnet`. This field
is user-visible according to the [Claude hooks contract](https://code.claude.com/docs/en/hooks#json-output),
whereas `additionalContext` is model context. The hook never switches a model.
It has a 3-second total budget, always exits 0, and sends prompt text only
through stdin to Jev, which retains the documented log excerpt.

After review, the orchestrator may merge this entry into existing settings
(do not replace the settings object, and do not use `async: true`, which
changes the message's recipient):

```json
{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"/Users/djbclark/src/djbclark-ade/claude/hooks/jev_effort_hook.py","timeout":3}]}]}}
```

## Promotion rule

Collect at least 200 successful calls per site over at least seven days.
Review every above-threshold disagreement, label at least 50 diverse cases
(including all observed high-risk mistakes), and require at least 95%
labelled accuracy. Dispatch additionally needs at least 95% incumbent
agreement; effort has no incumbent, so agreement cannot qualify it. Require
error rate below 1%, p95 below the site's deadline, mean cost below $0.0001
per call, and no labelled hard task wrongly marked confidently mechanical.
These are proposed acceptance bars, not evidence that promotion is safe.
Only the operator promotes after reviewing the evidence. Global act currently
enables the effort hint only; an acting dispatch policy requires a separate
reviewed code change. Turning off immediately stops new observations.

## Removal

1. Set mode off and remove only this hook's `UserPromptSubmit` settings entry.
2. Delete `bin/jev`, `claude/hooks/jev_effort_hook.py`, `tests/test_jev.py`, and `docs/jev.md`.
3. Remove `jev_shadow()` and its one call from `bin/acp-dispatch`, using an atomic replacement; do not delete dispatch itself.
4. Archive or delete `~/.local/state/jev/` and remove `~/.config/jev/mode` (and its empty directory).
5. Unset `JEV_MODE` and any test-only `JEV_REEXEC`/`JEV_RETURN_RECORD` variables.

No dependency, daemon, git hook or secret-store change is installed. The
separately managed API credential can remain for other callers.

## Offline verification

```sh
JEV_MODE=off /Users/djbclark/ops/site-private/bin/bg python3 -m pytest -q tests/test_jev.py tests/test_acp_dispatch.py
```

The explicit off override isolates the existing dispatch tests from a live
mode file; new integration tests enable shadow/act only with mocked calls.
