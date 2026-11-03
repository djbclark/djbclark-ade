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

## Offline CLI (not live migration)

The current CLI can plan from exported normalized metadata only. Without
`--inventory`, it returns `BLOCKED: authoritative-live-inventory-adapter-not-admitted`
rather than using an incomplete live list. No command imports a live transport.
Use the repository fixture for a zero-model, zero-agent offline example:

```sh
bin/fleet-migrate plan --from-tui omp --from-vendor anthropic \
  --to-tui pi --to-vendor openai --include-herdr \
  --inventory tests/fixtures/fleet_migrate/inventory.json \
  --output "$HOME/.local/state/ade/fleet-migrate/plans/example.json"
bin/fleet-migrate validate "$HOME/.local/state/ade/fleet-migrate/plans/example.json" --json
```

`plan` never overwrites an existing output. Parent directory must be private
0700; it is created if absent. Files are 0600. Metadata must contain no secrets:
whitelisting is not a guarantee against a credential pasted into a title or ID.
Do not import raw transcripts/environment dumps. All JSON reads are bounded to
1 MiB, reject duplicate keys/nonfinite numbers, and require regular single-link
owned files. State traversal uses no-follow directory descriptors, temp-neighbor
atomic replacement and fsync; a second local coordinator refuses lock contention.
These are accidental-corruption/path safeguards, not malicious same-uid isolation.

`apply PLAN --approved-digest SHA256` validates the immutable plan and records a
deterministic local BLOCKED run with zero external actions. It cannot launch,
fence, archive, publish ownership or notify. Repeated calls reuse that receipt.
`status RUN --json` reads it. `reconcile RUN --dry-run` only inspects;
`reconcile RUN --apply --approved-digest SHA256` verifies the binding but remains
blocked. `notify RUN --retry-due` refuses without a committed ownership epoch and
sends zero messages. These are explicit operational capability limits, not
simulated claims of a successful migration. No `--force` exists.

Exit codes: 0 valid offline draft/read; 2 refused input/schema/permissions/approval;
4 precise unsupported-runtime BLOCKED. Draft validation success explicitly says
`runtime_ready=false`. A digest is not operator authentication or live approval.

## Next milestones and completion boundaries

1. Admit authoritative discovery adapters; private artifacts/CLI are implemented
   but awaiting independent review and CI.
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

## Offline resource and identity protocol helpers (not live authority)

`resources.py` assesses already-inventoried evidence. Independent ACP/raw shell/
tmux/terminal/service jobs are preserved and observed, not adopted or restarted.
Process identity requires host, boot/start identity and command fingerprint, not
PID alone. A vanished parent/waiter is not a dead slice; rearming an existing
waiter is only a proposal. Final report access requires finalization evidence.
Native children wait or propose supported reattachment, with archive still
blocked pending lifecycle proof. Missing exit/report remains UNKNOWN. Converted
tool histories cannot prove side effects. Checkpoint assessment requires an
explicit authorized transfer, verified accessible artifacts, retrievable history
and a working set within an input budget (not the model's whole catalog window).
No resource adapter or operation retry is invoked by these helpers.

`directory.py` defines an immutable versioned directory and a separate mutable
recipient/receipt protocol in pure functions. Current-owner generation and READY
receipt references are checked before constructing a proposed commit; old/new
full host/native/incarnation identities persist. A→B→C resolution preserves
historical inspection; reused incarnations never borrow an alias. Recipient
membership is a union, including protected/unmigrated peers. Transport acceptance,
delivery and explicit applied receipts remain separate; applied receipts bind
full authenticated recipient identity, update ID, epoch and digest. New epochs
and changed incarnations invalidate application coverage while retaining prior
receipts. Acks generate no new ack request.

These helpers do not authenticate a live runtime or publish routing authority.
Opaque receipt references must be verified by a future trusted adapter against
actual artifacts; a checkpoint cannot bless itself. Directory persistence under
an owner-generation transaction, bounded accessible manifests/full-roster
bootstrap, durable retries/backoff, self-recipient acceptance, additive relay
lookup/acks and direct/native transport return-route reconciliation remain
unfinished. No live directory, alias or bulk notification has been installed.
Do not use the pure helper outputs to claim fleet convergence.

## Development checkpoint (2026-11-03 UTC)

Focused Linux CI at `e6fd50a0f2f95c3204aab3d9b97832d699c13fd5`:
[run 41714510722](https://github.com/djbclark/djbclark-ade/actions/runs/41714510722),
98 fleet-migrate tests passed; context-policy 142 passed, 20 skipped. Earlier
full-suite CI at `fb7762043d4f5b3db38c091f95e94f5ef2411d72`:
[run 41712995632](https://github.com/djbclark/djbclark-ade/actions/runs/41712995632),
still running at this checkpoint. It covers that earlier head only. No local
suite, paid smoke test, live migration or bulk notification was performed.

The separately permitted Pi Astra/high frontier advisory admission was tested
with `acp-dispatch ... --kind frontier --role advise --perm read-only --dry-run`.
It refused before launch (exit 2): **Pi is not eligible for frontier**, whose
current eligible routes are antigravity-argon, Claude and Codex. No reviewer or
report was launched; no missing report was read. Do not use route-override,
change pools, expand a capacity mapping or call raw Pi to bypass that gate.
This task pauses before activation/relay correctness-sensitive integration;
resume when a normally admitted review route is available under the brief.

Still required before delivery: authoritative full-scope inventory/membership
adapters, durable transition/intent-result coordinator and crash/concurrency
simulation, resource adapters, persisted identity-directory/relay/launch
integration and full convergence matrix, bounded manifests/retry reconciliation,
independent current-head adversary/local review, full current-head CI, PR-numbered
changelog fragment and reviewable PR. The canonical skill exists but is explicitly
WIP and is not installed. No claim that these mandatory pieces are complete.

## Task discovery discipline

Before probing a workflow, config, report or test filename, enumerate its known
parent directory. Do not guess `tests.yml`, `pyproject.toml` or pre-commit config
names. The initial task made those mistakes; these instructions prohibit their
recurrence. Run graft from the indexed reference checkout for existing seams;
a fresh unindexed worktree can otherwise fall back to an unrelated parent graph.
Use bounded byte output for large reports and never modify the research tree or
another chain's session log.
