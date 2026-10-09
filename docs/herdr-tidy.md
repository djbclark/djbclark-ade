# herdr-tidy — closing idle herdr panes without losing anything

Skill: [`skills/herdr-tidy/SKILL.md`](../skills/herdr-tidy/SKILL.md) (`tidy.py`,
no model). Command: `/herdr-tidy`. Ledger:
`~/.local/state/session-finder/closed.jsonl` (mode 0600). Built 2026-10-08 by a
Fable 5.1 sub-agent of the helm session, from the brief in
`~/.local/state/bigteam/herdr-safe-close/brief.md`.

## What was asked

djbclark: "With the current system, would it be safe to just close any TUI
sessions with open herdr tabs/panes that are not doing work currently, and
just let helm get to them as it does? I'd like to clean up my herdr." Then:
make a safe recipe that includes the sleeping panes, put it in a djbclark-ade
skill, move `/autorename` here too, close the cracks so this gets safer to do
widely, cover every non-Claude TUI and Hermes, and run a pass.

## Why the answer was "no" (the cracks, and which are closed)

Before this, `fleet.ended_open` surfaced only Claude handoff chains with next
steps and Claude transcripts that ended on a question. Everything else vanished
with its pane.

| Crack | Closed? | How |
|---|---|---|
| 1. Idle Claude with no handoff and no question: resumable, listed nowhere | yes | the recipe sends `/handoff` first (`tidy.py handoff`), and every close is ledgered; the ledger is a `closed` item in `helm.py scan --ended`. Decision: only ledgered closes are listed, not every old transcript, or the list would fill with months of history |
| 2. Looks idle, background work in flight (orchestrators, acp-run, Workflow, background Bash) | yes | `fleet.background_work`: live child processes of the session's pid that are not its MCP/LSP servers → status `busy-background`; helm never audits, tidy never closes. helm/`coord` tabs and panes named by a live bigteam CLAIM are structurally never closed |
| 3. Non-Claude TUIs (codex, cursor-agent, cline, copilot, opencode, crush, zcode, muse, agy, qwen) | yes, with a limit | resume forms read from each `--help` (`fleet.RESUME_FORMS`; SKILL.md 2.2 table); the ledger records the exact command and the screen tail. Limit: no TUI exposes its input box, so a typed draft in an idle TUI is the accepted loss. A TUI herdr does not detect (zcode) is now listed from `pane process-info` but closes only by hand (status `unknown`) |
| 4. Hermes: CLI panes and chats | yes | pane: `hermes --resume <id>` recorded; chats are not panes (`hermes --resume <id> -z` from a script; `ask_hermes`), nothing to close |
| 5. Sleeping stubs: closing one loses auto-wake; the manual line was never surfaced | yes | tidy copies the whole journal entry into the ledger and records the sleeper's own manual line; `fleet._sleeping_items` lists any journal entry whose pane is gone as a `sleeping` item with that line, ledger or not |
| 6. Duplicate panes of ACP launches | yes | class `acp`: closed with `launch.py close <id>` so session, log and tab go together |
| 7. Plain shells, undetected by `fleet.py --all` at all | yes | listed from `pane list`; closable when the shell is the only process, has no children and sits at a bare prompt; the ledger keeps the last 60 screen rows |

What still relies on judgement (the script fails closed and prints the reason):
a Claude pane whose composer line is not on screen (cannot prove the input box
is empty), a draft in any input box (including a staged `/quit`, which orc
leaves for the operator), a TUI with status `unknown`, anything herdr cannot
read.

## The ledger

One JSON object per line, appended by `tidy.py close`; a later line with the
same `id` updates it (`resumed: true` hides it). Fields: `id`
(`closed:<stamp>-<pane>`), `t`, `when`, `pane`, `tab`, `workspace`, `label`,
`tab_label`, `agent`, `cls`, `title`, `cwd`, `sid`, `resume`, `why`, `by`,
`handoff` (chain log for a Claude session), `mb`, `journal` (sleeper entry),
`launch` (ACP id), `screen` (last 60 non-empty rows). Readers:
`fleet.closed_ledger`, `fleet._closed_items`, `tidy.py ledger`. It lives with
`launches.jsonl` because both are session-finder's own records of sessions it
started or ended; the handoff state root stays the handoff skills'.

## Requests for the herdr-sleeper owner (not changed here; the repo is claimed)

1. `herdr-sleeper list` prints a `manual:` line only for `orphaned`/`displaced`
   entries. An `asleep` entry whose `pane_id` is no longer in `herdr pane list`
   should print it too (tidy and fleet work around this by reading the journal).
2. A `herdr-sleeper forget <key>` (or `resumed <key>`) for an entry the operator
   resumed by hand from the manual line, so the journal stops carrying it; today
   nothing removes such a record except a reuse of its pane id.
3. On reconcile, when a pane is gone, log one event (`pane-gone`) with the manual
   line; today the fact is only discovered at wake time ("pane no longer exists;
   entry kept").

## The first pass (2026-10-08 21:19, from the helm session)

`tidy.py scan` classified 24 panes; 16 closed, 6 left with a reason, 2 never.
Ledger ids `closed:20261008-2119*` (`tidy.py ledger`); `helm.py scan --ended`
listed all 16 as `closed` items with their resume lines right after, plus 3
`sleeping` items from the legacy journal (`~/.local/state/herdr-sleeper/`).

| Pane | Tab | Agent | Class | Outcome |
|---|---|---|---|---|
| w22:p2, w22:p3, w22:p7, w23:p3, w23:p9, w23:pA, w24:p1, w24:p3, w24:p4, w2A:p8, w2A:p9, w2A:pA | grok-bridge, saner-opencli, gateway-restart, crash-recovery, lockup, memory-reboot, lichess-handoff, phone-breaking, physiboard-3, zcode-setup, hindsight-alt, agent-teams-setup | claude (asleep) | sleeping | closed; journal entry + `cd … && claude --dangerously-skip-permissions --resume <uuid>` in the ledger; `herdr-sleeper list` still shows all 12 `asleep` (request 1 above) |
| w23:p8, w27:pT, w2A:p5, w2A:p7 | extrabar-shell, home-shell, aiuse-watch, crush-shell | shell | shell | closed; last 60 screen rows in the ledger |
| w22:p6 | cline2-watchdogd | claude | claude-idle | left: an unsent draft appeared in its composer mid-pass (earlier the composer line was not on screen at all) |
| w23:p7 | collie-doctor | claude | claude-idle | left: unsent draft `close the two finished panes now` |
| w25:p1 | cfengine-tracker | claude | claude-idle | left: staged `/quit` (orc's quit-no-Enter convention; /loose was clean) |
| w27:p44 | jobtest | claude | claude | left: a fresh session (composer placeholder `Try "…"` read as a draft at the time; now recognised as empty, and a session with no prompt yet is "nothing to hand off") |
| w2A:p4 | qwen-cloud | cursor-agent | cursor | left: a question on screen (helm's item) |
| w2A:p6 | sleeper-review | shell | shell | left: `claude` typed at the prompt, unsent |
| w27:p43 | 2 | zcode | busy-background, then focused | never (ran `bg just ci`; the operator moved into it) |
| w2E:p1 | helm-relay | claude | self | never |

Not touched: the sleeper-restore-flags claim's SDK session in `~/src/herdr-sleeper`
(not in a pane of its own; its pane alias is the helm pane), the three Hermes
chats (not panes), and `~/src/herdr-sleeper` itself.

## Orca host mode (`/orca-tidy`, 2026-10-08)

Issue djbclark/djbclark-ade#1; feasibility report
`~/.local/state/bigteam/orca-tidy-feasibility/report.md` (Orca 1.4.219). Skill section:
[`SKILL.md` §6](../skills/herdr-tidy/SKILL.md). Command: `/orca-tidy`
(`claude/commands/orca-tidy.md`). Tests: `tests/test_tidy_orca.py`.

### Why an adapter, not a fork

1. Host-neutral already: the verdict model, `claude_composer`, the transcript rules
   (`fleet.parse`), `TUI_WAITING`, `fleet.RESUME_FORMS`, `chain_for`, the ledger and
   the report format. A fork duplicates about 350 lines of that.
2. Orca-specific, about 150 lines behind `--host herdr|orca|auto` (module global
   `HOST`, `detect_host`): inventory (`orca_terminals`), screen read with Orca's
   `draft` (`orca_read`), pending prompt (`orca_agent_wait`), hook state merge
   (`orca_status_merge`), send receipt (`orca_send`), close with a re-list, self via
   `ORCA_PANE_KEY`, processes via `ps eww`. Dispatch points: `screen`, `pane_exists`,
   `pane_now`, `tab_label_of`, `procs_of`, `focus_hint`, `send_prompt`,
   `agent_idle_now`, `close_pane`, `resolve`, `show_pane`.
3. One ledger (`fleet.CLOSED`) with `host` and `pane_key` added, so `/helm-all`
   lists Orca closes next to herdr closes with no reader change.

### Mapping

| herdr-tidy need | Orca source (verified live 2026-10-08) |
|---|---|
| panes, tabs, leaf counts | `orca terminal list --json --include-visual-layouts`: `result.terminals[{handle, tabId, leafId, worktreeId, worktreePath, title, orphaned, connected, preview}]`, `result.visualLayouts[{worktreeId, root:{type:group, activeTabId, tabs:[{tabId, title, activeLeafId, panes}]}}]`; titles carry a leading state glyph (✳ ◐ 💤), stripped |
| agent kind and status | `orca worktree ps --json`: `result.worktrees[{worktreeId, path, isActive, liveTerminalCount, agents:[{paneKey, state, agentType, lastAssistantMessage}]}]`, joined on pane key `tabId:leafId`; rows persist for worktrees with no live terminal (join on a live terminal only); no `agentWait` (#23921) |
| pending prompt | `orca terminal show --terminal H --json` → `result.terminal.agentWait` (null when none) |
| screen, draft | `orca terminal read --terminal H --screen --json` → `result.terminal.{tail[], source: screen|stream|screen-unavailable, draft?}`; `draft` only when Orca's detector finds text after a ❯ › » prompt |
| submit a prompt | `orca terminal send --terminal H --text T --enter --wait-submit N --json` → `result.send.{accepted, prompt.stages:[input_accepted, turn_started]}`, exit 1 when not accepted |
| close | `orca terminal close --terminal H [--tab] --json`; may report ok and leave the terminal (#14719) → re-list |
| processes | `ps eww -ax -o pid=,command=`, the only macOS `ps` spelling that prints other processes' environments; each Orca terminal's shell (`bash --rcfile …`) and its descendants carry `ORCA_PANE_KEY=tabId:leafId` |
| session id, transcript | fleet first; then `~/Library/Application Support/orca/agent-hooks/last-status.json` → `entries{paneKey:{source, providerSession:{id, transcriptPath}, payload:{state}}}`, entries outlive the agent so they attach only when an agent row exists |
| focus the terminal | `orca terminal switch --terminal H` |

### Hazards designed around (all open upstream)

1. stablyai/orca#14719: `close --tab` may report ok and leave the TUI → re-list after
   every close; a surviving handle is exit 1 with the ledger written.
2. stablyai/orca#23865: close skips Claude Code's SessionEnd hooks → idle Claude gets
   `/exit` first, then the close, after the pid is gone.
3. stablyai/orca#23833: closing a Codex terminal can kill a shared `codex app-server`
   → a Codex terminal with that descendant is left.
4. stablyai/orca#14561: `terminal wait --for tui-idle` reports idle while the agent
   runs → never used.
5. stablyai/orca#23921: `worktree ps` lacks `agentWait` → `terminal show` per terminal.

### Fail-closed decisions

1. No focused flag: focused = active leaf of the active tab of the single `isActive`
   worktree; focus unknown (no `worktree ps`, zero or several active worktrees, tab
   missing from the layouts) → every terminal is `never`.
2. No pid carries the pane key → leave.
3. Non-Claude TUI with no ❯ › » prompt line on screen → leave (Orca cannot read a draft).
4. ACP launch in an Orca terminal → leave (`launch.py close` only closes herdr panes).
5. Codex terminal with a `codex app-server` descendant → leave (#23833).
6. Idle Claude is sent `/exit` before the terminal is closed (#23865).
7. `wait --for tui-idle` is never used (#14561).
8. `--tab` only when the layouts and the terminal list agree the tab holds one terminal.
9. An agent `worktree ps` reports with no fleet session matched → leave.
10. No sleeper stubs or popups exist in Orca (it hibernates whole worktrees, which then
    have no live terminal): those classes never fire.

### First live scan (read-only, 2026-10-08)

`tidy.py --host orca scan` over 6 terminals; nothing closed. Summary line:
`6 orca panes · 3 close · 0 handoff-then-close · 1 leave · 2 never`.

| Tab title | cwd | Agent | Class | Verdict |
|---|---|---|---|---|
| CLAUDE_APPLY_DJBCLARK_TOOLING update | (exited Claude at a bash prompt) | shell | shell | close |
| Battery locate sound + low-battery alerts | (exited Claude at a bash prompt) | shell | shell | close |
| Terminal 1 | ~/src/core-simjson | shell | shell | close |
| Fable 5.1 codebase | ~/src/cfengine-core | claude | claude | leave (working) |
| Djbclark-ade issue #1 | this worker | claude | self | never |
| Orca vs herdr with ACP | | claude | focused | never |

### Verified live vs not yet

Verified on 2026-10-08: the `terminal list`, `worktree ps`, `terminal show`,
`terminal read` and `terminal send` receipt schemas (from `~/src/orca` source and live
JSON), the read-only scan above, and the unit tests (`tests/test_tidy_orca.py`,
`tests/test_fleet_tidy.py`, stubs at the fleet/tidy boundary, no live Orca).

Also verified live on 2026-10-08: one real close. The worker created a throwaway
terminal in its own worktree (`orca terminal create --title tidy-selftest`), `scan`
classified it `shell / close`, `close --dry-run` printed the entry, and `close` wrote
ledger `closed:20261008-225245-term_b6a37f9a-e534` and removed the tab; the re-list
showed the handle gone. A security review (adversary agent) of `tidy.py` found nine
issues (tab-close scope, focus failing open, pane-key spoofing, orphaned terminals
counted as closed, Codex guard with unreadable processes, stale prompt glyphs, missing
`agentWait`, silent row collisions, malformed JSON raising); eight are fixed in the
same change, one declined: a missing `draft` key is read as "no draft detected"
because Orca omits the key whenever its detector finds nothing.

Not yet exercised live: a real close of an agent terminal, the `/exit`-then-close flow
(#23865), and a handoff over `terminal send`. The first live pass should run with
`--dry-run` first and close one shell terminal before any agent terminal.

Related: the stale-handle fix in `skills/session-finder/fleet.py` (Orca re-issues
terminal handles after a restart while a session's environment keeps the old one;
fleet now resolves the live handle by `ORCA_PANE_KEY`, and tidy's inventory joins a
session to its terminal by pane key when the channel handle is stale), and
stablyai/orca#22571 (expose worktree/terminal sleep in the CLI: with it a "close"
becomes a resumable sleep; our evidence comment is drafted in `docs/agent-sleep.md` and
`docs/upstream-issues.md` §4, not yet posted).
