---
name: baton
description: >-
  Start-of-session resume from the Tier 1 pointer: follow session-handoff's
  Reader protocol for this directory, or its chain discovery when cwd resolves
  to none. Use when the operator types /baton or /resume, or says "baton",
  "pick up the baton", "resume", "pick up where we left off" or "continue this
  task" at the start of a session.
---

# Baton — resume a task workspace from its Tier 1 pointer

**Provider scope (2026-10-25; Pi-only 2026-11-08).** Compaction (Claude/Pi auto-compaction or an archived OpenCode
`ade_compact`) continues an existing session; it does not start a new baton. Only resume a fresh session after the
owned Tier 1 checkpoint is durable and the supported lifecycle controller has acknowledged that successor. Never
clear a parent session to make a child resume. See [context hygiene](../../docs/context-hygiene.md).

After a whole-session handoff, the predecessor runs `ade-self-session handoff`
with its durable checkpoint; the new agent resumes from that checkpoint and its
exact Tier 1 pointer. See [self-session](../../docs/self-session.md#c-self-handoff-to-a-new-session)
for `accept` / `finish` and the agent-run fallback. The predecessor launches the
successor itself; no operator reset or pasted prompt is required.

**Syntax is per client (2026-10-25).** In Claude Code the skill is typed `/baton`. In Codex a skill is invoked with
`$` (`$baton`, `$baton PATH`) and `/` is reserved for Codex's built-ins (`/new`, `/compact`, `/quit`): a `/baton` typed
into a Codex composer is just text and starts nothing (seen live 2026-10-25, three Enters later it still sat in the
composer). So a Codex successor's first prompt is `'$baton PATH'` (single-quoted for the shell). The same skill answers
to either spelling; treat `$baton PATH` exactly like `/baton PATH`. Never write `$baton` for a Claude agent.

`/baton` never clears, compacts or starts a new session itself (a `/baton` that started a new session would
recurse). If the pointer
has nothing to resume (no open work, `latest_handoff` already finished), say
so and offer the `loose` Rule 4 choices (handoff and continue, finish and
archive, keep working); never write another handoff automatically.

A `/baton` can arrive as a successor's first prompt, a dispatched slice's brief,
or an explicit operator resume request. Treat all three alike for reading.
For a self-session transaction, read the preserved checkpoint/record, acknowledge
it with `accept`, wait for predecessor idle, then retire it with `finish`.
For an agent-run fallback, follow the same document's C1 acknowledgement and
verified idle-only archive checks. Reconcile claim ownership before writes;
then tell siblings your new id. A partial-transfer brief keeps its predecessor
running. A dispatched slice never retires its parent's session.

This is a thin entry point, not a separate protocol. Follow the
`session-handoff` skill's **Reader protocol** section exactly (read
`SESSION_LOG.md` if present, check sidecars newer than `updated_at`, run
the staleness check against real `HEAD`, state a resume plan before
touching anything, bootstrap a minimal log if none exists — never ask
the operator for information the file already answers).

**Which chain, before resolving by directory (2026-10-25).** A `/baton` after a handoff belongs to the chain that
session just handed off, and the directory can name a different one: a fresh load watcher resumed the repo's `main`
chain while its own was `load-spike-monitor-t`. A successor's first prompt names its chain's `SESSION_LOG.md`: resume
THAT chain (`session-handoff` chain discovery, `--dir .../chains/<key>`); after a bare `/clear`, the newest handoff of
this agent's own chain wins. A
directory-resolved pointer whose owner is another live session is not yours: say so and look further.
**Live owner: ask before the first write (2026-11-01).** After resolving any chain, run `session-handoff`'s
**Owner check** (Reader protocol; the one wording: how to match `session_id` to a fleet row for claude,
Pi, codex and Paseo logs — archived omp/OpenCode transcript rows are history only — the fail-closed rule when
nothing matches, the exemptions for your own chain, the named successor and your own chain after `/clear` or
`/new`). It applies only before the first write or resume; a read-only `/baton` just reports the owner.
Reconciled with the paragraph above: a directory-resolved pointer owned by another live session is not yours,
look further; a chain that is yours by `/new` or the operator's naming but that a live other session also owns
is asked about first. Incident: 2026-10-31, a `/baton` after `/clear` merged PR 173 ahead of PR 177.

If the operator invoked this with no argument, resolve the current
directory against the Tier 1 path convention in `session-handoff` (or,
if you were handed an explicit path in the prompt, use that instead of
resolving from cwd). If cwd doesn't resolve (e.g. running in the bare
home directory), that is NOT a dead end — go straight to
`session-handoff`'s **Chain discovery fallback** (step 0 of its Reader
protocol) instead of asking the operator to supply a path.

## Re-arm detached jobs (after the resume plan, before other work)

Background work does not carry over on its own: a `run_in_background` task or
waiter belongs to the session that started it. What survives is on disk: the
report path and `.done` marker named under `## Detached jobs` in the handoff,
plus any legacy bigteam job record
(`~/.local/state/bigteam/<task>/jobs/<name>.json`) a handoff still lists.
**Do not run retired Wave 6 dispatch-shim check / resume / reap subcommands** —
those are gone for live teaching (E6 / Wave 6 follow-up); Paseo-native wait and
artifact checks replace them.

For each open job named under `## Detached jobs` in the handoff (or, with no
handoff, each legacy record without a `"closed"` key under the task directory
the Tier 1 pointer names; never adopt a record whose `owner` session is still
alive and is not the handoff's author):

1. If its `done` path already exists, skip the wait: read the report (step 4).
2. If a Paseo agent id is known, wait with `paseo wait <id> --json` (or
   `paseo ls -a -g --json` filtered on your `ade.*` labels) until the agent is
   idle, then classify by the report / `.done` artifacts — the same meanings
   `skills/fan-out` Collect / the retired `report_finished` contract use: last
   non-blank line `DONE`, **or** `DONE` followed by one `AC_DONE:` verdict line
   = delivered; report present but unfinished / still running = wait again;
   missing report or a last line `NO-REPORT: …` = no-report; first line
   `BLOCKED:` = blocked. Quota pauses continue in place via Paseo's
   session-guard and usage-auto-resume plugins (2026-11-06); there is no
   resume CLI to invent.
3. If the work is unfinished and the agent id still exists, steer it with
   `paseo send <id> --prompt "…" --behavior steer --json --no-wait` (ask for
   `ack <your id>` when delivery matters). If the agent is gone, re-launch with
   `paseo run` under a **new** `ade.name` / brief, never a shim `resume`.
   Otherwise start any handoff-supplied waiter command as **its own
   `run_in_background` Bash call**, one per job, then carry on with the resume
   plan — only the waiter is new when the underlying work is already running.
4. Point a legacy record at this session so the next handoff lists it: set
   `owner` to this session's id, from the shared resolver (a successor inherits its predecessor's
   `$CLAUDE_CODE_SESSION_ID`, which is stale):
   `o=$(python3 ~/src/djbclark-ade/bin/claude_identity.py) && jq --arg o "$o" '.owner=$o' f > f.tmp && mv -f f.tmp f || echo "no session id: owner left unchanged" >&2`
   (no `|| echo $CLAUDE_CODE_SESSION_ID` fallback: that is the predecessor's stale id).
5. When the waiter returns, read the report, act on it, then **close the
   record** by appending `"closed": <epoch seconds>` with the same
   temp-file-and-`mv -f` form (`.closed=(now|floor)`). Records are closed, never
   deleted.

If a waiter times out (it is bounded) with no `.done`, look again with
`paseo ls -a -g --json` / `paseo agent inspect <id> --json`: a live agent is
left alone (re-arm the waiter); a gone agent with no report is a no-report /
lost slice — re-launch under a new name if the work still matters. Never judge
liveness by hand from `launchctl list` or `ps`: pids are reused after a reboot
(2026-10-17: trackpad-settings read as running for hours). There is no
`reap --install` replacement; `paseo ls -g` shows what runs.

`/resume` is the same thing under its older name (the `resume` skill was
folded in here on 2026-10-08; Claude Code keeps a `/resume` command wrapper
that loads this skill, next to its own built-in `/resume` session picker).

Do not duplicate the reader protocol's steps here — if they ever change,
they change in exactly one place (`session-handoff`'s SKILL.md), not two.

**Archived (OpenCode):** the native `ade_compact` tool was OpenCode V2 Go's manual compaction path; it is not a
live client under Pi-only (2026-11-08). See `docs/context-hygiene.md` §3 (archive). Write the checkpoint first and
require the normal host identity/acknowledgment checks for a lifecycle cycle.
