# Sleeping idle agents — Orca hibernation and `herdr-sleeper`

Status 2026-09-26. Probes beat this page; re-run the commands.

## The problem, measured

On 2026-09-26 this 16 GB machine had **15 `claude` processes summing to
2.0 GB RSS**, the largest single category (Orca 461 MB, Hindsight 247 MB),
with **6.5 of 8 GB swap in use** and ~6.9 GB in the compressor.
`orca diagnostics memory` reported `hostUsed: 10 GB / 16 GB`. Fourteen of the
fifteen lived in Herdr panes (`herdr agent list`), most idle 5–6 hours.

Probes: `ps -eo rss,comm | awk '$2 ~ /claude/ {s+=$1;n++} END {print n, s/1024/1024 " GB"}'`,
`sysctl vm.swapusage`, `orca diagnostics memory --json`.

## Orca: Agent hibernation (built in, GUI)

Orca ships exactly this feature; docs at
<https://www.onorca.dev/docs/agents/hibernation>.

1. **Automatic.** Settings → **Experimental** → toggle **Agent hibernation**;
   under it, **Hibernate after** (labelled "Sleep after" in the bundle) sets
   the idle window: default 30 min, range 1 min – 24 h. On this machine it is
   **enabled at 2 h** (`settings.agentHibernationIdleMs = 7200000` in
   `~/Library/Application Support/orca/profiles/local-default/orca-data.json`).
   Operator target is 12 h — change it in that settings pane.
2. **Manual.** Right-click a worktree card in the sidebar → **Sleep**, or
   **Sleep with Descendants (N)** when nested children exist. Multi-select
   works ("Close all active panels in the selected workspaces to free up
   memory and CPU").
3. **Finding slept worktrees.** Sidebar filter menu → show/hide sleeping
   workspaces; assignable shortcut **Toggle Sleeping Workspaces** under
   Settings → Shortcuts (no default binding).
4. **Waking.** Open the worktree. Orca relaunches the agent with the same
   resume flags it uses for session history (`claude --resume <id>`,
   `codex resume <id>`, …), the original argv, and the captured private env.
   Nothing to click.
5. **Eligibility (all must hold):** agent `done`; not in the active worktree
   or any worktree rendering a foreground terminal; no keystrokes since done;
   a resumable agent (Claude, Codex, Gemini, Antigravity, OpenCode, Pi, MiMo,
   Droid, Grok, Devin, OMP — *not* Cursor, Hermes, Copilot, Trae); idle ≥
   window; no mobile session driving it; no unsettled orchestration Dispatch;
   no live subagent roster. A worktree's panes hibernate together as a unit.
6. **Not scriptable.** "sleep" appears once in the 236-command CLI schema —
   as prose in `orca terminal close`'s notes. `orca terminal close --worktree
   <sel> --all` frees the same memory but *deletes the resume records*
   (destructive substitute). Upstream: **stablyai/orca#22571** "Expose
   worktree sleep as a CLI command" (open, 2026-09-23, names the runtime
   methods `runtime.sleepManagedWorktree` / `sleepTerminalsForWorktree`);
   **#3693** "Auto-Sleep inactive workspaces" (open since 2026-05-30; the
   hibernation feature answers it).

## Herdr: no sleep — `bin/herdr-sleeper` supplies the policy

Herdr (0.7.5-preview) has no sleep/suspend. It does track, per pane, the
Claude **session UUID** (`agent_session.value`, from the official Claude
integration's hooks) and a lifecycle state (`idle`/`working`/`blocked`/
`done`/`unknown`), and can start an agent into an existing shell pane with
forwarded args. That is everything a sleeper needs; the missing piece is
timestamps (Herdr exposes only a `state_change_seq` counter), which we get
from Claude's transcript mtime instead.

`bin/herdr-sleeper` (Python 3.11+, stdlib only, drives the `herdr` CLI):

| command | does |
|---|---|
| `herdr-sleeper scan [--idle 12h] [--dry-run] [--only PANE…] [--exclude …] [--json]` | sleep every eligible agent; dry-run runs every check (composer included) and acts on nothing |
| `herdr-sleeper wake <name\|pane> \| --all` | `herdr agent start … -- <orig argv> --resume <uuid>`; falls back to the `panes.json` snapshot if the journal was lost |
| `herdr-sleeper list` | journal of sleeping panes with phase (`asleep`, `exit-requested`, `recovered`) |
| `herdr-sleeper log [-n N]` | slept / woke / refused / reconciled, newest last (`events.jsonl`) |
| `herdr-sleeper config` | effective settings and where each came from |
| `herdr-sleeper install [--interval-minutes M]` / `uninstall` | launchd job `dev.herdr.sleeper` generated from the config (cron line on non-macOS) |

**The idle window is the user's choice**, not a property of the tool:
`idle = "12h"` / `"90m"` / `"1d"` or `idle_hours = 12` in
`~/.config/herdr-sleeper/config.toml`, `HERDR_SLEEPER_IDLE`, or `--idle`
per run (precedence: defaults → config → env → CLI). The shipped default
is 12 h. This operator uses 12 h with `exclude = ["orc", "orc-meta"]`
(Herdr orchestrators idle at the prompt by design), scanning every 30 min.
State and logs: `~/.local/state/herdr-sleeper/` (`sleeping.json` journal,
`panes.json` crash-recovery snapshot, `events.jsonl`, `sleeper.log`,
`lock`).

Mechanics, verified 2026-09-26 on throwaway workspaces (three rounds):
`/exit` returns the pane to its shell in ~1 s and the PID dies; wake
restores the **same UUID** and the agent answered a question about
pre-sleep context correctly; a draft in the composer is refused; a lost
journal is recovered from the snapshot; `--json` stdout is one document.
The pane is kept (it is the restart slot — `herdr agent start` needs a
pane at a shell prompt), terminal modes are reset, a `💤 … wake:
herdr-sleeper wake <name>` line is printed into it, and the sidebar label
gets a `💤` prefix until wake.

### Safety rules, and where each came from

Reviewed in three rounds by five models (codex/GPT-6 Astra xhigh,
Antigravity/Gemini 3.1 Pro high, Copilot, cursor-agent, opencode-go/DeepSeek
V4 Pro) — 60 findings, all adopted except the two a CLI-driven tool cannot
fix (see below); the rest of the rules come from Orca's hibernation
implementation and its bug history (#22657, #16279, #15625, #18731).

1. **Eligibility (all must hold):** kind `claude`; Herdr status `idle` or
   `done`; pane not focused; not excluded; has a session UUID *and* an
   on-disk transcript (newest copy wins when several match — a stale copy
   can never make a busy session look idle); UUID not open in another
   pane; transcript mtime older than the window; composer *positively*
   empty (a draft, an unreadable screen, a missing prompt glyph, or
   nothing rendered under the glyph all refuse); original argv safely
   replayable (`--fork-session`, `--print`, `--session-id`, a positional
   prompt or anything after `--` refuse).
2. **Act on live state:** everything is re-checked *after* the journal
   write and immediately before `/exit`, including that `state_change_seq`
   and the session UUID have not moved since the scan; `/exit` is sent to
   the **pane id**, never the agent name (names were observed being
   reassigned wholesale between two listings on 2026-09-26); "exited"
   requires Herdr to drop the agent *and* `process-info` to show no
   `claude` process — an unreadable process-info is unknown, not gone.
3. **Never lose the handle:** the journal entry is written before `/exit`;
   if the agent is still there after the wait it stays as
   `exit-requested` and later scans reconcile it (dropped only after being
   seen running with a real process on two consecutive scans, or when the
   pane runs a different session; `asleep` once it is verifiably gone). A record is never
   deleted because its pane vanished — the manual resume command is
   printed. Every scan merges pane→UUID→argv into `panes.json`; `wake`
   recovers from it and persists the recovered entry *before* trying.
4. **Never fork a session:** wake refuses if the UUID is live in any pane
   or any process that selects it (`--resume <id>`/`--resume=<id>`, direct
   or via `node …/cli.js`), if a `claude --continue` runs in the same cwd,
   or when that cannot be verified (Herdr or `ps` failing); it also refuses
   when the pane's cwd no longer matches the journal (recycled pane id) or
   the pane cannot be confirmed to be at a bare shell. Snapshot-recovered
   argv goes through the same replay filter, and recovery requires the
   pane to exist, hold no agent, and match the snapshot's cwd.
5. **Fail closed on state and config:** a state file whose root is not a
   JSON object aborts; malformed TOML, unknown keys, booleans where numbers
   go, string-vs-list confusion, conflicting env aliases, `nan`/negative/
   `inf` windows (config, env *and* CLI) abort
   `scan`/`install` while `wake`/`list`/`log` keep working. A file lock
   serialises overlapping runs (launchd + manual) and the journal is
   re-read under it before every write.
6. **Install faithfully:** the launchd plist is built with `plistlib`
   (paths with `&`/`<` stay valid), runs the same interpreter, pins the
   absolute `herdr` binary it resolved (`HERDR_SLEEPER_HERDR_BIN`) and puts
   its directory first on PATH, carries the `HERDR_SLEEPER_*`/
   `XDG_CONFIG_HOME` env present at install time, and restores the previous
   job if bootstrap fails; the cron fallback prefixes the same env and
   refuses intervals cron cannot express exactly. CLI `--exclude` adds to
   the config's excludes rather than replacing them.

**Known limits, deliberately not "fixed":** (a) there is still a window
between the final recheck and Claude consuming `/exit` — only a native
Herdr operation could close it, which is the Discussion ask upstream;
(b) Claude only, because the idle clock is Claude's transcript — other
agents with session refs need their own idle signal (or a Herdr
timestamp).

Cost to know: `claude --resume` replays the transcript, so each wake is a
full prompt-cache write — the reason for a long window rather than
minutes.

## Upstream

1. **Herdr** does not accept unsolicited PRs (`CONTRIBUTING.md`: auto-closed
   unless on `.github/APPROVED_CONTRIBUTORS`); feature ideas go to GitHub
   Discussions. The fork `djbclark/herdr` → `~/src/herdr` (upstream remote
   set) carries the reference implementation on branch **`herdr-sleeper`**
   (`scripts/herdr-sleeper/`: script, tests, README) — byte-identical to
   `bin/herdr-sleeper` here; re-copy after changes. Draft discussion post in
   [upstream-issues.md](upstream-issues.md). While reading Herdr's source for
   the draft: `agent_resume::plan()` rebuilds `["claude","--resume",<id>]`
   from the session ref alone, so Herdr's own restart-restore drops flags
   like `--dangerously-skip-permissions`.
2. **Orca**: add our evidence to #22571 rather than open a duplicate. Draft in
   [upstream-issues.md](upstream-issues.md).
