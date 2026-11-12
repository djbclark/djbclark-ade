# Context hygiene — 2026-10-25

Trimmed 2026-11-07 (slim-down E11); Pi-only third-party TUI 2026-11-08. The live tools are `bin/context-watch`
(how full each running Claude agent is, section 6), `bin/context-budget-check` (what a fresh session costs,
section 7) and the Claude nudge hook (`claude/hooks/context_size_nudge.py`, section 2). Compaction for current
clients includes auto-compaction and the explicit agent-invoked
[`ade-self-session`](self-session.md) native request/handoff path (restored
2026-11-12). Self-compaction preserves a checkpoint and requests native `/compact`;
it never claims completion from a send receipt. Self-handoff requires a durable
successor acknowledgement and idle-only predecessor retirement. Pi has no separate
ADE compaction plugin. Section 3 keeps archived OpenCode notes only. The old
pane-typing `self-slash` implementation remains removed; no terminal injection is
restored. Unsupported hosts/providers report their limitation.


Context capacity is a correctness ceiling, not a cost budget. Cached input is
billed again on every request, and Go models debit the same monthly allowance
at different rates. Choose a suitable economical model before trying to save
money by repeatedly compacting an expensive one.

## 1. Natural task boundaries

Terminology clarified 2026-11-04: this section describes controlled **handoffs**.
Continuous protection against unplanned interruption is the separate, planned
[checkpoint contract](checkpoint.md); a boundary handoff alone cannot provide it.

1. At a completed task, write a handoff before beginning unrelated work. Write the
   owned Tier 1 log and handoff with absolute paths, branch/head, dirty files,
   unresolved decisions, active job records, unread results and exact next steps.
2. A top-level session runs the `handoff` skill; its Step 9 leaves the operator `/clear` then `/baton`, or starts
   a successor. A dispatched slice writes a document-only handoff; it must never clear or archive its parent.
3. Never throw away an unsent draft, interrupt a running worker, or reset before
   the handoff is durable. Re-arm existing jobs instead of launching their
   work again. A failed lifecycle operation is reported, not retried in a loop.
4. A larger fixed instruction/tool baseline is not removable conversation.
   Repeated compactions of that baseline waste tokens. Preserve the handoff,
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
land 23k from the wall. The hook runs under `UserPromptSubmit` and, where the settings
register it (2026-10-29), `PostToolUse`; its text tells the agent how many tool rounds fit
before the wall and says it runs on prompt submit and between tool rounds (at most every
`POST_TOOL_CHECK_SECONDS` seconds).
A compaction written mid-turn (followed by more tool rounds, so no boundary is the newest record) is
found by searching every byte appended to the transcript since the previous prompt, as raw bytes in
1 MB chunks (cap 64 MB, then the last 2 MB); only a `system` `compact_boundary` record counts.

As of 2026-10-29, `claude/hooks/context_size_nudge.py` supports both
`UserPromptSubmit` (plain-text stdout) and `PostToolUse` (JSON
`hookSpecificOutput.additionalContext`). `agents/claude/settings.json.tmpl` registers both
(`PostToolUse`: matcher `*`, `hook-deadline 2`, timeout 20; `UserPromptSubmit`:
`hook-deadline 4`). Nothing applies the template (`agents/README.md`), so the live
`~/.claude/settings.json` gets the same entries by hand (order 11), after this code is
on the shared checkout the hook symlink points at (the sub-agent guard below must be
live first); until then the live file may run the hook on prompt submit only.
`ade-install doctor` / `just install-doctor` (2026-11-09) detects a missing registration
versus the template and prints that hand-apply hint; it never writes the live file
(queue Carried #10). Owner of the live edit: the operator (or a lead with an explicit
yes). As of 2026-11-01 one machine's live file had the `PostToolUse` entry; re-check with
doctor after any settings rewrite.
PostToolUse checks read the transcript at most once every `POST_TOOL_CHECK_SECONDS`
seconds per session; a wall-clock rollback permits a fresh check. A PostToolUse call
that carries an `agent_id` (a sub-agent's or an in-process agent-team teammate's tool
call; for a sub-agent Claude Code fires the same hooks with the parent's `session_id` and
transcript) is ignored before the throttle stamp, so it cannot spend the top-level
session's one-shot notes; a long-lived teammate therefore gets no PostToolUse nudge. Unrelated or non-string event
names are ignored; an omitted event name keeps the UserPromptSubmit default.
Each emitted early, ask, embedded mid-task or boundary note appends a JSON line to
`~/.claude/state/context-nudge-log.jsonl`, including UTC timestamp, session ID,
event, level, total tokens, growth and kind. An absolute `CONTEXT_NUDGE_LOG_PATH`
overrides the log path; relative overrides are ignored. A new log has mode 0600,
and opens reject symlinks where O_NOFOLLOW is available. Compaction resets the
nudge state but preserves this history;
at about 2 MiB the log rotates to a single `.1` backup. This records emission,
not whether the model acted on the note. Logging errors are ignored, and the
hook retains its two-second deadline. As of 2026-10-29, the usage tail reader
skips lines without usage/boundary needles and rejects at most 64 candidate
records across its 128 KiB and 2 MiB windows, without re-counting the first
window's complete lines. Exhausting that budget returns no
measurement (no nudge) rather than an older usage block; a later check retries.
An absent measurement does not advance the saved transcript size. Shared state
saves use unique temporary files in the same directory and atomic replacement.
On POSIX, a sibling lock serializes the full read/modify/write; acquisition uses
non-blocking flock attempts for at most 200 ms. If the lock is busy, unavailable
or unsupported, the hook proceeds without it: saves remain atomic, but a concurrent
update may be lost. Lock opens also reject symlinks where O_NOFOLLOW is available.
While holding the lock, each check inspects at most 128 directory entries and
removes matching `context-nudges.json.*.tmp` files older than a day; fresh files,
symlinks and directories are preserved. The two-second alarm still covers the entire hook.

Claude's existing `autoCompactWindow` stays at 300,000. Measurements that motivated
its growth and cooldown guards showed substantial summary/cache-write overhead;
lowering that window indiscriminately can cost more. Those Claude measurements
must not be presented as (archived) OpenCode Go prices or compaction thresholds.

## 3. Archived: native OpenCode compaction (not a live TUI)

> **Archive (2026-11-09).** OpenCode is not a current TUI under the Pi-only
> ruling (2026-11-08; `docs/queue.md` item 36). Keep this section for the
> `opencode-plugins/go-context` tree and Wave 6 cleanup. Do not launch OpenCode
> or teach `ade_compact` as a live path; use Claude/Pi auto-compaction and
> handoff instead.

When OpenCode was still a live client, its V2 compaction API ran at a safe
point (including ACP sessions). Do not type Claude slash commands into a
presumed parent terminal. The [native Go context plugin](../opencode-plugins/go-context/README.md)
warned at 64k and compacted at 96k plus 32k growth (hard trigger 128k) for
routine models; costly models warned at 32k, compacted at 64k plus growth and
hard-triggered at 96k. Those were local initial policy values, not vendor
recommendations. Use current input plus cached reads/writes; lifetime token
totals and output totals do not measure current context.

The plugin added the `ade_compact` tool, scoped by the native tool context, for
manual native compaction. It never rewrote shell or JavaScript source before
permission matching. (A host controller, `self-slash`, could call the same
guarded RPC until 2026-11-06.) `ade_compact` used the **same** provider/session
verification, durable pending state, cooldown and ineffective-baseline block as
automatic compaction. No separate shell cooldown or direct compact endpoint was
used. ACP launches scrubbed both inherited session ID and native directory.
Model/provider switches preserved session-level pending, cooldown and retry
blocks; changing models could not admit another summary charge. Acceptance was
not completion; native compaction events confirmed completion. An uncertain
write was persisted and never blindly retried; a failed lookup was only a read
failure, eligible for retry after the cooldown. (The `self-slash` helper's
`--dry-run` and its refusal when the plugin was unavailable went with
`bin/self-slash`, slim-down E4, 2026-11-06.)

Native compaction did not accept the Claude `/compact <focus>` syntax here.
Save the focus in the checkpoint first. `/new`, `/clear` and `/reset` through
the scoped native path failed closed: a native reset needed both a durable
owned handoff and a supported, acknowledged successor/baton path. A successful
compaction request alone was not that evidence. The successor path remains a
top-level `env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD paseo run …` that archives its
predecessor once it answers (`skills/handoff` Step 9; `self-slash --finish --successor`
went 2026-11-06).

OpenCode V2 settings were `compaction.auto`, `compaction.keep.tokens` and
`compaction.buffer`; `agents.compaction.model` chose its summarizer. The
buffer is relative to model capacity, not an absolute cost cap. Do not copy V1
`reserved` or pruning settings into V2. Background compaction was not enabled as
a cost optimization: an unused speculative summary still costs tokens.

## 4. Verification (archived OpenCode probes)

On 2026-10-25 the actual guard loaded on an isolated OpenCode 2.1.4 server and
answered its read-only status RPC (`ready: true`, no probe session known).
The native `self-slash` path (removed 2026-11-06) also reached the guard and refused a nonexistent
session through the real RPC transport. Both probes used a temporary HOME and
private server, with zero inference or compaction calls. This verified setup
and transport, not a paid production compaction or real event sequence.
A cold plugin listing did not initialize plugins; checking that proxy alone
would have produced a false negative. Native RPC schemas also reject regex
patterns by default, so the guard validates session IDs in code. Isolate shell
startup too (`BASH_ENV=/dev/null`, no `ENV`) in native test wrappers; a user
startup file can replace the test PATH.

Offline tests of the archived plugin use fake native APIs and separate temporary
session state. Cover provider/session identity, concurrent and duplicate
requests, uncertain writes, compaction completion, out-of-order usage,
fixed-baseline loops and parent lifecycle protection. Do not make paid inference
requests just to test a guard. Live Claude nudge tests remain the current path.

Local focused tests use the full `bg` path. Record the explicit decision first:

```bash
~/src/djbclark-ade/bin/load-watch ci decide /absolute/worktree local "Small offline focused checks; full matrix on GitHub"
~/ops/site-private/bin/bg bin/pytest -q tests/test_go_context_plugin.py
# Hook suites share a module basename: run separately to avoid import collisions.
~/ops/site-private/bin/bg bin/pytest -q tests/test_context_size_nudge.py
~/ops/site-private/bin/bg bin/pytest -q claude/hooks/handoff-tools/tests/test_context_size_nudge.py
```

## 5. Primary sources (archived OpenCode docs)

1. [OpenCode V2 compaction](https://opencode.ai/v2/docs/compaction): safe-point
   scheduling, recent-tail retention, completion events, fixed-baseline limits
   and speculative summary cost (historical reference only).
2. [OpenCode Go usage limits](https://opencode.ai/v2/docs/console/go/#usage-limits)
   and [allowance accounting](https://opencode.ai/v2/docs/console/api/inference/#cost)
   (historical; Go/Zen pools migrate through Pi acceptance, not the OpenCode TUI).
3. [OpenCode V2 plugins](https://opencode.ai/v2/docs/plugins): native server
   hooks and plugin discovery. Check the installed SDK against these docs only
   when touching the archived `opencode-plugins/` tree; similar V1 names do not
   establish a V2 hook contract.

## 6. Live readout: `bin/context-watch` (2026-10-28; nudge bands 2026-11-09)

`bin/context-watch` prints, for each running Claude Code agent, its context size against the
compaction ceiling that actually triggers, fullest first. Do **not** trust Paseo Desktop's own
context meter for headroom: it divides by the model-manifest window (often 1M) and ignores
`autoCompactWindow` (upstream [getpaseo/paseo#4949](https://github.com/getpaseo/paseo/issues/4949),
open 2026-10-28). The meter fix belongs upstream; this tool is the in-repo live readout that
scores against the real autoCompact wall and labels the nudge tier the Claude hook would use.

```
d3df4a46 sudo-secretspec secrets-collect low findings 241k/267k (90%) hard · wall in 26k · paseo~24%
c7fbc11d ade-ops-pt 153k/267k (57%) boundary · wall in 114k · paseo~15%
```

The band is `ok` / `early` / `boundary` / `hard` / `wall` (same ladder as
`claude/hooks/context_size_nudge.py`): `wall` at or past the autoCompact ceiling; `hard` within
`ASK_HEADROOM` (50k) of that ceiling, at the hook's `ASK_TOTAL`, or past `ASK_GROWTH` when a
baseline is known; `boundary` from `BOUNDARY_TOTAL` (120k); `early` only when
`~/.claude/state/context-nudges.json` has a baseline and growth past `EARLY_GROWTH` (32k).
`paseo~N%` is what the wrong Desktop meter would show (tokens / manifest window: 200k for Haiku,
1M otherwise), so a line that reads 90% real / `paseo~24%` is #4949 in one glance. Flags:
`--json` (list of records for scripts; adds `nudge_band`, `nudge_level`, `nudge_growth`,
`paseo_window`, `paseo_pct`), `--min-pct N` (hide emptier agents and unknown sizes; compared
unrounded), `--min-band BAND` (hide agents below `ok|early|boundary|hard|wall` and every
unknown size), `--source auto|paseo|recent`, `--recent-minutes M` (both numbers finite and not
negative, else exit 2). Read-only, writes not even bytecode, exit 0 always (2 for bad usage).
Titles and cwd go through `context-watch`'s `clean_text` (copied from the removed `fleet.py`,
2026-11-06) onto one line; ids must be uuids. It is not wired into `fleet-watch` or
`settings.json`.

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
   which also covers Claude Code outside Paseo (a bare terminal). `--source recent` forces it.
4. **Tests.** `tests/test_context_watch.py` runs the script against a scratch HOME, `PASEO_HOME`
   and a fake `paseo` (`CONTEXT_WATCH_PASEO`).

## 7. Fresh-session cost: `bin/context-budget-check` (2026-10-18; a Paseo schedule since 2026-11-06)

Runs `claude -p "/context"` (no model request) in each directory of `config/context-budget.toml` (default this repo
and `~`), compares the totals and the memory, skills and MCP rows with their budgets and with the previous night's
`~/.local/state/context-budget/<date>.json`, and sends one `hermes-ping` line on a breach or a rise. `--instruction-lint`
adds `bin/instruction-lint`'s counts, report-only (over each measured directory, so `~` covers `~/AGENTS.md` and
`~/.cursor/rules/home-agents.mdc`; or run `bin/instruction-lint --root ~` / pass those paths as FILE args — `~` in a
FILE expands). Exit 0 ok, 1 breach or rise, 3 a directory it could not measure. It
runs nightly as a Paseo schedule (J3): the `paseo schedule create` line is in the script's module docstring; the launchd job and its
`install`/`uninstall` subcommands were removed 2026-11-06 (E5). Tests: `tests/test_context_budget_check.py`.

Since 2026-11-10, its default reader adopts effective `[context_budget]` from
`config/ade.toml` or the legacy file, with per-machine `local.toml` overrides.
Directory arrays replace whole; numeric budget and directory-map leaves merge.
Missing context metadata keeps the existing code defaults. Explicit `--config`
retains an isolated legacy-file read. Invalid effective config exits 2 before
measurement, notification or state writes. `--from-file ... --dry-run` remains
the offline verification path. See [precedence and validation](config-migration.md).

This is the *baseline* half of context visibility (what a fresh session already costs before any
turn). For *live* fullness of running agents against the real autoCompact wall — and for the
Paseo Desktop meter mismatch tracked in getpaseo/paseo#4949 — use section 6's `context-watch`,
not the Desktop bar and not this nightly check.
