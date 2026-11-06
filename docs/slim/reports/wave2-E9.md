# Wave 2 report, slice E9 (unconditional provider retirements), 2026-11-06

Worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a469de6c7fc476388`, branch `worktree-agent-a469de6c7fc476388` (the brief named `claude/determined-maxwell-uvddaz`; the harness gave this one). Not pushed.
Note: the brief file `docs/slim/briefs/wave2-E9-retired.md` was untracked in the main checkout, so it was read from there (read-only).

## A. Removed, per provider

- **agy (TUI)**: `bin/agy-linux`; `skills/session-finder/adapters/agy.py`; `tests/test_acp_run_agy_server.py`; `tests/test_argon_frontier.py` (the Argon fallback service tested only agy); acp-run `AGENTS["agy"]`, `_agy_server()`, `ACP_RUN_AGY_SERVER`/`_CMD` override, `YOLO_SET`/`DENY_SET`/`CLIENT_NAME`/`GLOBAL_RULES` rows, `agy_deny_home`, `ensure_agy_home`, GEMINI_HOME/proxy/prompt special case in `run()`, `AGY_EFFORTS`, `agy_effort_model` and the agy branches of `apply_config`/`read_back`; routing services `antigravity`, `antigravity-claude`, `antigravity-argon`, `[dispatch.estimate_floor] antigravity-claude`, `gemini-4-argon` in `frontier_models`; `route_agent.antigravity_family` and the `agy` branch of both `map_agent_to_provider`s; `acp-dispatch` agy report path (`.acp-dispatch/`) and `resume_unsupported` agy case. Paseo's antigravity provider is untouched.
- **crush**: `bin/crush-context-check`, `bin/web-digest-mcp`, tests for both, `tests/test_acp_run_crush.py`, session adapter `crush.py`; acp-run `CRUSH_*` constants, `crush_deny_dir`, `crush_strip_config`, `CRUSH_DATA`, set_model-fallback crush guard; routing `crush` service and `extra = {crush=...}`.
- **pi**: `bin/pi-skill-dedup`, `docs/pi-skills.md`, `docs/pi-subagent.md`, `docs/pi-agent-profiles.md`, `pi/prompts/hand.md`, tests `pi_skill_dedup`, `pi_dispatch_admission`, `pi_history_identity`, `pi_native_controls`, `fleet_pi`, `acp_run_pi`; acp-run `AGENTS["pi"]`, `DENY_UNSUPPORTED["pi"]`; routing service `pi`; `route_agent.PI_OPENAI_MODELS/pi_api_pool`; `acp-dispatch.pi_capacity_refusal` and its four call sites; `agent_guard` pi row.
- **zcode**: `bin/zcode-key-auth`, `launchd/com.djbclark.zcode-key-auth.plist`, `tools/acp-run/zcode-denylist-shim.cjs`, tests `zcode_key_auth`, `acp_run_zcode_tools`, session adapter; acp-run `zcode_*` functions, `ZCODE_SHIM`, DENY/READONLY env rows, `READONLY_AGENTS`, `$/zcode` token_login_failed pattern, turninfo chunk filter; routing `zai`; `acp-dispatch` `MODEL_OPTIONAL_AGENTS`, `ZCODE_DEFAULT_PROVIDER`, Beijing-time stamp, `zcode` AUTH_HINT.
- **kiro**: `skills/session-finder/nested_pty.py`, `tests/test_nested_pty.py`, `tests/test_acp_run_kiro.py`; fleet.py `_kiro_inner`/`_KiroUnknown`; acp-run kiro rows (`HANDSHAKE_TIMEOUT`, `DENY_UNSUPPORTED`, `YOLO_CMD`); `never_route` kiro replaced by the retired-account list.
- **goose, qwen, devin, copilot CLI, cline, muse**: acp-run `AGENTS`/`YOLO_*`/`DEFAULT_SET`/`COPILOT_TIERS`/`CLINE_EFFORTS`/`launch_tweaks` branches/`task_complete` summary capture/`OPERATOR_GATED["cline"]`; session adapters `goose cline copilot muse qwen zcode`; routing services `alibaba`, `devin`, `copilot` (and `operator_gated`/aliases for cline); `fleet.py` `RESUME_FORMS`/`PROC_AGENTS`/`_native_extra` rows; `launch.py` `ACP_AGENTS`/`HERDR_KINDS`; `NON_ACP_HEADLESS` now empty; `skill-everywhere` target rows for goose pi agy copilot qwen devin cline muse zcode; `MODEL_CHECK_SKIP` emptied.
- **venicecode, aider, dsh**: no files, rows or code existed in the tree (only prose in `docs/tui-lessons-learned.md`, kept).
- **Docs trimmed**: `docs/model-routing.md`, `skills/model-routing/SKILL.md` (agy/Argon/Pi/zcode/copilot sections, table rows, per-agent items), `tools/acp-run/README.md` (all retired per-agent sections), `docs/skill-everywhere.md`, `skills/bigteam/SKILL.md` (agy pool section, reserve row, rows in the failure table), `skills/skills-everywhere/SKILL.md`, `docs/hand-alias.md` (Pi row), `skills/hand/SKILL.md` (pi/prompts mention only), `docs/scheduling.md`, `docs/threat-model.md` (dated note), `docs/apply-toolchain-prompt.md` (3 rows). `ade-template-check` and `agents/<provider>/` needed no change (no retired entries existed).
- **Tests**: acp-run tests trimmed (strip, strip_perm_all, effort_context, grok_deny, read_only, not_installed, deny); route/dispatch tests retargeted to surviving services (cursor-auto, omp, opencode); `test_acp_run_failure.py` kept as is (its agy strings are inputs to the generic refusal classifier, which stays). Fragment: `changelog.d/worktree-agent-a469de6c7fc476388.md` (PR number `#0` placeholder: the merger fills it).

## B. Left for Wave 3 / later, and why

- `pi/extensions/subagent`, `tests/test_pi_subagent_invocation.py`, `.pi/agents/`, `zcode/commands/`, everything in brief 1c: untouched as ordered.
- Pi logic in `skills/session-finder/fleet.py` (`_pi_*`, `EXACT_EXECUTABLES`), `adapters/pi.py`, `nativeid.py`, `session-find.py`, `skills/autorename/pi_*`: entangled with omp's shared code and session-finder (E5, SHIM with gate).
- `bin/failover.py`, `bin/skillopt-night`, `bin/skillopt_sources.py`: E10 deletes them (ruling 1); `bin/ade-backup-stores` credential exclusions: kept (Q4); `bin/agent_guard.py` otherwise kept (ruling 4).
- Error-text classifiers that mention retired providers but are generic (acp-run `AGENT_RUN_FAILED`/refusal patterns, acp-dispatch `COPILOT_QUOTA_TERMS` and the copilot far-reset case): left, harmless; `fallback_after` machinery in route_agent/acp-dispatch now has no service and no test (the argon test file went with its service): a later slice should delete or re-cover it.
- `DANN_SUBSTRATE` (`cline` leg) and `hermes provider_name clinepass=cline`: the Dann substrate rework is a separate ruling; the `clinepass` pool stays.
- Prose still naming retired TUIs: `skills/bigteam/SKILL.md` (copilot/cline paragraphs, steps text), `skills/session-finder/SKILL.md`, `skills/autorename/*`, `skills/research`, `skills/ralph-tui-orchestration`, `bin/self-slash`, `bin/paseo-self`, `bin/paseo-new-seat` (default provider cline: ruling says it must move), `bin/change-hermes`, `docs/failover.md`, `docs/skillopt-sleep.md`, `docs/ade-everywhere-*`, `docs/software-factory-*`, `docs/upstream-issues.md`.

## C. Merger's lines

- README roster rows, `docs/skills.md` rows for any removed skill/bin entries, and the `agents/claude/settings.json.tmpl` lines naming retired providers (12 hits for agy/antigravity etc.) are not touched.
- `AGENTS.md`: rows for `docs/pi-subagent.md`, `docs/pi-skills.md`, `docs/pi-agent-profiles.md` (table, lines 53-55) point at deleted files; review rule 3 names `bin/zcode-key-auth` (line 280).
- `.github/workflows/test.yml` test paths: not checked for the deleted tests (merger).
- Fill the `(#0)` in the changelog fragment.

## D. Operator steps (machine-side, none done; Q1 yes: back up each tool's local state first)

Backup first for all: `tar czf ~/tui-retire-backup-$(date +%F).tgz` of the directories listed below, then:
- zcode: `launchctl bootout gui/$(id -u)/com.djbclark.zcode-key-auth; rm ~/Library/LaunchAgents/com.djbclark.zcode-key-auth.plist ~/.local/state/zcode-key-auth -r`; `npm -g uninstall zcode-acp-server` and the zcode CLI (package `zcode-app-cli`; command unknown beyond that, operator looks it up); archive `~/.zcode`.
- pi: `npm -g uninstall pi-acp @earendil-works/pi-coding-agent`; archive `~/.pi`; remove `~/.pi/agent/prompts/hand.md` link.
- crush: remove `~/.local/bin/crush-acp`, `~/src/crush-acp`, `crush()` in `~/.bashrc`; archive `~/.config/crush`, `~/.local/share/crush`, `~/.local/share/crush-acp`.
- agy: `brew uninstall` the agy CLI (cask/formula name: operator looks it up); archive `~/.gemini`, `~/.local/share/agy-acp-server`, `~/.local/share/agy-acp-home`, `~/.local/bin/refined-antigravity-acp`.
- goose: `brew uninstall block-goose-cli`; remove `~/.local/bin/goose-scout`; archive `~/.config/goose`, `~/.config/goose-scout`.
- kiro: `brew uninstall --cask kiro-cli`; remove the `kiro-cli()` function in `~/.bashrc`; archive `~/.semantic_search`.
- devin: `brew uninstall --cask devin-cli`; archive `~/.config/devin`.
- cline: `npm -g uninstall cline` (prefix `~/.local`), remove `~/.local/bin/cline`; archive `~/.cline`.
- copilot CLI and qwen-code, aider, muse: install method not recorded in the repo (command unknown, operator looks it up); archive `~/.copilot`, `~/.qwen`.
- venicecode: remove `~/.local/bin/venicecode`, `~/.local/lib/venicecode`, `~/.config/opencode/venicecode.json`, `~/.config/venice-opencode-isolated`, the `venicecode()` function in `~/.zshrc`, and `~/ops/site-private-djbclark/bin/venicecode-upgrade` plus `run_venicecode_pass` in brew-fast-upgrade (plan report w20:p11).
- dsh (check-in B8f / plan): remove `~/.local/bin/dsh`, `~/.local/lib/dsh`, `~/.dsh` (including `profiles/web/cordis.patch.yml`), the `dsh()` function in `~/.zshrc`, `ensure_dsh_wrapper` in `roles/site_agents/templates/brew-fast-upgrade.sh.j2`, site-djbclark commit 3913c57's `dsh_repair_native_binding.py` and pnpm `@deepseek-ai/dsh` (`pnpm remove -g @deepseek-ai/dsh`).
- skill-everywhere links the retired TUIs hold: `~/.gemini/antigravity-cli/skills`, `~/.copilot/skills`, `~/.qwen/skills`, `~/.config/devin/skills`, `~/.cline/skills`; the goose/pi/zcode links live in `~/.agents/skills`, which codex also uses, so do not remove that directory. Then `bin/skill-everywhere --check` should list only the surviving TUIs.
- Remove `~/.local/bin/herdr-sleeper`-style dangling links only if listed by `ade update`; not part of this slice.

## E. Memory notes (Q3)

The 147 site-private memory notes that mention the retired TUIs (`site-private/memory/`, counted in `docs/slim/tui-retire-plan.md` R3: "site-private 158 incl. 147 memory notes") are to be moved by the operator to an archive folder agents do not read (for example `site-private/memory-archive/retired-tuis/`); the lessons live in `docs/tui-lessons-learned.md`. Not touched here.

## F. Tests

Method: `uv run --with pytest --with pytest-timeout --with pyyaml --with 'agent-client-protocol>=0.9,<1.0' python -m pytest` (the baseline's command). Full-suite run was NOT completed by this writer (50 min); instead, the files touching changed code were run and compared with `docs/slim/baseline.md`:
- route/gates family (`test_route_agent*`, `test_routing_recalibrate`, `test_gates`, `test_acp_dispatch_pool_map`, `test_acp_dispatch_routing`): green after fixes (last full run 3 failures, all fixed, re-run of route_agent pending in the final batch below).
- acp-run family (`deny`, `strip`, `strip_perm_all`, `read_only`, `effort_context`, `failure`, `not_installed`, `grok_deny`): 133 passed. The remaining acp-run files (`git_identity`, `verify`, `classify`, ...) were not re-run individually.
- acp-dispatch/quota/identity/fleet batch: see the last line of this section.
- Baseline failures seen unchanged: `test_acp_dispatch` (happy_path, partial_report, rearm_waiter, session_id, wrapup, quota_checkpointed), `quota_d2` (done_report_never_auto_resumes, partial_records_get_the_hint), `reap` (done_report_with_marker), `test_self_slash*` (14), `test_failover::ask_acp_runs_in_empty_dir`.
- The lead should run the full suite once and diff against the baseline before merging.

## G. Lost on purpose

- Routing to Google's AI Pro plan (Claude/GPT, Gemini, Gemini 4 Argon frontier fallback) through `acp-run agy`; reach it through Paseo's antigravity provider instead.
- The 60%-floor copilot reserve and the `github` kind's only pool (the kind stays in the TOML with no service).
- Pi's measured OpenAI-API pool (`api-only` rank 2) and its fail-closed admission gate; `api-only` is omp-only.
- zai GLM-5.3 and alibaba qwen as code/bulk pools, crush/SIPB light-bulk pool, devin.
- zcode `--perm read-only`/`deny` enforcement and key-auth keep-alive, crush/agy/zcode per-run config stripping, kiro/pi `--perm deny` refusals.
- acp-run `--list` now shows claude, codex, opencode, cursor, hermes, omp, grok.
- Tests that pinned the above (about 190 test functions removed or retargeted).
