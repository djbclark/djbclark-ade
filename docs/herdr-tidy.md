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

## The first pass (2026-10-08, from the helm session)

Recorded in the report returned to the helm session and in the ledger
(`tidy.py ledger`). Summary at the time of writing: 12 sleeping stubs and 4 bare
shells closable; one idle Claude pane could not be handed off because its
composer line was not on screen; two Claude panes held unsent drafts (one a
staged `/quit`); one cursor-agent pane was waiting on a question (helm's); one
zcode pane was `busy-background` (`bg just ci`), later focused; one shell had
typed-but-unsent text. The helm pane and the one live claim were never
candidates.
