# Context hygiene — 2026-10-25

Context capacity is a correctness ceiling, not a cost budget. Cached input is
billed again on every request, and Go models debit the same monthly allowance
at different rates. Choose a suitable economical model before trying to save
money by repeatedly compacting an expensive one.

## 1. Natural task boundaries

1. At a completed task, checkpoint before beginning unrelated work. Write the
   owned Tier 1 log and handoff with absolute paths, branch/head, dirty files,
   unresolved decisions, active job records, unread results and exact next steps.
2. A top-level session on a supported host runs the `handoff` skill and lets its
   Step 9 queue one new-session/baton cycle. A dispatched slice writes a
   document-only handoff; it must never clear or archive its parent.
3. Never throw away an unsent draft, interrupt a running worker, or reset before
   the checkpoint is durable. Re-arm existing jobs instead of launching their
   work again. A failed lifecycle operation is reported, not retried in a loop.
4. A larger fixed instruction/tool baseline is not removable conversation.
   Repeated compactions of that baseline waste tokens. Preserve the checkpoint,
   reduce the attached instructions/tools, or continue on a suitable model.

## 2. Earlier Claude nudges

The Claude hook warns after 32,000 tokens of growth and recommends a handoff at
the next completed-task boundary from 120,000 total input tokens. It still
accounts for growth from the post-compaction floor and suppresses repeated
warnings within a tier. These warnings do not interrupt a turn or clear context.
The hard tier (2026-10-28) fires at +140k of growth or 217k total, whichever comes
first: 50k below the ~267k wall where Claude Code auto-compacts (300,000 less its
33k buffer), so a turn in progress can finish its edit and hand off. The total
trigger also covers regrowth after a compaction (floor ~104k), where +140k would
land 23k from the wall. The hook runs only when a prompt is submitted, so its text
tells the agent how many tool rounds fit before the wall.
A compaction written mid-turn (followed by more tool rounds, so no boundary is the newest record) is
found by searching every byte appended to the transcript since the previous prompt, as raw bytes in
1 MB chunks (cap 64 MB, then the last 2 MB); only a `system` `compact_boundary` record counts.

Claude's existing `autoCompactWindow` stays at 300,000. Measurements that motivated
its growth and cooldown guards showed substantial summary/cache-write overhead;
lowering that window indiscriminately can cost more. Those Claude measurements
must not be presented as OpenCode Go prices or compaction thresholds.

## 3. Native OpenCode compaction

Use OpenCode V2's own compaction API at a safe point, including for an ACP
session. Do not type Claude slash commands into a presumed parent terminal.
The [native Go context plugin](../opencode-plugins/go-context/README.md) warns
at 64k and compacts at 96k plus 32k growth (hard trigger 128k) for routine models;
costly models warn at 32k, compact at 64k plus growth and hard-trigger at 96k.
These are local initial policy values, not vendor recommendations. Use current input plus cached reads/writes;
lifetime token totals and output totals do not measure current context.

The plugin adds the `ade_compact` tool, scoped by the native tool context. Use
it for manual native compaction. The plugin never rewrites shell or JavaScript
source before permission matching. A supported host controller may explicitly
supply a validated `ADE_OPENCODE_SESSION_ID` and `ADE_OPENCODE_DIRECTORY` for
`bin/self-slash "/compact"` to call the same guarded RPC in its exact location.
The RPC and `ade_compact` use the **same** provider/session
verification, durable pending state, cooldown and ineffective-baseline block as
automatic compaction. No separate shell cooldown or direct compact endpoint is
used. ACP launches scrub both inherited session ID and native directory.
Model/provider switches preserve session-level pending, cooldown and retry
blocks; changing models cannot admit another summary charge.
Acceptance is not completion; native compaction events confirm completion.
An uncertain write is persisted and never blindly retried; a failed lookup is
only a read failure, eligible for retry after the cooldown. `--dry-run` makes
no API calls. If the plugin is unavailable, the helper refuses rather than
falling back to an unguarded compact POST.

Native compaction does not accept the Claude `/compact <focus>` syntax here.
Save the focus in the checkpoint first. `/new`, `/clear` and `/reset` through
the scoped native path fail closed: a native reset must have both a durable
owned handoff and a supported, acknowledged successor/baton path. A successful
compaction request alone is not that evidence. Existing supported host lifecycle
paths remain available when their own identity and ownership checks pass.

OpenCode V2 settings are `compaction.auto`, `compaction.keep.tokens` and
`compaction.buffer`; `agents.compaction.model` chooses its summarizer. The
buffer is relative to model capacity, not an absolute cost cap. Do not copy V1
`reserved` or pruning settings into V2. Background compaction is not enabled as
a cost optimization: an unused speculative summary still costs tokens.

## 4. Verification

On 2026-10-25 the actual guard loaded on an isolated OpenCode 2.1.4 server and
answered its read-only status RPC (`ready: true`, no probe session known).
The native `self-slash` path also reached the guard and refused a nonexistent
session through the real RPC transport. Both probes used a temporary HOME and
private server, with zero inference or compaction calls. This verifies setup
and transport, not a paid production compaction or real event sequence.
A cold plugin listing did not initialize plugins; checking that proxy alone
would have produced a false negative. Native RPC schemas also reject regex
patterns by default, so the guard validates session IDs in code. Isolate shell
startup too (`BASH_ENV=/dev/null`, no `ENV`) in native test wrappers; a user
startup file can replace the test PATH. The native `self-slash` branch preserves
the caller's CLI selection rather than forcing a Homebrew copy.


Test offline with fake native APIs and separate temporary session state. Cover
provider/session identity, concurrent and duplicate requests, uncertain writes,
compaction completion, out-of-order usage, fixed-baseline loops and parent
lifecycle protection. Do not make paid inference requests just to test a guard.

Local focused tests use the full `bg` path. Record the explicit decision first:

```bash
~/src/djbclark-ade/bin/load-watch ci decide /absolute/worktree local "Small offline focused checks; full matrix on GitHub"
~/ops/site-private/bin/bg python3 -m pytest tests/test_opencode_self_compact.py
```

## 5. Primary sources

1. [OpenCode V2 compaction](https://opencode.ai/v2/docs/compaction): safe-point
   scheduling, recent-tail retention, completion events, fixed-baseline limits
   and speculative summary cost.
2. [OpenCode Go usage limits](https://opencode.ai/v2/docs/console/go/#usage-limits)
   and [allowance accounting](https://opencode.ai/v2/docs/console/api/inference/#cost).
3. [OpenCode V2 plugins](https://opencode.ai/v2/docs/plugins): native server
   hooks and plugin discovery. Check the installed SDK against these docs;
   similar V1 names do not establish a V2 hook contract.

## 6. Live readout: `bin/context-watch` (2026-10-28)

`bin/context-watch` prints, for each running Claude Code agent, its context size against the
compaction ceiling that actually triggers, fullest first:

```
d3df4a46 sudo-secretspec secrets-collect low findings 241k/267k (90%) wall in 26k
c7fbc11d ade-ops-pt 153k/267k (57%) wall in 114k
```

It exists because `paseo inspect` carries no context fields and Paseo's own bar divides by a 1M
window and ignores `autoCompactWindow` (upstream getpaseo/paseo#4949, open 2026-10-28). Flags:
`--json` (list of records for scripts), `--min-pct N` (hide emptier agents and unknown sizes; compared
unrounded), `--source auto|paseo|recent`, `--recent-minutes M` (both numbers finite and not negative,
else exit 2). Read-only, writes not even bytecode, exit 0 always (2 for bad usage). Titles and cwd go
through `fleet.py`'s `clean_text` onto one line; ids must be uuids. It is
not wired into `fleet-watch` or `settings.json`.

1. **Tokens.** The newest non-sidechain assistant usage block of the session transcript,
   `input + cache_read + cache_creation`: `_last_context_tokens` of
   `claude/hooks/context_size_nudge.py`, imported from the same checkout, so the nudge hook and this
   readout read one number. A transcript whose newest record is a `compact_boundary` prints
   `compacted` (no request since); an unreadable one prints `?`. Only the last 2 MB of the transcript is
   read (the hook's limit): an agent whose newest usage block is further back (one turn of huge tool
   output) prints `?` although the transcript is fine.
2. **Ceiling, per agent.** The agent's window minus the hook's `AUTO_COMPACT_BUFFER` (33,000,
   imported). Window = min(configured, model window). Configured: `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
   of the `context-watch` process (assumed to beat settings), else `modelSettings[<model>].autoCompactWindow`,
   else `autoCompactWindow` of `~/.claude/settings.json` (300,000 today, so 267,000); `"auto"` counts as
   unset. Model window: 1M for a `[1m]` id, 200k for Haiku (Claude Code caps the window at the model's),
   unknown for any other id; the model comes from the provider string (`claude/<model>`), else the
   transcript's newest assistant record. With neither: 1M when settings `model` carries `[1m]`, else
   200k (a guess). Not read, because unknowable from outside: the agent's own env, project settings,
   `--autocompact`. The nudge hook hard-codes its own 300,000 window; only the buffer is shared, so
   the two disagree if the setting changes.
3. **Which agents.** `paseo ls -g --background --json` supplies the agent ids and titles for every `claude...`
   provider; it carries no session id, so the session is `persistence.sessionId` in
   `~/.paseo/agents/*/<agent id>.json` and the transcript is `~/.claude/projects/*/<sessionId>.jsonl`.
   An agent with no state file prints `?`: the newest transcript of its cwd is not guessed because
   several agents share a cwd. If `paseo` is missing, fails or prints no JSON, the fallback lists
   top-level transcripts modified in the last 30 minutes (id = session id, title = cwd basename),
   which also covers Claude Code in herdr, Orca or a bare terminal. `--source recent` forces it.
4. **Tests.** `tests/test_context_watch.py` runs the script against a scratch HOME, `PASEO_HOME`
   and a fake `paseo` (`CONTEXT_WATCH_PASEO`).
