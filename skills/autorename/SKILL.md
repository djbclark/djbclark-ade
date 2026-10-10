---
name: autorename
description: Rename the current Claude Code, zcode, or Grok session (what /rename does) to a short title you derive from what you know about the session, then, inside herdr, offer to move its tab out of a generic workspace (a number, "shells", "src", "~") into a fitting existing or new one. Use when the operator types /autorename, says "name this session", "rename this session", "give this session a title", when the autorename_nudge hook asks for a title (Claude Code or zcode UserPromptSubmit, or a Grok Stop), and automatically as the last step of /handoff. Also the owner of the full herdr layout pass; use it when asked to reorganize, rearrange, re-name or clean up all herdr workspaces, tabs and panes ("from-first-principles reorg", "my herdr layout got grotty"), or to create workspaces and move tabs and panes between them; the procedure is `workspace-layout.md` beside this file. `/autorename all` (or `reorg`, `layout`) runs that full pass directly.
---

# autorename — title the session from what you know

Canonical copy: `~/src/djbclark-ade/skills/autorename/` (git: `~/src/djbclark-ade`; moved from
`~/ops/site-djbclark/skills/` on 2026-10-08, which is now a symlink here); every TUI reaches it through
the skill-everywhere hub `~/ops/site-private/skills/autorename`. Its sibling for the other end of a
session's life, closing idle herdr panes safely, is the `herdr-tidy` skill.

`/rename` is a built-in command a skill cannot call, so this skill writes the
same records `/rename` writes, through `autorename.py` next to this file.
It works in Claude Code, zcode, Grok, and cursor-agent, auto-detected
(`CURSOR_CONVERSATION_ID` when `CURSOR_AGENT=1` and cursor-agent is the nearest
agent process above the shell, else `GROK_SESSION_ID` when `GROK_AGENT=1`, else
`CLAUDE_CODE_SESSION_ID`, else zcode's exec-log fds); in any other TUI say so and
stop.

It runs three ways: the operator asks (`/autorename`), `/handoff` Step 8 calls it
with `--auto`, and `autorename_nudge.py` (next to this file) asks for an `--auto`
run once per untitled interactive session. Claude Code registers that script as
a UserPromptSubmit hook in `~/.claude/settings.json` (stdout is plain text).
zcode registers it as UserPromptSubmit in **both** `~/.zcode/cli/setting.json`
and `~/.zcode/cli/config.json`, with `hooks.enabled: true` beside it (both files
have it): the installed build (3.14.4-32) fires hooks only from `setting.json`
(verified live 2026-10-10 — a config.json-only registration never ran), while
current zcode docs name `config.json`, so newer builds are covered too; the
nudge's once-per-session state file absorbs a double fire. zcode stdout is JSON
`additionalContext`. Grok registers it as a
Stop hook in `~/.grok/hooks/autorename.json`, because Grok discards
UserPromptSubmit stdout; the Grok section below has the rest. cursor-agent
needs no registration of its own: it also loads `~/.claude/settings.json` hooks
and runs UserPromptSubmit as `beforeSubmitPrompt`. It ignores stdout that is not
JSON, so the script recognises cursor input (`cursor_version`) and prints
`{"additional_context": …}`. It skips headless runs (the parent cursor-agent was
started with `acp`, `-p` or `--print`) and chats titled with `/rename` (verified
live 2026-10-10). Before that fix, the Claude-format output was silently
dropped in cursor sessions and the once-per-session marker was used up.

## Arguments: `/autorename all` is the full herdr reorganization

The skill receives whatever follows the command. With no argument it titles this
session and places its tab (steps 1 to 3 below). With **`all`** (synonyms `reorg`,
`layout`; optionally followed by one workspace name or id to limit the pass to it)
it does the whole from-first-principles layout pass over herdr instead:
create, rename and renumber workspaces, relabel tabs and panes, and move tabs and
panes between workspaces. Only inside herdr (`HERDR_ENV=1`); elsewhere say so and stop.

1. Read the operator's special-workspace list (`herdr_place.py config`, file
   `~/.config/autorename/workspaces.conf`: names, hints, top-of-herdr order) and follow
   [workspace-layout.md](workspace-layout.md) end to end: principles, inventory
   (read-only), decide the target layout, rename workspaces, relabel panes, move panes,
   sleeping panes through `relocate-pane.sh`, verify and report.
2. **Show the plan before touching anything**: one numbered list of every change
   (`1.` create workspace X, `2.` move tab T from A to X as `<label>-t`, `3.` rename ...).
   Apply it straight away unless a placement is genuinely ambiguous; then ask **one**
   AskUserQuestion covering all the ambiguous ones, recommended option first. The plan
   never closes a pane or tab (herdr-tidy owns closing; the one exception is the
   untouched default shell of a workspace the pass just created) and never touches the
   `coord` panes. Helm tabs are placed in the `helm` workspace like any other.
3. Title this session and label its own tab last, as steps 1 and 2 below (a full pass
   moves this tab too, so do not run step 3's placement question).
4. Report: the final workspace, tab and pane tree as one numbered list, and anything
   left alone with the reason.

Without `all`, never start the full pass unprompted; the nudge hook and `/handoff`
only ever run the single-session path.

## 1. Pick the title

You already know the session: the goal, what shipped, what is still open. Do not
re-read the transcript or run tools to find out. Write one title:

1. 3 to 7 words, sentence case, at most 60 characters.
2. Name the **work**, not the ceremony: "Aiuse muse quota fix", not "Handoff
   2026-10-04" or "Session about stuff".
3. Lead with the project or subsystem when the operator juggles several, then the
   outcome or open question ("Aiuse autorename skill and handoff hook").
4. No quotes, dates, emoji, or trailing punctuation.

If the session covered several unrelated things, name the one that is still live
or took the most effort.

## 2. Apply it

Both scripts need Python 3.10 or newer (`str | None` annotations). In an agent
shell `python3` can resolve to the 3.9 system build (`BASH_ENV` reorders PATH;
seen 2026-10-09), so call one by full path:
`/opt/homebrew/opt/python@3.14/bin/python3.14` in place of `python3` below.

```bash
python3 ~/ops/site-private/skills/autorename/autorename.py "<title>"          # operator asked
python3 ~/ops/site-private/skills/autorename/autorename.py --auto "<title>"   # called from /handoff
```

`--auto` leaves the title alone when the operator renamed the session by hand
(the current title is not the one this script last wrote), so an automatic call
never overwrites a deliberate name. A direct `/autorename` always renames.

The script prints `renamed: …`, `unchanged: …` or `skipped: …`; exit 2 means it
could not run. Report that one line to the operator, nothing more. The title is
persisted (the `/resume` picker shows it), but the running session never re-reads
titles from disk, so its live label and `~/.claude/sessions/<pid>.json` keep the
old name until the operator types `/rename <title>` (upstream:
anthropics/claude-code#91468). Say so in the report when it renamed.

`autorename.py --show` prints the current title.

**zcode.** The same script detects zcode by itself and writes the title where the
TUI's own rename writes it: `title` plus `title_source='custom'` in the session db
(`storage.sessionDbPath` in `~/.zcode/cli/setting.json`, default
`~/.zcode/cli/db/db.sqlite`; `AUTORENAME_ZCODE_DB` overrides). Upstream never lets
a generated title overwrite a custom one (zai-org/ZCode `session-title.ts` guards
both at persist time and in the store write), so one write sticks. The running TUI
keeps its in-memory title until restart, and its herdr terminal title shows
activity status, not the title — the visible pieces are the tab label (below) and
the db row every picker reads. zcode sets no session-id env var: the script reads
it from this shell's own fd paths (zcode's exec log), which fails only if both
stdout and stderr are piped away (`2>&1 |`); `--session-id sess_…` names a
session explicitly. `--show` there prints `title (source)`.

**cursor-agent.** The same script detects it from `CURSOR_CONVERSATION_ID`
(override the base dir with `AUTORENAME_CURSOR_HOME`; default `~/.cursor`). A
chat lives in `~/.cursor/chats/<md5(cwd)>/<id>/`: the title is `name` in
`store.db` (meta row `0`, hex of a JSON object), mirrored to `title` in the
`meta.json` sidecar the resume picker reads. A running cursor-agent keeps that
object in memory and rewrites the whole row on every turn, so a disk write to a
live chat would be reverted. For a live chat (some process holds `store.db`) the
script therefore uses cursor-agent's own `/rename`: inside herdr it queues
`/rename <title>` into this pane through `bin/self-slash`, which waits for the
turn to end and for an empty input line (verified live 2026-10-10). It also
starts a detached waiter that writes both stores once the process exits, unless
the title changed in the meantime (log:
`~/.local/state/autorename/cursor-waiter.log`). Outside herdr only the waiter
runs, so the new title appears after the session ends. A closed chat is
written directly. The report line says which path ran. cursor-agent has no
"manual title" flag, so `--auto` counts a title as the operator's when a
matching `/rename <title>` is in the chat's `prompt_history.json` (built-ins
are recorded there). `--show` prints `title (manual|auto)`. Its herdr tab label
is set as below.

**Grok.** The same script detects this process when `GROK_AGENT=1` and
`GROK_SESSION_ID` is set (override the base dir with `GROK_HOME`; default
`~/.grok`). It writes what `/rename` writes: `generated_title` and
`title_is_manual: true` in
`~/.grok/sessions/<encoded-cwd>/<id>/summary.json`, under an exclusive lock on
the sibling `summary.json.lock`, so a racing auto-title refresh cannot drop
the pin. A non-empty `session_summary` is left as it is (that field is the
auto summary; the picker prefers `generated_title`). An automatic title whose
text already matches is still pinned, so the next refresh cannot replace it.
`--auto` will not replace a title the operator pinned with `/rename` unless
this script wrote that text. `--show` prints `title (manual)` or `title (auto)`.
`/resume`, `grok sessions list`, and `grok --resume <title>` see the new title
at once. The running TUI never receives the in-process notification `/rename`
sends, so the prompt border keeps its old caption until the session is resumed.
The herdr tab label below is the name on the sidebar.

**Grok nudge.** The same `autorename_nudge.py` is a Grok `Stop` hook, in
`~/.grok/hooks/autorename.json` (machine-local, same as the Claude registration;
a running session loads a new file on `/hooks` reload or at the next start).
Grok discards UserPromptSubmit stdout, including `additionalContext`, so the
note goes out on `Stop` as `hookSpecificOutput.additionalContext` and keeps the
turn open for one continuation. The script then prints nothing: on that
continuation (`stopHookActive`), on a subagent stop, and on any `Stop` whose
`reason` is not `end_turn` (session teardown is `channel_closed` or `shutdown`).
Once per session, via `~/.local/state/autorename/<sid>.nudged`. A manual title
is left alone. An automatic title is still nudged, so `--auto` can pin it and
herdr placement can run. The hook runs under `python3.14` (the script needs
3.10+).

**The herdr tab label is a separate thing.** Neither `/rename` nor `autorename.py`
touches the sidebar tab: it keeps its default number ("2") until something labels
it (operator, 2026-10-09, after three renames changed nothing he could see). Inside
herdr, right after step 2 (and whenever the operator has typed `/rename` by hand), run:

```bash
python3 ~/ops/site-private/skills/autorename/herdr_place.py label --force --from-title   # operator asked: always relabel
python3 ~/ops/site-private/skills/autorename/herdr_place.py label --from-title           # --auto / hook: generic labels only
python3 ~/ops/site-private/skills/autorename/herdr_place.py label [--force] <label>-t    # your own label
```

It prints `labelled:`, `unchanged:`, `kept:` (the tab already had a real label) or
`skipped:` (not in herdr). **A direct `/autorename` uses `--force`**: the tab's
old label is usually left over from whatever ran in the tab before (2026-10-09:
"monorepo setup" survived a rename and the operator saw no change), and the
operator asking is the signal that the current name is wrong. Only the `--auto`
path keeps a real label, so a hook never overwrites a name he typed. Step 3 then
decides whether the tab also moves.

## 3. herdr placement (only when `HERDR_ENV=1`)

Orca needs no step here (checked 2026-10-09, read-only): its terminal title is the one Claude sets
itself, and in a titled session `orca terminal list --json` showed exactly `autorename.py --show`
(behind Claude's status glyph). An `orca terminal rename` would pin the title and hide that glyph.
Re-check if the live label ever lags the rename in Orca. zcode needs no step either
(checked 2026-10-10): its pane terminal title is activity status only (`ZC | ⠸ running Bash…`),
so the tab label below carries the name.

Run this after step 2 whatever it printed (renamed, unchanged or skipped). `/handoff` Step 8 skips it: a session being handed off is about to end.

```bash
python3 ~/ops/site-private/skills/autorename/herdr_place.py check          # operator asked
python3 ~/ops/site-private/skills/autorename/herdr_place.py check --auto   # the nudge hook
```

It prints JSON: this tab, its workspace (with `generic` and `reason`), the other
workspaces with their tab labels, and `ask`. If `in_herdr` is false, stop.

**Whenever the tab stays put** (`ask` false, or the operator says "leave it"),
still label it: if `tab.label` is a bare number or otherwise generic, run
`herdr tab rename <tab.tab_id> <label>-t` (label as below). Only `move` sets a
label, so skipping this leaves the tab showing "3" (operator, 2026-10-09).
If `ask` is false, stop after that. (`--auto` gives `ask: false` once the
operator answered this session.)
Skip the question too if you are a dispatched worker no human is watching.

Otherwise ask with **one** AskUserQuestion, recommended option first:

1. Each existing workspace (at most two) whose label or tab labels plainly match
   the session's project or topic: "Move to `<label>`". Never offer another
   generic workspace.
2. A **configured** workspace (`configured_workspaces` in the check output, from
   `~/.config/autorename/workspaces.conf`) whose name or hint matches the topic: offer
   "Move to `<name>`" first (a new workspace if it does not exist yet, created with
   `--new-workspace <name>`; configured names are fixed, never reworded). A lone
   session that matches nothing goes to `one-offs`.
3. "New workspace `<name>`": a plain, short, lowercase name for the project or
   area (`herdr`, `mac`, `hermes`), the kind the existing workspaces use; no `-t`.
4. "Leave it in `<current>`".

The tab label for a move is a short kebab-case form of the title with the `-t`
suffix (`autorename-hook-t`), per the herdr naming convention. Then:

```bash
herdr_place.py move --workspace <workspace_id> --tab-label <label>-t
herdr_place.py move --new-workspace <name> --tab-label <label>-t
herdr_place.py decline                      # "leave it": no re-ask this session
```

`move` carries every pane of the tab (this one into a new tab in the target with
focus, the others split into it) because herdr has no tab-to-workspace move; the
old pane id stays valid as an alias. Report its one line.

To sort **another** session's tab (one the hook missed, say), title it with
`autorename.py --session-id <sid> "<title>"` (a Claude uuid, a cursor-agent
chat id, a Grok session id, or a zcode `sess_…` id) and move it with
`HERDR_PANE_ID=<its pane> herdr_place.py move ... --no-focus`
so the operator's view doesn't jump; `herdr pane list --workspace <id>` maps
`agent_session.value` to pane ids.

To re-arrange and rename **many** workspaces, tabs and panes at once (a full
pass or one workspace; sleeping panes included), follow
[workspace-layout.md](workspace-layout.md); `relocate-pane.sh` beside it cycles
one sleeping pane through wake → move/relabel → sleep.
