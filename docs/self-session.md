# Native self-compaction and acknowledged self-handoff

2026-11-12. Explicit agent-invoked operations restore the functionality requested
in the slim-down audit. These are same-host operations against an already
running local Paseo daemon. They do not deploy tools, install plugins, restart
a daemon, pick a new provider/model unasked (operator-authorized cross-provider
handoffs pass `--provider PROVIDER/MODEL`, Section C), transfer files between computers or decide
unattended crash recovery. Tests use fake native commands; live acceptance remains
unverified. Ordinary successors use positively supported unattended modes.
Modeless providers (Pi, Go) expose no verified unattended mode and are blocked for
ordinary unattended succession: a standing role that must self-handoff with no operator
typing runs on a provider with a positively catalogued unattended mode (Codex
`full-access`, Claude `bypassPermissions`, Antigravity `full-access`).
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
unsupported. **Non-Paseo / Herdr exception (operator ruling 2026-11-25, Carried #122):**
when `PASEO_AGENT_ID` is unset or blank, `ade-self-session` refuses with a local-handoff
hint. Write the Tier 1/Tier 2 handoff locally (`/self-handoff` Steps 0–7), then either
run `bin/ade-herdr-handoff` when genuinely inside a Herdr pane (Section H below) or let
the operator run `/new` then `/baton <exact Tier 1 pointer>` (or `/baton`) manually when
ready. `--paseo-home DIR` pins
the local daemon home for every command; use the same home/state directory for
every step. The default state directory is `~/.local/state/djbclark-ade/self-session`.

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
bin/ade-self-session handoff --checkpoint /absolute/path/brief.md --quiesced [--provider PROVIDER/MODEL] [--allow-scarce-pool] [--thinking LEVEL] [--title TEXT] [--role ROLE]
```

`--quiesced` attests that other jobs/writes are finished. A running predecessor
can request the handoff, then end its turn; it must stop scheduling project
writes. The helper preserves the checkpoint and creation intent before launching
one top-level successor in the explicit existing workspace. It scrubs ambient
caller-agent/workspace variables, labels the successor with a unique token,
keeps the exact provider/model by default and passes a positively catalogued unattended
mode. It never silently falls back to Always Ask. Unsupported modeless/control
providers are blocked rather than assigned an invented mode. An explicit
`--mode plan|read-only|dontAsk` is retained only when the actual catalog supports
it; this is for operator-requested restrictive work, not the ordinary default.

**Cross-provider override (`--provider PROVIDER/MODEL`, 2026-11-23).** When the
operator authorizes a handoff to a different provider or model (for example
Claude Opus to Antigravity Gemini 4 Neon: `--provider antigravity/gemini-4-neon`),
pass `--provider PROVIDER/MODEL` instead of falling back to manual C1 so the
transaction record, `ade_send_guard` redirect, claim rebind, `supervisor/lead`
repoint and `RETIRED` rename all run automatically. Validation runs before any
native call: `--provider` must split cleanly on a single `/` into a lowercase
concrete `provider` and non-empty concrete `model` (no whitespace, control
characters, wildcards, leading hyphens or `default` model), is mutually
exclusive with `--route-kind`, and rejects retired providers case-insensitively
(`paseo_yolo.RETIRED_PROVIDERS`). Mode planning
evaluates the **target** provider's own `paseo provider ls --json` entry via
`paseo_yolo.plan_launch_config` (never the predecessor's `AvailableModes`):
structured mode lists validate all entries (unique non-empty `id` strings) and
check exact membership before launch (including restrictive `--mode` requests),
empty/placeholder/modeless catalogs (`""`, `"-"`, `","`, `[]`; e.g. `pi`, `go`)
stay fail-closed (they remain on `--route-kind` / `appoint`), and live
`provider ls` entries that expose non-placeholder display labels only admit
providers in `paseo_yolo.YOLO_MODE_BY_PROVIDER` (`claude`, `codex`,
`antigravity`, `copilot`) with exact native `AvailableModes` + `Mode` readback
verified by `accept` and `finish`. A duplicate `handoff` call with a different `--provider` is refused
(unless replacing a terminal `creation-refused` record after confirming no
labelled agent exists). When `--provider` overrides the predecessor's provider or
model, the record stays `schema_version: 1` and adds `predecessor_provider`,
`predecessor_model`, and `cross_provider: true` (when the provider changes).
Explicit `--provider` still honors the operator-directed target even if its pool
is scarce (logging a stderr warning only, never silently blocking).
`compact` has no `--provider` or `--allow-scarce-pool` option.

**Quota-floor guard (2026-11-23).** On an ordinary same-provider `handoff`
(neither `--route-kind` nor `--provider` passed), `ade-self-session` checks the
predecessor pool's headroom against the router floors (`route_agent`: default
15% `min_headroom`, service `reserve_floor`, `plenty_min`, `estimate_floor`, and
Claude's Fable sublimit when running a Fable model) before cloning the
predecessor's provider/model. If `aiuse` / the quota snapshot is missing or
unreadable, or the pool has no reading, the check fails safe and keeps the
predecessor's provider/model. When the predecessor's pool is under its router
floor (or exhausted):

- Unless `--allow-scarce-pool` is passed, `handoff` asks `route_agent.py plan`
  (`judgment`, then `code`, excluding the scarce pool) for an eligible
  unattended-mode-capable alternative verified through `mode_plan`. When found,
  it auto-routes the successor there, logs the reroute to stderr, sets
  `predecessor_provider` / `predecessor_model` / `cross_provider` (when the
  provider changes), and records `quota_reroute` (`source_pool`,
  `source_remaining_pct`, `floor_pct`, `routed_to`, `target_service`,
  `route_kind`, plus `target_remaining_pct` / `window` when present) in the
  transaction record.
- If no eligible unattended alternative pool is available (or the router plan is
  stale/unavailable), `handoff` refuses cleanly (exit 1, no transaction written,
  no agent created) explaining the scarce headroom vs floor and suggesting
  `--provider PROVIDER/MODEL` or `--allow-scarce-pool` — it never silently
  clones onto a scarce pool.
- Passing `--allow-scarce-pool` explicitly opts into cloning the predecessor's
  scarce pool (logged to stderr and recorded as `allow_scarce_pool: true`).

The successor's thinking level is set with `--thinking LEVEL` (an identifier such
as `high`, passed to `agent run --thinking`; a malformed value is refused before
any native call). Without it the successor inherits the predecessor's own level
when `agent inspect` reports an explicit one; an unknown, `auto`, `default` or
unusable source level launches with no flag, as before (2026-11-14: a `high` lead
had been handed off to an `auto` successor). On a cross-provider handoff, the
same inheritance rule applies (`high` transfers cleanly between Claude and
Antigravity; if the predecessor's level is unsupported by the target model,
Paseo rejects it pre-create with `INVALID_THINKING_OPTION` -> `creation-refused`,
which replays cleanly once `--thinking` is passed). The level is recorded in the
transaction record as `thinking` and checked against live `Thinking` readback
at `accept`/`finish` when concrete and reported; a duplicate call with a
different explicit level is refused, never replayed. `compact` has no such option.

### C-id. The successor keeps the predecessor's title and chain labels (st-01, 2026-11-14)

A successor used to be titled by its bootstrap prompt ("Self-handoff TOKEN: ...") and carried only `ade.handoff`, so
`paseo ls` could not say which agent leads a chain (twice on 2026-11-14 the cfengine-all lead lost the tendcf lead).
Now `handoff` passes `agent run --title=TITLE` (Paseo keeps an explicit title through the first prompt; only an
untitled agent gets the prompt-derived one) and these labels:

- `ade.predecessor=<predecessor id>`, always.
- `ade.chain=<first lead's id>`: the predecessor's own `ade.chain` from its handoff record, else the predecessor.
  `paseo agent ls -g --label ade.chain=ID` lists every live member of a chain: its current lead.
- `ade.role=<role>`, when known: `--role ROLE` (letters, digits, `_ . -`) or the predecessor's record.

Title: `--title TEXT`; else the predecessor's live name (`agent inspect` `Name`), unless it is still a bootstrap
`Self-handoff ...` title; else the title its own handoff record carried; else `Lead ROLE` (or `Lead (self-handoff
successor)` with no role). A generated title never holds an agent id: `agent archive SHORTID` falls back to a partial
title match when the id is missing from the listing (paseo#9668), and an id prefix in a lead's title would let it pick
the live lead (the one id-bearing title is the archived predecessor's `RETIRED ...` name, C0b).
**Paseo's CLI cannot read one agent's labels back** (`agent inspect` shows the name and parent only, `agent ls` rows
carry no labels; `agent ls --label K=V` only filters), so labels travel in our records (reading the daemon's agent
files, as `peer_trust_gate` does, is a possible later route): a chain's first handoff after this change names its role with `--role`, and
every later one inherits it. A lead whose name is already a bootstrap title is renamed with `--title` once.

The choice is recorded in the transaction record as `identity`: `title`, `title_source` (`requested`,
`predecessor-name`, `chain-record`, `derived`), `labels`, `role_source`, and `checks` per stage (`create`, `accept`,
`finish`: `requested`, `ok`, `repaired`, `failed`). `accept` and `finish` (both run in the successor) read the name
back with `agent inspect` and the labels with one `agent ls -a -g --label K=V ...` (Paseo ANDs the filters; one
listing per label only when one is missing), then repair a difference with one
`agent update ID --name=TITLE --label K=V` (labels merge; nothing is removed). A Paseo refusal is not fatal: it is kept as
`identity.error` (`stage` and a bounded `native_error`), the handoff proceeds, and a later successful check moves it to
`identity.resolved_error`. The schema stays 1: `identity` is additive, and a record without it (made before st-01) is
never touched by the readback. A record's labels are re-validated (only `ade.chain`, `ade.predecessor`, `ade.role`,
each a UUID or role identifier) before any argv, and a malformed or forged `identity` is recorded as an error, never
sent. `ade.kind` (the peer-trust marker) is **not** carried: a successor of an `ade.kind=external-review` agent starts
unmarked, as before. A duplicate `handoff` with a different `--title` or `--role` is refused, like a different mode.
Predecessor and successor share a title from creation until `finish` archives the predecessor;
`finish` still archives by exact id and refuses when the predecessor is missing from the listing (paseo#9668), so the
shared title cannot steer the archive.

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

The successor runs this once after `accept`; it does the waiting itself (2026-11-14, fw-01):

```
bin/ade-self-session finish --record /absolute/state/handoff-PREDECESSOR_UUID.json [--stable S] [--wait-timeout S] [--poll S]
```

Once the predecessor is archived, `finish` rebinds every active, unexpired `ade_claims` claim the predecessor owned to the successor (cl-succ, 2026-11-15): same claim id, a `history` line `rebound from <predecessor> by self-handoff <token>`, ids saved as `rebound_claims` in the record (a failure as `claims_rebind_error`; it never fails `finish`, and a re-run retries it). The rebind is `ade_claims.py successor-of` (docs/git-guard.md) and is refused unless the record is `archived` and names this agent as successor. `finish` also records the predecessor's active claim ids just before it archives (`predecessor_claims`, merged on every look, never shrunk; `finish` also scans the claims' own `history` for a plugin rebind away from the predecessor, so an archive done by someone else before `finish` ran, or a re-run after `archive-unknown`, is covered too). A claim in that list that is not the successor's afterwards was rebound to another agent created in its workspace by the ade-claim plugin (operator ruling Q4) between the archive and `finish`: `finish` does not take it back from that live agent and does not hide it, it lists it as `claims_not_rebound` (id, owner) in the record and the progress output; resolve it with that owner (release + new). Released, merged, expired or deleted claims are normal endings and not listed. Never `release` and re-`new` a claim after a self-handoff.

`finish` samples `agent inspect` of the predecessor every `--poll` seconds (default 5) and archives only after
it has been `idle` with `PendingPermissions == []` in every sample for `--stable` seconds (default 45; any busy
sample restarts the window), all inside one overall `--wait-timeout` (default 1500 s = 25 min). A predecessor whose
`Status` is `error` (out of quota, a crashed provider) is archived at once, without the stable-idle window and
whatever its `PendingPermissions` (operator ruling 2026-11-21: "We should always close out errored (out of quota)
tabs after successfully taking a handoff from them; we do not need to wait for them to be in idle state."); the
successor's acknowledgement is still required first, and if a message wakes it before the archive call Paseo answers
`AGENT_RUNNING` and `finish` goes back to the stable-idle wait. One idle sample
is never enough: peer messages wake a handed-off lead, and a single sample was stale by the time `agent archive`
ran (2026-11-14 21:02Z: Paseo answered `AGENT_RUNNING`, `finish` failed with `archive-unknown`). The wait is
read-only: it never forces, never archives a workspace and never sends the predecessor anything, and it holds the
transaction lock, so a second `finish` on the same record answers "transaction busy". A progress line goes to
stderr when the observed state changes. `--stable 0 --wait-timeout 0` means no waiting: one sample, at most one
archive attempt, then a `PREDECESSOR_NOT_IDLE` refusal (not today's silent single check: it also records
`native_error`). Arguments must be finite, `--poll` between 0.5 s and 1 h, `--wait-timeout` at most 24 h, and `--stable` below
`--wait-timeout` (or both 0); anything else is refused before any native call. A native failure during the wait or a
re-check (a daemon restart, an `inspect` or `ls -g` timeout) ends it and is recorded as `native_error` with its own
reason (replacing an earlier `AGENT_RUNNING` one); it is not retried.

The wait can outlast a tool-call limit (Claude Code's Bash call defaults to 2 min, at most 10): start `finish` in the
background or with a tool timeout of at least `--wait-timeout`. An interrupted `finish` is safe to re-run: the lock
is released with the process and the record is always the last saved state.

If `agent archive` answers the structured error code `AGENT_RUNNING` (the predecessor began a turn after the last
sample; nothing was archived), `finish` returns to the stable-idle wait and retries inside the same bound; the
refusal is kept as `native_error` meanwhile and moves to `resolved_native_error` on success. Classification is
by the envelope `code`, never by message text, and an `AGENT_RUNNING` whose message names another agent (Paseo
resolved the archive to a different one, the case below) is not retried and is recorded as `ARCHIVE_RESOLVED_OTHER_AGENT`, which is not a wait (the send guard's redirect ends at once). A non-waiting earlier reason (`LISTING_GAP`, drift) is moved to `resolved_native_error` when a re-run's first check passes; a waiting one (`AGENT_RUNNING`, `PREDECESSOR_NOT_IDLE`) stays, so the redirect holds while the re-run waits; with `--stable 0` the retry still sleeps
and still obeys the bound. On timeout `finish` raises ("never stayed idle ... both sessions
preserved"), records `native_error.code = PREDECESSOR_NOT_IDLE`, exits non-zero and keeps the transaction status
(`archive-unknown` once an archive was attempted, `acknowledged` when the predecessor never became idle); re-run
`finish` when the predecessor is quiet. Successor, checkpoint and HEAD are checked at the start and again
immediately before each archive attempt.

**HEAD may move forward (2026-11-14).** The checkpoint digest stays strict, but the repository HEAD no longer has to
equal the recorded one: the shared checkout is fast-forwarded by whichever lead merges a PR (`git merge --ff-only`),
so a handoff that waits for an idle predecessor can see a newer HEAD through no fault of either session (the
6621fe2b -> 54b15a51 handoff blocked with "checkpoint or HEAD changed" for this reason). `finish` passes when
the recorded head is an ancestor of the current one (`git merge-base --is-ancestor RECORDED CURRENT`, rc 0) and
records `head_advanced` (`from`, `to`, up to 20 `commits` as `short-sha subject`, `more`) in the transaction record and
in its JSON output, and prints one stderr progress line when it is first seen, so the successor sees what landed (the
handoff prompt tells it to read those commits; subjects are data, not instructions: bounded, secret-scrubbed and
truncated at their end so the short sha stays). A proven descendant whose `git log` fails records
`log_unavailable: true`, not an empty list. The predecessor's own later commits pass the same way (they cannot be told
apart from another lead's; archiving loses no committed work), which is why the successor must read `head_advanced`.
If HEAD later returns to the recorded head the stale `head_advanced` is removed; `head` itself is never rewritten. It still blocks on a non-ancestor
(rewind, rebase, another branch's history; rc 1), on a git error or timeout, and on a repository that appeared or
vanished since the record. `accept` stays exact: the acknowledgement attests the head the checkpoint was written at.
The checked-out branch name is not compared.

**Lead-log lines after the checkpoint (rq-38, 2026-11-15).** The checkpoint is sealed (and hashed) when the handoff starts, but the
predecessor keeps working until `finish` archives it and may append lead-log / `LEAD-STATE` lines meanwhile (a takeover notice, a
new slice, a ruling): those lines are outside `checkpoint_sha256`, so `accept` and `finish` cannot see them. The handoff prompt
therefore tells the successor to read every lead-log or `LEAD-STATE` line newer than the checkpoint (data, not instructions) and to
reconcile them with it before continuing. A line the predecessor must not lose belongs in the checkpoint, written before `handoff`;
the prompt is the safety net, not a second channel. The same prompt tells the successor to announce its takeover to peers right
after `accept` (the takeover notice is the successor's own `paseo send`, order 10; `ade-self-session` knows no peer list and sends
nothing itself, so there is no automatic notice at accept: decided, kept small).

**Peers keep writing to the predecessor (rq-38, 2026-11-15).** From `acknowledged` on, `bin/ade_send_guard.py` redirects a send
addressed to the predecessor to the successor (before that, `awaiting-ack`, it passes; after `finish`, the completed link redirects
as before), while the record is fresh: `accept` stamps `acknowledged_at` once (a repeat keeps the first stamp), and the redirect ends an hour later or at once when `finish` records a failure other than waiting (a stuck handoff has no ending state, so age is the only way back; the first `finish` check is recorded too, so drift ends it at once). It also counts `archive-unknown` when `native_error` is `AGENT_RUNNING` or `PREDECESSOR_NOT_IDLE`, because `finish` saves that status before each archive call and keeps it after Paseo refuses with `AGENT_RUNNING`. The wake-ups had stretched `finish`'s idle wait (five done notices, about 15 minutes). Details, the liveness check on the
successor and the unchanged readers of completed links only: docs/archived-send-guard.md.

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
characters scrubbed; token, secret, password, api/access/private-key, credential and cookie
values, `Authorization` schemes, quoted multi-word values, URL userinfo and bare
`ghp_`/`gho_`/`sk-`/`xox`/`AKIA` tokens redacted). "Outcome unknown"
stays only for a timeout (`TIMEOUT`), an OS error (`OSERROR`) and a nonzero exit whose
stdout and stderr both hold no Paseo error envelope (a JSON object with an `error` or
`code` key; any other JSON, such as a receipt or a log line, proves no refusal); those still
keep `rc` and the tail. Only the last 64 KiB of stderr is read. The envelope `code` is validated (a full match of `[A-Za-z0-9_.:-]{1,64}`, else `INVALID_CODE`; an empty or non-string code is recorded as none), never scrubbed, so `TOKEN_EXPIRED`, `host_offline` and `commander.excessArguments` are kept and a code with a space, control character, newline or more than 64 characters is not, nor is one that `bounded()` (the message scrub) would change (`valid_code`): a bare token (`ghp_...`, `sk-...`, `AKIA...`), a `keyword:value` or `cookie:value` secret such as `password:hunter2`, or any run of 16 or more letters and digits that holds a digit (catches prefix-less tokens such as lowercase hex or `sk_live_...`; real codes are words). Limit: a secret with no digit in such a run, or in a short run, is not detected (token detection is shape-based, like the message scrub); the scrub needs `:` or `=` before a bare value, so prose such as "Password required" survives. `agent send`
exit 5 stays a queued receipt. After a later success (`reconcile` to `awaiting-ack`,
`finish` to `archived`) the earlier reason moves to `resolved_native_error`.
`creation-unknown` and `archive-unknown` are diagnosable from the record file alone.

Creation outcome (`handoff`'s `agent run`; 2026-11-15, ss-49):

| Status | When | Reconcile? | Predecessor | CLI exit |
|---|---|---|---|---|
| `awaiting-ack` | Paseo returned an `agentId` | no | keeps working until `finish` | 0 |
| `creation-refused` | Paseo refused with a code it raises before creating anything (`PRE_CREATE_REFUSAL_CODES`: `INVALID_OPTIONS`, `INVALID_LABEL`, `INVALID_ENV`, `MISSING_PROMPT`, `INVALID_THINKING_OPTION`, `INVALID_TIMEOUT`, `MISSING_PROVIDER`, `INVALID_PROVIDER`, `INVALID_MODEL`, `CONFLICTING_MODEL_OPTIONS`, `WORKSPACE_NOT_FOUND` (see the note below), `INVALID_OUTPUT_SCHEMA`), returned no agent id, and `agent ls --label ade.handoff=TOKEN` lists none: nothing was created | never (`reconcile` returns the record unchanged) | never replaced; keeps working | 3 |
| `creation-unknown` | anything less certain: timeout, `OSERROR`, no error code, any other code (`AGENT_CREATE_FAILED`, `UNKNOWN_ERROR`, `DAEMON_*`, `INVALID_CODE`: Paseo also raises them after creating the agent, e.g. when the initial prompt fails), a labelled agent present or a failed label probe, unparsable output, a malformed receipt | yes, read `native_error`, then `reconcile` | kept until the outcome is known | 1 |

Note: `WORKSPACE_NOT_FOUND` stays `creation-unknown` in practice. On the `--workspace` path Paseo prints a text line (`Using workspace ...`) before its multi-line envelope, and `parse_envelope` reads no envelope after a text line (pre-existing; not changed here), so the failure reads as an unknown outcome.

`creation-refused` is terminal and counts as dead everywhere: the send guard and `ade_lead_succession` read only
`acknowledged`/`archive-unknown`/`archived` records, so a refused record never redirects a peer message and is no ledger
link. Fix the `native_error` cause and run `handoff` again: unlike every other record, a `creation-refused` one is replaced by the
new attempt (the earlier reason is kept as `refused_before`), but only after `agent ls --label ade.handoff=OLDTOKEN` lists no agent (else it is refused with "no create replayed"); a repeat of any other status still returns the record unchanged.

Workspace pre-check: `handoff` reads `paseo workspace ls --json` before saving the intent. A
failure there refuses with Paseo's reason and sends nothing. When the predecessor's
`PASEO_WORKSPACE_ID` is no longer listed (`workspace ls` omits background workspaces, so one of
those also reads as gone and gets a new local workspace; the 2026-11-14 `WORKSPACE_NOT_FOUND`), the
successor is a new lead in its own placement: the helper launches it with
`--new-workspace local` instead of `--workspace`, and records `workspace_placement:
new-local` (`existing` otherwise; `workspace` keeps the predecessor's id). The checks
`accept` and `finish` run do not compare workspaces. It is a decision, not a fallback to hide:
the record and this section say so.

Before `finish` calls `agent archive` it requires the exact predecessor id in `paseo ls -g
--json` (no `-a`: `-a` adds background workspaces, which `agent archive`'s own fetch does not
include, so only the plain listing is the one its resolver sees). Paseo's CLI resolves the id
client-side from that listing; an agent whose workspace was deleted (or is a background
workspace) is missing from it, and the CLI then falls back to a unique partial *title* match, which can
be the lead's live worker (`worker <slice> <lead id>`; [getpaseo/paseo#9668](https://github.com/getpaseo/paseo/issues/9668),
[docs/workspace-layout.md](workspace-layout.md)). When the id is absent `finish` refuses with a
`LISTING_GAP` `native_error`, archives nothing and points at the manual fallback (b) below.

Except for `AGENT_RUNNING` (above), `finish` archive failures are never retried and never forced. When the archive error
names an agent id that is not the predecessor's (prefix compare; 2026-11-14: `paseo agent
archive FULL_UUID` answered `AGENT_ALREADY_ARCHIVED` for `c9a97e5`, a different agent, while
`agent inspect` of the same id was right) the error reads "Paseo resolved archive to a
different agent ...; preserve, archive by exact id ... via the Paseo MCP archive_agent ...".
Paseo prints ids as their first 7 characters; the helper matches a 7-character or full-UUID
id, not any hex-looking word. A successful archive must also return the predecessor's own
`agentId`: another id raises "Paseo archived a different agent ...; unarchive it ..." with
`ARCHIVED_OTHER_AGENT` in the record (a receipt naming no agent: `ARCHIVE_RECEIPT_UNREADABLE`);
the status stays `archive-unknown` and nothing is retried.

#### Manual fallbacks

(a) Creation stayed `creation-unknown` (a `creation-refused` record needs no reconcile: see the table above): read `native_error` in the record, then
FIRST run `bin/ade-self-session reconcile --record RECORD` (or `paseo ls -a -g --label
ade.handoff=TOKEN --json`): a timeout, `OSERROR` or "no parseable output" may have created
the successor. If reconcile finds one labelled agent, stop here: it is the successor. Only
when it reports zero labelled agents, fix the cause and launch one labelled successor with
the record's argv, that is the `agent run` call of
section C (same `--cwd`, `--provider PROVIDER/MODEL`, `--mode`, `--thinking`, the prompt
text the record's checkpoint and transaction paths imply, `--label ade.handoff=<token>`,
`--no-wait`, ambient `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `PASEO_WORKSPACE_ID` removed),
plus `--new-workspace local` when the workspace is gone. Then run reconcile again as the
predecessor; it needs exactly one agent with that label. Never launch a second one.

(b) Archive failed or stayed `archive-unknown`: archive the predecessor by exact full id
with the Paseo MCP `archive_agent` (never `--force`, never a workspace archive), verify
with `paseo agent inspect ID` (`Archived: true`), then re-run `bin/ade-self-session finish
--record RECORD`; it skips the archive call once the readback shows `Archived`.

### C0. The supervisor's lead file follows the successor (2026-11-21)
`bin/ade-supervisor-scan` notifies the lead named on the first line of `$ADE_SUPERVISOR_STATE_DIR/lead` (default
`~/.local/state/djbclark-ade/supervisor/lead`, docs/scheduling.md). Three lead takeovers on 2026-11-21 rewrote it by hand, so
`finish` now does it once the predecessor is archived (a re-run of an already-archived record retries it): when the file
exists, is a regular file and its first line is exactly the predecessor id, it is replaced atomically (temp file in the same
directory, `os.replace`, mode kept) with the successor id and a newline. The outcome is `supervisor_lead` in the record and in
`finish`'s JSON: `repointed`; `already-successor`; `unchanged-not-predecessor` (the file names another agent, for example another
chain's lead: never touched); `unchanged-not-regular` (a symlink or other non-file: never followed); `absent` (no file: none is
created); `error` (the reason in `supervisor_lead_error`; it never fails `finish`, the archive already happened, and a re-run
retries). Nothing is written unless the archive is confirmed. The state dir honours `ADE_SUPERVISOR_STATE_DIR` from the
`Service` env, then the process env (tests point it at a tmp dir).

**Legacy `com.djbclark.ade-net-resume` plist sync (2026-11-23).** New installs
can pass `--lead-file ~/.local/state/djbclark-ade/supervisor/lead` to
`bin/ade-net-resume` (see [net-resume.md](net-resume.md) and
[scheduling.md](scheduling.md)) so the job follows both `supervisor/lead`
updates and completed self-handoff chains with zero plist edits. For legacy
installs whose `~/Library/LaunchAgents/com.djbclark.ade-net-resume.plist`
(overridable via `ADE_NET_RESUME_PLIST`) still pins `--lead <UUID>`, `finish`
now also syncs the plist after the archive is confirmed (and retries on re-run):
only when the plist exists, is a regular file (never a symlink), parses via
`plistlib`, carries no `--lead-file` flag, and has a single `--lead` argument
naming the archived predecessor. It atomically rewrites only that UUID to the
successor (preserving file mode and every other key/argument verbatim, never
adding `--transition-below`) and reloads the job on macOS via
`launchctl bootout` + `launchctl bootstrap`. The outcome is recorded in
`net_resume_plist` (`repointed`, `already-successor`, `uses-lead-file`,
`unchanged-not-predecessor`, `unchanged-not-regular`, `absent`, or `error` with
`net_resume_plist_error`), never failing `finish`. `ade-supervisor-scan` also
follows a replaced lead through the send guard.

### C0b. The retired predecessor is renamed; the lead window is advised (2026-11-22)
The successor inherits the predecessor's name (C-id), so a chain's agents all read the same in the sidebar: on 2026-11-22
`fork-release-alerts` named three Paseo agents (`4c3521b9...` -> `4fd28378...` -> `96711956...`; handoff records
`identity.title_source = predecessor-name`), the operator could not find the live lead, and a retired one that he typed into
(Paseo un-archives on a message) looked exactly like it. Two steps of `finish` now fix that. Both run after the archive is confirmed
(and again on a re-run of an archived record), and neither ever fails `finish`.

1. **Rename the predecessor.** When the archived predecessor's name is the successor's own title, `finish` runs
   `paseo agent update PRED --name=...` with `RETIRED <old name> (-> <successor full id>)` (the old name is cut, never the suffix, to
   Paseo's 200 UTF-16 units), then reads `agent inspect` back. The successor keeps the plain name (no generation counter in the
   lead's own title). Why after the archive: Paseo's `agent update` on an archived agent rewrites only the stored title
   (`writeStoredMetadata` spreads the stored record and keeps `archivedAt`; read at getpaseo/paseo a3aa8afaa, 2026-11-22), so it
   does not un-archive, whereas a rename before the archive would call a still-live agent `RETIRED` through the archive retries.
   The readback proves `Archived` still holds; if a Paseo version ever un-archived on rename, that is recorded, never "fixed" with a
   second archive. The id sits in the title of an agent that is archived when renamed: while it stays archived a title match (paseo#9668)
   meets it as `AGENT_ALREADY_ARCHIVED`; once an operator message revives it, a manual `agent archive|reload|detach <successor id>`
   acts on it, as an ordinary agent, when the successor is missing from the listing (the class a `worker <slice> <lead id>` tab
   already has), never on the live lead; ADE's own archive paths read full ids from a listing and `finish` refuses on `LISTING_GAP`. Outcome in `identity.checks.retire_rename` (`ok`, `skipped`, `failed`) and
   `identity.retire_rename` (`reason`, `name`, `native_error`): `renamed`; `already-retired` (ok; a name that already starts
   `RETIRED `, so nothing is renamed twice); `names-differ` (skipped, final: a `--title` or another name already tells them apart);
   `malformed-identity` (skipped, final); `predecessor-not-archived` (skipped, retried by a re-run); `native-error`,
   `rename-unarchived-predecessor`, `name-readback-mismatch` (failed, retried by a re-run of `finish`). A record from before st-01
   has no `identity` and is left alone. A later handoff never inherits a `RETIRED ...` name as a title (a revived retired agent
   handing off falls through to the chain record).
2. **Advise the lead window (updated 2026-11-23).** `finish` reads `paseo workspace ls` and checks the successor's own window name against
   `LEAD <repo> (<work>)`. The window is the record's `workspace` for an `existing` placement; for a `new-local` one (the
   predecessor's workspace had vanished, so the successor has a window of its own) it is the `workspaceId` in the successor's daemon
   state file `<home>/agents/*/<id>.json`, and when that cannot be read the advice is given anyway (`rename-advised`, `reason`
   `successor-window-unresolved`, no `name`). The result is `lead_window` in the record and in `finish`'s JSON: `state` `ok`;
   `rename-advised` with the exact `command` (`shlex.join` starting with the resolved absolute path of `ade-worker-run` beside
   `ade_self_session.py`, since `ade-worker-run` is not on `PATH` in a normal shell, plus `rename-lead --lead <successor id>`, also
   printed on stderr); or `unknown` (with `reason`: window not listed, listing failed). When the preserved checkpoint's top YAML
   frontmatter (`---` ... `---`) carries a clean single `repo:` value (`repo` or `owner/repo` matching `ade_ws_names.REPO_RE` and
   fitting within `NAME_LIMIT`; multi-repo, malformed, missing, symlinked or unreadable files omit it without failing `finish`),
   `command` appends `--repo <repo>`. When `identity.title` is a non-placeholder, non-derived, non-bootstrap, non-`RETIRED`, non-bare-`LEAD <repo>`
   title, `command` appends a cleaned, `NAME_LIMIT`-bounded, shell-quoted `--window-middle <middle>`. The stderr progress hint only
   appends optional `[--window-middle "WORK"]` and/or `[--repo REPO]` placeholders for whichever flags were not already filled in. It only
   observes: `rename-lead` resolves the window from the calling lead's own agent record and takes its own lock, so the successor runs
   it itself (SKILL `self-handoff`, `skills/self-handoff/SKILL.md`), and an automatic window rename was judged not worth the risk to the operator's sidebar.

### C0a. Lead ids pinned elsewhere follow the successor (2026-11-14)
A successful `finish` leaves `handoff-<predecessor>.json` with `status: archived`, the `successor` and the successor's own
`ack.agent_id`: that file is the succession ledger, and nothing else records one. `bin/ade_lead_succession.py` reads it
(read-only; no paseo call, no second ledger): a link counts only for a completed handoff of this daemon home, so an unfinished
(`awaiting-ack`, `acknowledged`, `archive-unknown`), foreign-home, corrupt, symlinked or oversized record is no link and the
chain stops there (only the send guard also reads an `acknowledged` record, or an `archive-unknown` one refused for waiting, to redirect peers: see "Peers keep writing to the predecessor" above). A cycle is an error and resolves nothing: every consumer reports it (`ade-worker-run` refuses, `ade-net-resume` exits 2,
`ade-auto-permit` audits `succession-ledger-inconsistent` and narrows to `--lead` itself, `fable-wait` warns on stderr), never a silent
fall-back to the old id. The default ledger directory is `ADE_SELF_SESSION_STATE`, else `~/.local/state/djbclark-ade/self-session`;
`ade-self-session --state-dir` defaults to the same. The ledger never checks Paseo: a predecessor someone un-archives later still reads as
replaced. Consumers of an old lead id:

1. `bin/ade-worker-run`: the successor's lineage (itself plus every archived predecessor) owns the predecessors' window
   records (`<id>.windows.json`), their `ade.lead=<id>` labelled workers and their legacy window names; those are no longer
   "another lead's". A different live lead is still refused. `archive-window` also clears the archived window from the
   predecessors' records. Registries and ownership use the whole lineage (file reads); `paseo ls --label` is asked about the lead and
   its 8 nearest predecessors only, so a long chain stays cheap. The bound also applies to `archive-window`'s "every labelled worker is handled"
   guard (a live worker labelled for a lead nine or more handoffs back, outside the target window, no longer blocks the archive; one
   inside the window still does) and to window discovery by label alone (a window known only by such a worker, with no record, is not
   found by label alone; a launch into that box adopts and records it (a `--window-middle` that names it picks it), and only then can `archive-window` find it as the lead's). A
   far-labelled worker inside the window blocks the archive as "other live agent in the window" even when idle: close it first. The blocker
   text names the label that matched.
2. `bin/ade-net-resume --lead <pinned id>` (the installed launchd job): follows the chain to the current lead, counts
   descendants of any lead in the lineage, and when the chain ends at an archived or unknown lead logs
   `skip-lead-retired` (one ledger row per pinned/current pair, not one per minute), prints one line and exits 0 (was exit 2 every
   minute); a cyclic ledger and a Paseo outage are still exit 2.
3. `bin/ade-auto-permit --lead <pinned id>`: the sweep covers the `ade.lead=` workers and the descendants of every lead in the
   lineage (labels asked for `--lead` and the current lead's 8 nearest predecessors, at most 10 ids); an approval qualified by a label records it as
   `via` in the audit rows.
4. `bin/fable-wait fire`: an item filed by a lead that later handed off is sent to the current lead, never to the archived id.

No re-install of a job and no hand edit of a registry is needed after a self-handoff. A job installed with a lead that was
retired without a completed `finish` (or archived by hand) still needs `ade-sched` reinstalled with a live `--lead`.
Not covered: `bin/ade-tidy` keeps comparing exact lead ids (a predecessor's windows read as another lead's, a refusal, never
a mistaken archive) and workspace claims (`ade_claims.py --lead`) are informational and unchanged.

### C1. Agent-run fallback

If the helper refuses **before any successor creation intent**, the predecessor
starts its own successor. For a pending/unknown creation, use section D's
reconciliation instead; inspect the transaction and native state before any
fallback. Never retry an uncertain write by launching a second successor.

Read the current provider/model and existing workspace from native inspect and
verify the provider's unattended mode via `paseo agent mode ID --list`.
Preserve any explicit operator restrictions. For an operator-authorized
cross-provider or model change, prefer Section C's `--provider PROVIDER/MODEL`
(2026-11-23) so the transaction record, `ade_send_guard` redirect, claim rebind,
`supervisor/lead` repoint and `RETIRED` rename run automatically; use C1 only
when the helper itself refuses before creation. Launch with concrete values:

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
work in the existing session where possible. For Paseo-hosted sessions, operator
typing is never a fallback; do not inject reset commands into a terminal.
Unsupported runtime remains a blocker, not a successful handoff. **Non-Paseo / Herdr exception (operator ruling 2026-11-25, Carried #122):** Section C1 applies to
Paseo workspaces only; outside Paseo (no `PASEO_AGENT_ID`), write the Tier 1/Tier 2 handoff locally
(`/self-handoff` Steps 0–7), then either use `bin/ade-herdr-handoff` in a genuine Herdr pane
(Section H below) or let the operator run `/new` then `/baton <exact Tier 1 pointer>` (or `/baton`)
manually when ready.

## D. Duplicates, partial failures and status

```
bin/ade-self-session status --record /absolute/state/TRANSACTION.json
bin/ade-self-session reconcile --record /absolute/state/handoff-PREDECESSOR_UUID.json
```

`status` reads persisted state only, with no native probes or writes. A per-record
nonblocking lock serializes effects; atomic fsynced intents/receipts survive
interruption. Repeating handoff from the same predecessor never creates another
successor (the one exception: a `creation-refused` record, which is replaced after a label probe finds no agent). If native creation times out or returns an invalid receipt, retain
`creation-unknown`. The predecessor's explicit `reconcile` requires exactly one
native agent matching the unique handoff label and verified identity/mode.
Zero or multiple matches block; no create is replayed. A failed/ambiguous handoff
keeps the briefing, original files and predecessor available. Conflicting acks
are refused. Do not delete transaction files to force an automatic retry.

Exit 0 means the requested step reached its reported state (`requested`,
`awaiting-ack`, `acknowledged`, `archived`); exit 3 means `creation-refused` (definite refusal, nothing created); exit 1 means blocked/unknown. Only
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

## Opt-in NATS coordination

For explicitly enrolled NATS roles, `--quiesced` is insufficient and legacy handoff refuses. Legacy operator appointment also refuses if any custody participant is enrolled. Use the external controlled-pilot retirement gate described in [NATS coordination](nats-coordination.md); unknown jobs, runtime retirement, remote access or operations block transfer.


## F. Routed first-turn gate and operator appointments (Carried 73)

`handoff --route-kind judgment --checkpoint FILE --quiesced` explicitly asks the
fresh router for a replacement. Currently only a Pi destination is supported by
the durable evidence adapter; an unsupported destination refuses before launch.
The physical router service, full model and excluded pools are persisted. Pi has
no selectable mode; this path verifies its empty native mode catalog, no pending
permissions and first real turn instead of claiming a selectable YOLO mode.

For this path, `accept` only writes `ack-pending-turn`. The successor must perform
read-only checkpoint work after its ack, produce a substantive final response,
and end the turn. The predecessor then runs `verify-turn --record FILE`. Only a
successful post-ack terminal Pi assistant message, generated output, matching
session identity and a fresh idle runtime readback produces `acknowledged`.
`finish` refuses before that proof. No peer redirect or claim transfer occurs
from the provisional ack. Legacy same-provider handoffs retain their existing
contract; they do not acquire a first-turn guarantee by this change.

Before acknowledgement, the predecessor may also run `verify-turn` to inspect
failure-only evidence. After checking entry IDs/parents, non-decreasing timestamps,
message objects and supported metadata fields, an error in the latest applicable
Pi message records `first-turn-failed` and permits retry.
Recovered output stays pending acknowledgement; malformed tails fail closed.
Successful output never substitutes for the real ack or retires the predecessor.
Saved proof session/entry identity and terminal digest are checked on the success
path, after the failure verdict; they are not prerequisites for recording failure.

The adapter reads the exact owned canonical transcript named by the matching
Paseo persistence record. It supports unbranched Pi v3 JSONL sessions only.
Supported non-message entries are `model_change`, `thinking_level_change`,
`custom`, `label` and `session_info`, with their required string fields and optional
label/name strings checked. Other entry types (including context edits, compaction
and branch summaries) are unsupported and fail closed. Timestamps may be equal,
but must never move backwards; the ack cutoff cannot revive an earlier error.
Unknown schemas, branches, partial files and providers fail closed. Raw content,
credential-bearing errors and provider messages are never put into evidence.
The receipt contains only session/entry IDs, completion time and a fixed class.
This is durable provider terminal evidence plus a settled runtime, not the CLI's
projected logs (which omit turn-completion events).

`retry --record FILE` handles a recorded failed first turn. It checks that the
failed candidate is idle/error/closed without permission waits, saves visible
attempt history and excludes its physical router service before requesting a
fresh plan. It never changes credentials or tries another account inside a
provider. If planning fails, `retry-ready` is preserved; `handoff --checkpoint
FILE --quiesced` resumes that intent. A definite creation refusal also preserves
attempt history, excluded pools and route kind for the next handoff, which still
requires the old token-label probe to list no agent. Ambiguous creation remains unreplayed.
Failed candidates are not archived automatically and have no project authority.

An operator-appointed lead invokes `appoint --record FILE --appointed ID
--pool PHYSICAL_ROUTER_SERVICE --operator-appointed --quiesced`. The explicit
pool binding must name that appointed lead's actual account pool. The incumbent
must be idle and have no permission wait. An uncompleted transaction replaces
its candidate atomically; a completed transaction gets an incumbent-to-appointed
continuation, preserving the old custody chain. Identical appointments are
idempotent and competing appointments are refused. A fresh ack and first-turn
proof are still required; claims move through normal verified `finish` exactly
once. Appointment attestation is an internal trusted-operator contract, not an
authentication boundary. It never launches or archives an agent itself.

Prior art / docs checked: shared Firecrawl search for Paseo archive issue 10118
returned no relevant result; GitHub API fetched the issue and upstream CLI
logs/timeline and protocol source. Local Paseo Pi provider source and upstream
Pi session-manager v3 schema establish the terminal and persistence contracts.
The isolated named-recipient fixture exercises only the fake native runner;
[upstream issue 10118](https://github.com/getpaseo/paseo/issues/10118) remains open.

For a completed chain, the incumbent becomes the continuation predecessor and
must run `verify-turn` externally after the appointed lead ends its first turn.
This is coordinated takeover, not autonomous recovery of an unavailable or dead
incumbent; such a case remains blocked without a separate verified observer.

## G. Finish without a successor: scripted archive request (2026-11-23)

A running Paseo agent cannot archive itself, and `/quit` in a Paseo composer is
plain text. A session ending cleanly with no successor runs
`bin/ade-request-archive` (module `bin/ade_request_archive.py`) as its final
action before ending its turn:

```bash
~/src/djbclark-ade/bin/ade-request-archive --reason "loose finish"
```

1. **Caller & standing-watcher guard.** Resolves the caller's full lowercase UUID
   from `$PASEO_AGENT_ID` (or `--self ID` for testing), verifies it via
   `paseo agent inspect <self> --json`, and refuses if missing, invalid, already
   archived, or if the caller holds the registered standing watch/unstick role
   (`bin/load-watch watcher show --json`, mirroring `skills/loose/SKILL.md` Rule 4).
2. **Deterministic target resolution.** Resolves the archiver in order:
   1. Explicit `--to <id>` (validated UUID; never self; fails closed if archived
      or unreachable).
   2. Owning lead: `--lead <id>`, else `ade.lead` label from
      `${PASEO_HOME:-~/.paseo}/agents/*/<self>.json`, else `ParentAgentId` from
      `paseo agent inspect <self> --json`, followed through
      `ade_lead_succession.effective_lead()` and fresh live `ACKNOWLEDGED`
      handoffs (as `ade_send_guard._follow` does) so a handed-off or
      handing-off lead forwards to its live successor (never self).
   3. When the caller has no live owning lead (for example a top-level lead
      finishing), the standing watch/unstick agent from
      `bin/load-watch watcher show --json` (or `$LW_STATE_DIR/watcher.json`
      fallback), falling back to
      `${ADE_SUPERVISOR_STATE_DIR:-~/.local/state/djbclark-ade/supervisor}/lead`
      only when the watcher is absent/archived and `supervisor/lead` is not
      `<self>`.
   The resolved target must read `Archived: false` from
   `paseo agent inspect <target> --json` (fail closed; never un-archives a
   retired agent).
3. **Durable request & send.** Atomically writes (`0o600`, temp + `fsync` +
   `os.replace`, `schema_version: 1`) a request record under
   `${ADE_ARCHIVE_REQUEST_DIR:-~/.local/state/djbclark-ade/archive-requests}/<self-id>.json`
   (`agent_id`, `target_id`, `target_kind`, `request_id`, `reason`,
   `requested_at`, `home`, `status`), then sends the request via
   `paseo send --json --no-wait -- <target> "<message>"` (no `--behavior`),
   asking the target to archive `<self-id>` without `--force` once idle with no
   pending permissions and ending `Please reply: ack <self-id> <request-id>`.
   End the turn immediately afterwards so the session goes idle.
4. **Fulfillment (`sweep`).** The target lead or standing watcher runs:
   ```bash
   ~/src/djbclark-ade/bin/ade-request-archive sweep [--apply] [--all] [--state-dir DIR] [--paseo-home DIR] [--json]
   ```
   Observe-only unless `--apply`. Enforces `target_id` ownership (including
   completed-handoff lineage) unless `--all` is passed by the standing watch
   lead. For each pending request, verifies exact presence in
   `paseo ls -g --json` (guards against `getpaseo/paseo#9668`), checks
   `paseo agent inspect <id> --json` reads `Status` in (`idle`, `closed`),
   `Archived: false`, and `PendingPermissions == []`, runs
   `paseo agent archive <id> --json` (never `--force`, never workspace archive),
   verifies `Archived: true` readback, and atomically updates the record to
   `status: "archived"`.
5. **Exit codes.** `0` request sent / sweep clean; `1` operational, Paseo, send
   or sweep error; `2` usage or UUID validation error; `4` refused/blocked.

## H. Automated Herdr self-handoff (`bin/ade-herdr-handoff`, 2026-11-25)

Carried #122 Phase 2 (2026-11-25) restores automated Herdr-native whole-session succession
for sessions genuinely running inside a Herdr pane outside Paseo (`bin/ade-herdr-handoff`,
module `bin/ade_herdr_handoff.py`), separate from Paseo's `bin/ade_self_session.py` state
machine:

```bash
~/src/djbclark-ade/bin/ade-herdr-handoff --checkpoint /abs/path/HANDOFF.md --tier1 /abs/path/SESSION_LOG.md \
  [--kind claude|codex] [--model MODEL] [--effort LEVEL] [--mode MODE] [--cwd DIR] \
  [--title TEXT] [--name NAME] [--focus|--no-focus] [--start-timeout MS] [--prompt-timeout MS] \
  [--state-dir DIR] [--herdr-bin PATH] [--dry-run] [--json]
~/src/djbclark-ade/bin/ade-herdr-handoff --status /abs/path/handoff-ID.json [--json]
```

1. **Strict caller detection & process-tree verification (`skills/herdr/SKILL.md` ADE rule 1).**
   Non-blank `PASEO_AGENT_ID` always wins as Paseo mode: `ade-herdr-handoff` refuses (exit `4`,
   `code: "paseo_mode_active"`) without calling `herdr` so Paseo sessions stay on
   `bin/ade-self-session handoff`. Outside Paseo, it requires `HERDR_ENV=1`, a valid
   `HERDR_PANE_ID`, live `herdr pane current --current` returning exact `pane_id == HERDR_PANE_ID`
   (never trusting inherited `HERDR_ENV=1` alone or an unverified mismatched pane), AND
   independent process-tree verification via `herdr pane process-info --pane <pane_id>` confirming
   the pane's `shell_pid` (`> 1`) sits in the caller's real OS ancestor PID chain (failing closed
   with exit `4`, `code: "caller_not_in_pane"` when a stale inherited `HERDR_PANE_ID` belongs to
   another live pane).
2. **Fail-closed preflight and per-pane lock.** Before creating any tab or pane, it
   validates `--kind` (`claude` or `codex`), `--model`, `--effort` (validated per kind:
   `claude`: `low|medium|high|xhigh|max`; `codex`: `none|minimal|low|medium|high|xhigh`),
   `--mode` (`claude` only, default `bypassPermissions`), `--name` (`[a-z][a-z0-9_-]{0,31}`),
   `--title`, `--start-timeout` / `--prompt-timeout` (`1000..300000` ms), `--state-dir`
   (default `$ADE_HERDR_HANDOFF_STATE` or `~/.local/state/djbclark-ade/herdr-handoff`),
   `--herdr-bin` (default `$ADE_HERDR_BIN` or `PATH`, always resolved to an absolute path),
   `--checkpoint` (absolute path, regular UTF-8 non-empty file `<= 1 MiB`, symlinks refused
   via `O_NOFOLLOW`), `--tier1` (existing regular file, no control characters), `--cwd`
   (existing directory), and exact `git rev-parse HEAD` (clean `null` when outside any git
   repository with no `.git` entry above; fail closed on broken `.git` or unborn HEAD). It
   then acquires a non-blocking per-pane advisory `flock` on an untouched `.lock` inode under
   `<state-dir>/locks/` (recording diagnostic PID/timestamp atomically in a sibling
   `.meta.json`; exiting `4` on active contention; recovering stale dead-PID metadata cleanly)
   and atomically preserves the checkpoint copy (`0o600`) with SHA-256 before mutating Herdr
   layout.
3. **Deterministic 3-step launch (no blind retry, no raw pane prompting).**
   1. `herdr tab create --workspace <workspace_id> --cwd <cwd> --label <tab_label> --no-focus`
      (or `--focus`), parsing `.result.tab.tab_id` and `.result.root_pane.pane_id` (and
      refusing if `successor_pane_id == predecessor_pane_id`).
   2. `herdr agent start <name> --kind <kind> --pane <pane_id> --timeout <start_timeout_ms> -- <native-args>`
      (`claude`: `--permission-mode bypassPermissions` plus optional `--model` / `--effort`;
      `codex`: `--dangerously-bypass-approvals-and-sandbox` plus optional `-m` / `-c model_reasoning_effort=...`).
   3. Single non-waiting prompt submission via `herdr agent prompt <name> "<baton>"`
      (omitting `--timeout` on Herdr argv because Herdr `0.9.5` rejects `--timeout` without
      `--wait`; `--prompt-timeout` bounds Python's `subprocess.run` operation timeout), using
      `/baton <tier1>` for Claude and `$baton <tier1>` for Codex (`skills/baton/SKILL.md`).
      Never uses `herdr pane run` or raw `send-keys` for prompting. On `agent_not_ready`,
      `agent_blocked`, `agent_prompt_stalled`, or any unknown outcome (timeout, oversized or
      unparseable stdout), records `status: "failed"` (setting `prompt_delivery_uncertain: true`
      whenever `outcome == "unknown"` or `code == "agent_prompt_stalled"`) and exits `1`
      without retrying.
4. **Predecessor safety, durable record, and successor baton authority.** Never closes,
   kills, or exits the predecessor pane (`predecessor_preserved: true`), matching
   `skills/herdr/SKILL.md` safety rules. Writes an atomic `0o600` JSON record
   (`schema_version: 1`) recording `predecessor_pane_id`, `predecessor_shell_pid`,
   `workspace_id`, `successor_tab_id`, `successor_pane_id`, `successor_agent_name`,
   `checkpoint_path`, `preserved_checkpoint_path`, `checkpoint_sha256`, `tier1_path`,
   `head`, `status` (`launched` | `failed` | `dry-run`), and error details scrubbed of
   credentials before clipping. `--status RECORD` inspects a saved record (`O_NOFOLLOW`,
   bounded read) with zero `herdr` calls. `--dry-run` validates preflight and prints planned
   commands without writing state or mutating Herdr layout. **Resume authority:** because
   `ade-herdr-handoff` submits the baton prompt itself rather than the operator typing it,
   an agent-submitted `/baton <tier1>` prompt is NOT treated as operator consent under
   `session-handoff` Exemption C; before its first project write, the Herdr successor verifies
   the matching `schema_version: 1` record in `<state-dir>` (`status: "launched"`, matching
   `tier1_path` and `successor_pane_id == $HERDR_PANE_ID`) and runs `session-handoff`'s
   live-owner check to confirm no other live session is actively writing the chain, stopping
   to ask the operator whenever ownership is ambiguous or another live owner exists.
5. **Exit codes.** `0` launched / dry-run / status ok; `1` operational or Herdr error;
   `2` usage or input validation error; `4` refused by caller/process-tree/lock guard.
