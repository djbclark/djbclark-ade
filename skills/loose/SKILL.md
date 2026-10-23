---
name: loose
description: >-
  Audit the current session for loose ends (unfinished work, unverified claims,
  leftover test artifacts, unreported upstream bugs), step the operator through
  each with /steps, then ask whether to hand off and continue, finish and
  archive, or keep working. Use for /loose, "any loose ends?", "did we finish
  everything?", or unprompted before a handoff or at the end of a long session.
---

# loose — find what is unfinished, then make it decidable

Two halves, and the second is not optional. **Audit by verification, then prompt
him to choose.** A prose list of what you remember is the failure mode this skill
exists to replace.

Runs on the Mac's agent TUIs and on Grok Bot (rendered copy `ade-loose` on its
Linux box, 2026-10-23). Where a step names a Mac-only tool or path, the Grok Bot
equivalent is in "On Grok Bot" below; the audit itself is the same everywhere.

## Rule 1 — verify, never recall

Your memory of the session is the *input* to the audit, not the audit. Every item
gets a command behind it before it reaches him. This matters more than it sounds:
in the session this skill came from, auditing by verification found a real gap
nobody had noticed (an always-loaded `AGENTS.md` pointer that never mentioned the
rule the whole session had established), confirmed two things that had only been
*assumed* true, and refuted one claim that had already been stated as fact.

Corollary: when a check contradicts something you told him earlier, **say so
plainly in the audit**. An audit that quietly preserves your earlier framing is
worthless.

## Rule 2 — the sweep

Work the list; each line is a command, not a memory.

1. **Repo state, every repo touched.** Dirty files, unpushed commits, detached
   heads: `git status --porcelain` and `git status -sb` per repo. Distinguish
   *yours* from another session's — in a shared checkout you cannot attribute by
   `git log --author`, so if you did not touch it, say "not mine" and leave it.
   Grok Bot: G1.
2. **Test and probe artifacts.** Everything you created to prove something:
   throwaway MCP servers, marker functions appended to source, backup files,
   scratch clones, index caches you deleted or built. Grep for your own probe
   names. A marker function left in a tracked file is the worst kind of leftover.
   Grok Bot: G2.
3. **Background work.** Tasks still running, agents idle with output you never
   collected. An agent that looks finished with nothing delivered means *not yet
   delivered* — re-task it to write a file; never reconstruct what it would have
   said. Grok Bot: G3.
4. **Claims you made but did not verify.** Scan your own replies for assertions
   stated flatly. Anything you inferred rather than observed either gets checked
   now or gets downgraded to "assumed" in the audit.
   A pass you read through a pipe (`cmd | gtail`) is in this class: the exit
   status was the last stage's, not the command's. Re-run it to a file with
   `echo "rc=$?"`, or downgrade it. (`gtail` is the Mac's GNU tail; on Linux,
   Grok Bot included, it is plain `tail`.)
5. **Findings that exist only in chat.** A measurement, a defect, a workaround,
   a decision and its reasoning — if it is not in a repo, a doc, or memory, it is
   gone at session end. Put it somewhere durable before reporting the loose end.
   Grok Bot: G4.
6. **Docs that reality has overtaken.** Did this session's work falsify a
   standing note, an always-loaded instruction, or a pointer? Check the files
   that *load every session* specifically — a rule nobody reads is not a rule.
   Grok Bot: G4.
7. **Upstream bugs found and not reported.** Any third-party defect you hit with
   a clean reproduction. **Search existing issues and PRs first** (open and
   closed, several terms) — the existing thread often explains the behaviour or
   even hands you the fix. **Say in the audit, and in the draft, that you
   searched: which repo, which terms, and the nearest threads found** (operator,
   2026-10-09: "always search for and mention searching for existing issues
   first"); a bare "no upstream issue exists" is not evidence. Grok Bot: G5.
8. **Deviations from his decisions.** Anything you did that cut against a choice
   he had already made, even reversibly. Disclose it in the audit if you have not
   already; do not let it surface later.
9. **Deferred by him, not by you.** List these so they are not mistaken for
   oversights — and do not re-litigate them.
10. **Verified-closed items.** One line, so the same questions do not come back
    next time.

## Rule 3 — then step through them with `/steps`, do not prose

Once the sweep is reported, **invoke the `steps` skill automatically** on the
live decisions; don't wait for him to ask. That skill picks the prompt tool
(`AskUserQuestion` on Claude-class agents, `clarify` / Telegram buttons on
Hermes, the `SendToUser` question widget on Grok Bot, `steps` section 2d),
asks one item per prompt with the recommended option first, and does
each small chosen action before asking the next. Hand it the audit's items in
order of consequence, each with the finding and the recommendation you already
worked out, so it doesn't redo the audit. Include a genuine "leave it as is"
option where that is a real choice, and spell out the consequence.

Prose is for the context he needs to choose *with* — the numbers, the risk, what
you found. Not for the choosing.

Categories 9 and 10 are **not** questions. Report them and move on.

## Rule 4 — close by asking: handoff and continue, finish and archive, or keep working

Once `/steps` has finished (its summary table, and any queued work done), end
with one more prompt using the **same tool as `/steps`**, every time, even when
the audit found nothing:

1. **Handoff and continue** — the `handoff` skill: write a Tier 2 handoff, then
   (its Step 9) clear the context of this same session and start `/baton`, so work
   carries on with nobody typing. Recommend it when anything is still open or
   deferred, or the session was long or produced context that is not already
   durable. On Paseo the pre-`/clear` transcript is not kept by `paseo logs` once
   `/baton` runs (2026-10-20; the UI is unverified), so anything he must read goes
   into the handoff document, the Tier 1 pointer and the hermes-ping, not only the
   final message.
2. **Finish and archive this session** — write the final results as the last
   message, then end the session. Recommend it when the audit closed everything
   and all work is committed and pushed.
3. **Keep working** — stay in the session; nothing else happens.

Put the recommended one first with `(Recommended)` and give the reason in its
description, e.g. "2 items deferred; a handoff keeps them findable".

On Grok Bot the three options are the same but act differently (G6); ask
with the widget, the recommended option first with `style: "primary"`, the
reason in the text message before it.

Then act on the answer. For handoff and continue, invoke the `handoff` skill (its Step 9
runs here). **Lifecycle actions run only in the top-level session** (2026-10-20): a
sub-agent or a dispatched slice shares or inherits the parent's agent id, so it never runs
Rule 4's `self-slash`, `--finish` or Step 9; it treats a handoff as document-only and
reports.

A built-in like `/quit` is not a skill, but you can queue it yourself (operator,
2026-10-09: "you should actually be able to run /quit yourself"): when he picks
finish, write the final results as the last message so they stay readable, finish
everything first (commits pushed, no pending reads), then run
`~/src/djbclark-ade/bin/self-slash --finish` as the last action and end the turn
at once. On herdr and Orca that is the old `/quit`; on Paseo `/quit` does nothing
(it reaches Claude as plain text, seen twice 2026-10-20), so `--finish` waits for
idle and archives this agent without `--force` (it stays under "Archived agents",
and the operator can still read the final message). djbclark, 2026-10-20: "if there
is nothing to continue to just clear context but in a way that the human can still
read the final results". If the handoff was chosen and it was run document-only,
offer the finish prompt again once it is written.

`/compact` works the same way, but only when the context prompt's compact tier
fires (+200k since the start or last compaction) or he picked it, never just
because context looks large: each compaction costs ~150k+ token-equivalents
(`memory/feedback_self_compact.md` item 7). Then, if you are a Claude session in a herdr pane or an
Orca terminal (his standing say-so since 2026-10-09, `memory/feedback_self_compact.md`), write down
what the next turn needs, run `~/src/djbclark-ade/bin/self-slash "/compact <focus>"`
and end the turn at once. `self-slash` refuses outside herdr and Orca, or when his
input box holds a draft; then ask him to type it. Grok Bot: skip (G6).

## Silent mode, before a handoff

The `handoff` skill runs Rule 2 by itself first (its Step 0): sweep for your
own eyes, fix the small items, carry the rest into the handoff. No report, no
prompts, no Rule 4 question in that case. Grok Bot has no `handoff` skill
(it is not mirrored there), so it never enters silent mode.

## On Grok Bot (added 2026-10-23)

Grok Bot runs the same audit on its own Linux box (`HOME=/home/box`). It has no
herdr, Orca, Paseo, launchd, Keychain, `hermes-ping` or Mac process list.

- **G1 Repos.** `~/src/<repo>` is `/home/box/src/<repo>` (also check `/workspace`,
  the scratch dir, and any worktree you added: `git worktree list`). Remote
  state (open PRs, CI on what you pushed) is read with `gh`/`curl` using
  `GITHUB_TOKEN_DJBCLARK`, or the GitHub connector; never print the token.
- **G2 Artifacts.** The box's `/tmp` and `mktemp` dirs, scratch clones under
  `/home/box/src` or `/workspace`, files under `/home/box/agent-data/shared/`,
  and things made outside the box during the session: connector drafts (mail,
  Slack), test calendar events, Pages. List each with how to remove it.
- **G3 Background work.** Shell jobs started in the background (check them, or
  `ps -u box` on the box; that is its only process list), subagents whose
  result you never read, and routines you scheduled.
- **G4 Durable places and always-loaded files.** Bot memory, the shared skills
  in `/home/box/agent-data/workflows/` (the parent writes those through its
  skill tool; a sync-managed `ade-*` copy is changed upstream in djbclark-ade,
  never in place) and the repo docs the finding belongs to.
- **G5 Upstream issues.** Search with `gh search issues`/`gh api` or the
  GitHub connector, and Forgejo's API for forgejo.mit.edu. Filing the issue is
  posting: draft it and get his explicit OK first.
- **G6 Rule 4 on Grok Bot.** Notifying him is a normal chat reply, so skip
  every `hermes-ping`. There is no `handoff` skill, `/baton`, `self-slash`,
  `/compact` or `--finish` here:
  1. *Handoff and continue*: write the open items and what the next run needs
     somewhere durable (G4), say where, and keep working or stop as he says.
  2. *Finish*: the final results are the last message; nothing else to run.
  3. *Keep working*: unchanged.
  A Grok Bot subagent cannot prompt him: it runs Rule 2 and returns the
  findings and recommendations to its parent, which runs Rule 3 and Rule 4.
- **G7 Approval rules.** Fixing a small loose end he picked is fine, but
  pushing, sending, posting and merging still need his explicit OK (`steps`
  2d.5).

## What this is not

- Not a handoff. Use `handoff` / `session-handoff` for persisting context so work
  can resume; this is about deciding what is still owed. Rule 4 only *offers* one
  at the end.
- Not task verification. Use `verify-and-stop` to prove one task meets its
  acceptance conditions; this sweeps the whole session, including things nobody
  set acceptance conditions for.
- Not a scope expansion. Finding a loose end does not license fixing it. The
  exception is category 5 — make a finding durable before you report it, because
  reporting it is useless if the record dies with the session.

## Prior art, if a more comprehensive tool is wanted

Nothing local covers this. Externally, closest first:

- **[conclude-it](https://github.com/DevOtts/conclude-it)** (DevOtts) — the most
  comprehensive: one door for session close, pairing a ship pipeline (test gate →
  deploy → prod gate) with a close core of debrief, ledger, sweep and an honest
  verdict. Per-repo setup interview, config in `CLAUDE.md` / `AGENTS.md` /
  `.conclude-it/config.md`. Worth adopting if session-close should also *ship*.
- **glitchwerks session-analysis** — assesses whether the agent stayed on task and
  what it acknowledged leaving undone. Narrower, and retrospective rather than
  decision-producing.
- **petekp claude-code-audit** — audits many past sessions for step-change
  workflow improvements. A different altitude: meta-level, not this-session.

This skill deliberately keeps the decision-prompting half, which none of those
do, and stays out of deploy.
