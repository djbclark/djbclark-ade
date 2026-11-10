# djbclark-ade — an agentic development environment

One operator, one Mac, many coding agents run as one environment: the skills every agent loads, the few tools
that start, steer and review them, and the docs that record what was verified. **Paseo is the only harness**
(2026-10-31). Providers kept (pool audit 2026-11-06, rulings 2026-11-07; Pi sole-TUI 2026-11-08/09): **claude, codex,
cursor, antigravity, pi, hermes**, each on its own paid pool, and **grok-bot** (Cursor-billed, through peer-link).
omp/OpenCode are retired as live TUIs (routing `retired = true`; packaging may remain until Wave 6 cleanup). Agents
read [AGENTS.md](AGENTS.md) (`CLAUDE.md` links to it) first; this page is the map.

## The loop

1. **Find**: `paseo ls -a -g --json` lists every live agent and where it works; `paseo agent inspect ID --json` says
   what one is doing. Continue a topic by messaging its agent, by `/baton` from its handoff, or start fresh.
2. **Start**: `paseo run --provider P/M --title T [--thinking E] [--mode M] "<prompt>"`, in its own worktree with
   `--new-workspace worktree`. Which provider, model and effort: `bin/route_agent.py plan`, [`model-routing`](skills/model-routing/SKILL.md).
3. **Answer**: `paseo permit ls` lists pending permission cards; the asks / questions-please plugins (installed at the final merge) are the
   operator's inbox. Agents message each other with `paseo send --json` (positional id + message / `--prompt`; ask for
   `ack <your id>` and prove the return path). The one-cycle shim `skills/session-finder/relay.py` remains until Wave 6
   deletion (soft deadline 2026-11-20; [docs/slim/wave6-follow-up.md](docs/slim/wave6-follow-up.md)) — do not start new
   call sites on it.
4. **Carry**: [`handoff`](skills/handoff/SKILL.md) (Tier 2 document), [`session-handoff`](skills/session-handoff/SKILL.md)
   (Tier 1 pointer), [`baton`](skills/baton/SKILL.md) (`/resume`); [`loose`](skills/loose/SKILL.md) and [`steps`](skills/steps/SKILL.md) walk what is open.
5. **Fan out**: [`fan-out`](skills/fan-out/SKILL.md): the Agent tool or a Workflow in process; `paseo run --no-wait` for a
   slice in its own worktree; `paseo wait` to collect. Rules: [docs/orchestration-practices.md](docs/orchestration-practices.md).
   `bin/acp-dispatch` is a transitional `paseo run` shim scheduled for the same Wave 6 deletion — not the default launch path.

## Layout

| Path | What |
|---|---|
| `skills/` | the canonical copy of every hand-written skill (edit here, never through a TUI's path); roster below |
| `bin/` | the tools; roster below. `libexec/git-hooks/` and `libexec/agent-bin/git` are the git guard's hooks and shim |
| `claude/` | Claude Code `agents/` (`adversary`, `backend`, `fable-deep`, `ux`), `hooks/`, `commands/` (only `resume.md`), linked from `~/.claude/` |
| `agents/<tui>/*.tmpl` | live Claude, Codex and Hermes config templates (opencode tmpl is residual packaging); secrets as `{{ secret "NAME" }}`; `bin/ade-template-check` is their gate ([agents/README.md](agents/README.md)) |
| `config/` | `routing.toml` (pools, `[lead].fable_lead`), `gates.toml` (frontier allowance), `secret-deny.toml`, `pr-policy.toml`, schemas |
| `tools/acp-run/`, `opencode-plugins/`, `omp/` | transitional ACP client (removed with `acp-dispatch` in Wave 6 deletion); OpenCode plugins; omp's commands — Pi is the sole 3rd-party TUI policy ([docs/tui-security-and-pi-migration.md](docs/tui-security-and-pi-migration.md)) |
| `docs/` | AGENTS.md lists the live docs; `docs/history/` holds retired designs and records, `docs/slim/` the slim-down's plan and log |
| `changelog.d/`, `graft/` | one changelog fragment per PR (review rule 10); the generated context graph (`graft build`) |

## Install and update (this machine)

```sh
~/src/djbclark-ade/bin/skill-everywhere <name>          # link one skill into every TUI's skills dir
~/src/djbclark-ade/bin/skill-everywhere --all           # every public, private and site skill
~/src/djbclark-ade/bin/ade-update --check               # report only; exit 10 when behind
~/src/djbclark-ade/bin/ade-update                       # fast-forward, relink skills, check links, print the changelog delta
```

Targets: `~/.claude/skills` (cursor-agent reads it too), `~/.agents/skills` (Codex + Pi),
Hermes' external dir, a copy for Grok Bot; roots: this repo, `~/ops/site-private/skills`,
`~/ops/site-public-djbclark/skills`. Then `/reload-skills` in running Claude sessions. Paseo's `paseo*` skills come
from Paseo (`npx skills add getpaseo/paseo`). Details: [docs/skill-everywhere.md](docs/skill-everywhere.md).

## The review gate

Master takes changes **by PR only** (branch protection, admins included). The PR body carries the adversary's
verdict marker ([docs/code-review.md](docs/code-review.md) rule 1; AGENTS.md keeps a short pointer); the
`adversary-marker` Action (logic in `bin/adversary_marker.py`) reads it and posts the required
`adversary-marker` status beside the Tests checks. `bin/review-pr PR` is the local review (rule 11: Claude
inside `bin/review-launch`'s boundary, [docs/review-boundary.md](docs/review-boundary.md)) and prints the
marker. After a body edit `gh workflow run adversary-marker.yml -f pr=N`; wait with `gh pr checks N --watch
--required`; merge with `gh pr merge --squash --match-head-commit <reviewed sha>`.

## Where things went

herdr (bar the `herdr4paseo`/`paseo4herdr` bridges and its server runner), Orca and BB left this repo on 2026-10-31
(still installed on the Mac, untouched). The slim-down of 2026-11-06/07 ([`docs/slim/log.md`](docs/slim/log.md)
records every merge and every behaviour lost on purpose) removed what Paseo or Claude Code now does natively, or what
served a retired provider: session-finder's search and launch, helm, self-slash, autorename, bigteam (now `fan-out`),
the watch family, the quota guard and fleet governor (Paseo's session-guard and usage-auto-resume plugins, installed at the final merge), pr-wait
and the Codex local review (now the `adversary-marker` Action and `bin/review-pr`, review rule 11), SkillOpt-Sleep, the web ladder, and the agy, crush, pi,
zcode, kiro, goose, qwen, devin, copilot CLI, cline, muse and grok CLI integrations; fifteen site skills and five
tools moved to site-djbclark. Retired designs are in [`docs/history/`](docs/history/), the old README at tag
`pre-slim-2026-11-06`, each retired TUI's lessons in [docs/tui-lessons-learned.md](docs/tui-lessons-learned.md).
Every live doc is in AGENTS.md's "Read before acting" table; [docs/queue.md](docs/queue.md) holds what is carried.

## Roster (generated by `bin/ade-roster --write`; CI's `--check` fails a PR that changes skills or `bin/` without it)

<!-- roster:start -->
Skills (23, from each `skills/*/SKILL.md`):

| Skill | What |
|---|---|
| [`ade-update`](skills/ade-update/SKILL.md) | Keep this machine's djbclark-ade checkout current: fast-forward pull, relink missing skills, check CLAUDE.md and ~/.claude links, print the CHANGELOG delta. |
| [`baton`](skills/baton/SKILL.md) | Start-of-session resume from the Tier 1 pointer: follow session-handoff's Reader protocol for this directory, or its chain discovery when cwd resolves to none. |
| [`btww`](skills/btww/SKILL.md) | Remind the user which native side-question command this TUI has (Claude Code /btw, Codex /side, and so on), or say that it has none. |
| [`create-hook`](skills/create-hook/SKILL.md) | Create, edit, review or remove native OpenAI Codex CLI hooks (~/.codex/hooks.json, <repo>/.codex/hooks.json, inline [hooks] in config.toml): PascalCase events (PreToolUse, PermissionRequest, Stop, SessionStart ...), command or MCP hooks, trust review, deny/allow output. |
| [`dialogue`](skills/dialogue/SKILL.md) | Run a multi-model dialogue that produces one artifact (spec, report, design) with a final-word model: fixed speaking rounds through pinned headless routes, a machine-read footer per turn, the transcript as the record. |
| [`fan-out`](skills/fan-out/SKILL.md) | Slice parallel work, assign owners and verify reports. |
| [`graft`](skills/graft/SKILL.md) | This repo is indexed by graft/. |
| [`hand`](skills/hand/SKILL.md) | OLD WAY compatibility alias: prefer paseo-handoff for a fresh agent. |
| [`handoff`](skills/handoff/SKILL.md) | OLD WAY compatibility alias: prefer paseo-handoff for a fresh agent. |
| [`ingest-web-ai`](skills/ingest-web-ai/SKILL.md) | Design and offline normalizer for feeding Gemini/Grok (and similar) web chats into ADE memory. |
| [`loose`](skills/loose/SKILL.md) | Audit the current session for loose ends (unfinished work, unverified claims, leftover test artifacts, unreported upstream bugs), step the operator through each with /steps, then ask whether to hand off and continue, finish and archive, or keep working. |
| [`model-routing`](skills/model-routing/SKILL.md) | Route AI work by vendor × model × effort × context window on this machine: the Claude tier for a role, the effort level, which pool takes a slice (`route_agent.py plan`), how to read quota (aiuse, `paseo usage ls`), the frontier allowance, and what runs when a chosen model fails (fallback chains). |
| [`oc-go-key`](skills/oc-go-key/SKILL.md) | Archive only (Pi sole-TUI 2026-11-08/09): historically recovered an OpenCode Go session that stopped with "Go usage limit exceeded" or "Insufficient account funds" via `oc-go-key use <label>` and a resume. |
| [`old-hand-use-paseo-handoff`](skills/old-hand-use-paseo-handoff/SKILL.md) | OLD WAY: short alias for the ADE recovery handoff. |
| [`old-handoff-use-paseo-handoff`](skills/old-handoff-use-paseo-handoff/SKILL.md) | OLD WAY: deep ADE recovery handoff. |
| [`paseo-screen`](skills/paseo-screen/SKILL.md) | The route for controlling or looking at the Mac's GUI: any visible window, the desktop, a native app, a screenshot, a click, a key chord, "drive the app", "verify it in the desktop app", "computer use". |
| [`research`](skills/research/SKILL.md) | Evidence-grounded research with a verifiable paper trail: planned searches, every claim logged with a verbatim quote from an opened source, a counter-evidence pass, script-checked synthesis. |
| [`retro`](skills/retro/SKILL.md) | Write a short retrospective for a date window from the facts in git and GitHub. |
| [`session-finder`](skills/session-finder/SKILL.md) | Find past work across live and archived client transcripts in the private SQLite history index, including uninstalled TUIs. |
| [`session-handoff`](skills/session-handoff/SKILL.md) | Read/write the out-of-tree Tier 1 session pointer file (SESSION_LOG.md) for any git-repo session, not just the ops-djbclark suite. |
| [`steps`](skills/steps/SKILL.md) | Step the operator through open items one at a time, each as its own multiple-choice prompt (AskUserQuestion; clarify on Hermes; a SendToUser question widget on Grok Bot) with the recommended option first, acting on each answer before the next. |
| [`tell-chief-of-staff`](skills/tell-chief-of-staff/SKILL.md) | Pointer (2026-11-06) for messaging the operator's cloud Grok Bot "Chief of Staff" ("tell grok", "tell Chief of Staff", "hand this to grokbot") and for its ask_claude callback; the sender and its setup live outside this repository. |
| [`tell-coding-bot`](skills/tell-coding-bot/SKILL.md) | Pointer (2026-11-06) for talking to the operator's cloud Grok Bot "Coding" ("tell the Coding bot", "ask Coding", "hand this to the Coding bot", a task that needs a real browser session); the coding-bot code now lives in the peer-link repository. |

`bin/` (60, from each file's first docstring or comment):

| Tool | What |
|---|---|
| [`acp-dispatch`](bin/acp-dispatch) | Hand a slice to an agent through Paseo and get its report back (a shim, slim-down E6, 2026-11-06). |
| [`acp-dispatch-wait`](bin/acp-dispatch-wait) | DELETE with the acp-dispatch shim (Wave 6 follow-up, ledger E6/D6); was the cheap rearm waiter for one acp-dispatch record (2026-10-18). |
| [`ade-backup-stores`](bin/ade-backup-stores) | One consistent copy of every agent session store, plus the Hermes JSONL export. |
| [`ade-config`](bin/ade-config) | Check/get/diff/set for the versioned effective ADE config (schema_version=1). |
| [`ade-git-guard`](bin/ade-git-guard) | A `git` front door for what git's own hooks cannot see in a workspace another agent owns. |
| [`ade-github-setup`](bin/ade-github-setup) | Observe / plan / apply / verify for the merge-gate App (S8). |
| [`ade-install`](bin/ade-install) | Transitional install catalog, plan, doctor, keys, and bounded apply. |
| [`ade-merge-ready`](bin/ade-merge-ready) | Classify open ADE PRs against the merge gate (2026-11-09). |
| [`ade-retro`](bin/ade-retro) | A read-only raw report for a retrospective over a date window (2026-11-04). |
| [`ade-roster`](bin/ade-roster) | Print README's skills and bin/ roster, generated from the files themselves (2026-11-07, slim-down E11). |
| [`ade-sched`](bin/ade-sched) | Install a checked-in launchd plist on this machine's scheduler (launchd, systemd user units or cron). |
| [`ade-template-check`](bin/ade-template-check) | Check the agents/ config templates (Phase 0 item 4.4, 2026-10-20). |
| [`ade-update`](bin/ade-update) | Keep this machine's djbclark-ade checkout current: pull, relink, say what changed. |
| [`ade-user-install`](bin/ade-user-install) | User-scoped uv/just GitHub-release fetch or repo bin/ symlink into ~/.local/bin. |
| [`ade_claims.py`](bin/ade_claims.py) | The workspace claim library, the git-guard rules and the ref hooks (isolation slice W1, 2026-10-24; O2 redesign 2026-10-25). |
| [`ade_config.py`](bin/ade_config.py) | Versioned read-only effective ADE config (schema_version=1). |
| [`ade_config_edit.py`](bin/ade_config_edit.py) | Comment-preserving atomic scalar set for ADE config TOML. |
| [`ade_gates.py`](bin/ade_gates.py) | The frontier-model allowance, from code defaults and config/gates.toml [frontier] (docs/gates.md). |
| [`ade_github_setup.py`](bin/ade_github_setup.py) | Observe / plan / apply / verify for setup-plan S8. |
| [`ade_install.py`](bin/ade_install.py) | Install catalog, plan, observe-only doctor/keys, bounded apply. |
| [`ade_sched.py`](bin/ade_sched.py) | Install a launchd plist as a launchd agent, a systemd user unit or a crontab block (issue #279, 2026-11-04). |
| [`ade_user_install.py`](bin/ade_user_install.py) | User-scoped tool bootstrap (no shell=True, no root). |
| [`adversary_marker.py`](bin/adversary_marker.py) | Read the adversary's verdict marker from a PR body and judge it against the PR head. |
| [`agent_guard.py`](bin/agent_guard.py) | Per-agent identity guard for launch argv (2026-11-03 omp audit; Wave 6: Pi / native `paseo run` first). |
| [`bm-lint`](bin/bm-lint) | Read-only hygiene lint for a Basic Memory store (design-basicmemory W3 / R6, 2026-10-24). |
| [`changelog-fold`](bin/changelog-fold) | Fold changelog.d/*.md fragments into CHANGELOG.md's `## Unreleased` (2026-10-31). |
| [`claude-cost-mix`](bin/claude-cost-mix) | Where Claude Code spend goes, from local transcripts. |
| [`claude-settings-env`](bin/claude-settings-env) | Keep required and default `env` keys in ~/.claude/settings.json (2026-10-16). |
| [`claude_identity.py`](bin/claude_identity.py) | Which Claude Code session is this process in? |
| [`codex-env-policy-apply`](bin/codex-env-policy-apply) | Merge the template's [shell_environment_policy] tables into a Codex config.toml atomically. |
| [`context-budget-check`](bin/context-budget-check) | The nightly guard on what a fresh Claude Code session costs before the first prompt. |
| [`context-watch`](bin/context-watch) | How full is each running Claude Code agent's context, against the REAL compaction ceiling. |
| [`cursor-cloud`](bin/cursor-cloud) | Launch and inspect Cursor Cloud Agents from the terminal (2026-10-19). |
| [`deadline`](bin/deadline) | Register a maximum run time before a long command or wait, and enforce it from outside. |
| [`deadline_wait.py`](bin/deadline_wait.py) | How a long WAITER registers its own deadline (docs/deadline.md, "Waiters register themselves"). |
| [`firecrawl-router`](bin/firecrawl-router) | Firecrawl REST API with a self-hosted primary and a commercial fallback. |
| [`git-commit-own`](bin/git-commit-own) | Commit only your own paths, without pre-commit's whole-tree stash. |
| [`gnu-tools-check`](bin/gnu-tools-check) | Find macOS shell code that calls a BSD tool where the GNU one is wanted. |
| [`go_model_policy.py`](bin/go_model_policy.py) | Shared Go cost policy for routing and ACP entry points; no provider calls. |
| [`herdr-server-run`](bin/herdr-server-run) | What the dev.herdr.server LaunchAgent runs instead of `herdr server` (2026-10-25). |
| [`instruction-lint`](bin/instruction-lint) | Read-only lint for agent instruction files (issue 284, 2026-11-04). |
| [`load-watch`](bin/load-watch) | Find the agent behind a sustained load spike, tell it, and steer that work to CI (free GitHub runners; Forgejo/Hyades for MIT/SIPB work). |
| [`opencode-plugin-guard`](bin/opencode-plugin-guard) | Archive (Pi-only 2026-11-08): keep the tool-managed OpenCode plugin (rtk) at the v2 module shape; OpenCode is not a live TUI. |
| [`ops-post-checkout-guard`](bin/ops-post-checkout-guard) | Post-checkout guard for ~/ops/* deploy checkouts. |
| [`paseo-set-model`](bin/paseo-set-model) | Switch a live Paseo agent's model in place, or list the daemon's agents. |
| [`paseo-set-model.mjs`](bin/paseo-set-model.mjs) | The node half of bin/paseo-set-model. |
| [`pi-cursor-agent`](bin/pi-cursor-agent) | Cursor provider child launcher: preserve CLI auth; run print mode unattended. |
| [`pi-default`](bin/pi-default) | Choose a physical Pi model for the current task, without starting inference. |
| [`pi_defaults.py`](bin/pi_defaults.py) | Per-task Pi choices from the existing ADE router; no model calls or credentials. |
| [`post-edit-check`](bin/post-edit-check) | A fast, narrow syntax check of the file an agent just edited. |
| [`pr-policy`](bin/pr-policy) | Only djbclark (and the collaborators he invited) open ready pull requests on his repositories. |
| [`pytest`](bin/pytest) | Run this repo's pytest with the exact dependencies CI installs. |
| [`render-secret-deny`](bin/render-secret-deny) | Render config/secret-deny.toml into the files that enforce it (2026-11-04, issue #284 item 2; docs/secret-deny.md). |
| [`review-launch`](bin/review-launch) | Run ONE `claude -p` inside a review boundary and print its structured output. |
| [`review-pr`](bin/review-pr) | The local Claude review of a PR's exact head (docs/code-review.md rule 11), through bin/review-launch. |
| [`route_agent.py`](bin/route_agent.py) | Pick which vendor should run a piece of work, from capability and headroom. |
| [`skill-everywhere`](bin/skill-everywhere) | Make a shared skill visible to every agent TUI on this machine by symlinking it into each TUI's user-level skills dir. |
| [`wait-file`](bin/wait-file) | Block until a file the waited-on command writes is ready, with a hard timeout. |
| [`wave6-delete-check`](bin/wave6-delete-check) | Refuse Wave 6 shim deletion until gates pass; `--dry-run` / `--inventory` never invent Mac live (2026-11-10). |
| [`wave6-mac-proof-capture`](bin/wave6-mac-proof-capture) | Mac --live / Linux-safe proof harness for wave6-delete-check (never invents Mac live; 2026-11-10). |
<!-- roster:end -->

## Workflow migration

[Old way versus new way](docs/old-way-new-way.md) compares legacy skills with native Paseo,
records plugin advice, and defines the Linux/macOS cross-host handoff acceptance checks.
