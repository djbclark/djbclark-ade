# Central, non-blocking agent questions — implementation plan

Updated 2026-11-17. Status: frontier critique incorporated; implementation is gated on Phase 0 proof, not approved by this document. Queue: Carried 67 in `docs/queue.md`.

## A. Operator requirements

A1. All agent questions must be answered in one central location. No worker-tab visit, worker-local picker, clipboard-copy option or focus-stealing modal is the final interface. Include informational questions, not only permission-shaped decisions.

A2. Asking returns immediately. Only dependent actions stay held; independent ready work continues. If nothing independent remains, the agent may yield. Silence, preselection, recommendation and elapsed time never constitute consent.

A3. Keep ADE/Paseo and its existing plugin host; do not introduce a replacement controller, another daemon, server or port. General guarded ADE/Paseo live changes are authorized, subject to source review, CI, preserved work, rollback and measured runtime acceptance.

A4. Q1/Q2/Q3 are settled and must not be re-asked. Q3 separately authorizes audited declaration-metadata export work in sudo-secretspec, release/install if warranted, safe reconciliation and distinct actual-Jev storage. Blue/Green was a diagnostic canary, not operational consent. Preserve historical provenance without inventing missing old context/owner fields or widening those grants.

## B. Evidence and limits

B1. Progress saves questions but its option buttons copy reply text. Questions please navigates to worker tabs and filters by workspace. Neither meets the new UX. Preserve useful history rather than modifying those outside-ADE plugins for the first slice.

B2. Real Codex asynchronous Blue and Q3 responses completed the matching calls and cleared pending state; the helper performed independent inspection while waiting. This proves that helper path only, not a central interface, Pi production, receiver execution safety or all-provider parity.

B3. Current SDK primitives include paginated agent list/subscription, pending permissions, refresh, send and respondToPermission. Missed timeline events are not automatically replayed. Native response handling can steer before request resolution; no documented caller idempotency transaction spans local persistence and remote effects. Absence/resolution of a native request is not proof that our answer succeeded.

B4. Current public plugin documentation does describe defineAgentTool, AgentToolContext and agent.open.before attachment. Installed Progress uses a deprecated session_open hook plus feature/tool-enable checks. Freeze actual installed types, supported hooks and transport behavior before coding; this is compatibility uncertainty, not an assertion that the public API is missing. Callable tool names must satisfy the actual schema; conceptual dotted names are not proposed API spellings.

B5. The observed Pi 60-second prompt timeout followed by already-processing demonstrates why notifications cannot be assumed harmless, rejected or delivered. Its independent source investigation must inform provider-safe wake handling. Do not repair uncertainty by blindly retrying, switching APIs or choosing steer/followUp automatically.

## C. Minimal architecture and durable contracts

C1. Add one ADE-owned plugin at `plugins/ade-questions/`, with central screen/sidebar, producer tools and backend handlers. Ship enqueue, list/submit and owner read/receipt together, not another persistence-only ask tool. First scope: all workspaces on one explicitly named host; multi-host aggregation remains unverified.

C2. Maintain one authoritative private workflow ledger. Native pending requests are imported transport references/projections with stable source keys; Progress is historical reference, not a competing editable queue. Page/reconcile all relevant agents and snapshots. Ordinary execution/security permissions remain separate and are never auto-allowed by question handling.

C3. Show question/options, origin, current owner, host, decision context/revision, age and status centrally. Render text as inert data, not executable HTML/Markdown or submit-handler instructions. Selection alone is not submission; explicit Submit persists the chosen value. Support allowed free text and multi-question keys without clipboard or tab navigation. Never request secret values as answers.

C4. Bind question ID, host, trusted source-session incarnation, ownerEpoch, decisionRevision, immutable contextHash, stable producer key and dependent-action IDs. Keep a separate monotonically increasing recordVersion: delivery/status changes must not invalidate unchanged consent. Answers carry answerId plus server-verified principal/channel/submission provenance. A payload-supplied actor or request ID is not authority.

C5. Separate producer, operator-submit and owner-read/receipt authority. Derive identities from trusted execution context; prove how UI submission is distinguishable from an agent-accessible client before claiming a human gesture. An agent tool cannot assert that its own payload was a human click. Preserve the existing operator/peer trust policy: legitimate delegated instructions retain their actual trusted provenance, never fabricated UI attribution. If the necessary host capability is absent, hold that approval path pending a supported contract, not a new inter-agent sandbox.

C6. Serialize writers across plugin reload overlap and crashes. CAS covers answer, cancellation, rebind and dispatch admission, not only double clicks. Atomic rename/fsync alone is not CAS. A retry using the same producer key and payload returns the existing question; a different payload is rejected. Persist the dependent-action hold before returning queued, and recover it after restart or a lost enqueue response.

C7. For imported native questions, refresh and validate host, session incarnation, request occurrence/content and current binding before response; preserve provider keys/shapes such as Codex's `Question 1`. Refresh-then-send remains a race unless conditional submission or non-reusable request identity is established. Keep tombstones; unknown continuity is quarantined. Never merge by ID/text alone, synthesize a vanished request or silently overwrite ledger consent with another native UI's answer.

C8. Persist transport intent before sending; track accepted, uncertain and receipt-confirmed separately. Positive evidence must bind the exact answer and request incarnation. Resolution/absence can mean cancellation, competing response or history loss. Ambiguity stays visible/held without blind resend. Native-only consumers lacking receiver dedupe are compatibility observations, not the approved effect-execution path.

C9. Receipt is not execution. Each dependentActionId has immutable actionDigest, answerId, execution intent and independent attempt/outcome evidence. Before effects, the receiver validates current consent/epoch and durably claims that action. Retry effects only through receiver-supported idempotency or authoritative outcome reconciliation; otherwise outcome-uncertain stays held. One answer may authorize several distinct actions, so answer-ID dedupe alone is insufficient. A ledger flag/model promise cannot establish exactly-once effects; that requires an atomic effect/receipt transaction or actual effect-receiver dedupe/proof across restart. This is a first-slice dependency, not later hardening.

C10. Rebind uses CAS against expected ownerEpoch/revision and authenticated transfer provenance. Every action admission checks the epoch; the effect boundary must reject obsolete fencing tokens. If the executor cannot fence, prove old-owner quiescence and no unresolved action before transfer. Do not rebind an in-flight/uncertain action without reconciliation. Transfer an existing answer only when its consent scope permits the owner change; otherwise mark stale for a new central decision. Never guess a successor or wake an archived agent to seek acknowledgment.

C11. Notifications are separate fallible actions: persist wake intent, use only verified provider-safe semantics and distinguish accepted/uncertain/receipt-confirmed. Rechecking a busy flag does not remove its race. Prefer owner reads at natural scheduling boundaries and prove eventual discovery for idle owners without paid polling. A lost wake cannot lose an answer or authorize dependent work.

C12. Preserve private state, consent/action receipts, writer epochs and dedupe tombstones through backup/restore/schema transitions. Stale restored state must not regain old writer authority. Logs/notifications contain opaque IDs/status rather than question bodies, answers or secrets; document retention and access.

## D. Provider and scheduling coverage

D1. Record every supported provider/question kind: enqueue attachment/tool-enable gates, immediate return, durable holds, owner read/receipt, busy/idle discovery, source incarnation and handoff. Include informational questions and questions originating outside the selected workspace. Unsupported/unverified cells remain explicit.

D2. A central viewer cannot make a synchronous producer non-blocking. Implement supported ADE deferred production through installed/versioned APIs; require actual Pi enqueue/read/receipt and scheduling proof. A Codex helper is not Pi parity. Do not interrupt paid active sessions just to inject tools; prove attachment at natural reopen boundaries.

D3. If a required capability needs unavailable/outside-ADE API work, name the dependency and obtain appropriate scope approval. A bounded useful slice may ship with honest limits; the all-supported-agent requirement stays open until every required row passes. Do not silently exclude a provider or build a generic replacement workflow controller.

D4. Until rollout, workers relay decision needs centrally to the lead, continue independent work and hold affected actions. No new worker-local pickers, repeated paid question or recurring model-polling loop.

## E. Phased implementation and exit gates

E1. Phase 0 — before implementation: freeze actual installed signatures plus identity, authority, consent/action state machines, writer/CAS, fencing and producer/scheduling matrix. Resolve the action/receipt crash gap, owner execution fencing, UI provenance and request-incarnation contracts with evidence, not wording alone. The frontier review BLOCKS live dependent-action rollout until these gates are demonstrated.

E2. Phase 1 — after verified exclusive claim transfer: one ADE-hosted enqueue/central-list/Submit/owner-read/receipt slice and one benign receiver-deduplicated action. Enqueue returns immediately with stable IDs/revision/context and persisted hold. Include incarnation binding, CAS, lost enqueue response, notification uncertainty and crash recovery now. Prove an independent step completes before answer while the dependent effect cannot; the explicit answer releases only the bound action, with observable effect/outcome evidence rather than a model assertion. Informational answers need no effect executor; do not broaden this slice to arbitrary privileged actions.

E3. Phase 2 — two workspaces, actual Pi and each required provider; concurrent clients, restart/reconnect, old owner resuming after transfer, cancellation/rebind races, missing/reused native requests, lost responses and busy-owner wake ambiguity. Acknowledgment loss never authorizes a second effect. Overall completion remains open for unsupported cells.

E4. Phase 3 — independent exact-head source/security review, CI/bot gates and rollback artifact; then normal guarded ADE plugin install/enable under the existing authorization. Update plugin README, supported-version requirements, catalog and matrix with actual shipped scope. No installed-file hotpatch or indiscriminate agent restart. Focused tests require global lease and full-path bg/exact-root admission; heavy/full suites run in CI.

E5. Stop affected actions on forged/unknown provenance, stale owner, duplicate effect, unknown incarnation, uncertain delivery, corruption or unenforceable hold. Independent work continues unless the shared authority/ledger is compromised. For live UX evidence use genuine future decisions or separately authorized harmless canaries; never re-ask Q1/Q2/Q3.

E6. Rollback fences dispatch/execution admissions before any drain. Drain only positively identified safe intents, never uncertainty. Preserve/back up ledger, epochs, tombstones and action receipts; restore compatible readers without replaying sends. If downgrade is unsafe, retain a compatible central read-only recovery view and disable writes. Never erase answers, auto-approve, revive unrelated agents or fall back to blocking worker cards.

## F. Acceptance and regression evidence

F1. Two agents in different workspaces post questions on one central screen and complete independent steps before answers. Each affected action remains held across restart. Include the Pi lead and every required provider before claiming full completion.

F2. Explicit in-place Submit persists the answer with correct provenance and delivers only to its bound current owner. No tab jump, clipboard write, focus steal or preselected consent. Match receiver receipt and actual action outcome, not tool acceptance/counts alone.

F3. Cover enqueue committed-but-result-lost retry, mismatched producer key/payload, multiple questions/free-text keys, concurrent answer/cancel/rebind/dispatch, wrong host/actor/session, old-owner resumed execution, request reuse/tombstones and execution-permission exclusion.

F4. Inject crashes before/after durable answer, remote acceptance and effect/receipt. Reconcile snapshots/history plus receiver outcomes. Demonstrate no blind duplicate effect or stale approval, visible uncertainty and a recovery path. Disclose remaining remote exactly-once limitations rather than infer guarantees from a flag.

F5. Preserve completed work and historical decisions through migration/rollback. Do not store question bodies/answers in public Git or broad notifications. Credential collection remains within the managed credential boundary.

## G. Related work remains separate

G1. Carried 65 covers general network/provider/transport continuation for every agent, including the lead. Audit deployed recovery before changing it; distinguish interrupted, still-running and completed turns, preserve delivery uncertainty, and prove network/daemon/client reconnect. The Pi prompt-timeout/busy and wrong-target archive/clean-exit reports are concrete regression cases. No fixed quota reserve is introduced here.

G2. Carried 66 covers zero-model-token monitoring of trusted bot and verified human reviewer events, including conversation comments and CI approval-needed status. Scripts wake the correct owner; external text remains untrusted data.

G3. Carried 68 requires reliable, observable quota-probe freshness, not acceptance of stale readings. Keep current limits pending evidence; a proposed 20-minute limit is not selected, and a fresh Costs fetch cannot renew old measured cash. Q3 sudo-secretspec repair, aiuse release and held PR771 retain separate gates.

## H. Evidence references

H1. [Paseo SDK reference](https://paseo.sh/docs/sdk/reference.md), [SDK events](https://paseo.sh/docs/sdk/events.md), [plugin reference](https://paseo.sh/docs/plugins/reference.md) and [plugin hooks](https://paseo.sh/docs/plugins/hooks). Re-verify installed/versioned contracts before implementation.

H2. Private retained reports contain the native Blue/Q3 receipts, phased draft, frontier critique and Pi causal timeline. They prove only their stated cases, not implementation/runtime acceptance. The pre-frontier source draft is preserved privately; this revision incorporates all seven blocking design findings and the public-API documentation correction without claiming their runtime gates have passed.
