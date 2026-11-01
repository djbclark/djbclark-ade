---
name: session-handoff
description: "Read/write the out-of-tree Tier 1 session pointer file (SESSION_LOG.md) for any git-repo session, not just the ops-djbclark suite. Use at session start in any workspace, before handing off to another agent/session, and at session end. Triggers on: resume session, session log, tier 1, read the session log, update session log."
---

# Session Handoff — Tier 1 pointer file + chain-canonical log

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (v0.4).
State root: `~/.local/state/handoffs/`. This root and everything under it is
project-agnostic — `<repo>`/`<task>` are just directory names, chosen per
the Project scope section below, not a fixed enum the tooling checks
against.

## Project scope

Two regimes, same mechanics either way — only how `<repo>`/`<task>` are
derived differs:

- **ops-djbclark suite** (cwd under `~/src/ops-worktrees/` or `~/ops/`):
  the existing convention, unchanged. `<task>` is the task-workspace dir
  name under `~/src/ops-worktrees/` (`main` for reference checkouts, `ops`
  for `~/ops` sessions); `<repo>` is the repo name (`stayturgid`,
  `site-djbclark`, `site-private`, `Shizuku`, `ops-djbclark`).
- **Any other git repository**: `<repo>` = the repo's toplevel directory
  basename (`git rev-parse --show-toplevel`, or `git remote get-url origin`
  parsed to the repo name if that's more stable across clones/forks);
  `<task>` = the current checkout's directory basename if it's one of
  several parallel worktrees/clones for that repo, else `main`. Derive
  once at session start and reuse — don't re-derive mid-session and risk
  a different `<task>` landing a second, orphaned pointer.

Two kinds of file live there:

- **Pointer**, one per touched location:
  `<repo>/<task>/SESSION_LOG.md`. Frontmatter-only:
  `redirect: chains/<chain-key>/SESSION_LOG.md`.
- **Canonical log**, one per chain: `chains/<chain-key>/SESSION_LOG.md`
  (`<chain-key>` = the first `chain` tag, slugified). Holds Current
  State, Recent History, and a `workspaces` list — one entry per location
  the session touched, each with its own `repo`/`task`/`dir`/`branch`/
  `head_sha`/`dirty`. This is what a session that works both a worktree
  task and `~/ops` at once uses instead of two independent files.

A pointer with **no** `redirect` key is a pre-v0.4 legacy full log — read
it as already-canonical; it migrates itself the next time that workspace
is included in a real write.

## Ownership

One writer per chain — the session that owns it, even when the chain
spans multiple workspace directories. Sub-agents NEVER write Tier 1 or
Tier 2 — they return completion reports; the owner writes. Any agent may
read.

## Reader protocol (session start, or when handed a Tier 1 path)

0. If cwd doesn't resolve to a `<repo>/<task>` pointer path (e.g. running
   in the bare home directory) and no explicit path was given: **don't
   just refuse.** Run the chain discovery fallback below, then continue
   at step 2 using whichever chain you land on.
1. Read the pointer at `<repo>/<task>/SESSION_LOG.md` if present.
2. If it has `redirect`, follow it to the canonical log — that file's
   `workspaces` list is the full picture, not just the workspace you
   started from. Also glob `precompact-*.md` in the *pointer's* directory
   (sidecars land next to the pointer, not the canonical file) — sidecars
   newer than the canonical `updated_at` are unplanned-compaction
   checkpoints that supersede the log's recency.
   **Then run the Owner check (below)** on the canonical log. It gates the first write or resume, not reading.
3. Staleness check: for every workspace listed, compare `head_sha` to
   actual `git rev-parse HEAD` in its `dir`. Any mismatch (or dirty-state
   drift) demotes the file from briefing to lead for that workspace —
   verify its claims against the repo before trusting them.
   The helper does this mechanically and returns a per-workspace verdict —
   it is `claude/hooks/handoff-tools/session_log.py` in this skill's own
   repo (`~/.claude/hooks/handoff-tools` symlinks to it), **not** on `PATH`
   and **not** in `bin/`, and `read` needs `--state-root` as well as `--dir`:

       ~/.claude/hooks/handoff-tools/.venv/bin/python \
         ~/.claude/hooks/handoff-tools/session_log.py read \
         --state-root ~/.local/state/handoffs \
         --dir ~/.local/state/handoffs/<repo>/<task>

   A chain found through the discovery fallback (all its workspaces are side)
   has no pointer directory: give
   `--dir ~/.local/state/handoffs/chains/<chain-key>` instead. It prints
   `stale: true` per workspace alongside `actual_head`, so the
   verdict is a field to read, not a sentence to interpret.
4. **Check the memory layers the log cannot see** (added 2026-08-23). A
   `SESSION_LOG.md` only knows what *its own* session wrote. Decisions
   made in other sessions, or after that log was last touched, live
   elsewhere — so before stating a plan, spend one call on each that
   applies:

   - **This repo's curated docs.** `docs/queue.md` in `djbclark-ade`
     carries accepted-but-unstarted work and open blockers; a resume plan
     that contradicts the queue is already wrong.
     Bound large-document reads (2026-10-25): search headings and task IDs
     first, then read only matching sections with a byte cap before printing.
     Never print the whole queue or several long skills in one tool result;
     output truncation is a failed read, so retrieve the missing section.
      Before printing batched reads or structured command results, enforce a
      combined character ceiling (for example 12,000), summarize JSON fields
      first, and split any oversized batch before output.
   - **Memory search** (Basic Memory over `~/ops/site-private/memory`)
     — the `basic-memory` MCP
     `search_notes`, or `bm tool search-notes "<query>"`, for decisions
     and corrections from other sessions and for anything machine-wide.
     Hermes has `basic-memory` as an MCP server (`~/.hermes/config.yaml`,
     checked 2026-10-24), but its own memory provider is off
     (`memory.provider: ''`), so it does not recall from this store
     automatically. No `hindsight/` folder exists in `main` (checked
     2026-10-24). Verify any hit against the repo before relying on it.
   - **Verbatim recovery**, when the log references something it does not
     explain: `~/ops/site-djbclark/bin/s1_search.py search
     '<phrase>' --mode trigram`, then `neighbours <event_id>` for context.

   Prefer these over re-deriving from the code, and say in the resume
   plan which of them you actually consulted — an unsourced plan invites
   the operator to re-explain things that were already written down.
5. State a resume plan to the operator BEFORE touching anything.
6. Never ask the operator for information the file already answers.
7. Pointer missing or unparseable: not an error. Bootstrap a minimal
   canonical log from `git status` / `git log -1` / current branch with
   Active work: "no prior context found", then proceed.

### Owner check (2026-11-01; the one wording, `baton` points here)

Why: on 2026-10-31 a `/baton` after `/clear` resumed the djbclark-ade lead's live chain and merged PR 173
ahead of PR 177, which the lead's merge plan required to land together. An operator's "continue" does not
replace this check: it was given without knowing the chain had a live writer.

**Scope.** It applies only **before the first write or resume** of a chain: a Tier 1 write, a PR edit, merge
or thread resolve, a push or any continuation of the chain's tasks. A session that only reads a chain reads
it, reports the owner status in its resume plan and asks nothing.

1. **Read** the canonical log's frontmatter `session_id` (S) and `writer`. `session_id` is not uniform
   (checked 2026-11-01 over 146 real logs under `~/.local/state/handoffs/chains/*/SESSION_LOG.md`): a
   claude transcript UUID, a Paseo agent UUID (any TUI: omp, codex, claude), a herdr pane id such as
   `w36:p3`, or free text (`solo`, `omp-...-stage-d`). `writer` is a TUI name, never an id: it narrows
   candidates in step 4 and matches nobody alone.
2. **Match S to a row of `skills/session-finder/fleet.py --json`.** The row is the owner if S equals the
   row's `sid`, `paseo` or `id`; or the row's `id` (8+ chars) is a prefix of S; or S (8+ chars; shorter
   free text such as `solo` never matches by containment) occurs inside the row's `sid` or `transcript`
   path (herdr omp rows carry a jsonl path). A match on a herdr pane id (`wN:pM`, reused after a pane
   closes) also needs the row's `agent` to fit `writer` (`claude*` to claude, `omp*` to omp, `codex` to
   codex, otherwise any); a row of another agent is not the owner and is read as no match. Also read
   `bin/watch status --json`: a `holder.target` that equals or is a prefix of S, with `alive: true`, is a
   live owner even when the fleet row says `closed` (a closed Paseo watch holder is resumable by the next
   message).
3. **Live** means the row's `status` is neither `closed` nor `ended` and its `ended`, `archived` and `finished` fields are all
   empty or false (`idle`, `working`, `blocked`, `busy-background` and `unknown` are live), or the watch
   exception above. **You** are the owner when the row's `self` is true or S equals `$PASEO_AGENT_ID`
   (herdr and terminal sessions have no Paseo id: use `self`); after `/clear` or `/new` the same agent keeps
   its Paseo id, so its own chain reads as you, and a claude's old transcript sid that no row carries
   reads as no match (step 4, covered by exemption C).
4. **No match is not proof of absence: fail closed.** Treat the owner as possibly live and, unless an
   exemption below applies, say so in the resume plan and **ask the operator before the first write**.
   To make that question concrete, list live rows other than you whose `cwd` (compare by `realpath`: a
   symlinked cwd such as `~/s/...` names the same directory) equals, is under or contains a
   `workspaces[].dir` of the log and whose `agent` fits `writer` (`claude*` to claude, `omp*` to omp,
   `codex` to codex, otherwise any); name them in the question. Never proceed on a silent "no owner found".
5. **A live owner other than you:** relay ONE question to it through `session-finder/relay.py` (what may
   you resume, what overlaps) and ask the operator too; take no write action until the owner answers or
   the operator, told the owner is live, decides. Unanswered is not consent.

**Exemptions (resume without asking; state which one in the resume plan):**

- **A. S identifies you** (step 3: `self` true, or S equals `$PASEO_AGENT_ID`): the chain is yours.
- **B. You are the named successor**, even while the owner still reads live. Evidence, all read from
  `~/.local/state/self-slash.log`, whose `successor: starting` line is written before the successor's
  first prompt runs. B holds only when ALL of these are true:
  1. **A `starting` line names you, and the owner's terminal line is in.** A line `<host> <owner id>:
     successor: starting ...` newer than the log's `updated_at` (compare both in local time: the log's
     stamps are naive local time, `updated_at` carries an offset). On herdr its `pane <pane>` is your own
     pane (a unique token). On Paseo the line alone does NOT name you (its `cwd` is shared by every
     session in that directory): you need a later line of that owner naming `<your id>` =
     `$PASEO_AGENT_ID`. The `is top-level` line is not enough, because the owner can still fail after
     it (`agent open` failed, no Desktop process) and keep writing: wait for the owner's TERMINAL line,
     Paseo `finish: archived <owner id> (successor <your id>)` or `finish: archive refused ... successor
     <your id> left running`, herdr `successor: claude is up in <your pane>`. Real terminal lines
     arrive 2-4 s after `is top-level` (about 25-30 s after `starting`); if it is absent, re-read for up
     to 60 s from `starting`, then ask. Never admit on cwd alone.
  2. **No failure line voids it.** Any later line of that owner containing `NOT archived` (every
     `successor_fail` line ends with it, including `successor path aborted; NOT archived`), or a
     `finish: archive refused` line that does not name `<your id>`, voids the `starting` line before it,
     because the owner then believes the handover failed and keeps writing.
  3. **No third party.** The line must be tied to THIS chain. Either the line's owner id is S or the
     id/`paseo` of the step 2 row; or step 2 found no row at all for S and step 4's candidate list
     (live rows other than you and the line's owner, by realpath `cwd` within a `workspaces[].dir`,
     `agent` fitting `writer`) is empty. S is not required to equal the owner: it is often free text or
     stale (`omp-2026-10-31-tendcf-stage-d`; a log still naming an archived `6225c4a1`), but a bare
     `/baton` resolves its chain from the directory, so an unrelated live session's chain must never
     ride in on another owner's handover. A live step 2 row, or a candidate, that is neither you nor the
     line's owner still goes through the ask.
  4. **The handoff exists.** The log's `latest_handoff` is not `none` and names an existing file under
     any `workspaces[].dir` of the log (real handoffs are written to the workspace repo's
     `docs/handoffs/`) or under `~/ops/site-private-djbclark/`. Compare directories by `realpath`.

  The title is NOT evidence (`self-slash` truncates the default `<owner's name> → <model>` and `--title`
  replaces it), and neither is the first prompt: an operator-typed or relayed `/baton PATH` naming the
  chain proves only that the operator named it, and goes through the ask. `self-slash` starts and
  verifies the successor first and archives the owner only afterwards (it first waits up to 900 s for
  the owner to be idle, before `starting`; the archive itself is refused, exit 8, if the owner is busy
  again), so the owner normally still reads live while its successor reads the chain: that is the
  handover. A predecessor that ran `--finish --successor` stops writing once its successor is verified
  (top-level, or `is up`), even when the archive is refused and leaves it running; on a failure line
  (`NOT archived`, "this session stays usable") it is still the writer. A `launch.py start --baton`
  start writes no such line, so it goes through the ask.
- **C. Your own chain after `/clear` or `/new`, no live other owner:** the newest `then: /baton` line for
  your id in `~/.local/state/self-slash.log` follows a handoff of this chain, you hold the watch role the
  chain belongs to (`bin/watch status`), or the operator named the chain (`/baton PATH`, `--dir
  .../chains/<key>`) and its `workspaces[].dir` includes your cwd. C only waives the no-match question of
  step 4 (a claude's old transcript sid matches no row after `/clear`); it never overrides a step 2 match
  to a live row that is not you.

**Reconciling with `baton`'s "Which chain".** A pointer resolved only by directory whose owner is another
live session is not yours: say so and look further, no question. A chain that is otherwise yours (queued by
your `/new`, watch role, operator-named) but whose log a live other session also owns is asked about, per
steps 4 and 5 above, before the first write or resume.

### Chain discovery fallback (cwd doesn't resolve to a workspace)

The chain-canonical layout (v0.4) makes this cheap: the canonical logs
themselves are the index, no separate discovery file needed.

1. `ls ~/.local/state/handoffs/chains/` — one directory per active chain.
2. Read each `chains/<id>/SESSION_LOG.md` frontmatter (`updated_at`,
   `workspaces`) and the Current State's Active work line.
3. **Exactly one chain exists:** don't make the operator name a path —
   state the resume plan from that chain directly (reader protocol steps
   2–5), same as if its pointer had been handed to you explicitly.
4. **Multiple chains:** list them briefly (chain id, `updated_at`, Active
   work) and ask the operator which one — this is information the state
   directory doesn't answer, so asking here doesn't violate rule 5.
5. **No chains exist:** legitimately fresh state — say so, don't
   fabricate a workspace to resume.

## Writer protocol (before handoff, at session end, after major state changes)

Use the helper — it owns caps, sidecar folding, atomicity, git anchoring,
and pointer bookkeeping so you don't have to get them right by hand:

    ~/.claude/hooks/handoff-tools/.venv/bin/python \
      ~/.claude/hooks/handoff-tools/session_log.py write \
      --state-root ~/.local/state/handoffs

with the JSON payload on stdin (`session_id`, `writer`, `chain`,
`latest_handoff`, `active_work`, `blockers`, `next_steps`,
`history_bullets` — max 3; `active_work` is one string; `blockers`, `next_steps` and `history_bullets` are JSON lists of strings, never a bare string; and `workspaces`: a list of
`{"repo": ..., "task": ..., "dir": <absolute path>}`, one entry per
location this session is touching — list every location still active,
since `workspaces` is replaced wholesale each write same as Current
State). List **both** locations in the same write when a session is
working a worktree task and `~/ops` concurrently — that's the whole point
of v0.4, one call updates the canonical log and every pointer at once.
**List a repo as owned only if this chain owns it.** Each owned workspace's
pointer is rewritten to redirect to *your* chain, so listing a repo you merely
touched (a harness fix in `djbclark-ade`, a one-line config commit in `~/ops`)
steals that repo's pointer from the chain that owns it, and the next `/baton`
there resumes the wrong work (2026-10-12: a Plektra session hijacked
`djbclark-ade/main`). Before listing a repo, read its pointer: if it redirects
to another live chain, list it as a **side workspace** instead, by adding
`"side": true` to its entry (since 2026-10-13). A side workspace keeps its git
anchor in your log but gets no pointer, keeps the owner's sidecars, and its
head moving does not make your log stale. A chain whose repos are all owned by
other chains lists them all as side; its log is then found through
`ls ~/.local/state/handoffs/chains/` (the discovery fallback) and read with
`read --state-root ~/.local/state/handoffs --dir ~/.local/state/handoffs/chains/<chain-key>`.

`read`/`fold` take `--state-root` and `--dir <pointer-directory>`; `read`
returns the staleness verdict pre-computed per workspace. Only edit files
by hand if the helper is broken, and then follow the same rules it
enforces (replace Current State and `workspaces` wholesale; 10-entry/
30-day/3-bullet caps; temp-file + rename; sidecars fold into the
canonical file, never the pointer).

Composition rule regardless of path: every Next-steps item must be a
path, a runnable command, or an ID resolvable from cold start. Never
"as discussed above"; never a bare reference to tool-backed state (task
lists, memory) without the exact tool call that retrieves it.

## File format

Canonical log (`chains/<chain-key>/SESSION_LOG.md`):

    ---
    schema_version: 2
    updated_at: 2026-08-04T14:22:17-0400
    session_id: <herdr pane id, or session uuid, or "solo">
    writer: claude-code
    chain: [<bead/epic ids or standalone-hex>]
    latest_handoff: <site-private-relative path, or "none">
    workspaces:
      - repo: <repo name>
        task: <task dir name>
        dir: <absolute path>
        branch: <branch>
        head_sha: <full sha>
        dirty: true|false
      - repo: <repo name>
        task: ops
        dir: <absolute path>
        branch: master
        head_sha: <full sha>
        dirty: false
    ---

    ## Current State
    - Active work: <bead ID + description, or free text>
    - Blockers: <list or "None"; include each sub-agent `BLOCKED: <question>` line
      and each dispatched slice with no report, from `acp-dispatch check`>
    - Next steps: <bullets per the Writer protocol's Composition rule>

    ## Recent History
    ### 2026-08-04T14:22:17-0400 — claude-code
    - <max 3 bullets>

Pointer (`<repo>/<task>/SESSION_LOG.md`):

    ---
    schema_version: 2
    updated_at: 2026-08-04T14:22:17-0400
    chain: [<bead/epic ids or standalone-hex>]
    redirect: chains/<chain-key>/SESSION_LOG.md
    ---

    This is a pointer file — the durable log lives at the path in
    `redirect` above.

## Guards

- **Writing** requires a real git repo to anchor to — `session_log.py
  write` needs actual `head_sha`/`branch`/`dirty` state per workspace, not
  a bare directory. The ops-djbclark suite (`~/src/ops-worktrees/`,
  `~/ops/`) is the well-worn case; any other git repo works the same way
  per the Project scope section above. A directory that isn't a git repo
  at all: the writer protocol does not apply there.
- **Reading/resuming** does NOT require being inside a workspace — cwd
  outside any resolvable repo (e.g. the bare home directory) triggers the
  chain discovery fallback above, not a refusal.
- Deep recovery (12-item mining, chain docs) is the separate `handoff`
  skill (Tier 2). This skill is the cheap pointer only.
