# Wave 6 resumed in a fresh cloud environment — 2026-11-10

## A. Verified starting point

- ADE base: `7589e329e4a43f5569e9e14c349cec812d99e24d`.
  GitHub reports #534 and #535 merged. The initial cloud checkout was older;
  work uses a separate linked worktree, branch `wave6-cloud-resume-20261110`,
  claimed by `codex-wave6-root` for 72 hours.
- `python3 bin/wave6-delete-check --inventory --dry-run --json` exits 0:
  `callers_remaining=0`, `coverage_ok=true`, `fixture_shape_ok=true`,
  `gate_exits.evaluate_no_evidence=1`, `ready=false`, `mac_live_blocked=true`.
  This is inventory/fixture validation, not a live-evidence check.
- The earlier archive at `~/tmp/wave6-mac-from-bigmac-20261110/` is absent
  on this fresh host. Its earlier verification remains recorded in
  [the handoff](wave6-cloud-handoff-2026-11-10.md); no new archive verification
  or Darwin recapture was performed here.
- Neither `paseo` nor `aiuse` is on PATH. `route_agent.py show` reports an
  absent quota snapshot. Account quota and native Mac session state are unknown.
  No live pool acceptance, session labels, or outside configuration changed.
- `graft` and the local `graft/` graph are absent; preparation used targeted
  documentation/source inspection. One fresh-context GPT-6.1 Sol medium
  subagent prepared A3/A4; no extra frontier orchestrator was started.

## B. Read-only follow-up findings

### B1. A3/A4 — native routing must preserve capacity checks

The existing native routing procedure (`skills/model-routing/SKILL.md` D5)
does not subtract sibling in-flight reservations. Replacing the legacy
launcher name alone would therefore weaken the outside projects' stated
quota invariant. The migration must retain allowance, fresh headroom,
per-project estimate floors, and conservative accounting for other live work;
unknown capacity must hold the launch.

### B2. A5 — active instructions confirmed, no blanket historical waive

Read-only GitHub inspection of `djbclark/cfengine-all` at
`9bcc7f51eb384b23d381a3b6de9d58cff0f259d6` found active instructions in
`AGENTS.md` (blob `a0a6ad9dcf66dca934ce7da7a6da98236135c684`):

- Line 63 describes the current `fleet-watch upstream` draft-writing path.
- Lines 166–175 direct resumed sessions to a fleet relay and `/cfenginewatch`.
- Search also found dated references in
  `docs/handoffs/HANDOFF_standalone-3fd9_upstream-watch-relay_2026-10-24_6a9f.md`.

These are distinct active and historical categories. Search was not an
exhaustive local C3 probe. No migration or waive was applied; preserve the
dated handoff and existing upstream-contact approval rules.

### B3. A6 — passive history remains distinct from live teaching

Read-only inspection of `djbclark/aiuse` `AGENTS.md` (blob
`b5d50dd291be5bd406c578c71ce4e1db6f484738`) confirms both passive ACP
context-log accounting and historical delegation-enforcement teaching.
This is preliminary classification, not an exhaustive source audit. Retain
logs and accounting; any historical-reader waive needs its own explicit grant.

## C. Boundaries and next action

A3+A4 authorization is granted and the implementation is recorded in section D.
C1+C2 are already granted; do not ask again. A5–A7 and X1 still require
separate authorization, one card at a time. X2 requires Mac access and proof
the old lead has ended.

Keep `relay.py`, `acp-dispatch`, `acp-run`, and `review-launch`. Do not use
`--allow-early`; the deadline remains 2026-11-20. No deletion PR before the
real evidence gate exits 0 and the operator confirms. Keep Pi
Grok/Antigravity/SIPB/Go `accepted=false`.

## D. A3/A4 authorized and implemented in PRs

Operator explicitly authorized A3+A4 as proposed on 2026-11-10. Do not
ask for this authorization again. Upstream heads still matched the pinned
proposal. Separate claimed worktrees changed only `AGENTS.md`:

| Project | PR | Pushed head |
|---|---|---|
| tendcf | [#44](https://github.com/frdminc/tendcf/pull/44) | `71fe7d6b8acfb8d8b162b6f198ca8f2b7c3789ec` |
| nix2cf | [#7](https://github.com/frdminc/nix2cf/pull/7) | `f3965768d90b1ef2d022e9198dcc41c55b542d2b` |

Both pass `git diff --check` and the C3 AGENTS.md retired-launcher name
probe has no matches. The shared checkouts remain clean. A GPT-6.1 Sol
medium mechanical comparison found no application errors; this is **not**
the projects' mandatory independent frontier review. No policy/runtime tests
were run for these instruction-only changes.

**Availability exception granted (operator, 2026-11-10):** “We can override
anything that requires agents we don't have access to in our environment.”
Both PRs now document substitution of available capable agents for unavailable
named leads/reviewers. Review, CI, quota/admission and other approval boundaries
remain. A separate fresh-context GPT-6.1 Sol high reviewer is reviewing the
full changes; this is not cross-family review. PRs are ready for review,
not merged; exact-head review and CI remain pending. No C3 completion claimed.

## E. Resume prompt

```text
Continue Wave 6 / Pi from djbclark/djbclark-ade PR #538, branch
wave6-cloud-resume-20261110 (base master 7589e329).
Read docs/slim/wave6-cloud-resume-2026-11-10.md and
docs/slim/a3-a4-native-routing-proposal-2026-11-10.md, then the prior
wave6-cloud-handoff-2026-11-10.md and queue Carried item 1.
Check PR #538's current head, review and CI; no APPROVE marker was invented.
A3+A4 authorization was granted and implemented in PRs:
frdminc/tendcf#44 at 71fe7d6b8acfb8d8b162b6f198ca8f2b7c3789ec;
frdminc/nix2cf#7 at f3965768d90b1ef2d022e9198dcc41c55b542d2b.
Do not ask again. The operator permits available-agent substitutions. Obtain a separate fresh-
context substantive review on those exact heads; record actual model/effort.
Preserve quota/admission checks. Fix findings,
re-review changed heads, verify CI, then merge. Preserve native admission hold.
Then handle A5-A7 and X1 one authorization card at a time; preserve logs.
This fresh cloud host has no prior Mac archive, paseo, aiuse or quota snapshot.
Do not fabricate live evidence. C1+C2 already granted, no re-asking.
Keep all shims/review-launch, held Pi pools false, and no --allow-early.
Deletion needs actual gate exit 0 plus explicit operator confirmation.
```
