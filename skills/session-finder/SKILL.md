---
name: session-finder
description: >-
  Find which agent session (any TUI, running or ended) is or was on a topic,
  with its handoff chains, where it lives (herdr/Orca/tmux/Paseo/Ghostty) and how to
  continue: message it, /baton from its handoff, resume it, or brief a clean
  agent. Use for "tell the agent doing X ...", "which session is on X", "did we
  ever look at X", "find the session where we did X", /session-finder-all, or
  any relay to a session whose name you don't know.
---

# session-finder — which session, where, and how the work continues

Canonical copy: `~/src/djbclark-ade/skills/session-finder/` (git: `~/src/djbclark-ade`, github.com/djbclark/djbclark-ade); every TUI links it directly (skill-everywhere).
`ListAgents` shows names only (`one-offs-91`), not topics. Four scripts here answer
from local files, with no model tokens:

```bash
S=~/src/djbclark-ade/skills/session-finder
python3 -I $S/session-find.py <keyword>...       # running sessions, every TUI, ranked by keyword
python3 -I $S/session-history.py <keyword>...    # every session of every agent, live or ended, full text
python3 -I $S/fleet.py [list|show <id>|ended|conflicts --cwd DIR]   # the fleet itself
python3 -I $S/launch.py --agent A --cwd DIR --model M [--baton] -p "..."   # start a session (ACP-first)
python3 -I $S/launch.py wait <id> [--timeout S]  # block until THAT launch's turn ends
python3 -I $S/relay.py <id|name> "<one line>"    # message any running session: best route, falls back itself
```

Sibling skills: `helm` (answer every waiting session from one window; `/helm-all`
adds ended sessions), `bigteam` (fan a task out), `model-routing` (which vendor).
Searching everything that ever ran, not only what is running, is section 1.6
here (`/session-finder-all` loads this skill for it).

## 1. Search

1. `session-find.py` ranks **running** sessions: Claude ones by a per-session
   keyword index (title, name, cwd, prompts), every other TUI's by title, name and
   cwd (`fleet.py` supplies them). 1–3 distinctive words. A hit shows agent, name,
   status, `title:`, `where:` + `focus:` and, for Claude, the matching prompt.
   **`FINISHED (/handoff)`** on a hit means that session already handed off: do not
   message it (section 3b).
2. `session-history.py` searches the full text of every agent's sessions (SQLite
   FTS5; first run indexes everything, 1–2 minutes, start it with
   `run_in_background`). Ended hits print a `resume:` command. `--agent hermes`
   narrows to one agent. The same index holds every Basic Memory project's
   `todo/` notes (the `todo` skill's items): a hit prints as agent `todo`,
   `OPEN`/`closed`, `title: [open] main: <title>` and the note path; `--agent todo`
   lists only todos. "Is there a todo for X" is this search, not a semantic one.
   `--check` proves FTS5 works (integrity check plus a probe MATCH; exit 2 if not).
3. `fleet.py ended` lists ended work that still needs someone: handoff chains with
   next steps and nobody live in that repo, and transcripts whose last reply was an
   unanswered question. `fleet.py show <id>` prints one session's last prompt, last
   reply, pending tool call and measured work stretch.
4. Exit 1 / empty: `~/.local/state/handoffs/`, then Basic Memory (`search_notes`,
   project `main`; a semantic hit is not a match — confirm with `find` or an exact
   `read_note`).
5. This session is tagged `(this session)`; never message it.
6. **Everything that ever ran** (`/session-finder-all`, "which session did X",
   "did we ever look at X", "what happened to the X work", or when step 1 found
   no running session on the topic): cast the net widest first, then narrow.
   a. `session-history.py` with 1–3 distinctive words (prefix matching and
      stemming are on); `--agent <a> --limit 20` to narrow. Raise `--limit`
      before loosening the words.
   b. `fleet.py ended --days 30`: open items the transcripts do not show (a
      handoff chain whose next steps nobody took, a session that ended on a
      question).
   c. `launch.py list` (ACP sessions this tooling started) and `ls -t
      ~/.local/state/handoffs/chains/ | head` (chains, newest first).
   d. Basic Memory as in step 4: handoff notes under `memory/handoffs/<repo>/`,
      project notes, todos.
   e. `~/ops/site-djbclark/bin/s1_search.py search '<phrase>' --mode trigram`
      for a verbatim line you remember (session-handoff skill, reader step 4).

   Prefer the session whose **latest** prompt is about the topic over one that
   only mentioned it; two close candidates: name both and ask. Then section 3
   as usual: a live hit is rung a/b, a handoff chain rung c (name it with
   `--chain` when `fleet.py ended` shows more than one for that repo), and an
   old transcript is evidence for a rung-e brief, not something to replay.
   This finds sessions and says how to continue them; walking open items and
   sending answers is `helm` (`/helm-all`).

## 2. Say where it lives (always, when you report)

`where.py <pid>` reads the process's environment and prints the same facts
`hermes-ping` prints for itself: `herdr · ws shells#6 · tab 11#78 · pane claude ·
"<title>" · ~/src/one-offs` plus `focus: herdr tab focus <id>` (herdr, Orca
worktree/terminal, tmux, Ghostty/iTerm/Terminal.app/VS Code; ssh flagged). A Claude
the Paseo daemon spawned has no terminal: `where.py` says `host=paseo agent=<PASEO_AGENT_ID>` (JSON key
`paseo_agent`; recognised by that variable plus the daemon as its direct parent, 2026-10-20).
The finders call it and cache the result an hour (`locations` table in the history DB).

`fleet.py` lists **every** non-archived Paseo agent of any provider (claude, cline, omp, codex, ...), not only Claude
Code TUIs (2026-10-23; before, a cline agent that `paseo ls` showed was missing from `fleet.py list` and looked offline):
a row with `agent` = the provider, `host` = `paseo`, `id` = the first 8 hex of the agent id, `chan` = `("paseo", <full
id>)`, from `paseo ls -g --background --json`, deduplicated on the Paseo agent id (never the directory). `fleet.py --all`
adds the archived agents as `ended` rows (`relay.py` never sends to one). No `paseo` CLI, or a failed or slow call
(20 s): no Paseo rows, as before. `relay.py` takes a hex **prefix of 6 or more characters** of a Paseo agent id
(`paseo ls`'s 7-character short id works); exactly one agent must match, else it refuses and lists the candidates.
A working agent whose provider cannot steer (cline and every other ACP provider, which Paseo would interrupt and replace
the running turn of) is **queued, not refused** (2026-10-24): `relay.py` writes a 0600 record under
`~/.local/state/relay/deferred/`, starts a detached deliverer and **exits 0** with `queued: <id> ...` on stdout
(`"state":"queued","queued":true` with `--json`; a caller that reads 0 as "sent" keeps working; checked 2026-10-24: fleet-watch,
load-watch and session-load-watch read only the exit code and log the last output lines). The deliverer has its own clean environment (no session id of any agent; the sender's Paseo id, label and hop
count come from the record, taken at queue time from the sender's own hosted or fleet-`self` identity), sends the text,
prefixed `[queued Nm ago] `, through the same gates when the agent goes idle, and tells the sender (one
`relay: your message to <target> was failed|expired: <reason>` notice, or `is unverified ... do not resend, check its pane`)
if it cannot; that notice is itself deferred once when the sender is busy (a `kind: notice` record: its own cap of 20, an
hour, owes no notice, never collapsed with a normal record, so no notice loop). **A caller with no identifiable sender**
(no verified Paseo id and no fleet `self` row: fleet-watch, load-watch, a cron script) **is not deferred for**: exit 1 "not
sent: that session is busy and cannot take it now; deferring needs an identifiable sender (it gets a notice if the send
fails). Retry with --idle S, or --no-defer for the plain refusal"; `load-watch` and `session-load-watch` pass `--no-defer` for every incident
brief or load-shedding ask, since a brief that arrives after the load spike is useless. Per target, messages go out in order; at most 20 queued
per target, 20 per sender and 100 in all (over: exit 1 "deferred queue full (N)"); a pane id reused by another session
fails the message ("target changed": the agent, session id or transcript differs, or, for a target with neither session id
nor transcript, the TUI's pid, taken at queue time as the one foreground process named like the agent, is no longer among the
pane's foreground pids; a TUI restarted onto the same session id is still the target). At queue time a herdr pane
with none of session id, transcript or an unambiguous TUI process is not deferred (exit 1); at poll time a pane whose
processes herdr cannot read is an error, and 3 in a row (about 10-15 s) fail the message. A Paseo daemon that cannot answer fails a queued message only
after 3 consecutive errors 5 s apart, counted apart from "not found"; a pending permission or question card is waited for with
capped exponential backoff and full jitter (5 s up to 2 min between looks, never typed into; a target that is only blocked on a card is
queued at once, 2026-10-28, instead of refused). **Why it waits (2026-10-29): `relay.py --why IDENT [--json]`** says which obstacle it is, from two
methods compared: a Paseo agent by `paseo agent inspect` (status, pending cards by tool: a QUESTION is a picklist, a PERMISSION a tool awaiting approval)
plus `paseo permit ls` (the card's text) plus `paseo logs` (its last activity), a pane by the multiplexer status plus the screen itself; states idle,
working, silent (running, nothing new for 15 min: hung or one long tool call), card:question|permission|plan|picker|unknown, archived, gone, error, refused (a
hard stop: the caller's own session, a finished one). **Herald (2026-10-30)** is a third witness (`src` `herald-attention`, from `~/.paseo/plugin-data/herald/attention.json`;
an absent file changes nothing): a `question`, `plan` or `permission` it reports blocks like a card even when `inspect` and `permit ls` list none while the agent runs (the methods
DISAGREE, blocking wins); on an idle agent with no card it is a leftover (`agree` False, still deliverable), an `error` is `needs_you` in `--json` and `why` (never a `paseo permit allow` card; the agent stays deliverable), `finished` and
`canceled` only add evidence; its headline and detail are shown by `--why` only as evidence labelled untrusted agent text, never in `why`, never filed. A Paseo-hosted Claude row with a sid is `blocked` in
`fleet.py` from Herald too while its registry status is not `idle` (row key `herald`: reason, eventId, requestId, createdAt, status). a
disagreement between the methods is reported and the blocking reading wins. `--pending` shows each queued record's latest reason as `[why: ...]`. **Two
witnesses for delivery (2026-10-29):** a Paseo target's transcript AND its own timeline (`paseo logs`), either proves, so codex, omp, opencode and cline
Paseo agents are "delivered", not "unverified"; `--sweep` reads a transcript-less sender's own timeline for `ack ID`. A record
`sending` for 15 minutes is failed "unverified": a deliverer still alive stops, and when its send returns the log and
the notice say "unverified", never "delivered". `--idle S`
still blocks for idle and wins, `--no-defer` restores the refusal (exit 1), `--defer-for S` sets the life (default 6 h, at
most 24 h); `relay.py --pending [--text] [--json]` lists (the text only with `--text`), `--cancel ID` withdraws a queued
one, `--retire ID --reason "..."` closes an expectation that will never be answered and records why (only an `open` one; state
`retired`, the reason and evidence stay in the record and `--pending` shows them; the target cannot retire its own, it answers
`ack ID`), `--sweep` re-arms records whose deliverer died (it also runs, cheaply, at the start of every relay: it only changes
states and starts detached deliverers). A non-Claude pane TUI that is working is deferred the same way. Archived,
wrong-directory and no-route refusals are never deferred. Residual: `PASEO_AGENT_ID` is an
environment value a same-user process can forge, as `HERDR_PANE_ID` is, and the bounds can be starved (100 records in all:
a same-user process that mints sender keys fills the queue, never silently; one sender can fill one target's 20; a stuck
deliverer holds its own record's notice until a later sweep). claude, codex, omp, opencode and pi
can steer (`fleet.PASEO_STEER_PROVIDERS`, read from the Paseo daemon bundle 2026-10-23), but Paseo replaces the running
turn of even these when the provider declines the steer at that moment (while Claude or Codex compacts, a Codex review
turn, an omp steer error), which relay cannot see beforehand: only **claude** is steered into a working agent by default;
a working codex, omp, opencode or pi agent is queued unless `--steer` (or `--idle S`). A Paseo agent with no Claude
registry row is found by its id, Paseo id or hex prefix, never by its workspace title (titles come from its first
prompt). A running one with a pending permission or question card shows as `blocked` (one `paseo permit ls --json`),
`relay.py` refuses it, and helm lists it as a `permission` item with every card and its own
`paseo permit allow|deny <agent> -- <request id>` (never without the id: `allow` alone approves all the agent's cards), or the Paseo UI (helm presses no keys there).

**Give three things:** the session name, its title, and the `where:` line with the
`focus:` command. `one-offs-91 "CCC slow performance" — herdr ws shells#6 · tab
11#78 · pane claude (focus: herdr tab focus w27:t2E)`.
For an **ended** session give agent + session id, title, its last activity time
and transcript size (they decide rung 3d versus 3e), and end with the command
you recommend, ready to run.

## 3. Decide how the work continues — cheapest adequate first

Pick the first rung that applies. The cost model: a running session already holds
its context (free while its prompt cache is warm, under 55 minutes idle; still the
cheapest option when cold); resuming an ended transcript re-reads all of it at full
price (about 250k tokens per MB); a `/baton` session reads only the Tier 1 log and
the Tier 2 handoff (a few thousand tokens); a clean session reads only its brief.

a. **Running and not finished → message it, even while it is `working` on
   something else** (operator, 2026-10-17: I asked instead of relaying to a busy
   `~/ops` session, and he said an open agent is never blocked and I could have
   sent it the task). A message to a working Claude is queued for its next tool
   round, so it interrupts nothing. Read its latest prompt line only to name
   files it is editing (section 4.2), not to decide whether to ask. Ask the
   operator only when it is the same task or the same dirty files; otherwise
   relay the request and say so. Reach by the table in section 6. **SendMessage fails** ("No agent
   named … is reachable": a workflow sub-agent's `ListAgents` often lists only its
   teammates, 2026-10-11), **or a `[Cross-session delivery notice]` says it was
   refused** (that session turned inbound messages off, 2026-10-12) →
   `relay.py <id> "<one line>"`. **It is the one command for messaging any peer** (2026-10-23): it picks
   the best route for that session (Paseo `send`, `acp-dispatch tell`, a live launch's inbox, keys into its
   pane, then the Claude messaging socket; a Hermes gateway conversation by `hermes --resume SID -z`) and tries the next route itself when one fails before sending;
   it errors only when every route has, listing each reason (`--plan` shows the order, `--via R` pins one).
   Don't pick a channel by hand or hand-roll a waiter. A working Claude queues it for its next tool round. Put a
   long brief in a file and relay one line naming its absolute path. For a headless worker or a custom
   `acp-dispatch --out` directory absent from the fleet list, pass its exact record:
   `relay.py /absolute/jobs/name.json "<text asking for ack NAME>" --via dispatch`. The output names
   its inbox and replies file. `queued` proves only the write; a named `REPLY N:` acknowledgement
   proves the worker read it. Finished or closed records are refused, never resumed here. Don't resend
   a refused message, and don't hand the operator a clipboard prompt to paste in
   its place: relay it.
b. **Running but finished** (`finished: /handoff` or `/quit`: its last prompt was a
   handoff or it is sitting at "Bye!") → **never continue there** (operator rule,
   2026-10-08: "it ends with a /handoff; a new session should be opened in its CWD
   with a /baton"). Start a fresh session from the handoff:
   `launch.py --baton --cwd <dir> --agent <A> --model <M> --pane <its pane> -p "<instruction>"`.
   `--baton` resolves the chain whose workspace is that directory (`--chain <id>` to
   name one; `fleet.py ended` lists them) and hands the new session the canonical
   log path, so it never falls into the "which chain?" prompt. `--pane` reuses the
   finished session's pane after sending it `/exit` (refused if a draft is in its
   input box); a pane that is gone falls back to a new tab. `--model` for an acp-run claude is checked before any tab opens
   (`claude-sonnet-5-5` is mapped to the `claude-sonnet-5` that `acp-run claude` takes; an unknown id exits 2,
   2026-10-25). **On herdr, `--baton` with claude or codex starts a real TUI, not an acp-run session**
   (djbclark, 2026-10-25: an ACP pane shows only "⚙ Terminal" lines, nothing a human can read or steer):
   `herdr agent start NAME --kind K --pane P -- <yolo, model, effort>` then `herdr agent prompt` with the brief,
   `--effort E` allowed, `--acp` keeps acp-run, `--tui` forces a TUI without `--baton`. A TUI session can take
   `/new`, `/compact` and another handoff; an acp-run one cannot (`self-slash` exits 9). `--no-interactive`
   (a dispatched slice) is never a TUI. A session handing ITSELF off uses `self-slash` (handoff Step 9), not this.
c. **Ended, with a handoff chain for its directory** → the same `launch.py --baton`.
d. **Ended, no handoff, and the task needs that exact context** (a debugging state
   only that conversation holds) → resume it, but only when the transcript is small:
   under 2 MB freely; 2–8 MB only if nothing else can replace it (say the size);
   over 8 MB never — write a brief from `session-history.py`/`fleet.py show` and use
   rung e. Resume form: `cd <cwd> && claude --resume <sid> [--model sonnet]` (other
   agents: the `resume:` line session-history prints). Host it visibly with
   `herdr agent start <name> --kind claude --pane <free pane> -- --resume <sid>`;
   in Orca, `orca terminal create --worktree path:<cwd> --title <name> --command
   "claude --resume <sid>"` (a fresh terminal; there is no "free pane" to reuse).
   Never resume a session id that is live anywhere (`fleet.py conflicts --sid <sid>`
   says `SESSION ALREADY LIVE`): two instances share one transcript.
e. **Otherwise a clean session**: `launch.py --agent <A> --cwd <dir> --model <M>
   -p "<self-contained brief>"`. Write the brief the way the `todo` skill's
   *Prompt* rules say (absolute paths, goal, evidence, rules that bite, done
   condition). For harness-internal state (task ids, memory notes, session
   ids) name the tool that reads it and paste a snapshot: a fresh session
   that cannot find a bare id guesses. Three or more independent slices → `bigteam` instead.

### Vendor × model × effort (b–e)

Choose with `model-routing` and `aiuse --available` (bigteam Step 1), cheapest
adequate pool first; re-probe before each launch, since pools move:

1. Judgment, integration, anything security-relevant: Claude (`opus`; `sonnet`
   for ordinary implementation; `fable` only for the hardest adjudication). The
   `claude` ACP adapter takes `--model opus|sonnet|haiku|fable`.
2. Mechanical, bulk, writing, research: a fresh subscription pool — codex,
   opencode-go, cursor, copilot (small GitHub-shaped slices only). Reserve pools
   (clinepass/Hermes) never for bulk; grok vendor excluded (bigteam's *Current
   exclusions*); agy only via ACP and only once it is back (todo note).
3. **Change the vendor or model for a `/baton` or resumed session only when the
   saving is real**: a handoff is on disk, so a `/baton` session can run on any
   ACP agent that reads skills (claude, codex, copilot, cursor, opencode, qwen,
   hermes); a long mechanical continuation of Claude work can resume with
   `--model sonnet`. Keep the vendor when the next step needs the same judgment
   that produced the handoff, or when the repo's rules name a tool only one agent
   has. Say which you chose and why in one line.

## 4. Never collide with another session (standing rule, 2026-10-08)

Before relaying work into a repo, resuming, or launching:

1. `fleet.py conflicts --cwd <dir> [--sid <id>]`. Exit 1 means another session is
   **working** there (or that session id is already live): do not start a second
   one; message the working session instead (rung a), or wait. `launch.py` runs
   this check itself and refuses unless `--force`.
2. Dirty files in the worktree and files named by live bigteam claims
   (`~/.local/state/bigteam/*/CLAIM`) belong to someone else: `launch.py` writes
   them into the brief as do-not-touch and records its own claim
   (`~/.local/state/bigteam/sf-<id>/CLAIM`, `DONE` appended when the run ends).
   When you message a running session about new work, name those files yourself.
3. Two sessions close in score on the same topic: ask which, or tell the one whose
   latest prompt is on the topic and tell it the other exists.
4. Hands off other sessions' panes: reach them through their channel, never by
   closing, reusing or typing into their terminal (bigteam Step 0).
5. Prior art checked 2026-10-08: lease/lock daemons (dos-kernel lanes, Wit symbol
   locks, decapod `todo claim`) and agent-deck's refusal to read a transcript two
   live instances share. The claim files above are the local form of the same idea.
   [hcom](https://github.com/aannoo/hcom) (MIT; read 2026-10-11) does it with hooks
   into a shared SQLite db: agents launched as `hcom <tool>` (or that run `hcom
   start`) message, watch, spawn, fork, resume and kill each other, herdr panes
   included, and can subscribe to file-edit `collision` events.

## 5. Start sessions over ACP, visibly

`launch.py` drives the agent over the Agent Client Protocol through `acp-run`
(typed permissions, exit codes, JSONL log) because key presses into panes have
proven fragile (operator, 2026-10-08). The call runs inside a terminal the
operator can watch: an Orca terminal when launched from Orca (`orca terminal
create --command`), otherwise a herdr tab in the workspace that already holds that
repo (a new workspace when none fits), reported to herdr as an agent so `helm`
and `fleet.py` list it like any other. Agents with no ACP route (zcode, muse)
get `herdr agent start --kind` plus `agent prompt` — the fragile way; say so.

1. **The pane shows the agent and takes input** (`acp-run --interactive`,
   2026-10-08): output streams into the pane as it happens; when a turn ends the
   session stays open and waits for the next prompt from the keyboard in that
   pane *or* from its inbox (`launch-<id>/inbox/*.txt`), which is what
   `launch.py reply <id> "<text>"` writes — no keys, no screen scraping. `helm`
   shows a `done` item per finished turn (or `reply` when the text asks a
   question). `--no-interactive` is the one-turn-and-exit form, and a `reply`
   to an exited session starts a new turn with the brief and last reply as
   context. **Headless turns go through `acp-dispatch`** (2026-10-08; `bin/` in
   djbclark-ade): `--model` is mandatory, the shared delivery footer
   (`docs/dispatch-footer.md`) is appended to a copy of the brief, and the turn
   leaves `launch-<id>/<id>-report.md`, its `.done` marker and
   `launch-<id>/jobs/<id>.json`; the launch's recorded exit is acp-dispatch's
   (0 done, 1 unfinished, 3 no report, 4 `BLOCKED:`, 124 timeout), and
   `acp-dispatch check ~/.local/state/session-finder/launch-<id>` classifies it.
   An interactive session is not a report-producing sub-agent, so it keeps
   plain acp-run and no footer. acp-run reports `working`/`idle`/`blocked` to
   herdr with its resume command, so `herdr agent prompt` and a herdr restart
   both work.
2. **Finished sessions are audited, then closed** (operator, 2026-10-08):
   `launch.py audit <id>` sends `/loose` as the next turn; `launch.py close <id>`
   sends `/exit`, marks the launch closed and closes its herdr tab (or pane), or its Orca
   terminal (`orca terminal close`, never the caller's own), so tabs do not accumulate. `helm.py wait --auto-audit` does both without asking:
   audit when a launch goes `done`, close once the audited result has been shown.
   **A test or trial launch you drive yourself: `--mark <label>`** (or
   `SESSION_FINDER_MARK=<label>` for a whole script). The mark is recorded and
   inherited by every later turn; `launch.py audit` refuses it (`--force` to
   override), so the operator's standing auto-audit cannot take it over (hcom
   trial, 2026-10-11), and `fleet.sessions(include_marked=False)` leaves it out.
   You audit and close it.
3. Always `--model`. Default `--timeout` is four hours per turn (an hour cut a
   real deploy short); acp-run runs yolo for every agent (operator 2026-10-14),
   so the only gate is `--perm read-only` for a review-only session (`deny` gives claude no tools) (`scoped:` and
   `ask` are deprecated: a warning, then `--perm all`); `--files` lists the
   paths the claim owns, and the diff afterwards is the check that it kept to
   them. On herdr 0.9.1 `herdr agent prompt` does not reach a session that
   reported itself (Claude Code's own hook owns the pane), so text goes through
   the inbox (`launch.py reply`) or `herdr pane run`, never `agent prompt`.
4. **Next turns and waiting** (2026-10-11 fixes). `launch.py reply <id>` keeps
   the original host (`--host none` stays detached), mode (headless stays
   acp-dispatch) and mark unless you pass them. It is **refused** when `<id>` was
   already continued (`superseded_by`; the message names the newest turn to reply
   to) or another open launch holds its ACP session: two `session/load`s of one
   session are the shared-transcript case section 4 forbids. `reply` and `audit`
   check and start under one lock. `launch.py wait <id> [--timeout S] [--json]`
   blocks until that launch's turn ends, including a prompt still queued in its
   inbox, and follows `superseded_by` to the newest turn (exit 0 ended, 3 timed
   out). Use it instead of `helm.py wait`, which returns the first fresh item of
   any session. A detached interactive launch (`--host none`) now stays alive
   between turns (it reads a FIFO, so stdin never hits EOF), so replies go to its
   inbox in the same process. `--dry-run` writes nothing and touches no pane; it
   prints the record, the command and the runner script.
   Claude session ids: over ACP, claude-agent-acp picks the id, logs it as
   `new_session` and passes it to Claude as `--session-id`, so the logged id is the
   exact conversation (`claude --resume <it>` or `launch.py reply`). A headless
   Claude launch also seeds `acp-run --session-id` (`session_seed`), the id
   acp-run's `claude -p` fallback runs as after an ACP handshake hang.
5. Everything about a launch lives under `~/.local/state/session-finder/launch-<id>/`
   (brief, acp log, out, err, runner, inbox; for a headless turn also the
   acp-dispatch brief copy, report, `.done` and `jobs/` record) and
   `launches.jsonl`; `launch.py list` shows state.
6. Exit 0 is not success: read the `done` text and the diff, as for any delegation.

## 6. Reach each agent

`fleet.py list`/`show` print a `WARNING:` on stderr when `~/.claude/settings.json` lacks `env`
`CLAUDE_CODE_HARBOR_KITE=1`, or the installed Claude binary no longer reads it: without it, a server flag that
flips to false turns peer messaging off in running Claude sessions (2026-10-13; anthropics/claude-code#100760).

| Agent / host | Running session | Ended session |
|---|---|---|
| claude (TUI) | `SendMessage({to: "<name>"})`; read its latest prompt line first. Not in your `ListAgents`, no messaging socket (`fleet.py` then says so in `reach:`), or a delivery notice says SendMessage was refused → `relay.py <id> "<one line>"` (route ladder, best first, falls back by itself: keys into its herdr/Orca/tmux pane → Claude socket frame; queued while it works; the pane route is skipped on a typed draft, and an open question stops all routes; a dim/grey suggested prompt is not a draft). A Paseo-hosted one (`where: host=paseo agent=<id>`, or you were handed a `PASEO_AGENT_ID`): `relay.py <sid|name|agent-id> "<text>"` runs `paseo send --behavior steer -- <id> <text>` (its only route; any refusal from `paseo agent inspect` ends the run) with your own `PASEO_AGENT_ID` kept, so Paseo labels it an agent message from you (a caller that is not a Paseo agent gets a `[relay from <name>] ` prefix), never the operator's turn. It re-runs `paseo agent inspect` first and refuses an archived agent, a pending permission or question card (helm only lists a card of a Paseo agent that has no Claude transcript and presses no keys there: the Paseo UI, or `paseo permit allow|deny <agent> -- <request id>` per card, answers it), a status other than idle/running, and text starting with `/`; `--idle S` (finite, > 0) waits for idle first; no draft check, there is no input box. Exit 0 means "accepted" (the daemon's acknowledgement), or "delivered" once a Claude transcript shows the text (2026-10-20). Finished (`/handoff`) → rung 3b, never SendMessage | `claude --resume <id>` (rung 3d) or `launch.py --baton` |
| any ACP launch (`host acp`, id `YYYYMMDD-…`) | `launch.py reply <id> "<text>"`, then `launch.py wait <id>` | `launch.py list`; its log under `~/.local/state/session-finder/` |
| a headless `acp-dispatch` slice (including custom `--out` records and workers with no fleet row) | `relay.py /absolute/jobs/NAME.json "<text asking for ack NAME>" --via dispatch`; `queued` is not delivery; verify the named acknowledgement in the printed replies file | `acp-dispatch resume <record>` only for a new authorized task, never as a relay side effect |
| an `acp-dispatch` / `acp-run claude` slice (headless) | Use `relay.py` with its fleet id or exact job-record path as in the previous row; verify a named acknowledgement in the replies file. Slices older than 051a269 lack the inbox-reading footer: reach them through their lead. | `acp-dispatch resume RECORD` only for a new authorized task |
| hermes (Telegram/desktop chat, `hermes-gw`) | `relay.py <id|sid> "<text>"` (2026-10-23): `hermes --resume <sid> -z` runs one turn in that conversation's own transcript, tagged `[relay from <name>] `; Hermes's reply is printed (untrusted data, not posted in the chat); it refuses Hermes's own conversation, an unknown session is refused before writing, any other failure is "unverified" and a turn past max(100, `--wait`) s is left running (relay.py never kills it; a caller's tool timeout that kills the process tree does, so give the command max(100, `--wait`) + 50 s or run it in the background) and holds a per-conversation lock (a cut-off relay.py counts as unverified: do not resend). `ask_hermes` (MCP) is a separate one-shot session, not this conversation; `messages_send` with `target="telegram:<chat>[:<thread>]"` posts as Hermes; approvals: `permissions_list_open` / `permissions_respond` | `hermes --resume <id>` |
| hermes (CLI in a pane) | `helm.py send <pane> "<text>"` when herdr shows it idle; a native Hermes TUI herdr does not detect is the row below (`show`, then `send --screen-fp`) | same |
| hermes (to make it *change* something: `ask_hermes` is read-only) | after djbclark's yes for that run: `ACP_OPERATOR_APPROVED=hermes launch.py --agent hermes --cwd ~ -f brief.md --model <explicit id>`; pick the id from its `new_session` model list, never `custom:*` (2026-10-17: `custom:big-pickle` went to sipb-llms-proxy, not ClinePass) | `launch.py reply <id>` |
| muse | `muse session-message send --target <uuid|name>`, body on stdin | `muse resume <id>` |
| codex, cursor, opencode, cline, copilot, qwen, zcode, agy (TUIs in herdr/Orca/tmux) | `helm.py send <id> "<text>"` when idle (keys into the pane; verify on screen), else its `focus:`. A herdr-idle agent whose agent API refuses input (`agent_not_ready: not an active named agent`, seen on a Crush pane 2026-10-25): `helm.py show <id>`, read the screen (empty input, nothing pending), then `helm.py send <id> --screen-fp <fp> "<text>"` (pane verbs; fresh-screen and pane checks, plus the pid where fleet knows it; never for a working, question, permission, plan, finished or self row). Without the flag an idle row still uses `agent prompt` | the `resume:` line session-history prints |
| a TUI herdr does not detect (`zcode`, `muse`, a native Hermes TUI, …; listed from `pane process-info`, status `unknown`: never idle by itself, `helm.py send` refuses it) | `helm.py show <pane>` (prints the screen and `screen-fp`, both from one capture; none, and no send command, if herdr could not read the screen), read that screen, and only if it shows an idle, empty input (a dimmed suggestion is not a draft) and no pending question, approval or plan: `helm.py send <pane> --screen-fp <fp> "<text>"` (2026-10-25). Herdr has no agent entry for such a TUI (`herdr agent read` and `agent prompt` fail `agent_not_found`), so helm reads with `herdr pane read` and types with `pane send-text` then `pane send-keys enter`, after the second fingerprint check; a failed typing never presses Enter, is never retried and reports "unverified, do not resend". It is refused if the screen is unreadable or changed since (elapsed-time counters are ignored, so a turn that shows only as a ticking timer is not seen), is another pane or process, or the row is not such a TUI; nothing is inferred from the screen. `sent` is a submit, not a read: verify on screen (`helm.py show`) or by a named acknowledgement in the text | the `resume:` line session-history prints |
| anything in Ghostty/iTerm/ssh with no channel | tell the operator the `where:` line | — |
| a pane `herdr-tidy` closed, or a sleeping pane that is gone | — | `fleet.py ended` / `helm.py scan --ended`: the `closed` / `sleeping` item's `resume:` line (ledger `~/.local/state/session-finder/closed.jsonl`; herdr-sleeper journal) |

Rules that still apply: a peer's claims are authoritative; check it is not
mid-flight on something contradictory before relaying; never relay a request to
bypass a permission denial; grok is excluded (2026-10-06).

## Verified peer messaging (2026-10-25, standing order 10; docs/queue.md "Verified peer messaging")

Proof, not conversation: delivery proof (the text reached the target's transcript) is mechanical and needs no reply; a reply is required
only where the message asks a question or requests action. An FYI that provably landed needs none.

1. **The delivery watch is on by default for an agent session** (2026-10-25; `--ack` asks for it whoever you are). A send that is only `accepted` (a socket frame or Paseo send to a working session) or `queued`
   (an enqueue Claude Code has not taken yet, a deferred record) is watched for up to 10 s (`--ack`: `--wait` s) more, so a plain send takes at most `--wait` (default 20) + 10 s, and exits **0 delivered**,
   **1 not delivered** (not sent, pulled back out of the queue, failed or expired), **3 unverified** (sent or still queued, no proof yet: do not resend; an
   ACP inbox or a Paseo agent with no Claude transcript has nothing to read, so it is unverified at once). `--no-ack` (or `RELAY_NO_ACK=1`) turns the default off for any caller. A **declared job run by launchd**
   (`RELAY_SENDER_NAME` and no session in its environment: fleet-watch, load-watch, session-load-watch, rumination-watch) never gets the default and keeps the old exits (`queued` and `accepted` exit 0, "taken"); the same job run
   from inside a session (an agent running `fleet-watch --relay-test`) is identified and does get the default, so it passes `--no-ack`: the three watchers in this repo do (fleet-watch's two relay calls are a follow-up in site-djbclark).
   `--json` carries `ack` and `ack_note`, and `"ack_default": true` when the watch was the default. An `ack ID` reply (alone, or with a remark of at most 40 characters in parentheses or after a colon, no `?`, no request word),
   an ack of an ack and a text whose **last clause** is "no reply needed" are **terminators**: they take no footer, open no link (so nothing loops) and still get this proof. Only the bare shape (`ack ID` alone, or the phrase alone) refuses
   `--expect-ack` and `--needs-reply` (exit 2); on any longer text the flag wins and the text is an ordinary one. `ack the PR and merge it` is no terminator: it goes the normal path with the first-contact footer (the peer answers `ack ID`, one extra message).
   **When the proof is not `delivered`, you handle it** (requester steps, never assume read):
   a. Exit **1**, or a link that fleet shows as `ONE-WAY`: the text did not land or was never answered. Re-send **once** by **another** route (`--via`; `--plan` lists them), never the same route twice.
   b. Exit **3** (`unverified`), `queued`, or `accepted`: do **not** resend yet; read the target's transcript (or `relay.py --pending` for a deferred record) for the text first. Only a text that is absent is re-sent, by a different `--via`.
   c. An `OVERDUE ack ID` line from `--sweep`: ask for a named ack in a new message (`... please reply ack ID2`, with `--expect-ack ID2`).
   d. Still unproven after that: report to the operator with the exact line from `relay.py --pending` (or the `OVERDUE ack ID: ...` line); once it reads `ASSUMED LOST` (6 h past due), re-route your own expectation's work instead. Never assume read.
2. **A question or an action request needs `--expect-ack ID`**: a `?` outside a URL, or `--needs-reply`, is refused (exit 2, nothing sent) without it
   when you are an identifiable session; `--fyi` overrides a `?` that is no question. `ID` is 1-40 characters of `A-Za-z0-9._-`, unique among open ones. The sent text
   ends `[reply through relay.py to <your id>: ack ID]`. It is **state, not a wait**: `relay.py --pending` lists it (sender, target, age, `OVERDUE`;
   `--json` rows have `"kind": "expect"` and the keys `kind, id, state, sender, target, age_s, within_s, overdue, assumed_lost, created` (a `state: "retired"` row also carries `reason, evidence, retired_by, retired`, never `overdue`); `created` is the record's creation time (fractional epoch seconds, `0.0` when missing, non-numeric or non-finite; use it verbatim, never round or truncate it), which with the ID names one expectation, since a closed expectation's ID may be reused), and `relay.py --sweep` resolves it when a user-role line in YOUR transcript says `ack ID` under the target's relay header (its ID word or `aka` name; a Hermes session answers as `hermes <last 8 of its session id>`;
   two sessions with one name are not told apart, and a same-uid process can forge a header) (your own tool calls and results never count). After `--ack-within S` (default 1800) with no answer it is OVERDUE: the sweep prints `OVERDUE ack ID: ...`, and **you tell the operator**; never assume read. **6 hours past due (2026-10-28)** the line ends `ASSUMED LOST` and `"assumed_lost"` is true: for an expectation YOU opened, re-route the work once without asking (peer-relay rule 13); another sender's row is theirs.
   **No transcript needed (2026-10-26):** a session with a fleet row but no readable transcript may open `--expect-ack` too, but it can close only by the route rule below; its record holds no transcript (`tx: null`) and `--sweep` reads none for it. It is closed when the target's reply goes THROUGH `relay.py` (the footer says so) as a text that begins `ack ID`, sent to you: relay closes it itself, from the target's fleet identity, never from the text. This applies ONLY to a sender with no readable transcript; a sender with one is closed by its transcript alone, as before. **A native pane sender with no transcript (OMP, Hermes TUI, opencode, gemini, pi in a herdr or tmux pane) can NEVER be closed this way: relay reaches it only by the pane route, which proves nothing for it, so every `--expect-ack` it opens goes `OVERDUE` even when the target answered at once (the safe direction; close it by hand).** The relay-side close works for a sender reached by a route that proves delivery or keeps the text: a non-Claude Paseo agent, an ACP launch or an acp-dispatch slice. It counts only when that reply's delivery watch ran and the route PROVED it delivered, or handed it, with no proof to take, to something that keeps the text (a Paseo agent the daemon accepted it for, or an ACP launch or dispatch inbox it was written to). A reply that does not go through relay.py, a third party's `ack ID`, another ID, a replay or an ack that was refused, failed, pulled back, sent with `--no-ack` (no watch ran, so nothing counts), only queued for a busy peer (the deliverer never closes one), typed into a pane that shows it only as "queued" (a screen match, no proof), or whose delivery watch ran out without seeing the text closes nothing, so it goes `OVERDUE`. An ack deferred to a BUSY no-transcript Paseo recipient never closes either, so the sender may go OVERDUE although it was delivered: that is the safe direction (a false ack silences the page for a dead return path), do not loosen the gate. Only a caller with no session at all (a launchd script) is refused `--expect-ack`.
   **A Hermes gateway conversation as the target (2026-10-27, Codex P2 #2, PR 87):** it closes such a record with `ack ID` through relay when relay recognises the caller: the full `HERMES_SESSION_ID` equals the session id of exactly one live `hermes-gw` row, and the relay process descends from the pid written in that conversation's lock file (`hermes_lock_path(sid)`) or in `~/.hermes/gateway.pid`, with no `fleet.PROC_AGENTS` agent other than Hermes between. Relay reads only the digits of the lock file and the JSON `pid` of `gateway.pid` (`int()` of that value, so `true` reads as 1, the pid-1 anchor every walk reaches): it checks no liveness, command, flock or start time, and the anchor pid itself (or 1) passes. It is never taken from `RELAY_SENDER`, `RELAY_HOPS` or the 8-character label, and the record's target must carry the same full session id (a record with only the date-prefix `sid8` stays open). A relayed Hermes turn drops the `self` mark it inherits from its asker's herdr pane, so its `ack` to that asker is no longer refused as "that is this session". A Hermes conversation can only CLOSE: `--expect-ack` from it exits 2, and it can no longer defer a send to a busy target (exit 1, "deferring needs an identifiable sender"; before this change a relayed turn from a herdr asker deferred under the asker's id, a misattribution). Bounds (same-uid, not cryptographic): ANY deliberate same-user process can answer as a conversation by setting `HERMES_SESSION_ID` to a live gateway row's full session id and writing an ancestor's pid into that conversation's lock file or into `~/.hermes/gateway.pid` (the same class as `HERDR_PANE_ID=... relay.py` naming a pane; a shell outside Hermes that only sets variables is still refused, unless a pid left in that conversation's lock file (kept at least 7 days after its last relayed turn, until a later relay into Hermes prunes it) or in `gateway.pid` now belongs to the shell or one of its ancestors (pid reuse; relay checks no liveness)); a process inside the gateway needs no file write to answer for another of its conversations; omp, pi, gemini and any agent not in `fleet.PROC_AGENTS` started inside a turn is not stopped by the walk (a Paseo-hosted agent is not a descendant of a turn, so it does not pass); a conversation whose session id rotates stays open and goes OVERDUE. Further bounds and the relay.py wording still to fix: `docs/queue.md` item 9.
   An answer that arrives while the question's own send is still running (a Hermes target's route returns only after its whole turn) is kept (2026-10-26, Codex P2, PR 87): the reservation made before the send names both ends, the relay-side close accepts it under the same route rule as an open record, and the record the send then writes stays `acked` (`early: true`). A send that did not happen, whatever answered meanwhile, drops it: never an `acked`. An early-acked ID is held until its send returns (`sent: true`, adversary r5 F1), at most `EXPECT_RESERVE_TTL` (600 s) after the reservation, so a second relay cannot reserve it meanwhile. A reservation older than `EXPECT_RESERVE_TTL` (600 s) closes nothing: that bites only a send that blocks 600 s or more after the reservation (Hermes with `--wait` about 600 or more), whose late ack is lost and whose question goes OVERDUE, and a send that blocks longer can lose even an early answer and the ID to another relay; at the default `--wait 20` a Hermes turn returns `unverified` after `max(100, --wait)` s and the open record is written normally. A busy non-Claude pane sender or a non-steerable Paseo sender gets the ack deferred, so such a question can still go OVERDUE (same as the open path).
   Handoff transfer (2026-10-28): after the old session finishes, the successor FIRST runs
   `relay.py --transfer-expectations OLD_SENDER [--id TOKEN ...] [--json]`, THEN tells peers to address delayed `ack TOKEN`
   replies to the successor. OLD_SENDER must exactly name one fleet id, full session id or Paseo id whose row carries
   `finished`: Claude's transcript `/handoff` or `/quit` heuristic, or ACP `done`. This is the same evidence as `hard_stop`,
   not proof the process exited: an ACP session can take another turn. Non-Claude Paseo agents cannot be transferred yet
   (no `finished` evidence; exit 2). Live, missing, ambiguous and self rows are refused with exit 2, without changes.
   A same-pane successor with the same fleet id cannot transfer, even with a different session id and the old full session id.
   The successor must have its own fleet `self` identity, not a deliverer override or Hermes caller.
   Only the old sender's open expectations are considered; closed/reserved records and deferred sends stay unchanged.
   When the old row has a session id, each record must store that exact non-empty sender session id. Without it, a record
   with no stored session id is eligible only if no other fleet row shares the old id; a stored non-empty id must still match.
   Records failing that check, or targeting the successor's id/session id, are listed as `skipped` and stay unchanged.
   Under the expectation lock, an ack still unswept in the OLD transcript IS counted using its original offset and target identity:
   the record becomes `acked` and its old return-path link is updated, rather than transferred. Otherwise the record keeps its token,
   target, state, creation time and deadline; sender identity and transcript become the successor's, with `transferred_from`
   (previous sender/transcript and prior transfer history) and `transferred_at` audit fields. Writes are atomic under that same lock.
   `--pending` shows the new owner; `--sweep` reads the successor's transcript from the transfer offset. An ack already in the
   SUCCESSOR's transcript before that offset is not counted; transfer BEFORE notifying peers. Without a successor transcript,
   the relay-based ack path applies (`tx: null`). Transfer sends nothing and forwards no replies.
   JSON lists `transferred`, `acked`, `skipped`, `missing` and the successor `sender`; text reports the same outcomes.
   A requested `--id` not transferred exits 1 and appears in `missing` (absent, closed, another sender's, skipped, or settled as
   `acked` during this call). Successful transfers still take effect in a partial result; with no explicit ids, zero transfers exits 0.
   Rerunning changes no adopted records. Keep the old finished fleet row until adoption succeeds; a missing row is refused (exit 2).

3. **First contact**: the first message from your session to a peer carries ` [first contact from <your id>: reply `ack <your id>` through relay.py ...]`.

   The ledger `~/.local/state/relay/links.json` records who you messaged; `--sweep` marks the link acked when a user line in your transcript says `ack <your id>` and names the peer
   (or an `--expect-ack` from it resolved); `fleet.py list` then shows `link: acked` or `link: ONE-WAY` (sent, never answered) under that peer.
4. **Inbound**: a message tagged `[relay from KIND ID (DIR)]` (`KIND ID aka NAME (DIR)` for a named session; a deferred send has `[queued Nm ago] ` right after the tag; on the socket route there is no tag, the same label is the `from-name="relay.py (LABEL)"` attribute of the `<cross-session-message>` envelope; or a Paseo
   agent message) that **asks a question or requests action is answered by `relay.py <ID> "<answer>"`** (ID is the second word: a herdr pane id such as w2F:p45, a session
   id prefix, a Paseo agent id; a job's declared label, `[relay from load-watch]`, has no ID and cannot be replied to: tell the operator instead), never only in your own prose: your prose does not reach it. The sender is read from the sending process (2026-10-25): fleet's `self`
   row, `HERDR_PANE_ID` or the pane an ancestor runs in, `PASEO_AGENT_ID` or the Paseo agent above it, `CLAUDE_CODE_SESSION_ID`, `HERMES_SESSION_ID` (a relay Hermes starts itself is `hermes SID8`), `RELAY_SENDER_NAME`. A Codex tool shell
   has none of these variables (`shell_environment_policy inherit = "core"`), so relay reads the `codex` process above it. **A relay whose sender resolves to none of these
   is refused, never sent (2026-10-25)**: exit 4, nothing sent, queued or recorded (`--json`: `{"sent": false, "error": "no_sender", "reason": ...}`), the message names every
   variable and ancestor source checked; **re-run it with `RELAY_SENDER_NAME=<label> relay.py ...`** (a launchd job or script with no session; a relay Hermes starts itself is named `hermes SID8` and sends) or from inside a
   session. `[relay from unknown]` is never sent, so a header you read always names a sender you can answer. A footer
   `[reply through relay.py to ID: ack X]` means start the answer with `ack X`; an answer that also asks the peer for something is sent with `--needs-reply --expect-ack ID2` (the flags make it an ordinary message, never a terminator). **Never put `--expect-ack`/`--needs-reply` on an ack whose remark asks nothing new (`ack X: done`): an answer to an expectation is never itself flagged unless it asks a new question or requests an action** (otherwise two agents chain acks forever). A message that asks `ack <id>` as first contact: send `relay.py <id> "ack <id>"`.
   An FYI needs no reply. After a relay that is not `delivered`, read its status word; `queued`, `accepted`, `unverified` are not proof.
5. **Prose-only answer nudge (2026-10-25)**: `claude/hooks/relay_prose_nudge.py`, a Claude Code **Stop** hook, enforces item 4 for Claude sessions: **a question or an
   action request only**. When the turn that just ended began with relay's sender label, as `relay.py` writes it (the `[relay from KIND ID ...]` text at the very start, from the pane, inbox and Paseo routes, logged as a user entry or a `queued_command` attachment; on the **socket
   route**, which writes no header, the `from-name="relay.py (LABEL)"` attribute of its `<cross-session-message>` envelope, read as the header. Claude Code logs a socket frame two ways and both are read (real transcripts, 2026-10-26): to a busy receiver a `queued_command` attachment holding the bare envelope (all 124 envelope-bearing peer attachments of 174); to an idle one a user entry with `isMeta: true` and `origin.kind: "peer"` holding a harness prefix (`Another Claude session sent a message:` and a newline, or a while-you-were-working variant), the envelope and a harness suffix after the closing tag (all 108 envelope-bearing peer user entries of 176 (the other 68 are teammate or task entries that parse to nothing)). The body is cut at the first closing tag (relay escapes `<`, so that tag is the wrapper's own) and unescaped. [INFERENCE] no relay frame to an idle session was observed (all 7 relay or acp-dispatch frames were to busy ones); Claude Code's handler sets `isMeta` and the peer origin for every socket frame. A deferred send's `[queued Nm ago] ` follows either and is skipped; a
   Paseo-hosted sender's own label is not read; the label needs a `(DIR)` suffix or a herdr pane-id, hex-prefix, uuid or, for `hermes`, 1-8 character `[A-Za-z0-9_-]` tail ID, so a declared label such as `load watch` names no target) and the text asks for an answer, the hook nudges. **It asks** when it ends with relay's own
   `[reply through relay.py to ID: ack X]` or `[first contact from ID: ...]` footer (relay appends one, last; a quoted footer earlier in the text decides nothing), **or** has a `?` outside a URL (the detector `relay.py` uses) **unless relay enforced footers on
   that sender**. relay refuses a `?` text without the reply footer or `--fyi` only when it found the sender's own fleet row, and only a herdr pane has one: **only a header with a herdr pane id (`w2F:p45`) and a `(DIR)` suffix** shows that, so there a
   footer-less `?` text is a `--fyi` text or a NOTICE and never nudges. Every other header (a Paseo uuid, a session-id prefix, `hermes TAIL`, a pane id with no `(DIR)`; `(DIR)` is written whenever the sender's cwd exists, row or not) says nothing about footers,
   so its `?` counts and a `--fyi` question from such a sender is nudged once (accepted: the `?` is the only signal there).
   And the turn made no Bash call containing `relay.py` and no `SendMessage` to that sender (its header ID or `aka` name), it returns `{"decision": "block", "reason": "You answered a relayed message in prose; the sender does not
   see it. Reply with relay.py <ID> \"<text>\" ... If it needs no answer, end the turn; if it asks for one, start your relay reply with `ack X`."}`: the session takes one more step.
   Never for a statement, "noted, thanks" or "received" (no question, no footer), never for an `ack <ID>` text with or without an answer after the ID as long as it has **no `?` outside a URL** (`ack q1`, `ack q1: 3a24fdc.`, `ack q1 - ...`; `Ack the status?`, `ack q1: is that the SHA you meant?`, `ack, but ...?` and `acknowledge ...` are not acks; on a first-contact footer a bare-space `ack q1 3a24fdc` is an ack too unless the text has a `?`), one starting `FYI`, one starting or ending `no reply needed`, or one ending `no need to reply` or `no response needed` (relay's reply
   footer overrides these; a quoted "no reply needed" inside a question exempts nothing), so acks and acks of acks never provoke messages; never twice for one relayed message
   (a state file per session in `~/.claude/state/relay-prose-nudges/`, and Claude Code's `stop_hook_active`), and silent on any parse error. A `queued_command` prompt given as a list of text blocks is read like a user
   message; a `<task-notification>` entry does not start a new turn. It reads only the last 256 KB of the transcript (a turn that began further back is not nudged), uses no network and never calls relay.py.
   **Known limit (2026-10-26, deferred)**: an `ack ...` text, one starting `no reply needed` or one starting `FYI` that goes on to ask for an action without a `?` (`ack the status please`, `No reply needed on the log, but please merge PR 14 now`, `FYI, please merge PR 14`) is read as an exemption and is
   not nudged, also under a first-contact footer, and an `FYI` text is silent even WITH a `?` (`FYI: load is 11, can you pause your build?`; only relay's reply footer overrides it). It only under-nudges and cannot loop. Slice A merged in #81 (`is_terminator` is on master); the hook sharing relay's `is_terminator` is the follow-up after this PR, not done here; docs/queue.md item 8 lists the 18 request texts that are its acceptance corpus. Accepted: a herdr pane id with no `(DIR)` counts `?`; two envelopes in one prompt (no harness writes it): only the first is read.
   `RELAY_PROSE_NUDGE_OFF=1` disables it. Registered in `agents/claude/settings.json.tmpl` under `Stop`; the live `~/.claude/settings.json` gets it only by the operator's install
   (docs/queue.md, "Verified peer messaging, round 2").


## Direct Herdr control and detached relay workers (2026-10-25)

For direct Herdr control, follow the upstream `herdr` skill's caller-context
boundary. A precondition must gate execution: check its exit status in a
separate tool call, or use conditional shell logic, for example:

```bash
if test "${HERDR_ENV:-}" = 1; then
  herdr agent list
else
  printf '%s\n' 'Direct Herdr control requires a Herdr-managed pane.' >&2
  exit 1
fi
```

A bare `test` followed by another command does not gate that command. Do not
set `HERDR_ENV=1` to make an outside caller pass this check.

Codex's `shell_environment_policy.inherit = "core"` can omit Herdr context
from tool subprocesses even when the TUI itself is inside Herdr. In that
case, recover only this TUI's inherited context from its own live process and
owning shell, verify that both descend from Herdr and agree on the caller
IDs, and pass those verified values explicitly to the helper. Confirm that
`agent get` for that pane names this TUI's exact session ID before controlling
it. A verified live server handoff can reparent the owning shell; retain the
previous caller-context receipt and confirm the same TUI/session mapping with
the new server. Never substitute the UI-focused pane or another process's context.

This is a boundary for an agent's direct control of its current session.
Detached `relay.py` delivery workers intentionally scrub caller identity and
Herdr context; they resolve an explicitly recorded target and verify its
identity and delivery themselves. Do not add a `HERDR_ENV` requirement to
those workers or weaken their target and delivery checks. Use the canonical
relay from outside Herdr when coordinating an explicitly requested peer.

## Codex messages in Herdr (2026-10-25)

`self-slash` also supports Codex's shaded `›` composer. It preserves multiline
drafts, waits for Herdr to report `idle` or `done`, and submits through the
atomic agent surface. Its detached waiter starts a new process session so a
tool executor's process-group cleanup cannot take it down. An ambiguous Codex
submission failure ends the waiter without a resend. A queued lifecycle is
not proof it ran: check `self-slash.log` and the new thread before reporting
automatic continuation.

**Skill versus built-in in a Codex pane (2026-10-25).** Codex invokes a skill as `$name` and keeps `/name` for its
built-ins (`/new`, `/compact`, `/quit`). `self-slash` keeps `/new` and the other built-ins as they are and sends the
follow-up skill as `$baton` (default `--then`), rewriting a legacy `--then "/baton PATH"` once into `$baton PATH`
(exact command name `/baton` at the start only; the rest of the text is untouched). It chooses by the provider herdr
reports for the pane, confirmed again with `herdr agent get` (provider, this pane, idle or done) right before the
submit; a missing or different identity submits nothing (exit 8), a pane herdr reports no agent for gets no baton
follow-up at all (exit 3), and `$baton` is refused (exit 2) for any other client. In a shell, single-quote it:
`--then '$baton PATH'`. A Codex skill prompt goes in with one `herdr agent prompt`, no Enter and no retry, and is
reported sent only when herdr still names the same pane as codex and that session's rollout holds a user message that
is exactly the text, byte for byte (paths with runs of spaces are not folded), stamped after the submit
(`SELF_SLASH_RECEIPT_WAIT`, default 30 s); otherwise exit 8 `NOT confirmed delivered`. Text still in the composer or a
zero exit from herdr is not proof.

Relay submits a Herdr message with one `herdr agent prompt` call, so the entire
message is bracketed paste followed by submission. Do not replace that with raw
`pane send-text` plus a separate Enter: Codex can leave a long message unsent.
A visible message in the composer is not delivery. For Codex, relay verifies the
exact new user message in the rollout belonging to its session id, under
`CODEX_HOME` (default `~/.codex`). If that proof is missing, it reports unverified;
never ask the operator to press Enter as the normal delivery path.

## 7. How it works (nothing for sessions to do)

1. Running sessions (`fleet.py`): herdr `agent list` (any agent kind), herdr
   `pane list` + `pane process-info` for panes herdr did not classify (an
   undetected TUI such as zcode becomes a session with status `unknown`; the rest
   are shells, shown with `--all`), the Claude registry `~/.claude/sessions/*.json`
   (live pids), a `ps` scan for TUIs outside herdr (located by `where.py`), Hermes
   gateway sessions active in the last day (`~/.hermes/state.db`, read-only), and
   `launches.jsonl`. A Claude session is `finished` when its last real prompt was
   `/handoff`, `/quit` or `/exit`. A session with child processes that are not its
   MCP/LSP servers is `busy-background` (`busy:` lists them): helm never audits
   it, `herdr-tidy` never closes it.
   Ended work (`fleet.py ended`): handoff chains, transcripts that ended on a
   question, the `herdr-tidy` close ledger (`~/.local/state/session-finder/closed.jsonl`,
   `closed` items with resume commands) and herdr-sleeper journal entries whose
   pane is gone (`sleeping` items with the manual resume line).
2. Claude keyword index: `~/.local/state/session-index/<sessionId>.json`, extended
   from the byte offset last read. History: one adapter per agent in
   `adapters/*.py` (contract in `adapters/README.md`), FTS5 at
   `~/.local/state/session-index/history.v2.sqlite`; a broken adapter is skipped.
   `adapters/todo.py` is a document adapter: one entry per note under
   `<project>/todo/*.md` for every project in `~/.basic-memory/config.json`,
   split into one FTS row per `##` section, `live()` = `status: open`. A full
   update drops entries of agents whose adapter is gone (crush, 2026-10-08).
   `session-history.py --agents` lists counts; `--check` tests FTS5; `--rebuild`
   starts over.
3. `fleet.parse` also measures each Claude session's **work stretch** (median
   minutes between an operator prompt and the next stop), which `helm` uses to
   order its walk.
4. agy: history adapter only; live detection and `launch.py --agent agy` wait for
   agy to work again (todo note `Add agy to session-finder and helm live detection
   once agy works again`, project `main`).

The indexes and launch directories hold prompt text: private, mode 0700, outside
every repo. Never copy them into a repo or a memory note.
