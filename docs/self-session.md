# Native self-compaction and acknowledged self-handoff

2026-11-12. Explicit agent-invoked operations restore the functionality requested
in the slim-down audit. These are same-host operations against an already
running local Paseo daemon. They do not deploy tools, install plugins, restart
a daemon, select a new provider/model, transfer files between computers or decide
unattended crash recovery. Tests use fake native commands; live acceptance remains
unverified. Ordinary successors use positively supported unattended modes.
Explicit operator-requested restrictions remain restrictions.

## A. Prepare a durable checkpoint

Write a nonsecret UTF-8 briefing with the task/authority, completed work,
remaining action, exact repository/worktree, dirty and untracked work, outstanding
jobs/permissions, claims and coordination responsibilities. Do not include keys,
login tokens or credential-store contents. Pass that file explicitly; ADE does
not harvest transcripts or credentials. The helper preserves a copy and SHA256
in a private state directory, plus repository HEAD for handoff. A session whose
cwd is in no git repository (for example `~`) records `head: null` and its ack must
attest `head: null`. That needs git's "not a git repository (or any ...)" discovery
failure (exit 128) and no `.git` entry of any kind in the real cwd or any ancestor; any
other `git rev-parse HEAD` failure (timeout, unborn HEAD, broken linked worktree or
gitfile, unreadable `.git`, repository across a mount point, Apple git's
`not a git repository: (null)`) still refuses (2026-11-13). Original worktree
files remain in place; archiving an agent is never workspace deletion.

The executable requires the full `PASEO_AGENT_ID` supplied by Paseo. Handoff also
requires `PASEO_WORKSPACE_ID` in Paseo's `wks_` plus 16 lowercase hexadecimal
digit format (verified against `paseo workspace ls --json`, 2026-11-12). Agent
IDs retain UUID validation. An unrelated shell or a cross-host invocation is
unsupported. `--paseo-home DIR` pins the local daemon home for every command;
use the same home/state directory for every step. The default state directory is
`~/.local/state/djbclark-ade/self-session`.

## B. Self-compact

```
bin/ade-self-session compact --checkpoint /absolute/path/brief.md --request-id task-compact-1
```

This preserves the checkpoint and an intent before native
`paseo agent send ID --no-wait --behavior steer -- /compact`. End the current
turn so Paseo can process a queued self-message. Claude, Codex and Pi have
source-backed native compact commands; other providers are refused. A repeated
request ID returns its existing receipt and never resends, including after an
unknown timeout. Use a new ID only for a deliberately new request.

**`requested` is not completed compaction.** Output always has
`completion_confirmed: false`. Neither queued/sent/completed message receipts nor
agent idle prove successful compaction. The current CLI exposes no per-request
compaction result/correlation ID. Inspect the native provider timeline and
report observed results separately; do not blindly retry an ambiguous request.
Pi can emit a completed compaction marker on an error path, so that marker alone
is insufficient. A future exact completion mechanism requires a supported
correlated native API; no success is fabricated here.

## C. Self-handoff to a new session

This is the default whole-session handoff (operator, 2026-11-12). The agent
performs it itself, including successor launch; no operator typing is required.
Finish other writes/background jobs and prepare the briefing, then:

```
bin/ade-self-session handoff --checkpoint /absolute/path/brief.md --quiesced
```

`--quiesced` attests that other jobs/writes are finished. A running predecessor
can request the handoff, then end its turn; it must stop scheduling project
writes. The helper preserves the checkpoint and creation intent before launching
one top-level successor in the explicit existing workspace. It scrubs ambient
caller-agent/workspace variables, labels the successor with a unique token,
keeps the exact provider/model and passes a positively catalogued unattended
mode. It never silently falls back to Always Ask. Unsupported modeless/control
providers are blocked rather than assigned an invented mode. An explicit
`--mode plan|read-only|dontAsk` is retained only when the actual catalog supports
it; this is for operator-requested restrictive work, not the ordinary default.
The successor's thinking level is set with `--thinking LEVEL` (an identifier such
as `high`, passed to `agent run --thinking`; a malformed value is refused before
any native call). Without it the successor inherits the predecessor's own level
when `agent inspect` reports an explicit one; an unknown, `auto`, `default` or
unusable source level launches with no flag, as before (2026-11-14: a `high` lead
had been handed off to an `auto` successor). The level is recorded in the
transaction record as `thinking`; a duplicate call with a different explicit level
is refused, never replayed. `compact` has no such option.

Creation is not acceptance. The successor reads the preserved checkpoint and
transaction, writes its own nonsecret acknowledgement JSON, then runs:

```
bin/ade-self-session accept --record /absolute/state/handoff-PREDECESSOR_UUID.json --ack-file /absolute/state/ack.json
```

The acknowledgement must contain exactly matching `token`,
`checkpoint_sha256`, `head` (the recorded sha, or JSON `null` when the cwd is not a git
repository; the key must be present) and a nonempty `next_action`. A cwd that became or
stopped being a repository since handoff fails accept and finish (2026-11-13). The receipt binds it
to the successor's actual `PASEO_AGENT_ID`. The helper verifies the checkpoint
bytes, repository HEAD and live successor identity/provider/model/cwd, no parent,
no pending permissions, and effective native mode/catalog readback. It does not
claim to prove semantic comprehension: the trusted successor explicitly attests
that it read and accepts the briefing and scope.

The successor must wait until the predecessor finishes its turn, then run:

```
bin/ade-self-session finish --record /absolute/state/handoff-PREDECESSOR_UUID.json
```

Only the acknowledged successor may retire its predecessor. The helper rechecks
checkpoint/HEAD and mode drift, requires predecessor idle/no pending permissions,
archives **only that agent without `--force`**, then verifies archived readback.
Running/permission waits are blocked; neither session is forced to stop. An
archive timeout retains `archive-unknown`; retry first inspects native state and
does not rearchive an already archived predecessor. Continue project writes only
after verified retirement **and** reconciliation of the repository's exclusive
workspace claim/ownership. This helper does not grant or rewrite claims.

### C0. Why a native command failed (2026-11-14)

A failed native command raises with Paseo's own reason, not "outcome unknown". The helper
reads the `{"error": {"code", "message"}}` envelope from stderr (or stdout), and the error
and the transaction record carry `native_error`: `op` (subcommand words only, never a
prompt), `code`, `message`, `rc` and `stderr_tail` (at most 512 characters, control
characters and token/secret/password/api-key shaped values scrubbed). "Outcome unknown"
stays only for a timeout (`TIMEOUT`), an OS error (`OSERROR`) and a nonzero exit whose
stdout and stderr both hold no JSON object; those still keep `rc` and the tail. `agent send`
exit 5 stays a queued receipt. After a later success (`reconcile` to `awaiting-ack`,
`finish` to `archived`) the earlier reason moves to `resolved_native_error`.
`creation-unknown` and `archive-unknown` are diagnosable from the record file alone.

Workspace pre-check: `handoff` reads `paseo workspace ls --json` before saving the intent. A
failure there refuses with Paseo's reason and sends nothing. When the predecessor's
`PASEO_WORKSPACE_ID` is no longer listed (the 2026-11-14 `WORKSPACE_NOT_FOUND`), the
successor is a new lead in its own placement: the helper launches it with
`--new-workspace local` instead of `--workspace`, and records `workspace_placement:
new-local` (`existing` otherwise; `workspace` keeps the predecessor's id). The checks
`accept` and `finish` run do not compare workspaces. It is a decision, not a fallback to hide:
the record and this section say so.

`finish` archive failures are never retried and never forced. When the archive error
names an agent id that is not the predecessor's (prefix compare; 2026-11-14: `paseo agent
archive FULL_UUID` answered `AGENT_ALREADY_ARCHIVED` for `c9a97e5`, a different agent, while
`agent inspect` of the same id was right) the error reads "Paseo resolved archive to a
different agent ...; preserve, archive by exact id ... via the Paseo MCP archive_agent ...".

#### Manual fallbacks

(a) Creation failed or stayed `creation-unknown`: read `native_error` in the record; fix the
cause; launch one labelled successor with the record's argv, that is the `agent run` call of
section C (same `--cwd`, `--provider PROVIDER/MODEL`, `--mode`, `--thinking`, the prompt
text the record's checkpoint and transaction paths imply, `--label ade.handoff=<token>`,
`--no-wait`, ambient `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `PASEO_WORKSPACE_ID` removed),
plus `--new-workspace local` when the workspace is gone. Then run `bin/ade-self-session
reconcile --record RECORD` as the predecessor; it needs exactly one agent with that label.
Never launch a second one.

(b) Archive failed or stayed `archive-unknown`: archive the predecessor by exact full id
with the Paseo MCP `archive_agent` (never `--force`, never a workspace archive), verify
with `paseo agent inspect ID` (`Archived: true`), then re-run `bin/ade-self-session finish
--record RECORD`; it skips the archive call once the readback shows `Archived`.

### C1. Agent-run fallback

If the helper refuses **before any successor creation intent**, the predecessor
starts its own successor. For a pending/unknown creation, use section D's
reconciliation instead; inspect the transaction and native state before any
fallback. Never retry an uncertain write by launching a second successor.

Read the current provider/model and existing workspace from native inspect and
verify the provider's unattended mode via `paseo agent mode ID --list`.
Preserve any explicit operator restrictions. Use the trusted checkout's routing
policy for a separately authorized model change. Launch with concrete values:

```bash
env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD -u PASEO_WORKSPACE_ID \
  paseo run --no-wait --provider PROVIDER --model MODEL --mode UNATTENDED_MODE \
  --cwd /absolute/owned/worktree --workspace EXISTING_WORKSPACE_ID \
  --title "Task successor" --json "Read /absolute/checkpoint.md and resume its exact Tier 1 chain. Predecessor: PREDECESSOR_ID. Follow docs/self-session.md C1; acknowledge before retirement."
```

The first prompt includes the checkpoint path, exact chain pointer, predecessor
id, next action and whether this is a whole or partial transfer. Use the client's
baton syntax when invoking the skill: Codex `$baton PATH`, Claude `/baton PATH`.
Pass prompts as literal argv values (Python subprocess argv lists are preferred).

Persist the returned successor id and creation receipt beside the checkpoint.
Verify native inspect shows the expected provider/model/cwd/workspace, no parent,
the verified unattended mode and no pending permissions; an id alone proves
creation only. If creation times out, inspect native state and retain uncertainty
instead of relaunching. The successor reads the exact checkpoint, verifies its
SHA256 and repository HEAD, and sends the predecessor an acknowledgement naming
both agent ids, checkpoint digest, HEAD and its accepted next action. Preserve
that acknowledgement beside the checkpoint; a send receipt is not acceptance.
After the predecessor receives the exact acknowledgement, it ends its turn and
stops project writes. The successor then verifies predecessor idle/no pending
permissions, archives only that id with `paseo agent archive PREDECESSOR_ID`
(without `--force`), and verifies archived readback before reconciling the
exclusive workspace claim and continuing writes. An archive timeout requires
inspect before retry. A partial transfer leaves the predecessor running.

If native identity/mode checks or acknowledgement cannot be completed, preserve
the checkpoint and predecessor, report the precise blocker, and continue safe
work in the existing session where possible. Operator typing is never a fallback;
do not inject reset commands into a terminal. Unsupported runtime remains a
blocker, not a successful handoff.

## D. Duplicates, partial failures and status

```
bin/ade-self-session status --record /absolute/state/TRANSACTION.json
bin/ade-self-session reconcile --record /absolute/state/handoff-PREDECESSOR_UUID.json
```

`status` reads persisted state only, with no native probes or writes. A per-record
nonblocking lock serializes effects; atomic fsynced intents/receipts survive
interruption. Repeating handoff from the same predecessor never creates another
successor. If native creation times out or returns an invalid receipt, retain
`creation-unknown`. The predecessor's explicit `reconcile` requires exactly one
native agent matching the unique handoff label and verified identity/mode.
Zero or multiple matches block; no create is replayed. A failed/ambiguous handoff
keeps the briefing, original files and predecessor available. Conflicting acks
are refused. Do not delete transaction files to force an automatic retry.

Exit 0 means the requested step reached its reported state (`requested`,
`awaiting-ack`, `acknowledged`, `archived`); exit 1 means blocked/unknown. Only
`archived` is completed handoff. Compaction has no completion-confirmed state.
Missing CLI/daemon, unsupported provider/mode and malformed state fail explicitly.
The default is ordinary YOLO; the supported mode helper is shared with the
ordinary-agent mode restoration, not a second provider-mode table.

## E. Native source evidence and limits

Read-only source inspection, getpaseo/paseo
`4df5307eaab6b22d06fe54a45c68211b3413f45c` (package `0.16.0-beta.2`):

- [`agent/run.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/commands/agent/run.ts): explicit workspace, caller identity, mode, label and creation receipt; no exposed idempotency key.
- [`agent/send.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/commands/agent/send.ts): native prompt submission, queued delivery and message-processing receipts.
- [`agent/inspect.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/commands/agent/inspect.ts), [`agent/archive.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/commands/agent/archive.ts): exact runtime readback and non-force running-agent refusal.
- [`utils/timeline.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/utils/timeline.ts): CLI log projection discards entry IDs/timestamps.
- [`claude/agent.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/providers/claude/agent.ts), [`codex-app-server-agent.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/providers/codex-app-server-agent.ts), [`pi/agent.ts`](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/providers/pi/agent.ts): native compact command handling; Pi error catch also emits a completed marker.

Installed older hosts may lack `--home`, exact inspect fields or modes. Such
hosts are unsupported until observed; source compatibility is not live runtime
acceptance. There is no automatic restart loop, cross-host transfer, forced
archive, claim takeover or provider acceptance change.

### E1. Completion adapter still required for verified self-compaction

The missing contract is a daemon-owned operation ID bound to the exact agent
and native session, with queryable requested/running/completed/failed outcomes.
An idempotency token must return the original operation on a retry, including
after a disconnected caller. Provider start acknowledgements must remain pending;
only the matching native success boundary may complete the operation. Pi's error
path must produce failure even if its UI closes a compaction marker. Another
manual or automatic compaction must not complete this request. This needs source
and fixture validation for each provider plus installed-host acceptance before
ADE can report verified completion. No such API is invented or deployed here.
