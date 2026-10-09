---
name: herdr-tidy
description: >-
  Close idle herdr panes and tabs safely, every TUI and Hermes included: a
  no-model classifier (tidy.py) says per pane what it is, whether it may be
  closed and why not, performs the precondition (/handoff for an idle Claude
  session), writes a close ledger with the exact resume command, and closes the
  tab; closed panes resurface through /helm-all with their resume command. Use
  when the operator types /herdr-tidy, says "clean up my herdr", "close the idle
  panes", "which panes can I close", "tidy the tabs", or asks whether a pane is
  safe to close. Fails closed on anything it cannot verify.
---

# herdr-tidy — close idle panes without losing anything helm cannot find again

Canonical copy: `~/src/djbclark-ade/skills/herdr-tidy/` (git: `~/src/djbclark-ade`); every TUI
reaches it through the skill-everywhere hub `~/ops/site-private/skills/herdr-tidy`. Design
record and the first pass: `~/src/djbclark-ade/docs/herdr-tidy.md`. Its sibling for the start of
a session's life (titles, workspace placement) is `autorename`.

**Safe** means: after the close, everything the pane held can be found again from `/helm-all`
(`helm.py scan --ended`) or `/session-finder-all`, and nothing in flight is killed. The script
enforces it; the agent only decides the few things the script hands back as "decision needed".

```bash
T="python3 -I $HOME/ops/site-private/skills/herdr-tidy/tidy.py"
$T scan                        # every pane: class, verdict, reason, the resume command the ledger would hold
$T handoff <pane>              # idle Claude pane: send /handoff, wait until the transcript says it finished
$T close <pane> [--why "…"]    # re-check every precondition, write the ledger, close tab (or pane)
$T close <pane> --dry-run      # the ledger entry it would write, nothing closed
$T ledger [--days N]           # what was closed, when, why, and how to resume it
$T resumed <ledger-id>         # the operator resumed it: helm stops listing it
```

Verdicts: **never** (structural: this session, the helm or a `coord` pane, a live claim, a
popup, the focused pane), **leave** (not now; the reason says what would change it),
**handoff-then-close** (idle Claude, no handoff yet), **close** (every precondition holds).
`close` refuses anything but a `close` verdict, re-reads the screen and the pane right before
acting, and prints the ledger id it wrote.

## 1. Never closed, whatever the state

1. The pane this session runs in (`HERDR_PANE_ID`) and any pane whose tab, label or title starts
   with `helm` or `coord` (the fleet relay and bigteam orchestrators; their background work is
   invisible from outside).
2. A pane named by a live bigteam claim: `~/.local/state/bigteam/*/CLAIM` without a `DONE` line
   and under six hours old, whose `session:` line mentions the pane id, tab id, session id or
   session name (`fleet.claims()`). Its slice is still running somewhere.
3. The focused pane (the operator is in it) and popup/tool panes (`collie`, `drovr`,
   `herdr-jump`, `herdr-navigator` as the foreground process): they belong to the tool.
4. Anything `working`, `blocked` (waiting on a prompt: that is helm's item, answer it first) or
   **`busy-background`**: idle to herdr and the registry, but a child process that is not one of
   the session's servers is still running (a backgrounded Bash, an `acp-run`, a build, `bg just
   ci`). The test is the process tree under the session's pid (`fleet.background_work`): MCP and
   language servers, `token-savior`, `caffeinate` are servers; everything else is work. Claude
   Code's background tasks under `/private/tmp/claude-<uid>/<project>/<session>/tasks/*.output`
   are history once their process is gone, so the live descendant is what counts. For other
   TUIs the same tree test applies. Closing the pane would kill the children.
5. Anything whose state cannot be read: `pane process-info` unreadable, a Claude composer line
   not on screen, a TUI herdr cannot tell idle from working (status `unknown`). Fail closed and
   put it on the decision list with the reason the script printed.

## 2. Per class: what is checked, the precondition, how it is closed

Every close appends one line to the **ledger**, `~/.local/state/session-finder/closed.jsonl`
(mode 0600; `fleet.CLOSED`): `id`, `t`/`when`, `pane`, `tab`, `workspace`, `label`, `tab_label`,
`agent`, `cls`, `title`, `cwd`, `sid`, `resume` (the exact command), `why`, `by` (session and pane
that closed it), `handoff` (chain log path for a Claude session), `mb` (transcript size),
`journal` (the full herdr-sleeper entry for a sleeping stub), `launch` (ACP launch id), and
`screen` (the last 60 non-empty screen rows, so a shell's final output is kept too). A later line
with the same `id` and `resumed: true` hides it. `fleet.ended_open` turns every entry into a
`closed` item for `helm.py scan --ended`; sleeping-journal entries whose pane is gone become
`sleeping` items (section 4).

Close command: `herdr tab close <tab>` when the pane is the tab's only pane (tabs do not pile up
empty), else `herdr pane close <pane>`; an ACP launch closes with `launch.py close <id>` so the
session, its log and the tab go together. The script picks; you do not type these by hand.

### 2.1 Claude Code in a herdr pane (`agent: claude`)

Checked: herdr status (`agent get`), the registry (`~/.claude/sessions/<pid>.json`), the
transcript tail (`fleet.parse`: finished with `/handoff`/`/quit`, last reply a question), the
process tree (section 1.4), and the visible screen for the composer line `❯`.

1. Composer shows a draft (`❯ text`) → **leave**: "unsent draft". Includes a staged `/quit` that
   orc leaves for the operator's review (memory rule "quit-no-Enter"): his to submit.
2. Composer not visible → **leave**: focus the tab so it redraws, rerun.
3. Finished (`/handoff` or `/quit` was the last real prompt) → **close**. Ledger: resume
   `cd <cwd> && claude [replayed flags] --resume <sid>` plus the newest chain log whose
   workspaces include the repo (`handoff`). `/helm-all` already lists the chain's next steps;
   the `closed` item is hidden while that chain item exists.
4. Last reply ends on an unanswered question → **close** (`claude-question`): helm's
   `ended-question` collector finds the transcript; the ledger adds the pane and resume.
5. Idle, no handoff, no question → **handoff-then-close**: `$T handoff <pane>` submits `/handoff`
   through `herdr agent prompt` only after the composer is verified empty, then waits (default
   900 s) until the transcript's last prompt is `/handoff` and herdr shows idle, and reports
   whether the chain log under `~/.local/state/handoffs/chains/` was updated since the send (exit
   1 if not: read the pane before closing). Then `$T close`. One model turn per session; a cold
   session (idle > 55 min) re-reads its context at full price, which the operator accepted for
   idle Claude panes (2026-10-08). Per pass, at most ~15 handoffs; list the rest.
6. Claude over ACP (`launch.py`): `host acp`; idle or blocked → **close** via `launch.py close
   <id>` (it sends `/exit`, records `closed`, closes the tab). Working → leave. Resume: `launch.py
   reply <id> "<text>"` reopens it with `session/load`.

### 2.2 Non-Claude TUIs (codex, cursor-agent, cline, copilot, opencode, crush, zcode, muse, agy, qwen, grok)

Checked: herdr `agent get` (status, `agent_session.value`), `pane process-info` (the TUI's argv,
for a `--resume`/`-s`/`--session`/`--conversation`/`--id` value when herdr reports no session), the
process tree, and the last 16 screen rows for a prompt (`[y/N]`, `Question 1 of 1`, "Enter to
select"…). No TUI exposes its input box, so a typed draft cannot be ruled out: the ledger keeps the
screen tail, and that is the accepted loss for an *idle* TUI (operator, 2026-10-08).

Resume forms, each read from `<tui> --help` on this machine on 2026-10-08 (`fleet.RESUME_FORMS`;
herdr-sleeper's KINDS table agrees); a kind not in the table gets **leave**, never a guess:

| TUI | idle → close with resume | notes |
|---|---|---|
| codex | `codex resume <id>` | `codex resume --last`; `codex resume --all` shows other cwds; `codex agents` lists sessions |
| cursor-agent | `cursor-agent --resume <chatId>` | `--continue` = latest; `cursor-agent ls` picks |
| cline | `cline --id <session-id>` | `cline history` lists; the CLI's `--id` is the only resume form |
| copilot | `copilot --resume=<id>` (name or 7+ hex prefix also) | `--continue` = latest; `--session-id <id>` also attaches |
| opencode | `opencode -s <id>` | `-c` = latest; `opencode session list` |
| crush | `crush --session <id>` (`-s`) | `--continue`; `crush session list --json` |
| zcode | `cd <cwd> && zcode --resume <sess_…>` | `-c` = latest for cwd; the TUI's `/resume` |
| muse | `muse resume <uuid-or-name>` | `muse resume --last`; sessions are per workspace |
| agy | `agy --conversation <id>` | `-c` = latest; agy is history-only in fleet until it works (todo note) |
| qwen | `qwen --resume <id>` | per herdr-sleeper's verified table |
| hermes (CLI pane) | `hermes --resume <session-id>` | see 2.3 |
| grok | none recorded | the grok vendor is excluded (2026-10-06): a grok pane is **leave** |

Precondition: herdr `idle`/`done`, no prompt on screen, no busy children, a session id. If the TUI
is idle and the operator wants a handoff paragraph in the ledger, `helm.py send <pane> "<ask for a
one-paragraph handoff>"` first and copy its reply into `--why`; it is a turn on that TUI's pool,
so only when cheap. Status `unknown` (a TUI herdr does not detect, listed by `fleet.py` from
`process-info`, e.g. zcode) → **leave**: decide by hand from the screen.

### 2.3 Hermes

1. **Hermes CLI in a pane** (`agent: hermes`): resume `hermes --resume <session-id>` (`-c
   [NAME]` by name; `hermes sessions list`); the id comes from herdr's `agent_session`, the argv,
   or `~/.hermes/state.db` (`sessions` where `source='cli'`, newest with that `cwd`). No id →
   leave. The screen prompt test applies.
2. **Hermes chats** (Telegram, desktop, Discord; `host hermes-gw`) are not panes: nothing to
   close. Their session id is the chat's `hermes --resume <id>`; a turn from a script is
   `hermes --resume <id> -z "<prompt>" </dev/null` (ACP `session/load` cannot reach them:
   memory `reference_hermes_acp_cannot_load_gateway_sessions`).

### 2.4 Sleeping panes (herdr-sleeper stubs, `agent: sleeper`, label `💤 …`)

Checked: the journal entry for the pane id in `~/.local/state/herdr/plugins/djbclark.herdr-sleeper/sleeping.json`
(the plugin's; the legacy `~/.local/state/herdr-sleeper/sleeping.json` second; read-only), its
`phase` (`asleep` only; `waking`/`exit-requested` → leave), `kind`, `uuid`, `cwd`, `argv`; the
transcript on disk for a claude uuid; the stub being the pane's only process; the stub prompt
("press Enter to resume") on screen.

Precondition: all of the above, and a resume recipe for the kind (claude:
`cd <cwd> && claude <replayable argv> --resume <uuid>`, the same line herdr-sleeper's
`manual_command` prints). **The whole journal entry is copied into the ledger** (`journal`).
Then `herdr tab close`. What the sleeper does afterwards: the record is never deleted because
its pane vanished (its own rule 3); `herdr-sleeper list` keeps showing it `asleep` and a wake
attempt says "pane no longer exists; entry kept. Manual: …". `fleet.ended_open` lists such
entries as `sleeping` items with the manual line, so `/helm-all` offers the resume even without
the ledger. Auto-wake on focus is gone with the pane: that is the trade.

### 2.5 Plain shells (no agent)

Checked: `pane process-info` shows only the shell (`-bash`, `zsh`, …), the shell has no child
processes, the last screen row is a bare prompt (`$`, `%`, `#`, `>` with nothing after it).
Typed-but-unsent text (`…$ claude`) → leave. A running foreground job → leave. Otherwise
**close**; the ledger's `screen` keeps the last 60 rows (a TUI's farewell output, a `claude
--resume "<title>"` hint). Resume: none (a shell); the ledger entry is still listed by
`/helm-all` for one look, then `$T resumed <id>` or `helm.py skip`.

### 2.6 Popups and tool panes

collie, drovr, herdr-jump, herdr-navigator: **never**. They are closed by their tool.

## 3. A pass

1. Inventory: `$T scan` (it runs `fleet.py` with shells, reads the sleeper journal and the
   claims). `cswap list` first: each `handoff-then-close` is one Claude turn.
2. Walk the `handoff-then-close` panes: `$T handoff <pane>` one at a time (background it with
   `run_in_background`, wait on the notification; never poll). Before each send and again
   before each close, the script re-reads the screen: an operator typing in the pane meanwhile
   turns it into a `leave`. Do not send anything to a `working` session, and never type into a
   pane helm is mid-relay with (helm only sends keys to blocked/idle panes; the composer check
   catches a race, a second scan catches the rest).
3. Close every `close` verdict: `$T close <pane>`. Read its line: `closed <pane> (<cls>, tab
   <label>) → ledger <id>; resume: …`. An exit 1 means the ledger was written but the pane
   remained; say so.
4. Report, numbered: every pane with id, tab, agent, class, action taken or the one-line
   decision the operator has to make (verbatim `reason`), the ledger ids, and `$T ledger`'s
   tail. Then `~/.local/bin/hermes-ping "<repo>: herdr-tidy pass done — N closed, M decisions"`.
5. Budget: more than ~15 handoffs in a pass → do 15, list the rest.

## 4. Finding closed things again

1. `helm.py scan --ended` (helm section 7): `closed` items (from the ledger; hidden once the
   session is live again, marked resumed, or its handoff chain is listed for that repo) and
   `sleeping` items (journal entries whose pane is gone), each with `resume:`; both rank below
   handoffs and unanswered questions. `helm.py skip <id>` hides one until something changes.
2. `fleet.py ended`, `$T ledger`, `/session-finder-all` (section 1.6 of session-finder: the
   ledger is one of its sources).
3. Resuming: run the `resume:` line in a free pane, or host it visibly with `herdr agent start
   <name> --kind <kind> --pane <free pane> -- <resume tokens>`; `fleet.py conflicts --sid <sid>`
   first (never two instances of one transcript). Then `$T resumed <ledger-id>`.

## 5. What this is not

1. Not helm: helm relays and never closes; tidy closes and never relays. The audit → `/loose`
   → `/handoff` flow stays helm's.
2. Not the sleeper: tidy never edits the journal (read-only), never wakes, never sleeps. A
   request to the herdr-sleeper owner: a `list` line for an asleep entry whose pane is gone, and a
   `herdr-sleeper forget <key>` for entries the operator resumed by hand (docs/herdr-tidy.md).
3. Not a cron: run it when the operator asks or at the end of a /helm walk.
