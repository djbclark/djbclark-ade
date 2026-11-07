# Brief E2 (S-dead): delete the retired and dormant pieces

Wave 2 of `docs/slim/PLAN.md` (E2, D14, D12). Writer: one Claude agent in its own worktree of djbclark-ade on branch `claude/determined-maxwell-uvddaz`. Evidence per path: `docs/slim/ledger.md` section D (rows whose plan ref names E2) and `docs/slim/ledger-rows.json`. Facts: `docs/slim/research/wave2-2026-11-06.md` item 1b (Paseo's built-in `.worktreeinclude`) and 1c (native idle cleanup, fixed 1 h). Rulings: `docs/slim/ledger-rulings.md` items 6, 7, 8, 11. Read AGENTS.md orders 2 and 9.

**Merge gate**: this slice's merge waits for the C7 drain output (`docs/slim/log.md`, Wave 2 operator batch) because it deletes `plugins/herdr-sleeper`. Do the work now; the lead merges later.

## 1. Scope (exact)

1a. **DELETE** with their tests: `bin/ade-scan-state`, `bin/ade-scan-state-doc`, `tests/test_ade_scan_state.py`; `bin/seat-name`; `bin/jev`, `bin/jev-eval`, `docs/jev.md`, `tests/test_jev.py`, `tests/test_jev_eval.py`, `claude/hooks/jev_effort_hook.py` (its template line, `agents/claude/settings.json.tmpl:618` area, is the merger's: report it), and the JEV / `shadow_kind` code in `bin/route_agent.py` that only `jev` fed (find it with `grep -n -i "jev\|shadow_kind" bin/route_agent.py`; remove the branch, keep the function signatures the tests of `route_agent.py` call; run `tests/test_route_agent*.py`); `skills/ralph-tui-orchestration` (five `ralph-tui-*` skillOverrides lines in the template: merger's, report them); `skills/skillopt-sleep-learned`; `plugins/herdr-sleeper` and `docs/agent-sleep.md` (replacement text in the report: Paseo `agents.idleRuntimeCleanup`, default on, fixed one hour, host-wide); `skills/cow-workspaces`, `bin/cow-pasture`, `tests/test_cow_pasture.py`, `tests/test_cow_pasture_deps.py`, `tests/test_cow_pasture_untrust.py`; `vendor/gate-scripts` (and its rows in `vendor/README.md`; the `config/routing.toml` rows at about 539-547 that reference gate-scripts go in this slice too, ruling 11, with `tests/test_route_agent*.py` and `tests/test_gates.py` run after).

1b. **UNLINK**: `skills/jevlike` (a symlink into sipb-agent-skills).

1c. **MOVE to `docs/history/`** (`git mv`, same filename, with a one-line header "moved from docs/ on 2026-11-06 by the slim-down, E2"): `docs/ade-everywhere-codex-review-2026-10-19.md`, `docs/ade-everywhere-inventory-2026-10-19.md`, `docs/ade-everywhere-inventory-2026-10-20-stores.md`, `docs/ade-everywhere-phase0-scan-2026-10-20.md`, `docs/ade-everywhere-prior-art-2026-10-19.md`, `docs/ade-everywhere-proposal.md`, `docs/ade-everywhere-review-evaluation-2026-10-19.md`, `docs/ade-everywhere-review-evaluation-v21-2026-10-19.md`, `docs/ade-everywhere-v21-review-codex-2026-10-19.md`, `docs/ade-everywhere-v21-review-fable-2026-10-19.md`, `docs/apply-toolchain-prompt.md`. Fix links that point at them from KEEP docs (`grep -rn "ade-everywhere\|apply-toolchain-prompt" docs/ README.md`).

1d. **Precondition** (research 1b): add a committed `.worktreeinclude` at the repo root listing the gitignored files a Paseo worktree of this repo needs (read `.gitignore` and `skills/cow-workspaces/SKILL.md` for what `cow-pasture` copied: typically `.claude/settings.local.json`, `.env`-style files are NOT included; keep it to what cow-pasture's scrub kept, and say in the report what you chose and why). If nothing needs copying, commit an empty file with a comment line saying so.

1e. **Reference-only edits in KEEP files** (ruling 11): `bin/ade_claims.py:1272` and `bin/ade-git-guard:18` name `cow-pasture`: reword to Paseo worktrees; `docs/threat-model.md` mentions `ade-scan-state`: reword; `skills/session-finder/*` or any other file naming `seat-name`, `jev`, `herdr-sleeper`: reword or drop the sentence. Not AGENTS.md's retirement box (E11).

1f. **Not in this slice**: `config/launchd/dev.herdr.server.plist`, `bin/herdr-server-run`, `tests/test_herdr_server_run.py` (ruling 6: DECIDE at the C7 gate); the herdr plugin registration on the Mac (operator step, see 3E); `skills/dialogue`, `skills/research`, `skills/loose` (E6); `prior_art_nudge.py`, `skillopt-night` (E10).

## 2. Method

2a. Delete and move as listed; after each group, `grep -rn` every removed name (`ade-scan-state`, `seat-name`, `jev`, `jevlike`, `ralph-tui`, `skillopt-sleep-learned`, `herdr-sleeper`, `agent-sleep`, `cow-pasture`, `cow-workspaces`, `cow pasture`, `gate-scripts`, `ade-everywhere`, `apply-toolchain-prompt`). Zero hits outside `AGENTS.md`, `README.md`, `docs/queue.md`, `docs/history/`, `docs/slim/`, `docs/checkins/`, `docs/handoffs/`, `changelog.d/` and `graft/`; README rows, `docs/skills.md` rows and template lines are the merger's (report them with line numbers, do not edit). Note `jev` is a short word: check each hit is the tool.

2b. `launchd/`: no plist here belongs to E2 (the skillopt-sleep plist is E10's, zcode-key-auth is E9's, the others E5's). Touch none.

2c. Tests: `bin/pytest -q tests/test_route_agent.py tests/test_route_agent_disabled.py tests/test_gates.py tests/test_ade_git_guard.py tests/test_ade_claims_quote.py tests/test_skill_everywhere_all.py`, then the full suite in the background (`bin/pytest -q > /tmp/e2-suite.log 2>&1; echo rc=$? > /tmp/e2-suite.rc`) compared with `docs/slim/baseline.md`: no new failure; the baseline rows for deleted test files disappear.

## 3. Report (`docs/slim/reports/wave2-E2.md`, committed in your worktree)

A. deleted (path, lines), B. moved to history, C. `.worktreeinclude` content and reasoning, D. reference edits made in KEEP files (file:line), E. operator steps: `herdr plugin unlink djbclark.herdr-sleeper` (or the exact command from `plugins/herdr-sleeper/README.md:61`) before the final merge, and the `~/.claude/settings.json` hook line for `jev_effort_hook.py` (C2), F. merger's lines (README, docs/skills.md, template, AGENTS.md retirement-box items that this slice makes stale: `seat-name`, `plugins/herdr-sleeper`), G. test result with the baseline diff, H. lost on purpose: one line per behaviour (e.g. "herdr sleeper: idle herdr panes are no longer put to sleep and woken; Paseo's own idle cleanup covers Paseo agents only").

## 4. Do not

Touch AGENTS.md, README.md, docs/skills.md, CHANGELOG.md, docs/queue.md, the template (merger's); touch the Mac; delete anything in 1f; "fix" a baseline failure by deleting a test that is not in 1a.
