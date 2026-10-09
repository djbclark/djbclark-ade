# helm auto — run the fleet while the operator is away

Canonical copy: `~/src/djbclark-ade/skills/helm/auto.md`, loaded by the `helm`
skill (section 8). Relay mode (`SKILL.md`) answers sessions that wait on the
operator; auto mode is what the helm session does when nobody can answer: it
becomes the lead, surveys the open work, dispatches a wave of workers, keeps
the queue and the sources moving, and leaves one numbered document the
operator can undo item by item. Written from the first unattended run
(ClaudeHelm, 2026-10-09 00:46 to 05:45 EDT: 24 workers, 9 repos, one compact,
one external outage).

Invariants, in force for the whole run:

1. Nothing irreversible, by lead or worker (section 3.3). Every change is a
   commit the operator can `git revert` or a branch they can delete.
2. One wave at a time; re-probe quota before each.
3. The lead integrates from messages and keeps `STATE.md` current; the detail
   stays in report files.
4. The lead never publishes for a worker that is still running.
5. Compact only through `self-slash`, only after `STATE.md` is written.

## 1. When it applies

1. The operator says so, in words that name the end: `/helm auto`, "run
   unattended until 05:45", "keep the fleet busy while I sleep". Silence is not
   a go: an operator who is merely away gets relay mode and `wait`.
2. Write the parameters as the first lines of `STATE.md` (section 5) before
   anything else: stop time for the lead, a worker hard stop about 45 minutes
   earlier (integration and the final doc need that time), the repos in scope,
   the quota ceilings (section 3.5), the agents allowed (tonight: Claude only;
   Fable where judgement matters), and anything the operator ruled out.
3. A hint that arrives mid-run ("also look at X") is a new source, not a
   re-plan: survey it with two cheap commands and put it in the next wave.
4. Every timestamp you write comes from `date`, never from memory: the first
   hours of STATE.md on 2026-10-09 carried guessed stamps and had to be
   relabelled.

## 2. Start: scan, then survey

1. `$H scan` first, exactly as relay mode (SKILL.md section 1). Audit warm idle
   sessions with `$H audit <id>`; their `/steps` prompts are parked for the
   operator, not answered. **Never choose for the operator** holds in auto mode
   too: nothing in the queue is answered by the lead.
2. Survey the work sources into one ranked table (repo, id, title, size guess,
   model class). All three, in one pass:
   a. GitHub issues: one `gh issue list -R <owner/repo> --state open` per repo
      in scope, one call for all of them.
   b. Beads: `bd list --status open` in every repo with a `.beads/` directory,
      and `bd list --status blocked` (helm and fleet-watch see neither).
   c. Todo notes: `status: open` in `~/ops/site-private/memory/todo/`. The file
      names hold spaces, so walk them with a `for f in …` loop, never
      `$(grep -l …)`.
3. `fleet.py conflicts --cwd <repo>` for every repo in the table, before any
   dispatch. A `working` session means skip the repo. An idle session means
   commit by exact path only, with `git status` showing nothing else of yours.
   Dirty files are someone else's: never stage, stash or reset them.
4. Scan the scratchpad for reports whose first line is `BLOCKED:`
   (`acp-dispatch check <dir>`) and for `bd list --status blocked`, now and at
   the start of every round. Those are items only the lead sees.

## 3. Dispatch one wave

1. **Files, not prompts.** Write one `common-rules.md` for every worker, one
   brief per worker, and generate the footer with
   `acp-dispatch footer --report <scratchpad>/<name>-report.md`. The Agent-tool
   prompt is then one line ("read and follow the brief at …, including the
   footer") plus the footer pasted verbatim. Nine pasted briefs cost the lead
   50k of context on 2026-10-09; nine one-line prompts cost nothing.
2. **One worktree per worker**, even two on the same repo:
   `git -C <repo> worktree add <scratchpad>/wt-<name> -b claudehelm/<topic>
   <default>`. Repos under `~/ops` always get one (running deployments read
   those checkouts; never commit to their master). Repos under `~/src` work on
   the default branch unless `.github/workflows` publishes on push, in which
   case a branch. A finished worker's worktree and branch may be handed to a
   follow-up worker; leave every worktree in place at the end and list it.
3. **Standing worker rules** (the `common-rules.md` that worked; keep it one
   screen):
   a. The operator is away: never ask; decide conservatively and record each
      decision under `DECIDED:`; anything only the operator can decide goes
      under `QUEUED-FOR-OPERATOR:` and the worker moves on.
   b. Hard stop by `date`; then finish the report and touch `.done`.
   c. Forbidden: force-push, history rewrite, `reset --hard`, `stash`, `clean`,
      deleting branches or files outside the worktree, `commit -a` or
      `add -A`, touching others' dirty files, closing issues, posting to any
      repo the operator does not own, sending messages, changing live services
      or `~/.config`, global installs. One comment per issue worked, stating
      the commits and "left open for operator review", is allowed.
   d. Every commit message contains the run marker (`ClaudeHelm`) and ends with
      the co-author trailer **for that worker's model**; the brief, not the
      shared rules file, carries the trailer, so there is one source of truth.
   e. Tests through `~/ops/site-private/bin/bg`; Gradle one at a time; graft or
      `rg` with a path for discovery; research outward before trial and error;
      `agy` only via `acp-run agy`; `~/src/<name>` paths, never `~/s/…`.
   f. Report shape: `## N. <id> <title>`, then `Na. Done`, `Nb. Commits`
      (SHA + branch), `Nc. Undo` (an exact `git revert <sha>` or
      `git push origin --delete <branch>`), `Nd. Verified` (real output, or
      "not verified: why"), `Ne. Queued for operator`; then `## DECIDED`,
      `## QUEUED-FOR-OPERATOR`, `## SKIPPED (why)`.
4. **Model per slice.** Fable for the slices where judgement is the work
   (platform internals, architecture, whether an upstream port is right);
   Opus for Python, ops, docs and fix-ups; a read-only reviewer can be Opus.
5. **Quota, before every wave.** `aiuse --available --json`; the fullest window
   binds. The lead's own pool keeps a reserve for integration, the review wave
   and the final doc: when it is below about 20 percent left, no new worker
   goes on it (on 2026-10-09 Fable at 15 percent sent the whole second wave to
   Opus). Count workers already running on a pool as spend not yet visible.
6. **One wave at a time.** Dispatch all of a wave in one message (independent
   Agent calls run concurrently), name each worker so `SendMessage` reaches it,
   then wait for completions. The next wave starts when quota and the queue
   both say so, not when the first worker finishes.
7. Hand a worker nothing it must ask about: the brief names the repo, the
   worktree, the branch, the items in order, the report path, and what to do
   when an item needs device access or operator judgement (write the analysis
   and a proposed patch, queue it, continue).

## 4. Integrate

1. A worker's completion arrives twice: a teammate message (its report in
   ordered chunks) and a task notification. **Integrate from the message**;
   open the report file only for a detail the message does not carry (a diff,
   a URL, a test excerpt). `acp-dispatch check <scratchpad>` classifies every
   report in one call when the notifications have piled up.
2. After each completion, append to `STATE.md` (section 5): worker, commits,
   branch, pushed or not, what is queued, what the final doc must list. The
   running list "still running: …" is updated in the same edit.
3. **Never publish for a live worker.** A worker that is still running may
   have your "the route is back" message in its inbox and publish itself: on
   2026-10-09 the lead pushed and commented for one such worker and it did the
   same four seconds later (three duplicate comments, deleted by hand). Either
   `SendMessage` the worker to publish, or wait for its `.done` and read the
   push section of its report first. A queued `post.sh` or push list in a
   report is stale the moment the worker publishes itself: check before you
   run anything from it.
4. Apply nothing a worker left for the lead (bead status changes, patches on
   other branches) until the review wave has read it (section 7).
5. A worker that ends on a question wrote `BLOCKED:` as its report's first
   line (footer rule 6). Answer it with `SendMessage` and the worker resumes;
   a sub-agent is woken by nothing else.

## 5. STATE.md and self-compact

1. `STATE.md` in the scratchpad is the lead's anchor: parameters (section 1),
   the scratchpad file list, every worker with its slot, worktree and branch,
   the wave-2 candidates, the integration checklist, and an `## Update` block
   per event. The post-compact turn reads it first, before any message.
2. The context hook fires at +40k and again at +70k (home-agents.md). In auto
   mode the second one is the compact point. Before compacting: finish the
   STATE.md edit, then `~/src/djbclark-ade/bin/self-slash --delay 10 "/compact
   <focus: read STATE.md first>"`, and **end the turn at once**. Nothing else
   may queue `/compact`: a bare `herdr pane run` appended to the operator's
   draft on 2026-10-09 and ran it as a prompt; `self-slash` refuses when the
   input box is not empty and targets only its own pane.
3. A compact loses nothing a worker holds: workers are sub-agents of the
   session and their messages still arrive. It does lose the lead's memory of
   what it promised, which is why STATE.md is written first.

## 6. External outage

A shared dependency failing mid-run (on 2026-10-09: the login keychain locked
at screen lock, so `gh`'s token and the 1Password SSH agent went with it) is
handled once, in this order, and not repaired:

1. **Verify from the lead's shell** (`gh api user -q .login`, `ssh -T`, the
   public API for CI state) so one worker's error is not taken for an outage.
2. **Find the cause cheaply**: a notice in Gmail, the public status page,
   `security show-keychain-info` for the keychain. Ten minutes at most; a
   worker can research it properly as a slice later.
3. **Hermes once**: `~/.local/bin/hermes-ping "ClaudeHelm: <one line>"`. Not
   per worker, not per retry.
4. **Broadcast the fallback** in one short `SendMessage` to every running
   worker: commit locally, put the exact push commands and the draft comment
   text in the report, continue. Record the outage and the fallback in
   STATE.md so the final doc lists every unpushed branch and draft comment.
5. If a sanctioned route exists, the lead may publish for **finished** workers
   through it (2026-10-09: `sudo-secretspec run --reason "ClaudeHelm: <what>"
   -- sh -c '…'` with the token used per invocation, never on disk or echoed;
   branch pushes, `~/src` default-branch pushes and issue comments only, never
   `~/ops` master). List the decision in the final doc for the operator.
6. Never repair credentials, unlock anything, or change a live service.

## 7. Review wave, then fix-up wave

1. When the main waves have finished and quota allows, dispatch one read-only
   reviewer (Opus is enough) over every worker branch, local default-branch
   commit and patch, with a `MERGE ORDER` summary at the top of its report:
   merge now, push now, hold (with the one-line reason), should-fix, nit.
2. Dispatch a fix-up wave from its should-fix list only: one worker per
   branch, commits on the same branch, pushed through whatever route is up.
   Holds stay holds; the operator lifts them.
3. The `MERGE ORDER` summary is copied into the final doc verbatim.

## 8. Finish

1. Stop starting work at the lead's stop time minus the longest slice you
   would still start; let running workers finish to their own hard stop.
2. Write the final doc to `<scratchpad>/ClaudeHelm-<date>.md`, numbered so
   every item can be referred to: one `## N.` per item with Done, Commits,
   **Undo** (one exact command), Verified, Queued; then the `MERGE ORDER`
   summary, every unpushed branch, every draft comment, every worktree left in
   place, every `DECIDED:` the lead made, and the instruction fixes a worker
   asked for (a rule to add to home-agents.md is one of them). Print the path.
   Where the doc lives permanently is the operator's call (ask-where rule):
   queue it, do not pick a repo.
3. `~/.local/bin/hermes-ping "ClaudeHelm: done — <one line, the doc path>"`.
4. `python3 ~/src/djbclark-ade/skills/autorename/autorename.py --auto "<title>"`
   then `herdr_place.py check --auto`, so the session is findable later.
5. Append tonight's learnings to this file's sources (section 9 grows; the
   operator asked for the skill to learn from each run).

## 9. Don'ts learned on 2026-10-09

1. **Footer placeholder.** The shared footer's placeholder is the literal
   `EXAMPLE-report.md` (and `{report}` in `docs/dispatch-footer.md`), not
   `<REPORT>`; a hand `sed` left it unchanged and the worker wrote
   `EXAMPLE-report.md`. Generate footers with `acp-dispatch footer --report`.
2. **Duplicate comments.** Section 4.3: the lead published for a live worker.
3. **`rg` without a path.** On a non-terminal stdin `rg PATTERN` reads stdin
   and hangs; a worker lost 30 minutes. Briefs say `rg PATTERN .`; the rule is
   in home-agents.md since 2026-10-09.
4. **Trailer per model.** The shared rules file said one model's trailer while
   half the workers ran another; the trailer belongs in each worker's brief.
5. **`BASH_ENV`.** Non-interactive `bash -c` here sources `~/.bashrc`, which
   re-prepends `~/.local/bin` to PATH, so a test or script that assumes the
   interactive PATH order sees a different binary. Call tools by full path in
   anything a worker runs non-interactively.
6. **Guessed timestamps** (section 1.4) and **pasted briefs** (section 3.1).
7. **Repairing the outage** instead of routing around it (section 6).

## 10. What this is not

1. Not relay mode with the answers filled in: the queue's items are still the
   operator's, parked until they return.
2. Not `bigteam`: that fans one prompt out across vendors for the operator's
   own task; auto mode works a backlog across repos with Claude workers it
   briefs itself. It borrows bigteam's quota reading and claims.
3. Not `orc`: no herdr panes are started or closed; workers are Agent-tool
   sub-agents (or `acp-dispatch` slices) that end with a report.
