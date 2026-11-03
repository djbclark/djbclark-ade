# Paseo switching plugins: what they implement, what the recovery skill must supply

## A. Verdict and inspected state

A1. **Keep switch-provider enabled. Do not enable Continuity automatic failover on this fleet yet.** They are complementary, not interchangeable: switch-provider is a manual native-history converter plus transcript fallback; Continuity is an automatic, daemon-driven fresh-agent handoff. Neither implements complete connected-fleet recovery.

A2. Installed switch-provider is enabled/running; Continuity is absent; Usage Auto Resume is enabled/running. The daemon reports plugins globally enabled. No plugin, agent, scheduler or daemon state was changed in this research. The operator permitted changes conditionally; inspection did not justify enabling automatic Continuity before resolving predecessor ownership.

A3. Evidence scope: current upstream source pins are recorded in `source-checkouts.json`; installed switch-provider server files match its inspected upstream server files byte-for-byte. Snapshots, hashes and full code spans accompany this report. Unit tests were read, not run. No native conversion, crash recovery, daemon restart, quota fault or child-adoption behavior was exercised. Public documentation describes intent; source establishes the narrower implementation.

## B. Switch-provider: useful manual migration primitive

B1. **Implemented — native transcript reconstruction.** For supported Claude/Codex/Pi/OpenCode pairs it reads a saved native session, translates through a common representation, optionally compacts it, writes/imports a fresh target-provider session, and preserves workspace placement on this path. This is richer than sending a small summary. It does not make the target own the old runtime. <sup>[1](#E1001)</sup>

B2. **Implemented — deterministic bounded working context with retrieval references.** Oversized history is compacted with recent turns plus detected edited files, commits and unfinished tasks; line references point to a temporary detailed transcript. The generated compaction prompt tells the target to wait for the user's next request instead of automatically repeating old work. This is a useful anti-replay instruction, but not an enforced side-effect ledger. Long tool blocks, images and reasoning are not universally retained, so “full history” is conditional. Temporary transcripts are not durable canonical task checkpoints. <sup>[2](#E1004) [3](#E1005)</sup>

B3. **Implemented — manual selection and visible old-owner retention.** The picker selects a ready provider/model and explicitly says the old agent keeps running. Retaining it can protect child jobs, but the future skill must establish exclusive write ownership before the target acts. Preservation is not a completed ownership transfer. <sup>[4](#E1022)</sup>

B4. **Missing or risky for unattended fleet use.** The generic Markdown fallback passes `cwd`, not the original `workspaceId`; unlike the native-import branch, exact placement needs verification where several workspaces share a folder. Native import uses an internal daemon-client API and silently tolerates a failed model-setting call. The skill must verify actual workspace, model, mode and capabilities after creation rather than trust the picker result. These are source-level limitations, not reproduced runtime failures on this daemon. <sup>[5](#E1002) [6](#E1003)</sup>

B5. **Important pending-tool limitation.** OpenCode export constructs tool records with completed state and substitutes an empty result when no mapped result exists. That is not proof the original operation completed. A mid-tool quota failure therefore requires external reconciliation before importing history or deciding to rerun anything. Source conversion is not an operation-status authority. <sup>[7](#E1006)</sup>

B6. **Not implemented in the inspected transition code:** automatic quota policy, cross-agent logical routing, durable successor deduplication, writer fencing, ACP/background-job observer transfer, native child adoption or message acknowledgment transfer. Do not disable a useful manual tool simply because these are outside its advertised job; wrap it in the right recovery procedure.

## C. Continuity: meaningful safeguards, incomplete fleet coordination

C1. **Implemented — recovery without the failed model.** Its daemon turn-ended hook classifies failure from codes/messages, error notices and short assistant status text. Canceled turns are skipped and native subagents are excluded by default. It can initiate the handoff while the exhausted model cannot answer; optional LLM summarization is not required. Classification remains heuristic, not a provider error-contract guarantee. <sup>[8](#E1007) [9](#E1012)</sup>

C2. **Implemented — partial duplicate and loop protection.** An in-flight guard prevents concurrent attempts for the same agent within the plugin process. Agent creation supplies an idempotency key and durable chain labels, including source identity and sequence. Per-chain and host-wide breakers constrain repeated switching. These are real improvements over a naive fallback loop. Their presence does not establish a durable migration transaction or prove the daemon's idempotency persistence semantics. <sup>[8](#E1007) [10](#E1008) [11](#E1010)</sup>

C3. **Implemented — useful portable handoff content.** Original/latest user task, last todo list and recent conversation/tool details are included within character budgets. Common credential patterns are redacted. Optional summaries fall back to plain text on failure; optional handoff files are self-ignored in the project. Neither regex redaction nor an ignored file is a complete confidentiality or durability boundary. <sup>[12](#E1013) [13](#E1015) [14](#E1016) [15](#E1017)</sup>

C4. **Only partial rate/quota best practices.** It has provider-level cooldowns and parses some reset times; target selection checks readiness, cooldown and model availability. It does not reserve destination quota or identify actual shared-account pools. The UI's quota display is not an admission gate in the server transition path. No jittered fleet queue appears in that path. <sup>[16](#E1011) [9](#E1012)</sup>

C5. **Host breaker is not a concurrent fleet admission limiter.** It checks the history count before asynchronous creation and increments the count after creation. Multiple different agents can pass before any success is recorded. In-flight locking is per source agent, not a global target-capacity reservation. This is a static race analysis, not an executed reproduction. <sup>[10](#E1008) [11](#E1010)</sup>

C6. **Restart safety is incomplete.** The code explicitly keeps handled/in-flight/cooldown/rate-history state in memory; reload/restart loses it. Chain labels retain some lineage/counters, but there is no shown transactional intent/commit record joining source retirement, target readiness and communications cutover. <sup>[17](#E1009) [10](#E1008)</sup>

C7. **No predecessor fencing or readiness handshake in the transition.** Creation starts the successor with a prompt; the plugin then records and displays success. The inspected function does not verify that the successor understood the handoff or retire the source. Its prompt encourages finishing a mid-step, without an operation ledger to distinguish “not started” from “already completed but receipt lost.” Human-controlled single-agent use and autonomous multi-writer fleet recovery have different safety requirements. <sup>[10](#E1008) [12](#E1013)</sup>

C8. **No child/process/peer adoption.** A subagent tool detail becomes a short description, not a reparented child handle or report subscription. Allowing subagents into the failure hook means they may trigger more failovers; it does not establish parent/child reconnection. The transition code supplies no peer inbox/outbox watermarks, expectation transfer or background-job inventory. <sup>[8](#E1007) [18](#E1014)</sup>

## D. Critical installed interaction: Usage Auto Resume

D1. **Observed code behavior:** Auto Resume persists a job for a concrete agent, rechecks archive/provider/model/message/permission/turn state, claims the job and sends that agent a continue when appropriate. Its gate does not check Continuity lineage or a logical task's successor owner. <sup>[19](#E1018) [20](#E1019)</sup>

D2. **Inferred collision scenario:** the original hits quota; Auto Resume schedules it; Continuity starts a successor in the same worktree; quota resets; the old agent is idle, unarchived and otherwise eligible; Auto Resume continues it. Both can now act on the same task. Creating a successor does not send a new user message to the original, so the original's new-message cancellation check need not protect this case. This interaction is not reproduced here, but follows from the inspected paths. <sup>[10](#E1008) [19](#E1018) [20](#E1019)</sup>

D3. **Decision:** no Continuity installation/enablement now, and no unauthorized disabling of the useful existing Auto Resume plugin. The future skill needs an explicit per-task choice: wait and resume the original, or transfer ownership and retire its pending automatic continuation through supported controls. Keep unrelated agents' resume jobs intact. Archiving is not the first step: inspect children, terminals and outstanding replies before any action that may disturb them.

## E. Connected skills: reuse, with known gaps

E1. Neither inspected plugin repository bundles a `SKILL.md`. A scoped search of ADE and Pi skill files found no dedicated skill mentioning these plugin identifiers. This is bounded discovery, not a claim that no such skill exists anywhere. Plugin installation does not install a fleet-recovery procedure.

E2. **Generic `paseo-handoff`:** reuse its self-contained task brief and provider/profile discovery discipline. It explicitly leaves detachment to the user; workspace placement does not confer top-level ownership or adopt old children. It does not provide fleet discovery, outstanding acknowledgment adoption or a job ledger. <sup>[21](#E1021)</sup>

E3. **ADE `ade-paseo-handoff`:** this has much of the missing operational knowledge: bilateral sibling/child registration, durable role versus instance identity, verified successor acceptance and outstanding relay-expectation transfer. It explicitly documents that transfer can refuse live/missing/ambiguous owners and non-Claude Paseo predecessors without the required finished evidence. A quota-dead source may not satisfy that contract. The new skill must surface that blocker, not fabricate completion or edit expectation records. <sup>[22](#E1020)</sup>

E4. **Do not copy lifecycle rules blindly.** The ADE handoff text includes older top-level/`ParentAgentId: null` retirement guidance, while the generic handoff/current Paseo skill says detach is a user gesture. Astra must reconcile those against the installed public API and current ownership contract. A prompt saying “you are the successor” cannot change actual parentage. No instruction file was modified during this research. <sup>[22](#E1020) [21](#E1021)</sup>

E5. **Other dependencies for the skill:** `session-handoff` for owned durable context and stale-owner checks; `handoff` for detailed context artifacts; `peer-relay`/session-finder for actual verified peer delivery; ACP dispatch records for existing slices and waiter rearming; `model-routing` for independent quota capacity; `ade-paseo-plugin` for trusted-plugin management. These must be consulted as live contracts, not replaced with guessed commands. Snapshot copies of the directly inspected handoff/plugin-management skills accompany the packet.

## F. Contract for Astra's recovery skill

F1. **Entry points:** external rescue of quota-dead agents, cooperative planned transfer, and validation-only/dry-run. Begin with a fleet/task dependency inventory including background/remote workspaces, healthy children, all schedulers and pending messages. Identify real shared quota pools. Do not require dead agents to author a final summary.

F2. **Choose a mechanism per task:** native switch-provider conversion when source/target/session-format constraints fit and uncertain tools are reconciled; controlled Continuity/manual prompt reconstruction otherwise; same-provider native resume when waiting is safer. Neither tool may substitute for task ownership and communications transfer.

F3. **Prepare before execution:** checkpoint task/artifacts/dirty state, claim and owner identity, peer list, outstanding message/ack records, job/child handles, process start identity, operation-status uncertainties and exact next action. Verify target quota/capabilities and create prepare-only behavior where supported. A textual “wait” instruction is not a hard fence.

F4. **Reconcile then commit:** secure exclusive write ownership, adopt/observe surviving work, verify destination placement/runtime settings, transfer supported relay expectations, verify bilateral peer routing and return paths, and explicitly neutralize the old task's automatic continuation. Retire only the intended predecessor once resource retention is safe. Persist the transition so coordinator restart cannot cause blind duplicate creation.

F5. **Unsupported recovery is an output state, not an invitation to improvise.** If a live owner cannot be fenced, a native child cannot be adopted, relay transfer refuses the dead source, or an operation outcome is unknown, preserve resources and report precisely what requires the operator or an upstream API. Do not promise a Markdown skill alone can repair missing runtime primitives.

F6. **Acceptance coverage:** simultaneous fleet failures; duplicate recovery invocations; reload between create and commit; source auto-resume after successful transfer; target quota rejection; live pending tool converted as history; fallback cwd shared by several workspaces; model-setting failure; late peer replies; parentless/parented native children; surviving ACP job; PID reuse; missing report/exit artifact; stale task checkpoint; secrets in historical tool output. Tests must check artifacts, ownership and message receipts, not only successful agent creation. Use CI for code/test work.

## G. Confidence and handoff status

G1. High confidence in the inspected code boundaries and current installed enablement. Moderate confidence in the inferred concurrency/auto-resume collision scenarios until fault-tested. No assurance of txcript fidelity, current beta API compatibility, target-runtime reparenting or end-to-end fleet safety is claimed.

G2. The accompanying Astra brief asks for development of an ADE skill, superseding the earlier design-only brief's intended next phase. No Astra launch is claimed: its previous launch was refused by quota gates. Fresh quota inspection must precede any new dispatch; do not bypass those gates, expand paid fan-out or silently substitute vendors.

## Citation footnotes

1. <a id="E1001"></a>E1001 — Native conversion and compaction create/import a fresh target session. — server/convert.ts (Switch-provider authors), lines 92-132. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/convert.ts#L92-L132>

2. <a id="E1004"></a>E1004 — Deterministic compaction points to a transcript and instructs the target to wait for the next request. — server/compact.ts (Switch-provider authors), lines 215-260. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/compact.ts#L215-L260>

3. <a id="E1005"></a>E1005 — Transcript export paginates projected history but clips long tool blocks and uses temporary storage. — server/transcript.ts (Switch-provider authors), lines 1-58. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/transcript.ts#L1-L58>

4. <a id="E1022"></a>E1022 — Switch provider explicitly tells the user the original agent keeps running. — client/picker.tsx (Switch-provider authors), lines 75-86. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/client/picker.tsx#L75-L86>

5. <a id="E1002"></a>E1002 — The generic transcript fallback creates with cwd but does not pass workspaceId. — server/convert.ts (Switch-provider authors), lines 138-159. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/convert.ts#L138-L159>

6. <a id="E1003"></a>E1003 — Import uses an internal daemon client and silently tolerates model-setting failure. — server/daemon.ts (Switch-provider authors), lines 1-42. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/daemon.ts#L1-L42>

7. <a id="E1006"></a>E1006 — OpenCode export rewrites tool records as completed, even without a mapped result. — server/opencode.ts (Switch-provider authors), lines 99-115. <https://github.com/anh-chu/paseo-plugin-switch-provider/blob/e35f1d4abcc988f0c80c8eeab66bf98372754958/server/opencode.ts#L99-L115>

8. <a id="E1007"></a>E1007 — Automatic continuity watches ended turns, skips canceled turns/default subagents, and locks per-agent attempts. — index.server.ts (Continuity authors), lines 29-68. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/index.server.ts#L29-L68>

9. <a id="E1012"></a>E1012 — Failure classification reads error codes, notices and short assistant status text; parses reset text. — server/classify.ts (Continuity authors), lines 30-97. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/classify.ts#L30-L97>

10. <a id="E1008"></a>E1008 — Continuity creates with an idempotency key, configured settings and chain labels, then records success without retiring the predecessor. — server/failover.ts (Continuity authors), lines 155-199. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/failover.ts#L155-L199>

11. <a id="E1010"></a>E1010 — Chain and host breaker limits exist, but read a completed-failover count. — server/chain.ts (Continuity authors), lines 31-82. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/chain.ts#L31-L82>

12. <a id="E1013"></a>E1013 — Continuity includes the original/latest task, todos and a bounded tail, and advises finishing a mid-step. — server/serialize.ts (Continuity authors), lines 30-63. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/serialize.ts#L30-L63>

13. <a id="E1015"></a>E1015 — Continuity redacts selected common credential patterns. — server/serialize.ts (Continuity authors), lines 194-212. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/serialize.ts#L194-L212>

14. <a id="E1016"></a>E1016 — Summary is optional, uses a helper agent and falls back on failure; the helper is archived. — server/summarize.ts (Continuity authors), lines 25-62. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/summarize.ts#L25-L62>

15. <a id="E1017"></a>E1017 — Optional project handoff files are self-ignored, but are not a durable transition transaction. — server/handoff-file.ts (Continuity authors), lines 1-22. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/handoff-file.ts#L1-L22>

16. <a id="E1011"></a>E1011 — Target selection checks readiness/models/cooldown, not a shared quota reservation. — server/failover.ts (Continuity authors), lines 201-264. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/failover.ts#L201-L264>

17. <a id="E1009"></a>E1009 — Handled/in-flight/cooldown and rate-history state is in-memory and lost on restart. — server/state.ts (Continuity authors), lines 1-18. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/state.ts#L1-L18>

18. <a id="E1014"></a>E1014 — Subagent detail becomes a short type/description string, not an adopted runtime handle. — server/serialize.ts (Continuity authors), lines 150-159. <https://github.com/keefeere/paseo-continuity/blob/063b7e272ee1946f05e9a4845d239821aa02a049/server/serialize.ts#L150-L159>

19. <a id="E1018"></a>E1018 — Auto Resume gates on archive/provider/model/message/permission/turn state, not logical successor ownership. — server/decisions.ts (Usage Auto Resume authors), lines 82-99. <https://github.com/babo-jeonguk/paseo-usage-auto-resume/blob/b1150985c8d62c335c3e3d682b2062138299a5b7/server/decisions.ts#L82-L99>

20. <a id="E1019"></a>E1019 — Auto Resume claims a durable job and sends a continue to its original concrete agent. — server/resumer.ts (Usage Auto Resume authors), lines 376-415. <https://github.com/babo-jeonguk/paseo-usage-auto-resume/blob/b1150985c8d62c335c3e3d682b2062138299a5b7/server/resumer.ts#L376-L415>

21. <a id="E1021"></a>E1021 — Generic handoff guidance includes a self-contained brief and leaves detach to the user. — paseo-handoff/SKILL.md (ADE skills), lines 14-65. <file:///Users/djbclark/.agents/skills/paseo-handoff/SKILL.md>

22. <a id="E1020"></a>E1020 — ADE handoff guidance includes bilateral peer registration and transferring outstanding acknowledgment expectations. — ade-paseo-handoff/SKILL.md (ADE skills), lines 88-142. <https://github.com/djbclark/djbclark-ade/blob/78aa363047e0b34a25bc19542dcbfc9bb5d8ec21/skills/ade-paseo-handoff/SKILL.md#L88-L142>
