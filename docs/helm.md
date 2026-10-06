# helm — every waiting agent session, answered from one window

**Built 2026-10-06.** Skill and script: `~/ops/site-djbclark/skills/helm/`
(`SKILL.md`, `helm.py`), linked into every TUI by `skill-everywhere`. This page
is the design record: what was asked, the prior art checked first, how it
works, what was verified, and what is still open.

## What was asked

One window (a Claude session, or Hermes on Telegram) that keeps `/steps`
going in every running session, runs `/loose` in a session once it has
nothing left, and shows each pending decision as a summary, a recommendation
and an option list, titled with the project and where the session lives
(herdr workspace/tab, Orca worktree). The operator changes windows only when
an item needs more depth. It has to be cheap in tokens.

## Prior art (checked 2026-10-06, before building)

| Tool | What it does | Why it was not adopted as-is |
|---|---|---|
| Claude Code agent view (`claude agents`, in 2.1.291) | One list of Claude sessions with a needs-input state and inline reply | Claude only; no Codex/Cursor/Hermes; no audit step |
| [ccgram](https://github.com/alexei-led/ccgram) | Telegram bridge to tmux, **herdr** or agterm: a topic per session, AskUserQuestion and permission prompts as inline buttons, no model | Closest match for the Telegram half. Needs its own bot token and a daemon. Not installed; see "Open" below |
| [agent-deck](https://github.com/asheshgoplani/agent-deck) conductor | A persistent agent session that watches the others, answers routine questions itself, escalates the rest to Telegram/Slack | tmux-based session manager that would replace herdr and Orca; and it answers for the operator, which we do not want |
| [Collie](https://github.com/AltanS/collie) (installed) | Phone web UI for herdr panes, Web Push when an agent waits | Already covers "answer any pane from the phone". Helm adds the single queue |
| claude-telegram-mirror, ccbot, vibe-kanban, Dailybot agent inbox | Telegram mirrors of one tool, or task boards | Nothing to adopt |

None of them runs an audit such as `/loose` in each session and feeds the
result into one decision queue. That is the part that is ours.

## Design

The design follows from three things that turned out to be free here.

1. **herdr already knows each session's state.** `herdr agent list` gives
   idle / working / blocked, the agent's session id, cwd and title per pane.
2. **A blocked Claude session's question is on disk.** Its transcript ends
   with an `AskUserQuestion` tool call that has no result yet: question,
   options, descriptions and the recommended one, exactly as `/steps` wrote
   them. No model is needed to read it or to summarise it.
3. **An answer is a key press.** A digit selects and submits.

So the sessions keep doing their own `/steps` and `/loose`, where their
context is, and helm is a relay:

1. `helm.py` (no model) builds the queue from herdr, the Claude Code session
   registry (`~/.claude/sessions`) and transcript tails.
2. The `helm` skill shows each item as one prompt (AskUserQuestion; `clarify`
   on Hermes) with the session's own text, and sends the pick back with
   `helm.py answer`, which confirms it against the transcript.
3. `helm.py wait --auto-audit` runs in the background and returns only when
   something new needs the operator. While it waits it sends `/loose` to a
   Claude session that has gone idle (3 to 55 minutes idle, not the focused
   pane, empty input box, not audited since it last changed). The `/steps`
   prompts that `/loose` produces come back through the queue.
4. A session idle past 55 minutes is never audited automatically: the
   one-hour prompt cache has expired, so the audit would re-read the whole
   context at full price. It becomes an "audit or skip" item instead.

Token cost: the collector and the wait loop cost nothing; each relayed item
costs the helm session one small prompt; the audits cost what `/loose` costs
in the audited session, once per stretch of new work. A helm session relays
and does not judge, so it can run on a cheaper model.

Helm never picks an option itself, including the recommended one.

## Verified (2026-10-06, herdr 0.9.1-preview, Claude Code 2.1.291)

On a scratch Haiku session in a herdr pane, through `helm.py`:

1. `scan` read the real pending questions of the three sessions blocked at
   the time, word for word.
2. `answer <id> 3` selected the third option; the transcript recorded it.
3. `answer <id> --text "…"` used "Type something"; the transcript recorded it.
4. A two-question prompt: `answer <id> 2 1` sent one digit per question,
   saw the review tab, pressed Enter, and the transcript recorded both.
5. Refusals: option out of range, and no pending question, both exit 1 and
   send nothing. A session is matched by its exact id or name
   only: in testing, an unquoted empty variable turned `answer 2 1` into a
   prefix match on another session (it was not blocked, so nothing was sent).
6. A key sent when no prompt is on screen lands in the session's input box.
   That is why `answer` checks the screen before it sends anything.
7. `helm.py audit` sent `/loose`; its `/steps` prompts came back through the
   queue and were answered from there. herdr reported the session idle for a
   moment between the `/steps` summary and the closing handoff-or-quit
   prompt, so "audited" is read from the transcript (the last prompt there is
   `/loose`), not from a pane-state edge.

## Limits

1. The Orca and tmux channels are written but not exercised: no Claude
   session was running in either at the time.
2. Non-Claude agents give state and a screen excerpt only. Structured
   questions need one small parser per agent.
3. Multi-select prompts are shown but not sent; the item carries the `focus:`
   command.
4. A Claude session outside herdr, Orca and tmux is listed but cannot be
   answered by keys.
5. On Telegram the command is `/skill helm`: Hermes's `skill-slash` plugin
   registers only `/steps` as a bare command, and that plugin is Hermes's to
   change.

6. A session that is idle only because it waits on its own background task
   still gets `/loose` after three minutes; the audit reports the running
   work and nothing is lost, but it is a turn that could have waited.

## Open

1. Trial ccgram as a no-model Telegram front end for the same herdr panes
   (second bot token, new daemon). Deferred by the operator's choice of the
   Hermes skill plus Collie for now.
2. A no-model notifier (`fleet-watch` style) that sends one Hermes line when
   the queue gains an item, so Telegram does not have to be asked.
3. A bare `/helm` on Telegram.
4. Exercise the Orca and tmux channels.
