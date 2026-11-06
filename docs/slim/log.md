# Slim-down log

One entry per wave (PLAN.md F): what merged, what was lost on purpose, what the operator must do by hand. Appended by the slim lead; the operator pastes gate output (C7, C1) here when asked.

## Wave 0 (2026-11-06, lead session 01BvGHM3M9bXWXHwGGHz6Ctd, Fable 5.1 high)

Branch: the slim branch is `claude/determined-maxwell-uvddaz` (this session's designated branch), started at master e397dda (PR 295). `claude/cool-hopper-61dqzq` was PR 295's branch and is finished.

### Verified against the artifact

- **Baseline suite**: done, `docs/slim/baseline.md` (166 failed / 10,141 passed at master da6b2e7d in a container, 2026-11-06). Not re-run.
- **PR 289** (head `beb417db6e811080db6434eb788427743696a54c`): `pytest-linux`, `context-policy`, both Cursor checks `success`; marker APPROVE on that head; all 5 Codex and Cursor review threads `is_resolved: true`. Merge-ready; not merged (operator step, R2).
- **PR 291** (head `e95816ebf83b36d388243d142839134dba79b4f8`): same checks `success`; marker APPROVE on that head; all 4 Codex threads resolved. Merge-ready; not merged (operator step, R3). PR 293 is stacked on its branch and is already draft.
- **gitignore-aider**: branch `origin/gitignore-aider` @ 9946ed38 (djbclark's commit from the shared checkout, report F1). Adversary (Opus 5.5, high) APPROVE, 3 LOW. Opened as [PR 296](https://github.com/djbclark/djbclark-ade/pull/296) with the marker; the commit is unchanged. No changelog fragment (not user-visible, rule 10).
- **Rulings already carried out** (open-PR list, 2026-11-06): PRs 261, 292 and 294 are closed; 270, 290 and 293 are draft. Still open and non-draft, per R8's provisional rows: 194, 208, 227, 231, 254, 256, 260, 269, 281.
- **Tag `pre-slim-2026-11-06`**: points at master fb3b9deb (after PRs 289, 291 and 296, before any slim change). Created locally in the lead's checkout; pushing a tag is refused by the cloud proxy (`git push` and the refs API both), pushed by the operator with `gh api` on 2026-11-06 (verified: `refs/tags/pre-slim-2026-11-06` → fb3b9deb on origin).
- **J questions**: J1, J2, J2a, J2b, J2c, J3–J11 all carry an answer in PLAN.md; none is open.
- **R6 (batch-2 stragglers)**: the consolidated report (37 agents) covers it; its section H lists the two unverified herdr panes (w20:pM, w36:pB) and five agents named without a report (c987a634, d8891c91, 1d003359, 01BvGHLzKz, 7c54a88c-as-c688cc). J1 is answered (the three slices exited). Treated as satisfied for Wave 1 (reads only); the C7 drain gate before Wave 2 is where a late straggler still matters.

### Added on the branch

- `docs/slim/inventory.md`: a mechanical inventory (file, lines, whole-word reference count outside tests and history, tests naming it) of `bin/` (76 entries, 49,670 lines), `skills/` (65 entries), `tests/` (181 files, 86,584 lines), `docs/` and the other tracked areas. Input for the Wave 1 readers; no judgement in it.
- This log.

### Lost on purpose

Nothing yet.

### Merged by the lead (operator, 2026-11-06 19:35Z: "handle all merges now and in the future")

- PR 289 squash-merged at head beb417db (REST merge with `sha` pinned, the API form of `--match-head-commit`): master 734b7d9b.
- PR 291 squash-merged at head e95816eb: master 00839c48. Branch `claude/issue-279-linux-ports-1-sched` kept: PR 293 is stacked on it (R3).
- PR 296 squash-merged at head 9946ed38 after `pytest-linux` went green (Codex code and security reviews completed, no findings; Cursor approved): master fb3b9deb.
- The slim branch merged master in (merge commit, no rewrite of pushed history).
- Not done: deleting branch `claude/issue-284-ndc-oslo-ideas` (the proxy refuses ref deletion over the API and over `git push --delete`); operator step 3a below.

### Operator steps (in this order)

1. ~~Merge PR 289~~ done.
2. ~~Merge PR 291~~ done.
3. ~~Merge PR 296~~ done.
3a/3b. ~~Tag and branch deletions~~ done by the operator with `gh api` (2026-11-06; the cloud proxy drops tag pushes and ref deletions silently).
4. On the Mac, in the shared checkout: `cd ~/src/djbclark-ade && git status` (stop if another session's edits are there: their owner migrates them, order 9), then `git fetch origin && git checkout master && git reset --keep origin/master` (drops the local 9946ed38, now merged; `--keep` refuses rather than discarding uncommitted edits).
5. On the Mac: `cd ~/src/djbclark-ade && git worktree prune && git worktree list | wc -l` (89–115 entries at check-in, report I6; prune removes only entries whose directory is gone).
6. Approve or resize the W1 workflow (section H of PLAN.md) proposed in the lead's Wave 0 reply, then the ledger once it exists.

### Ruling taken (2026-11-06)

Operator: "Try to minimize the number of blocking things like this in the future." Applied as PLAN.md H: workflows start on the stated count; the ledger is posted, not awaited; Mac-only steps are batched per wave. W1 started at once (5 readers, 3-vote refute per KEEP row, 1 critic, cap 100 agents).

### Gate

**Wave 0 closed 2026-11-06**: tag on origin, three merges done, slim branch carries master fb3b9deb. Still open from the operator list: shared-checkout reset and `git worktree prune` (now in the Wave 2 batch, step 7). Wave 1 (reads only, no merge) starts on the W1 approval; it does not need the tag.

## C7 drain gate (operator output received 2026-11-06 ~22:05Z; raw file kept in the lead's scratch, not committed: 5,650 lines, mostly job listings)

1. herdr sleeper: ONE pane asleep, `w1:p1` (claude, slept 2026-10-08T21:28, title "Title"); nothing orphaned; the journal's last event is 2026-11-01. **Waiver asked** (default: waived; a month old, its transcript stays resumable with `claude --resume`).
2. acp-dispatch records: 203 job dirs listed; the `.done` marker sits beside each report file, not in `jobs/`, so the listing cannot show resumability; `launchctl list | grep acp-dispatch`: none; `pgrep acp-run|acp-dispatch`: none. **One follow-up command asked** (unfinished records without a `.done`).
3. worktrees: 116 entries; 74 dirty lines, of which the `.claude/settings.json` / `.cursor/hooks.json` pairs in ~10 worktrees are the graft hook-path rewrite (report F5, noise). Substantive: `djbclark-ade` shared checkout `.aider*` untracked (gitignored since PR 296); `djbclark-ade-checkpoint-d1-wt` (PR 290's D1 probe, parked); `djbclark-ade-failover-tmp-sweep-wt` (edits to `failover.py`, `skillopt-night`, both DELETE); `djbclark-ade-bridge-guard-wt` (an untracked handoff doc); `djbclark-ade-route-scope-wt` (F4). cow pastures: aiuse and cmdb ones, outside this repo. **Waiver asked for the four** (default: waived; none is edited by Wave 2).
4. relay: 320 delivered, 8 failed, 21 expired, 45 cancelled; none non-final. PASS.
5. bigteam inboxes: none. PASS.
6. launchd: deadline-sweep, pr-policy, load-watch loaded (PASS); also loaded and to be booted out at the final merge: skillopt-sleep (E10), rumination-watch, session-history-update, context-budget, routing-recalibrate (E5), claude-fleet-governor (exit 10) and claude-quota-guard (exit 1) (E7), acp-dispatch-reap (E6), watch (Wave 3b), opencode-cpu-watch, codexbar-cpu-watch (E9 Wave 3 part), acpdispatch.n2maskfix.reset (one-shot, exited). No acp-run process.
8. aiuse: the output was cut at 200 lines (the script's `head`); only the antigravity account was read (Gemini weekly exhausted, Claude/GPT weekly exhausted, Argon 98 %). **Full account list asked.**
9. `bg`: `~/ops/site-private/bin/bg` is a symlink to `../../site-public-djbclark/bin/bg`; site-public owns it. PASS.
10. adhoc `adversary-pr254f`: record modified 11:04 after its lock (10:47); no launchd job. PASS.
12. both `~/ops/site-djbclark` and `~/ops/site-public-djbclark` exist; E1's default `site-public-djbclark` is right either way. PASS.

Follow-ups (operator, 2026-11-06 ~22:20Z): C1 `UNFINISHED` scan over every job record printed nothing → item 2 PASS. C2 `aiuse --json` accounts: antigravity/agy (subscription), bedrock PAYG (API), claude (subscription), codex prolite, cursor Ultra, grok SuperGrok, grok-bot plan, opencode-go ×3 (plan "go"), pi ("Last 30 days", an API pool), sipb (unknown), zai lite via zcode. **No omp account.**

J2 pool audit (lead's reading, ruling 10 / R2-12..15): Paseo providers that each carry a paid plan: claude, codex, cursor, antigravity, opencode (opencode-go, sipb; zai lite folds into it when zcode goes); the grok CLI stays as the only SuperGrok route (no Paseo grok provider known); grok-bot stays with peer-link (E9j). Retire in Wave 3's E9 part: pi (API pool, not a plan), zcode (fold into opencode's zai route), omp (no plan in aiuse; the pi→omp port is moot), glm-acp-agent (not listed). Operator (2026-11-06): omp uses Codex and Claude **API credits**, pools distinct from the claude and codex subscriptions and not tracked by aiuse → **omp KEEP** (a paid pool reachable only through it); pi retires and its OpenAI API pool folds into omp (the pi→omp port of `pi/extensions/subagent` stands, Wave 3 E9 part). Small-context provider (R2-15): none survives → `web-get`, `web-digest*`, `firecrawl-router` go in Wave 3's E9 part. Cursor stays (R2-14).

Waivers given by the operator 2026-11-06 ("B waive both"): the sleeping pane w1:p1 and the four dirty worktrees. **C7 PASSED.** E2 may merge after E1; E3/E4/E6 are clear of this gate.

## Wave 4 research filed (2026-11-07 ~00:30Z)

- `docs/slim/research/wave4-2026-11-06.md`: Claude Code 2.1.319 and Paseo 0.15.3 run by the researcher; GitHub changelog read. **E8's Action changes trigger**: `pull_request_target` is blocked by default in public repositories from 2026-12-02 (brownouts 2026-11-09 and 2026-11-16) and its ref is now the default branch, so the Action runs on `workflow_run` (after the `pull_request`-triggered `Tests` workflow) plus `workflow_dispatch -f pr=N` for body-edit re-runs; the App-minted status, the ruleset's `integration_id` pin and the `master`-only environment stand (the environment is reachable by `workflow_run`, whose ref is the default branch, and not by any `pull_request` run). **E6**: no per-run tool set or MCP config through Paseo, no `--prompt-file`, `--output-schema` not with `--no-wait`, Claude's default mode is `auto`: the Claude restricted modes stay on `bin/review-launch`, other providers map `--perm` to a verified provider mode, prompts are argv pointers to the brief. **E7**: `paseo provider ls --json` (`loading` first; `modes` are labels), `paseo provider models`, `paseo usage ls --json` with non-`available` reports as unknown. Rulings: `docs/slim/ledger-rulings.md`, "Wave 4 research".
- The researcher's "four read tools" became `{Read, Grep, Glob, StructuredOutput}` (`--json-schema` injects the last; `LS` is not a tool in 2.1.319); bypass is silently downgraded to acceptEdits, so the launcher refuses it itself.

## Wave 3 merges (2026-11-06 ~23:50Z onward)

- E5 merged at 8c05930 (worktree branch `worktree-agent-af59a42109b4c5868`, head 2e15726, APPROVE after one repair round: the ancestor walk now stops at the agent's own CLI, archived agents are listed out with `paseo ls -g --background`, loose heavy work reaches the operator). Conflicts: docs/scheduling.md (plist count sentence combined), tests/test_session_history_adapters.py (both E9's and E5's removals taken; E3 deletes the file). Merger's lines and fragment at 90982fa.
- E4 merged at aca3a9d (worktree branch `worktree-agent-a1901adc45a1860e6`, head c9319dd, APPROVE after two repair rounds). Conflict in bin/claude-quota-guard (E9's agy removal and E4's self-slash removal combined). Merger's lines (README helm/autorename rows, the commands-wrapper row, two docs/skills.md rows, the autorename hook object in the template) and fragment lines in the next commit. The live `~/.claude/settings.json` hook line for `skills/autorename/autorename_nudge.py` joins the C2 operator edit.
- E3 merged at 2324512 (worktree branch `worktree-agent-a4772e28ffb7daa78`, head ea150e9, APPROVE after one repair round plus the `closed`-is-sendable follow-up). Conflicts: nine modify/delete cases resolved as deletions; bin/load-watch and tests/test_load_watch.py took E5's version (E3's relay-channel edits were moot once E5 removed that channel). E3b done in the same step: `fleet.py`, `where.py`, `prompt_line.py` and the six `tests/test_fleet_*.py` deleted (a63d287); merger's lines and fragment at the next commit. nix2cf#6 merged at bf2842e (Codex clean on the repaired head; its CI green); tendcf#43 merged at 069958d (Codex clean on 405078b, four VM jobs green). Both C3 AGENTS.md PRs are landed.
- Order kept: E5 before E3 (rumination-watch); E3b (fleet.py, where.py, nested_pty.py, tests/test_fleet_*.py, test_nested_pty.py) after E3; E10 last.
- Targeted tests of E4+E5 on a detached copy of the merged head: `/tmp/slim-t2.log`.

## Wave 2 closed; Wave 3 merging (2026-11-06 ~23:00Z)

- E9 merged at 4ac820f (worktree branch `worktree-agent-a469de6c7fc476388`, head b525ba4, APPROVE after two repair rounds); conflicts with E1/E2 resolved in docs/model-routing.md (E2's "removed" rows kept, E9's dropped rows gone), skills/model-routing/SKILL.md (both notes combined), tests/test_skill_everywhere_all.py (E1's five tests kept, the pi test dropped), tools/acp-run/README.md (E9's trimmed paragraph). Merger's lines at aed8f2f: three AGENTS.md pi doc rows, rule 3's zcode-key-auth/codium-ai note; E9's fragment folded into the branch fragment. changelog-fold and ade-template-check clean. Full suite on a detached copy of aed8f2f running (`/tmp/slim-verify-w2.log`).
- Ruling (ledger-rulings.md, "Wave 3 merge gates re-read"): Wave 3 slices merge to the branch on APPROVE; the day-of-verification and C3 per-file gates move to the final PR's checklist; C3 migrations start now in parallel.
- C3 scan (2026-11-06 ~23:20Z, clones attached with push access: frdminc/tendcf, frdminc/nix2cf, djbclark/plektra-djbclark, djbclark/paseo4herdr, djbclark/aiuse; GitHub code search for paseo-runner and sudo-secretspec): **Plektra, paseo4herdr, paseo-runner and sudo-secretspec contain no file naming relay.py or acp-dispatch** (report I4d/I4e/I4g described those agents' session usage, not repo files): no edit needed, nothing to waive. tendcf and nix2cf: AGENTS.md only (frontier route 3 via the retired agy TUI, the weekly `acp-run agy --info` recheck, acp-dispatch lines that the shim keeps). site-djbclark `bin/fleet-watch`: relay `--sweep/--pending/--no-ack` calls. aiuse: `src/aiuse/collectors/acp_usage.py` reads `~/.local/state/acp-run/` JSONL turn logs (plus nine files naming acp-run/acp-dispatch): a **Wave 6** item for the follow-up PR that removes acp-run (the shim keeps the logs for one cycle); order 11 applies to aiuse. A Sonnet writer is preparing the tendcf, nix2cf and fleet-watch edits on `slim-c3-2026-11` branches; the lead opens the PRs (J2b).
- C3 edits done (2026-11-06 ~23:40Z, Sonnet writer, lead's J2b grant): [frdminc/tendcf#43](https://github.com/frdminc/tendcf/pull/43) and [frdminc/nix2cf#6](https://github.com/frdminc/nix2cf/pull/6) (AGENTS.md only: frontier route 3 via `paseo run --provider antigravity`, the Carbon recheck via `paseo provider models antigravity`, a dated shim note on acp-dispatch; the antigravity full-access mode id is unverified and the text says so); the lead merges them after their CI. site-djbclark `bin/fleet-watch` migrated to the shim on `slim-intake/2026-11` @ d6a46d0d (the ack-overdue step and `tests/test_fleet_watch_ack.py` removed with the outbox; sends read the shim's exit code, non-Paseo targets skipped with a log line; `test_fleet_watch_upstream.py` 27/27 with GNU shims). Remaining C3 items: aiuse (Wave 6), the operator-side state scripts lander/feeder (J11, retired). CFEngine's fork (`djbclark/core` @ b0f6da2, read-only clone 2026-11-06 ~23:55Z): no file names cfenginewatch, bin/watch, fleet-watch, relay.py or acp-dispatch; the CFEngine watcher's registration lives only in site-djbclark's fleet-watch, so C3's I4b needs no repo edit. The watch family is therefore clear to delete in Wave 3b.
- Lesson: a test run in the main checkout was disturbed by a merge made there mid-run (one writer at a time); from now on every test run uses a detached worktree (`scratchpad/slim-verify`, `slim-t1`).
- E10 writer started from aed8f2f. E3 (845735b) and E5 (4db4047) under review; E4 approved at c9319dd, merges after E5 and E3 (order: E5, E3, E4; E3b after E5).

## Wave 2 merged (2026-11-06 ~22:40Z)

- E1 merged at 826da46 (worktree branch `worktree-agent-a4b7b27ccf9493f12`, head 6dc2093, APPROVE after one repair round); site-djbclark `slim-intake/2026-11` at fee6ac5 (pushed; direct-commit repo: the lead merges it to master at the final merge, naming the five files edited outside the moved set: AGENTS.md, bin/bg-offload, claude/README.md, cursor/home-agents.mdc, roles/watchdogd/templates/watchdogd.d/hermes-quota.toml.j2).
- E2 merged at d756030 (worktree branch `worktree-agent-ad5e8b64e18a63e8b`, head 35e03c1, APPROVE after one repair round; C7 passed with the operator's waivers). Conflicts resolved: `.gitignore` keeps both appended blocks; `.gnu-tools-check-ignore` keeps the history path only (E1 removed the setup-modern-cli line).
- Merger's lines applied at 1ac230b: 18 README rows, 21 docs/skills.md rows, 10 template skillOverrides and the siyuan MCP entry and the jev hook object, 2 AGENTS.md doc-table rows (jev, agent-sleep), the README numbered-doc items 4 and 13, the ralph-tui paragraph; fragment `changelog.d/claude-determined-maxwell-uvddaz.md` (PR number `#0` until the final PR exists). Checks: changelog-fold --check 0, ade-template-check 0, instruction-lint 0 (3 retired-term warnings in AGENTS.md, E11's), gnu-tools-check 39 findings (fewer than base). Targeted tests of both slices run on the merged branch (log `/tmp/w2-merge-tests.log`).
- The c688cc check-in report (answering for 7c54a88c) landed as `docs/checkins/2026-11-06-c688cc.md` from the operator's upload.
- E9: writer at b525ba4 (two repair rounds; eight test files green bar the baseline detached test); confirm pass running. Merges after APPROVE, with its fragment folded into the branch fragment.
- Ruling R2-23 corrected (E5 found it): `scripts/github-ci-run` has a live caller, site-djbclark `bin/bg-offload`; KEEP.

### Operator batch for the final merge (Wave 6), growing: from the E1 and E2 reports (full detail in `docs/slim/reports/wave2-E1.md` section E and `wave2-E2.md` section E)

1. Merge site-djbclark `slim-intake/2026-11` into its master (lead), pull it on the Mac, then `ade update`, then `~/src/djbclark-ade/bin/skill-everywhere --all` (relinks the 14 moved skills from the new root; `report` first, dialogue/research/retro call it by name).
2. Relink by hand the five unlinked skills from their own repos (sudo-secretspec, forgejo, hyades-docker, forgejo-ci, sipb-llm-bench) or `npx skills add` them; `skill-everywhere --remove siyuan siyuan-article-import siyuan-excalidraw siyuan-markdown`; run `tools/book-to-kb/install.sh` in site-djbclark to repoint the `book-to-kb` links.
3. Bin links: `~/.local/bin/{swift,xcodebuild}` → site-djbclark `bin/heavy-shim`; `~/.local/bin/codium-ai`, `~/.local/bin/change-hermes` → site-djbclark `bin/`; `~/.claude/commands/teach.md` → site-djbclark `claude/commands/teach.md`; remove `~/.local/bin/{jev,seat-name,ade-scan-state,cow-pasture}` and any `opencode-ralph-tui*` copies.
4. Forced-command keys: the Mac's `authorized_keys` line for the Grok Bot box key names `change-hermes-ssh-gate` by the old path (→ `/Users/djbclark/ops/site-public-djbclark/bin/change-hermes-ssh-gate`); pastebin's `authorized_keys` names `barnowl/scripts/bo-ssh` by the old path (pastebin needs the site-djbclark checkout). Re-render the watchdogd role (hermes-quota template now names the site path).
5. Grok Bot box: its skills sync reads djbclark-ade `origin/master` only; the moved skills drop out of its set unless it also reads site-djbclark.
6. `~/.claude/settings.json`: remove the `jev_effort_hook.py` hook entry and `~/.claude/hooks/jev_effort_hook.py` (C2 list, growing).
7. `herdr plugin unlink djbclark.herdr-sleeper` (form unverified against herdr's CLI; the link was `herdr plugin link plugins/herdr-sleeper`); `cow remove` the pastures under `~/.cow/pastures` when done.

## Wave 2 progress (2026-11-06, evening)

- E2: writer done (full suite: 164 failed vs 166 baseline, zero new by id); review BLOCK (stale ignore path, references in kept docs, edits to two E1 files) → repaired → APPROVE at 35e03c1. Merge waits on the C7 paste. Ruling: E1 merges before E2.
- E1: writer done (82 files moved with history to site-djbclark `slim-intake/2026-11`, secrets scan clean, suite no new failure); review BLOCK: two live site-djbclark callers missed (`bin/bg-offload` forgejo scripts, watchdogd `hermes-quota` template calling `change-hermes` by the old path), root default should be `site-public-djbclark`; repairs in progress on both branches (site edits under the J2b grant).
- E9: writer done (77 files, −9,245 lines; batch tests green vs baseline); review running with the full suite.
- Operator D1 done 2026-11-06: shared checkout reset to origin/master (`## master...origin/master`), `git worktree prune` left 119 entries (stale ones still have directories; a later sweep); one untracked file there, `docs/checkins/2026-11-06-c688cc.md`, is a check-in report never committed: asked for it as an upload, to land in `docs/checkins/`.
- Operator D2 ("keep the better one"): `tools/book-to-kb` stays (the packaged tool with bin/, docs, installer, licence and a semantic index; touched on master this week); the moved `skills/book-to-kb` was deleted on `slim-intake/2026-11` at 86832d2 by the lead.
- E3 (Wave 3): writer done at 99a7ccb+ (shim 166 lines reading `.status`; 52 files / 22.4k lines deleted; claude_identity.py in bin/; full suite 166 failed with the three new ones resolved, one as a strict xfail: `bin/rumination-watch` breaks on the shim, so **E5 merges before E3**). Ruling sent: targets resolve by id or shortId only (no titles). Found: `site-djbclark/bin/fleet-watch` calls relay with `--sweep/--pending/--no-ack` and breaks when the shim goes live: an edit in Wave 3b with the watch family (site-public, J2b grant). Review after the id-only change.
- Wave 3 started early: E3 (Opus), E4 (Sonnet; done, bin/watch default patch pending, review running), E5 (Opus) writers; E10 after the Wave 2 merges.

## Wave 1 (started 2026-11-06 20:05Z)

W1 round 1 done 20:40Z (99 agents, 11.1M tokens, 39 min): 627 rows, 263 KEEP rows, 31 voted (cap 100), 2 refuted (`failover.py`, `bin/pytest`), 50 rows disagree with the plan, 119 unlisted paths, critic: 12 missing-path groups, 27 inconsistencies, 9 uncovered outside dependents, 15 questions (answered in `docs/slim/ledger-rulings.md`). Round 2 done 21:35Z (282 agents in all, 19.5M tokens): all 92 code KEEP rows voted, 12 refuted (8 are reference lines in kept files that the plan already rewrites; new: the six vendored `ade-paseo*` skills are REPLACE in Wave 3 by Paseo's shipped skills, the redundant `claude/commands/*` wrappers are DELETE, `session-history.py` and its plist DELETE, `npm_metadata.py` DELETE). Ledger v2 with a Lead column; the critic's 26 round-2 questions are answered as R2-n in `docs/slim/ledger-rulings.md`. Wave 1 closed; the ledger is posted, not awaited.

Added to the operator batch: line 10 (adhoc `adversary-pr254f` record exited?).

W1 as designed: 5 Sonnet readers (bin, skills, tests, docs, outside), dedup by path, 3-lens refute per KEEP row, 1 Opus critic; cap 100 agents. The ledger (`docs/slim/ledger.md`) is written by the lead from its output and posted, not awaited (H ruling).

Facts found while preparing Wave 2 (so a slice does not trip on them):

- `git filter-repo` was not installed in this container (PLAN.md D12 recorded a40bce5 from the previous session's container); installed here with pip, version a40bce5.
- tendcf and nix2cf live at `frdminc/tendcf` and `frdminc/nix2cf` on GitHub (push access); Plektra at `djbclark/plektra-djbclark`, paseo4herdr at `djbclark/paseo4herdr`, site-djbclark and site-private at `djbclark/`. All five C3 repos are attachable from the cloud (J2b), as is the E1 destination.
- PLAN.md C7 names `bin/cow-pasture ls` and `acp-dispatch ls`; neither exists. `cow-pasture` has create/remove/scrub/trust/check/untrust and reads `cow list --json`; acp-dispatch has check/resume/wait/tell/outcome, and its records are the files under `~/.local/state/bigteam/*/jobs/`. The batch below uses the real commands.

### Operator batch for Wave 2 (the C7 drain gate; run on the Mac, paste the output here as one block)

Nothing in E2, E3, E4 or E6 merges before this is pasted. Items 1-6, 8-10 and 12 are read-only and are one script (the lead sent it in chat on 2026-11-06; it writes `~/slim-c7-<date>.txt`); 7 changes state; 11 is a decision.

1. Sleeping herdr panes holding a Claude session: `~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper list` and `... log | tail -20`. Expected: nothing sleeping, nothing orphaned.
2. Resumable acp-dispatch records: `ls -la ~/.local/state/bigteam/*/jobs/ | grep -v '\.done'`; `launchctl list | grep -i acp-dispatch`. Expected: every record has a `.done`, no launchd job.
3. Worktrees and pastures: `git worktree list` plus `git -C PATH status --short` per path; `cow list --json`. A dirty one is its owner's to migrate (order 9) or yours to waive by name (report F4, F5, F7).
4. Queued relay acks: `relay.py --pending --summary`. Expected: empty, or each of the eight ids in report I3 retired with `relay.py --retire ID --reason "slim-down C7"`.
5. Bigteam inboxes: `find ~/.local/state/bigteam -name 'inbox*' -type f -newer ~/.local/state/bigteam`. Expected: none.
6. C1 live jobs and processes: `launchctl list | grep com.djbclark`; `pgrep -fl 'acp-run|acp-dispatch'`. Expected: deadline-sweep, pr-policy, load-watch listed; no acp-run process.
7. Wave 0 leftovers (state-changing, by hand): in the shared checkout `git status` (stop on another session's edits), then `git fetch origin && git checkout master && git reset --keep origin/master`; then `git worktree prune`.
8. J2 pool audit input (ledger ruling 10): `aiuse --json`, so the lead can settle which paid plans are reachable only through omp or opencode before E9's Wave 3 part.
9. `bg`'s live path (ruling 14): `ls -la ~/ops/site-private/bin/bg ~/ops/site-public-djbclark/bin/bg`.
10. The adhoc adversary record (report B1b): `ls ~/.local/state/bigteam/adhoc-2026-11-02/jobs/`; `launchctl list | grep adversary-pr254f`.
11. Decision: site-djbclark has two `book-to-kb` skills after E1 (`tools/book-to-kb/skills/book-to-kb` with its own `install.sh`, and the moved `skills/book-to-kb`): which wins; the other is deleted there in a follow-up.
12. Checkout name: `ls -d ~/ops/site-public-djbclark ~/ops/site-djbclark` (E1's third skill root defaults to `site-public-djbclark`).

Facts from the site-djbclark clone (2026-11-06, `djbclark/site-djbclark` @ f11d8218, attached with push access as the E1 destination):

- `bin/fleet-watch` is in site-djbclark (`bin/fleet-watch`, beside `bin/bg`, `hook-deadline`, `hermes-ping`); PLAN.md C3's "home unverified" is settled: it is site-public, not site-private, and AGENTS.md's doc-table row pointing at a local `bin/fleet-watch` is wrong (E11 fixes the row).
- `skills/README.md` there says the hub layer was retired on 2026-10-14 ("nothing should link here any more"; public skills live in djbclark-ade, private ones in site-private). J2a makes that directory a third `skill-everywhere` root again for the moved skills, so the E1 intake branch rewrites that README in the same change, and `bin/skill-everywhere` gains the root (E1 owns that one edit, PLAN.md E10).
