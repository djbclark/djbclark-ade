---
name: autorename
description: >-
  Rename the current session (what /rename does) to a short derived title and
  name its own tab (the Paseo tab, or the herdr tab label); nothing else. Use for
  /autorename, "name this session", the autorename_nudge hook, and as the last
  step of /handoff. Also owns the full herdr layout pass (`/autorename all`, herdr
  only): reorganize or clean up herdr workspaces, tabs and panes.
---

# autorename — title the session from what you know

Canonical copy: `~/src/djbclark-ade/skills/autorename/` (git: `~/src/djbclark-ade`; moved
from `~/ops/site-djbclark/skills/autorename` on 2026-10-08); every TUI links to it directly
(skill-everywhere). Its sibling for the other end of a
session's life, closing idle herdr panes safely, is the `herdr-tidy` skill.

`/rename` is a built-in command a skill cannot call, so this skill writes the
same records `/rename` writes, through `autorename.py` next to this file.
It works in Claude Code, zcode, Grok, cursor-agent, OpenCode, Codex, and omp in a
Herdr pane, auto-detected
(`OMPCODE=1` with omp the nearest agent process above the shell, then
`OPENCODE_SESSION_ID` for OpenCode, `CURSOR_CONVERSATION_ID` when
`CURSOR_AGENT=1` and cursor-agent is the nearest agent process above the shell,
else `GROK_SESSION_ID` when `GROK_AGENT=1`, else `CLAUDE_CODE_SESSION_ID`, else
zcode's exec-log fds); in any other TUI say so and stop.

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

The skill receives whatever follows the command. **With no argument it titles this
session and names this agent's own tab, and nothing else** (steps 1 and 2 below; djbclark,
2026-10-30): in Paseo the agent's tab (`<topic>-pt`, which is the agent's name), in herdr
the tab label (`<topic>-t`). It never renames a workspace and never moves a tab. With
**`all`** (synonyms `reorg`, `layout`; optionally followed by one workspace name or id to
limit the pass to it) it does the whole from-first-principles layout pass over herdr
instead: create and rename workspaces, and move tabs and panes between them. Rename a
tab only when its label is a single digit. Keep every other tab label, and keep every
pane label that already has a name. **`all` is herdr only.** First, before any
`herdr_place.py` call: if this session is a Paseo agent (`$PASEO_AGENT_ID` is set, or you know you
were started by Paseo: a Codex tool shell strips that variable), reply exactly `autorename all is not
yet supported in Paseo` and stop (nobody has looked into what Paseo supports for this;
`herdr_place.py config` also refuses when the variable is set, exit 2). Otherwise, outside herdr
(`HERDR_ENV` not `1`), say so and stop.

1. Read the operator's special-workspace list (`herdr_place.py config`, file
   `~/.config/autorename/workspaces.conf`: names, hints, top-of-herdr order) and follow
   [workspace-layout.md](workspace-layout.md) end to end: principles, inventory
   (read-only), decide the target layout, rename workspaces, move panes,
   sleeping panes through `relocate-pane.sh`, verify and report.
   Principle 13 in that file is the monitor rule: `monitor` is first, and
   its tab order is aiuse-watch, then htop, then tokscale. That match wins
   over every other hint.
2. **Do every sure move before any question.** Show the plan first: one
   numbered list of every change (`1.` create workspace X, `2.` move tab T
   from A to X keeping its label, `3.` ...). Apply the hint matches, `monitor`,
   `remote`, and `one-offs` straight away. Then ask the unclear tabs **one
   after another**, only after that work is finished: one question, apply the
   answer, re-count tabs, then the next question. Do not combine them into one
   question, and do not ask while sure moves are still pending.
   The plan never closes a pane or tab (herdr-tidy owns closing; the one
   exception is the untouched default shell of a workspace the pass just
   created, and only after a real tab is already in it) and never touches the
   `coord` panes. Helm tabs are placed in the `helm` workspace like any other.
   A workspace holds at most 5 tabs.
   Failures from 2026-10-29 and the rules that block them are in
   [workspace-layout.md](workspace-layout.md#pitfalls-met-on-2026-10-29). Read
   that section before the first move.
3. Do not retitle this session, and do not relabel its tab, when that tab
   label is not a single digit. Steps 1 and 2 below stay on `/autorename`
   without `all`. A full pass may move this tab (principle 7); step 3 below
   describes the move commands.
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
python3 ~/src/djbclark-ade/skills/autorename/autorename.py "<title>"          # operator asked
python3 ~/src/djbclark-ade/skills/autorename/autorename.py --auto "<title>"   # called from /handoff
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

**OpenCode.** The same script detects OpenCode from `OPENCODE_SESSION_ID`
(`ses_…`) and writes `title` where the TUI's own rename writes it: through the
running server's `session.update` API
(`opencode api session.update --param sessionID=… --data '{"title":"…"}'`), which
updates both `~/.local/share/opencode/opencode.db` (`session_v2`, falling back to
`session`) and the live server's in-memory state, so the running TUI picks it up
at once. It reads the current title from that db (`AUTORENAME_OPENCODE_DB`
overrides the path). OpenCode has no manual/auto title marker, so `--auto`
treats every title as auto and never skips, and `--show` prints the bare title.
The herdr tab label below is set as usual.

**omp** (2026-10-13). omp holds a write lease on its session file and would move
the session to a sibling file if anything else wrote it, so the running omp renames
itself: `omp-bridge.ts` (next to this file) is an omp extension, installed as the
symlink `~/.omp/agent/extensions/autorename-bridge.ts` (omp loads extensions only at
startup, so sessions already running need a restart). It registers each omp process
as `~/.local/state/autorename/omp/<pid>.json` and, once a second, applies a
`<pid>.request.json` from the script with `setSessionName(title, "user")`, writing a
result file back. The script finds the session as the nearest `omp` process above
itself (omp runs bash-tool commands in its own process). It reads the title and its
source from the session file's first line, omp's title slot; `user` is a manual
title, so `--auto` keeps a title the operator set with `/rename`. A session that is
not running cannot be renamed (exit 2: resume it and use `/rename`). Verified
2026-10-13 with `omp -p`: `renamed:` and a `title_change` entry with `source: user`.

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
label the tab. The hook runs under `python3.14` (the script needs
3.10+).

**Paseo** (2026-10-23; tab only since 2026-10-30). A session hosted by a Paseo agent (`$PASEO_AGENT_ID`) also gets
its tab name set. **The workspace is never renamed** (djbclark, 2026-10-30: `/autorename` renames only the
current agent's own tab; from 2026-10-23 to 2026-10-30 it also renamed the workspace to `<slug>-pw`). The one naming
rule across the environment, always lower case with hyphens: `-pw` Paseo workspace (at most 40
characters before the suffix), `-pt` Paseo tab (at most 17 characters **including** `-pt`: Paseo shows about 17 even for
a lone tab), `-t` herdr tab, `-p` herdr pane (under 24), the agent in a herdr pane bare `<topic>`
(`feedback_herdr_tab_pane_naming_convention`). A Paseo agent tab's name **is** the agent's name (`paseo agent update
--name`), so the agent is named `<topic>-pt`; `paseo_tab_name()` in `autorename.py` is the shortener. It drops the words
of the project name and of the workspace's title (except a workspace named `<slug>-pw` from this same title, so a re-run
gives the same tab), abbreviates, and adds `-2`, `-3` ... on a clash with another live agent or terminal of the
workspace. Check suffixes longest first: `x-pt` also ends in `-t`. The sentence title stays the provider session's
title. The workspace id comes from the agent's record under `$PASEO_HOME/agents/`. A direct `/autorename` always
renames the agent. `--auto` is guarded: it keeps an agent name that already ends in `-pt` (a name the operator or an
earlier run set); a name without the suffix is still replaced, because no names store exists yet to explain a rename.
The reply line ends `(paseo tab <name>)` (`(paseo tab kept: <name>)` when guarded); under `--auto` it also carries
`(names store unavailable)`. A Paseo-hosted agent is never in herdr: `herdr_place.py` skips `label` and `check` there,
even if the daemon passed a herdr environment down to it.

**The herdr tab label is a separate thing.** Neither `/rename` nor `autorename.py`
touches the sidebar tab: it keeps its default number ("2") until something labels
it (operator, 2026-10-09, after three renames changed nothing he could see). Inside
herdr, right after step 2 (and whenever the operator has typed `/rename` by hand), run:

```bash
python3 ~/src/djbclark-ade/skills/autorename/herdr_place.py label --force --from-title   # operator asked: always relabel
python3 ~/src/djbclark-ade/skills/autorename/herdr_place.py label --from-title           # --auto / hook: generic labels only
python3 ~/src/djbclark-ade/skills/autorename/herdr_place.py label [--force] <label>-t    # your own label
```

It prints `labelled:`, `unchanged:`, `kept:` (the tab already had a real label) or
`skipped:` (not in herdr). **A direct `/autorename` uses `--force`**: the tab's
old label is usually left over from whatever ran in the tab before (2026-10-09:
"monorepo setup" survived a rename and the operator saw no change), and the
operator asking is the signal that the current name is wrong. Only the `--auto`
path keeps a real label, so a hook never overwrites a name he typed. That is the
whole no-argument path in herdr: the tab is not moved (step 3 is not part of it).

## 3. Moving a herdr tab (only for `all` or an explicit request)

Orca needs no step here (checked 2026-10-09, read-only): its terminal title is the one Claude sets
itself, and in a titled session `orca terminal list --json` showed exactly `autorename.py --show`
(behind Claude's status glyph). An `orca terminal rename` would pin the title and hide that glyph.
Re-check if the live label ever lags the rename in Orca. zcode needs no step either
(checked 2026-10-10): its pane terminal title is activity status only (`ZC | ⠸ running Bash…`),
so the tab label below carries the name.

Not part of `/autorename` without an argument, nor of the nudge hook or `/handoff` (djbclark, 2026-10-30). Use it
when the operator asks to move or sort a tab, and within `/autorename all`.

```bash
python3 ~/src/djbclark-ade/skills/autorename/herdr_place.py check
```

It prints JSON: this tab, its workspace (with `generic` and `reason`), the other
workspaces with their tab labels, and `ask`. If `in_herdr` is false, stop.

**`check` labels the tab itself** (2026-10-11): a generic `tab.label` is renamed from
the session title before the JSON prints, and `tab_labelled` reports `'3' -> 'x-t'`
(null when nothing was replaceable). **Replaceable** = generic, or a `-t` label autorename
wrote earlier on a single-pane tab (2026-10-11: a stale `helm-t` from the pane's previous
session stayed for the whole new session; `replaceable()` in `herdr_place.py`, test
`tests/test_autorename_tab_label.py`). Leaving the hook to remember the separate `label` call
left the tab at "3" (operator, 2026-10-09 and again 2026-10-11). **Whenever the tab stays
put** (`ask` false, or the operator says "leave it"), confirm `tab.label` is no longer a
bare number; if it still is (or `tab_labelled` is an error), run `herdr_place.py label
--from-title`. An explicit move request first labels with `label --force --from-title`
(as step 2 does).
If `ask` is false, stop after that. Skip the question too if you are a dispatched worker
no human is watching.

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
```

"Leave it" needs no command: the tab stays where it is.

`move` carries every pane of the tab (this one into a new tab in the target with
focus, the others split into it) because herdr has no tab-to-workspace move; the
old pane id stays valid as an alias. Report its one line.

To sort **another** session's tab (one the hook missed, say), title it with
`autorename.py --session-id <sid> "<title>"` (a Claude uuid, a cursor-agent
chat id, a Grok session id, or a zcode `sess_…` id) and move it with
`HERDR_PANE_ID=<its pane> herdr_place.py move ... --no-focus`
so the operator's view doesn't jump; `herdr pane list --workspace <id>` maps
`agent_session.value` to pane ids. A Paseo-hosted agent cannot do this: `move` refuses there
(exit 1), as `/autorename all` does; it is not yet supported in Paseo.

To re-arrange **many** workspaces, tabs and panes at once (a full pass or one
workspace; sleeping panes included), follow
[workspace-layout.md](workspace-layout.md). A full pass renames a tab only
when its label is a single digit. `relocate-pane.sh` beside it cycles one
sleeping pane through wake, move, and sleep.
