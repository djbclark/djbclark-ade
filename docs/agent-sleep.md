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

## Herdr: no sleep — the `djbclark.herdr-sleeper` plugin supplies the policy

**2026-10-04: the sleeper is now a Herdr plugin** (`plugins/herdr-sleeper/`,
linked with `herdr plugin link`), and it owns sleeping duty; the launchd job
is retired: booted out, and its plist moved to `~/Library/LaunchAgents/disabled/` on 2026-10-05
after it had reloaded itself at a login and run alongside the plugin (bootout alone does not stick).
Restore with `mv ~/Library/LaunchAgents/disabled/dev.herdr.sleeper.plist ~/Library/LaunchAgents/ &&
launchctl bootstrap gui/501 ~/Library/LaunchAgents/dev.herdr.sleeper.plist`. The standalone `bin/herdr-sleeper` remains as the reference
implementation (byte-identical to the fork branch's `scripts/herdr-sleeper/`)
and its legacy journal was adopted once, on first startup.

The plugin keeps every fail-closed rule of the standalone script (77 unit
tests ported and extended) and adds what only a plugin can do, adopting the
good parts of both community plugins studied (`dalogax/herdr-agent-hibernate`,
`prabhatgmp/herdr-park`):

- **in-process idle watcher** started by the `startup` hook — no launchd; the
  idle clock is `state_change_seq` movement over `agent list` polling, so the
  transcript-mtime dependency (and the Claude-only limit it caused) is gone;
  claude + opencode supported (claude argv replayed on wake)
- **SIGTERM exit** (claude/opencode shut down cleanly; a composer draft is
  discarded, never submitted — the old composer-empty check still guards any
  kind exited by typing)
- **wake on focus** (`pane.focused` hook, per-pane debounce lock), **wake by
  pressing Enter in the pane** (a wake stub is exec'd into the pane's shell
  carrying its socket/session/state routing), and wake by action
- **slept panes keep their sidebar row** (`pane report-agent` claim showing
  `<kind> · sleeping`) and get a `notification show` with freed MB
- `terminal_id` as the pane identity that survives pane-id reuse

Live soak (`tests/soak_plugin_herdr.sh`, isolated named session, real Claude
processes): 15/15 — SIGTERM sleep + stub + claim, focus-wake and Enter-wake
both restore the exact session id, watcher tick sleeps, recycled-pane and
session-live-elsewhere refusals keep the handle, corrupt journal quarantined
with snapshot recovery, ~0.4 GB freed per sleep. Two live catches worth
remembering: the focus-wake refused a migrated entry whose pane now hosts a
different program (cwd check — the handle stayed printable), and the first
soak runs routed to the operator's session because a pane shell exports
`HERDR_SOCKET_PATH`, which beats `HERDR_SESSION` — the soak now unsets it
(this also explains September's leftover `focus-holder` workspace).

**2026-10-05: v0.1.1** (`ca929d7`; public `djbclark/herdr-sleeper` `ec9e92c`, byte-identical
script/manifest/tests). After two adversarial review rounds (Fable, Grok 4.7) found that v0.1.0
could silently lose its watcher, refused every slept pane after a Herdr restart (restore
re-allocates terminal ids), and could drop the only handle to a session when a pane id was reused.
v0.1.1: restored panes recognised by their 💤 label; reused ids orphan the entry (`orphan:<uuid8>`,
manual resume only) instead of dropping it; the in-pane stub marks its row `waking` instead of
popping it; the watcher never exits, holds `watcher.lock`, and is healed by any plugin activity;
idle clocks persist in `idle.json`. 156 unit tests (Python 3.9 + 3.14), branch coverage 84%, soak
27/27 (P8 server restart, P9 reused pane id, P10 focused sleep-pane added). Live since 22:29.

- **Config path:** the watcher reads `~/.config/herdr/plugins/config/djbclark.herdr-sleeper/config.toml`
  (`HERDR_PLUGIN_CONFIG_DIR`), which holds `exclude = ["orc", "orc-meta"]`. v0.1.1 refuses to sleep
  if that file lacks `exclude` while an older config still has one.
- **Soak:** run through `bin/bg`; to test code other than the installed checkout, give the lab its
  own `XDG_CONFIG_HOME` with a `herdr/plugins.json` pointing at that code.
- **For other implementers:** [LESSONS.md](https://github.com/djbclark/herdr-sleeper/blob/main/LESSONS.md)
  (41 traps with Herdr file:line evidence); upstream asks posted on
  [#631](https://github.com/herdrdev/herdr/discussions/631#discussioncomment-18769271).

## History: the standalone `bin/herdr-sleeper`

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
`<absolute script path>` `wake <name>` line is printed into it (the
running script's own path, since the bare name is not on PATH — the
launchd copy lives in this project's `bin/`; fixed 2026-10-04 after a
slept pane's hint was unrunnable as pasted), and the sidebar label
gets a `💤` prefix until wake.

### Safety rules, and where each came from

Reviewed in three rounds by five models (codex/GPT-6 Astra xhigh,
Antigravity/Gemini 3.1 Pro high, Copilot, cursor-agent, opencode-go/DeepSeek
V4 Pro) — 60 findings, all adopted except the two a CLI-driven tool cannot
fix (see below); the rest of the rules come from Orca's hibernation
implementation and its bug history (#22657, #16279, #15625, #18731).
A fourth hardening iteration ran from a week of live deployment
(2026-10-03): damaged-state quarantine, displaced-session handling,
consecutive-sighting streaks, staged plist install — 65 tests.

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
