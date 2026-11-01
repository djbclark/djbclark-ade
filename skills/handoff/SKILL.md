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
  `<repo-root>/docs/handoffs/` — unless the project's always-loaded
  `AGENTS.md` names another directory and a push exception, which wins
  (e.g. every CFEngine/libntech tree writes to
  `~/src/cfengine-all/docs/handoffs/` and pushes there, 2026-10-20). Commit locally in that repo (Step 6 below)
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

## `/handoff paseo` routes to a durable Paseo transfer (operator, 2026-10-27)

When the arguments begin with the word `paseo` (`/handoff paseo`, `$handoff paseo`, "handoff to paseo"), this skill still writes the
owned Tier 2 document and Tier 1 pointer (Steps 1-7, below), then **does not run Step 9's same-session `/new`**: it continues with
the **paseo-handoff** skill's durable-transfer procedure (existing suitable workspace and a new real tab, live launch settings,
verified startup, explicit chain pointer, successor-owned peer notices with delivery proof, carried queued/blocked receipts). Plain
`/handoff` keeps the behaviour below unchanged. In Plan Mode `/handoff paseo` mutates nothing: it says that mode is the blocker,
keeps the destination, and resumes on the operator's "go" after Default mode returns, without asking again.

The Tier 2 document of a `paseo` handoff carries the **durable peer list** (each peer's id, title, workspace, the relay record ID and
status of every notice already sent, and the ack token each was asked for) so the successor can adopt it; see paseo-handoff,
"Peer notices belong to the successor".

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
leads used to land in `~/basic-memory/mined/` via `~/ops/site-djbclark/bin/mine_sessions.py`. That folder was moved to `~/ops/site-private/memory/basic-memory/mined/` (frozen since 2026-08-24, to be archived per queue ruling 5); nothing writes to it now, so the lead has no home yet. A
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
    ## Key Decisions            <- chosen AND rejected, as prose
    ## Decisions               <- the same decisions in indexed form, one per line (syntax below)
    ## Relations                <- indexed relations, one per line (syntax below)
    ## Evidence & Data          <- real numbers, file paths
    ## Operator Feedback
    ## Where We're Going        <- ordered; item 1 is THE next action
    ## Detached jobs            <- one entry per open job record, or "none"
    ## Quick Start              <- exact commands for the next session

`## Decisions` and `## Relations` are indexed by Basic Memory: handoffs written
to `~/ops/site-private/memory/handoffs/` become observations and relations. Use
exactly this syntax (checked 2026-10-25 against Basic Memory 0.24.1's observation and
relation parser):
- `- [decision] <choice>; rejected: <alternative>; because <reason>`
- `- [ruling] <what djbclark said, quoted> (djbclark, YYYY-MM-DD)`
- `- continues [[<previous handoff's file stem, HANDOFF_..._<id>>]]` (a handoff resolves by its file stem,
  never by its `# Handoff — <title>` heading)
- `- decided_in [[<file stem of the handoff that made the decision>]]` (the first handoff of a chain has no earlier
  one: use its own stem); a PR is no note, so give it as a Markdown link inside the observation, and end the
  line with the link plus a full stop, never with a closing parenthesis after the link (Basic Memory's parser
  drops a `[category] ...` line that contains `](` and ends in `)`): `- [decision] <choice>; rejected:
  <alternative>; because <reason>; in [PR N](https://github.com/OWNER/REPO/pull/N).`
- no `part_of [[<repo>]]`: no repo notes exist in the store, so it would never resolve (create the repo note first
  if you want that relation)

A `[ruling]` is only for something djbclark said, quoted and dated, never for
your own choice. An agent's own design choice is a `[decision]` with a
`decided_in` relation to the handoff that made it, or a PR link as above.

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
- [ ] `## Decisions` and `## Relations` use the indexed syntax; every `[ruling]` is quoted and dated
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
cursor-agent, OpenCode, Codex in a herdr pane (herdr retired from djbclark-ade 2026-10-31; that code path lives until D4/D6), and omp (once its bridge extension is
installed and omp restarted), and exits 2 without harm where it finds no supported
session; in that case skip it silently. Add its one-line result to the report.

## Step 9 — Clear and continue

**Paseo provider restriction (2026-10-31):** `/new` via `self-slash` is for Claude-provider agents only. Other providers (including omp, codex and opencode), or an unknown provider, end with `self-slash --finish --successor PROVIDER/MODEL`. Clear aliases and `/compact` refuse with exit 7 when the daemon record does not prove Claude; no `/baton` is queued after a refused clear.

**Context and provider check (2026-10-25).** Follow [context hygiene](../../docs/context-hygiene.md): start a handoff at a completed task boundary rather than carrying unrelated work into a large context. Cached reads still consume the provider allowance. If `ADE_OPENCODE_SESSION_ID` is set, this is the native OpenCode path: persist the owned checkpoint and use `self-slash "/compact"` when continuing. Do not send `/new`, `/clear` or `/reset` into a presumed parent; native reset needs a supported, acknowledged successor/baton path. Until that path is verified, this step is document-only for a native reset, and compaction is the automatic continuation mechanism.

Last action, after Step 8 (djbclark, 2026-10-20: "handoffs [should] immediately clear context and
then start a baton and continue running without human intervention"). Run

```bash
~/src/djbclark-ade/bin/self-slash "/new"
```

**once**, and end the turn at once (no further tool call, no question). On Paseo that sends `/clear`
to this same agent and then exactly one `/baton` into the fresh session; on herdr and Orca (retired from djbclark-ade 2026-10-31; `self-slash` keeps those branches until D6, never start them for new work) it sends
`/new` and then `/baton` (`self-slash` queues the `/baton` itself, `--then`, so never type or queue
one yourself). The fresh session resumes from the Tier 1 pointer Step 7 just wrote.

On a **Codex** pane (herdr reports the pane's agent as `codex`; only a herdr pane is treated as Codex, herdr being retired from djbclark-ade 2026-10-31 with this branch alive until D6) the same command sends the built-in `/new` and then
`$baton`: Codex invokes a skill with `$`, and `/baton` there is plain text that starts nothing (2026-10-25). Nothing
changes in how you call it; `self-slash` chooses the spelling and `--dry-run` prints the text it will send. If you give
`--then` yourself on Codex, single-quote the `$` so the shell keeps it: `--then '$baton /path/SESSION_LOG.md'` (the
legacy `--then "/baton /path"` is rewritten once, keeping every byte of the path). A Codex skill prompt is submitted
once, never with extra Enters, and counts as sent only when that Codex session's rollout holds the exact message;
otherwise the waiter exits 8 and logs `NOT confirmed delivered`: report that, never type it again.

**A Codex (or any non-Claude) agent on Paseo cannot use that command.** `bin/self-slash`'s `paseo_check_builtin` refuses `/new`, `/clear`, `/reset` and `/compact` there unless the Paseo provider is `claude` (exit 7, nothing sent: "daemon clear/compact is unproved"), and Codex syntax (`$baton`) is only ever produced for a herdr pane. On Paseo such an agent writes the handoff, then uses the refusal's own pointer, `self-slash --finish --successor PROVIDER/MODEL` (the successor form below), or tells the operator the handoff is written and stops.

If Codex tool commands lack host variables, `self-slash` refuses Cline hub discovery rather than choosing another agent.
Verify the current Codex thread against the host and its parent-process identity before restoring host variables for a lifecycle call;
never substitute an agent discovered through an unrelated client's shared hub.

**One contract on every host (2026-10-25, agreed with the Paseo lead; same-agent Paseo reset is Claude-only):** (a) the default is the same agent with
a fresh context, the command above: no new process, and its name, model, effort, mode, pane or workspace are
kept (verified live on herdr, Orca and Paseo); (b) a NEW process only when something cannot change in place (a
model change, a quota-guard downgrade, a wedged agent), the `--finish --successor` form below, which means the
same on Paseo (and on herdr, retired from djbclark-ade 2026-10-31 and live until D6): wait for idle, a new top-level agent in the SAME workspace and cwd on the model asked,
first prompt `/baton`, verified (status idle, running or initializing) before anything is retired, exit 11 and
nothing retired on any failure; detached jobs move only through the successor's first action, `/baton`'s re-arm
(it re-points each record's `owner` and restarts the waiter); (c) the
old agent is retired only after that check: Paseo archives it, herdr (retired from djbclark-ade 2026-10-31; its `herdr-tidy` is gone) leaves its pane idle and
never closes it (djbclark rule: no throwing away work). **The new agent is always a real TUI, never an ACP
session, when the operator is expected to read and answer it (djbclark, 2026-10-25: an `acp-run` pane shows only
"⚙ Terminal" lines and failed commands, no transcript to read or steer).** On herdr (retired from djbclark-ade 2026-10-31; `launch.py` keeps this host branch until D6, never start it for new work) that is `herdr tab create
--workspace "$HERDR_WORKSPACE_ID" --cwd DIR --no-focus`, `herdr agent start NAME --kind claude --pane PANE --
<yolo, --model, --effort>`, then `herdr agent prompt NAME "<brief>"`; `launch.py start --baton` and
`launch.py successor` do exactly that (claude and codex; yolo is `--dangerously-skip-permissions` /
`--dangerously-bypass-approvals-and-sandbox`), and `--acp` is the opt-out. Dispatched slices and unattended runs
keep `acp-dispatch` and `acp-run`; they are never handoff hops. A TUI session can take `/new`, `/compact` and
another handoff, an `acp-run` one cannot (`self-slash` exits 9 under `ACP_RUN_AGENT=1`). On Paseo the successor
is already a real agent with a transcript the operator can open.

**A `claude-fleet-governor` steer names its own successor** (`--finish --successor omp/anthropic/claude-sonnet-5-5`):
run that command instead of this step, once; the rest of this section is for a session no governor has steered.

**Quota guard `critical` (2026-10-29): leave the subscription, whatever model you run.** When
`~/.local/state/ade/quota-guard.json` exists and its `level` is `critical` (read it with `.get`; a missing
or unreadable file means no), a Claude Code lead of any model, Sonnet and Opus included, never runs plain
`self-slash "/new"` (that stays on the exhausted subscription) and never a Claude successor. On Paseo, while
`aiuse --available --json` lists omp, run the guard advice's own command (the omp successor with
`--thinking high`); on herdr or Orca (retired from djbclark-ade 2026-10-31; `self-slash` refuses an omp successor there) write the handoff, then
start omp by hand in a new pane or tab. With omp not listed, a codex or grok successor the same way (agy is
reached only by `acp-run agy` slices, home rule 29, never as a successor; `acp-run` sessions are never handoff
hops). **At `critical` this paragraph replaces every Claude path in the rest of Step 9:** the Fable branch
(a) below, the "verify the successor" by-hand fallback (a governor-steered session still runs that verify step,
with these providers), the partial-handoff recipe's `paseo-new-seat --provider claude`, the `/clear` then
`/baton` or `self-slash "/new"` retry after a refusal, and the Orca "relaunch `claude --model <m>`" line. A
refusal retry or a by-hand start reruns the guard advice's command (omp, else codex or grok), never claude. The
partial-handoff recipe is the exception to "the guard advice's command": it keeps `paseo-new-seat` (the
`--finish --successor` form archives the session it keeps) with `--provider omp --model
anthropic/claude-sonnet-5-5 --thinking high` and no `--mode` (omp has its own default; a claude mode id means
nothing to it), else codex with `--provider codex --model gpt-6.1-sol --mode full-access` and the first prompt
`'$baton PATH'` (single-quoted: a Codex skill is `$baton`, `/baton` is Claude's spelling), or grok with
`--provider grok --model grok-4.7`, no `--mode` (`paseo provider ls` lists none for grok) and the first prompt
`Resume from the handoff at PATH: read it, then continue the work.` (no skill syntax is verified for grok). Only (c), an operator-asked model change, still
decides for itself at any level. The `[quota-guard critical]` line is printed once per session and compaction
can drop it, so the state file, not the line, is what you test.

**Successor on another model (Paseo; herdr is retired from djbclark-ade 2026-10-31 and its branch lives until D6; djbclark, 2026-10-23: a Fable lead burned ~30% of a week's
Claude quota, so lead sessions run on Opus 5.5 high, Sonnet 5.5 medium when pipeline-driving).** Use this
form **instead of** `self-slash "/new"` when (a) this session's model is Fable and the level is below `critical` (any `claude-fable-*`,
`[1m]` suffix or not; check the model line in your own context, or `paseo agent inspect <your id>`
shows `Model`), (b) the state file's `level` is `tight` (`critical` is the paragraph above), or (c) the
operator asked for a model change. **Never a same-model or upward successor:** a `tight` guard moves a
session only down, from a model known to be above the target (Fable or Opus becomes Sonnet). If the guard
says `tight` and this session runs on Sonnet or Haiku, or you cannot tell which model you run, run plain
`self-slash "/new"` instead of the command below:

```bash
~/src/djbclark-ade/bin/self-slash --finish --successor claude/claude-opus-5-5 --thinking high
```

Use `claude/claude-sonnet-5-5` when the guard says `tight`, or when the operator asked for Sonnet or for
pipeline-driving; for pipeline-driving pass `--thinking medium` (`[lead] pipeline_effort`, djbclark 2026-10-23). `--title` defaults to "<old name> → <model>"; `--mode` defaults to this agent's mode only
for a successor on the SAME provider (an omp agent's `full` is not a claude mode: the first live run,
2026-10-23, was refused), else `bypassPermissions` for claude and the provider's default otherwise. For a `claude/MODEL` successor `--mode` must be a
permission mode of the installed claude CLI (`plan`, `default`, `acceptEdits`, `auto`, `bypassPermissions`, `manual`,
`dontAsk` when the CLI cannot be asked); anything else exits 2 before anything starts (2026-10-28, PR 110). Run it
**once** and end the turn, as above. After the turn it waits for this agent to be idle, starts a NEW
top-level agent in the same workspace (`paseo run "/baton" ...`), checks that it is top-level and runs
the model asked, and only then archives this agent (never `--force`). The successor's first prompt is
`/baton`, so it resumes from the Tier 1 pointer Step 7 just wrote: Step 7 must be done first. **When this
chain lists the repo as a side workspace** (another chain owns `<repo>/<task>/SESSION_LOG.md`), a bare
`/baton` resumes THAT chain (2026-10-23: the first successor picked up another session's work): pass
`--baton ~/.local/state/handoffs/chains/<chain-key>/SESSION_LOG.md` so its first prompt names the chain. **The
pre-handoff transcript survives only in the handoff document and the archived agent's log** (Archived
agents in the Paseo UI); put anything the operator must read there and in the hermes-ping. On
Orca (retired from djbclark-ade 2026-10-31) there is no successor form (exit 2): write the handoff, then tell the operator to
relaunch `claude --model <m>` in the pane. **On herdr** (retired from djbclark-ade 2026-10-31, live until D6) the same command takes `claude/MODEL` only
(`--thinking` becomes `claude --effort`, `--mode` `--permission-mode`, `--baton PATH` as on Paseo;
`--title`, `--workspace` and `--keep-workspace` exit 2): it runs `skills/session-finder/launch.py successor`, which
waits for this pane's agent to be idle, opens a tab named `<old tab>-<model>-t` in the same herdr workspace and
cwd, starts a real claude TUI there (`herdr agent start --kind claude -- --model M`, never `acp-run`),
prompts `/baton`, and checks that the pane runs claude under another session id; an agent blocked on a question,
an unsent draft or a pane that never settles exits 11, and the old pane is left exactly as it was. Not
verified live yet (2026-10-25: nothing may start a session unattended): the first run is the test, so check
`~/.local/state/self-slash.log` and `herdr agent list`. The waiter runs detached, so you never see its exit
code: if the successor does not start or is a subagent (exit 11) it archives nothing and logs
`successor: ...` to `~/.local/state/self-slash.log`; this session just stays idle and usable (a
successor that was created is left running, not stopped), so when the operator writes again, read the
log first. "several workspaces share this cwd" is resolved from this agent's own Paseo state file (`workspaceId`, 2026-10-28); if it still appears, pass `SELF_SLASH_WORKSPACE=<id>` (`paseo workspace ls`).
The waiter polls the successor for up to 20 s and archives this agent only if it has a new id, is
top-level, runs the model asked and is idle, running or initializing.

**Workspaces (djbclark, 2026-10-23).** The successor is a top-level agent in an EXISTING workspace
(`paseo run --workspace <id>`, this agent's by default, `--workspace ID` for another), never a new
workspace or window (`--new-workspace`) unless the operator asks. Keep an explicit `--title` short: the
sidebar shows only its first words (the default is the old name cut to 24 characters plus
`opus-5-5`). A Paseo workspace name ends in `-pw` (herdr tabs end `-t`, panes `-p`; herdr retired from djbclark-ade 2026-10-31); `self-slash`
creates and renames none, so name any workspace you make by hand that way. After the old agent is
archived, `self-slash` also archives its workspace, but only when that is PROVEN no longer needed
(`paseo workspace archive` archives every agent in it, kills its terminals and deletes a Paseo-owned
worktree): it must be a different workspace from the successor's, found by exactly one cwd match (an
override or a tie-break may place the successor but is never archived), `local` isolation (never a
worktree: archive that yourself), a cwd that neither equals nor contains the successor's, no terminals
(`paseo terminal ls --workspace <id>`) and no other agent in it. Otherwise it keeps the workspace and
logs why (the usual case is the same workspace: archiving it would take the successor along). With
`--workspace ID` the successor runs in that workspace's own cwd. `--keep-workspace` skips the close.

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
on the input line; or exit 3 outside Paseo (and the herdr and Orca hosts that live until D6), or on Paseo without a usable `paseo`
CLI), do not retry or loop: tell the operator the handoff is written and stop. In herdr or Orca (retired from djbclark-ade 2026-10-31) say
`/new` is ready. On Paseo `/new` typed into the composer reaches Claude as plain text and does
nothing (only self-slash's mapping to `/clear` works), so say instead: once this agent is idle,
send `/clear`, then `/baton` (or run `~/src/djbclark-ade/bin/self-slash "/new"` again after the
gap or lock clears, which does both).

**Verify the successor started, every time (djbclark, 2026-10-28).** `self-slash` printing "queued" and exiting 0 proves nothing:
its waiter runs detached and a refusal (exit 11) is only in the log. On 2026-10-28 a handoff to a new tab reported "queued" and no
tab ever opened ("several workspaces share this cwd"). After any `self-slash` that should start a new agent, and after any
"hand this off to a new tab" request, wait about 30 s and then check, and report what you saw, never "should start":

1. `tail -5 ~/.local/state/self-slash.log` shows no `successor: ... NOT archived` line for this agent;
2. `paseo agent ls -g --json` lists the new agent (title, status idle or running) and `paseo agent inspect <new id> --json` shows
   `ParentAgentId` null (`ls` does not carry it); say its title and workspace name to the operator;
   its tab: `self-slash` opens the successor in Paseo Desktop (`paseo agent open <new id>`) before it archives this agent, and keeps this
   agent when that fails or no Desktop process runs afterwards (log: `could not be opened in Paseo Desktop` / `no Desktop process matching`; `agent open` itself
   cannot confirm a tab, so look for it); a successor started any other way has NO tab until you run
   `paseo agent open <new id>` (2026-10-30: a lead without a tab sat 13 hours on a question card nobody could see);
3. if either check fails, say so at once, with the log line, and start the successor by hand (below) or ask which route; do not claim a handoff.

**Partial handoff: the operator keeps this session** ("hand X off to a new tab", "I still use this agent for other things"). The
`--finish --successor` form archives this agent when it works, so do not use it. Write the handoff (Steps 1-7, scoped to the slice and
written to its own chain), then start a separate top-level agent in this agent's workspace and leave this one running. This is not
`/handoff paseo` (the durable transfer of the whole session, which ends this one): use this recipe only when the operator keeps this
session, and `/handoff paseo` when this session is the one being handed on:

```bash
~/src/djbclark-ade/bin/paseo-new-seat --title "<short title>" --provider claude --model claude-sonnet-5-5 --thinking medium \
  --mode bypassPermissions --cwd <this agent's cwd> --workspace <wks_ id> --json \
  --prompt "/baton ~/.local/state/handoffs/chains/<chain-key>/SESSION_LOG.md"
```

The `wks_` id is `workspaceId` in `$PASEO_HOME/agents/*/<your agent id>.json` (`~/.paseo` when unset). Exit 4 with `"mode":"bypassPermissions","modeApplied":true`
is fine for claude only (the shield is for auto-accept; this mode is already yolo); an exit 4 on an omp, codex or grok seat is not covered by that note: check the new agent's
mode with `paseo agent inspect <new id> --json` before calling it fine. Verify as above, and `paseo logs <new id>` shows the
`/baton` was read. Skip Step 8's autorename for a partial handoff: it would rename the session the operator keeps using.

**Document only:** skip this step when a skill that clears the session itself runs the handoff, when
the operator says "doc only" or otherwise asks for the document without a restart, or when you are a
sub-agent or a dispatched slice (above). `loose` Rule 4 option 1 wants this step to run: it does not
make a handoff document-only. Say in the report that Step 9 was skipped and why.

OpenCode V2 Go sessions use the native `ade_compact` tool for manual compaction.
The plugin never rewrites shell commands. A supported host controller may pass
an explicit validated session and directory to `self-slash "/compact"`.
These paths compact only the verified current session; they do not implement a
new-session/baton successor.
See `docs/context-hygiene.md`. Write the checkpoint first and require the normal
host identity/acknowledgment checks for a lifecycle cycle.
