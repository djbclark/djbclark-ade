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

## C. Current scope and hard stops

Operator clarification, 2026-11-10: focus on **djbclark-ade**. Outside work
is permitted only when a specific ADE dependency requires it. The scoped C3
instruction/client migrations and X1 relay caller qualify; no general work on
those projects is authorized by this session. The operator then requested
wrapping work already in progress to a good stopping point; start no new items.

The operator also permits capable available agents in place of agents required
by local instructions but unavailable in this environment. This changes named
model requirements, not review, CI, quota/admission or other approval boundaries.

C1+C2 are granted; do not ask again. No further historical/passive-reader waiver
has been granted. Preserve all historical records and usage accounting.
Keep `relay.py`, `acp-dispatch`, `acp-run`, and `review-launch`. Do not use
`--allow-early`; deadline remains 2026-11-20. Deletion still requires real
Mac evidence, a successful gate and explicit operator confirmation. Keep Pi
Grok/Antigravity/SIPB/Go `accepted=false`.

## D. Dependency checkpoint

| ADE blocker | Artifact | Head / result |
|---|---|---|
| A3 tendcf | [#44](https://github.com/frdminc/tendcf/pull/44) | **merged** `3f93d28d36363fb9b0c63d2281e12dd0e82cd294`; reviewed head `71fe7d6b8acfb8d8b162b6f198ca8f2b7c3789ec`; Check + all Linux jobs passed |
| A4 nix2cf | [#7](https://github.com/frdminc/nix2cf/pull/7) | **merged** `572b0b705278bf54e53769820a91b8c20413e144`; reviewed head `f3965768d90b1ef2d022e9198dcc41c55b542d2b`; exact-head Check passed |
| A5 cfengine-all | [#1](https://github.com/djbclark/cfengine-all/pull/1) | **merged** `134c9afb3aea11a00b72750562a935934101406a`; reviewed head `8ba9ce32a11802c04e390ece7dd83e0e8f129cda`; active instructions only |
| A6 aiuse | [#54](https://github.com/djbclark/aiuse/pull/54) | draft `a69d2e80b0f743a65b7c54ec8421c2b9cc9ef32d`; local review clean, CI pending |
| A7 home instructions | [#250](https://github.com/djbclark/site-djbclark/pull/250) | draft `05998b34c4c0e86655a131b854a0398f4ef23676`; review clean, CI pending |
| X1 fleet-watch | [#251](https://github.com/djbclark/site-djbclark/pull/251) | draft `8aecdd371bc7d5b921de0a6ac2537655b3986c31`; repaired/re-reviewed, CI and live proof pending |

### D1. Review and validation

A3/A4: a separate fresh-context GPT-6.1 Sol high reviewer reviewed both full
diffs against their pinned bases and ADE source: **no findings**. This is
same-family review under the explicit availability exception, not cross-family
frontier review. Both `git diff --check` and the AGENTS.md retired-launcher
probes passed. No policy/runtime tests were run locally for instruction edits.

A5: GPT-6.1 Sol medium authored the two prepared instruction replacements;
the root independently reviewed the complete diff, preserving upstream-contact
approvals and historical handoffs. No findings. No GitHub workflow directory
exists in this repository. Documentation checks passed. Runtime watcher
integration remains X1 work; preserved historical references still need a
separate C3 disposition. The default branch is `main`.

A6: GPT-6.1 Sol high authored the active runtime-message/instruction correction;
root independently reviewed all eight changed files, with no findings. Full
pytest: **1,897 passed before and after**; changed-file mypy, Ruff formatting
and lint, Prettier, Markdownlint and whitespace checks passed. Passive ACP
collectors, refusal/frozen-quota readers, schema and logs remain unchanged.
Their historical references still need explicit operator disposition; this
PR does not silently grant a waive or complete C3.

A7: GPT-6.1 Sol medium authored the two instruction-file changes. Root review
required clarification that ADE report classes are not native CLI exit codes,
DONE/.done is success-only, and the unavailable-agent exception is explicit.
The repaired diff has no findings. Stable unique rule IDs and all original
memory/wiki pointers retained; retired names absent; whitespace clean. Size:
`home-agents.md` 70 lines / 13,785 bytes; Cursor copy 75 / 13,998 bytes. No
live home file was installed. PR #250 is mergeable; an initial false result
while GitHub calculated mergeability was transient, not a confirmed conflict.

X1: GPT-6.1 Sol medium authored the native sender migration. A separate
fresh-context GPT-6.1 Sol medium reviewer found two P2 duplicate-send hazards:
unknown timeouts and accepted agent messages were treated as retryable failures.
Repaired at the table's exact head: persist pending/unknown receipt state before
sending; do not replay or dispatch a fallback for ambiguous/accepted outcomes;
retain phantom write-ahead state; request a named ack for agent-origin sends.
Bounded re-review: **no findings**. Pending states require manual receipt/ack
reconciliation; no automatic ack ingestion is implemented.

Focused X1 validation via `just test`: **34 passed, 2 skipped, 24 subtests
passed**, 1,321 deselected; shell syntax and diff checks passed. Initial broader
fleet selection had 29 failures associated with absent GNU-prefixed tools;
the changed upstream fixture supplies aliases, and the focused migration suite
passed. Unrelated S1 harness failures were left untouched. Full live Mac send
behavior remains unverified. Draft #251 preserves the tested source.

### D2. Evidence limits

Merged source is not proof of installed Mac state. No C3 evidence JSON has
been fabricated or marked complete here. No Mac B2 recapture, live receipt
round, live quota reading, pool acceptance, or extra waiver occurred. Archived
historical matches in CFEngine/aiuse stay preserved. The old live lead's B2
label and the date gate remain outstanding.

The cloud `gh` API path is forbidden; use connected GitHub tools for metadata.
The specialized commit-workflow wrapper returned empty results even when the
repository Actions feed had runs. Inspect Actions runs/jobs and their full
`head_sha`, not an empty wrapper result or a prior head's passing run.

## E. Resume prompt

```text
Resume ADE Wave 6 from djbclark/djbclark-ade PR #538,
branch wave6-cloud-resume-20261110. Read this checkpoint and the prior
wave6-cloud-handoff-2026-11-10.md, wave6-follow-up.md and queue Carried 1.
The operator asked to wrap current work; do not start new work without a
new continuation request. ADE is the focus; outside work is permitted only
for specific ADE dependencies. A3+A4 authorization was granted. Required
unavailable agents may be replaced by capable available agents; record the
actual reviewer model/effort and preserve all other gates.
Check the current exact heads and CI on the PRs in section D. Tendcf#44, nix2cf#7 and
cfengine-all#1 are merged. Aiuse#54 and site#250/#251 are draft checkpoints
with their recorded remaining checks. Fleet pending receipts need manual
reconciliation; never replay unknown/accepted sends automatically. Preserve historical/passive accounting; no extra
C3 waive is granted. Do not equate source merge with Mac deployment evidence.
No Mac archive/paseo/aiuse/quota snapshot exists on this fresh cloud host.
Keep shims/review-launch, held Pi pools false, no --allow-early. Deletion
requires actual evidence gate exit 0 plus explicit operator confirmation.
```

## F. Local checkpoint layout

All task work is committed and pushed; clean task worktrees are retained for
resumption. Agents are quiescent at closeout; GitHub CI may continue independently.
No watcher or automation was created to resume this chat.

| Worktree | Remote branch |
|---|---|
| `/workspace/wave6-cloud-resume-wt` | ADE `wave6-cloud-resume-20261110` (#538) |
| `/workspace/tendcf-wave6-wt` | tendcf `wave6-native-routing` (merged) |
| `/workspace/nix2cf-wave6-wt` | nix2cf `wave6-native-routing` (merged) |
| `/workspace/cfengine-all-wave6-wt` | cfengine-all `wave6-native-instructions` (merged) |
| `/workspace/aiuse-wave6-wt` | aiuse `wave6-native-guidance` (#54) |
| `/workspace/site-djbclark-wave6-home-wt` | site `wave6-home-native-instructions` (#250) |
| `/workspace/site-djbclark-wave6-fleet-wt` | site `wave6-fleet-native-send` (#251) |

Claims have 72-hour TTLs; inspect/reclaim appropriately on resume. No account
quota API was available: actual token/quota consumption is unknown, not zero.
One preparation/review agent, one substantive-review/aiuse agent, and two site
writers were used with bounded briefs; no additional frontier orchestrator.
