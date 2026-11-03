# Recovering a quota-hit Paseo fleet across vendors

## A. Recommendation and guarantee boundary

A1. **Recommendation — inference:** build a provider-independent recovery coordinator around durable task, message, and job records. Evaluate Paseo Continuity as the existing single-agent transition mechanism before inventing another one. Do not equate “a new agent received a transcript” with “the connected fleet resumed correctly.”

A2. **Source claim:** Continuity already creates a fresh fallback agent in the same workspace, with chain metadata and a bounded projected timeline, without asking the exhausted provider to produce a handoff. Its catalog describes task, latest request, task-list and recent tool-activity transfer; it excludes subagents by default. These are useful, but neither opened page establishes transactional fleet migration, peer-address rewriting, or runtime/child adoption. <sup>[1](#E0001) [2](#E0002) [3](#E0003) [4](#E0004) [5](#E0022)</sup>

A3. **Limit — inference:** an unconditional “no context loss at an arbitrary instant” guarantee is not credible. Private/unpersisted reasoning, truncated history, unsaved child state, and already-destroyed runtime resources cannot be reconstructed reliably. The achievable contract is: preserve all durably recorded task state; expose uncertain operations; never silently rerun a possibly completed side effect; maintain logical communication continuity; explicitly classify what could not be recovered.

## B. Classify the incident before moving the fleet

B1. **Fact:** a rate error and exhausted quota need different treatment. OpenAI distinguishes pacing errors from billing/spend/quota failures, which retries do not repair. Retry timing should respect `Retry-After`; otherwise use bounded exponential backoff with jitter. These API semantics inform the design but do not establish the exact error behavior of every subscription CLI. <sup>[6](#E0016) [7](#E0017)</sup>

B2. **Recommendation — inference:** group affected agents by the actual shared account/pool, not just displayed model or vendor name. An alternative model may draw the same depleted pool. Persist failure class, scope, observed error, reset/retry time, confidence and freshness. Never change billing or credentials automatically.

B3. **Fact and recommendation:** AWS documents jitter to spread synchronized retry spikes and token-bucket retry budgets to stop unproductive retry traffic. Apply this at fleet admission: open a shared-pool circuit, use a bounded probe on recovery, reserve target-provider headroom, and stagger replacement starts. Do not let every failed agent independently stampede the fallback. <sup>[8](#E0014) [9](#E0015)</sup>

B4. **Recommendation — inference:** transient rate limiting can wait under the same task lease; a long quota outage can justify a controlled cross-vendor transition. Stop scheduling new calls on the failed pool, not unrelated successful child jobs. Recovery control must run outside the affected inference pool and must not require an LLM to produce the essential checkpoint.

## C. Recover a task graph, not independent chats

C1. **Fact:** ACP session loading and resumption are capability-negotiated operations. Loading replays history; resume restores existing session context without replay and reconnects requested MCP servers. This is not a cross-vendor session-import guarantee. <sup>[10](#E0006) [11](#E0007)</sup>

C2. **Analogy, not a Paseo feature claim:** LangGraph keys checkpoints by stable thread identity and retains successful parallel-node writes when another node fails. AutoGen saves the states of all agents in a team, while custom agents can default to empty saved state. Together these show why the recoverable unit includes graph/node state and explicit serialization, rather than only the lead transcript. <sup>[12](#E0010) [13](#E0011) [14](#E0020) [15](#E0021)</sup>

C3. **Proposed architecture — inference:** separate stable logical task/role identity from ephemeral `{host, workspace, agent, provider-session}` identity. Keep parent/child relationships, dependencies, workspace claims, MCP capabilities, peer channels, job ownership, and watch registrations in a durable registry. The new agent must receive tool access and permissions appropriate to its role; an old transcript is not authorization.

C4. **Proposed transition protocol — untested:**

C4a. Record an incident and acquire an exclusive recovery lease. Inventory affected and healthy nodes, including hidden/background/remote workspaces and ACP jobs. Fence old task writers or establish their quiescence; do not kill surviving child work.

C4b. Capture a consistent task/communication cut: canonical checkpoint plus the event tail since that checkpoint, with per-channel sequence watermarks and in-flight message records. Concurrent jobs may continue, but the successor must reconcile their later events before writing. A fleet-wide wall-clock timestamp alone is insufficient.

C4c. Persist a transition intent, old/new ownership epoch, source snapshot checksum, target route and stage. Create a successor with a deterministic transition key; keep it in a **prepare-only** phase while validating its readiness and capabilities. A title match is not deduplication.

C4d. Bind job observers and prepare routing. Atomically publish the successor identity and new ownership epoch; reject stale-epoch writes where enforcement exists. Where it does not, require proven quiescence or operator intervention rather than pretend a registry field fences a live process.

C4e. Redeliver pending messages through the durable ledger, reconcile task/job state, and acknowledge readiness before enabling work. Retire or archive predecessors only after proving that action will not destroy resources still needed. Retrying any transition stage must reconcile existing effects instead of creating another successor.

C5. **Priority — inference:** recover coordinator/relay/job observation early, then workers according to actual dependencies. Do not blindly rerun healthy nodes or restart an entire DAG because one shared pool failed. LangGraph's successful-node preservation is a useful acceptance-model analogy. <sup>[12](#E0010)</sup>

## D. Preserve communications as an explicit protocol

D1. **Proposed design — inference:** peers address logical task roles through a durable mapping, not hard-coded replacement agent IDs. Record message ID, sender/recipient task, conversation/correlation ID, sequence, ownership epoch, payload reference and delivery/processing state. Preserve both directions of every relationship, including return callbacks and watcher registrations.

D2. **Proposed semantics — inference:** at-least-once delivery with deduplication and application-level processing records is more honest than an unqualified exactly-once promise. Transport acceptance, inbox persistence, delivery and answered/processed are different states. Carry unanswered requests, not just unread chat excerpts. Treat the message ledger as history, never as new operator approval.

D3. **Mid-transition cases — inference:** stage incoming messages at the stable mailbox while routes change; retain the sender's outbox until the appropriate acknowledgment; detect messages already processed by the predecessor; correlate late child replies with the logical parent even after its concrete agent changes. Keep old-to-new aliases long enough to cover existing direct-ID senders, without forwarding loops.

D4. **Local compatibility:** ADE currently mandates verified `session-finder/relay.py` peer messaging and has durable ACP inbox/reply records. Preserve that delivery model rather than silently adding a parallel chat system. Exact existing capability and missing seams belong in the accompanying local audit; no transparent fleet redirect is claimed merely because relay exists.

## E. Reattach work by category

E1. **Supervised workspace jobs or tmux sessions — recommendation:** retain the same host, workspace/job/terminal identifiers, logs and exit-artifact paths. Rebind observation and completion notifications, not the computation. tmux explicitly supports detaching and reattaching programs already running inside it; it does not by itself adopt arbitrary existing jobs. <sup>[16](#E0018)</sup>

E2. **ACP-client terminals — fact:** `terminal/release` kills a still-running command and invalidates the handle. The recovery path must inspect terminal ownership and cleanup behavior before closing clients or archiving owners. A released terminal cannot be recovered by replaying its ID in a new vendor's prompt. Cross-session terminal adoption remains an implementation question. <sup>[17](#E0008) [18](#E0009)</sup>

E3. **Independent ACP slices — recommendation:** keep their original record, session ID, report path, inbox/reply files and process-identity evidence. If still running, observe them and rebind the waiter/return destination; if finished, consume the finalized result. If stopped, prefer native resume when supported. Cross-vendor reroute is a new runtime attempt with inherited durable state, not native session continuation. Never start a duplicate because the original parent disappeared.

E4. **Provider-native or in-process subagents — limit:** a transcript can describe the child but does not prove resumability or reparentability. A healthy independent child can continue and report through the logical-parent mapping; a coupled/opaque child may have to drain on the old runtime or be reconstructed from its own saved state. Verify actual negotiated capabilities and ownership APIs; otherwise mark adoption unsupported.

E5. **Unsupervised processes — recommendation:** inventory host, PID plus start identity/boot, executable and working-directory evidence, process group, output/exit paths and any control socket. PID alone is not identity. Observation may be possible without terminal or process-parent adoption; a replacement shell cannot generally recover another shell's job table or `wait` relationship. The opened reptyr README supports Linux and FreeBSD, not macOS; do not propose it as a generic fix for this Mac. No ptrace/security-setting changes are recommended. <sup>[19](#E0019)</sup>

E6. **Unknown outcome — fact and recommendation:** Temporal recommends idempotent Activities and makes recorded heartbeat progress available to later attempts. Use durable operation IDs and checkpointed progress around side-effecting work. If a commit, deployment, message, payment or file write may already have happened, inspect the destination artifact before any retry; uncertainty must block unsafe replay. <sup>[20](#E0012) [21](#E0013)</sup>

## F. Minimum recovery bundle

F1. **Proposed schema contents — untested:** logical task and incident IDs; owner epoch and transition stage; source/target host, agent, provider/session and workspace identities; base/head SHA, branch, dirty patch/untracked-file inventory and claim; task objective, latest operator request, decisions, constraints, rejected approaches and exact next action; checkpoint checksum and full transcript/artifact references plus bounded working context; graph edges and capabilities; inbox/outbox watermarks and unresolved requests; jobs, children, watchers and waiter destinations; side-effect operation IDs/status/uncertainties; redaction/provenance policy; readiness and routing receipts.

F2. **Recommendation — inference:** capture mechanically and incrementally before quota failure. Summarization is optional enrichment, not the sole checkpoint. Keep original evidence retrievable; don't flood the successor with every transcript. Credentials remain in approved stores, referenced by name, never copied as environment dumps. Continuity itself warns that pattern redaction misses secrets. <sup>[22](#E0005)</sup>

## G. Acceptance tests for Astra's design

G1. **Proposed fault-injection matrix, not executed:** quota stops before dispatch, during streaming, while a tool is running, after a side effect but before its receipt, during message delivery, during successor creation and after route publication but before acknowledgment.

G2. **Fleet cases:** concurrent recovery coordinators; shared-pool depletion; target pool also depleted; a healthy slow child; native child with no resume; remote host offline; hidden workspace; reused PID; missing exit file; duplicate completion notification; late peer response; unacknowledged request; daemon restart; expired lease; old provider resumes after quota reset.

G3. **Pass conditions:** no acknowledged task/message state silently disappears; no protected operation repeats without reconciliation; no duplicate active writer or successor; every job is adopted, draining, completed, reconstructable, or explicitly unrecoverable; readiness/routing have durable evidence; secrets do not cross providers accidentally. Run applicable tests in CI; no live fault injection without permission.

## H. Counter-evidence, confidence and next decision

H1. **Counter-evidence:** a useful single-agent solution already exists, so a blanket “Paseo cannot fail over” claim would be wrong. Conversely, bounded context, default subagent exclusion, capability-gated resume, destructive terminal release and incomplete custom state saves all limit a seamless/lossless claim. <sup>[1](#E0001) [3](#E0003) [4](#E0004) [10](#E0006) [17](#E0008) [15](#E0021) [5](#E0022)</sup>

H2. **Confidence:** high in the documented boundaries and the distinction between native resume, semantic task reconstruction and job observation. Moderate in the proposed fleet architecture; it has not been implemented or fault-tested here. Unknown: installed Paseo/plugin support for external migration, terminal ownership transfer, reparenting native children, atomic aliases and enforceable write fencing.

H3. **Astra's next decision:** perform a read-only design review: reuse Continuity versus extend ADE or propose upstream hooks; identify the narrowest missing primitives; specify staged rollout and the failure matrix. Do not install plugins, migrate the live fleet or edit third-party code as part of this research handoff. Source snapshots, verbatim evidence and search results accompany this report.

## Citation footnotes

1. <a id="E0001"></a>E0001 — Catalog advertises successor creation in the same workspace with recent conversation. — Continuity (primary; Paseo), saved text line 12. <https://paseo.sh/plugins/keefeere/continuity>

2. <a id="E0002"></a>E0002 — Cross-provider switching creates a new agent; it does not mutate the old provider. — Continuity (primary; Paseo), saved text line 16. <https://paseo.sh/plugins/keefeere/continuity>

3. <a id="E0003"></a>E0003 — Catalog promises bounded conversation, task and tool-activity transfer, not arbitrary runtime state. — Continuity (primary; Paseo), saved text line 28. <https://paseo.sh/plugins/keefeere/continuity>

4. <a id="E0004"></a>E0004 — Catalog says subagents are excluded by default. — Continuity (primary; Paseo), saved text line 21. <https://paseo.sh/plugins/keefeere/continuity>

5. <a id="E0022"></a>E0022 — Continuity claims failover without requiring the failed provider to produce a handoff. — Paseo Continuity README (primary; Continuity authors), README introduction. <https://github.com/keefeere/paseo-continuity>

6. <a id="E0016"></a>E0016 — Billing/spend/quota failures are not fixed by retry. — Error codes (primary; OpenAI), saved text line 53. <https://developers.openai.com/api/docs/guides/error-codes>

7. <a id="E0017"></a>E0017 — Respect retry timing, use jitter and bounded retries when absent. — Error codes (primary; OpenAI), saved text line 135. <https://developers.openai.com/api/docs/guides/error-codes>

8. <a id="E0014"></a>E0014 — Jitter spreads synchronized retry spikes. — Exponential Backoff And Jitter (primary; AWS), saved text line 36. <https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/>

9. <a id="E0015"></a>E0015 — Retry budgets can fail fast instead of amplifying outages. — Retry behavior (primary; AWS), saved text line 37. <https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html>

10. <a id="E0006"></a>E0006 — ACP history loading is capability-negotiated. — Session Setup (primary; ACP), saved text line 54. <https://agentclientprotocol.com/protocol/v1/session-setup>

11. <a id="E0007"></a>E0007 — ACP resume restores context without replay and reconnects requested MCP servers. — Session Setup (primary; ACP), saved text line 213. <https://agentclientprotocol.com/protocol/v1/session-setup>

12. <a id="E0010"></a>E0010 — Durable pending writes can avoid repeating successful parallel nodes. — Checkpointers (primary; LangChain), saved text line 25. <https://docs.langchain.com/oss/python/langgraph/checkpointers>

13. <a id="E0011"></a>E0011 — Stable thread IDs key persistent checkpoints. — Checkpointers (primary; LangChain), saved text line 38. <https://docs.langchain.com/oss/python/langgraph/checkpointers>

14. <a id="E0020"></a>E0020 — Team-state recovery must include child agent states, not only the lead. — Managing State (primary; Microsoft), saved text line 92. <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html>

15. <a id="E0021"></a>E0021 — Custom state hooks may default to empty state, limiting generic saves. — Managing State (primary; Microsoft), saved text line 86. <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html>

16. <a id="E0018"></a>E0018 — Programs already inside tmux can survive terminal detach and reattach. — Getting Started (primary; tmux), saved text line 14. <https://github.com/tmux/tmux/wiki/Getting-Started>

17. <a id="E0008"></a>E0008 — Releasing a terminal kills its still-running command. — Terminals (primary; ACP), saved text line 281. <https://agentclientprotocol.com/protocol/terminals>

18. <a id="E0009"></a>E0009 — Released terminal handles are invalid. — Terminals (primary; ACP), saved text line 296. <https://agentclientprotocol.com/protocol/terminals>

19. <a id="E0019"></a>E0019 — reptyr supports Linux and FreeBSD, not documented macOS support. — reptyr (primary; reptyr), saved text line 99. <https://github.com/nelhage/reptyr>

20. <a id="E0012"></a>E0012 — Idempotency is needed to avoid duplicate retry side effects. — What is a Temporal Activity? (primary; Temporal), saved text line 15. <https://docs.temporal.io/activities>

21. <a id="E0013"></a>E0013 — Heartbeats expose progress checkpoints to later attempts. — What is a Temporal Activity? (primary; Temporal), saved text line 38. <https://docs.temporal.io/activities>

22. <a id="E0005"></a>E0005 — Pattern-based transcript redaction is incomplete. — Continuity (primary; Paseo), saved text line 28. <https://paseo.sh/plugins/keefeere/continuity>
