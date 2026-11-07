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
owned Tier 2 document and Tier 1 pointer (Steps 1-7, below), then **does not run Step 9**: it continues with
the **paseo-handoff** skill's (Paseo's own shipped skill) durable-transfer procedure (existing suitable workspace and a new real tab, live launch settings,
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

**Also list this session's open background jobs** (the dispatch shim's job records; `~/.local/state/bigteam/`
is still its state directory). A record is open when it has no `"closed"` key and its `owner` is
this session (`me` below: the shared resolver, because a successor inherits its predecessor's `$CLAUDE_CODE_SESSION_ID`):

```bash
me=$(python3 ~/src/djbclark-ade/bin/claude_identity.py) || { echo "claude_identity.py found no session id; set me by hand" >&2; me=; }   # no || $CLAUDE_CODE_SESSION_ID: that is the stale one
for f in ~/.local/state/bigteam/*/jobs/*.json; do [ -e "$f" ] || continue
  jq -r --arg me "$me" 'select(.owner==$me and (has("closed")|not))
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

## Step 8 — Name the session

Last step, after the report, on Paseo only: give this agent a title derived from this session's work (not "handoff"),
unless the operator named it by hand:

```bash
paseo agent update "$PASEO_AGENT_ID" --name "<short title>"
```

Naming rules (`<name>-pt` tabs, `<topic>-pw` workspaces, at most 17 characters): `docs/workspace-layout.md`. Outside
Paseo, or with no `$PASEO_AGENT_ID`, skip it silently. Add its one-line result to the report. (The `autorename` skill
that did this was removed 2026-11-06, slim-down E4.)

## Step 9 — Clear and continue

djbclark, 2026-10-20: "handoffs [should] immediately clear context and then start a baton and continue running without
human intervention". Since 2026-11-06 (slim-down E4: `self-slash`, which typed `/new` into the agent's own input, is
gone) there are two ways to continue, and an agent cannot run a built-in slash command on itself:

1. **Same agent, fresh context (the default).** End the turn with one line for the operator: the handoff is written;
   type `/clear` (Claude Code; `/new` in Codex), then `/baton` (Codex: `$baton`). If the work simply goes on in this
   session, auto-compaction carries it; nothing to send.
2. **A successor agent**, when something cannot change in place: (a) this session runs on Fable and
   `config/routing.toml [lead].fable_lead` is false (the shipped value is true since 2026-11-07, so a Fable lead stays),
   (b) `bin/route_agent.py show` reads the Claude pools exhausted, (c) the operator asked for another model, or (d) the
   agent is wedged. Never a same-model or upward successor. Start it top-level in this agent's workspace, its first prompt
   the chain's pointer, and end the turn:

   ```bash
   env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD paseo run --no-wait --title "<short title>" \
     --provider claude --model claude-opus-5-5 --thinking high --mode bypassPermissions \
     --cwd "<this agent's cwd>" --workspace "$PASEO_WORKSPACE_ID" --json \
     "/baton ~/.local/state/handoffs/chains/<chain-key>/SESSION_LOG.md"
   ```

   The `env -u` prefix keeps `paseo run` from parenting the new agent to this one (it parents to the caller). When
   the Claude pools are exhausted, the successor is omp (`--provider omp --model anthropic/claude-sonnet-5-5
   --thinking high`, no `--mode`: omp has its own default), else codex (`--provider codex --model gpt-6.1-sol --mode
   full-access`, first prompt `'$baton PATH'`, single-quoted). Check the new agent's mode with `paseo agent inspect
   <new id> --json` (`paseo agent mode <new id> --list` shows the provider's modes). **The successor archives its
   predecessor by id once it has answered** (`paseo agent archive PRED_ID`; name `PRED_ID`, this agent's id, in the
   Tier 2 document): a running agent cannot archive itself, and `--force` cascades to its children. Pass the chain's
   own `SESSION_LOG.md`, never a bare `/baton`, when this chain lists the repo as a side workspace (2026-10-23: a bare
   `/baton` resumed another chain's work).

**Verify the successor started, every time (djbclark, 2026-10-28).** A `paseo run --no-wait` that printed an id proves
only that the daemon accepted it. Wait about 30 s, then check, and report what you saw, never "should start":

1. `paseo agent ls -g --json` lists the new agent (title, status idle or running) and `paseo agent inspect <new id>
   --json` shows `ParentAgentId` null (`ls` does not carry it); say its title and workspace name to the operator;
2. give it a tab: `paseo agent open <new id>` (2026-10-30: a lead without a tab sat 13 hours on a question card nobody
   could see), and `paseo logs <new id>` shows the `/baton` was read;
3. if a check fails, say so at once and ask which route; do not claim a handoff, and do not archive anything.

**Workspaces (djbclark, 2026-10-23).** The successor is a top-level agent in an EXISTING workspace (`--workspace <id>`,
this agent's by default), never a new workspace or window (`--new-workspace`) unless the operator asks. Keep the
`--title` short: the sidebar shows only its first words. The `wks_` id is `$PASEO_WORKSPACE_ID`, or `workspaceId` in
`$PASEO_HOME/agents/*/<your agent id>.json` (`~/.paseo` when unset). Never archive a workspace that holds the
successor (`paseo workspace archive` archives every agent in it and deletes a Paseo-owned worktree).

**Partial handoff: the operator keeps this session** ("hand X off to a new tab", "I still use this agent for other
things"). Write the handoff (Steps 1-7, scoped to the slice and written to its own chain), then start a separate
top-level agent with the successor command above (Sonnet 5.5 with `--thinking medium` for pipeline-driving work) and
leave this one running: no archive. Skip Step 8 for a partial handoff: it would rename the session the operator keeps
using. This is not `/handoff paseo` (the durable transfer of the whole session).

**Top-level session only.** A sub-agent (Agent tool, a `fan-out` slice, an `acp-dispatch` slice) shares or inherits
the parent's agent id, so a successor or rename from it would act on the PARENT. A sub-agent or dispatched slice
always treats the handoff as document-only and never runs Steps 8 and 9.

**What the operator can read afterwards** (2026-10-20): on Paseo the pre-`/clear` transcript is not kept by `paseo
logs` once `/baton` runs; an archived predecessor's log stays under Archived agents. Anything the operator must read
goes into the handoff document, the Tier 1 pointer and the hermes-ping (`~/.local/bin/hermes-ping`, sent **before**
this step), not only into the final message.

**Document only:** skip this step when a skill that clears the session itself runs the handoff, when the operator says
"doc only" or otherwise asks for the document without a restart, or when you are a sub-agent or a dispatched slice
(above). `loose` Rule 4 option 1 wants this step to run: it does not make a handoff document-only. Say in the report
that Step 9 was skipped and why.

OpenCode V2 Go sessions use the native `ade_compact` tool for manual compaction (`docs/context-hygiene.md`); it compacts
only the verified current session and is not a successor. Write the checkpoint first.
