---
name: steps
description: >-
  Step the operator through open items one at a time, each as its own
  multiple-choice prompt (AskUserQuestion; clarify on Hermes; a SendToUser
  question widget on Grok Bot) with the recommended option first, acting on
  each answer before the next. Use for /steps (optionally with item numbers or
  a topic), "step me through it", "one at a time", "walk me through" a list of
  items or pending decisions.
---

# steps — one open item at a time, recommendation first

Canonical copy: `~/src/djbclark-ade/skills/steps/` (git: `~/src/djbclark-ade`, github.com/djbclark/djbclark-ade); every TUI reaches it via a direct skill-everywhere link `~/src/djbclark-ade/skills/steps`.
Hermes Telegram `/steps` is native skill slash. It injects this skill; call `clarify` (section 2b) so Telegram shows one button per choice. Do not register a plugin command that returns this file — that dumps the markdown and never starts the walk.
Claude Code: `~/src/djbclark-ade/claude/commands/steps.md` → `~/.claude/commands/steps.md` (symlink; `/steps` is also native skill slash).
Grok Bot: a rendered copy `ade-steps` in `/home/box/agent-data/workflows/` (skill-everywhere `grokbot`
target, synced nightly by `/home/box/agent-data/shared/skills-sync/sync.sh`; 2026-10-23).

He is choosing, not reading. Give him one decision per prompt, pre-ranked, and
do what he picked before asking the next one. Same motive as
`memory/feedback_walk_me_through_means_prompt_choices.md`. The difference is
pacing: that note allows four questions per call, but `/steps` asks **one per
call**, so each answer can change the next question.

Never dump the whole queue as numbered prose options for him to type back — the
prompt tool is the walk. (A runtime without a native chooser uses the numbered
one-at-a-time fallback in rule 4 of "Prompt tool" below, not a full-queue dump.
Grok Bot is not such a runtime: it has a question widget, rule 5.)

## Prompt tool (pick once per session)

Use the native chooser your runtime actually has. Do not invent a second UX.

1. **Claude Code, Copilot, Cursor, OpenCode, and any agent with
   `AskUserQuestion` / `question`:** the native arrow-key chooser
   (`AskUserQuestion` on Claude-class agents, `question` on OpenCode).
   Keep using it even if you also have something else.
2. **Hermes:** `clarify`. On Telegram that is a native card: the **question**
   in the message, and **one full-width button per choice whose label is the
   choice text** (not `1`/`2`/`3`), plus "✏️ Other (type answer)".
   Discord/Slack get the same card on those adapters. CLI/TUI get numbered
   text. If the card fails to render, Hermes already falls back to a numbered
   list — do not pre-empt that with prose options of your own.
3. **Codex:** for the terminal arrow-key picklist, use the native
   `request_user_input` chooser when the current mode permits it. It rejects
   calls in Default mode with `request_user_input is unavailable in Default
   mode`; explain that Plan mode is required and wait for the operator to
   switch modes. The agent cannot switch collaboration mode itself.
   `request_user_input_async` is a different surface: an `accepted` response
   establishes submission, not a visible arrow-key picklist. Use it only when
   the client is known to display its question UI. If the operator reports no
   chooser, report the mode limitation rather than reissuing asynchronous
   questions, sleeping, or claiming a choice is waiting in a visible picker.
   Keep unanswered decisions pending. A preselected option or elapsed time is
   not an answer. Honor the native tool's question schema and limits.
4. **No native chooser (no `AskUserQuestion`/`question`/`clarify` tool in the
   function list, and not Grok Bot, which has rule 5):** the walk falls back
   to a numbered text walk, still one
   item per message, still recommendation first. Do NOT refuse with a one-line
   "I cannot prompt" and stop. Instead:
   1. Number the options `1.`–`n.` with the recommendation first (labelled),
      recommendation-first ordering preserved, each numbered once. Numbering
      here is the fallback transport for a runtime that has no picker — it is
      NOT the "numbered prose dump" banned in section 1, which bans dumping
      the whole queue at once and skipping the one-per-call pacing.
   2. Ask exactly one question and wait for the reply before the next; act on
      each answer (or queue it, section 3) before asking the next, exactly as
      a native-chooser walk would.
   3. Say the queue size up front (`1/2`), and offer `stop` once per question.
      Keep it to a single short paragraph — do not re-dump the whole queue
      every turn.
   4. This fallback is for runtimes **without** a picker only. Any agent that
      HAS `AskUserQuestion` / `question` / `clarify` keeps using it (rules
      1–3 above) and never drops to this text fallback; Grok Bot keeps its
      widget (rule 5).
5. **Grok Bot** (djbclark's cloud assistant on its own Linux box, 2026-10-23):
   the question widget, `SendToUser` with type `"widget"`. It is a native
   chooser, not the rule 4 fallback: one question per widget, the widget ends
   the turn, and his pick comes back as his next message. Shape and limits in
   section 2d.

Do not call `AskUserQuestion` on Hermes (it is not a tool here). Do not call
`clarify` on Claude Code. Grok Bot has neither; it uses the widget (2d).

## 1. Collect the items

1. **From the arguments.** Numbers (`/steps 2 4`, `/steps 1a 3`) refer to items in
   your most recent numbered reply. A topic (`/steps the backup stuff`) means the
   open items about that topic.
2. **Otherwise from the conversation.** Take every open item from the latest
   list: loose ends, options you offered, deferred work, questions you asked that
   he never answered.
3. **Drop anything he has already decided.** Don't re-litigate it.
4. **Never invent items to fill the walk.** If nothing is open, say so in one line
   and suggest `/loose` to audit for what might be.

Before the first prompt, show the queue as a short numbered list of titles
("4 items: 1. …"), so he knows how long this will take.

## 2. Ask one item per prompt

Shared rules for every prompt, whichever tool:

1. **One question per call.** Never batch.
2. **Recommended option first.** Distinct outcomes. Include "Leave it as is"
   or "Skip for now" where that is a real choice. 2–4 options.
2a. **Every option label starts with its number** — `1. Client swap only`,
   `2. Full upgrade`, … — so he can answer "do the 3rd option, then the 2nd"
   and be understood (djbclark, 2026-10-20: "from now on, number options so it
   is easy to refer to them from here"). The number is part of the label text
   the tool shows, not something you add only in the prose; keep the numbering
   stable if you re-ask the same item, and in your reply refer back by the
   same number.
3. **"Other" is added by the tool.** He can type `stop` there to end the walk.
4. **Say what it is.** The question is not a title. Lead with position (`2/4`),
   then one or two sentences: what the item is, what it does, and why a choice
   is needed. Longer background is a short prose line *before* the call.
5. **Anything he may click, copy or paste goes in that prose line, as a
   markdown link** (`[label](url)`), never inside the question or an option:
   Paseo's question card is neither selectable nor linkified
   ([getpaseo/paseo#3164](https://github.com/getpaseo/paseo/issues/3164);
   djbclark, 2026-10-19). The card carries only the decision text.
6. **Text he must read before deciding goes in the reply as wrapped markdown**
   (a PR or issue body, a draft message, a quoted document): a blockquote or
   plain prose, never `cat` output. Tool-output blocks do not word-wrap
   (Paseo shows a horizontal scrollbar); reply markdown does (djbclark,
   2026-10-20: "you should always do it that way"). Fixed-width only for
   diffs, commands and transcripts. The file stays the source of truth for
   `--body-file`. Memory: `feedback_long_text_as_wrapped_prose.md`.

### 2a. `AskUserQuestion` (arrow keys)

1. Position in the `header` chip, `2/4`.
2. Put the what-it-is / what-it-does sentences in `question`.
3. Label the first option `(Recommended)` and say why in its description.
4. Put each option's consequence in its description.
5. Use `preview` when comparing concrete artifacts.

### 2b. `clarify` (Hermes / Telegram buttons)

`clarify` has no `header`, no per-option description, no `preview`. The choice
strings **are** the Telegram button labels.

1. Start `question` with the position, then what it is and does, e.g.
   `1/2 — landing-health pager: hourly Jobber job on this Mac that pages
   Telegram Inbox if a must-be-up listener is down. Investigate the last
   page and fix it?`
2. Pass 2–4 strings in `choices`. First string is the recommendation; Hermes
   marks it `(Recommended)` in CLI — do not write that label yourself.
3. Keep each choice under ~60 characters, self-contained (he should not need
   the message body to know what tapping the button does). Section 2b
   overrides shared rule 2a on Hermes: do not number the choice strings.
   Hermes and Telegram number the buttons; a leading `1.` becomes a double
   number and is not how he taps. Put the consequence in the string
   (`Skip — leave pager as-is`).
4. Artifacts go in the prose line before the call, not inside `choices`.
5. One entry in `questions`. `multi_select` stays off.

### 2c. `question` (OpenCode)

`question` is the OpenCode analogue of `AskUserQuestion`: an arrow-key chooser
with 2–4 options, descriptions, optional `multiple`. There is no `header` chip,
so the position (`2/4`) goes at the start of `question`.

1. Lead with the position, then one or two sentences on what it is and what it
   does — same shape as `2a`.
2. First option is the recommendation; label it `(Recommended)` and put the
   reason in its description. Each option's description carries the consequence.
3. Leave `multiple` unset (off).
4. The "Other (type answer)" line is added by the tool; he types `stop` there
   to end the walk.

### 2d. Grok Bot widget (`SendToUser`, type `"widget"`)

Grok Bot's chooser (2026-10-23): `SendToUser` with type `"widget"` and
`widget: {prompt, options: [{label, value, style}], allowCustom, multiSelect, dismissOnMoveOn}`.
The card has no header chip, no per-option description, no `helpText` and no
`preview`, so each item is **two messages**:

1. **A `SendToUser` text message first** with everything that is not the
   decision: the position (`2/4`), what the item is, what it does, why a choice
   is needed (rule 4), each option's consequence when a label cannot carry it,
   links as markdown (rule 5) and text he must read (rule 6). Before the first
   item, the queue list from section 1 goes here too.
2. **Then the widget**, holding only the decision:
   1. `prompt`: the short question, one line (`Investigate the last pager alert and fix it?`).
   2. `options`: 2–4, same as rule 2 (the widget takes up to 6). One-line labels,
      no descriptions. Each label starts with its number (rule 2a):
      `1. Fix the pager (Recommended)`, `2. Skip — leave it as is`.
   3. Recommended option first with `style: "primary"`; a destructive one
      (delete, force-push, revert, close, cancel) gets `style: "danger"`.
   4. `value`: a short stable id per option (`fix`, `skip`), so the reply that
      comes back maps to one option without parsing the label.
   5. `allowCustom: true`: that is the free-text "Other" of rule 3, where he
      types `stop`. `multiSelect: false`. One question per widget, never two.
3. **The widget ends the turn.** His pick (or typed text) arrives as his next
   message. Act on it (section 3), then send the next item's text and widget.
4. **A dismissed widget is a decline.** Record the item as skipped (or left
   open) and move on; do not re-ask it in this walk.
5. **Grok Bot's own rules still bind.** Small picked items are done before the
   next question (section 3.1), but pushing, sending, posting and merging still
   need his explicit OK: an option he picks counts only if its label names that
   exact action (which commit to which branch, which message to whom).
6. **Not on Grok Bot:** `/compact` and `self-slash` (section 3.5). Grok Bot has
   no herdr, Orca or Paseo host and manages its own context; if he picks
   `/compact`, say in one line that it does not apply there and go on.

## 3. Act, then move on

1. **Do what he picked before you ask the next question**, if it is small and
   inside the session's scope. Confirm it in one line ("Done: pushed `abc123`"),
   then ask the next one.
2. **Queue anything bigger** (a long build, a multi-file change, an agent
   dispatch). Say it is queued and do the queue right after the last item.
3. **If an answer or its result changes a later item**, re-rank that item's
   options or drop it, and say so in a line. Don't ask a question an earlier
   answer has already settled.
4. On `stop`, stop. Report what was decided and what is still open.
5. **If he picks `/compact`** (or the context prompt's compact tier, +200k since
   the start or last compaction, fires mid-walk with nobody at the keyboard; he
   pre-approved it standing, 2026-10-09; never compact earlier, it costs more
   than it saves, 2026-10-10), a Claude session in a herdr pane, an
   Orca terminal or a Paseo agent queues it itself: note the remaining queue, run
   `~/src/djbclark-ade/bin/self-slash "/compact <focus: the open items>"`, and
   end the turn at once. Outside those three hosts, or if it refuses (a draft in
   his input box), ask him to type it. Grok Bot: does not apply (2d.6).

## 4. Keep going until nothing is left

**Don't stop after one pass** (standing rule, 2026-10-05: "keep doing more /steps
until there is nothing left to do"). After the last item, work the queue, then
collect the open items again: new decisions the queued work raised, items it
re-opened, results that need a choice. If any exist, start another round (show the
new queue, ask one per prompt, act). Repeat until a round finds nothing open.

What ends the loop:

1. **Nothing open.** No item needs his decision now.
2. **Only waiting is left.** Every remaining item waits on something no answer
   can speed up (a running agent, a quota reset, a build, him holding a phone).
   Say what each waits on and when; don't ask him to re-decide something already
   decided just to keep the loop going.
3. **`stop`.**

## 5. Close with a summary

End with a table: item, his choice, outcome (done / queued / skipped / left
open), covering every round. Number any remaining open items so he can run
`/steps` on them again.

## What this is not

1. Not an audit. `/loose` finds the loose ends and verifies each one, then calls
   `/steps` itself to walk them. `/steps` walks a list that already exists,
   wherever it came from.
2. Not a licence to widen scope. An option you recommend should close the item,
   not start new work he didn't ask for.
