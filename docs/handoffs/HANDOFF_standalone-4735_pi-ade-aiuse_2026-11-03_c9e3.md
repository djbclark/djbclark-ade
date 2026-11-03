---
schema_version: 1
handoff_id: c9e3
parent_handoff_ids: []
lineage: none
chain: [standalone-4735]
repo: djbclark-ade
workspace: djbclark-ade-pi-first-class-wt
branch: pi-first-class
head_sha: 3a95fa2df0f76ce1e0d0cbe61ccbbc135345a138
created_at: 2026-11-03T10:01:53-05:00
writer: pi
---

# A. Handoff — finish Pi/ADE integration and fully release aiuse

## B. The Goal

B1. Make Pi first-class wherever OMP parity is appropriate in ADE: ACP/routing, shared skills without duplicate warnings, history/fleet/relay/backup, safe native naming/lifecycle controls, and subagent model/thinking configuration. Classify all OMP references, distinguishing intentional provider differences from missing integration.

B2. Add independent Pi/OpenAI API accounting to aiuse, with scope `codex-api`, never borrowing Codex subscription capacity or treating API costs/spending limits as prepaid balances. Keep OMP's stable machine identifiers while displaying scope `claude-api`; preserve SCOPE on explanatory/gated rows.

B3. The operator explicitly requires **a full aiuse release and artifact/install verification when finished**, not just a branch push, PR, or tag. Fix incidental findings too. Latest instruction supersedes continuous implementation: get to a good handoff boundary, then hand off. Do not schedule more paid work merely to polish this checkpoint.

## C. Where We Are

C1. **NOT COMPLETE. No PRs, merge, deployment, live duplicate-skill cleanup, or aiuse release were performed.** aiuse integration is now clean, pushed, and full Linux CI green. ADE slices are separately pushed but independently BLOCKed. All native subagent invocations have returned: 20 completed successfully and one quota-failed invocation across four waves; no native workers remain running. Three earlier Gemini research jobs have completed reports/markers. Do not rerun completed work.

C2. Artifact root is `/Users/djbclark/.local/state/bigteam/pi-first-class-20261103/`. Read `lead-state.md` plus this document; this document supersedes its older checkpoints. `handoff-repo-audit.json` captures all nine worktrees, branch/head/status and 15-commit logs. It was gathered before the handoff-only commit, so the main ADE head in that audit is its content parent, not the eventual handoff commit.

C3. Owned workspaces, all under `/Users/djbclark/src/`, with active exclusive claim IDs `pi-20261103-...`:

C3a. `djbclark-ade-pi-first-class-wt`, branch `pi-first-class`, head `3a95fa2df0f76ce1e0d0cbe61ccbbc135345a138` before this handoff commit; claim `pi-20261103-djbclark-ade`. Checkpoint commits worker profiles and the earlier native-ID underscore repair. **Only remaining dirty files are `.claude/settings.json` and `.cursor/hooks.json`, not mine: preserve and do not stage/reset/stash them.** Source reference checkout's unrelated `.gitignore` was also preserved. Main cwd `/Users/djbclark/src/djbclark-ade` belongs to other chains: do not steal its pointer or develop there.

C3b. `aiuse-pi-api-wt`, branch `pi-api`, head **`a24366409cc5e7670bb0b874c20bd6ed0e33b8ca`**, clean; claim `pi-20261103-aiuse`. All cost/grant corrections integrated. Independently verified [full CI 41657521860](https://github.com/djbclark/aiuse/actions/runs/41657521860) is SUCCESS at that SHA; saved log reports **1,705 tests passed**, all-files pre-commit and formatting passed. No independent adversary review of this final integrated head yet.

C3c. `aiuse-pi-costs-fixes-wt`, branch `pi-costs-fixes`, head `03a378eb08695285e926791a11bdb073763eca7b`, clean; claim `pi-20261103-pi-costs-fixes`. Integrated into pi-api; retain as evidence, don't reapply. Its full CI 41592555399 passed.

C3d. `aiuse-pi-grants-fixes-wt`, branch `pi-grants-fixes`, head `1ec55646a1399ff3cd4b12eda412839e403f7268`, clean; claim `pi-20261103-pi-grants-fixes`. Integrated into pi-api. Its old CI failed only on the scope assertion owned/fixed by the other slice; this is confirmed from failed logs, not an outstanding integrated failure.

C3e. `djbclark-ade-pi-native-controls-wt`, branch `pi-native-controls`, head `ddf77aa7f816691ef2beb8714d7924df41de949a`, clean; claim `pi-20261103-pi-native-controls`. [CI 41593031134](https://github.com/djbclark/djbclark-ade/actions/runs/41593031134) FAILED: one non-isolated OMP regression test, 9,997 passed/27 skipped. Production fixes reviewed positively, but scoped verdict remains BLOCK; see D3.

C3f. `djbclark-ade-pi-skill-cleanup-wt`, branch `pi-skill-cleanup`, head `ab8f33188b3ce947fb1402acd4ebfece8ba1380c`, clean; claim `pi-20261103-pi-skill-cleanup`. [CI 41592773639](https://github.com/djbclark/djbclark-ade/actions/runs/41592773639) SUCCESS; scoped review still BLOCK; see D4.

C3g. `djbclark-ade-pi-dispatch-fixes-wt`, branch `pi-dispatch-fixes`, head `2306ac10e167a2681b6e2c199262c23ac2f3ad4a`, clean; claim `pi-20261103-pi-dispatch-fixes`. [CI 41587865976](https://github.com/djbclark/djbclark-ade/actions/runs/41587865976) SUCCESS, scoped review BLOCK; see D1.

C3h. `djbclark-ade-pi-history-fixes-wt`, branch `pi-history-fixes`, head `fa4c77a98d2ea777100c921588e2b2d49ae30f25`, clean; claim `pi-20261103-pi-history-fixes`. [CI 41588018794](https://github.com/djbclark/djbclark-ade/actions/runs/41588018794) SUCCESS, scoped review BLOCK; see D2. Its `nativeid.py` and tests overlap the main lead's now-committed underscore checkpoint: integrate carefully, don't blindly replay/delete either side's paid work.

C3i. `djbclark-ade-pi-subagent-invocation-wt`, branch `pi-subagent-invocation`, **WIP head `2d5f30d72fbf84cf4b5d582ad3e052930881219c`**, clean after lead checkpoint; claim `pi-20261103-pi-subagent-invocation`. Worker quota-failed after writing partial `pi/extensions/subagent/{index.ts,agents.ts,config.ts,test-invocation.mjs,package.json,LICENSE}` and `tests/test_pi_subagent_invocation.py`. Lead preserved these in an explicitly WIP commit and pushed; **unreviewed, untested, unfinished, not installed**. `astra-subagent-invocation-report.md` remains `STATUS: working`, no `.done`: this is a failed delivery, not a completed report to reconstruct or silently approve.

## D. Remaining Verified Blockers

D1. **Dispatch**, `astra-dispatch-review-report.md`: P1 pass-through `--acp-arg` can append a replacement `--model` after the billed/admitted primary model. Validate the effective final identity or reject all identity-changing forms, including argparse abbreviations, in normal/deferred/resumed/legacy paths before paid preflight/spawn. P2 resumed records lose the admitted 10% minimum because construction omits `min_headroom`; runner falls to the 1% floor. Persist and recheck the actual minimum. Current model allowlist only covers `openai/gpt-6.1-sol` and `openai/gpt-5.4-mini`, intentionally independent from Codex subscription.

D2. **History/fleet**, `astra-history-review-report.md`: P2 native ID + cwd does not prove exact Pi identity across custom stores, even with one indexed candidate; require verified file/storage scope, otherwise LIVE? and don't suppress other-root history. P2 target parser loses which flag supplied a value: `--session-id daily.jsonl` is miscast as a file; relative `--session` targets are incorrectly resolved against post-resume/tool cwd. Preserve kind/flag and don't fabricate absolute identity. Exact-file resume, file-scoped DB keys, underscore fix and positive tty/foreground proof otherwise reviewed well.

D3. **Native controls**, `astra-native-controls-review2-report.md`: production safety fixes close prior runtime findings. But `tests/test_pi_native_controls.py` sets AUTORENAME_STATE_DIR while imported autorename constants ignore it; tests write real `~/.local/state/autorename/omp` or sidecars and fail before exercising selection. Monkeypatch each imported module's STATE_DIR, OMP_DIR and fallback OMP_SESSIONS into the temporary fixture, keeping selector/writer paths consistent. Do not just mkdir parents or mock selection away. Obtain exact-new-head CI/re-review. **External automatic Pi compaction intentionally always refuses:** installed public API cannot prove main editor is active rather than a native selector. Safe naming remains; don't remove the fail-closed gate to manufacture parity. Trusted private state-path ownership is a documented precondition, not enforced same-user IPC security.

D4. **Skill cleanup**, `astra-skill-cleanup-review2-report.md`: prior URL/project-shadow/permission findings fixed. P2 Linux inode flags aren't `st_flags` or xattrs; atomic replace can strip `chattr +d`/other flags. Add explicit conservative Linux flag probing of original and temporary inode or refuse when policy cannot be proven, with regressions. **Additional real Mac limitation:** this installed Python lacks `os.listxattr`; current apply/undo refuses every write safely. Actual macOS cleanup requires bounded native xattr/ACL support or a documented unsupported result; don't claim Linux mocks prove Mac behavior. Never delete native/shared skills. No live settings were changed.

D5. **Subagent overrides:** required precedence is invocation > frontmatter > Pi default, independently for model and thinking in single/parallel/chain. Pass effective `--model`/`--thinking`, report values, validate effort, preserve abort/concurrency/project consent, test defaults/overrides/provider namespaces. Canonical ADE WIP is preserved but incomplete. Installed `~/.pi/agent/extensions/subagent/index.ts` remains official example; agents.ts parses thinking but index ignores it. Root project hit **enforced OpenAI spend limit**; do not retry paid native Astra calls or bypass with credentials. Choose a verified eligible governed route after checking quotas, or ask operator about funding. Source worker read docs before failing; no trustworthy final implementation report exists.

D6. Final aiuse adversary/security review, PR/merge, main test+Semgrep, full release and deployment remain. All ADE changes need integration, final-head tests/review, real-number changelog fragments and protected-master PR merge. No old-head APPROVE or green CI permits merging new heads.

## E. What We Tried

E1. External strong-code routing initially had no eligible pool. User clarified native Pi subagents may use Astra; installed static user profiles and verified actual `PI_PROVIDER=openai`, `PI_MODEL=gpt-6-astra`, `PI_REASONING_LEVEL=high`. This worked for 20 completed invocations, then the next hit enforced API spend limit. Do not claim unlimited capacity or retry blindly.

E2. Native project agent lookup is anchored to the parent's cwd; tool `cwd` sets child cwd only. First cross-project project-scope lookup failed with no agents. User-scope profiles resolved it; this distinction is recorded in `~/.pi/agent/AGENTS.md`. Source profiles now live in lead ADE `.pi/agents`, installed copies in `~/.pi/agent/agents`; runtime claim `pi-20261103-astra-profile` covers that agents directory. Model suffix `:high` enforces actual effort despite missing thinking propagation.

E3. Initial billing research incorrectly assumed no usable OpenAI billing credential. Corrected after CodexBar successfully returned USD 2.8000538 organization costs, source admin-api. Existing cost reporting needs no new key; **cost is not balance/funding type**. Optional direct grant refresh still needs managed OPENAI_ADMIN_KEY and operator-verified anchors; never read auth stores or log secret bodies.

E4. Some aiuse CI failures were obsolete assertions: scope now precedes gated notice, and a test claiming a newer grant used an equal timestamp. Strengthened tests, not weakened financial guards. Integration additionally fixed cached OpenAI aliases escaping multi-account ambiguity counts; final full CI is green.

E5. `git-commit-own` commits but does NOT push. Earlier CI dispatch 422 was an unpushed workflow_dispatch change, fixed by explicit push. Checkpoint pushes now explicitly executed. Do not repeat completed CI/work merely because an older error log exists.

## F. Key Decisions

F1. Pi API and Codex OAuth are separate identities; spend-only Pi has no available quota pool. OMP stable key/family stays unchanged; display scope changes only. Grants require verified anchors, monotonically safe locked updates, explicit reconciliation, and ambiguity fail-closed. Multiple Pi accounts must not each inherit an unbound wallet.

F2. ACP Pi supports only `--perm all`: thinking modes aren't permission enforcement; deny/read-only refuse. `pi-acp` installed and no-prompt model/effort selection probes succeeded, but no paid prompt canary or final deployed governed route is verified.

F3. Reversible exact skill exclusions only after complete bundle/runtime policy checks; preserve other TUIs. Safe refusal beats unsupported APIs, heuristic compaction focus or fabricated live session identity. All source development in exclusive claimed worktrees, heavy tests in Linux CI.

F4. Native profiles are not a substitute for per-invocation overrides; installed behavior must be distinguished from unmerged branch code. No supported native Pi reset/successor route has been verified. Do not send `/new` through inherited herdr/Paseo or guess a host based on environment.

## G. Decisions

- [decision] Keep Pi OpenAI API independent of Codex subscription; rejected: reuse OAuth quota; because billing and allowances differ.
- [decision] Refuse external Pi compaction without authoritative public focus evidence; rejected: empty-editor/idle/prompt-event heuristic; because built-in selectors bypass it.
- [decision] Preserve quota-failed source as WIP; rejected: discard or call it complete; because paid work is valuable but unverified.
- [ruling] "If you make changes to aiuse when done do a full release" (djbclark, 2026-11-03)
- [ruling] "Also fix any issues you may find while doing this work even if not directly related to the work" (djbclark, 2026-11-03)
- [ruling] "Get to a good handoff point, then hand off" (djbclark, 2026-11-03)

## H. Relations

- decided_in [[HANDOFF_standalone-4735_pi-ade-aiuse_2026-11-03_c9e3]]

H1. No parent handoff: this task started in the present native Pi session and only internal checkpoints preceded this formal Tier 2. Existing unrelated handoffs/pointers were not adopted or overwritten.

## I. Evidence & Data

I1. All reports are under the artifact root in C2. Start with `astra-aiuse-integration-report.md` (green integrated head + full release checklist), four latest ADE review reports named in D, and `astra-subagent-invocation-report.md` (unfinished). Prior `astra-*-fixes-report.md`, `astra-*-ci-repair-report.md` and `astra-*-repair-report.md` explain implementation decisions; `.done` exists for completed reports, not the quota-failed one. Saved `<run-id>-status.json` and CI logs provide observed results. No local heavy tests/builds ran.

I2. `omp-parity-classification-report.md` is completed 185-path Gemini research: 77 parity-supported, 11 gaps, 23 intentional differences, 69 historical, 5 proposed rulings. **Not authoritative:** lead only read executive/gap sections, not every table row; some conclusions are wrong/outdated. Its claim of no non-repository maintenance path is false: `ade_claims.py new --no-pointer` works for exact runtime files and is documented by cleanup source. Its identical-Pi/OMP-API/symlink suggestion is unsafe; dedicated bridge required. Its suggested PICODE marker is not the documented Pi marker. Already-authorized native Astra reviews and chosen JSON/PAYG semantics don't need invented new policy questions. Reconcile actual remaining `usage_sources.py`, generated secretspec manifest, btww/prompt-line and lifecycle gaps against current source before declaring parity complete; do not blindly implement terminal scraping.

I3. Inventories: `ade-omp-occurrences.json` (944 hits/126 files), `aiuse-omp-occurrences.json` (866/59). Initial read-only reports `ade-inventory-report.md`, `aiuse-research-report.md` are completed; do not rerun. Official Costs reference `openai-costs-doc.md/json`; sanitized billing evidence `codexbar-openai-verification.json`. Canonical bounded-read guidance is already committed in ADE skills/graft and setup-modern-cli; long reports require byte budgeting, not merely line counts.

I4. Live changes: pi-acp installed; static native Astra profiles installed; narrow Pi instructions updated. No duplicate exclusion, bridge install/reload, direct grant refresh, credential changes, full release or promotion. `~/.pi/agent/settings.json` originally `{}` and intentionally not cleaned yet. `~/.pi/agent/AGENTS.md` priority remains: remove only after real implementation/testing/install and memory update.

## J. Operator Feedback and Dependent Peer

J1. User authorized both repositories, useful subagents/web research, native Astra/high parallelization, incidental fixes and full aiuse release. Do not bypass depleted subscription gates or enforced API limits. Preserve other agents' work and all completed paid branches; never stop their workflows to hand off.

J2. **Fleet-migrate waits on actual Pi completion.** Target `ebd6ed1a` / Paseo `ebd6ed1a-4898-4ecf-af3a-63376530ef81`. NOT COMPLETE status and exact `ack pi-integration-ready-1103` were verified delivered through relay.py; peer returned `ack w38:p8`. See `dependent-fleet-migrate.md` and `fleet-migrate-reply-{status,ack}.log`. No ack loop. Successor MUST proactively notify peer when genuinely complete with final commit/PR URLs, landing, blockers, verified governed launch and exact model/thinking support. Do not unblock fleet-migrate from this handoff.

## K. Where We're Going

K1. **FIRST ACTION:** read `astra-aiuse-integration-report.md` and the four latest ADE review reports, inspect `handoff-repo-audit.json`/actual git state, and check available quota with `aiuse --available --json` before choosing any new worker/successor. Do not retry the spend-exhausted Astra profile. Establish exclusive ownership/adopt claims through supported ADE tooling; predecessor will schedule no more work after this handoff.

K2. Repair isolated native-controls test, dispatch effective-model/minimum bugs, history identity ambiguity, and skill-cleanup metadata/platform gap in disjoint worktrees. Preserve current code; collect final-head CI and independent re-review. Resume WIP model/thinking source only with a quota-eligible route; validate all modes and defaults before normal installation. Remove stale priority only after complete proof.

K3. Review final aiuse a243664 head independently, integrate any justified fixes with full CI, open appropriate PR, verify main tests AND Semgrep, then execute full release. Version currently 3.13.2; recheck. Release helper runs local tests/builds, raw commits, gh run watch and Homebrew/live probes, so do NOT invoke blindly under CI-first rules. `astra-aiuse-integration-report.md` C1-C12 enumerates exact commands/targets and the need for compliant CI release orchestration or explicit operator exceptions. Release includes GitHub tag/assets, PyPI OIDC publish, canonical formula plus `djbclark/homebrew-aiuse`, hashes, CI install/import/version smoke, and authorized Homebrew install/PATH verification. No token reads or invented funding. A push/tag alone is not done.

K4. Integrate ADE owned slices carefully (nativeid/test overlap), add real-PR-number changelog fragments, independent final-head security/adversary markers, full Linux CI, protected-master PR/squash with reviewed SHA. Promote/install by normal path, verify native naming, duplicate catalog behavior and actual launch/config selection, not just source presence. Any live Pi reload must not discard an operator draft or affect an ancestor.

K5. Reconcile audit differences, disclose intentional limitations, verify all release/deployment artifacts, update durable memory, remove completed priority, then send verified completion to fleet-migrate. Never claim completion merely because a subagent returned exit 0.

## L. Detached Jobs

L1. No active native subagents; all returned. Quota-failed source invocation is NOT running and has no final report marker. Its paid partial files were checkpointed in C3i. No CI or agent was cancelled.

L2. Three legacy records exist under artifact-root `jobs/`, owner is empty and no closed field. All reports AND done markers exist. They are **finished, not jobs to relaunch**: `ade-inventory.json`, `aiuse-research.json`, `omp-parity-classification.json`. Their rearm command pattern is `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait JOB_JSON REPORT_MD.done`; corresponding report basenames are `ade-inventory-report.md`, `aiuse-research-report.md`, `omp-parity-classification-report.md`. Do not mutate unknown-owner expectations or rerun their paid commands. No surviving waiter is required for completed markers.

L3. Handoff checkpoint background process completed successfully; `handoff-lead-checkpoint.rc` and `handoff-partial-subagent.rc` are both 0 (commit AND explicit push). Logs preserved. Final handoff commit/push and Tier 1 results should be verified separately in `handoff-finalize.*` artifacts if present. No assumption that session children survive retirement.

## M. Quick Start

M1. Canonical Tier 1: `/Users/djbclark/.local/state/handoffs/chains/standalone-4735/SESSION_LOG.md`. It lists all nine task workspaces and their actual final anchors. Follow the owner protocol; do not resume a similarly named unrelated chain in the shared checkout. The predecessor explicitly hands this task on and will make no further source changes after final handoff confirmation.

```bash
cd /Users/djbclark/src/djbclark-ade-pi-first-class-wt
git status --short
git log -3 --oneline
cd /Users/djbclark/src/aiuse-pi-api-wt
git status --short
git rev-parse HEAD
gh run view 41657521860 --repo djbclark/aiuse --json headSha,status,conclusion,url
aiuse --available --json
```

M2. Resume prompt: read this handoff and Tier 1, verify ownership/claims and quota, then continue K1-K5. User requires full aiuse release and incidental fixes. No work may be discarded. Do not use this native session's inherited host to reset or fabricate a successful successor launch. Document-only fallback is required if no verified governed successor route is available; report the limitation honestly.
