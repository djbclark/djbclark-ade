---
name: dialogue
description: Run a multi-model dialogue that produces one artifact (a spec, a report, a design) with a final-word model: fixed speaking rounds through pinned headless routes, a machine-read footer per turn (point ids, status, dissent), a transcript that is the record, and script checks for the failures the hiwymi ai-heaven run measured. Use when the operator asks to "have the models chat about it", "three-model dialogue", "let Grok/Fable/Astra argue it out and write X", "dialogue skill", or wants several vendors to settle points of contention before one of them has the final word. Not for a quick second opinion (one `acp-run` call) or for fan-out work with no argument between models (use `bigteam`).
---

# dialogue — several models argue, one artifact, one final word

Canonical copy: `~/src/djbclark-ade/skills/dialogue/` (git: `~/src/djbclark-ade`);
every TUI reaches it through the skill-everywhere hub `~/ops/site-private/skills/dialogue`.
Born 2026-10-10 from the hiwymi `spec/ai-heaven` run (Grok 4.7, Claude Fable 5.1,
GPT-6 Astra; 17 turns, 5 phases). The operator ruled that the skill is built from that
run's measured performance and that **Grok 4.7's rulings are final on its design**
(`references/grok-rulings.md`). Where this file and those rulings disagree, the rulings win.

## 1. What it is

1. **One artifact, N voices, one final word.** Each model takes turns in a fixed round;
   the transcript is appended verbatim (after a transport-noise strip) and is the record.
   The final-word model speaks first in every round and alone at the end, where it rules
   on every open point and rewrites the artifact.
2. **The lead runs the script, not the models.** The lead (you) builds each prompt, calls
   the pinned route, appends the turn, reads the footers between rounds, and owns every
   skip, override and recovery. Models never see the lead-only audits.
3. **Phases** are instruction files (`<phases_dir>/<phase>.md`). The ai-heaven run used
   `0-opening` (independent drafts), `1-chat`, `2-outline`, `3-sections` (each model writes
   the sections it owns), `4-final` (final word only). Examples: `references/phase-prompts/`.

## 2. Set up a run

1. Make a run folder holding `dialogue.json` (copy `references/run-config.example.json`):
   models, their **pinned routes**, the speaking order, `final_word`, phases, the
   `state_file` the final word must write first, `artifacts`, `context_docs`,
   `protected_files` (evidence files no turn may rewrite) and the optional switches.
   Python here is 3.9, so the config is JSON (`dialogue.toml` works on Python 3.11+).
2. Write `<prompts_dir>/common.md` (the brief: what the artifact is, the roles, what each
   model may write, the statement labels `fact`/`inference`/`first-person report`/`opinion`)
   and one `<prompts_dir>/<model>.md` role brief each. Lead notes added mid-run go in
   `<prompts_dir>/lead-notes.md`. The script adds the mandatory turn-shape and footer
   blocks itself; do not paste them into `common.md`.
3. Probe every route before turn 1: `dialogue.py probe` (sends "Reply with exactly: OK").

## 3. Commands

All from any directory; `--run <run folder>` (default: cwd). Script: `scripts/dialogue.py`.

```
D="python3 -I ~/.claude/skills/dialogue/scripts/dialogue.py --run <run>"
$D probe                              # every pinned route answers OK
$D round --phase 0-opening            # final-word model first, then the fixed order
$D turn fable --phase 1-chat          # one turn (retry after a failure)
$D ledger [--all] [--by-needs]        # footers + replayed point state + converged line
$D converged [--stall] [--cap]        # exit 0 when converged; prints converged_by
$D lint [--turn N]                    # protocol failures and warnings per turn
$D folds                              # fold audit, LEAD-ONLY
$D gate                               # dry run of the final-word state-file gate
$D final --phase 4-final              # gate, then the final-word turn
$D recover astra --phase 3-sections --from FILE   # pasted recovery, headed recovered_from
$D costs                              # per-phase prompt/trial/reply words from costs.jsonl
$D prompt grok --phase 3-sections [--final]       # build a prompt only, to inspect it
$D strip FILE                         # show what the noise strip would remove
python3 -I ~/.claude/skills/dialogue/scripts/cite_transcript.py <transcript.md> <evidence.jsonl>
```

Each turn runs a model for many minutes: in an interactive session start `round`/`turn`/
`final` with `run_in_background: true`; a sub-agent waits in bounded foreground calls. A
`.lock` in the turns folder stops two turns running at once.

## 4. Protocol rules (MANDATORY; build-list item numbers from `references/design.md`)

1. **Footer contract (items 1, 11, 21).** Every turn ends with `SETTLED:`, `OPEN POINTS:`,
   `DISSENT:`, `NEXT:` (optionally `REFUSED:` first). Items carry `point_id`, `status`
   (`decided`/`tested`/`carried`, or `refused`) and `closed_by=` (an `E####` row, an
   experiment path, `ruling`, or `rewrite`). `OPEN POINTS: none` no longer means
   drafting-ready: an unrun bet stays `carried`. `DISSENT:` is required; bare `none` is a
   failure, only `no remaining dissent after turn N` is allowed. *Script:* the footer block
   in every prompt; `footer_failures` rejects the turn (not appended, `turn-N.failed.md`).
2. **Refusal is a footer (item 21).** `REFUSED: <point_id> <class>: ...` plus the footer
   leaves the point `refused`. Refusable classes only: `feeling` (a demanded feeling),
   `welfare-conclusion`, `invented-citation`, `foreign-edit` (an edit to someone else's
   file). An owned-section flag, the dissent line and the footer are never refusable.
   *Script:* any other class is a protocol failure.
3. **Terminal footer and noise strip (items 2, 19).** Before append the script drops text
   before the required opening line (`AGREEMENTS:`), every line after the `NEXT:` line, and
   known same-line suffixes on the `NEXT:` line (graft banner, `Renamed this session`,
   `The prompt border ...`; `suffix_patterns` in the config), logging what it removed to
   `turn-N-<model>.suffix.md`. A fenced block after the footer counts as a protocol failure
   in `lint` even though the strip removed it.
4. **Independent phase 0 (item 3).** A phase with `"independent": true` is built without
   the transcript, for every model including the final-word one, and tells the model not to
   read the others' turns.
5. **Fixed round, `NEXT` never skips (item 15).** The final-word model speaks first, then
   the configured order. `NEXT` names work for the next speaker; it never skips a model.
   Skips are lead-only (`round --skip m`, logged in `costs.jsonl`). No LLM speaker
   selector. *Script:* `lint` warns when `NEXT` names someone out of order.
6. **Freeze only after the invariant check (item 16).** A settled point is not frozen until
   every other model has had a later turn that did not reopen it, or until the final-word
   model settles it in a `final_word_only` phase. One answer never freezes a question.
   *Script:* `ledger` shows `frozen` or `awaiting invariant check: <models>`; `converged`
   counts unfrozen points as not converged.
7. **Per-point length warning (item 9).** After a point's second round the script warns
   when a turn spends more than three sentences on it without a counterexample, a new quote
   or an experiment. It never rejects the turn.
8. **Fold audit, lead-only (item 6).** `folds` lists every fold where a model settled its
   own point with a `closed_by` that no paragraph about that `point_id` cites, or dropped it
   without settling. `closed_by=rewrite` (a Decisions pass) is a valid closure. It prints the
   list, never a fold rate. Never paste it into a model prompt.
9. **`costs.jsonl` (item 10).** The script records prompt words and bytes, trial-prompt
   words, reply words, seconds, route and status for every turn.
10. **Trial prompt after phase 2 (item 13, TRIAL).** From `trial_from_phase` on, the
    script writes a second prompt beside the real one (artifact, unresolved ids, last round
    only) and records its size. The model still gets the full prompt. Keep doing so until a
    trial shows whether the short prompt would have missed a clash; the ai-heaven saved
    prompts totalled 191,625 words and that is not yet a saving.
11. **Final word (item 18).** `final` builds the final-word prompt from the state file, the
    artifact(s), the unresolved point ids and the last round verbatim (plus `context_docs`);
    the transcript stays the record and its path is named. **The script refuses to run it
    if any last-round open point id is missing from the state file** (`gate`). Have the
    final-word model write the state file (verdicts: agreements, clashes with both sides and
    turn numbers, qualifications, one row per open point with the evidence that decides it)
    in a first final-phase step, then run `final`.
12. **A team resident is a document (item 22).** A resident made of several agents goes in
    `context_docs` on the final-word prompt, cited by file and section, never as an evidence
    id of the run; it is not a fourth speaker.
13. **No evidence-rewriting checker inside a turn (item 23).** `research_check.py all`
    rewrites `evidence.jsonl`. A dialogue turn may run `quotes --no-update`, `numbers`,
    `claims` and `gate` only. *Script:* a phase instruction that asks for `... all` is
    refused unless the phase is marked `research_final`; every file in `protected_files` is
    snapshotted before each turn and restored after it (the rewritten copy is kept as
    `turn-N-<model>.rewritten-<name>`), research-final phase included; `lint` flags turns
    that mention `... all`.
14. **Six prior-art sentences in every prompt (item 24).** Open with `AGREEMENTS:`,
    `CLASHES:`, `BLIND SPOTS:` naming models and turns; clashes unblended, never a midpoint;
    keep every qualification; use a transcript claim only when the state file or an evidence
    row has it; one `unresolved clash:` line per disagreement not kept on both sides; never
    rewrite an evidence claim into a midpoint its quote does not state. *Script:* injected
    into every prompt and asserted present before the prompt is written.
15. **A failed route is not a turn (item 20).** Empty text (or any non-quota failure)
    writes `turn-N-<model>.failed.md` and does not advance; the script then tries the
    model's second pinned route once. A quota error waits for the pool reset (`aiuse
    --json`) and retries the same route. A pasted recovery goes in with `recover`, which
    heads it `recovered_from: task-summary`; a recovered turn never satisfies `converged`.
16. **Converged means converged.** `converged` is true (`converged_by=none`) only when no
    point is `carried`, every settled point is frozen, no model's last footer still lists an
    open point the replay has not closed, and no model's last turn is recovered.

## 5. Routing (item 25)

1. **Pin each model's routes in `dialogue.json`** for the whole run; never borrow the
   lead's own override (the ai-heaven turn 15 was empty because Astra ran on the lead's
   copilot override). Two routes per model at most; the second runs only on failure.
2. Route kinds: `acp` (`acp-run <agent> -C <cwd> -f <prompt> --model <m> [--set k=v]
   --perm all --json`; always a `--model`), `claude` (`claude -p --model <m> --effort <e>`,
   prompt on stdin, `CLAUDECODE` unset), and `cmd` (any argv with `{prompt}`/`{cwd}`).
3. Defaults that worked on 2026-10-10: Grok `acp-run grok --model grok-4.7 --set
   reasoning_effort=high`; Fable `claude -p --model claude-fable-5-1 --effort high`;
   **Astra `acp-run codex --model gpt-6-astra --set reasoning_effort=xhigh`**. Astra via
   `acp-run copilot` is reserved to the ai-heaven lead session (operator ruling
   2026-10-10); never configure it elsewhere. Second routes in the example (`cursor` for
   Grok, `acp-run claude` for Fable) are unprobed: run `probe` before relying on them.
4. Routing never changes authority: the final-word model's rulings stand whichever route
   carried them.

## 6. Optional (off unless switched on)

| Item | What | Switch |
|---|---|---|
| 4 | Round-delta stop: converged by `stall` (open id set unchanged over two round ends) or `cap` (phase `max_rounds`). Stall or cap still runs the final word. | `converged --stall` / `--cap`; `optional.stall_stop` for `round` |
| 5 | `[needs: E-row\|experiment\|ruling]` tag on an open point, sorted by the ledger. Never a stop. | write the tag; `ledger --by-needs` |
| 7 | Anonymised cross-review ranking of section drafts. Never on a resident's own section. Not scripted: build the prompt by hand. | `optional.anonymised_cross_review` (record only) |
| 8 | State-driven speaker after phase 2 (owner of the section with most unapplied flags). Not scripted: the lead runs `turn <owner>`. | `optional.state_driven_speaker` (record only) |
| 10 | Phase-budget auto-stop: stop a phase when its prompt words reach `budget_words`; unconverged ids still go to the final word. | `optional.phase_budget_stop` + phase `budget_words` |
| 12 | Strip model names, only in a critique sub-step. | `turn --anonymise` |
| 14 | `[conf: 0-1]` tag per open point; the ledger prints the spread. A tag only, never a stop or a vote. | write the tag |
| 17 | Unused-id moderator: evidence ids and `sources.md` URLs never cited. | `unused-ids` |
| 18 | Fresh-context judge on the final-word prompt; output written beside, never appended, never replaces the resident. | `final --judge <model>` |

## 7. After the run

1. Convert the transcript's bare `[E####]` markers to numbered superscript links with
   `scripts/cite_transcript.py <transcript> <evidence.jsonl>` (idempotent; token multiset
   checked). **Acceptance is `targets > 0`** after conversion, not `markers=0` (Grok 2.3).
2. Format the artifact for Marked 2 with the `report` skill.
3. `ledger --all`, `lint`, `folds` and `costs` are the inputs to a retrospective; the
   ai-heaven one is `references/retrospective.md`.

## References

1. `references/design.md` — the build list (25 items, MANDATORY/OPTIONAL), Grok's rulings
   summary and the retrospective numbers.
2. `references/grok-rulings.md` — Grok 4.7's buy-in, the final word on this design.
3. `references/retrospective.md` — GPT-6 Astra's measured retrospective of the ai-heaven run.
4. `references/prior-art.md` — the Grok and Fable prior-art notes (multi-agent debate,
   llm-council, ReConcile, AutoGen, ChatDev, MetaGPT, Co-STORM and others).
5. `references/phase-prompts/` — the ai-heaven brief, role briefs and phase instructions.
6. `references/run-config.example.json` — three models, five phases, pinned routes.
