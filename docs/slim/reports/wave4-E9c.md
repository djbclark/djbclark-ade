# Wave 4 report, slice E9c (the grok CLI retired, grok-bot kept), 2026-11-07

Worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a24cc0459db1ac868`, branch `worktree-agent-a24cc0459db1ac868` (merged from `claude/determined-maxwell-uvddaz` at bb76f46 first; bb76f46 is an ancestor of HEAD). Brief: `docs/slim/briefs/wave4-E9c-grok.md`. Scope rule kept: E7 owns `bin/route_agent.py`, `config/routing.toml`, `skills/model-routing/`, `docs/model-routing.md` and `tests/test_route_agent*.py`; none of those was touched.

## A. Deleted / trimmed

- `tools/acp-run/acp-run`: the `"grok"` row of `AGENTS`; `AFTER_KILL_DROP` and its three call-site conditions (the deny dir is now dropped before the kill for every agent); `STRIP_USER_CONFIG` and `STRIP_ANY_PERM` are `("opencode",)`; the whole "--perm deny for grok" block (`GROK_HOME_DROP`, `GROK_DROP_TABLES`, `GROK_DENY_UI_KEYS`, `GROK_HOOKS_ONLY_TABLES`, `GROK_DENY_PERMISSION`, `grok_real_home`, `grok_filter_config`, `grok_check_config`, `grok_user_hooks_requested`, `grok_strip_home`, `grok_sync_auth`); the grok branches of `strip_user_config` (the `grok_hooks` default strip, `ACP_RUN_GROK_USER_HOOKS`); `grok_windows`, `grok_set_context` and the grok branch of `apply_config` (the `--context` path is now the generic one); the `--always-approve` drop under `--perm deny` in `run()`; the `grok_sync_auth` call in `drop_deny_dir`; the docstring paragraphs and `--strip-user-config` help.
- `tools/acp-run/README.md`: the `### grok` section, the grok deny paragraph in "Per-agent choices" item 6, the grok mentions in the deny and strip lists.
- `tests/test_acp_run_grok_deny.py`: deleted. Grok cases trimmed from `tests/test_acp_run_effort_context.py` (the grok context test and fixtures), `test_acp_run_read_only.py` (retargeted to cursor, which is also read-only-unsupported), `test_acp_run_strip.py` and `test_acp_run_strip_perm_all.py` (sweep fixture names, now `acp-run-hermes-...`).
- `bin/skill-everywhere`: the `grok|~/.grok/skills` target (the `grokbot` copy target stays). `docs/skill-everywhere.md`: the Grok row, the trash-dir/`~/.grok` paragraph, the btww row and the aiuse pool list.
- `bin/ade-backup-stores`: the `grok` and `grok-db` stores. The `.grok/auth.json` credential exclusion (:118) stays as the named exception. `tests/test_ade_backup_stores.py`: the grok-only memory-v2 test removed; every other test that used `grok` as the sample file store was repointed to `omp` (`.omp/agent/sessions`) and `omp-db`.
- `bin/agent_guard.py` and `docs/agent-guard-contract.md`: the `grok` unreviewed row; `tests/test_agent_guard.py` uses `cursor` for the unreviewed loop.
- `bin/acp-dispatch`: only the two "grok retired" comments in the provider list (E6 had already removed the map entry); `tests/test_acp_dispatch.py` and `tests/test_relay_shim.py` no longer use `grok` as a sample name.

## B. Reference edits

- `skills/hand/SKILL.md`, `docs/hand-alias.md`, `skills/btww/SKILL.md`, `skills/create-hook/SKILL.md`: grok removed from the per-TUI rows.
- `skills/handoff/SKILL.md`: the grok successor route (provider, model, prompt) and the "codex or grok" fallbacks removed (successor is omp, else codex).
- `skills/research/SKILL.md`: the lead/reviewer role map no longer routes through the `grok` TUI or `--kind realtime-web`; it is Cursor's grok model through `cursor-agent`; the GrokBot shared-window note became a Cursor-slice note.
- `skills/dialogue/SKILL.md` and `references/run-config.example.json`: the Grok seat's route is `cursor` / `grok-4.7` (the `agent: grok` route removed, pool label `Cursor`); phase prompts, rulings and the `grok` seat name left alone.
- `bin/claude-quota-guard` (+ its test), `bin/load-watch` (`grok` out of `AGENT_CLIS`), `bin/paseo-set-model.mjs` (`grok` out of `PROVIDERS`), `docs/coding-factory.md` (coders row), `docs/model-tiers-design.md`, `docs/disabled-skills.md`.
- `changelog.d/claude-determined-maxwell-uvddaz.md`: one `### Removed` line, ending `(#0)`.

## C. Merger's lines

- README roster and `docs/skills.md` rows naming grok (not touched, per the brief); the `acp-run --list` sentence in the E9 changelog bullet ("... omp and grok") is now stale history.
- `agents/hermes/config.yaml.tmpl` (:6, :83, :117-126, :125, :370): the `grok-sub` provider, `xai-oauth` and `grok-4.7` defaults are Hermes-side xAI API entries, not the CLI; the template is the merger's. Decide whether the xAI API route in Hermes also goes with the cancelled subscription. `skills/fallback-chains/references/{integration,inventory}.md` and `scripts/check.py` describe the same Hermes xai-oauth chain (dated snapshots), also left.
- `docs/paseo-only-rearchitecture.md` (:258, 265, 350, 607) lists grok among Paseo providers: the plan of record, a D7 sweep item.
- `docs/software-factory-design.md`: `Grok` there is the Grok Bot reviewer persona in a dated design record; left. `docs/coding-factory.md:119` describes a third-party tool (Firstmate) and was left.
- `bin/load-watch`'s `Grok|Chrome|WindowServer` churn exception refers to the Grok desktop app process, not the CLI; left (a one-line change if the app goes too).

## D. Operator steps (the Mac, not done here)

1. Back up, then archive `~/.grok` (`bin/ade-backup-stores` no longer has a grok store; `~/.grok/sessions`, `memory-v2`, `memtrace`, `worktrees.db` are what it held).
2. Remove the `~/.grok/skills` symlinks, `~/.grok/hooks` (the autorename hook) and `~/.grok/config.toml` ignore entries.
3. Uninstall the grok CLI as installed (`npm`/`brew`/the vendor installer; not determined here).
4. Nothing for grok-bot, the `grokbot` skill-everywhere copy target or the peer-link pointer skills.

## E. Tests (baseline `docs/slim/baseline.md`)

Targeted (`bin/pytest -q`): `test_acp_dispatch.py`, `test_agent_guard*.py`, `test_skill_everywhere_all.py`, `test_claude_quota_guard.py`, `test_load_watch_churn.py`, `test_paseo_set_model.py`, `test_dialogue*.py`, `test_relay_shim.py`, `test_ade_update.py`, `test_acp_run_*.py`, `test_ade_backup_stores.py`: 879 passed, 6 skipped, 3 failed. The 3 failures are the baseline's `tests/test_acp_run_git_identity.py` rows (same three names). `tests/test_route_agent*.py` is E7's and was not run in the targeted set.

Full suite (detached worktree of the branch, the baseline command, `tests/` whole including `test_route_agent*.py`): **63 failed, 6147 passed, 29 skipped, 1248 subtests passed, 743 s**, rc=1. Every one of the 63 failing test ids is a row of the baseline's full list (`comm` of the two id lists: zero new failures). The baseline's 166 failures drop to 63 because earlier waves deleted test files; the rest are the same environment failures (git hooks and guard, self-slash, local-review leftovers, wait_file, git_identity and so on). No test in this slice's files fails apart from the three baseline `test_acp_run_git_identity.py` rows.

## F. Lost on purpose

The grok CLI as a realtime-web and research pool (the only route to `--kind realtime-web`, an xAI pool outside `aiuse`). What remains: Cursor's grok models through `cursor-agent` (used by `skills/research` and the dialogue Grok seat), and grok-bot (peer-link). The per-run `GROK_HOME` strip, its `session/set_model` context path and the grok deny semantics (`--always-approve` dropped, `[permission] ask = ["*"]`) are gone with no replacement.
