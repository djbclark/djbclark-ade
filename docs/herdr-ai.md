# herdr-ai — say what you want done in Herdr

`bin/herdr-ai` is a natural-language command line for Herdr. Press
`prefix+alt+i` (`ctrl+a alt+i` here), type `go to the window where we are
working on physiboard`, Enter, and the tab is focused. It also renames,
creates, splits, moves, closes and tells agents things. Built and checked
2026-10-08 on herdr 0.9.1-preview (2026-09-21); the popup itself is verified
by the orchestrator, not by this page.

## Why a script

1. **Nothing does this for Herdr.** Searched GitHub and the web on
   2026-10-08: no plugin, fork or upstream feature turns language into
   workspace/tab/pane operations. Adjacent plugins (auto-pilot, explain,
   agent-titler, agent-inbox) are not a command line; the pickers are fuzzy
   only; upstream parked the command-palette requests (`docs/herdr-jump.md`).
2. **The idea exists elsewhere.** TmuxAI is tmux-only and a resident agent;
   Warp and iTerm2 are whole terminals; Ghostty declined it for core. All of
   them converge on show-then-confirm, which this copies.
3. **The shell exists.** `herdr-jump` already proved the one-line popup; this
   is the same popup with a model in the middle. Research:
   `~/.local/state/bigteam/herdr-ai-cmd/report-prior-art.md` §2, §5.

## Setup

In `~/.config/herdr/config.toml` (added 2026-10-08, after the `prefix+colon`
block; backup beside it as `config.toml.bak-herdr-ai`):

```toml
[[keys.command]]
key = "prefix+alt+i"
type = "popup"
command = "~/src/djbclark-ade/bin/herdr-ai"
description = "ask Herdr: natural language → herdr commands"
width = 72
height = 10
```

Then `herdr server reload-config`. The model is `gemini-free-lite` on the local
LiteLLM gateway (`127.0.0.1:4000`), falling back to `gemini-free` and then
retrying the lite model (the free quota behind `gemini-free` was 429 on
2026-10-08). The key
is the per-client label `herdr-ai` in `litellm_client_keys`
(`~/ops/site-djbclark/roles/litellm/defaults/main.yml`); `HERDR_AI_KEY`
overrides it. It is a loopback-only label, not a secret, and the role creates
it idempotently. `clinepass-*` models are refused.

## What you can say

1. `move to the sleeper tab` / `go to w22:t4`
2. `go to the window where we are working on physiboard`
3. `rename this tab handoff-docs` / `rename this workspace ops`
4. `new tab here called scratch` (cwd = the active pane's cwd)
5. `split this pane right` / `zoom` / `swap this pane with the one on the left`
6. `move this pane to a new tab`
7. `close this tab` (asks first)
8. `send /loose to the collie session` (asks first)
9. `prompt the hermes agent: status?` (asks first)
10. `wake grok-bridge` (asks first; only if the pane still exists)

Empty input or `q` exits at once. From a shell: `herdr-ai "<line>"`,
`herdr-ai --dry-run "<line>"` (prints the plan as JSON, runs nothing),
`herdr-ai --index` (prints the index it would send; a stderr line gives the
build time per phase: snapshot, handoffs with dirs scanned/matched, pane text,
session titles, sleepers).

## How intent is resolved

The model sees only an index, 2 to 8 KB, built every time under a 1.5 s wall-clock
deadline (env `HERDR_AI_INDEX_BUDGET`, seconds). The snapshot is required; the
other four sources are optional and are skipped when the deadline passes.
Measured 2026-10-08 on a quiet snapshot (2 workspaces, 2 panes, 31 matching
handoff dirs), five runs: 0.33 to 0.35 s in total, snapshot 0.01 s, handoffs
0.01 to 0.02 s, session titles 0.33 to 0.35 s (the slowest source, a Python
subprocess), pane text 0.02 to 0.16 s. With many panes, or the machine under load
(load average 12 to 16 at the time), expect up to the 1.5 s deadline; an
adversarial review that day saw 2.7 s with the old unbounded handoff scan:

1. **Snapshot**: workspaces, tabs, panes with labels, cwd, agent kind, name and
   status, and the active ids (`HERDR_ACTIVE_*`, else the focused ids).
2. **Session titles** from `skills/session-finder/fleet.py list --json`, joined
   by pane id (skipped if slower than 1 s).
3. **Handoff chains**: `~/.local/state/handoffs/<project>/main/SESSION_LOG.md`,
   its redirected chain file (heading, "Active work", latest handoff topic),
   for projects whose directory name matches a live pane's cwd. Bounded: the
   40 newest matching project dirs at most, a 0.4 s deadline for the scan
   (newest first, so a late stop loses the oldest), and the newest 25 are kept.
4. **Sleeping panes** from `plugins/herdr-sleeper/herdr-sleeper list`, only
   those whose pane exists in the snapshot.
5. **Pane text**: the last six lines of every pane (`herdr pane read`, 8 in
   parallel, 0.5 s each, 1.2 s in all), rules and box edges dropped.

"The window where we work on X" is matched against those in that order.
Over the 12 KB prompt budget, pane text goes first, then the oldest handoffs.
Two equally good matches make the model ask; the question is shown, your answer
is added, and it tries once more.

## Checks and confirmation

The script, not the model, checks every command before anything runs: the verb
must be in its allow-list, every workspace, tab, pane and agent must exist in
the snapshot (case fixed to the real id), `--cwd` must be a directory, at most
six commands, no `--current`. A bad plan prints `refusing: …` and runs nothing.

Everything the model writes is made harmless before it is shown or run: labels
(rename, `--label`, agent names) are cut to 80 characters and `agent prompt`,
`pane send-text` and `pane run` text to 2000; escape sequences and control
characters are removed and newlines, carriage returns and tabs become spaces, so
a plan line, `say` and `ask` can never move the cursor or hide another line. Ids
are case-folded to the live id only when exactly one live id matches; two ids that
differ only by case are refused as `ambiguous id`. `pane move` needs a destination
(`--tab`, `--new-tab`, `--workspace`, `--new-workspace` or `--target-pane`).

| Runs at once | Needs one `y` for the whole batch |
|---|---|
| focus, focus-id, rename, create, split, move, swap, resize, zoom, report-metadata (without `--env`) | close; pane run, send-keys, send-text; agent prompt, start, send-keys; herdr-sleeper wake; any command carrying `--env`; session, worktree, machine, server, plugin, integration changes |

The class is worked out per command, so `tab create --env X=Y` asks while a plain
`tab create` does not. The session, worktree, machine, server, plugin and
integration verbs take only the argument shapes in each verb's `--help`: a name or
id (letters, digits, `_ . -`, never starting with `-`), `owner/repo[/subdir]` for
`plugin install`, an existing directory for `plugin link`, and the listed flags;
any other `--word` or `-y`/`--yes`/`--json`/`--trust-repository` is refused.
`plugin action` is not allowed at all (its arguments are a nested subcommand).

The plan prints as `herdr …` lines first (`!` marks the ones that ask). Any key
but `y` cancels with exit 0. Without a terminal a confirm-class plan cancels with
exit 0 and a note on stderr (`needs a keypress to confirm …`).
Absolute pane focus is the socket call `pane.focus` (the CLI has none), as in
`herdr-jump`. Each run appends a line to `~/.local/state/herdr-ai/log.jsonl`
(your line, the model, the plan and the outcome; no pane text, no key). The file
is created mode 0600 and cut to its last 2000 lines whenever it passes 4000.

Exit codes: 0 = done, nothing to do, asked a question, or cancelled (including
the no-terminal cancel above); 1 = failed or refused (the message shows for 1.5 s
on a terminal); 2 = usage error or a refused `--model` (`clinepass-*`, any case,
leading spaces ignored).

## Limits

1. One shot, no tool loop: it cannot look something up and try again.
2. `gemini-free-lite` is a small model: it can pick the wrong tab. Read the
   plan; focus and rename are cheap to undo, the rest asks.
3. Index text (titles, screen lines) reaches the model, so a hostile pane could
   try to steer it. The allow-list, the id check, the text cleaning and the `y`
   gate bound what a steered plan can do; do not press `y` on a line you did not
   ask for.
4. Model timeout is 8 s in total (5 s for the first attempt). Measured gateway
   latency was 0.7 to 5 s for a new prompt, so a call takes about 1 to 6.5 s with
   the index. Two of nine dry-runs timed out on a cold gateway; run it again.
5. Sleeper entries for panes that no longer exist are dropped, so `wake` of a
   gone pane is refused. Ids are never invented; unknown ones are refused.
6. Python 3.9+ standard library only; tests: `tests/test_herdr_ai.py`.

## Verified 2026-10-08

1. Config reload applied with no diagnostics (`herdr config check`: ok).
2. `herdr-ai "go to w27:t3S"` moved the view through the CLI path; a focus to
   a tab that does not exist was refused with exit 1.
3. `--dry-run` plans for "go to the window where we are working on
   herdr-sleeper" (tab focus), "rename this tab xyz" and "close this tab"
   (confirm-class) came out right; the confirm prompt was driven through a pty
   and `n` cancelled without closing anything.
4. Popup behaviour (focus from inside the popup moves this client's view) is
   left to the orchestrator.

## Review fixes 2026-10-08

An adversarial review the same day found, and this page now describes the fixes
for: control characters in model text (cleaned), `--env` on auto-class verbs (now
confirm-class), unchecked arguments on the session/worktree/machine/server/plugin/
integration verbs (typed), an unbounded handoff scan (deadlines and caps), and
nine smaller points (exit-code docs, `clinepass` guard, `pane move` destination,
`http.client` errors, log mode and size, ambiguous ids).
