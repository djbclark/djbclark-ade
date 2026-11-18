# Opt-in NATS coordination adapters (issue 779)

This source is uninstalled and disabled until the controlled pilot is approved.
Unenrolled paths retain legacy claims, succession, completion and prompt-ack
behavior. Enrolled acquisition and authority decisions fail closed on missing
configuration, unavailable broker, stale owner, resource mismatch or generation
rollback. Previously authorized disconnected work does not obtain a new grant.
The protocol proof does not claim arbitrary filesystem hard fencing.

## Configuration and enrollment

Set `ADE_COORD_CONFIG` to a private JSON configuration. Credentials come only
from the existing sudo-secretspec-injected `ADE_NATS_URL`/`ADE_NATS_TOKEN`
environment. Config contains no credentials. Example structure (dummy IDs):

```json
{
  "generation": "pilot_generation",
  "generation_manifest": "/private/independent-generation.json",
  "state_dir": "/private/ade-coord",
  "identity": {"host": "host_a", "server": "daemon_a"},
  "roles": {"lead_role": {"controller": true, "controlled_pilot": true,
    "successors": [{"host":"host_a","server":"daemon_a","agent":"new_agent"}],
    "runtime": {"owner":{"host":"host_a","server":"daemon_a","agent":"old_agent"},
      "ownership_epoch":1,"processes":[]}}},
  "claims": {"pilot_claim":{"role_id":"lead_role","resources":["/controlled/worktree"]}},
  "aliases": {"old_agent":"lead_role","new_agent":"lead_role"},
  "assignments": {"worker_agent":{"id":"assignment_one","recipient_role":"lead_role","message_id":"completion_one"}}
}
```

The independent manifest must contain matching `generation` and
`reconciled:true`. It must be reconciled against off-broker high-water evidence,
not copied from a restored broker. The optional `retirement_contract` described
below is independent evidence too. Configuration is trusted operator input;
booleans are attestations, not a substitute for its collection procedure.

Explicitly register opt-in with
`python3 bin/ade_coord_controller.py --enroll`. This writes a private persistent
config-location marker outside the repository. Missing config after registration
is an error, not unenrollment. Tests can override `ADE_COORD_ENROLLMENT_MARKER`;
default is `~/.local/state/ade-coord/enrollment.json`. New enrolled claim projection
requires an already bound broker role/resource, exact local host/server and
owner. Its persistent `coordination` marker prevents disappearing config from
turning it into an ordinary local claim. It does not expire into unclaimed state
and legacy release cannot discard it. Local projection is not another ownership
store. Enrollment does not create arbitrary broker roles or new resource grants.

Keep every historical agent alias and approved successor in the config. Stable
role lookup reads the stream leader. `ade_lead_succession.effective_lead` retains
its legacy string return but resolves enrolled IDs through that role. The send
guard refuses when enrolled ownership cannot be established; archived/replaced
local overrides do not grant broker authority. Native generic sends cannot route
to a foreign daemon merely from an agent ID; they refuse when its live local
owner cannot be inspected. Durable cross-host completion uses NATS instead.

## JSON driver and completion

`bin/ade-coord GROUP COMMAND` reads a JSON request on stdin and emits one JSON
result/error. It invokes the maintained Node package CLI through argv/stdin with
a 30-second bound and sanitized errors. See `lib/ade-coord/DELIVERY.md` for core
commands. Generation always comes from verified config, never a request override.
Outbox status and explicit reconciliation remain available offline. Operation
journals never invoke/retry external effects.

For enrolled `completion-notice --send`, assignment identity is validated
separately from recipient ownership epoch. Use explicit `--msg-id` or a
preassigned stable `assignments.<sender>.message_id`. The complete canonical
intent and report bytes commit before connect/upload/publish. Lost replies
reconcile the original ID/digest. Missing artifacts recover from persisted bytes;
existing corruption is visible. Offline returns `local-buffered` (exit 5) only
after verifying that durable row exists. `broker-accepted` exits 0 and means
broker publication, not model understanding. Conflicting IDs fail.

Enrolled `--lead-ack` performs durable `ADE-inbox-recorded` under the current
role owner and writes the existing `<done>.ack` projection. It sends no routine
prompt ack and does not infer processed. Paths and legacy footer contracts stay
intact. Explicit `inbox read` / `inbox dispose` with current snapshot/authority
read or process retained reports. `artifact read` verifies and returns bytes as
base64 for caller materialization; a local path alone is never an artifact ref.

`python3 bin/ade_coord_controller.py --role ROLE` performs one bounded machine
intake pass; it checks producer assignment and current local authority, verifies
artifacts, records durable intake and never dispositions. The optional plugin
runs this bounded pass at startup and every 30 seconds, coalescing concurrent
passes per role. This is machine work, not recurring model prompts. Opt-in wake:true now enables coalesced notifications under the ownership/archive
fence; it defaults off until pilot approval. Durable inbox remains the truth and
queued notifications never mean intake or processing. Goal completion still
requires approved live pilot/controller evidence, not this source alone.

## Shared external-operation intent

The local SQLite operation journal remains available for legacy/local use; it
cannot prove cross-host reconciliation. Enrolled commands are:
`shared-operation intent`, `inspect`, `list`, `reconcile`.
Intent takes `{snapshot,id,intent}` and uses immutable stable IDs/digests. It
records UNKNOWN under active role authority. Reconciliation takes
`{snapshot,id,state,result,evidence}`; state is SUCCEEDED or NOT_APPLIED with
explicit endpoint evidence, under active or draining authority. Same-stream
atomic guard checks role revision while the operation entry checks its own prior
revision. No external invocation engine exists. Quiescence cannot be persisted
while retained shared operations for that role contain UNKNOWN. Intents survive
handoff and remain visible to another client. Generation mismatch fails closed.

## Managed jobs and controlled local handoff gate

`bin/ade-coord job run` accepts `{claim,job_id,argv}`. It verifies fresh authority,
persists claim/authority-bound launch intent, atomically consumes launch permission
before Popen, records the actual process birth/group, waits, and requires exit of
the process and group before terminal state. Output goes to a private job log;
its path is returned without echoing child output into the JSON protocol. Job IDs
never authorize another spawn after uncertainty. Explicit no-child/endpoint
reconciliation or observed identity binding resolves SPAWN_UNKNOWN. Birth identity
excludes mutable scheduling state. Arbitrary commands must follow normal build/
CI policy; this wrapper does not authorize local builds.

Enrolled legacy `ade-self-session handoff --quiesced` refuses. A boolean or idle
status cannot retire a writer. Instead an **external machine controller** can
invoke `bin/ade-coord handoff transfer` with
`{role_id,next_owner,attempt_id,checkpoint_path,archive_reconciliation?}`.
It requires `controlled_pilot:true`, an approved successor, persistent old/new
aliases, a current local host/server and exact bound claim/resource manifest.
Create the waiting successor outside bound resource directories before enrollment;
it has no role grant before transfer. This unit does not create successor agents.

The journal persists original owner/epoch/revision, immutable checkpoint bytes
and attempt before mutations. It records draining revision, all claim-bound
tracked-job terminal states, shared operation resolution, positive native
retirement, actual `lsof +D` process-user census for **all** bound directories,
and checkpoint upload/read-back digest. Unknown host/inspection/census blocks.
The controller must run outside resource paths so its own cwd is not a user.
Native archive is allowed only after explicit draining and idle/no permissions;
it is never a timeout takeover or an instruction to interrupt paid work.

For a provider without an audited close contract, `runtime.processes` must contain
independently captured `{pid,birth,boot,pgid,state}` identities; every identity
must be gone after retirement. For controlled Codex, the independent manifest
and `runtime.codex_close_contract` instead carry identical
`{server,daemon_version,provider:"codex",source_commit,verified:true}`.
The gate calls **`paseo daemon status --json`** and checks top-level
`daemonVersion`/`serverId`, then checks inspected Provider. CLI version is never
substituted. Root verified live beta.2 commit
`23bae61535542a45ade7196a7b3c152705f16de3`: native Codex close awaits transport
child termination and throws on kill timeout. This is release-specific evidence,
not a version pin; an upgrade needs current source revalidation.

Archived is stored before close. Therefore only a positively completed archive
operation plus archived/closed readback establishes this audited contract.
A lost archive result stays UNKNOWN. Reconciliation must provide independent
endpoint evidence bound to the exact agent/draining revision; merely seeing the
archived flag does not permit retry or transfer. Direct-child exit does not prove
detached descendants stopped: jobs and workspace census remain separate.
Saved evidence is checked again on resume before checkpoint/transfer. Transfer
CAS uses persisted quiescence/checkpoint proof. A lost transfer reply reconciles
owner/epoch and checkpoint provenance, never blindly increments epoch again.
Projection repair is idempotent after authoritative transfer.

Nonempty cross-host resource migration remains unsupported and blocks rather
than inventing remote census. Explicitly resource-free roles may transfer to an
approved remote successor after the prior local runtime is retired; that is not
filesystem migration. NATS artifacts/reports remain retrievable independently.
The explicit pilot excludes arbitrary untracked filesystem writes; no hard
filesystem fencing guarantee is made. Further adapters can supply independently
verified remote retirement/census under the same evidence contract.

## Evidence and instrumentation

`ADE_COORD_METRICS` optionally records command, real request/response byte counts,
elapsed milliseconds and prompt-ack suppression count. It stores no content,
credentials, configs, argv or fabricated token/N-squared estimates. No model-token
savings claim is made.

Linux conformance includes real NATS CAS/batches, SQLite process death/reopen,
immutable reports and artifacts, shared operations, Python completion/claim paths,
late acknowledgements, independent client retrieval, managed-job launch races,
failed Popen recovery and external gate using a real OS child/workspace census
with a **synthetic native API**. The synthetic native fixture is not live Paseo
retirement proof. Plugin tests verify documented hook and teardown policy; no
plugin was installed or run on this Mac. Legacy seam regressions run separately.
No deployment, credentials, enrollment or production resources are changed here.

## Provisioning and bundle layout

Explicit `broker provision` with `{generation,confirm:"ADE_COORD_V1"}` creates
missing coordination stream and Object Store only when requested. Existing unsafe
configuration fails validation; runtime publication never provisions or silently
changes retention. Server sync_interval remains a deployment check, not a claim
made by doctor. Provisioning must use managed environment credentials and is not
authorized by merely installing this package.

A distributable source bundle preserves root `bin/`, `lib/ade-coord/` including
Linux-CI-resolved pure JavaScript `node_modules`, and `plugins/ade-coord/`.
Python derives this root from its real path; the plugin uses relative bin paths.
`ADE_COORD_NODE` can choose a supported Node binary (otherwise PATH node).
No local npm build is required; root owns separate bundle/distribution CI.

Managed launch recovery is explicit: `job inspect` takes `{job_id}`; `job reconcile`
adds independent `evidence` proving no launch/child; `job bind` adds observed `pid`
and endpoint `evidence`; `job complete` adds `result` and verifies the recorded
process/group are gone. None of these commands launches another process for an
uncertain job. Mutation requires fresh local role authority; inspection alone
may read retained local evidence offline.

`artifact materialize` accepts `{artifact}` and writes verified bytes into the
private content-addressed local state cache, atomically and at mode0600. It
returns `{path,sha256,size}`. Existing corrupt cache content is a conflict, never
a silent overwrite. It accepts no arbitrary output path or source-resource grant.

## Audited plugin compatibility and enrolled role brief

The actual beta.2 agent.open.before strict schema permits only env/tools/MCP
changes. The plugin contributes role/instruction-path environment only for interactive
opens. Provider history opens are authority-fenced but receive no additions.
It does not append a system prompt.
Supply this explicit role brief through the supported agent creation prompt:

> This role uses the durable ADE inbox. Read docs/nats-coordination.md. Routine
> prompt acknowledgements are suppressed. ADE-inbox-recorded is machine intake,
> not model understanding or processing. Read the inbox and explicitly dispose
> under current active authority. Queued wakes and completed turns prove neither.

This is an explicit enrollment prerequisite, not automatic injection through an
unsupported field. Executor shutdown sends SIGTERM to its owned group, escalates
to SIGKILL after a bounded grace, and rejects by a final deadline. A remaining
unreaped/uninterruptible process is an unknown failure, never successful intake.

## Admission barrier, shipped guards and exact offline policy

Managed job admission holds the common state-directory admission.lock before its
fresh online authority check, through durable launch reservation and observed
process birth binding. It releases before waiting for the job lifetime. Handoff
takes the same barrier before draining, including resumed quiescent/checkpointed
attempts, and keeps it through certification/transfer. An earlier preflight read
is not a grant; the under-barrier check must match exact owner/epoch/revision.
Unknown/running admitted jobs remain transfer blockers.

Only opted-in interactive agent opens prepend the shipped
`<bundle-root>/libexec/agent-bin` to PATH. Managed jobs explicitly prepend the same
path and carry their claim/role context. These checks do not depend on the dirty
shared reference checkout, change global PATH, or switch global plugin enforcement.
Sibling modules load from trusted absolute __file__ paths, including Python -I
callbacks after temporary path restoration; no cwd/PYTHONPATH dependency is added.

Pilot default (operator-selected conservative option1): ordinary edits within
already-authorized scope, already-running jobs and report buffering may continue.
Git mutations and NEW managed job launches wait for NATS. This wave adds no
cached-grant engine or expanded offline authority.

Offline allowed: inspect local outbox/evidence and already materialized artifacts;
persist report intent/artifact bytes and completion reports as local-buffered;
read local transcript/cache files without starting a provider; an already admitted process can finish
its existing computation and record observed process/group exit locally. Local
operation notes remain UNKNOWN and cannot authorize an external retry.

Deferred until online: new claims/jobs or expanded resource scope, guarded Git
mutations, broker publication/acceptance, new artifact retrieval, inbox intake or
disposition, shared operation resolution, wakes, ownership/lifecycle transitions
and projection grants. Existing application computation does not imply an offline
Git-write grant. No cached role/claim or local journal substitutes for a fresh
online authority check. Disconnected work must not expand its previously granted
scope; unknown operations still block later handoff.

## Retained handoff attempt history

Handoff attempts are keyed by role plus immutable attempt ID and record the prior
epoch. At most one unfinished attempt per role exists in a host state directory.
The old role-only journal is retained and migrated without deleting evidence.
Transfer is recorded before projection; an interrupted projection is reconciled
before a new attempt starts. After completion, a new request takes a fresh active
snapshot/runtime proof and may advance the next epoch. Repeating an old completed
request returns the current broker role plus its historical result; it never
re-runs retirement, rolls a claim projection back or increments ownership again.

## Resource-free cross-host succession

A role explicitly marked resource_free:true may move to an approved different
host/server only when the broker bindings, configured local claims, and inspected
active local role claims are all empty. The controller still executes on the
verified prior host and retires its runtime; native close/birth evidence, shared
UNKNOWN resolution, durable checkpoint retrieval, generation and alias fences
remain mandatory. The receiving host enrolls independently with its own state
and server identity. No local resource claim is projected to a foreign owner.
This is not permission to migrate a nonempty workspace or unknown remote writer.
Unreadable local claim census is unknown and blocks. CI uses separate host/server
IDs and directories with a real broker; live two-host provider evidence is still
a pilot gate.

## Current managed credentials without daemon restart

Each network consumer executes `sudo-secretspec run --reason ... --` followed by
a narrow consumer hop. That hop passes only ADE_NATS_TOKEN and plain broker URL
plus safe runtime/path/locale fields to Node; unrelated injected secrets and
NODE_OPTIONS are dropped. It does not read/export/store a token, place it in argv,
or rely on the old daemon having inherited today's credential. An operator may
select the installed absolute client via credential_boundary in private config;
CI uses an explicit fake boundary, never real credentials. Broker URL may be plain
broker_url config or ADE_NATS_URL environment. Plugin opens supply role, config
path and shipped guard PATH; the driver itself obtains current credentials.

Report buffer commits canonical intent/artifact bytes offline before boundary
execution, then report flush reconciles/publishes that stable row through the
current managed consumer. If the boundary is unavailable, completion can still
return verified local-buffered; it does not silently use a stale inherited token.
Offline inspection/local journaling executes a sanitized child without credentials.
No daemon or unrelated agent is restarted by this mechanism.

## Opt-in machine wakes and recovery

Set wake:true on an enrolled local role to enable notifications; default is off.
Each pass re-resolves the active role, local host/server and daemon serverId,
inspects the exact current native owner, refuses archived/replaced/wrong-daemon
targets and defers busy or permission-blocked owners. The common admission barrier
serializes this native-send seam with controlled drain/retirement.

The journal coalesces by generation/owner/epoch and pending-report sequence
high-water, so removals/unchanged reports do not repeatedly prompt. A new owner
epoch can receive one wake for retained unfinished reports. Local intent commits
before a same-stream shared operation intent, then before native send. Queued,
sent and completed native statuses mean acceptance of a notification only: they
never create an intake/processed receipt or imply understanding. Model processing
still requires explicit inbox disposition under current authority.

Unknown responses are never automatically resent. Local RESERVED/UNKNOWN and
accepted-but-ledger-unreconciled wakes block handoff; shared UNKNOWN also survives
host changes and blocks core quiescence. `wake status` takes `{role_id}` and reads
safe retained evidence. `wake reconcile` takes `{wake_id,state,result,evidence}`
with endpoint-confirmed SUCCEEDED or NOT_APPLIED. Only an explicit rearm:true
alongside verified NOT_APPLIED permits another attempt; all old evidence remains.
This is an operator/endpoint decision, not an arbitrary retry engine. Already
resolved authoritative operation results cannot be overwritten. Standalone
controller timers perform machine work only; when there are no new reports there
is no model prompt. Remote host controllers handle their own local owner, never
send an agent ID blindly to another daemon.

Plugin tests use the audited beta.2 strict shape, real signal-resistant local
children in Linux CI, synthetic native wake transports and real broker shared
operation/receipt fences. No real agent is messaged during implementation. Actual
Paseo wake/retirement and two-host behavior remain rollout evidence for root.

## Queued-old-wake provider-open fence

The waiting open hook checks authoritative active owner/host/server for both
interactive and provider-history opens, and checks a durable deny-only admission
marker before/after the lookup. The gate atomically writes that marker before
drain and retains it for the retired epoch. A stale alias, nonactive role or
matching draining marker throws before the provider opens. A newer owner epoch
still needs its own fresh broker grant; the old marker never grants authority.
Direct local transcript/cache reads remain offline-readable, but enrolled provider
history reopen is deferred offline just like other provider starts.

Root audited exact beta.2 commit23bae61535542a45ade7196a7b3c152705f16de3:
AgentManager.runLifecycleMutation2956 serializes create1484, import1498,
resume1630, reload1838, close2126, archive2203 and history-upgrade3165.
Thus a pre-marker in-flight native opening is completed before archive closes
that runtime; an opening queued afterward must pass the new waiting hook.
Source: [agent-manager.ts](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/agent/agent-manager.ts#L2956).
This does not prove detached descendants dead; all job/census/operation checks
remain separate. No live-agent test or provider opening was performed here.

The plugin minimum is >=0.16.0-beta.2, the audited compatible prerelease, rather
than a stable-only minimum that might reject the running beta. This is a lower
compatibility bound, not a software version pin or permission to upgrade/restart.
