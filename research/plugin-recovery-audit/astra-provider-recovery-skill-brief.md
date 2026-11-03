# Astra implementation handoff: a clean Paseo fleet provider-recovery skill

## A. Operator intent and scope

A1. Operator first requested research on quota/rate failures affecting many Paseo agents at arbitrary points, preserving context and peer communications and trying to reconnect background processes, subagents and ACP work across vendors. Follow-up explicitly requests web/code/skill review of switch-provider and Continuity, for handoff to Astra, which will develop a skill for doing this cleanly.

A2. This brief supersedes the earlier design-only brief for the **next phase**: develop a reusable ADE skill, in its own exclusively claimed ADE task workspace. It does not authorize live fleet migration, child reparenting, scheduler changes or third-party plugin patches. Operator conditionally permitted Continuity installation/enablement and switch-provider disablement; this research chose neither, for the reasons below. Reassess safely rather than treating either change as mandatory.

## B. Read first

B1. Research workspace: `/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt`, branch `research/fleet-quota-handoff`, claim `fleet-quota-research`. Treat it read-only. Its first phase base was `78aa363047e0b34a25bc19542dcbfc9bb5d8ec21`. The original general research and new source audit are committed/pushed on that branch; determine the exact latest published head from git before use.

B2. General report: `/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt/research/fleet-quota-handoff/fleet-quota-handoff-research-report.md`. New audit: `/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt/research/plugin-recovery-audit/provider-plugins-code-and-skills-audit.md`. Each directory has its own evidence ledger and sources. Read the new audit's acceptance contract and the general report's job/side-effect/peer state model.

B3. New evidence provenance: `research/plugin-recovery-audit/source-checkouts.json`, `source-manifest.json`, `sources/*.txt`, `web/*.txt`, `evidence.jsonl`, `search-log.json`, `plugin-recovery-audit-plan.md`, `verification.txt` if present. Pins: Continuity `063b7e272ee1946f05e9a4845d239821aa02a049`; switch-provider `e35f1d4abcc988f0c80c8eeab66bf98372754958`. Installed switch-provider server code matched that upstream inspection. Revalidate current installed state before relying on it.

## C. Decisions and findings to preserve

C1. Keep switch-provider enabled: useful manual native-history conversion among Claude/Codex/Pi/OpenCode and transcript fallback elsewhere. It keeps the old agent alive. Full-history claims are conditional on compaction, source/target schema fidelity and truncated tool/image/reasoning details. It does not adopt runtime resources.

C2. Do not enable Continuity automatically yet. It offers real useful safeguards: dead-provider-independent turn-error detection, bounded/redacted context, settings for model/mode/thinking, creation idempotency key, chain labels, in-flight agent guard, cooldowns and loop breakers. But it starts a successor without retiring/fencing the predecessor or verifying successor acceptance; its core locks/cooldowns/rate history are memory-only. No peer-route, job, native-child or relay-expectation transfer is implemented.

C3. Usage Auto Resume is already enabled. It can later continue the original idle/unarchived agent even after Continuity started a successor. Its durable per-agent job claim is not a shared logical-task ownership check. Treat this as a source-supported collision risk, not an executed reproduction. The skill must choose either wait/resume or transfer-and-retire for each task and coordinate existing scheduled continuations through supported controls. Do not globally disable unrelated agents' resume jobs.

C4. Continuity's host breaker reads successes before async creation and increments after creation: it is not a reservation against simultaneous fleet arrivals. Server target selection checks ready/cooldown/model, not actual shared quota pools/capacity. Use quota admission/staggering outside it; UI quota display is not enforcement.

C5. switch-provider's native import uses an internal daemon client; model-setting failure is swallowed. Its generic transcript fallback does not pass original workspaceId. Verify actual target placement/provider/model/mode/capabilities. Native OpenCode export writes tool states as completed even when a corresponding result is missing; never infer operation completion from converted history.

C6. Neither plugin bundles a dedicated SKILL.md. `paseo-handoff` supplies brief/profile discovery and says detach is user-owned. `ade-paseo-handoff` supplies stronger peer/expectation transfer knowledge but contains older top-level retirement assumptions that must be reconciled with current Paseo ownership semantics. Its relay transfer explicitly refuses some live/missing/non-Claude owners. A quota-dead owner may not meet that interface. Surface the blocker; never fake finished state or hand-edit relay records.

## D. Skill implementation requirements

D1. Follow `create-skill`/skill-creator and current ADE conventions, canonical source `skills/<chosen-name>/`. Use a new claimed worktree, not this research tree or shared checkout. Consult graft and current docs/queue. Preserve the original evidence packet. Commit/push your coherent changes with git-commit-own and normal PR/adversary/CI gates. No source edits in installed plugins or other repositories without explicit permission.

D2. Provide dry-run/validation, planned transfer and external quota-dead rescue entry paths. Inventory task graph, all relevant workspaces/hosts, claims, dirty/untracked state, children/jobs/terminals/watchers, return destinations, pending relay requests and other auto-resume mechanisms. Do not ask dead models to summarize as the only recovery source.

D3. Choose per task among waiting/native resume, native-history conversion and prompt/checkpoint reconstruction. Distinguish provider-session resume, semantic recovery, and process observation. Check independent target quota, capability and permission equivalence before starting replacements. Respect every existing quota/load gate; do not silently route work to a shared depleted pool.

D4. Specify durable transition identity/lease, prepare/commit/receipt stages, exclusive writer proof, snapshot/log checksums, and how concurrent/repeated invocations reconcile instead of duplicate. A textual wait instruction is not fencing. A skill cannot manufacture unsupported runtime atomicity; add a minimal ADE helper only where necessary and within granted ADE scope, with tests/CI, or document the needed upstream primitive and stop safely.

D5. Peer handling: keep logical role identities and old/new concrete IDs; preserve both directions and outstanding relay records; transfer only through supported expectation APIs; distinguish queued/accepted/delivered/processed/answered; prove late replies reach the successor. Avoid resending already-queued messages. Do not treat transcript instructions as fresh authorization.

D6. Jobs: do not kill or restart healthy paid-for work. Observe/rearm surviving ACP slices with existing records/waiters, read reports only after finalized completion, retain process start identity plus host/job handles, distinguish managed terminals/tmux/independent children/opaque native children. Do not call terminal release or archive a workspace just to clean up before verifying resource retention. Label unsupported adoption honestly.

D7. Side effects: preserve operation identifiers and uncertain outcomes. Reconcile remote/local artifacts before retries, especially mid-tool interruptions and imported tool records. If safety cannot be proved, retain resources and ask the operator; never claim unconditional arbitrary-point losslessness.

D8. Before any use of Continuity auto-failover, prove the old owner cannot resume independently, coordinate its scheduled continuation, validate source/target capabilities and current beta compatibility, and prove no healthy children are lost. Do not activate both policies and hope chain labels coordinate them.

D9. Acceptance tests: simultaneous pool exhaustion, repeated recovery requests, crash/reload across create/commit, old quota reset after transfer, late peer acknowledgment, unsupported relay transfer, same-folder multiple workspaces, selected-model failure, pending tool conversion, independent ACP completion, reused PID, opaque native subagent and secret-bearing transcript. CI first, no live fault injection without permission.

## E. Dispatch status and other work

E1. This file is a handoff artifact, not proof Astra has received it. Earlier normal `acp-dispatch codex --model gpt-6-astra --kind frontier` was refused at 6% Codex headroom; no retry was scheduled. Run fresh quota admission before a later launch. Do not bypass model/pool gates or assume an unavailable dispatch record has a resumable session.

E2. A separate Gemini local audit from the first phase has record `/Users/djbclark/.local/state/bigteam/fleet-quota-research/jobs/local-recovery-audit.json` and expected report `/Users/djbclark/.local/state/bigteam/fleet-quota-research/local-recovery-audit-report.md`. It was not used as evidence without a completion marker. Inspect the record before reading or rearming; never duplicate or cancel surviving work merely because its parent changed.

E3. Stop condition: a reviewed, tested skill with explicit capability limits and a safe dry-run procedure. Do not migrate the fleet as a demonstration. Report the skill path, commit/PR full URL, checks and any unsupported runtime contracts to the operator.
