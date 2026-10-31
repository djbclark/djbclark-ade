---
schema_version: 1
handoff_id: 6776
parent_handoff_ids: []
lineage: none
chain: [standalone-6776]
repo: kool-ade
workspace: djbclark-ade-zz-probe-wt
branch: zz-probe-archive
head_sha: 6998c441ee774095508741bf298b7c0abc4f0f76
created_at: 2026-10-28T18:55:00-04:00
writer: claude-code
---
# Handoff — zz probe tab fix, watcher archiving, watch-tab consolidation

Scope: only the "zz probe" tab fix (PR 100) and the watch-tab work. The Octoclip memory report, the macOS
low-memory investigation, kiro-cli and goose are out of scope except as context (end of this file).

## The Goal

1. djbclark: "Find out which agent keeps making a "zz probe" tab in the "watch" paseo workspace", then "Coordinate
   having it not appear unless it is needed for some reason."
2. djbclark: "Maybe we should consolidate into a single watch tab that handles all of the watch notifications."
3. Retired watchers (`x watch ...`) and any other `x `-titled agent must be archived automatically, with their
   stuff handed to the replacement watcher first.

## Where We Are

Worktree `/Users/djbclark/src/djbclark-ade-zz-probe-wt`, branch `zz-probe-archive`, head `6998c441ee774095508741bf298b7c0abc4f0f76`,
clean, pushed. PR https://github.com/djbclark/djbclark-ade/pull/100 is OPEN, `mergeStateStatus` UNSTABLE.
Checks at 2026-10-28 18:52 New York: `pytest` SUCCESS, `context-policy` SUCCESS, Cursor Approval/Security agents NEUTRAL,
`pytest-linux` still running (run 40776576703 on this head). Master baseline for the same job: run 40782293787
(`workflow_dispatch` on cf00dfb), also still running at that time.

Done (4 commits on the branch, 93fb5fe, 7beb45e, d40d05c, 6998c44):

1. Source of the "zz probe" tabs: the throwaway seat created by probes of `bin/paseo-new-seat` (titles starting `zz probe`).
   `bin/paseo-new-seat --probe` now forces `--json`, waits (`archive_probe`, polls `paseo agent ls -g --json` until the
   status is not running/initializing) and then runs `paseo agent archive`; exit 5 if that fails. Env:
   `PASEO_NEW_SEAT_PASEO`, `PASEO_NEW_SEAT_POLL`, `PASEO_NEW_SEAT_PROBE_WAIT`. Tests: `tests/test_paseo_new_seat_probe.py` (4).
2. `bin/pytest` (executable): runs `uv run --with pytest --with pyyaml --with "agent-client-protocol>=0.9,<1.0" python -m pytest`
   (default args `tests/ -q`, `--print` shows the command, chdirs to the repo root). `tests/test_bin_pytest.py` pins it to the
   `run:` line in `.github/workflows/test.yml`. This is "fix the pytest issue permanently". The name is `pytest` on purpose:
   `bg` recognises tests by basename `pytest` or `-m pytest`.
3. `bin/watch`: `archive_retired(domain, pv, holder_target)` archives idle `x watch <domain>[ n]` agents after the
   replacement registers (a busy one is logged "left running" and archived on a later pass; the current holder never);
   `archive_other_retired(pv)` archives any idle agent titled `x ` except `x watch ` at the start of `cmd_up` (not in dry run),
   logged under domain "retired". `tests/test_watch.py` (25 tests pass) has a fake paseo that marks `archived: true` and hides
   archived agents unless `ls -g -a`. Title numbers are never reused (archived agents stay listed with `-a`).
4. Docs: `skills/watch/SKILL.md`, `CHANGELOG.md` (Unreleased, #100), `AGENTS.md` rule 2, `docs/dispatch-footer.md` item 16,
   `docs/context-hygiene.md` (use `bg bin/pytest`).

NOT done: the single consolidated watch tab. Nothing in this branch merges the per-domain watchers into one agent. djbclark
raised it as a question ("Maybe we should consolidate...") and I never put it to him as a decision, so it is OPEN, not rejected.

## What We Tried

1. `bin/ade-pytest` as the wrapper name: `bg` refused it (exit 3, treated it as a build). Renamed to `bin/pytest`.
2. The first `bin/watch` archive test failed because the fake paseo deleted archived agents, so numbering reused a title.
   Fixed the stub to keep archived entries (real Paseo does too).
3. Bare `python3 -m pytest` fails with "No module named pytest": the repo has no installed test deps, which is why the runner exists.
4. Hooks refuse: bare pytest outside `bg`, bare `sed`, and `cmd | x && y` (exit status through a pipe). Use `bg`, `gsed`, `;`.
5. PR 100's `pytest-linux` failed 59 tests that my change does not touch (suspected cause: the ubuntu runner image; PR 102 pins
   ubuntu-24.04). Not yet proven: I reran the failed job and dispatched a master baseline instead of touching the tests.

## Key Decisions

Probe seats are archived by `paseo-new-seat --probe` itself, once the seat goes idle, so a probe cleans up after itself. Retired
agents are archived only when idle and only after the replacement registered, so nothing in flight is thrown away
(`~/CLAUDE.md` item 9). Alternatives I did not weigh in writing: a pattern sweep of `zz probe` titles in `bin/watch`.

## Decisions

- [decision] `--probe` archives the seat itself after it goes idle; rejected: none recorded; because the creator knows when its own seat is finished.
- [decision] wrapper is `bin/pytest`, pinned to CI's `run:` line by a test; rejected: `bin/ade-pytest`; because `bg` treats unknown basenames as builds (exit 3).
- [decision] archive only idle retired agents, and never the current holder; rejected: none recorded; because a busy retired watcher may still hold unhanded work.
- [ruling] "Do 1, and also in the future make sure that all stuff from them gets handed off to the new watch tab, and then new/archive them automatically" (djbclark, 2026-10-28).
- [ruling] "Coordinate having it not appear unless it is needed for some reason." (djbclark, 2026-10-28)
- [ruling] "1. Yes, archive any idle `x ` agent (Recommended)" (djbclark, 2026-10-28; question-card answer)
- [ruling] "1. Not now — I'll say when (Recommended)" on restarting the Paseo daemon (djbclark, 2026-10-28; question-card answer)

## Relations

- decided_in [[HANDOFF_standalone-6776_zz-probe-and-watch-archiving_2026-10-28_6776]]

## Evidence & Data

1. Branch commits: `git -C /Users/djbclark/src/djbclark-ade-zz-probe-wt log --oneline -4`.
2. Tests: `tests/test_watch.py` 25 passed, `tests/test_paseo_new_seat_probe.py` 4 passed, `tests/test_bin_pytest.py` passed in my earlier runs (re-run with the Quick Start command to confirm; the full-suite Linux result is the open check).
3. CI: https://github.com/djbclark/djbclark-ade/actions/runs/40776576703 (this head) and https://github.com/djbclark/djbclark-ade/actions/runs/40782293787 (master baseline).
4. Agent state is `~/.paseo/agents/<cwd>/<id>.json`; watcher seq file `~/.local/state/watch/`.

## Operator Feedback

1. He chose to archive the three retired agents `x Dann 5`, `x Dann Chat 2`, `x Dann VPS` (about 290 MB of live cline processes) and wants this automatic from now on (rulings above).
2. The Paseo daemon is not to be restarted until he says.
3. Hand this work to a new tab (this handoff).

## Where We're Going

1. THE next action: read the two CI runs. `gh run view 40776576703 --repo djbclark/kool-ade --json status,conclusion` and the same for 40782293787. If `pytest-linux` fails on the same 59 tests as master, the failure is not this PR (say so; PR 102 pins ubuntu-24.04). If it passes, or fails identically to master, tell djbclark and merge only on his go: `gh pr merge 100 --squash --match-head-commit 6998c441ee774095508741bf298b7c0abc4f0f76`.
2. Repo rule 1 asks for an adversary verdict marker in the PR body (`<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->`). I have not run the adversary on this head. Dispatch it, read-only, and add the marker for head 6998c44 before merge. Re-review any repair too.
3. Put the consolidation question to djbclark as a /steps card: one `watch` agent covering all domains versus the per-domain watchers. Cost to quote: each watcher is a live agent process; measure with `ps` before quoting a number (I did not). My recommendation: keep per-domain agents but archive retired ones automatically (done), and decide on consolidation only with a measurement.
4. After merge, run one real `watch up` and check `paseo agent ls -g -a` shows no stray `x ` or `zz probe` agent (everything above is tested against a fake paseo only; no live run of `archive_retired` has happened yet).
5. Paseo daemon restart: only when djbclark says; hand off first, it drops running turns.

## Detached jobs

none

## Quick Start

```
cd /Users/djbclark/src/djbclark-ade-zz-probe-wt   # a claimed workspace; git status and git log -3 first
gh pr view 100 --repo djbclark/kool-ade --json state,mergeStateStatus,headRefOid
~/ops/site-private/bin/bg bin/pytest tests/test_watch.py tests/test_paseo_new_seat_probe.py tests/test_bin_pytest.py
```

Out-of-scope context, in case it comes up: macOS ran out of application memory because swap was nearly full (disk 94%, now about 41 GiB free);
kiro-cli and the goose proxy are DISABLED until djbclark says (memory files `project_kiro_cli_term_leaks_gpu_memory.md`,
`project_goose_scout_proxy_on_demand_only.md`); a separate Octoclip memory report is at `/tmp/octo/octoclip-memory-report.md`
(not sent; he decides).
