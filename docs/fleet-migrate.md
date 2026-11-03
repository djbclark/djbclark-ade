# Fleet migration — implementation contracts

Snapshot: 2026-11-03 UTC. **Work in progress, not an operational migration tool.**
The operator authorized implementation and offline/CI validation only. No live
migration, bulk notification, timer change, process termination, plugin change or
paid smoke test is implied. No installed plugin has been changed by this task.

## Capability matrix (first implementation action)

1. **Workspace enumeration:** public `list_workspaces(includeBackground=true)`
   returns workspace IDs and titles. Read-only probe on 2026-11-03 found Dann Home.
   Resolve exact-name matches on every scoped host; retain all protected IDs even
   after rename. Never infer membership from cwd, even a unique realpath match.
2. **Agent membership:** public `list_agents` is recent/bounded (maximum 200,
   `sinceHours` maximum 720), not a complete fleet snapshot. The recorded CLI
   `ls`/`inspect` evidence omits workspace membership. `self-slash`
   `own_workspace_id` reads per-agent local metadata, but that code only promises
   placement. A schema-validated, no-follow read-only local adapter remains to be
   admitted. No local state/database edits are allowed.
3. **Externally gated activation:** public `create_agent` requires an initial
   prompt and starts work immediately; scoped calls default to a child. There is
   no proven tool-disabled staging contract here. A prompt saying wait is not a
   fence. Block live creation until exclusive source ownership is proven first.
4. **Predecessor fence with child survival:** not established. Quota exhaustion,
   idle/error status, a claim or a marker cannot fence the old runtime. No kill,
   archive or auto-resume disable is permitted as an inferred workaround.
5. **Per-task scheduler control:** Usage Auto Resume has independent durable
   continuations; no integrated supported cancellation/readback contract has
   been proved. Preserve all healthy work and block affected transfers.
6. **Runtime model/thinking:** public Pi provider inspection reports no features
   or modes; lead CLI inspection reads `Provider=pi`,
   `Model=openai/gpt-6.1-sol`, `Thinking=high`, `ParentAgentId=null`. This proves
   the current lead's configuration only, not a successor's permissions, tools,
   skills, MCP, context acceptance or capacity. Use runtime readback, not prose.
7. **Desktop tab proof:** creation is not proof of opening a visible tab. Need a
   supported Desktop readback or separately approved UI verification. An open
   request alone is unverified, never COMPLETE.
8. **Identity redirects/application acks:** existing relay expectation transfer
   is gated on a finished predecessor; it is not a universal alias. Rendered
   timelines prove transport delivery only, never authenticated application.
   Direct native/plugin transports need inventory and supported return-route
   updates or remain explicit blockers.
9. **Resources:** independent ACP records/waiters may support observation, not
   arbitrary native-handle adoption. Parent disappearance is not child failure.
   Native/raw child lifecycle and archive survival remain per-resource evidence
   obligations. Unknown exit/report is UNKNOWN; reports require finalization.
10. **Governed Pi delegation:** PR 273 is verified MERGED at
    `1608f0429561e3ea141bb7d591a7cc08822e120f`; installed registry lists `pi-acp`.
    Integration owner's paid canary failed at the project spend limit. The
    current aiuse available snapshot has no admissible Pi entry. Serial lead
    implementation only until ordinary gates admit a route; no Codex pool
    substitution, raw Pi launch or paid canary bypass.

Sources: read-only public MCP tool schemas/probes, installed `acp-run --list`,
`bin/self-slash` workspace resolver, `docs/queue.md` Verified peer messaging round
2, and the research branch `research/fleet-quota-handoff` (read-only worktree
`/Users/djbclark/src/djbclark-ade-fleet-quota-research-wt`). Its
`research/plugin-recovery-audit/provider-plugins-code-and-skills-audit.md` and
`astra-provider-recovery-skill-brief.md`, plus
`research/fleet-quota-handoff/fleet-quota-handoff-research-report.md`, are evidence,
not claims that live failure tests passed.

## Frozen first-stage interfaces

`libexec/fleet_migrate/planning.py` is a pure draft planner. Its normalized
inventory v1 has `hosts`, `workspaces`, `agents` and `catalog`. Each host records
reachability and enumeration completeness. Agent identity is host plus full
native identity; bridge views collapse only on explicit matching native IDs.
Membership evidence is independent of cwd. Unknown identity/membership blocks
selection. Catalog records separate TUI, vendor, model, thinking, billing pool
and context. Inventory is whitelisted metadata, not raw histories or environments.
An imported `authoritative` label is not itself a trusted live adapter receipt.

`build_plan` emits exact selected source/view IDs, protected workspace IDs,
excluded/unresolved records, destination capabilities/pool, full communicating
recipient roster, deterministic mapping-policy version, runtime blockers and a
SHA-256 digest. Every result has `execution_authorized=false`: selecting a
candidate never permits execution. `validate_plan` checks both digest integrity
and deterministic recomputation; neither digest nor inventory authenticates an
operator or proves current runtime state.

`guard` is the shared predicate for create/fence/scheduler/ownership/archive/
placement. Notification is a separate permission category, so protected agents
remain recipients. Live adapters must obtain a fresh complete snapshot under the
coordinator lock and invoke this guard immediately before every mutation. No
Dann Home force override is planned. A local lock is not cross-host atomicity.

Dann-titled DeepSeek agents on explicit OpenCode Go/Cline/DeepSeek billing routes
are protected even if membership is missing. Title/model/route comparisons are
case-normalized, independent of TUI identity. A single inconsistent signal needs
review. Protected workspace membership wins even without expected title/model.
Bridge protection propagates across all views of the same backing identity.

The only automatic mapping currently implemented is the exact Fable 5.1 ID
`anthropic/claude-fable-5-1` to Pi `openai/gpt-6-astra`, high, with a matching
catalog entry and explicit pool. Unknown aliases block. Opus/Sonnet proposals
are not automatic rules. Pi's reported 272K catalog limit is not an input budget
and no Codex 500K override is transplanted into Pi.

## Next milestones and completion boundaries

1. Add bounded private artifact storage/CLI and authoritative discovery adapters.
2. Implement durable transition/journal contracts against a fake action sink,
   resource/operation evidence and restart/concurrency fault cases. Live apply
   remains a precise refusal wherever the matrix is unproven.
3. Implement committed versioned identity directory, authenticated ack interface,
   consolidated full-roster updates and additive relay lookup, including old
   addresses, surviving children, newcomers and protected recipients. Do not
   claim universal convergence while direct transports are unsupported.
4. Complete skill/runbook, safe dry-run examples, changelog, independent review,
   current-head CI and reviewable PR. No deployment or live canary under this
   implementation approval. Ownership completion and communications convergence
   must remain separate report dimensions.

## Task discovery discipline

Before probing a workflow, config, report or test filename, enumerate its known
parent directory. Do not guess `tests.yml`, `pyproject.toml` or pre-commit config
names. The initial task made those mistakes; these instructions prohibit their
recurrence. Run graft from the indexed reference checkout for existing seams;
a fresh unindexed worktree can otherwise fall back to an unrelated parent graph.
Use bounded byte output for large reports and never modify the research tree or
another chain's session log.
