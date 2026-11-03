# Astra handoff — quota-hit Paseo fleet recovery

## A. Task and authorization

A1. Operator requested web research into best practices when quota/rate limits stop many Paseo agents at arbitrary moments, so another agent can hand all affected tasks to another vendor while retaining context, peer communications and recoverable background processes/subagents/ACP slices. Operator explicitly intended the research to be handed to Astra afterward.

A2. Your next task is **read-only frontier design review and recommendations**, not implementation or live migration. Critique the supplied research, inspect the narrowest relevant local seams, and propose an implementable phased design with acceptance criteria. Do not stop/replace/archive agents, install Continuity, restart daemons, transfer live claims, modify quota settings, edit code or open a PR. Changes to third-party code/config or installed tools require explicit operator permission. Existing tasks must not be taken over.

## B. Durable inputs

B1. Workspace: `/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt`, branch `research/fleet-quota-handoff`, exclusive claim `fleet-quota-research`, recorded base `78aa363047e0b34a25bc19542dcbfc9bb5d8ec21`. This is a research artifact workspace, not a fleet task workspace. Treat it read-only; write your report only to the dispatch-designated report path.

B2. Start with `/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt/research/fleet-quota-handoff/fleet-quota-handoff-research-report.md`. Supporting files beside it: `evidence.jsonl`, `sources/*.txt` and `sources/*.json`, `searches/*.json`, `fleet-quota-research-plan.md`, `counter.md`, `review.md`, `verification.txt` (if present). Evidence quotes were mechanically verified. The report separates source claims from proposals; no live behavior was tested.

B3. Independent local capability audit was dispatched to Gemini 3.8 Flash high through ACP. Job record: `/Users/djbclark/.local/state/bigteam/fleet-quota-research/jobs/local-recovery-audit.json`. Expected report: `/Users/djbclark/.local/state/bigteam/fleet-quota-research/local-recovery-audit-report.md`. **Do not read that report until its `.done` marker or finalized record proves completion.** If still running, let it finish, rearm its existing waiter if needed, never duplicate the slice. The audit is local-only and not an independent web-source review. It was pending when this handoff was written; check the durable record, not this sentence.

## C. Findings to preserve

C1. Existing candidate: [Paseo Continuity](https://paseo.sh/plugins/keefeere/continuity), [source repository](https://github.com/keefeere/paseo-continuity). Its opened catalog and README advertise same-workspace fresh fallback agents, bounded conversation/task transfer and no need for the failed provider to generate a handoff. Subagents are excluded by default. It is NOT installed by this research and neither its source implementation nor installed compatibility was audited. Do not reinvent its single-agent feature without comparing it.

C2. Central architectural distinction: native provider-session resume ≠ cross-vendor semantic reconstruction ≠ job observation/reattachment. ACP load/resume are capability-negotiated and don't establish portable vendor runtime state. Terminal release can kill work; arbitrary subagent reparenting is unproven.

C3. Recommended recovery unit: logical task graph with durable checkpoints, stable peer addresses, message inbox/outbox/watermarks, job/child handles, side-effect ledger and write ownership. A transcript-only loop is insufficient. “No loss at an arbitrary point” must be bounded to persisted recoverable state; unknown outcomes must remain explicit.

C4. Recommended fleet transition: classify shared pool; stop new calls, not healthy jobs; acquire recovery lease; fence/quiesce old task writers; persist snapshot and transition intent; create idempotent prepare-only successors; verify capabilities; reconcile jobs and message tails; publish new owner/routing epoch; enable new writers only after receipts. An epoch field does not physically fence a process unless its write path enforces it.

C5. Preserve peers and children through logical identity plus durable messaging, distinguishing accepted/persisted/delivered/processed/answered. At-least-once plus deduplication and idempotent operation handling, not unqualified exactly-once. Keep healthy children running; redirect observation/results. Avoid rerunning paid-for work.

C6. Handle runtime categories separately: managed workspace scripts/terminals; tmux jobs already inside tmux; independent ACP records; native provider children; unsupervised OS processes; completed results; failed/unknown jobs. PID plus start identity/boot, host and artifacts matter. reptyr is not a macOS solution per its documented supported systems.

C7. Quota vs rate vs overload classification, Retry-After, jitter, retry budgets, per-shared-pool circuits and staged admission prevent a fleet failover storm. Target providers must have truly independent available capacity. Research observed only 6% Codex quota headroom; run fresh normal gates before spending more. Do not bypass a refusal to execute this handoff.

## D. Local seams and constraints

D1. Read trusted ADE's `AGENTS.md`, consult graft first for source localization, inspect relevant docs/queue sections rather than the whole file. Related queued item: “Quota-aware automatic cross-vendor subagent routing,” historical and not proof of implementation.

D2. Existing primitives to examine: `bin/acp-dispatch` resume/reroute/reap/rearm and inbox/replies; `tools/acp-run` negotiated session capabilities; `bin/self-slash` successor readiness and predecessor archive ordering; `skills/session-finder/relay.py` delivery verification; `claude/hooks/handoff-tools/session_log.py` task state and owner checks; watch-holder/child callback rebinding; Paseo public plugin APIs and Continuity extension seams.

D3. Trusted primary checkout `/Users/djbclark/src/djbclark-ade` carried a foreign `.gitignore` change and an unrelated stale Tier 1 chain. Neither was adopted or edited. No live fleet state changed. Do not write shared Tier 1 pointers. Paseo creation defaults to subagent parentage; workspace placement is not reparenting/detachment. Do not claim an autonomous top-level successor from its title or workspace alone.

## E. Requested output and stop condition

E1. Return a concise design review with: verified current capability matrix in prose; missing primitives; reuse-versus-extension recommendation; crash-safe state/message/job schemas; state machine including rollback/uncertain outcomes; incremental implementation slices in ADE versus upstream proposals; security boundaries; and failure-injection/CI test plan.

E2. Explicitly decide whether Continuity can be wrapped/extended safely or needs upstream hooks for external batch migration, stable routing, child result subscription and resource retention. Do not infer API support from catalog wording. Any needed web research must fetch sources, not cite snippets.

E3. Acceptance: preserve acknowledged durable task/message state; prevent duplicate successors and concurrent writers; do not replay uncertain side effects; account for every surviving child/job; recover after coordinator crash; handle late peer responses and original-provider quota reset. Document impossible/unverified cases and how the operator sees them.

E4. Stop after the design-review report. Research handoff is not permission to execute the proposed recovery or start another vendor fan-out. Write the final report and completion marker per dispatch footer; do not treat this briefing as proof that you have been launched or that anything is already migrated.
