# Workspace, tab and pane layout: the from-first-principles re-arrangement

Operator request, 2026-10-08: "a one-time from-first-principles re-arrangement
and re-name of all herdr workspaces, tabs, and panes". This file is the
procedure so it can be repeated (a full pass, or one workspace) without
rediscovering the gotchas. Read [pane-layout.md](pane-layout.md) first: it
owns the "never close" rule and the geometry inside a tab; this file owns
which workspace and tab a pane lives in and what everything is called.

## Principles

1. **Workspace = project or area, named after the operator's `~/s` topic
   tree** (`~/s/ai/hermes` → `hermes`, `~/s/android` → `android`,
   `~/s/cm` → `cm`, `~/s/ai/litellm` → `litellm`). A pane goes in the
   workspace of the thing it is *about*, not the directory it happens to be
   in (a Mac lockup investigation running in `~` belongs in `mac`). Two
   fixed workspaces are not topics: `ade` for work on the agent toolkit
   itself (this repo) and `helm` for the orchestrator/relay sessions that
   watch everything else. One-tab workspaces are fine when the project is
   distinct; do not merge projects to save sidebar rows.
2. **Tab = one unit of work, labelled `<topic>-t`; its pane `<topic>-p`;
   the agent in it bare `<topic>`** (the convention in
   `memory/feedback_herdr_tab_pane_naming_convention.md`). `<topic>` is the
   session's subject, taken from the session itself (first user message,
   handoff, sleeper journal entry), never from the old label: labels drift
   and were found rotated relative to their panes.
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
6. **Nothing is closed, ever** (pane-layout.md). Empty tabs are moved out of,
   not deleted; `pane move --new-tab` closes the *source* tab for you, which
   is the only closure this procedure performs.
7. **Do not move your own pane.** Moving the pane you run in gives it a new
   pane id mid-session and is the documented risk in pane-layout.md; leave
   it where it is and say so in the report.
8. **Workspace order cannot be changed** (no reorder command; order is
   creation order). Rename in place rather than recreating to reorder.

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
name, cwd (`herdr pane process-info <pane>`), and for each pane *what it is
about*. Sources for "about", in order: the sleeper journal entry title, the
live agent's name, the session's first user message
(`~/.claude/projects/<slug>/<uuid>.jsonl` for Claude; the sleeper record
holds the session id), the pane's last screen lines (`herdr pane read <pane>
--source recent-unwrapped --lines 40`, plain text, not JSON), and finally
the cwd. Do not trust the existing label.

### 2. Decide the target layout before touching anything

Write the whole target table (pane → workspace, tab label, pane label, agent
name) to a scratch file and check it against the principles: every
`<topic>` unique within its workspace, nothing over 24 characters, no
generic workspace names (`herdr_place.py check` in the `autorename` skill
rejects `shells`, `agents`, `work`, `scratch`, numbers, …), your own pane
left where it is.

### 3. Rename workspaces

```bash
herdr workspace rename w24 android
```

Rename, never recreate: a new workspace would change every pane id in it.

### 4. Relabel panes that stay in place

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
(the old one is reported as `previous_pane_id` and stops resolving; the
`terminal_id` is unchanged). Use the new id for the `pane rename` /
`agent rename` that follow. The source tab is closed by the move. A live
agent survives the move; its name is kept.

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

[relocate-pane.sh](../relocate-pane.sh) does exactly this cycle for one pane
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
   `grok-chief-of-staff-t` held the Mac lockup session). Identify by
   content, relabel from the journal/session, and do not propagate old names.
3. `herdr pane move` of a legacy sleeping pane without waking it first leaves
   a record the plugin can no longer match (no terminal_id, pane id gone).
4. A pane with typed-but-unsubmitted text (`sleeper-review-p` had a bare
   `claude` typed) must only be relabelled, never prompted or moved with
   focus.
5. `herdr_place.py check --auto` returns `ask: false` once the workspace is
   not generic, so the autorename hook does not fight the new names.
