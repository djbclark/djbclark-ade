# Wave 2 report, slice E1 (S-move), 2026-11-06

Writer: one Claude agent (Opus 5.5) in worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a4b7b27ccf9493f12`,
branch `worktree-agent-a4b7b27ccf9493f12` (the brief named `claude/determined-maxwell-uvddaz`; the lead started this agent in its
own worktree branch, fast-forwarded here to the slim branch head 21384c9 before the first commit). Brief:
`docs/slim/briefs/wave2-E1-move.md`. djbclark-ade commits: `3f35486` (unlink, delete, move, `skill-everywhere` root, test, docs),
`3209bfc` (reference rewordings), `2214d07` (this report), and the review repair (section I). Not pushed (the lead merges).

## A. What moved

Source: a fresh full clone of `djbclark/djbclark-ade` at `f994bc08` (slim branch head when cloned; the paths below are unchanged
from there to 21384c9, which only added docs under `docs/slim/research/` and a `.gitignore` line), filtered with
`git filter-repo --paths-from-file` (a40bce5), one select line and one identity rename line per path (56 lines). The filtered
tree has the same 82 files with identical blob ids and modes as the source (`git ls-tree -r` compared). Merged into
`djbclark/site-djbclark` branch `slim-intake/2026-11` with `--allow-unrelated-histories`; `git log --follow --
skills/gmail-search/SKILL.md` there shows the old history (5 commits back to 4480922).

site-djbclark commits on `slim-intake/2026-11` (base `origin/master` f11d8218):

- `f3a273f2e7222a67455b0895efcd80954c75c35a`: the merge that brings every path below (second parent 4b87808, the filtered
  history: 112 commits).
- `f8ae50f3aba1164698946165cf88360fa3f9a17f`: `skills/README.md` rewritten (section 2c), CHANGELOG line, moved files' own
  paths repointed from `~/src/djbclark-ade/...` to `~/ops/site-djbclark/...`, corrected to `~/ops/site-public-djbclark/...`
  in 3bc38c1 (barnowl SKILL.md:14,181; bottom-config
  SKILL.md:29-30; greptile SKILL.md:43; report SKILL.md:8-9; teach SKILL.md:15-16; claude/commands/teach.md:6;
  bin/change-hermes-ssh-gate:4; the "canonical source" lines of firecrawl, gmail-search, ovhcloud-api, setup-modern-cli).
  References to tools that stay in djbclark-ade (`load-watch`, `firecrawl-router`, `session-finder`, `self-slash`,
  `apply-toolchain-prompt.md`) were left as they are.
- `d2176afcf385f0354c74522a31cb4e075d4c7143`: `.gnu-tools-check-ignore` gains `skills/setup-modern-cli/*` (the line that left
  djbclark-ade's file).
- `3bc38c1884b1b7e16eb175fc1054d60f6df0974c`: the review repair (section I): `bin/bg-offload:180-184` and
  `cursor/home-agents.mdc:133` take `git-forgejo`/`forgejo-api` from `~/src/sipb-agent-skills/skills/forgejo/scripts`;
  `roles/watchdogd/templates/watchdogd.d/hermes-quota.toml.j2:19,28` run
  `/Users/djbclark/ops/site-public-djbclark/bin/change-hermes`; one sentence each for the third root in `AGENTS.md:205-207`,
  `claude/README.md:14-17`, `cursor/home-agents.mdc:126-127`; every `~/ops/site-djbclark` in the moved files (including 4
  pre-existing ones: diskfree SKILL.md:95,279, teach SKILL.md:117, firecrawl SKILL.md:150) now `~/ops/site-public-djbclark`;
  `skills/README.md` noted the two `book-to-kb` versions (the operator then chose `tools/book-to-kb`; the moved copy was deleted at 86832d2).

| Path | Newest imported commit (site-djbclark) | Commits carried |
|---|---|---|
| `skills/gmail-search/` | 52e1c2e | 5 |
| `skills/ovhcloud-api/` | 6fcdc18 | 11 |
| `skills/aws-rules/` | 3860757 | 4 |
| `skills/terminus-kira/` | 52e1c2e | 2 |
| `skills/diskfree/` | 1fec62a | 8 |
| `tests/test_bigteam_prune.py` | 1fec62a | 1 |
| `skills/bottom-config/` | 4ad2981 | 5 |
| `skills/setup-modern-cli/` | 4b87808 | 16 |
| `skills/teach/` | ce557cb | 3 |
| `claude/commands/teach.md` | 836a1f4 | 2 |
| `skills/todo/` | 3ca165a | 4 |
| `skills/report/` | 45390a4 | 7 |
| `skills/greptile/` | a0c0736 | 1 |
| `skills/coderabbit-feeder/` | 52e1c2e | 2 |
| `skills/firecrawl/` | 508a5f9 | 19 |
| `skills/barnowl/` | f6770b1 | 15 |
| `tests/test_barnowl_skill.py` | f5563bd | 4 |
| `tests/fixtures/barnowl-1.10/` | 5b4b257 | 1 |
| `tests/fixtures/barnowl-master/` | f5563bd | 1 |
| `skills/book-to-kb/` | c93b552 | 3 |
| `bench/` | d7d3f57 | 2 |
| `bin/app-tamer-ab` | 1702427 | 3 |
| `bin/heavy-shim` | 772230f | 1 |
| `bin/codium-ai` | c73c195 | 1 |
| `bin/change-hermes` | 8c91ead | 4 |
| `bin/change-hermes-ssh-gate` | 4d7711d | 1 |
| `tests/test_change_hermes_auto.py` | 4d7711d | 1 |
| `tests/test_change_hermes_lock.py` | 8c91ead | 1 |

History stops where a path was renamed into its current name (filter-repo keeps only the listed paths). PR numbers in the
imported commit messages refer to djbclark/djbclark-ade; GitHub will link them to site-djbclark's numbers (said in the merge
commit message and in `skills/README.md`).

## B. What was unlinked and deleted (djbclark-ade, commit 3f35486)

1. B1 UNLINK (`git rm` of the symlink only; targets untouched): `skills/sudo-secretspec` ->
   `/Users/djbclark/src/sudo-secretspec/skills/sudo-secretspec`; `skills/forgejo` ->
   `/Users/djbclark/src/sipb-agent-skills/skills/forgejo`; `skills/hyades-docker` ->
   `/Users/djbclark/src/sipb-agent-skills/skills/hyades-docker`; `skills/forgejo-ci` ->
   `/Users/djbclark/src/loopback-port-shim/skills/forgejo-ci`; `skills/sipb-llm-bench` ->
   `/Users/djbclark/src/sipb-llms/skills/sipb-llm-bench`.
2. B2 DELETE: `skills/siyuan` (6 files), `skills/siyuan-article-import` (6), `skills/siyuan-excalidraw` (2),
   `skills/siyuan-markdown` (2), `skills/_shared` (4: `UPSTREAM.md`, `UPSTREAM-LICENSE`, `__init__.py`, `siyuan_common.py`).
   `_shared`'s only importers were four siyuan scripts (`siyuan-article-import/scripts/{upload_image,import_article}.py`,
   `siyuan-excalidraw/scripts/upload_asset.py`, `siyuan-markdown/scripts/insert_image.py`); no test names `skills/_shared`
   (the `_shared` hits in `tests/` are test-function names such as `test_..._shared_checkout`).
3. B3 MOVE removal: every path in section A, `git rm -r` (82 files).
4. B4 Edits that go with them: `bin/skill-everywhere` third root, default
   `${OPS_ROOT:-$HOME/ops}/site-public-djbclark/skills` since the repair (first `site-djbclark`, section I), override
   `SKILL_EVERYWHERE_SITE`, read by `--all` and by name lookup after public and private, in both error texts and the header;
   tests in `tests/test_skill_everywhere_all.py`; `docs/skill-everywhere.md` (rule 8); `.gnu-tools-check-ignore` loses the `setup-modern-cli` comment and glob; `docs/threat-model.md:29` names
   `~/src/sudo-secretspec/skills/sudo-secretspec/SKILL.md`.
5. B5 Reference rewordings in KEEP files (commit 3209bfc): `bin/load-watch:22` (heavy-shim is site-djbclark's),
   `bin/load-watch:537-538` (the CI-offload skill's home `~/src/loopback-port-shim/skills/`, no longer the removed
   `skills/forgejo-ci` path); `claude/hooks/bash_habits_gate.py:75` (setup-modern-cli is a site-djbclark skill);
   `tools/acp-run/README.md:941` (bench.py is in the sipb-llms repo); `docs/mcp-servers.md:23,195`;
   `skills/fallback-chains/references/web-access.md:364`; `docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md:5-6`;
   `docs/disabled-skills.md:175-177` (dated note).

## C. Secrets scan, per path

Method: the brief's patterns (AWS `AKIA…`, private-key headers, `ghp_`/`gho_`, `xox[baprs]-`, `sk-…`, `password|token|secret|api[_-]?key`
followed by `:`/`=`, 40-hex, base64 runs over 32 characters outside fixtures) over every added and removed line of
`git log -p -- PATH` in the full clone (1,428 commits; the worktree itself is shallow, 66 commits, so it was not used), plus a
second pass for mixed-case alphanumeric runs of 16-39 characters (OVH-style keys). Values were masked in the scan output.
Then a read of every script and every flagged file at the current head, and a grep of all current files for e-mail
addresses, IP addresses and `sudo-secretspec get|run` lines.

**Result: no real credential in any path; nothing stopped.** Every pattern hit, explained:

1. `skills/ovhcloud-api`: `scripts/test_signing.py:17-19` and `SKILL.md` (commit a00afbbd) carry an AK/AS/CK triple. It is
   OVHcloud's own published documentation example (docs.ovhcloud.com "First Steps with the OVHcloud APIs" and the US support
   guide show the same three values, checked 2026-11-06), used against a local mock server. `password`/`secret`/`token` hits
   are prose and a `--secret 'OVH_APPLICATION_SECRET=… (AS):32'` prompt label.
2. `bin/codium-ai`: `CONTINUE_ANTHROPIC_API_KEY=$key` (a variable read at run time from `sudo-secretspec get`) and a comment.
3. `skills/diskfree`, `tests/test_bigteam_prune.py`: prose, a docstring, and a fake `alice:s3cr3t-token@nowhere.invalid` URL in a test.
4. `skills/firecrawl`, `skills/bottom-config`, `skills/setup-modern-cli`: long path and URL strings matched the base64 pattern.
5. Not credentials, noted: `bin/change-hermes-ssh-gate:4` names a Tailscale address (100.106.43.66) in a comment;
   `skills/greptile/SKILL.md:54` the operator's e-mail address in sample output; `bench/firecrawl/results/*.json` the
   self-hosted endpoint host name; `skills/aws-rules/SKILL.md:42` an IAM user name. site-djbclark's CLAUDE.md accepts host
   names and addresses; both repositories are public (`gh api`, 2026-11-06), so nothing became more visible.

| Path | Scan |
|---|---|
| `skills/gmail-search/`, `skills/aws-rules/`, `skills/terminus-kira/`, `skills/teach/`, `claude/commands/teach.md`, `skills/todo/`, `skills/report/`, `skills/greptile/`, `skills/coderabbit-feeder/`, `skills/barnowl/`, `tests/test_barnowl_skill.py`, `tests/fixtures/barnowl-1.10/`, `tests/fixtures/barnowl-master/`, `skills/book-to-kb/`, `bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`, `bin/change-hermes`, `bin/change-hermes-ssh-gate`, `tests/test_change_hermes_auto.py`, `tests/test_change_hermes_lock.py` | clean (no pattern hit) |
| `skills/ovhcloud-api/` | clean (6 hits, all documentation examples or prose, item 1) |
| `bin/codium-ai` | clean (2 hits, item 2) |
| `skills/diskfree/`, `tests/test_bigteam_prune.py` | clean (5 + 1 hits, item 3) |
| `skills/firecrawl/`, `skills/bottom-config/`, `skills/setup-modern-cli/` | clean (4, 2, 1 hits, item 4) |

## D. Shared-file lines for the merger (not edited here)

1. D1 `README.md`: skill rows 110 (`aws-rules`), 134-138 (`book-to-kb`, `gmail-search`, `barnowl`, `bottom-config`,
   `greptile`), 140-147 (`todo`, `terminus-kira`, `sipb-llm-bench`, `forgejo`, `forgejo-ci`, `hyades-docker`,
   `coderabbit-feeder`, `siyuan`). Line 147's `siyuan` row goes; the moved rows go or move to a "site-djbclark skills"
   pointer; the five unlinked rows become pointers to their source repos or go. Other moved names (`report`, `teach`,
   `firecrawl`, `diskfree`, `ovhcloud-api`, `setup-modern-cli`, `sudo-secretspec`) have no README row.
2. D2 `docs/skills.md`: 13-15 (the "five skill dirs here are themselves symlinks" note), 32, 62 (`teach`), 77
   (`terminus-kira`), 87-92 (`report`, `book-to-kb`, `gmail-search`, `barnowl`, `bottom-config`, `greptile`), 96 (`todo`),
   103-110 (`sipb-llm-bench`, `forgejo`, `forgejo-ci`, `hyades-docker`, `coderabbit-feeder`, `aws-rules`,
   `sudo-secretspec`, `setup-modern-cli`), 113 (`siyuan*` with `skills/_shared/UPSTREAM.md`). No rows found for
   `firecrawl`, `diskfree`, `ovhcloud-api`.
3. D3 `agents/claude/settings.json.tmpl`: drop 100-103 (`siyuan`, `siyuan-article-import`, `siyuan-excalidraw`,
   `siyuan-markdown` skillOverrides; the skills are deleted). Keep 106-108 (`terminus-kira`, `setup-modern-cli`, `teach`) and
   112 (`coderabbit-feeder`): the skills still exist under the site root and the keys are by name. Line 16
   (`~/.config/coderabbit-feeder/*`, the separate coderabbit-feeder repo) and 166 (`siyuan` MCP server deny) are not about
   the removed skills.
4. D4 `AGENTS.md:280` (review rule 3) names `bin/codium-ai`, now site-djbclark's `bin/codium-ai` (E11 rewrites the rule).
5. D5 `CHANGELOG.md` lines 20-22, 26, 100-101, 242-243, 269-270, 514, 542 name moved or deleted paths in past entries
   (history, `bin/changelog-fold` only). The one fragment for this slice is the merger's (`changelog.d/slim-2026-11.md`); a
   suggested line: "Removed: moved 15 site skills (aws-rules, barnowl, book-to-kb, bottom-config, coderabbit-feeder, diskfree,
   firecrawl, gmail-search, greptile, ovhcloud-api, report, setup-modern-cli, teach, terminus-kira, todo), `bench/` and
   `bin/{app-tamer-ab,heavy-shim,codium-ai,change-hermes,change-hermes-ssh-gate}` with their history to site-djbclark;
   unlinked the five peer-repo skills; deleted the vendored `siyuan*` and `skills/_shared`. Added: `skill-everywhere`
   reads a third root, `~/ops/site-public-djbclark/skills` (`SKILL_EVERYWHERE_SITE`); `--check --all` warns about an absent
   root; `--remove` of a gone skill matches all three roots; Grok Bot copies name the root they came from."
6. D6 `.github/workflows/test.yml`: no line names a moved or deleted test.
7. D7 `docs/queue.md`: 10 lines name moved or unlinked skills (exempt; E11).
8. D8 Hits left on purpose in files another slice of this wave deletes or moves (ruling 11): `skills/cow-workspaces/SKILL.md:62-69`,
   `bin/cow-pasture:81`, `tests/test_cow_pasture_deps.py:34` (E2), `skills/ralph-tui-orchestration/SKILL.md:260-263` (E2),
   `bin/ade-scan-state-doc:606`, `tests/test_ade_scan_state.py:3454-3458` (E2; a branch name `forgejo-ci-2026-10`, not the
   skill), `docs/apply-toolchain-prompt.md` (60 lines, E2 to history), `docs/ade-everywhere-*.md` (E2 to history),
   `zcode/commands/hyades-docker.md:2-7` (provider directory, E9; the skill name still resolves once relinked).
9. D9 Hits that are not references to the removed paths, left as they are: `tests/test_pr_policy.py:48-338` and
   `docs/pr-policy.md:37,93` (the Forgejo repository `djbclark/barnowl`); `docs/coding-factory.md:38`,
   `agents/codex/config.toml.tmpl:173` (the separate `djbclark/coderabbit-feeder` repository); `agents/codex/config.toml.tmpl:351`,
   `agents/hermes/config.yaml.tmpl:345`, `docs/mcp-servers.md:253-263` (the `siyuan` MCP server, not the skills);
   `docs/upstream-issues.md:960-983` (an upstream bug draft for zhiluop/siyuan-skills, still valid upstream);
   `tests/fixtures/context-now.txt` (a recorded `/context` listing); `tests/test_acp_dispatch_reap.py:143` (a slice name);
   `skills/autorename/workspace-layout.md:274` (a tab label); `skills/tell-coding-bot/SKILL.md:51` (already the
   sudo-secretspec repo path); `docs/skill-everywhere.md:84` (zcode command list naming `hyades-docker`); dated research
   reports `docs/claude-cache-cost-research-report.md:79,94`, `docs/software-factory-reviews/*-2026-10-19.md`,
   `docs/paseo-plugins-scan-2026-10-19.md:86`; `bin/load-watch:24,76` name the `forgejo-ci` skill, which still exists in
   loopback-port-shim.
10. D10 Name-resolved callers that keep working once the site root is linked: `skills/dialogue/SKILL.md:223`,
    `skills/research/SKILL.md:130`, `skills/retro/SKILL.md:22`, `bin/ade-retro:29` (the `report` skill);
    `skills/session-finder/SKILL.md:68,251` and `skills/session-finder/adapters/todo.py:1` (the `todo` skill's notes).

## E. Links and outside files for the operator (the Mac and two remote hosts; nothing was touched there)

Order after the final merge: (1) merge `slim-intake/2026-11` and pull the site-djbclark checkout; (2) `ade update`, which
removes the moved directories, so their links dangle; (3) `~/src/djbclark-ade/bin/skill-everywhere --all`, which relinks a
dangling link to its source in the new root (link mode replaces a dangling link). `ade update` checks only djbclark-ade's
own `skills/*`, so it does not do step 3. The site root is `~/ops/site-public-djbclark/skills` (the Mac checkout, per
site-djbclark's `bin/deploy_ops_release.py:26,419` and `AGENTS.md:18,160,189`; `~/ops/site-djbclark` is the July-era name);
`skill-everywhere --check --all` now says so in one warning line if that directory is absent.

Skill links (each is `<dir>/<name> -> ~/src/djbclark-ade/skills/<name>` in every installed target dir:
`~/.claude/skills`, `~/.agents/skills` (codex, goose, pi, zcode), `~/.gemini/antigravity-cli/skills`, `~/.copilot/skills`,
`~/.config/opencode/skills`, `~/.qwen/skills`, `~/.config/devin/skills`, `~/.cline/skills`,
`~/.local/share/skill-everywhere/skills` (Hermes), `~/.grok/skills`, `~/.omp/agent/skills`; Grok Bot holds a rendered copy
`~/agent-data/workflows/ade-<name>/` on its box):

1. E1 `aws-rules`: relink with `skill-everywhere aws-rules` against the site root.
2. E2 `barnowl`: same; also pastebin.xvm.mit.edu's `~/.ssh/authorized_keys` forced command names
   `$HOME/src/djbclark-ade/skills/barnowl/scripts/bo-ssh` (old SKILL.md:181): it breaks when pastebin's checkout updates;
   pastebin needs the site-djbclark checkout and the line repointed (the moved SKILL.md:181 now names
   `$HOME/ops/site-public-djbclark/...`, which assumes the Mac's layout on pastebin; adjust to pastebin's checkout).
3. E3 `book-to-kb`: two versions now sit in site-djbclark, the moved `skills/book-to-kb/` and the packaged tool's
   `tools/book-to-kb/skills/book-to-kb/` (a different text, about 215 `diff` lines), and `tools/book-to-kb/install.sh` links
   `<agent dir>/book-to-kb` at the tools copy, the same link name `skill-everywhere` makes. Pick one (operator batch);
   `skill-everywhere` leaves a link to the other copy alone and exits 1. Neither was deleted (`skills/README.md` says so).
4. E4 `bottom-config`: relink.
5. E5 `coderabbit-feeder`: relink.
6. E6 `diskfree`: relink.
7. E7 `firecrawl`: relink.
8. E8 `gmail-search`: relink (`~/.claude/skills/gmail-search` is named in `docs/mcp-servers.md:196`).
9. E9 `greptile`: relink.
10. E10 `ovhcloud-api`: relink.
11. E11 `report`: relink first among these (dialogue, research, retro and `bin/ade-retro` call it by name).
12. E12 `setup-modern-cli`: relink.
13. E13 `teach`: relink; also `~/.claude/commands/teach.md` links `~/src/djbclark-ade/claude/commands/teach.md`:
    relink to `~/ops/site-public-djbclark/claude/commands/teach.md` or remove (`ade update`'s command-link check covers
    djbclark-ade's `claude/commands/` only).
14. E14 `terminus-kira`: relink.
15. E15 `todo`: relink.
16. E16 the five unlinked skills (`sudo-secretspec`, `forgejo`, `hyades-docker`, `forgejo-ci`, `sipb-llm-bench`): their
    links point at `~/src/djbclark-ade/skills/<name>`, which no longer exists; `skill-everywhere` cannot relink them (their
    source repos are not roots). Relink each target dir by hand to the source repo
    (`~/src/sudo-secretspec/skills/sudo-secretspec`, `~/src/sipb-agent-skills/skills/{forgejo,hyades-docker}`,
    `~/src/loopback-port-shim/skills/forgejo-ci`, `~/src/sipb-llms/skills/sipb-llm-bench`), or install them with
    `npx skills add` from those repos. The ledger's note "operator relinks via the third root" (rows 236-281) does not hold.
17. E17 `siyuan*`: four dangling links to remove (`skill-everywhere --remove siyuan siyuan-article-import siyuan-excalidraw
    siyuan-markdown` works after the directory is gone); reinstall with `npx skills add zhiluop/siyuan-skills` where wanted.

Bin links and outside files:

18. E18 `~/.local/bin/swift` and `~/.local/bin/xcodebuild` -> `~/src/djbclark-ade/bin/heavy-shim`: relink to the site-djbclark
    `bin/heavy-shim` (until then the two names dangle and `swift`/`xcodebuild` by name fail on PATH).
19. E19 `~/.local/bin/codium-ai` -> `~/src/djbclark-ade/bin/codium-ai`: relink.
20. E20 `~/.local/bin/change-hermes` -> `~/src/djbclark-ade/bin/change-hermes`: relink; the Mac's `~/.ssh/authorized_keys`
    forced command for the Grok Bot box key names `/Users/djbclark/src/djbclark-ade/bin/change-hermes-ssh-gate` (the gate's
    own comment, now `/Users/djbclark/ops/site-public-djbclark/bin/change-hermes-ssh-gate` on the site side): repoint it; the box's own copy of `change-hermes` (remote mode) comes from
    wherever the box syncs it, check that it does not track djbclark-ade master only.
21. E21 `bin/app-tamer-ab`: any running `nohup app-tamer-ab run` keeps its old file open; a restart uses the new path.
22. E22 Grok Bot box: `/home/box/agent-data/shared/skills-sync/sync.sh` fetches djbclark-ade `origin/master` and renders
    `ade-<name>` copies; the 15 moved skills drop out of its set at the next sync unless it also reads site-djbclark.
23. E23 Done on the intake branch (3bc38c1), Mac step left: `bin/bg-offload` now finds `git-forgejo` and `forgejo-api` in
    `~/src/sipb-agent-skills/skills/forgejo/scripts` (the unlink removed the `~/src/djbclark-ade/skills/forgejo` path it used),
    and `cursor/home-agents.mdc:133` names the same path; `roles/watchdogd/templates/watchdogd.d/hermes-quota.toml.j2:19,28`
    run `/Users/djbclark/ops/site-public-djbclark/bin/change-hermes`. **Re-render the watchdogd role on the Mac** after the
    merge: the rendered `watchdogd.d/hermes-quota.toml` still names `/Users/djbclark/src/djbclark-ade/bin/change-hermes`, which
    `ade update` removes.
24. E24 The four moved test files (`tests/test_barnowl_skill.py`, `tests/test_bigteam_prune.py`,
    `tests/test_change_hermes_{auto,lock}.py`) run in no CI on site-djbclark: its workflows run only
    `tests/test_tendcf_consent.py`, and `just test` is local. The operator decides whether to add them to a workflow.

## F. Tests

1. F1 Targeted (`bin/pytest -q`): `tests/test_skill_everywhere_all.py tests/test_ade_update.py tests/test_gnu_tools_check.py
   tests/test_bash_habits_gate.py tests/test_load_watch.py tests/test_load_watch_admit.py tests/test_load_watch_chrome_alert.py
   tests/test_load_watch_churn.py`: 390 passed, rc=0. No remaining test imports a moved path (`grep` over `tests/`).
2. F2 Moved tests on the site-djbclark branch (`PYTHONPATH=. uv run --with pytest --with pyyaml --with ruamel.yaml pytest -q`
   on the four moved test files): 182 passed, 3 skipped, 8 failed, rc=1. The 8 failures are exactly the 8
   `tests/test_bigteam_prune.py` rows in `docs/slim/baseline.md` (network-remote cases that this container's git proxy
   settings change), so the move added none.
3. F3 Full suite (the baseline's command: `uv run --with pytest --with pytest-timeout --with pyyaml --with
   'agent-client-protocol>=0.9,<1.0' python -m pytest tests/ -q --timeout=120`): **158 failed, 10,398 passed, 49 skipped, 2,107 subtests passed, 2,793 s**, rc=1
   (baseline: 166 failed). Comparing failing test IDs with the baseline's full list: the 8 `tests/test_bigteam_prune.py`
   rows left with the file (166 - 8 = 158); `tests/test_local_review.py::test_a_hung_codex_is_killed_with_its_group_and_the_run_is_failed`
   (baseline) passed this time; one ID is new,
   `tests/test_relay_card_alert.py::TestCardAlert::test_a_message_that_waited_past_the_threshold_pings_once_naming_target_card_sender_and_message`.
   It is load-sensitive, not caused by this slice: another worktree's full suite ran at the same time (load 5-6 on 4 cores); a
   re-run of that file in this worktree under the same load failed 3 different tests; at load 4 it passed (26 passed, rc=0), and
   it passes at the pre-change revision f994bc08 (26 passed). The slice touches no relay code. **No new failure.**
   (`bin/pytest -q` over the whole tree first stopped at collection, `import file mismatch` between
   `tests/test_context_size_nudge.py` and `claude/hooks/handoff-tools/tests/`, which is why the baseline's command ran `tests/`.)
4. F4 `bin/gnu-tools-check .` on site-djbclark reports 23 findings in moved files (`skills/barnowl/scripts/bo`,
   `skills/bottom-config/SKILL.md:53`, `skills/diskfree/SKILL.md:67`, `bin/app-tamer-ab:36,42`,
   `bin/change-hermes-ssh-gate:7`); the same 23 were reported in djbclark-ade before the move (pre-existing, not fixed here);
   `skills/setup-modern-cli/*` is skipped by the carried ignore line.

## G. site-djbclark branch

`djbclark/site-djbclark` branch `slim-intake/2026-11`, head `3bc38c1884b1b7e16eb175fc1054d60f6df0974c` after the repair
(first push d2176af; both pushes verified with
`gh api repos/djbclark/site-djbclark/branches/slim-intake%2F2026-11`). No PR: site-djbclark's master is not protected
(`gh api .../branches/master/protection`: 404 "Branch not protected") and its CLAUDE.md lands by direct commit to master, so
the lead merges the branch (fast-forward from master f11d8218, which it contains). Open a PR from
https://github.com/djbclark/site-djbclark/pull/new/slim-intake/2026-11 if a review surface is wanted.

## H. Left undone, and why

1. H1 (resolved in the repair) The site root defaults to `~/ops/site-public-djbclark/skills`, not the brief's
   `~/ops/site-djbclark/skills` (section I).
2. H2 No PR opened on site-djbclark (section G).
3. H3 The shared files of section D (merger's), AGENTS.md, CHANGELOG.md and the template: not edited, per the brief.
4. H4 `skills/tell-coding-bot`, `skills/tell-chief-of-staff`, `bin/open-clean`, `skills/jevlike`: not touched (1d).
5. H5 `tests/test_bigteam_prune.py`: the ledger row 510 says DELETE (E6, with bigteam); the brief moved it with
   `skills/diskfree`, whose script it tests. It moved.
6. H6 `bin/load-watch:24,76` still name the `forgejo-ci` skill by name (it exists in loopback-port-shim); only the dead path
   at 538 was reworded. E5 trims load-watch and may drop the lines.
7. H7 The 23 pre-existing `gnu-tools-check` findings in moved files (F4) were not fixed: out of scope for a move.
8. H8 Correction: the site-djbclark merge commit f3a273f and djbclark-ade commit 3f35486 say six bin tools in their subject;
   it is 5 (`app-tamer-ab`, `heavy-shim`, `codium-ai`, `change-hermes`, `change-hermes-ssh-gate`). Both lists in the bodies,
   the site-djbclark CHANGELOG line and this report name the 5 correctly; the pushed commit is not rewritten.

## I. Review repair (2026-11-06, after the lead's BLOCK)

1. I1 site-djbclark 3bc38c1: the forgejo script paths, the watchdogd `change-hermes` path, the third-root sentence in three
   docs, `~/ops/site-public-djbclark` in every moved file, the `book-to-kb` note (section A, last bullet; section E23, E3).
   `bash -n bin/bg-offload` passes; `tests/test_watchdogd.py` 50 passed; `tests/test_bg_offload.py` times out at its first test
   (`test_a_held_targeted_run_is_offloaded_and_passes`, over 60 s) here, and the same test times out the same way at master
   f11d8218 in a scratch clone, so the timeout is not caused by this change.
2. I2 djbclark-ade `bin/skill-everywhere`:
   1. I2a default site root `${OPS_ROOT:-$HOME/ops}/site-public-djbclark/skills` (`SKILL_EVERYWHERE_SITE` kept);
   2. I2b `--check --all` prints `warning: skill root <dir> does not exist; its skills are not checked` once per absent root
      (stderr, exit code unchanged); link-mode `--all` stays quiet;
   3. I2c the `--remove` comment says three roots, and with the skill gone each link is matched against `<root>/<name>` for
      all three roots (`gone_srcs`), not only the public one;
   4. I2d Grok Bot copies: the `.skill-everywhere` marker's `source=` and the banner's link follow the root
      (`djbclark-ade`, `site-djbclark` with its GitHub URL, `site-private` with no link); a djbclark-ade skill renders byte
      for byte as before, so existing copies stay `copied`;
   5. I2e usage text: `--all` syncs public/private/site skills, `--check --all` warns per absent root.
3. I3 Tests: four new cases in `tests/test_skill_everywhere_all.py` (default root, absent-root warning, `--remove` of a gone
   site skill, Grok Bot provenance per root), and the fixture now pins `SKILL_EVERYWHERE_SITE` to an empty directory so a real
   `OPS_ROOT` cannot leak the operator's site skills into a run. `bin/pytest -q tests/test_skill_everywhere_all.py
   tests/test_ade_update.py`: 112 passed, rc=0. No full suite (per the lead).
4. I4 `docs/skill-everywhere.md`: the site root's path and default, the absent-root warning, `--remove` across three roots, the
   Grok Bot provenance. `docs/mcp-servers.md:23,195`: `~/ops/site-public-djbclark`.
