# Brief E1 (S-move): unlink, delete vendored, move the non-ADE pieces to site-djbclark

Wave 2 of `docs/slim/PLAN.md` (E1, D7, D12, J2a). Writer: one Claude agent in its own worktree of djbclark-ade on branch `claude/determined-maxwell-uvddaz`, plus a branch of `djbclark/site-djbclark` (cloned at `/home/user/site-djbclark`, push access). Evidence per path: `docs/slim/ledger.md` section D (rows whose plan ref names E1) and `docs/slim/ledger-rows.json`. Research facts: `docs/slim/research/wave2-2026-11-06.md` items 2–4. Read `docs/slim/ledger-rulings.md` items 2, 7, 8, 11 and the standing orders in AGENTS.md (order 9: work only in your worktree; order 2: commit after each coherent unit).

## 1. Scope (exact)

1a. **UNLINK** (symlinks into other repos; `git rm` the link only, the target repos keep the skill): `skills/sudo-secretspec`, `skills/forgejo`, `skills/hyades-docker`, `skills/forgejo-ci`, `skills/sipb-llm-bench`. (`skills/jevlike` is E2's.)

1b. **DELETE** (vendored upstream, reinstalled with `npx skills add zhiluop/siyuan-skills` where wanted): `skills/siyuan`, `skills/siyuan-article-import`, `skills/siyuan-excalidraw`, `skills/siyuan-markdown`, and `skills/_shared` (its only users are the four siyuan scripts; `tests/` mention `_shared` only as a path string, check each before deleting).

1c. **MOVE with history to site-djbclark**, same path on the other side: `skills/gmail-search`, `skills/ovhcloud-api`, `skills/aws-rules`, `skills/terminus-kira`, `skills/diskfree` (with `tests/test_bigteam_prune.py`, which tests `skills/diskfree/scripts/bigteam-prune.py`), `skills/bottom-config`, `skills/setup-modern-cli` (with its line in `.gnu-tools-check-ignore`), `skills/teach` (with `claude/commands/teach.md`), `skills/todo`, `skills/report`, `skills/greptile`, `skills/coderabbit-feeder`, `skills/firecrawl`, `skills/barnowl` (with `tests/test_barnowl_skill.py`, `tests/fixtures/barnowl-1.10`, `tests/fixtures/barnowl-master`), `skills/book-to-kb`, `bench/` (whole directory), `bin/app-tamer-ab`, `bin/heavy-shim`, `bin/codium-ai`, `bin/change-hermes` and `bin/change-hermes-ssh-gate` (with `tests/test_change_hermes_auto.py`, `tests/test_change_hermes_lock.py`). No name clashes exist on the site-djbclark side (checked 2026-11-06: none of these bin, tests or bench paths exist there).

1d. **Not in this slice**: `skills/tell-coding-bot` (KEEP, pointer), `skills/tell-chief-of-staff` (E6/E9j decides, leave it), `bin/open-clean` (PR 256 not landed), `skills/jevlike` (E2).

## 2. Method

2a. **Secrets scan first** (J2a): for every path in 1c run a pattern scan (AWS keys `AKIA[0-9A-Z]{16}`, `-----BEGIN .* PRIVATE KEY`, `ghp_`, `gho_`, `xox[baprs]-`, `sk-[A-Za-z0-9]{20,}`, `password\s*[:=]`, `token\s*[:=]`, `secret\s*[:=]`, `api[_-]?key\s*[:=]`, 40-hex and base64 blobs over 32 chars in non-fixture files) over the whole git history of those paths (`git log -p -- PATH | grep -nE ...`), then read each current file once. Any hit that is a real credential: STOP, write the hit's path and line (never the value) to your report, and do nothing further on that path. Record "scan clean" per path in the report.

2b. **History move** with `git filter-repo` (installed, a40bce5): fresh clone of djbclark-ade at the slim branch head into your scratch dir; a paths file with a select line AND a rename line per path (a rename-only line drops the path, verified 2026-11-06):

    skills/gmail-search/
    skills/gmail-search/==>skills/gmail-search/
    bin/app-tamer-ab
    bin/app-tamer-ab==>bin/app-tamer-ab
    …

Run `git filter-repo --paths-from-file FILE` in that clone, then in `/home/user/site-djbclark`: `git fetch origin master && git checkout -b slim-intake/2026-11 origin/master`, `git fetch /path/to/filtered-clone master:slim-intake-src` (or `git remote add`), `git merge --allow-unrelated-histories --no-edit slim-intake-src`. Verify `git log --follow -- skills/gmail-search/SKILL.md` shows the old history there. Before pushing: `git fetch origin master` (thin pack; the clone is shallow).

2c. **site-djbclark side**, on `slim-intake/2026-11`: rewrite `skills/README.md` (today it says the hub is retired and nothing should link there; it becomes "third skill-everywhere root for the skills moved here on 2026-11-06, linked by `~/src/djbclark-ade/bin/skill-everywhere`"); add a `tests/` entry if its test runner enumerates files; add a CHANGELOG line if that repo keeps one under Unreleased (read its CLAUDE.md first; follow its own landing rule; if master is PR-only there, open the PR and report its number, the lead merges). Push the branch.

2d. **djbclark-ade side**, in your worktree: `git rm -r` every path in 1a, 1b, 1c; edit `bin/skill-everywhere` to add the root `~/ops/site-djbclark/skills` beside the two existing roots (`bin/skill-everywhere:44` area; E1 owns this one edit, keep it minimal, and add one test case to `tests/test_skill_everywhere_all.py` if the roots are tested there); delete the `setup-modern-cli` line from `.gnu-tools-check-ignore`; add to `docs/threat-model.md:29` a pointer that the sudo-secretspec skill lives in `~/src/sudo-secretspec/skills/`. Commit in your worktree branch.

2e. **References**: after the removal, `grep -rn` each removed name (skill names, bin names, `_shared`, `bench/`) over the tree. The rule: zero hits outside `AGENTS.md`, `README.md`, `docs/queue.md`, `docs/history/`, `docs/slim/`, `docs/checkins/`, `docs/handoffs/`, `changelog.d/` and `graft/`. Hits in `docs/skills.md` rows, README rows and `agents/claude/settings.json.tmpl` (four `siyuan*` skillOverrides lines) are the serial merger's: list them in your report with line numbers, do not edit. Any other hit you fix (reword, not delete the sentence, in KEEP files; e.g. `bin/load-watch:538` names `forgejo-ci` in a docstring: reword to not name the skill). `skills/dialogue` and `skills/research` resolve `report` by name: they keep working once the operator links the new root; note it.

2f. **Tests**: `bin/pytest -q tests/test_skill_everywhere_all.py tests/test_ade_update.py tests/test_gnu_tools_check.py` plus any test that imports a moved path (grep `tests/` for each). `docs/slim/baseline.md` lists tests that fail in containers already. Then the full suite in the background: `bin/pytest -q > /tmp/e1-suite.log 2>&1; echo rc=$? > /tmp/e1-suite.rc` (review rule 2: no exit status through a pipe) and compare the failing set with the baseline: no new failure.

## 3. Report (write `docs/slim/reports/wave2-E1.md` in your worktree, commit it)

Sections: A. what moved (path, site-djbclark commit), B. what was unlinked and deleted, C. secrets scan result per path, D. shared-file lines for the merger (README rows, docs/skills.md rows, template lines), E. links and outside files for the operator: every `skill-everywhere` link the Mac has for the moved and unlinked skills (one line each, the operator relinks after the final merge with `skill-everywhere` against the new root; the unlinked five need relinking from their source repos), F. test result with the baseline diff, G. the site-djbclark branch or PR number, H. anything you left undone and why. Keep it factual; file:line, not opinions.

## 4. Do not

Touch AGENTS.md, README.md, docs/skills.md, CHANGELOG.md or the template (merger's); touch anything on the Mac; rewrite history on a pushed branch; move anything not in 1c.
