# Wave 3 report, E10 (S-skills-sync), 2026-11-06

## A. skill-everywhere: targets and roots after the trim
- Targets (unchanged since E9, which had already removed the retired-TUI rows; no retired-TUI code path was left): `claude ~/.claude/skills`, `codex ~/.agents/skills`, `opencode ~/.config/opencode/skills`, `hermes ~/.local/share/skill-everywhere/skills`, `cursor-agent via ~/.claude/skills`, `grok ~/.grok/skills`, `omp ~/.omp/agent/skills`, `grokbot copy ~/agent-data/workflows`. The brief names Codex as `~/.codex/skills`; the script's row is `~/.agents/skills` (E9's, verified by the original author 2026-10-03) and was left as is: flagged for the lead.
- Roots: `skills/` (`SKILL_EVERYWHERE_ADE`), `~/ops/site-private/skills` (`_PRIVATE`), `~/ops/site-public-djbclark/skills` (`_SITE`, E1); precedence public, private, site.
- Changed: usage text gains "After a new skill is linked, run `/reload-skills` in running Claude sessions" (per-skill symlinks stay; no directory symlink). `--check` output format unchanged: per-skill `== name` header, one row per TUI, ends with `== end`; one stderr `warning:` per absent root.

## B. ade-update and ade-backup-stores trims
- `bin/ade-update`: already contained only fetch/ff-merge, `skill-everywhere --check`, the claude link check and the changelog listing (including fragments); it had no call to skillopt, fix-skill-frontmatter, skill-get or prior_art. No code change.
- `bin/ade-backup-stores`: store list cut to the surviving providers. Removed stores: `zcode-db`, `zcode-files`, `crush-acp`, `crush-tui`, `crush-repo`, `crush-files`, `copilot-db`, `copilot-files`, the three `antigravity-*-db` and three `-files`, `qwen`, `cline`, `cline-db`, `pi`, `muse`, `muse-db`; the schema-guard allowlist rows of zcode-db, copilot-db and cline-db; the `agy` variable. Kept: handoffs, cursor (3), hermes-state, opencode, codex (2), claude, grok, grok-db, gemini-cli, omp, omp-db, paseo, herdr (still on the machine), hermes-memory. The credential exclusions (`EXCLUDE_NAMES`, `EXCLUDE_PATHS`, `OTHER_SKIPS`) are untouched, the named exception (E9h Q4).
- `tests/test_ade_backup_stores.py`: the pi store test became `test_retired_tui_credential_paths_stay_excluded`; twelve engine tests that borrowed a retired store now get generic stores from a new `fixture_stores(mod, monkeypatch)` helper (same names, defined in the test file). 150 passed, 3 skipped.

## C. Deleted
`bin/skill-get`, `tests/test_skill_get.py`; `bin/fix-skill-frontmatter.py`, `tests/test_skill_frontmatter.py`; `skills/skills-everywhere/`; `bin/skillopt-night`, `bin/skillopt_sources.py`, `skills/skillopt-sleep/`, `claude/commands/skillopt-sleep.md`, `zcode/commands/skillopt-sleep.md` (a retired-TUI copy, extra), `launchd/com.djbclark.skillopt-sleep.plist`, `docs/skillopt-sleep.md`, `docs/skillopt-preferences.md`, `docs/skillopt-sleep-config.example.json`, `docs/skillopt-sleep-night.example.json`, `tests/test_skillopt_night.py`, `tests/test_skillopt_sources.py`, the `.gitignore` skillopt lines; `claude/hooks/prior_art_nudge.py`, `tests/test_prior_art_nudge.py`; `bin/failover.py`, `tests/test_failover.py`; `bin/npm_metadata.py`, `tests/test_npm_metadata.py` (0 callers confirmed); `claude/commands/paseo-screen.md`, `retro.md`, `steps.md`. Moved: `docs/failover.md` to `docs/history/failover.md`. No deleted test file was named in `.github/workflows/test.yml` (it runs `tests/` whole), so that file is unchanged.

## D. The failover.py finding
`grep` over bin, tools, skills, tests, claude: the only runtime import was `bin/skillopt-night` (`import failover`). `bin/web-get`, `bin/web-digest`, `bin/route_agent.py`, `bin/ade_gates.py` and `bin/acp-dispatch` name "failover" only as the English word or in comments (ade_gates and acp-dispatch comments referred to failover.py; reworded). Deleted as ruled. `tests/test_route_agent.py:1735` has a comment pointing at `tests/test_failover.py` AIUSE rows (its own fixture rows stay; comment now stale, harmless).

## E. Reference edits in KEEP files
`skills/ade-update/SKILL.md` (link step points at `bin/skill-everywhere`), `skills/retro/SKILL.md` and `skills/steps/SKILL.md` (wrapper paths replaced by "the skill's own slash command"), `skills/model-routing/SKILL.md`, `docs/model-routing.md`, `config/routing.toml` (failover.py route replaced by "a model chain is `paseo run`'s job"), `.worktreeinclude`, `bin/acp-dispatch` (2 comments), `bin/ade_sched.py`, `bin/ade_gates.py`, `bin/context-budget-check`, `launchd/com.djbclark.context-budget.plist`, `docs/scheduling.md` (2), `docs/threat-model.md` (dated E10 note under the E9 note; its skillopt/failover entries are marked a snapshot). Left on purpose (exempt: logs, history, queue, upstream-issues, tui-lessons, CHANGELOG, handoffs, checkins): and test docstrings/acp-run comments that recount the 2026-10-13 SkillOpt night as history.

## F. Merger's lines
- `AGENTS.md:49-50` (rows for `docs/skillopt-sleep.md` and `docs/failover.md`); `README.md:79` (bin list), `:83` (`/skillopt-sleep`, `/paseo-screen` in the commands row), `:84` (prior_art_nudge row), `:131` (skillopt-sleep skill row), `:250-256` (docs 14, 15); `docs/skills.md:75` (skillopt-sleep), `:84` (skills-everywhere).
- `agents/claude/settings.json.tmpl:95` (`"skillopt-sleep": "user-invocable-only"`) and the three `prior_art_nudge.py` hook lines (272, 294, 587).
- `docs/disabled-skills.md:170` names skillopt-sleep as a historical disabled skill (left).
- `tests/fixtures/context-now.txt:361-363` is a captured fixture (left).

## G. Operator steps
1. `launchctl bootout gui/$UID/com.djbclark.skillopt-sleep` and remove `~/Library/LaunchAgents/com.djbclark.skillopt-sleep.plist`; `~/.local/bin/skillopt-sleep` (installed by `uv tool`) and `~/.skillopt-sleep*`, `~/.local/state/skillopt-sleep` are his to remove.
2. C2 hook lines: remove the two live `prior_art_nudge.py` lines (PostToolUse/PostToolUseFailure and UserPromptSubmit) from `~/.claude/settings.json` (the template has three, the merger's).
3. After the final merge run `skill-everywhere --all`, then `/reload-skills` in running Claude sessions. Dangling links to remove: `skills-everywhere`, `skillopt-sleep` in every target dir; command links `~/.claude/commands/{paseo-screen,retro,steps,skillopt-sleep}.md`.
4. Links each deleted skill held: `skills-everywhere` and `skillopt-sleep` were linked from each target's skills dir (`~/.claude/skills`, `~/.agents/skills`, `~/.config/opencode/skills`, hermes' external dir, `~/.grok/skills`, `~/.omp/agent/skills`, Grok Bot's `ade-` copy), plus the Claude command links above.

## H. Tests with the baseline diff
- Required list: `tests/test_skill_everywhere_all.py tests/test_ade_update.py tests/test_ade_backup_stores.py tests/test_web_get.py tests/test_web_digest.py tests/test_route_agent.py`: 652 passed, 4 skipped, 1 failed: `tests/test_web_get.py::test_crwl_gets_js_delay`, which is in the baseline list (not a regression).
- Full suite (`bin/pytest -q tests/`, 42 min): 152 failed, 8974 passed, 32 skipped, 1 error (baseline: 166 failed). Every failing file is in the baseline table (git_hooks 45, self_slash* 41, git_guard 10, local_review 6, acp_dispatch 6, wait_file 3, acp_run_git_identity 3, deadline_wrappers 2, quota_d2 2, web_get 1, launch_turns 1, dispatch_reap 1) and none is a test this slice touched; the one ERROR is a self_slash_codex test in a baseline-failing file. Baseline rows absent now (bigteam_prune, session_relay, ade_scan_state) were fixed or deleted by other waves, not by E10. Note: `pytest` at repo root also collects `claude/hooks/handoff-tools/tests`, whose `test_context_size_nudge.py` basename collides with `tests/`; run `tests/` only.

## I. Lost on purpose
- The nightly skill-edit cycle (SkillOpt-Sleep and its transcript-source harvest).
- The prior-art shadow nudge (telemetry only, never installed as an advisory).
- `skill-get` (fetch a skill by name).
- The frontmatter fixer (`fix-skill-frontmatter`).
- failover's model chain and the Claude SDK route (`paseo run`'s model chain replaces it).
- The `npm_metadata` helper (no callers).
- Backup of retired TUIs' session stores (zcode, crush, copilot, antigravity, qwen, cline, pi, muse); existing generations stay.
