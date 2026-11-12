# Nightly learning: first admission slice

Design snapshot: 2026-11-12. The [walk decisions, lines 111–124](slim/audit-walk-decisions-2026-11-12.md)
require a real token budget, independent review and regression checks before
PR-based adoption of skill-only improvements. Standing-order edits remain
proposals; suspected injection blocks the affected proposal. Classification
depends on effect, including policy changes disguised as skill edits.

`ade-retro` and [skills/retro](../skills/retro/SKILL.md) already gather read-only
facts and propose recurring lessons. There is no `skills/learn` in this checkout.
Historical SkillOpt's unenforced budget is not reused. [Scheduling](scheduling.md)
places agent judgment jobs in Paseo schedules; this slice installs none.

The future pipeline is: collect bounded evidence → reserve worst-case tokens →
bounded model call → injection assessment → independent effect review → classify
→ proposal PR → regression checks and independent adoption review. A later
adopter must bind all evidence to the exact reviewed diff/head and enforce the
repository merge gates. This slice does not harvest transcripts, call a model,
publish proposals, schedule jobs, or merge anything.

## Budget guard

`bin/ade-nightly-learning` is an offline CLI. A trusted runner creates one ledger
per night; every generation, replay, injection assessment and review call must
reserve against that SAME ledger before dispatch. The runner owns the night ID
and ledger location: creating a fresh ledger per retry defeats the budget.

```
bin/ade-nightly-learning init /trusted/state/night.json --limit 20000
bin/ade-nightly-learning reserve /trusted/state/night.json --call-id review-1 --tokens 4000
```

`--tokens` must bound all input (including cached input) plus maximum output and
reasoning tokens. A future provider adapter must establish that bound and enforce
its output cap; providers without a reliable bound are refused. This tool cannot
cap an independently launched model or verify a caller's estimate. It enforces
admission accounting, not a live provider runtime limit.

Reservations are charged permanently, even on timeout, retry or crash. Duplicate
call IDs are denied, not replayed as fresh admissions. Exact-cap admission is
allowed, further calls are refused. Initialization cannot overwrite a ledger.
An exclusive sidecar lock serializes concurrent callers; atomic replacement and
fsync precede a successful admission. A crash after charging can waste budget
but cannot reclaim it. Missing/corrupt ledgers fail closed. The parent directory
must already exist and be private/trusted; this is not a security boundary
against an actor who can rewrite the ledger or bypass the CLI.

## Proposal classifier

```
bin/ade-nightly-learning classify /trusted/review-manifest.json
```

The manifest is produced by a trusted independent reviewer from the full diff,
including removed lines, renames (both paths), symlinks and referenced scripts.
It must not come from the learning model or proposal text. Every changed path
must be listed; a rename lists both endpoints. No content heuristic can prove
that a skill edit preserves standing policy. This classifier therefore requires
an explicit reviewed effect, with `unknown` available for uncertain changes:

```json
{"changes":[{"path":"skills/retro/SKILL.md","effect":"skill-local"}],"injection":"unknown"}
```

Effects: `skill-local`, `standing-order`, `other`, `unknown`. All paths must be
canonical repository-relative paths. An empty manifest is invalid. Known agent
instruction filenames force `standing-order`; so does any standing-order effect,
even under `skills/`. Only an entirely skill-local change set under `skills/`
is `skill-only`; mixed or unknown effects are `other`. A standing-order change
is proposal-only. `reviewed_adoption_candidate` is a routing hint for later
review, never an approval: every result has `adoption_authorized=false`.

Injection assessment is `clear`, `suspected`, or `unknown`. Both suspected and
unknown block proposal publication. [S5a PR 576](https://github.com/djbclark/djbclark-ade/pull/576)
was inspected at head `052e7c3452d88484fc60b18619ddee620dc30853`: it remains an
advisory, shadow-mode probability gate with measurement before reader adoption.
This slice neither imports it nor treats its benign score as `clear`. A future
integration needs measured authorization and evidence bound to every source
and proposal; unavailable/escalated evidence remains unknown.

Exit codes: 0 initialized/admitted/proposal allowed; 3 budget/duplicate refusal
or injection hold; 2 invalid input/unavailable state. No result authorizes merge.
Tests cover cap boundaries, durable restart, corruption, concurrent contention,
policy effects inside skills, mixed changes, injection holds and CLI refusals.
