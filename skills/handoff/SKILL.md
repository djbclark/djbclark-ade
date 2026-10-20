---
name: handoff
description: >-
  Create a deep Tier 2 handoff document, chain-tagged, DAG-linked, mined from
  the full conversation. Use when pausing substantial work, before ending a long
  session, or on "do a handoff", "create a handoff", "save session context".
---

# Handoff — Tier 2 deep recovery document

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (now at
v0.4 — the v0.4 revision only changed Tier 1/`session-handoff`; this
skill's Tier 2 mechanics are still the v0.3 content, unchanged).

## Project scope

Two regimes — pick this first, it determines the output path and Step 6's
commit flow:

- **ops-djbclark suite** (target repo is `stayturgid`, `site-djbclark`,
  `site-private`, `Shizuku`, or `ops-djbclark`): unchanged existing
  behavior. Output `~/ops/site-private/memory/handoffs/<target-repo>/` —
  committed DIRECTLY TO MASTER under site-private's own memory-data
  exception, pushed immediately (Step 6 below).
- **Any other project**: output lives inside that project's own repo, at
  `<repo-root>/docs/handoffs/`. Commit locally in that repo (Step 6 below)
  — do **not** push automatically. Pushing to a project you don't have an
  explicit standing exception for is a "visible to others" action per the
  general action-care policy; site-private's push-immediately rule is a
  specific, deliberate carve-out that repo's own AGENTS.md/CLAUDE.md
  declared, not a default other repos inherit. If that project's own
  AGENTS.md/CLAUDE.md declares an equivalent "memory is data, commit (and
  push) in place" exception, follow it and push; otherwise leave the
  commit local and tell the operator it's ready to push whenever they want.

## Guards

- Only the workspace-owning session runs this. Sub-agents never do.
- Never generate handoff-like documents freeform outside this skill.
- Only when the operator (or owning orchestrator) explicitly wants a
  handoff created now. If ambiguous, ask.
- Not in plan mode.

## Step 0 — Run the `loose` sweep silently first (operator rule, 2026-10-08)

Before Step 1, run the `loose` skill's Rule 2 sweep **for your own eyes
only**: no audit report, no `/steps` prompts, no handoff-or-quit question.
Then, for each loose end found: fix it now if it is small and inside the
session's scope (commit it), otherwise carry it into "Where We're Going"
with enough context that the next session can act on it without this
conversation (what it is, the command that shows it, the recommendation).
Why: a handoff written without the sweep hands on a list from memory, and
the sweep is what finds the gaps memory misses. (djbclark, 2026-10-08:
"automatically run /loose before /handoff but only you should see the
output, and then make sure the handoff has enough context to do those
items, or if it would make more sense, deal with them before the handoff".)

## Step 1 — Gather external state (parallel Bash, never agents)

`git log --oneline -15`, `git diff --stat`, `git status -s | ghead -30`,
`git branch --show-current`, `git rev-parse HEAD`; Beads state if
available and this is an ops-djbclark-suite repo (`bd list
--status=in_progress`) — skip this bullet entirely for other projects
unless that project also uses Beads; list existing handoffs at the
Project-scope-resolved output directory for this target repo (e.g. `ls
~/ops/site-private/memory/handoffs/<repo>/` or `ls
<repo-root>/docs/handoffs/`).

**Also list this session's open background jobs** (bigteam's job records,
Step 4 there). A record is open when it has no `"closed"` key and its `owner` is
this session (`$CLAUDE_CODE_SESSION_ID`):

```bash
for f in ~/.local/state/bigteam/*/jobs/*.json; do [ -e "$f" ] || continue
  jq -r --arg me "${CLAUDE_CODE_SESSION_ID:-}" 'select(.owner==$me and (has("closed")|not))
    | [input_filename, .report, .done, .rearm, .cmd] | @tsv' "$f"; done
```

For each row note whether the `done` path exists yet (finished but unread, or
still running). A `run_in_background` task or waiter of this session is **not**
a job record: it is a child of the session and is not promised to outlive it.

## Step 2 — Chain tag and lineage

Chain tag, first match: (1) Beads epic ID; (2) 1–4 bead IDs (list);
(3) `standalone-{4-hex}` (`python3 -c "import secrets;print(secrets.token_hex(2))"`).

Lineage is an explicit DAG:
- `handoff_id`: fresh 4-hex id.
- `parent_handoff_ids`: if this session started from a resume prompt
  naming a parent handoff file, that file's id (deterministic — primary).
  Else grep this target repo's Project-scope-resolved output directory for
  the chain tag as RECOVERY ONLY: a shared bead is a candidate, not proof — read
  the candidate's "Where We're Going"; only clear continuation makes it
  a parent, and the new doc must say `lineage: inferred`. Doubt → ask
  the operator. No parent → `[]`.

## Step 3 — Mine the conversation

Announce pass choice: Quick (<100K context) / Deep (100K–500K) /
Chunked map-reduce (500K+).

**Scope narrowed 2026-08-23: capture position and intent, not the
transcript.** Every session is archived losslessly in S1 (448k events,
indexed), so re-narrating what happened is duplicated effort that also
drifts from the record. Write what S1 cannot reconstruct — the state in
your head:

- goals, and where you actually are against them;
- work completed, concretely (files, functions, numbers);
- **FAILED approaches + why** — still the most expensive thing to
  rediscover, and the one thing a transcript buries rather than surfaces;
- decisions + the alternatives rejected, with the reason;
- open questions, blockers, dependencies, and the intended next move.

**Do not** transcribe discoveries, gotchas, signatures, or constants that
the session already contains — link to them instead. Recover any of it
with:

```bash
~/ops/site-djbclark/bin/s1_search.py search '<phrase>' --mode trigram
~/ops/site-djbclark/bin/s1_search.py neighbours <event_id> --window 5
```

Durable machine facts belong in the curated layer, not a handoff: an
operator-verified fact goes to `docs/` or the relevant skill; model-mined
leads land in `~/basic-memory/mined/` via `bin/mine_sessions.py`. A
handoff that carries them becomes a second canon that nobody updates.

## Step 4 — Write the file

Path: `<output-dir>/HANDOFF_{chain}_{slug}_{YYYY-MM-DD}_{handoff_id}.md`,
where `<output-dir>` is `~/ops/site-private/memory/handoffs/<repo>/` for
the ops-djbclark suite or `<repo-root>/docs/handoffs/` otherwise (slug:
2–4 kebab words; multi-bead chains use the primary bead in the filename).
`mkdir -p <output-dir>` if needed.

    ---
    schema_version: 1
    handoff_id: <4 hex>
    parent_handoff_ids: []
    lineage: deterministic|inferred|none
    chain: [<ids>]
    repo: <target repo>
    workspace: <task dir name>
    branch: <branch>
    head_sha: <sha>
    created_at: <ISO 8601 with offset>
    writer: claude-code
    ---
    # Handoff — <title>
    ## The Goal
    ## Where We Are
    ## What We Tried            <- failed approaches, chronological, with why
    ## Key Decisions            <- chosen AND rejected
    ## Evidence & Data          <- real numbers, file paths
    ## Operator Feedback
    ## Where We're Going        <- ordered; item 1 is THE next action
    ## Detached jobs            <- one entry per open job record, or "none"
    ## Quick Start              <- exact commands for the next session

Each `## Detached jobs` entry gives: the job file (`.../jobs/<name>.json`), the
report path, the `.done` path (and whether it exists now), the exact `rearm`
command, and one line on what the job is and what to do with its report. The
next `/baton` re-arms from these entries.

## Step 5 — Validation gate (all required; line count is NOT the gate)

- [ ] Objective stated
- [ ] Exact git state (branch, head_sha, dirty list)
- [ ] Files changed this session
- [ ] Tests run + results (or explicit "none run")
- [ ] Decisions + rejected alternatives
- [ ] Failed approaches + why
- [ ] Blockers / open questions, including every sub-agent report whose
      first line is `BLOCKED: <question>` and every dispatched slice with no
      report (`acp-dispatch check <out dir | report paths>`): an unanswered
      sub-agent question does not survive a compaction unless it is written here
- [ ] ONE explicit next action at the top of Where We're Going
- [ ] Every open job record of this session is listed under Detached jobs
      (or the section says "none"), and nothing in the doc assumes a
      `run_in_background` task or waiter survives the session
- [ ] Parent linkage (ids, or explicit none)
- [ ] Redaction: no credentials, tokens, .env values, key material,
      anywhere in the doc

Any unchecked box: fix before proceeding. Thin sections: expand from the
conversation, don't pad.

## Step 6 — Commit

**ops-djbclark suite target (memory exception flow, EXACTLY this — plain git,
per the 2026-08-23 operator decision retiring `just ops-memory-sync`; that
target's release-gating precondition was failing for site-djbclark):**

1. `cd ~/ops/site-private && git pull --rebase` — another agent may have
   written to `memory/` since you started. **If it refuses because another
   agent has unstaged edits** (common in site-private), never stash, add or
   `--autostash` them: skip the pull, do step 2, then `git fetch` and push
   only if `git status -sb` shows ahead and not behind; if behind, ask.
2. `git add memory/handoffs/<repo>/<filename> && git commit -m "memory: handoff <repo>/<filename>"`
   — memory-only commit of your own file; NOTHING else staged (other
   agents' files under `memory/handoffs/` may be untracked or modified).
3. `git push` immediately. Leave your own changes clean.

**Any other project target:**

0. If the repo's `.pre-commit-config.yaml` runs prettier, run `npx --no-install
   prettier --write <handoff file>` first: its check hook rejects the commit
   otherwise (2026-10-13, aiuse).
1. `cd <repo-root> && git add docs/handoffs/ && git commit -m "docs: handoff <slug>"`
   — handoff-only commit; nothing else staged.
2. Push only if that project's own AGENTS.md/CLAUDE.md declares an
   equivalent memory-is-data exception (see Project scope above);
   otherwise leave it committed locally and say so to the operator.

## Step 7 — Update Tier 1

Via the `session-handoff` skill's writer protocol: set `latest_handoff` to
the new handoff file's path (site-private-relative for the ops-djbclark
suite, repo-relative otherwise), refresh Current State, add a history
entry. Then report to the operator: file path, chain + lineage,
validation outcome, the next action, and (for a non-ops-djbclark target)
whether the commit was pushed or is waiting locally.

## Step 8 — Autorename the session

Last step, after the report. Run the `autorename` skill in `--auto` mode with a
title derived from this session's work (not "handoff"):

```bash
python3 ~/src/djbclark-ade/skills/autorename/autorename.py --auto "<title>"
```

It keeps a title the operator set by hand. It works in Claude Code, zcode, Grok,
cursor-agent, OpenCode, Codex in a herdr pane, and omp (once its bridge extension is
installed and omp restarted), and exits 2 without harm where it finds no supported
session; in that case skip it silently. Add its one-line result to the report.

## Step 9 — Clear and continue

Last action, after Step 8 (djbclark, 2026-10-20: "handoffs [should] immediately clear context and
then start a baton and continue running without human intervention"). Run

```bash
~/src/djbclark-ade/bin/self-slash "/new"
```

**once**, and end the turn at once (no further tool call, no question). On Paseo that sends `/clear`
to this same agent and then exactly one `/baton` into the fresh session; on herdr and Orca it sends
`/new` and then `/baton` (`self-slash` queues the `/baton` itself, `--then`, so never type or queue
one yourself). The fresh session resumes from the Tier 1 pointer Step 7 just wrote.

**Top-level session only.** A sub-agent (Agent tool, `/bigteam`, an `acp-dispatch` or `acp-run` slice)
shares or inherits the parent's agent id, so a `/new` from it would clear the PARENT's session
(2026-10-20; `acp-run` now scrubs the id and `self-slash` exits 9 when `ACP_RUN_AGENT=1`, but an
Agent-tool sub-agent carries no marker). A sub-agent or dispatched slice always treats the handoff as
document-only and never runs this step.

**What the operator can read afterwards** (2026-10-20): on Paseo the pre-`/clear` transcript is not kept
by `paseo logs` once `/baton` runs (the UI is unverified). Anything the operator must read goes into the
handoff document, the Tier 1 pointer and the hermes-ping (`~/.local/bin/hermes-ping`, sent **before** this
step's `self-slash`), not only into the final message.

If `self-slash` refuses (exit 7: the 30-minute gap check or a lifecycle already queued; or a draft
on the input line; or exit 3 outside herdr, Orca and Paseo, or on Paseo without a usable `paseo`
CLI), do not retry or loop: tell the operator the handoff is written and stop. In herdr or Orca say
`/new` is ready. On Paseo `/new` typed into the composer reaches Claude as plain text and does
nothing (only self-slash's mapping to `/clear` works), so say instead: once this agent is idle,
send `/clear`, then `/baton` (or run `~/src/djbclark-ade/bin/self-slash "/new"` again after the
gap or lock clears, which does both).

**Document only:** skip this step when a skill that clears the session itself runs the handoff, when
the operator says "doc only" or otherwise asks for the document without a restart, or when you are a
sub-agent or a dispatched slice (above). `loose` Rule 4 option 1 wants this step to run: it does not
make a handoff document-only. Say in the report that Step 9 was skipped and why.
