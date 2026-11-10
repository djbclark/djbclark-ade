# CI notes (Tests workflow)

Snapshot **2026-11-10** (pytest-linux timing still from PR #324 / runs 42653623753 and 42654543342; fold `--check` added to `context-policy`).

## A. What runs

| Job | When | Role |
|---|---|---|
| `pytest-linux` | Every PR/push unless `workflow_dispatch` sets `context_only` | Full `pytest tests/ -q` on `ubuntu-latest` (required for merges) |
| `pytest` (macOS) | Manual `workflow_dispatch` with `macos: true` only | Same suite on `macos-latest` |
| `context-policy` | Every PR/push | Focused Go/context/instruction-lint + `ade-roster --check` + `ade-config fold --check` (~15 s) |
| `adversary-marker` | Separate workflow | Required merge gate; do not weaken |

## B. Why `pytest-linux` is ~11 minutes

Measured on a green install PR (2026-11-09):

1. Checkout + `setup-uv` + GNU wrappers + Node 24: **~5 s**
2. `uv run --with pytest … python -m pytest tests/ -q`: **~643 s** (**6103 passed**, 19 skipped, 1375 subtests)

So the cost is the suite size, not dependency install. `astral-sh/setup-uv` already caches; adding pip/apt caches would not move the needle.

Local contrast: `tests/test_ade_install.py` alone is ~1 s. The full tree is ~87 files / ~6k tests.

## C. Options ranked (impact / risk)

1. **Docs/changelog short-circuit inside `pytest-linux`** (implemented): if every changed path is under `CHANGELOG.md`, `changelog.d/**`, or `docs/**`, skip the suite but still post a successful `pytest-linux` check. Saves ~11 min on those PRs. Does **not** change branch-protection required checks. `context-policy` still runs. Script: `.github/scripts/pytest-suite-needed.sh`.
2. **`pytest-xdist` (`-n auto`)** — high impact on every code PR (could cut wall time several× on 2–4 vCPUs), medium risk (shared temp dirs / subprocess races). **Local proof 2026-11-09** (cloud Linux worktree, `uv run … pytest -n auto tests/`): **6043 passed**, 19 skipped, 1375 subtests, **63 failed** in **613.6 s** wall. Sample failures (`test_ade_git_hooks`, `test_wait_file`, `test_deadline_wrappers[dispatch]`) also fail **serially** in the same environment, so they match container baseline noise (PLAN I5), not a clear xdist-only regression. **Do not flip required CI to `-n auto` until a GitHub Actions trial on `ubuntu-latest` is green** (compare failure set to a serial CI run on the same head).
3. **Workflow-level `paths-ignore`** — skips the whole Tests workflow (including `context-policy`). Missing required checks then need a waiver/ruleset change (see closed PR #118). Prefer (1) unless the operator wants a ruleset edit.
4. **Split fast required job vs slow full suite** — needs ruleset approval to demote `pytest-linux`. Lead can already run focused `bin/pytest tests/test_….py` locally; protection still requires the full job today.
5. **Caching / fewer redundant jobs** — low impact here (setup already ~5 s; macOS already off by default).

## D. Practice while CI is slow

Draft the next path-disjoint unit while `pytest-linux` runs (CI-overlap). Do not dual-write shared `config/install.toml` / `bin/ade_install.py` across parallel PRs. Prefer focused local pytest for the touched module; full CI remains the merge gate.
