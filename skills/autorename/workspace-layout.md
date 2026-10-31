# Workspace, tab and pane layout: the from-first-principles re-arrangement

Operator request, 2026-10-08: "a one-time from-first-principles re-arrangement
and re-name of all herdr workspaces, tabs, and panes". This file is the
procedure so it can be repeated (a full pass, or one workspace) without
rediscovering the gotchas. It owns which workspace and tab a pane lives in,
what everything is called, and (last section) the geometry inside a tab.
Moved here from the retired `herdr-orchestration` skill on 2026-10-09.

## Principles

1. **Workspace = project or area, named after the operator's `~/s` topic
   tree** (`~/s/ai/hermes` → `hermes`, `~/s/android` → `android`,
   `~/s/cm` → `cm`, `~/s/ai/litellm` → `litellm`). A pane goes in the
   workspace of the thing it is *about*, not the directory it happens to be
   in (a Mac lockup investigation running in `~` belongs in `mac`). The
   operator's special workspaces (`aiuse+ade` for the agent toolkit, `helm`
   for the orchestrator/relay sessions that watch everything else, `one-offs`,
   ...) come from the config file, see
   [Configured workspaces](#configured-workspaces-and-their-order). A project
   that is not configured gets its own workspace only when it has two or more
   tabs or a tab with several panes (subagents); a lone single-pane tab goes
   in the configured catch-all (`one-offs`) instead, except where the
   [Postscript](#postscript-tabs-that-match-no-configured-hint) says `remote`
   or `agents`, or where principle 13 says `monitor`.
2. **Tab = one unit of work, labelled `<topic>-t`; its pane `<topic>-p`;
   the agent in it bare `<topic>`** (the convention in
   `memory/feedback_herdr_tab_pane_naming_convention.md`). On the
   single-session `/autorename` path, `<topic>` is the session's subject,
   taken from the session itself (first user message, handoff, sleeper
   journal entry), not from a stale label. A full pass (`/autorename all`)
   does not follow that. It places by the current tab label (principle 12),
   keeps every tab label that is not a single digit, and keeps every pane
   label that already has a name. A single-digit tab is named from its
   screen, then placed by that new name.
3. **A plain shell is labelled by its directory**: `<dir>-shell-t` /
   `<dir>-shell-p` (`home-shell-t`, `extrabar-shell-t`). It lives in the
   workspace of the project the directory belongs to; a leftover `shells`
   workspace holds only shells with no project.
4. **Labels stay under 24 characters**; the sidebar truncates longer ones.
   `<topic>` is therefore at most ~21 characters: `clinepass-pr44379`, not
   `clinepass-pull-request-44379`.
5. **Sleeping panes keep the `💤 ` prefix** on the pane label (the
   herdr-sleeper plugin's identity mark for legacy records). The tab label
   has no prefix.
6. **This procedure closes nothing.** Closing idle panes was `herdr-tidy`'s (retired from djbclark-ade 2026-10-31)
   job (it checks preconditions and writes a resume ledger). Empty tabs are
   moved out of, not deleted; `pane move --new-tab` closes the *source* tab for you
   (and a workspace closes itself once its last tab is gone). The one closure
   the pass adds: the default shell tab that `workspace create` makes in a
   workspace the pass itself just created, and only after at least one real
   tab is already in it. Close it when a second `pane read` shows it
   untouched: the shell startup warning plus a prompt that ends in `$`, `%`,
   or `#`, even when the cwd is a project directory. An empty `pane read`
   means the read missed; read it again before keeping the tab. A shell with
   any history stays. Rename its tab only when the label is a single digit.
7. **Do not move your own pane** during ordinary placement. Moving it gives
   it a new pane id mid-session. The one exception is putting a new configured
   workspace above the one you are in. Herdr's order is creation order, so
   the later workspaces, including yours, have to be recreated. Move your
   pane once, using an id read immediately before that move, and confirm the
   old id still resolves to the new pane. Do not move it again in the same
   pass. Say so in the report.
8. **There is no reorder command; order is creation order.** Rename in place
   when the order is already right; otherwise follow the ordering method below.
9. **Helm tabs are placed, not left alone** (operator, 2026-10-09): they go to
   the `helm` workspace like any other topic, moved with `--no-focus`; the agent
   survives the move. Only the `coord` panes (bigteam's) are never touched.
10. **Paseo** (2026-10-24): one top-level agent per Paseo workspace (`<topic>-pw`). Its tab and each worker's tab are
    `<name>-pt`, at most 17 characters with the suffix (shortener: `autorename.py paseo_tab_name`). Workers and adversary
    rounds are sub-agent tabs in the lead's workspace, not new workspaces. Closing a top-level agent's tab archives the
    agent; only `self-slash --finish` closes one.
11. **At most 5 tabs in a workspace** (operator, 2026-10-29). The next tab of that
    same kind goes to `<name>-2`, then `<name>-3`. Count tabs after the moves, not before.
12. **The tab label is the placement key** (operator, 2026-10-29). Match it against
    configured names and hints before the session title, cwd, or screen. A hint
    word has to be its own token in the tab label (`paseo-herdr-generic-t`
    matches herdr; `paseo-pane-t` does not). Rename a tab only when its label
    is a single digit. Keep every other tab label. When the session title,
    cwd, or screen disagrees with the tab label, that is a question, asked
    after every sure move, not a move.
13. **`monitor` is first and wins** (operator, 2026-10-29). It is the first
    name in the config file. A tab goes there when its tab label or pane label
    contains the token `htop`, `tokscale`, or `aiuse-watch`, or when its
    foreground command is `htop`, `tokscale`, or the `aiuse watch` subcommand.
    That match beats every other hint, including `aiuse+ade`. Inside the
    workspace the tab order is aiuse-watch, then htop, then tokscale. Herdr
    cannot reorder, so create `monitor` and move the matching tabs in that
    order. Two tabs in the same group keep their relative order. Drop a
    competing hint on another workspace (`aiuse watch` on `aiuse+ade`) so the
    next pass does not pull the same tab back.

## Configured workspaces and their order

`~/.config/autorename/workspaces.conf` (override with `AUTORENAME_WORKSPACES`; read
it with `herdr_place.py config`; the real file is `~/ops/site-djbclark/config/autorename-workspaces.conf`, symlinked there) lists the operator's special workspaces, one per
line as `name # hint`. `#` starts a comment, whitespace around the name and the hint
is ignored, and the hint says what belongs there (use it to decide where a tab
goes; it is never part of the name). Names may contain `+` and `-`.

1. A configured workspace exists as soon as one tab belongs in it, even a lone
   tab, and is not created while it would be empty.
2. Configured workspaces sit at the top of herdr in file order; the others follow.
3. A tab matching no hint stays in (or goes to) a non-configured workspace named
   for its topic; a lone single-pane tab in such a workspace goes to the
   configured catch-all (`one-offs`), which is just the last entry of the file.
4. **Ordering method.** herdr cannot reorder, so order by creation: walk the
   target list top to bottom; keep every workspace that is already in the right
   relative place (rename it in place, which is how your own pane's workspace
   gets its configured name); for each one that is not, rename the old one out of
   the way (`<name>-old`), create the new one, move its tabs in with `pane move
   --new-tab`, and let the old one close when it empties. Create the missing
   workspaces in file order so they land in file order. Panes get new ids on
   move. Read the id you are about to move immediately before that move
   (section 5); an id from the inventory is stale once any earlier move has
   run. Use the id from `move_result` for the renames that follow.
   **A kept non-configured workspace is recreated too** whenever any configured
   one is created or recreated: it is older than the new ones, so it jumps
   above them once the `-old` copies close (2026-10-12: `Plektra` landed second,
   above `helm`). Recreate it last, after the configured ones.

## Procedure

### 1. Inventory (read-only, from your own pane)

```bash
test "${HERDR_ENV:-}" = 1 || exit 1
herdr workspace list > ws.json
for w in $(python3 -c 'import json;print(" ".join(x["workspace_id"] for x in json.load(open("ws.json"))["result"]["workspaces"]))'); do
  herdr tab list --workspace $w > tabs-$w.json
done
herdr pane list > panes.json
herdr agent list > agents.json
~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper list > sleeping.txt
```

Build one table: pane id, tab id, workspace, current labels, agent kind and
name, cwd (`herdr pane process-info --pane <pane>`), and for each pane *what it is
about*. Sources for "about", in order: the sleeper journal entry title, the
live agent's name, the session's first user message
(`~/.claude/projects/<slug>/<uuid>.jsonl` for Claude; the sleeper record
holds the session id), the pane's last screen lines (`herdr pane read <pane>
--source recent-unwrapped --lines 40`, plain text, not JSON), and finally
the cwd. Place by the tab label (principle 12). Use these other sources
only when that label matches no configured hint.

### 2. Decide the target layout before touching anything

Read `herdr_place.py config` first and apply the section above.

Write the whole target table (pane → workspace, tab label, pane label, agent
name) to a scratch file and check it against the principles: every
`<topic>` unique within its workspace, nothing over 24 characters, no
generic workspace names (`herdr_place.py check` rejects `shells`, `work`,
`scratch`, numbers, and the other names in `GENERIC`). `agents` and `remote`
are real destinations, not generic names. Leave your own pane where it is,
except principle 7.

### 3. Rename workspaces

```bash
herdr workspace rename w24 android
```

Rename, never recreate: a new workspace would change every pane id in it.

### 4. Relabel panes that stay in place

A full pass does not run these renames on a tab whose label is not a single
digit, and does not rename a pane that already has a label. Fill a blank pane
label from its tab (`-t` becomes `-p`). The commands below are for a
single-digit tab, a blank pane label, or the single-session `/autorename` path.

For a live or empty pane, labels are three separate things:

```bash
herdr tab rename  w23:t4 swap-fix-t
herdr pane rename w23:p4 swap-fix-p
herdr agent rename w23:p4 swap-fix      # only if an agent is live in it
```

### 5. Move panes to another workspace

```bash
herdr pane move w27:p2Z --new-tab --workspace w23 --label one-offs-shell-t --no-focus
```

The result's `.result.move_result.pane.pane_id` is the pane's **new id**
(`terminal_id` is unchanged). The old id often keeps working as an alias
(2026-10-29: `pane get` on the id from before the move returned the new pane).
Do not reuse an id saved before other moves. An alias can point at a different
pane, or at nothing, and a pane you skipped is destroyed when its workspace
empties. Immediately before each move, read the pane id again and record the
foreground pid (`herdr pane process-info --pane ID`). After the move, confirm
that pid is on the new pane. At the end, every recorded pid must still be
alive in some pane. A missing pid is a lost pane: report it and do not start
a replacement. Pass `--label` the tab's current label. `--no-focus` on every
move of someone else's pane. Use the new id for a following `pane rename` or
`agent rename`. The source tab is closed by the move. A live agent survives
the move; its name is kept.

### 6. Sleeping panes: wake → move/relabel → sleep again

The herdr-sleeper journal (`~/.local/state/herdr/plugins/
djbclark.herdr-sleeper/sleeping.json`) is keyed by pane id and, for legacy
records (slept before v0.1.1), has no `terminal_id` and relies on the
`💤 ` label prefix. Moving such a pane orphans its record; relabelling it in
place is undone on wake because `restore_label` puts `entry["label"]` back.
So a sleeping pane is cycled, never edited while asleep:

```bash
S=~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper
$S wake w27:p8                                   # pane id or journal name
# poll `herdr agent get <pane>` until agent_status is idle or done (≤60 s)
new=$(herdr pane move w27:p8 --new-tab --workspace w23 --label memory-reboot-t --no-focus \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["move_result"]["pane"]["pane_id"])')
herdr pane rename  "$new" memory-reboot-p
herdr agent rename "$new" memory-reboot
sleep 2
$S sleep-pane "$new"                             # records the new label + terminal_id
```

[relocate-pane.sh](relocate-pane.sh) does exactly this cycle for one pane
(`relocate-pane.sh <pane> <workspace|-> <tab-label> <topic>`; `-` relabels
in place). Run the batch in the background and log to a file; each cycle
takes 20–40 s because wake resumes the Claude session. After the batch,
`herdr-sleeper list` must show every record `asleep` with the new title and
`sleeping.json` must show a `terminal_id` on each (that is what makes the
record survive the next move).

Orphan records (`orphan:<id>`, pane gone) cannot be cycled: leave them, and
report the manual resume command `herdr-sleeper list` prints for them.

### 7. Verify and report

Re-run the inventory and diff it against the target table. Report, as
numbered lists: the final layout per workspace, panes deliberately left
(your own), and loose ends (orphan sleeper records, panes with unsubmitted
typed text that must not receive keys, agents that were `blocked`).

## Pitfalls met on 2026-10-08

1. `herdr pane read` prints plain text; everything else prints JSON.
2. Labels were **rotated** relative to panes in two workspaces (a tab called
   `grok-chief-of-staff-t` held the Mac lockup session). That pass identified
   panes by content. A later full pass does not. Principle 12 keeps a
   non-digit tab label and places by it. Content that disagrees with the
   label is a question, asked after the sure moves.
3. `herdr pane move` of a legacy sleeping pane without waking it first leaves
   a record the plugin can no longer match (no terminal_id, pane id gone).
4. A pane with typed-but-unsubmitted text (`sleeper-review-p` had a bare
   `claude` typed) must only be relabelled, never prompted or moved with
   focus.
5. The autorename hook only relabels a generic or autorename-made tab and
   never moves it (2026-10-30), so it does not fight the new names.

## Pitfalls met on 2026-10-29

Read this before the first move of a full pass.

1. Closing the starter tab of a workspace you just created, before a real tab
   is in it, deletes the workspace (`workspace_not_found`). Move a real tab in
   first, then close the starter (principle 6).
2. The first `pane read` of a new starter can be empty. That is a missed read.
   Read again. Untouched is the shell startup warning and a prompt ending in
   `$`, `%`, or `#`.
3. A host named in a hint belongs in that configured workspace. Do not create
   `pastebin` when `remote` lists pastebin. The hint word has to be a token in
   the tab label. A foreground `ssh`, `mosh`, or `et`, or a screen that shows
   one, does not move a tab whose label does not match. `mac-barnowl-t` stays
   in `one-offs`. That disagreement is a question after the sure moves, and
   only when the operator has not already ruled it.
4. Session title, cwd, and screen do not place a tab. Four tabs were moved
   into `aiuse+ade` because their sessions mentioned herdr, secretspec, or
   OpenUsage, and the operator rejected that. `paseo-herdr-generic-t` stays
   with herdr because the tab label contains `herdr`. `paseo-pane-t` does not.
5. `pane move --label` is the current tab label. Do not rename a non-digit
   tab because the screen looks like something else. A new single-digit tab
   can appear during the pass and push a workspace past 5 tabs. Name it from
   its screen, place it by that name, and count tabs again before the next
   question.
6. Unclear tabs are asked one at a time, and only after every sure move
   (hint matches, `monitor`, `remote`, `one-offs`). Apply the answer, count
   the tabs, then ask the next. One combined question, or a question while a
   sure move is still pending, is wrong. `stop` sends the tabs not yet asked
   to `agents`, then `agents-2`, `agents-3`.
7. Moving from a list of pane ids captured before other moves dropped the
   mosh client on `pastebin.xvm` when its workspace emptied. No mosh client
   to pastebin remained. Old ids alias, so the stale id never moved that
   pane. Fresh id and foreground pid before each move; confirm the pid after;
   diff the pid list at the end. Do not relaunch the lost client.
8. To put `monitor` first when other configured workspaces already exist,
   rename those later workspaces to `<name>-old`, create in file order
   starting with `monitor`, and move into each new workspace before closing
   its starter. Creating `monitor` while `aiuse+ade` already exists puts
   `monitor` second. The match itself is principle 13. Another rebuild in
   the same pass, after a pid has already gone missing, waits for the
   operator.

## Geometry inside a tab (from the retired pane-layout notes, 2026-07-28)

1. `herdr pane resize --direction` is inconsistent across a nested split: if
   a call returns `"changed": false` or grows the wrong pane, try the same
   direction on the *other* pane sharing that boundary, and check the rect.
2. `herdr pane swap --source-pane <id> --target-pane <id>` repositions panes
   without closing or recreating them.
3. A pane shrunk to a few rows returns only 1-2 lines from `agent read`, even
   at `--lines 150`. If `herdr pane get <id>` shows single-digit
   `viewport_rows`, `herdr pane zoom <id> --on`, read, then `--off`.

## Postscript: tabs that match no configured hint

Operator, 2026-10-29. Do this after the placements that match a hint,
including principle 13, and before the report. Start it only once those sure
moves are finished. `~/.config/autorename/workspaces.conf` is the list (it is
not a toml). `remote` sits just before `one-offs`.

1. **Remote.** A tab whose label names `pastebin`, `vps-primary`, or another
   remote machine, or contains `ssh`, `mosh`, or `et` as its own token, goes
   to `remote`. Create `remote` only when at least one tab belongs there.
   Do not also create a workspace named after the host.
2. **Obvious groups.** An agent tab that matches no hint still shares a
   workspace when the tab name, then the session title, cwd, or screen, names
   one clear project. Two tabs of that project are enough to make the
   workspace. Keep the tab labels.
3. **Steps for the ones that are still unclear.** This walk starts only after
   the sure moves. Walk them with `/steps`: one question per tab, recommended
   option first, then act, then the next tab. Offer the configured workspace
   the other info suggests, a new workspace named from the tab, `agents` (or
   `agents-2` when `agents` already holds 5), and leaving it where it is.
   `stop` ends the walk. Tabs not yet asked go to `agents`, then `agents-2`,
   `agents-3`.
4. **Not an agent and not remote.** A shell or tool whose tab name matches no
   hint goes to `one-offs`.
5. Do not move the pane this pass is running in, except principle 7. A
   workspace that would go past 5 tabs overflows to `<name>-2`.
