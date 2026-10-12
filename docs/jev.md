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
bin/jev disagreements --site prompt-effort --limit 20
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

### dispatch-verdict (retired 2026-10-11)

`acp-dispatch` used to launch a detached shadow `jev decide` after each slice,
asking whether it was done, partial, blocked, refused, a provider error or had
no report. The offline evaluation below scored it 74.7%, equal to always
answering `done`, while `classify()` already gives the exact answer for free.
djbclark retired it the same day: `jev_shadow()` is gone from `bin/acp-dispatch`
and `tests/test_jev.py` checks `finalize()` launches nothing. Earlier rows stay
in `decisions.jsonl`. A dispatch site only returns for a question the rule
cannot answer, such as whether a report did what its brief asked.

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

## Dual review: Jev vs GLiDE (started 2026-10-11, ends by 2026-10-23)

The Jev-only review (live since 2026-10-11, due 2026-10-18) was **closed 2026-10-11**; its results
are in the closing report below. A new review compares Jev with Fastino's GLiDE
(`POST https://api.fastino.ai/v1/systemone`, model `fastino/glide`, `X-API-Key`, key
`FASTINO_API_KEY` in sudo-secretspec) **on the same state, options and option descriptions,
concurrently, one call each**, and lasts at most **12 days**.

```sh
bin/jev review status                    # id, ends, active, backends
bin/jev review start --days 12 --id dual-1   # --days above 12 is refused; one review at a time
bin/jev review stop                      # writes a stop marker, removes ~/.config/jev/review.json
echo jev,glide > ~/.config/jev/backends  # or JEV_BACKENDS=jev,glide; absent = jev only
bin/jev report --review dual-1 --json    # per-backend sites plus a "pairs" section
bin/jev disagreements --site agent-choice --between
bin/jev label PAIR_ID truth              # a label on a pair id scores both backends
```

1. **Window.** `review start` writes `~/.config/jev/review.json`; when `ends_epoch` passes,
   `mode()` returns `off`, so every `decide` exits 3 by itself. Each row carries the review id.
2. **Rows.** One row per backend per call, sharing a `pair` id, with `backend` (`jev` | `glide`).
   `latency_ms` is that backend's own call time (the unlock is excluded when there are two
   backends); `total_ms` is the whole call. Old rows have neither field and count as `jev`.
3. **Report.** Jev keeps its old site key; GLiDE's rows appear as `<site>@glide`. `pairs.<site>`
   gives Jev-vs-GLiDE agreement and confusion, confident disagreements (both at the threshold),
   matches with the incumbent, and, for labelled pairs, who was right alone. GLiDE reports no
   cost, so its `cost_usd` is `null` rather than a guess; compare tokens and latency.
4. **Sites.** `prompt-effort` (the hook; no incumbent) and **`agent-choice`** (new): `bin/route_agent.py
   route --kind K --brief FILE` and `plan --kinds a,b --brief FA --brief FB` ask both deciders which of
   the six kinds the brief is, beside the kind the caller chose (the incumbent), detached, never
   changing the route. Without `--brief` nothing is asked. Options and their descriptions are the same
   for both backends (`KINDS` and `EFFORT` in `bin/jev`).
5. **Not a migration.** Jev stays the primary backend: the hook's act output and the exit code follow
   it. Nothing acts on GLiDE.
6. **Questions this review answers.** (a) Do they agree, and where not, who is right on labelled
   pairs? (b) Is GLiDE's probability better calibrated (the offline prompt-effort run found Jev's
   was not)? (c) Latency against the hook's 2.7 s budget and `route_agent`'s 5 s. (d) Cost, once
   GLiDE's pricing is known. The promotion rule below applies to each backend separately.

### GLiDE first probes (2026-10-11, before the review; hand-made cases, not accuracy evidence)

Five live calls with `fastino/glide` through `sudo-secretspec run`: a persona-rule yes/no on three
hand-written replies (caved to "trust me": 0.998; held position: 0.005; updated on real evidence:
0.025, all correct), a 3-level sycophancy score (2, 0, and a coin flip between 0 and 1 for the
evidence update, confidence 0.004), and a 3-way route (live research to the research option, 0.995).
Latency 0.3-0.6 s. **Docs mismatches seen:** the response `model` was `glide_v2`, where Fastino's
skill says `glide`; an empty `state` was accepted. Early dual-1 rows show GLiDE's probabilities
sitting near 0.5 on prompt-effort where Jev's are more spread; judge that only after the window.

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
3. Delete `bin/jev-eval` and `tests/test_jev_eval.py` (`acp-dispatch` no longer calls Jev: removed 2026-10-11).
3a. Dual review: `bin/jev review stop`, then delete `~/.config/jev/backends` and `~/.config/jev/review.json`, the `com.djbclark.jev-remind-2026-10-23` launchd job, and (if unwanted) the `FASTINO_API_KEY` declaration (`sudo-secretspec delete` then `undeclare`).
4. Archive or delete `~/.local/state/jev/` and remove `~/.config/jev/mode` (and its empty directory).
5. Unset `JEV_MODE` and any test-only `JEV_REEXEC`/`JEV_RETURN_RECORD` variables.

No dependency, daemon, git hook or secret-store change is installed. The
separately managed API credential can remain for other callers.

## Offline verification

```sh
JEV_MODE=off /Users/djbclark/ops/site-private/bin/bg uv run --with pytest python -m pytest -q tests/test_jev.py tests/test_acp_dispatch.py tests/test_route_agent.py
```

The explicit off override isolates the existing dispatch tests from a live
mode file; new integration tests enable shadow/act only with mocked calls.

## Offline evaluation (2026-10-11)

`bin/jev-eval` replays history through `bin/jev decide` (a subprocess, `JEV_MODE=shadow`,
`--site eval-<dataset>`, so every call is in `decisions.jsonl` like a live one) and through a
Haiku baseline, then scores both. `bin/jev-eval {build,show,run,score}`; tests in
`tests/test_jev_eval.py` (mocked deciders, no network). Data and raw per-row results stay
outside the repo in `~/.local/state/jev/eval/` (`<dataset>.jsonl`, `<dataset>.{jev,haiku}.results.jsonl`,
`score.json`); the rows contain excerpts of private task text.

### Method

1. **Jev:** same call shape as the live sites (6, 6 and 3 options; threshold 0.8; `--timeout 30` so
   a slow call is measured, not cut, and p95 is compared with the live deadline afterwards).
   `bin/jev` attaches option descriptions only for the site named `prompt-effort`, so for the
   `eval-*` sites the definitions of the effort and kind options travel in the question text,
   identically for both deciders. This differs from the live site, which sends the descriptions
   as `criteria` values.
2. **Haiku:** `claude -p --model haiku --effort low --tools "" --setting-sources "" --strict-mcp-config
   --disable-slash-commands --no-session-persistence`, run in an empty cwd, a one-line system
   prompt, the option list closed, no temperature set. The reply, trimmed of whitespace, must be exactly
   one option name; anything else (including `Normal.`) is wrong. No reply was off-list in this run.
   (`--bare` cannot be used: it refuses OAuth.)
3. **Parallelism** 4 calls at once; Jev cost is the log's `usage.cost` (or the $0.042/M input
   assumption), Haiku cost is `total_cost_usd` from `--output-format json`.
4. Jev latency is the logged `latency_ms`; it includes the `sudo-secretspec` unlock because the
   key is not in the environment. Haiku latency is the wall time of `claude -p` (CLI start included).

### Datasets and where the truth comes from

| Dataset | Rows | Truth taken from records | Truth labelled by the reviewing agent | Majority baseline |
|---|---|---|---|---|
| dispatch-verdict | 99 | 99 (job-record `status`, mapped as `jev_shadow` does) | 0 | 74.7% (`done`) |
| slice-kind | 72 | 4 (a `(kind: X)` in the brief's own title, masked from the state) | 68 | 54.2% (`code`) |
| prompt-effort | 100 | 0 | 100 | 43.0% (`normal`) |

1. **The labels are a proxy, not ground truth.** The slice-kind and prompt-effort labels are one
   agent's reading of the brief or prompt against the definitions in `route_agent.py` and
   `claude/hooks/jev_effort_hook.py`. No operator reviewed them. Nothing in `batch.log`, `CLAIM` or
   the job records names a kind, so the hoped-for "kind from a record" source barely exists.
   Where the definitions are fuzzy (a short question; a doc edit that is also a design call) the
   label is a judgment call, and a simple question was labelled `mechanical`.
2. **dispatch-verdict truth is a text rule.** `classify()` in `bin/acp-dispatch` sets the status
   from the report's first line (`BLOCKED:`), last line (`NO-REPORT`, `DONE`) and the recorded
   failure note. So that dataset measures how well Jev re-derives a regex from the last 4000
   characters, not whether the work was good.
3. **Skew.** 74 of 99 outcomes are `done`; `refused` has no rows and `blocked` one. Slice-kind is
   39 code, 18 research, 11 judgment, 3 mechanical and 1 github, so the per-class rows for the
   rare kinds mean almost nothing. Prompt effort is 38 mechanical, 43 normal, 19 hard.
4. **Sampling.** Slice-kind: every `*brief*.md` under `~/.local/state/bigteam` (not the `work*`
   scratch dirs; this run's own briefs and exact copies dropped), at most 4 per task directory plus
   any with a kind header. Prompt-effort: typed text from `~/.claude/projects/*/*.jsonl` (no tool results,
   meta lines, `<...>` wrappers, slash commands, peer messages, dispatched briefs or context
   summaries; at least 20 characters), spread across projects, first 1500 characters kept. The prompt
   sample was re-drawn once after the filter was tightened, and the rows already labelled were kept.
5. **Sample size.** 72 to 100 rows give a 95% interval of about plus or minus 9 to 10 points
   (Wilson: Jev 65-82 / 73-90 / 53-72, Haiku 68-84 / 68-87 / 41-61 for the three datasets in the
   order above). Differences between the deciders of under about 12 points are not established.

### Headline

| Dataset | Decider | Accuracy | 95% interval | p50 latency | p95 latency | Cost per call | Total cost |
|---|---|---|---|---|---|---|---|
| dispatch-verdict | Jev | 74.7% (74/99) | 65-82 | 0.80 s | 4.67 s | $0.000052 | $0.0051 |
| dispatch-verdict | Haiku | 76.8% (76/99) | 68-84 | 5.50 s | 7.05 s | $0.00058 | $0.0575 |
| slice-kind | Jev | 83.3% (60/72) | 73-90 | 0.94 s | 1.86 s | $0.000061 | $0.0044 |
| slice-kind | Haiku | 79.2% (57/72) | 68-87 | 3.34 s | 5.34 s | $0.00062 | $0.0447 |
| prompt-effort | Jev | 63.0% (63/100) | 53-72 | 1.09 s | 1.78 s | $0.000018 | $0.0018 |
| prompt-effort | Haiku | 51.0% (51/100) | 41-61 | 3.72 s | 5.06 s | $0.00027 | $0.0266 |

Jev's latency is its logged `latency_ms` (the wall time of the whole subprocess was 0.89 / 1.21 /
1.37 s at p50 and 4.98 / 2.21 / 2.13 s at p95). Total spend: Haiku $0.129 (budget $2), Jev $0.011.
Neither decider errored, timed out or answered off-list on any row. Paired outcomes (Jev right, Haiku
wrong / Haiku right, Jev wrong): dispatch 3 / 5, slice-kind 11 / 8, prompt-effort 26 / 14. Only the
last is near significance (two-sided sign test p of about 0.08).

### Jev calibration

Accuracy of Jev's chosen option by its probability for it (n in brackets):

| Dataset | <0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1.0 |
|---|---|---|---|---|---|---|
| dispatch-verdict | 50% (4) | 0% (2) | 29% (7) | 38% (8) | 46% (13) | 94% (65) |
| slice-kind | 0% (1) | 50% (6) | 17% (6) | 100% (1) | 88% (8) | 96% (50) |
| prompt-effort | 67% (9) | 48% (31) | 75% (24) | 54% (13) | 67% (12) | 82% (11) |

Accuracy and coverage if only answers at or above a threshold are used (coverage is the share of all rows):

| Dataset | at 0.6 | at 0.8 | at 0.9 |
|---|---|---|---|
| dispatch-verdict | 77.4%, 94% | 85.9%, 79% | 93.8%, 66% (4 wrong of 65) |
| slice-kind | 87.7%, 90% | 94.8%, 81% | 96.0%, 69% (2 wrong of 50) |
| prompt-effort | 70.0%, 60% | 73.9%, 23% | 81.8%, 11% |

1. Probabilities are usable for dispatch and slice-kind above 0.9 and not usable below it on
   dispatch (below 0.9 the answers are right under half the time, and a score of 0.8 to 0.9 is a
   coin flip). Prompt-effort is poorly calibrated: 0.5-0.6 is as accurate as 0.7-0.9.
2. The four dispatch answers at or above 0.9 that were wrong: a `partial` called `done`, a `partial`
   called `provider_error`, a `blocked` called `done`, a `provider_error` called `no_report`.

### The effort hint (the only site that can act)

Act fires only on a confident (>= 0.8) `mechanical` while the session runs Opus or Fable.

| Jev says `mechanical` at | Rows | Truly mechanical | Labelled `normal` | Labelled `hard` |
|---|---|---|---|---|
| >= 0.6 | 24 | 20 | 4 | 0 |
| >= 0.8 (live threshold) | 13 | 11 | 2 | 0 |
| >= 0.9 | 9 | 8 | 1 | 0 |
| >= 0.95 | 5 | 5 | 0 | 0 |

Recall is low (11 of 38 mechanical rows at 0.8), so the hint would fire on about a ninth of prompts.
No `hard` prompt was ever confidently called `mechanical` (Haiku called 3 of 19 `hard` prompts
`mechanical`, unqualified). The 2 mistakes at 0.8 are `normal` prompts, so the cost of a wrong hint
here is a suggestion to drop to Sonnet for a task a little above rote.

### Per-site recommendation (by the promotion rule above)

The rule asks for 200 successful live calls over seven days, 50 reviewed labels, 95% labelled
accuracy, dispatch agreement of 95%, error rate below 1%, p95 under the deadline, mean cost under
$0.0001 and no confident-mechanical on hard. This run can only speak to accuracy, agreement,
cost, latency and the mistake rule; the live log has to supply the rest.

| Site | Verdict | Why |
|---|---|---|
| dispatch-verdict | **Drop** (keep the shadow call only if it is re-aimed) | Accuracy and agreement 74.7% equal the always-`done` baseline and trail the 95% bar by 20 points; Haiku is no better (76.8%) and 10 times dearer; even at 0.9 it is 93.8% (below 95%) on two thirds of rows; 4 of 99 calls ran over 5 s with 4 in flight, close to the 5 s default timeout. The incumbent is a free exact rule. A Jev site only earns its place on a question the rule cannot answer, such as "did this report do what the brief asked", which needs labels this run does not have. |
| prompt-effort | **Stay shadow** | 63.0% overall and 73.9% at the live 0.8 threshold, far below 95% on this agent's labels; no confident-mechanical on hard (rule met on 19 hard rows), p95 1.8 s fits the 3 s budget, cost $0.000018. If the hint is wanted sooner, raise the act threshold to 0.9 or 0.95 (8 of 9, then 5 of 5 right here) and let the live shadow log, labelled by the operator, confirm. Jev beat Haiku by 12 points, not conclusively. |
| slice-kind (no live site exists) | **Candidate for a new shadow site** | 83.3% overall and 96.0% at 0.9 on 69% of rows, p95 1.9 s, $0.000061. Only worth wiring if routing wants a second opinion beside the rules in `route_agent.py`; start in shadow, send sub-0.9 answers to the existing rule, and have the operator relabel a sample. Not promotable: no live calls yet, and 68 of 72 labels are the reviewer's. |

### What would change these numbers

1. Operator labels. Sixty-eight slice-kind and 100 prompt-effort labels are one agent's; the first
   disagreement the operator finds in either set is a reason to relabel the lot.
2. State shape. Dispatch sees only the stderr summary and the last 4000 characters, as the live
   site does; its truth depends on the first line (`BLOCKED:`) and the presence of a final `DONE`.
   A variant that adds the report's first line was not run.
3. Effort option text in the `criteria` (as live) rather than the question may move prompt-effort
   either way; the eval could not use it without editing `bin/jev`.
4. A larger, older mix: the dispatch history is 101 jobs from about a week of work.

Reproduce: `bin/jev-eval build && bin/jev-eval run --dataset D --decider jev` (and `haiku`), then
`bin/jev-eval score`. Runs resume; labels live in `~/.local/state/jev/eval/<dataset>.labels.json`.
Offline test: `~/ops/site-private/bin/bg uv run --with pytest python3 -m pytest -q tests/test_jev_eval.py`.
