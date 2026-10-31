---
schema_version: 1
handoff_id: 0d50
parent_handoff_ids: [c671]
lineage: deterministic
chain: [go-followups-20261025]
repo: kool-ade
workspace: djbclark-ade-ack-period-wt
branch: fix/relay-ack-period-01a17631
head_sha: 36905dbfd53dbbf633819a5fe8f8cc1b5a98d286
created_at: 2026-10-27T10:25:25.188454-04:00
writer: codex
---
# Handoff — Paseo continuation and relay acknowledgment repair

## The Goal

Continue this operator-facing session in a real Paseo tab in existing workspace `wks_d7ef123a8fdc01c5` (`relay-expect-ack-pr-merge-with-master-pw`). Preserve previous work and verified peer links. The next implementation is the narrow relay acknowledgment punctuation bug selected by the operator through /steps. The user explicitly authorized handoff and continuation, then said “go” after Default mode resumed. Do not ask again merely because the previous session was in Plan Mode.

## Where We Are

Snapshot 2026-10-27. Source root is `/Users/djbclark/src/djbclark-ade`; shared reference checkout is read-only. This new exclusive task worktree is `/Users/djbclark/src/djbclark-ade-ack-period-wt`, branch `fix/relay-ack-period-01a17631`, recorded base `5011bd0a7194b16ae56cc42729a8e57653b23c40` (published master at preparation). Documentation commit `36905dbfd53dbbf633819a5fe8f8cc1b5a98d286` changed only `skills/paseo-handoff/SKILL.md` and `skills/paseo/SKILL.md`. At the pre-handoff checkpoint it was clean; this handoff will be its own subsequent commit. No repair source or tests have changed. Source skill links remain on canonical master until an authorized promotion; do not say the new procedure is installed.

Claim `relay-ack-period-01a17631` belongs to outgoing Codex session `01a17631-0a20-7cc0-9d5e-a6f122a95425` during documentation preparation. The sender will release this task claim before launching you. Acquire a NEW claim with your actual identity before edits/tests; never borrow the old session ID. Check status/log and unresolved merge/rebase first. The retained issue89 claim remains frozen with its prior owner; do not edit or borrow it.

PR71 and PR86 are already merged and activated. [PR71](https://github.com/djbclark/djbclark-ade/pull/71) squash `a6b6bd4fd373551d2032c2337f0228c28dd53d4b`; [PR86](https://github.com/djbclark/djbclark-ade/pull/86) squash `b28548a50dc7688703068972a58a7cb8d2a9f30c`. Codex live policy inherits all, keeps default exclusions (`ignore_default_excludes=false`), preserves seven explicit settings, and passed three fresh zero-inference contexts. Backup intentionally retained mode0600 at `/Users/djbclark/.codex/config.toml.bak-20261026T222434Z-env-policy`. Existing bash startup deliberately overrides SSH_AUTH_SOCK to 1Password: baseline reproduced it; do not “repair” .bashrc. Old PR71/86 worktrees and claims were cleanly removed/released. Do not reopen these tasks.

[Issue89](https://github.com/djbclark/djbclark-ade/issues/89) implementation is complete and pushed, **not PR-created, merged, installed or live-promoted**. Worktree `/Users/djbclark/src/djbclark-ade-git-config-env-wt`, branch `fix/acp-git-config-env-01a17631`, head `f0f90ac533079a828ebc6e8c20fcba14ec709536`, active claim `acp-git-config-env-01a17631`. Clean/head reconfirmed during handoff. User chose a slice excluding paid review, PR creation, merge and runtime promotion. Keep it frozen, including the exact CI-tested head; no new paid review is authorized by this handoff. Future PR prerequisites (independent adversary verdict on exact head, actual PR-number changelog entry) are prepared in private review materials. Never call issue89 PR89.

Issue89 changed `tools/acp-run/acp-run`, `bin/ade_claims.py`, three focused Git tests, `tools/acp-run/README.md` and `docs/git-guard.md`. Complete counted Git config tuples become GIT_CONFIG_PARAMETERS preserving inherited tuple → injected identity-guard → existing raw parameters ordering, including nested legacy launches. Separately quote `'key'='value'` with Git-compatible single-quote escaping; shlex.quote alone is wrong. Incomplete tuples fail launch exit2 with variable-name-only errors. Guard parser accepts old and new quoting and spends only the exact known guard pairs once; CLI duplicates/extra hooks still fail. Operator Codex policy and identity guard stay enabled.

## What We Tried

Plan Mode correctly prevented all transfer mutations; repeated imperative requests could not override that developer mode. Now Default mode is active. This was the primary delay, not a failed Paseo launch.

The current host exposes no callable Paseo MCP tools. Installed root CLI roster has no profile subcommand (`paseo profile ls` failed without side effects). Do not infer the live profile catalog is empty. Local source shows list_profiles reads daemonConfigStore.agentProfiles; config.json has no such configured field, but that is not a live RPC profile result. We used the documented terminal fallback: live provider/model discovery, quota and explicit launch settings. Available Claude Sonnet5.5 has medium thinking; Claude has 26% weekly remaining and 100% current five-hour remaining in a fresh snapshot, so medium Sonnet pipeline continuation is appropriate. No paid frontier call was needed.

Actual old acknowledgments arrived, but running normal relay sweep alone cannot recognize them. The exact matcher rejects sentence-final dot; replacing the terminal dot with whitespace makes the read-only detector succeed. Do not hand-edit records to hide the defect. Do not resend already delivered/queued messages.

An earlier red issue89 assertion dumped ambient environment; fixture and saved log were sanitized. Never inspect or reopen the original contaminated `codex-adversary.jsonl` or original adversary output/report/transcript. Operator previously declined rotation; do not reopen that decision. Clean r2 report is the retained review evidence.

## Key Decisions

Use the existing relay Paseo workspace and a new real agent tab, never an ACP terminal as the operator-facing successor. Shared workspace cwd stays read-only; all implementation/tests belong in this task worktree. Do not detach through wire/CLI operations or archive existing agents/workspaces.

Durable procedure is now recorded in the two source skills: distinguish Plan Mode from launch failure; use live CLI discovery when MCP profiles are unavailable; pass explicit workspace and chain pointer; verify startup once; notify peers through relay; never bypass question-card refusal. These docs are committed/pushed on this task branch, not installed on master.

## Decisions

- [decision] Continue through real Paseo agent in existing workspace; rejected: ACP headless handoff; because the operator needs a readable and steerable transcript.
- [decision] Keep issue89 implementation frozen at its tested head; rejected: mix acknowledgment repair into it; because scope and review evidence are separate.
- [ruling] “Never use .docx; use .md or .pdf only” (djbclark, 2026-10-26).
- [ruling] “we do not need to be super-pedantic about security; I want to spend as little money on that aspect as is reasonable” (djbclark, 2026-10-26).
- [ruling] “when you figure it out, please make sure how to do it getrs recorded in appropriate places in ~/src/djbclark-ade” (djbclark, 2026-10-27).

## Relations

- continues [[HANDOFF_go-followups-20261025_final-review_2026-10-25_c671]]
- decided_in [[HANDOFF_go-followups-20261025_paseo-relay-continuation_2026-10-27_0d50]]

## Evidence & Data

Private artifacts directory: `/Users/djbclark/.local/state/bigteam/go-followups-20261025/`. Read `gitcfg-review-materials.md`, `gitcfg-ci-final.json`, `gitcfg-ci-totals.json`, `gitcfg-branch-evidence.json`, `pr71-activation.json`, `pr71-fresh-probes.json`, `activation-summary.md`, `final-promotion.json` only as needed, without printing secrets or entire logs.

Issue89 local checks passed: focused157+5subtests; broad459+5subtests; final22+10subtests. [Exact-head hosted CI40418914673](https://github.com/djbclark/djbclark-ade/actions/runs/40418914673) succeeded: Linux5526passed/25skipped/1507subtests; macOS5530passed/21skipped/1507subtests; context108passed/20skipped. Zero-inference installed-Codex probes preserve default exclusions and actual identity-hook enforcement; do not call them model-issued tool execution proof.

This documentation-only handoff ran git diff --check successfully; no new test suite or model inference was needed. New repair tests have not run.

## Operator Feedback

Act autonomously within authorized scope; no .docx, no optional Finder reveal, no busy-TUI restart, no new paid review, no blanket security redesign. All work in claimed workspaces; commit/push coherent own changes through git-commit-own explicit paths. Run local tests through `/Users/djbclark/ops/site-private/bin/bg`, heavy suites in hosted CI. Coordinate related peers; do not steal their tasks.

## Where We're Going

1. **First action:** read the explicit chain pointer `/Users/djbclark/.local/state/handoffs/chains/go-followups-20261025/SESSION_LOG.md`, verify this worktree and published branch head, acquire your own exclusive task claim, and coordinate with relay owner `bb2a32df-81a6-4370-927a-d61717b6e985` before any relay source edit. Sender is notifying peers of your new location; inspect private transfer receipts for delivery evidence rather than duplicating messages.
2. Implement the selected narrow acknowledgment fix: `skills/session-finder/relay.py` `ack_token` around2725 currently returns `re.compile(rf"(?<![\w-])ack[ :=]+{re.escape(token)}(?![\w.-])", re.I)`. Accept a terminal sentence period only when followed by whitespace/end, while refusing longer valid identifiers (`ID.more`, `ID.-suffix`, `ID..suffix`, word/underscore/hyphen suffix). Preserve existing case-insensitive ack/ack:/ack= behavior, exact peer-header matching and user-role-only scanning. Use graft callers before editing; span may drift.
3. Regression coverage in `tests/test_relay_verified.py` TestExpectAck: real Codex user-message schema with `ack ID.` resolves; whitespace/end cases; longer dotted identifiers do not; wrong peer, assistant/tool/summary quotations do not. Existing sweep test around211 and longer-id test around226 are entrypoints. Keep the fix and focused validation proportionate; document behavior and repository-required changelog before any future PR. No automatic paid reviews or merger authorization is inferred.
4. Actual expectations `/Users/djbclark/.local/state/relay/deferred/expect/promo-peer-20261026.json` and `gitcfg-context-01a17631-1026.json` remain open/overdue despite genuine matching peer acknowledgments after stored transcript marks. Both actual acks end in a period. Once the repaired tool is appropriately validated and authorized for use, reconcile through normal `relay.py --sweep`, not hand-edited state. Do not count queued/unverified as delivered.
5. Preserve issue89 until separately authorized PR/review/promotion work. The old deep handoff c671 has historical PR71 review text; this handoff supersedes that stale state.

Still-relevant peers: Codex `w2Q:p3` (one-offs, sid `01a173a2-d7f2-71c1-a68b-9cecbc14f1ad`) acknowledged issue89 ownership and implementation; its final notice record `20261026-195411-4a3a78` is now delivered. ADE lead `e934e0e6-6767-40be-bc72-576254955377` (`LEAD ade-queue-build (PR 59 guard)`) is running in another workspace and presently blocked on a permission/question card: relay --plan refused, no notice sent. Do not bypass; notify when card resolves. Existing relay agent `bb2a32df-81a6-4370-927a-d61717b6e985` (`relay-ack-pr87-pt`) is idle in the receiving workspace; coordinate scope before writing relay.py. Ask new contacts for a named ack (avoid terminal punctuation until parser fixed) through relay only, using --expect-ack when sender self/transcript exists and --ack for delivery. No competing Git transport work was reported.

## Detached jobs

No running task jobs to re-arm. Five historical job records are status=done and all done markers exist; prior results were collected. They have empty owner fields, not this session's open ownership. Do not restart or rerun them. Registry directory is the private artifacts directory plus `jobs/`: codex-adversary-r2.json, prwait-adversary.json, rtk-adversary.json, codex-adversary.json, codex-env.json. Each stores its exact report/done/rearm path. Original codex-adversary record is contaminated: never open its report/log/transcript. The temporary read-only Paseo graft queries finished and were collected. Outgoing source push/relay startup commands must finish before writer ownership transfers. No watcher belongs to this session; do not touch load/Paseo/CFEngine watchers.

## Quick Start

Explicit baton: `/baton /Users/djbclark/.local/state/handoffs/chains/go-followups-20261025/SESSION_LOG.md`.

Use `/Users/djbclark/src/djbclark-ade-ack-period-wt` for edits; inspect `git status --short` and `git log -3` there. Read repository AGENTS.md, current source procedure `skills/paseo-handoff/SKILL.md`, and `skills/peer-relay/SKILL.md`. All peer messages use `/Users/djbclark/src/djbclark-ade/skills/session-finder/relay.py`; --plan is read-only, and delivered is the success word. Incoming ack replies in your transcript must be relayed to the peer, not merely answered in prose. Never use raw paseo send for peer messages.
