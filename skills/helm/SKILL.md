---
name: helm
description: >-
  Answer every agent session that is waiting on the operator from one window: a
  no-model collector finds each waiting session of every TUI (herdr, Orca, tmux,
  Claude registry, Hermes, ACP launches), and this skill relays one item per
  prompt (AskUserQuestion; clarify on Hermes), sends the answer back, and has
  idle sessions audit themselves with /loose; with "all" it adds ended sessions
  that still hold open work (handoffs nobody picked up, unanswered last
  questions). Use when the operator types /helm or /helm-all, says "take the
  helm", "run the fleet from here", "what needs me", "what is waiting on me",
  "what is open anywhere", "including stopped sessions", "what did we leave
  hanging", or wants to answer other sessions' prompts or restart handed-off
  work from one window.
---

# helm — every waiting session, one prompt at a time

Canonical copy: `~/src/djbclark-ade/skills/helm/` (git: `~/src/djbclark-ade`, github.com/djbclark/djbclark-ade); every TUI reaches it through the skill-everywhere hub `~/ops/site-private/skills/helm`.
Design and prior art: `~/src/djbclark-ade/docs/helm.md`.

Each session runs its own `/steps` and `/loose`, because that is where its
context is. Helm is the relay: `helm.py` (no model, no tokens) finds what is
waiting and carries answers back; you only present the choice. He changes
windows only when an item needs more depth than a prompt can carry.

```bash
H="python3 -I $HOME/ops/site-private/skills/helm/helm.py"
L="python3 -I $HOME/ops/site-private/skills/session-finder/launch.py"
$H scan                      # open items, every TUI, ranked (--all: every session; --ended: section 7; --order attention: old order)
$H wait --auto-audit         # block until something new needs him
$H answer <id> <n>           # pick option n; one number per question
$H answer <id> --text "..."  # free-text answer to a single question
$H audit <id>                # send /loose to an idle session
$H skip <id>                 # hide until that session changes
$H show <id>                 # full detail: question, last reply, screen
$H keys <id> <key>...        # raw keys for a prompt helm cannot parse
```

## 1. Start

1. Run `$H scan`. Show the queue as a short numbered list (project, where,
   kind, `~N min unlocked`), so he knows how long the walk is.
2. Walk the open items (section 2) **in the order printed**. The order is the
   estimate of unattended work each answer buys (operator, 2026-10-08: keep as
   many sessions working as possible at every moment): plan approvals (~45 min),
   then a session's questions weighted by its own measured work stretch (median
   minutes between an operator prompt and its next stop) times the `/steps`
   items still to come, then permissions (~20), finished sessions whose work
   restarts as a /baton session (~25), ACP replies (~15), then idle audits (~8
   warm, ~3 cold). One session's items are kept together so it gets its answers
   in quick succession and runs on. Do not reorder by your own judgement.
3. Then wait (section 3). `/helm` stays on until he says `stop`.
4. Every item is from a session another window owns: relay, never act in that
   repo yourself, and never start work there while that session is `working`
   (`fleet.py conflicts --cwd <dir>` says so; session-finder section 4).

## 2. Relay one item per prompt

Pick the prompt tool exactly as `steps` does (`AskUserQuestion`; `clarify` on
Hermes; never numbered prose). One item per call.

1. **`question`** — the session already wrote the summary, the options and
   its recommendation. Relay them, do not rewrite them.
   a. Header chip: the project name (12 characters at most).
   b. Question text: the item's heading (`project — where · "title"`) on the
      first line, then the session's question, unchanged.
   c. Options: its labels and descriptions, same order, `(Recommended)` kept
      where it put it. Do not add your own ranking. If you know something the
      session cannot (two sessions about to touch the same thing), say it in
      one prose line before the prompt.
   d. Send his pick: `$H answer <id> <n>`. Text typed under "Other" goes with
      `--text`. `skip` typed there means `$H skip <id>`; `stop` ends the walk.
   e. A prompt with several questions: ask each as its own prompt, then send
      once (`$H answer <id> 2 1`). A multi-select prompt cannot be sent this
      way: give him the `focus:` command.
2. **`permission`, `plan`, `blocked`** — helm could not parse a question.
   Show the screen excerpt in one prose block, offer the choices that are on
   that screen, and send with `$H keys <id> <key>`.
3. **`idle`, not audited, warm** — run `$H audit <id>` without asking: that is
   the standing instruction, and the script refuses when it is unsafe (input
   box not empty, session not idle). Its `/steps` prompts come back through
   the queue.
4. **`idle`, not audited, cold** (idle past 55 minutes, so the prompt cache
   has expired and an audit re-reads the whole context at full price), and
   every non-Claude agent: ask. Give a one or two sentence summary of its
   last reply, then offer Audit (name the transcript size), Skip, or Leave it
   in the queue.
5. **`reply`** — a session started over ACP (`launch.py`) ended its turn with a
   question. Relay the question text with options he can answer in a line;
   send with `$L reply <id> "<his text>"` (into the live session's inbox; a new
   acp-run turn if it already exited). **`done`** — a turn finished: show its
   final line once. `wait --auto-audit` then sends `/loose` as its next turn
   (`$L audit`) and, once that audited result has been shown, closes the
   session and its herdr tab (`$L close`) so tabs do not pile up (operator,
   2026-10-08). Offer `$L reply` for a follow-up before the close happens.
6. **`finished`** — a running Claude session whose last prompt was `/handoff`
   or `/quit`. It is not audited and not messaged. Offer: Start a /baton session
   in its repo now (`$L --baton --cwd <dir> --agent claude --model <M> --pane
   <its pane> -p "<next step he names>"`), Skip, or Leave it. Ended sessions
   with open work come only with `scan --ended` (section 7).
8. **`busy-background`** — looks idle to herdr but a child process that is not
   one of its servers still runs (a backgrounded Bash, an acp-run, a build).
   Not an item and never audited; `scan --all` shows the processes. Leave it.

**Never choose for him.** Not the recommended option, not an obvious one.
Helm relays; the answer is his. Never relay around a permission denial.

**Report against the artifact.** `answer` prints `answered [id] "…" = "…"`
only after the session's transcript records that answer. Repeat that line.
On exit 1, say what it printed; nothing went through.

## 3. Wait without spending tokens

Run `$H wait --auto-audit` with `run_in_background: true`. It polls locally and
exits only when an item is new or changed, printing only those items. When the
notification arrives, relay them (section 2) and start it again.

1. Never poll, never `/loop`, never schedule a recurring prompt for this.
2. One `wait` at a time.
3. `--auto-audit` sends `/loose` itself, with no model, to a Claude session
   that has been idle for 3 to 55 minutes, is not the focused pane, has an
   empty input box, and has not been audited since it last changed. Once
   audited, a session stays quiet until new work happens in it.

## 4. Keep this session cheap

1. Relay item text as given. No `show` unless he asks for depth.
2. One line per result. No recap of the queue between items.
3. When he wants depth, give the `focus:` command. That is the moment to
   change windows.
4. Say once, at the start: a helm session relays and does not judge, so a
   cheaper model (`/model`) is enough.

## 5. Hermes and the phone

1. **Hermes** (on Telegram: `/helm`, registered by Hermes's `skill-slash`
   plugin since 2026-10-06; `/skill helm` also works). Same script. Per item, one `clarify`: the question starts with
   `project · where — `, then the session's question; `choices` are its option
   labels (under about 60 characters each, first one is its recommendation).
   Then `$H answer`. Hermes is not re-invoked by a background command, so it
   runs `scan`, walks the items, and runs `scan` again until nothing is open.
2. **Hermes's own open approvals** (Claude side): `permissions_list_open` on
   the `hermes` MCP server lists them, `permissions_respond` answers. Check
   once per round and relay them the same way.
3. **Collie**: the helm pane is an ordinary herdr pane, so its prompts are
   answerable from the phone with nothing extra.
4. **Notices**: `fleet-watch` (launchd, every 5 minutes, no model) calls
   `helm.py brief` and sends one Hermes line when a session starts waiting or
   asks a new question. Nothing is sent when one is answered.

## 6. Limits (verified 2026-10-06, herdr 0.9.1, Claude Code 2.1.291)

1. Verified on herdr: a digit key selects and submits; "Type something" takes
   free text; a several-question prompt ends on a review tab that Enter
   submits. The Orca and tmux channels are written but not yet exercised.
2. Non-Claude TUIs (Cursor, Codex, …) give state and a screen excerpt only;
   Hermes chats (`remote`) are listed for context and reached through the
   hermes MCP server (section 5), not keys. Sessions started over ACP give
   their full final text (`reply`/`done`).
3. A Claude session outside herdr, Orca and tmux can be listed but not
   answered: use `SendMessage`, or his `focus`.
4. Sessions come from `session-finder/fleet.py` (2026-10-08): herdr, the Claude
   registry, a process scan, Hermes `state.db`, `launches.jsonl`. agy is
   history-only until it works again (todo note).
5. Keys sent when no prompt is on screen land in the input box. `answer`
   checks the screen first; `keys` checks only that the session is blocked.
6. Since 2026-10-08 a session whose own background task is still running is
   `busy-background` (fleet), not idle: it is never audited. A session waiting
   on an in-process sub-agent is `working` in the registry and never was.

## 7. Ended sessions (`/helm all`, `/helm-all`, `--ended`)

Ended mode is this skill with ended sessions added to the queue. Use it when he
types `/helm-all` (a Claude command and a Hermes command, both loading this
skill), `/helm all`, passes `--ended`, or asks what is open anywhere,
including stopped sessions. Everything above applies unchanged; only the
collector call and two item kinds differ.

1. **Start** with `$H scan --ended [--days 14]` instead of `$H scan`, shown the
   same way (project, kind, where or "ended", `~N min unlocked`). Ended items
   appear only when they hold open work (`helm.py` → `fleet.ended_open`): a
   `handoff` whose Next steps are non-empty and whose repo has no live session,
   or an `ended-question`. Walk them in the order printed, then `$H wait
   --auto-audit` (section 3); ended items do not change on their own, so rerun
   `scan --ended` when he asks what else is open, not on a timer.
2. **`handoff`** — a chain with next steps and nobody live in its directory.
   Offer exactly: **Start a /baton session now** (first; say the agent and model
   you would pick per session-finder's vendor rules), **Skip** (`$H skip <id>`),
   or **Leave it**. On start: `$L --baton --cwd <dir> --agent <A> --model <M>
   --name "<project>: <active work>" -p "<the next steps, verbatim from the item,
   plus anything he adds>"`. Run `fleet.py conflicts --cwd <dir>` first;
   launch.py refuses when another session is working there — relay that instead.
3. **`ended-question`** — a session that stopped on a question nobody answered.
   Relay the question as the prompt text with options **Answer in a fresh
   session** (`$L --agent claude --cwd <dir> --model <M> -p "<the question> —
   operator's answer: <his text>; continue from there"`), **Resume it** (only
   when the item's transcript size is under 2 MB, see session-finder 3d; give
   the `claude --resume` command for him to run in the pane he picks), **Skip**.
4. **`closed`** — a pane `herdr-tidy` closed (any TUI, Hermes CLI, a shell, a
   sleeping stub); the ledger `~/.local/state/session-finder/closed.jsonl`
   holds its exact resume command, why it was closed and its last screen rows.
   Offer exactly: **Resume it** (first; give the item's `resume:` line to run in
   a free pane, or `herdr agent start <name> --kind <kind> --pane <free pane> --
   <its resume tokens>`; `fleet.py conflicts --sid <sid>` first; then
   `tidy.py resumed <id>`), **Start fresh** (`$L --agent <A> --cwd <dir> --model
   <M> -p "<brief from the item's title and why>"`), **Skip** (`$H skip <id>`).
   Hidden by itself once the session is live again or its handoff chain is listed.
5. **`sleeping`** — a herdr-sleeper journal entry whose pane no longer exists
   (closed by hand, lost in a restart, re-keyed as an orphan): auto-wake cannot
   reach it; only the manual line can. Same three offers as `closed`, with the
   item's `resume:` line (the sleeper's own `manual:` form). A `--days` window
   applies to both kinds (slept/closed within N days, default 14).
6. Started sessions come back through the queue as `done` or `reply` items
   (section 2.5), so the walk continues without you watching them.
7. Ended items are read from logs and transcripts only; nothing is re-opened
   until he says so. Do not summarise a handoff beyond its Active-work line and
   next steps as printed. Closing panes is `herdr-tidy`'s job, never helm's.

## What this is not

1. Not an orchestrator: it starts no work (`orc`, `bigteam` do).
2. Not an auto-responder. agent-deck's conductor answers routine questions
   itself; helm deliberately does not.
3. Not a status feed. Periodic status is `fleet-watch`, which also sends the
   "new session waiting" notice (section 5).
