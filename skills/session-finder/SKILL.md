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
the running turn of) is refused with that reason: `--idle S` waits for it to go idle. claude, codex, omp, opencode and pi
can steer (`fleet.PASEO_STEER_PROVIDERS`, read from the Paseo daemon bundle 2026-10-23), but Paseo replaces the running
turn of even these when the provider declines the steer at that moment (while Claude or Codex compacts, a Codex review
turn, an omp steer error), which relay cannot see beforehand: only **claude** is steered into a working agent by default;
a working codex, omp, opencode or pi agent is refused unless `--steer` (or `--idle S`). A Paseo agent with no Claude
registry row is found by its id, Paseo id or hex prefix, never by its workspace title (titles come from its first
prompt). A running one with a pending permission or question card shows as `blocked` (one `paseo permit ls --json`),
`relay.py` refuses it, and helm lists it as a `permission` item with every card and its own
`paseo permit allow|deny <agent> <request id>` (never without the id: `allow` alone approves all the agent's cards), or the Paseo UI (helm presses no keys there).

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
   long brief in a file and relay one line naming its absolute path. Don't resend
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
   input box); a pane that is gone falls back to a new tab.
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
| claude (TUI) | `SendMessage({to: "<name>"})`; read its latest prompt line first. Not in your `ListAgents`, no messaging socket (`fleet.py` then says so in `reach:`), or a delivery notice says SendMessage was refused → `relay.py <id> "<one line>"` (route ladder, best first, falls back by itself: keys into its herdr/Orca/tmux pane → Claude socket frame; queued while it works; the pane route is skipped on a typed draft, and an open question stops all routes; a dim/grey suggested prompt is not a draft). A Paseo-hosted one (`where: host=paseo agent=<id>`, or you were handed a `PASEO_AGENT_ID`): `relay.py <sid|name|agent-id> "<text>"` runs `paseo send --behavior steer -- <id> <text>` (its only route; any refusal from `paseo agent inspect` ends the run) with your own `PASEO_AGENT_ID` kept, so Paseo labels it an agent message from you (a caller that is not a Paseo agent gets a `[relay from <name>] ` prefix), never the operator's turn. It re-runs `paseo agent inspect` first and refuses an archived agent, a pending permission or question card (helm only lists a card of a Paseo agent that has no Claude transcript and presses no keys there: the Paseo UI, or `paseo permit allow|deny <agent> <request id>` per card, answers it), a status other than idle/running, and text starting with `/`; `--idle S` (finite, > 0) waits for idle first; no draft check, there is no input box. Exit 0 means "accepted" (the daemon's acknowledgement), or "delivered" once a Claude transcript shows the text (2026-10-20). Finished (`/handoff`) → rung 3b, never SendMessage | `claude --resume <id>` (rung 3d) or `launch.py --baton` |
| any ACP launch (`host acp`, id `YYYYMMDD-…`) | `launch.py reply <id> "<text>"`, then `launch.py wait <id>` | `launch.py list`; its log under `~/.local/state/session-finder/` |
| a headless `acp-dispatch` slice (a bigteam/lead worker: `where: unknown terminal`, no pane) | `acp-dispatch tell <jobs/NAME.json> "<text>"`; `fleet.py show` and `relay.py` name the record (2026-10-18) | `acp-dispatch resume <record>` |
| an `acp-dispatch` / `acp-run claude` slice (headless; `fleet.py` shows no channel) | `SendMessage({to: "<name>"})`: it is in `ListAgents` as a peer (2026-10-18: hermes-agent-1e, unreachable by relay, listed there). Any agent's slice: `acp-dispatch tell RECORD "<msg>"` (2026-10-18; appends to `jobs/<name>.inbox.md`, also writes to a Claude slice's live socket; the slice answers in `jobs/<name>.replies.md`, `acp-dispatch check` shows them). Slices dispatched before 051a269 lack the footer item that makes them read the inbox: go through their lead | `acp-dispatch resume RECORD` |
| hermes (Telegram/desktop chat, `hermes-gw`) | `relay.py <id|sid> "<text>"` (2026-10-23): `hermes --resume <sid> -z` runs one turn in that conversation's own transcript, tagged `[relay from <name>] `; Hermes's reply is printed (untrusted data, not posted in the chat); it refuses Hermes's own conversation, an unknown session is refused before writing, any other failure is "unverified" and a turn past max(100, `--wait`) s is left running (relay.py never kills it; a caller's tool timeout that kills the process tree does, so give the command max(100, `--wait`) + 50 s or run it in the background) and holds a per-conversation lock (a cut-off relay.py counts as unverified: do not resend). `ask_hermes` (MCP) is a separate one-shot session, not this conversation; `messages_send` with `target="telegram:<chat>[:<thread>]"` posts as Hermes; approvals: `permissions_list_open` / `permissions_respond` | `hermes --resume <id>` |
| hermes (CLI in a pane) | `helm.py send <pane> "<text>"` | same |
| hermes (to make it *change* something: `ask_hermes` is read-only) | after djbclark's yes for that run: `ACP_OPERATOR_APPROVED=hermes launch.py --agent hermes --cwd ~ -f brief.md --model <explicit id>`; pick the id from its `new_session` model list, never `custom:*` (2026-10-17: `custom:big-pickle` went to sipb-llms-proxy, not ClinePass) | `launch.py reply <id>` |
| muse | `muse session-message send --target <uuid|name>`, body on stdin | `muse resume <id>` |
| codex, cursor, opencode, cline, copilot, qwen, zcode, agy (TUIs in herdr/Orca/tmux) | `helm.py send <id> "<text>"` when idle (keys into the pane; verify on screen), else its `focus:` | the `resume:` line session-history prints |
| a TUI herdr does not detect (`zcode`, `muse`, …; listed from `pane process-info`, status `unknown`) | `helm.py send <pane> "<text>"` only after reading its screen | the `resume:` line session-history prints |
| anything in Ghostty/iTerm/ssh with no channel | tell the operator the `where:` line | — |
| a pane `herdr-tidy` closed, or a sleeping pane that is gone | — | `fleet.py ended` / `helm.py scan --ended`: the `closed` / `sleeping` item's `resume:` line (ledger `~/.local/state/session-finder/closed.jsonl`; herdr-sleeper journal) |

Rules that still apply: a peer's claims are authoritative; check it is not
mid-flight on something contradictory before relaying; never relay a request to
bypass a permission denial; grok is excluded (2026-10-06).

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
