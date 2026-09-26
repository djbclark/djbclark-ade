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

`bin/herdr-sleeper` (Python, stdlib only, drives the `herdr` CLI):

| command | does |
|---|---|
| `herdr-sleeper scan [--idle-hours 12] [--dry-run] [--only PANE…]` | sleep every eligible agent |
| `herdr-sleeper wake <name\|pane> \| --all` | `herdr agent start … -- <orig argv> --resume <uuid>` |
| `herdr-sleeper list` | journal of sleeping panes |

Mechanics, verified 2026-09-26 on a throwaway workspace: `/exit` returns
the pane to its shell in ~1 s and the PID dies; wake restores the **same
UUID** and the agent answered a question about pre-sleep context correctly.
The pane is kept (it is the restart slot — `herdr agent start` needs a pane
at a shell prompt), a `💤 … wake: herdr-sleeper wake <name>` line is printed
into it, and the sidebar label gets a `💤` prefix until wake.

Eligibility: kind `claude`; status `idle`/`done`; pane not focused; has a
session UUID *and* an on-disk transcript; UUID not open in another pane;
transcript mtime older than the window; not already journaled. The script's
docstring is the full rationale.

Schedule: `launchd/com.djbclark.herdr-sleeper.plist` (every 30 min, 12 h
window), installed as a symlink in `~/Library/LaunchAgents/`. State and logs
in `~/.local/state/herdr-sleeper/`.

Cost to know: `claude --resume` replays the transcript, so each wake is a
full prompt-cache write — hence 12 h, not 30 min.

## Upstream

1. **Herdr** does not accept unsolicited PRs (`CONTRIBUTING.md`: auto-closed
   unless on `.github/APPROVED_CONTRIBUTORS`); feature ideas go to GitHub
   Discussions. The fork at `djbclark/herdr` → `~/src/herdr` (upstream remote
   set) exists for reading source, not for a PR. Draft discussion post in
   [upstream-issues.md](upstream-issues.md).
2. **Orca**: add our evidence to #22571 rather than open a duplicate. Draft in
   [upstream-issues.md](upstream-issues.md).
