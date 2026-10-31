---
schema_version: 1
handoff_id: 9eaf
parent_handoff_ids: []
lineage: none
chain: [standalone-20d5]
repo: kool-ade
workspace: kool-ade
branch: master
head_sha: fdce56bb60a34b28b97d70ac6a4b622527d39759
created_at: 2026-10-18T20:10:53-04:00
writer: claude-code
---
# Handoff — routing overhaul done; sudo-secretspec release gated on GitHub CI

## The Goal

1. Land the routing overhaul from /steps (operator decisions 1–10: in-flight reservation, `--kind`
   required, frontier advises unless `ACP_OPERATOR_APPROVED=frontier-exec`, cheap-first ladder,
   calibrate + monthly re-rank, pace/reset scoring, Fable side-door, policy in `config/routing.toml`,
   Jev shadow, housekeeping).
2. Close the last open item: sudo-secretspec `packaging/release.py` tests off this Mac.

Both are complete. Nothing is open for this chain.

## Where We Are

1. kool-ade master (all pushed): slices B, C, `tell`, D1 (waiter/lazy policy/reap throttle),
   D2 (quota: reset formats, far-reset reroute, pmset wake via NOPASSWD rule, exit-0 quota scan,
   `[escalation] ladder`), D3 (`acp-dispatch outcome`), `claude/hooks/bash_habits_gate.py`
   (0f4d9a9, live in Claude/Codex/Cursor), claude Sonnet code pool + quality band (128415a),
   Claude tier rules in `skills/model-routing` 4a–4e (557a3df).
2. sudo-secretspec sudo-main pushed 4b0b717:
   1. `release.py` `ci_gate()`: `git fetch origin ci/base`, refuses a local `ci/base` that differs
      from origin's, runs `scripts/github-ci-run --no-wait HEAD`, finds the run whose headSha is the
      overlay commit, `gh run watch --exit-status`; `--local-tests` keeps the old local suites.
   2. `test_release.py` ruff-formatted (why every tag's `sudo-release.yml` run failed) + 7 ci_gate tests.
   3. Formula: `depends_on :macos` before `sqlite` (brew style DependencyOrder).
   4. Docs: `packaging/README.md`, `AGENTS.md` CI section.
3. `ci/base` (sudo-secretspec 5b11caf + wrapper fix): `linux-ci.yml` gained a `macos` job (companion
   crate `cargo test -p sudo-secretspec-cli --locked`, `tests/sudo_packaging` ruff + pytest, formula).
4. `github-ci-run` `.git`-strip bug fixed (`s#\\.git$##` inside `$(...)` never matched, so `gh run
   list -R owner/repo.git` 404'd and wait mode always said "no run found yet") in: ci/base of
   sudo-secretspec, herdr, secretspec-sqlite; secretspec-sqlite main (pushed); sudo-secretspec main.
5. This session's job records are all closed.

## What We Tried

1. Asked the operator to "gate on GitHub CI, local tests behind a flag" before reading
   `linux-ci.yml`: it excludes `sudo-secretspec-cli` and never runs `tests/sudo_packaging`, so that
   option would have dropped the companion tests from the release gate. Retracted and re-asked;
   operator chose the macOS-job design.
2. Ran `tests/sudo_packaging` via bg: refused (rc=3, repo is CI-only per `load-watch ci`); the task
   notification still said exit 0. CI is the test run for this repo.
3. First CI run 39178019598: linux green, macos red at the formula step only (never reached before
   because ruff failed first). Fixed the dependency order; second run green.
4. Earlier in the session (pre-compaction): `git merge … | tail && git push` hid a failed merge,
   bare `sed`, and a `sudo -n` check passing on a cached ticket: all now hook-enforced or warned
   (`bash_habits_gate.py`).

## Key Decisions

1. Chosen: release gate = one GitHub run with Linux + macOS jobs. Rejected: Linux CI + local
   companion tests (still builds on the Mac); leave local (status quo).
2. release.py watches the run itself rather than the wrapper's watch (480 s cap, run takes ~15 min).
3. Run lookup matches headSha == overlay commit, so a force-pushed reuse of the branch name can't
   gate on an older run.
4. The macOS job lives in `linux-ci.yml` (name kept "Linux CI") so one `gh run watch` covers both;
   `sudo-release.yml` stays for tags/PRs.

## Evidence & Data

1. Green gate run: https://github.com/frdminc/sudo-secretspec/actions/runs/39178593187 (overlay
   492c9b0 for 4b0b717; jobs linux + macos success).
2. Red run (formula order): https://github.com/frdminc/sudo-secretspec/actions/runs/39172296558 was
   4d's first green Linux-only run; 39178019598 was mine with macos red.
3. Earlier tag failure cause: https://github.com/frdminc/sudo-secretspec/actions/runs/39151733655
   (`ruff format --check` on `test_release.py`).
4. State file: `~/.local/state/bigteam/routing-overhaul/merge-b-todo.md` (last line: DONE ~20:30).
5. Tests: kool-ade full suites green at each merge (1584, 1590, 1631); sudo-secretspec checked only
   on CI (above).

## Operator Feedback

1. "Gate on GitHub CI (Recommended)", then after the correction "Add macOS CI job, gate on both".
2. Earlier: "claude should be in a code pool, it's just fable that shouldn't be"; "include rules
   for when Opus should be used … web search for prior art" (done, 557a3df).

## Where We're Going

1. **Next action: none required for this chain.** Next real release: `just release 0.19.1-sudo.26`
   in `~/src/sudo-secretspec` now waits on GitHub CI (~15 min) instead of a local cargo test.
2. Not mine, left alone: uncommitted edits to `claude/hooks/bash_habits_gate.py` +
   `tests/test_bash_habits_gate.py` (+229 lines) by another session working here (djbclark-ade-51 or
   -1d per `fleet.py conflicts --cwd ~/src/djbclark-ade`); paseo skill edits; untracked `bin/graft/`,
   `scripts/`, `docs/handoffs/HANDOFF_standalone-32c0_…`.
3. Known unverified (from the hook work): Codex may prompt once to trust the new hook; Cursor CLI may
   not run `beforeShellExecution`; Grok has no pre-tool hook. Verify only when seen.

## Detached jobs

none (all ten of this session's records closed 2026-10-18 ~20:10).

## Quick Start

```bash
git -C ~/src/sudo-secretspec log --oneline -4 origin/sudo-main
gh run list -R frdminc/sudo-secretspec -L 3 --json headBranch,conclusion,url
tail -5 ~/.local/state/bigteam/routing-overhaul/merge-b-todo.md
```
