# Slim-down check-ins, 2026-11-06: consolidated

Source: 34 report files in `~/.local/state/bigteam/lead-2026-11-02/checkins/` (copied from the pushed `checkin/*` branches of djbclark/djbclark-ade), the request `checkin-request-2026-11-06.md`, `pending-decisions.md` and `checkin-done.txt`. Facts come only from the reports. Where two reports disagree, this file says so.

## A. Summary

A1 Reports in: 37. Six of them (w20:p0, w20:p12, w20:pS, w20:p11, c688cc, ed6863c7) arrived while this file was being written; they are the last six rows and D32 to D37. Stragglers: 2 herdr panes (section H). djbclark's answers to the held decisions are in E9.

A2 Pushed SHAs come from `checkin-done.txt` and the agents' replies. 7c58015b (HELM LEAD) pushed `checkin/7c58015b` at `4508666c`.

A3 Recommendation codes follow request section f: (i) stop and discard, (ii) stop after landing what is committed, (iii) finish first, (iv) continue unaffected.

| short id | agent (harness/model, tab or pane) | task | recommendation | branch@sha |
|---|---|---|---|---|
| 01BvGHLy | Claude Code cloud, claude-opus-5-5, cloud session | issue 279 Linux ports | (ii) for PR 291; nothing else is used by Linux scheduling | checkin/01BvGHLy@de095986 |
| 01BvGHLzD4 | Claude Code cloud, claude-opus-5-5, cloud session | issue 284, PR 289 | (ii) merge 289, then fix 3 findings | checkin/01BvGHLz@e59258a0 |
| 01BvGHM3 | Claude Code cloud, claude-opus-5-5, cloud session | issue 278 checkpointing, PR 290 | (ii) Paseo-native, does not overlap the split | checkin/01BvGHM3@b7a99a0d |
| 042d0c8d | omp, claude-sonnet-5-5, relay "v0-release-pt" | sudo-secretspec rollout | (iv) work is outside djbclark-ade | checkin/042d0c8d@c5c4227c |
| 0b68fe51 | Pi, gpt-6.1-sol, Dann 7 worker | techno-euphora SIGINT probe | (ii) only the report needs publishing | checkin/0b68fe51@52bd4dfd |
| 0dc43dbd | Cursor, claude-opus-5-5 high, Paseo | pr-policy and TUI retirement | (ii) landed; fold retirement into the split | checkin/0dc43dbd@3dd9fcd1 |
| 1057582a | omp, claude-sonnet-5-5, Paseo | Paseo plugin sync, paseo-runner | (iv) none of the work is in djbclark-ade | checkin/1057582a@98dcf89d |
| 19ece915 | Pi, gpt-6.1-sol, Paseo | HELM LEAD continuation | (i) for the role; keep recovery files | checkin/19ece915@6b4f6d87 |
| 1e61c979 | omp, claude-opus-5-5, tab "LEAD paseo-only rearch" | djbclark-ade lead, D1 | mixed: (ii)/(iii)/(iv) per item | checkin/1e61c979@469d95cf |
| 23adbb25 | Cursor, Composer, Paseo | aiuse PR 47/48, v4.0.1 | (ii) the aiuse work has shipped | checkin/23adbb25@1c72994b |
| 2507bcbf | omp, claude-sonnet-5-5, Paseo tab | dann-workspace-accent plugin | (iv) work lives in a separate repo | checkin/2507bcbf@75aef78d |
| 2b4437d2 | Claude Code, Sonnet 5.5, Paseo 63c48307 | paseo4herdr adapter | (iv) did not edit djbclark-ade | checkin/2b4437d2@7cb1689a |
| 32779db2 | Claude Code, claude-sonnet-5-5, herdr pane w20:pE | Finder/mds CPU, PR 231 | (ii) or (i) PR 231; (iv) everything else | checkin/32779db2@fe19dfc6 |
| 3846a46e | omp, claude-sonnet-5-5, Paseo | rename one Paseo workspace | (iv) no work in flight | checkin/3846a46e@0974a4a0 |
| 3ac46de6 | omp, claude-opus-5-5 high, tab "tendcf nixos stage D" | tendcf lead | (iv) if the acp-dispatch CLI stays | checkin/3ac46de6@c5874180 |
| 501a7e0d | Cursor, Claude Opus 5.5, Paseo | TUI consolidation plan, PR 283 | (ii) finished; work superseded by PR 288 | checkin/501a7e0d@ea5d1399 |
| 6eb6d3f6 | Codex, GPT-6.1 Sol, "watch cfengine 1f" | CFEngine upstream watcher | (ii) report only; keep watching | checkin/6eb6d3f6@2b83a414 |
| 7c58015b | omp, claude-opus-5-5, "HELM LEAD" | fleet lead | (ii) land PRs 270 and 294 | checkin/7c58015b@4508666c |
| 7c96a0ca | Claude Code, Sonnet 5.5 high, Paseo seat 18b6d528 | autorename fix, PR 259 | (iv) already merged | checkin/7c96a0ca@a745b441 |
| 9e5b46d1 | omp, claude-sonnet-5-5 high, Paseo | PRs 252 and 254 | (ii) PR 254 is merge-ready | checkin/9e5b46d1@591dcb1c |
| ac95a703 | Pi, gpt-6.1-sol, Paseo | PR 254 backtick repair | (ii) the lead owns the merge | checkin/ac95a703@7e58919a |
| ba920539 | Pi, gpt-6.1-sol, Dann 7 worker | techno-euphora SIGINT fix | (ii) parent already committed the fix | checkin/ba920539@803dfcdd |
| bcff073a | Codex, gpt-6.1-sol medium, "watch paseo 1j" | Paseo upstream watcher | (ii) report only; keep watching | checkin/bcff073a@1d106d75 |
| c3cbe51a | omp, claude-sonnet-5-5 high, Paseo "key-remap-pt" | Plektra device checks | (iv) did not edit djbclark-ade | checkin/c3cbe51a@4cf3913e |
| ce04246a | Cursor, Grok 4.7, Cursor | Claude Cloud skills research | (iv) did not edit djbclark-ade | checkin/ce04246a@dc5abc31 |
| ebd6ed1a | Pi, openai/gpt-6.1-sol high, Paseo | fleet-migrate tool (WIP) | (ii) preserve the branch, do not merge it | feat/fleet-migrate@4abbb824 |
| f111c672 | omp, claude-opus-5-5, Paseo (workspace ~) | Coding bot link, PR 269 | (i) variant: re-home into peer-link | checkin/f111c672@07b655c1 |
| ff08899e | Cursor, Claude Opus 5.5, "watch load t" | load watcher | (iv) watcher makes no repo edits | checkin/ff08899e@a6a0748c |
| w20:pN | omp, claude-sonnet-5-5, herdr pane w20:pN | aiuse features | (iv) separate repo, all pushed | checkin/w20-pN@903e0aa1 |
| w20:pQ | omp, claude-sonnet-5-5, herdr pane w20:pQ | opencode bridge guard, PR 281 | (i) or (iii): depends on whether opencode support stays | checkin/w20-pQ@04cabc2d |
| w38:p8 | omp 18.16.0, claude-sonnet-5-5, label w38:p8 | Pi first-class in ADE | (iv) everything is merged | checkin/w38-p8@25664796 |
| w20:p0 | Cursor Agent, Composer (Auto), herdr pane w20:p0 | dsh setup, retire relays | (ii) ops commit landed; report only | checkin/w20-p0@270dd593 |
| w20:p12 | Cursor Agent, Composer (Auto), herdr pane w20:p12 | relay answers only | (ii) report is the only commit | checkin/w20-p12@ea7a2a4e |
| w20:pS | Codex, model not exposed, herdr pane w20:pS | issue 278 recovery architecture, PR 282 | (ii) already merged, docs only | checkin/w20-pS@76749bc7 |
| w20:p11 | Cursor, Composer, herdr pane w20:p11 | OpenCode `/hand` YAML fix, PR 286 | (ii) already merged | checkin/w20-p11@08eb4915 |
| c688cc | Claude Code, claude-haiku-4-5, Paseo "Herald summary" df4a2ed6 (answered the request sent to 7c54a88c) | one Herald message on tendcf Q10 | (iv) no repo changes | checkin/c688cc@9a6363d6 |
| ed6863c7 | Claude Code, claude-haiku-4-5, Paseo "Herald summary" 7df4c112 | wind-down; `.gitignore` aider commit | (i) discard; branch `gitignore-aider` reviewable separately | checkin/ed6863c7@8a93eb7e |

## B. What the split must not break

Grouped by the candidate areas in request section e. Each item names who reported it.

### B1. bin/acp-dispatch*, tools/acp-run

B1a Three detached acp-dispatch slices from 3ac46de6 were still running at check-in, with HELM's permission to finish. They need `acp-dispatch` finalize and acp-run to stay in place until they exit. Each takes about 0.5 to 1.5 h. Job records: `~/.local/state/bigteam/tendcf-s5-20261103/jobs/s5-design.json` (worktree `~/src/tendcf-s5-design-wt`), `~/.local/state/bigteam/fork-cmdb-closed-20261103/jobs/fork-cmdb.json` (`~/src/cfengine-core-cmdb-wt`, `~/src/tendcf-fork-pin-wt`), `~/.local/state/bigteam/tendcf-q10-policy-20261106/jobs/q10-policy.json` (`~/src/tendcf-cmdb-xcheck-wt`). w38:p8 also saw the `tendcf-q10-policy` acp-run processes running. 7c58015b says the `acp-dispatch-wait` processes under `tui-retire/`, `tendcf-*` and `fork-cmdb-*` belong to other sessions.

B1b 9e5b46d1's read-only adversary round `adversary-pr254f` was still running, with a waiter. It uses launchd label `acp-dispatch.adhoc-2026-11-02.adversary-pr254f`, which removes itself on exit. Its record is `~/.local/state/bigteam/adhoc-2026-11-02/jobs/adversary-pr254f.json`.

B1c The tendcf and nix2cf AGENTS.md files name `acp-dispatch ... --kind frontier` explicitly (3ac46de6). If the command moves or is renamed, both files need updating.

B1d `bin/agent_guard.py` (PR 275) is a safety guard for pi, omp, codex and claude. w38:p8 asks that it stay or move intact, with `tests/test_acp_dispatch_identity.py`, `tests/test_omp_operator_gate.py` and `docs/agent-guard-contract.md`, into whatever replaces acp-dispatch.

B1e These agents use acp-dispatch and acp-run as clients and need the new usage if either changes: 1057582a (frontier advisory), 2b4437d2 (adversary slices), c3cbe51a, 6eb6d3f6, 7c96a0ca, 9e5b46d1, ac95a703, f111c672, 042d0c8d.

B1f 1e61c979's lander3.py and feeder.py are state-dir scripts, not repo code, in `~/.local/state/bigteam/deepseek-review-2026-10-30/`. They build on acp-dispatch, acp-dispatch-wait, acp-run, route_agent.py, relay.py, fleet.py, bin/local-review, bin/pr-wait, bin/load-watch and bin/deadline. They stop working if those tools move.

### B2. skills/session-finder (relay.py, fleet.py, launch.py)

B2a Nearly every agent sends peer messages through `skills/session-finder/relay.py`. 3846a46e, w20:pN, c3cbe51a and 23adbb25 said they need the new path if it moves. Several sends are still queued and may be delivered late (section I).

B2b ebd6ed1a's planned fleet-migrate integration builds directly on relay.py, fleet.py and launch.py.

B2c 7c58015b's helm lead mode (`skills/helm/lead.md`) is built on relay.py and fleet.py.

B2d w38:p8 changed `fleet.EXACT_EXECUTABLES`, the Pi and omp adapters, `skills/session-finder/nativeid.py` and the relay helpers. These sit inside session-finder.

### B3. Claims (ade_claims.py)

B3a Active claims exist for many check-in worktrees and for `fleet-migrate-1103`, `cfengine-6424-prep-20261106` and `pr254-nested-backticks-ac95a703`. 19ece915 warns that retiring the claim tool must not orphan an active claim. w38:p8 counted 20 active claims in `~/.local/state/ade/claims`.

### B4. Watchers

B4a `com.djbclark.load-watch` runs `/Users/djbclark/src/djbclark-ade/bin/load-watch sample` by absolute path (ff08899e). If `bin/load-watch` or `skills/loadwatch` moves, the plist ProgramArguments and the skill path must move in the same change. Otherwise the sampler dies silently.

B4b Load watcher registration: `~/.local/state/load-watch/watcher.json` points at paseo ff08899e. To clear it: `/Users/djbclark/src/djbclark-ade/bin/load-watch watcher clear paseo:ff08899e-a6a0-443b-9d80-6eb96a490d62`.

B4c `load-watch admit` is called by `bg` and `acp-dispatch` (ff08899e). It is also used by 3ac46de6 and c3cbe51a.

B4d fleet-watch upstream registrations: 6eb6d3f6 for CFEngine, and bcff073a ("watch paseo 1j") for Paseo. Both are kept while paused. Both depend on `bin/watch`, the paseowatch/cfenginewatch skills, session-handoff, relay.py and fleet.py, plus the external fleet-watch launchd scheduler.

B4e PR 231 (32779db2) builds on `bin/load-watch`.

### B5. bin/deadline and the deadline sweep

B5a `com.djbclark.deadline-sweep` was installed by `bin/deadline install` after PR 223. It is loaded and runs every 60 s (1e61c979).

B5b `acp-dispatch-wait` waiters register their own deadlines (9e5b46d1). bin/bg deadline registration and the `--holder` guard live in `~/ops/site-public-djbclark` (1e61c979).

### B6. pr-policy (outside every listed area)

B6a `com.djbclark.pr-policy` runs every 600 s from the shared checkout (`~/Library/LaunchAgents/com.djbclark.pr-policy.plist`, state in `~/.local/state/pr-policy/`). If `bin/pr-policy` moves or is deleted, run `bin/pr-policy uninstall` first, or reinstall from the new place. Otherwise the job fails every 10 min (0dc43dbd).

### B7. Lander and feeder

B7a `com.djbclark.ade-lander` and `com.djbclark.ade-feeder` plists are in `~/Library/LaunchAgents`. Both have been booted out since the stop order. To resume: `launchctl bootstrap` the two plists (1e61c979).

### B8. Non-Claude TUI support (pi/, omp/, opencode/, zcode/, agents/, coding-bot)

B8a `~/.local/bin/coding-bot` is a symlink to `~/src/djbclark-ade/bin/coding-bot`. `~/ops/site-public-djbclark/home-agents.md` item 40 points at coding-bot. If `bin/coding-bot` goes, repoint both (f111c672). The live Coding link does not depend on djbclark-ade.

B8b `~/.pi/agent/extensions/subagent` is a symlink to `~/src/djbclark-ade/pi/extensions/subagent`. If the path goes, Pi loses the extension (w38:p8).

B8c Four `hand` symlinks point into the repo: `~/.omp/agent/commands/hand.md`, `~/.pi/agent/prompts/hand.md`, `~/.zcode/commands/hand.md` and `~/.config/opencode/commands/hand.md`. The `hand` skill is also linked by skill-everywhere into many TUI skill dirs (w38:p8).

B8d `agents/claude/settings.json.tmpl` is the target of `bin/render-secret-deny` (PR 289). If `agents/` moves, the renderer's default `--claude-template` path and `tests/test_secret_deny_repo.py` must move too (01BvGHLzD4).

B8e The `tell-coding-bot` skill is linked into every TUI by `bin/skill-everywhere` (f111c672).

B8f dsh machine state from w20:p0, left for the retirement lead to uninstall: the `~/.local/bin/dsh` wrapper (secretspec plus YOLO), the `~/.local/lib/dsh/bin/dsh-bin` symlink, `~/.dsh/profiles/web/cordis.patch.yml`, a TIER 2 `dsh()` function in `~/.zshrc` and `~/.config/zsh/zshrc.expected`, and the re-rendered `~/.local/bin/brew-fast-upgrade`. Its ops commit is site-public 3913c57.

### B9. Quota gates and route_agent.py

B9a `bin/quota-surplus` (PR 270) uses only the public API of `bin/route_agent.py` (7c58015b).

B9b 3ac46de6 uses route_agent.py and the quota gates for dry-run shortness checks.

B9c The aiuse interim exclusion `[analysis.excluded_pools] "opencode-go"` in `~/.config/aiuse/config.toml` should be removed after PR 260 (1e61c979).

### B10. skills/autorename, bin/self-slash

B10a c3cbe51a and 9e5b46d1 were started through `bin/self-slash`. c3cbe51a uses autorename for titles.

B10b The CLAUDE_PID registry lookup from PR 259 (`registered_claude_session_id`, `_proc_start_matches`) and its test must move with autorename or be dropped together (7c96a0ca).

### B11. Outside the repo, not a candidate area

B11a `com.djbclark.watchdogd` runs `bin/apple_daemon_ban.sh` from `~/ops/site-public-djbclark/bin`. Do not move that path (32779db2).

B11b `config/launchd/com.djbclark.quota-surplus.plist` (PR 270) and the oc-go-key drain plist (one-offs) are templates only and are not loaded (7c58015b).

B11c `bin/ade-sched` / `bin/ade_sched.py` are new in PRs 291 to 293. They are not a candidate area. `bin/deadline` and `bin/pr-policy` import them when they load (01BvGHLy).

### B12. docs/

B12a `docs/tui-lessons-learned.md` is the one intended record of the retired TUIs. Keep it (0dc43dbd).

B12b `docs/checkpoint.md` sections F and G should move with whatever keeps the Paseo plan (01BvGHM3).

B12c The docs/checkins reports and docs/handoffs files are evidence. ac95a703 and ba920539 ask that they be kept.

## C. Open PRs and branches to decide

All PR links are https://github.com/djbclark/djbclark-ade/pull/N unless stated.

C1 [PR 291](https://github.com/djbclark/djbclark-ade/pull/291). Owner 01BvGHLy. Head 6d9a647e. State: blocked. The adversary marker names the pre-merge head 9d1dba2, so it is stale. Needs a fresh adversary confirm plus Codex and CI, about 30 to 60 min. Recommendation: (ii) land. Areas: mostly outside the candidates (ade-sched, deadline, pr-policy).

C2 [PR 293](https://github.com/djbclark/djbclark-ade/pull/293). Owner 01BvGHLy. Head 58c5d9ef. Base is PR 291's branch. Depends on 291: merge 291 first, and never delete the `-1-sched` branch before that. Stale marker. Recommendation: (ii) only if load-watch and claude-quota-guard stay; otherwise close it or rebase after the split. Areas: watchers, quota gates, docs.

C3 [PR 292](https://github.com/djbclark/djbclark-ade/pull/292). Owner 01BvGHLy. Head e232f889. Stale marker. Recommendation: (ii) only if coding-bot and acp-dispatch stay. The skill-everywhere, codium-ai, app-tamer-ab and paseo-set-model parts could be cherry-picked into a small PR, about 30 min. Areas: acp-dispatch, coding-bot.

C4 Branch `claude/issue-279-linux-ports` (9da4a797). Owner 01BvGHLy. Superseded by the three PR branches and kept on purpose.

C5 [PR 289](https://github.com/djbclark/djbclark-ade/pull/289). Owner 01BvGHLzD4. Head 205a863. Mergeable clean. The adversary APPROVEs 205a863. CI was green on 3861c1a and had not finished on 205a863. Three review findings in `secret_read_gate.py` are not fixed. The `/retro` PR-title thread waits on djbclark. Recommendation: (ii) merge, then a follow-up PR, about 1 h. Areas: agents/, docs/.

C6 [PR 290](https://github.com/djbclark/djbclark-ade/pull/290). Owner 01BvGHM3. Head 15186fb. Blocked: the marker names ed4e2c5. It needs an adversary confirm, the last Codex thread resolved, CI and a Codex re-review, about 30 to 60 min. Recommendation: (ii). Areas: none (Paseo-native), plus small README and docs edits.

C7 [PR 254](https://github.com/djbclark/djbclark-ade/pull/254). Owners 9e5b46d1 (review completion) and ac95a703 (pushed the head). Head e0250889. Reports disagree on whether it is ready. 9e5b46d1 and ac95a703 say merge-ready: local-review clean, exact-head adversary APPROVE, CI green, only `gh pr merge --squash --match-head-commit e0250889...` left. 1e61c979 says 254 is "blocked by a real Cursor security finding", and that its merge watcher ran once and `pr-wait` refused it (open-findings). Recommendation: (ii). Area: `claude/hooks/bash_habits_gate.py`, which is not on the list.

C8 [PR 256](https://github.com/djbclark/djbclark-ade/pull/256), open-clean-env. Owner 1e61c979. Head 8c5c13fc. Waits on 254, because both edit the habits gate. Recommendation: (ii) land after 254 if the habits hook stays. `bin/open-clean` is useful either way.

C9 [PR 260](https://github.com/djbclark/djbclark-ade/pull/260), route-repo-scope. Owner 1e61c979. Head 315493f0. Blocked: 6 tests pin old rulings, 2 Argon P1s are confirmed, and local-review is not done (about 2 to 4 h). It carries djbclark's 2026-11-02 routing rulings: opencode-go and cline only for techno-euphora and Hermes, a cline floor of 40%, and spend agy/omp/codex/zcode/cursor/grok to empty. Recommendation: (iii) if route_agent.py and acp-dispatch stay; otherwise (i), and re-apply the rulings in the replacement. Areas: route_agent.py, acp-dispatch, routing.toml, quota gates. The worktree `~/src/djbclark-ade-route-scope-wt` also holds an uncommitted 3-line change (section F).

C10 Branch identity-intervening-agent (worktree `~/src/djbclark-ade-identity-ia-wt`, no commits). Owner 1e61c979. It fixes a mis-attribution bug merged in PR 248. Recommendation: (iii) if session-finder stays, about 1 to 2 h. It blocks PR 261. Area: session-finder.

C11 [PR 261](https://github.com/djbclark/djbclark-ade/pull/261), relay question ledger. Owner 7c58015b. Head fe676324. Waits on identity-intervening-agent (1e61c979). Recommendation: (ii) if relay.py stays; (i) if Paseo gets a native equivalent (that loses about 3 repair rounds). Area: session-finder.

C12 [PR 270](https://github.com/djbclark/djbclark-ade/pull/270), quota-surplus watchdog. Owner 7c58015b. Head ca969c51. local-review clean and 43 tests passed (reported by 19ece915 and 7c58015b). Recommendation: (ii) land as is, about 10 min. Areas: quota gates, route_agent public API.

C13 [PR 294](https://github.com/djbclark/djbclark-ade/pull/294), lead-stagger-wake rule. Owner 7c58015b. Head a688c9e4. Docs only. Recommendation: (ii) land, about 5 min. Area: skills/helm.

C14 [PR 208](https://github.com/djbclark/djbclark-ade/pull/208), astra-readonly. Owner 1e61c979. Head af83e53e. Recommendation: (i) acceptable if acp-run and acp-dispatch are deleted; that loses a read-only denial fix. Areas: acp-run, acp-dispatch.

C15 [PR 214](https://github.com/djbclark/djbclark-ade/pull/214), recursion-readers. Owner 1e61c979. Head 2a6fe8b6. Recommendation: (i) acceptable if the quota gates are deleted; that loses nested-JSON hardening. Area: quota gates.

C16 [PR 263](https://github.com/djbclark/djbclark-ade/pull/263). Owner 3ac46de6. Closed as a duplicate of 208. Branch `acp-run-codex-readonly-never-ask` (fa381ed4) and worktree `~/src/djbclark-ade-codex-ro-wt` are kept as evidence for PR 208. Recommendation: (iv) keep until 208 is decided. Area: acp-run.

C17 [PR 231](https://github.com/djbclark/djbclark-ade/pull/231), load-watch mds-client probe. Owner 32779db2. Branch mds-client-probe at bf4259ee, worktree `~/src/djbclark-ade-mds-probe-wt`. Open, waiting on the lander. Recommendation: (ii), or (i) if load-watch goes. Landing takes about one agent turn. Area: watchers.

C18 [PR 269](https://github.com/djbclark/djbclark-ade/pull/269), coding-bot as a peer_mail wrapper. Owner f111c672. Head 144443c3. Blocked: one unfixed BLOCK (the caller's HOME picks peer_mail's trust file), the rest of the PATH fix, and 3 local-review P2s. Recommendation: stop here and re-home it into frdminc/peer-link, one repair round of about 2 to 3 h. Do not delete the branch `coding-bot-peer-link` or the worktree `~/src/djbclark-ade-cb-pl-wt`. Area: coding-bot.

C19 [PR 281](https://github.com/djbclark/djbclark-ade/pull/281), opencode bridge guard. Owner w20:pQ. Head c8403793. CI green and adversary APPROVE marker in place. local-review was refused by the load gate twice. Recommendation: (i) if opencode support goes; else (iii), about 15 to 25 min plus 5 min to merge. Area: non-Claude TUI (`bin/*opencode*`).

C20 Branch d1-prep (b30216d3, 55 files). Owner 1e61c979. D1 Paseo acceptance tasks T1 to T8 and T11. Recommendation: (iv) continue, and land as one PR after the split (about 1 day of review). Areas: Paseo-native core, docs.

C21 Branch feat/fleet-migrate (7be0d42b before the check-in, 4abbb824 after). Owner ebd6ed1a. No PR. Recommendation: (ii) in the sense of preserve, do not merge. Areas: non-Claude TUI, session-finder, docs.

C22 Branch docs/tui-consolidation (2c22ba5b). Owner 501a7e0d. Belongs to the closed [PR 283](https://github.com/djbclark/djbclark-ade/pull/283). Keep it until the lead confirms PR 288 carries what it needs, then delete it.

C23 Branch handoff-snipe-session (two handoff docs). Owners 9e5b46d1 and ac95a703. Branch handoff/bridge-guard-ba7b (2e35bb0e). Owner w20:pQ. Both are docs-only handoff records.

C24 Branch fix/dispatch-completion-notice (last known c67ab3fa), worktree `~/src/djbclark-ade-dispatch-notice-wt`. Owner is c987a634, which did not report (named by bcff073a).

C25 Outside djbclark-ade: questions-please PR 1 (Decisions screen) and one-offs branch `oc-go-key-idle`, both from 7c58015b. frdminc/techno-euphora PR 57 is the parent integration for ba920539's fix.

## D. Per-agent sections

### D1. 01BvGHLy

D1a Task: issue 279, Linux versions of macOS-only pieces, Paseo-first. Built `bin/ade-sched`, Linux installs for 6 tools, exit-69 guards, coding-bot clipboard fallbacks and a skill-everywhere root fix. Split into PRs 291, 293 and 292.

D1b State: all three PRs had master merged in on 11-06. The adversary confirm was stopped by STOP, so the markers are stale. Clean. No processes.

D1c Footprint outside the repo: none (cloud container).

D1d Overlap: acp-dispatch (292), coding-bot (292), claude-quota-guard and load-watch (293), docs.

D1e Recommendation: (ii) for 291, about 30 to 60 min. 292 and 293 depend on which tools survive. A cherry-pick of 292 is about 30 min. (i) would lose about 300 tests and 5 review rounds.

D1f Must-know: merge 291 before deleting its branch, or 293 closes. In the container, 9 acp-dispatch tests and some other tests fail on master too.

D1g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/01BvGHLy/docs/checkins/2026-11-06-01BvGHLy.md

### D2. 01BvGHLzD4

D2a Task: issue 284 (NDC Oslo ideas). Built instruction-lint, the secret-file read-deny gate, post-edit-check, `/steps plan`, and ade-retro with the retro skill. Item 4 (goal loop) was not built.

D2b State: PR 289 is clean at 205a863 with adversary APPROVE. Three gate findings are open.

D2c Footprint outside the repo: none. The template changes are not applied live.

D2d Overlap: `agents/claude/settings.json.tmpl`, docs/. acp-dispatch, acp-run and report are only referenced.

D2e Recommendation: (ii) merge, then fix in a follow-up, about 1 h. (iii) is reasonable because the findings are real bypasses.

D2f Must-know: short id renamed from 01BvGHLz because it clashed with the lead 01BvGHLzKz. Report branch `checkin/01BvGHLz`.

D2g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/01BvGHLz/docs/checkins/2026-11-06-01BvGHLzD4.md

### D3. 01BvGHM3

D3a Task: issue 278, checkpointing. Built the `plugins/ade-recovery` passive Paseo plugin, the `bin/paseo-checkpoint` CLI and `docs/checkpoint.md` F and G. Five adversary rounds.

D3b State: PR 290 at 15186fb. The marker is stale (it names ed4e2c5). Node tests pass 269/269.

D3c Footprint outside the repo: none.

D3d Overlap: none apart from small README and docs edits. It builds on Paseo itself.

D3e Recommendation: (ii), about 30 to 60 min. (iv) would also be safe.

D3f Must-know: do not merge PR 290 until the marker is refreshed.

D3g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/01BvGHM3/docs/checkins/2026-11-06-01BvGHM3.md

### D4. 042d0c8d

D4a Task: sudo-secretspec release. v0.21.1-sudo.5 is installed on the Mac, dann, vps-primary and get. Pastebin is on .4.

D4b State: all repos are clean and pushed. It never edited djbclark-ade.

D4c Footprint outside the repo: `~/.ssh/config` (removed the vps-public block, with a backup), deleted regenerable caches, installed sudo-secretspec, host deploys.

D4d Overlap: none. It used relay.py, acp-dispatch, deadline, load-watch and clip.

D4e Recommendation: (iv). What remains is one paste by djbclark for pastebin.

D4f Must-know: relay.py hung four times on 11-06.

D4g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/042d0c8d/docs/checkins/2026-11-06-042d0c8d.md

### D5. 0b68fe51

D5a Task: techno-euphora SIGINT mask fix (Dann 7). It ran a pre-edit probe only. Implementation was never started.

D5b State: the probe did NOT reproduce the leak. The agent's own inference is that the detached shell inherited an ignored SIGINT. These numbers are not proof.

D5c Footprint outside the repo: `.n2-mask-evidence/` in `~/src/te-async-wt` (untracked scratch), plus reports in `dann-copilot-burn-2026-11-01/`.

D5d Overlap: docs/ only.

D5e Recommendation: (ii), publish the report only. (iii) would need a fresh authorized round.

D5f Must-know: holds claim checkin-0b68fe51. Old relay messages may still be queued.

D5g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/0b68fe51/docs/checkins/2026-11-06-0b68fe51.md

### D6. 0dc43dbd

D6a Task: (1) pr-policy ([PR 285](https://github.com/djbclark/djbclark-ade/pull/285), merged; 127 repos set to collaborators_only). (2) Agent-TUI retirement: [PR 288](https://github.com/djbclark/djbclark-ade/pull/288) lessons doc, [PR 287](https://github.com/djbclark/djbclark-ade/pull/287) credit refusal, aiuse PRs 47 and 48, and merged [PR 286](https://github.com/djbclark/djbclark-ade/pull/286). Wave 3 (57 files) never ran because of the load gate.

D6b State: everything is landed. Only the check-in worktree remains.

D6c Footprint outside the repo: launchd `com.djbclark.pr-policy`, the GitHub repo policy, an aiuse note-exhausted entry, and `~/.local/state/bigteam/tui-retire/`.

D6d Overlap: the unfinished retirement builds on acp-run, acp-dispatch, route_agent, failover, session-finder, bigteam and non-Claude TUI support.

D6e Recommendation: (ii), already landed. Fold the retirement into the split and hand over `tui-retire/PLAN.md`. Keep pr-policy (it may move out).

D6f Must-know: run `bin/pr-policy uninstall` before moving it. Q1 to Q5 are pending (section E1).

D6g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/0dc43dbd/docs/checkins/2026-11-06-0dc43dbd.md

### D7. 1057582a

D7a Task: sync Paseo plugins on the Mac and vps-primary, upgrade vps-primary and both phones to Paseo 0.14.0, and build djbclark/paseo-runner stage 1.

D7b State: runner stage 2, the fresh-worktrees 3.1.1 apply and the phone plugin check are not done.

D7c Footprint outside the repo: Mac daemon (paseo-runner enabled, fresh-worktrees disabled). vps-primary has 14 plugins installed and disabled, and herdr-harness copied an OMP companion file there. vps-primary nixos-upgrade. adb installs on the s24 and Titan 2.

D7d Overlap: none. It used acp-dispatch, acp-run and relay.py as a client.

D7e Recommendation: (iv).

D7f Must-know: relay record 20261106-102251-406062 is on disk.

D7g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/1057582a/docs/checkins/2026-11-06-1057582a.md

### D8. 19ece915

D8a Task: a Pi continuation of HELM LEAD 7c58015b. It reconciled the failed tendcf decision delivery and the quota-surplus repair. No implementation.

D8b State: report only. It verified PR 270 open at ca969c51.

D8c Footprint outside the repo: `RECOVERY-2026-11-03.md`, `tendcf-validate-picks-undelivered.txt`, `tendcf-s5-picks-delivered.txt`, a `~/.pi/agent/AGENTS.md` note, and claim checkin-19ece915.

D8d Overlap: docs/ only. Coordination builds on relay.py, fleet.py and helm.

D8e Recommendation: (i) for the role, now that HELM LEAD is back. Keep the recovery files and do not resend them.

D8f Must-know: eight older review and research reports were not endorsed. Their owner should check them before dispatching duplicates. `argon-failfast-second` had no report.

D8g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/19ece915/docs/checkins/2026-11-06-19ece915.md

### D9. 1e61c979

D9a Task: djbclark-ade lead for the Paseo-only rearchitecture. About 60 PRs landed since 11-01. D1 T1 to T8 and T11 are done on d1-prep.

D9b State: the lander and feeder are booted out. Slices for 260 and identity-intervening-agent never started (load gate). The 254 watcher was refused by pr-wait.

D9c Footprint outside the repo: lander, feeder and deadline-sweep launchd jobs. The aiuse config exclusion. `~/ops/site-public-djbclark` bg deadline commits and port 18809. A site-private memory note. Lander state dirs. Quicksilver and Default Folder X relaunched with a clean environment.

D9d Overlap: landing automation builds on most of the candidate areas. PRs 260, 208 and 214 touch candidates.

D9e Recommendation: automation (ii), keep it paused. D1 (iv), about 1 day after the split. 260 (iii), 2 to 4 h, or (i). identity-intervening-agent (iii), 1 to 2 h. 208 and 214 (i) acceptable. 256 (ii) after 254.

D9f Must-know: deadline-sweep runs every 60 s. adversary-pr254f belongs to 9e5b46d1. The route-scope worktree has an uncommitted change. Tier 1 log: `standalone-b457`.

D9g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/1e61c979/docs/checkins/2026-11-06-1e61c979.md

### D10. 23adbb25

D10a Task: aiuse PR 47 follow-up, [aiuse PR 48](https://github.com/djbclark/aiuse/pull/48) merged, v4.0.1 released, Homebrew bump.

D10b State: aiuse is clean at 79c0797. No djbclark-ade edits.

D10c Footprint outside the repo: only the relay.py records and the check-in worktree.

D10d Overlap: none (used relay.py).

D10e Recommendation: (ii), already shipped. (i) would discard a public release.

D10f Must-know: `ade-git-guard` and `deadline` are not on PATH. Its stash listing shows `stash@{0}: prwait-wip2`.

D10g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/23adbb25/docs/checkins/2026-11-06-23adbb25.md

### D11. 2507bcbf

D11a Task: fix the dann-workspace-accent plugin enable failure (the daemon and app versions did not match). The plugin cannot apply its label because `setWorkspaceLabel` is absent. Disabled it on djbclark's decision. Pushed 81e4a44.

D11b State: clean. Not touched djbclark-ade.

D11c Footprint outside the repo: the plugin repo, the `~/.paseo/config.json` entry (net disabled), and `/tmp/paseo-asar`, which is safe to delete.

D11d Overlap: none (relay.py).

D11e Recommendation: (iv).

D11f Must-know: relay.py timed out several times, so acks may only be queued.

D11g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/2507bcbf/docs/checkins/2026-11-06-2507bcbf.md

### D12. 2b4437d2

D12a Task: paseo4herdr generic pane-bound adapter and opt-in shell input. [paseo4herdr PR 5](https://github.com/djbclark/paseo4herdr/pull/5) merged ad5d1095. Issues 6 to 8 filed.

D12b State: open items are the GUI check, the real-shell trial (needs djbclark's yes to swap the live plugin), and slices S3/S4.

D12c Footprint outside the repo: none changed. The live `herdr-harness` plugin still runs from the pasture dir.

D12d Overlap: none edited. It uses acp-dispatch, relay.py, acp-dispatch-wait and self-slash.

D12e Recommendation: (iv).

D12f Must-know: the handoff's next steps need updating if the dispatch tools move.

D12g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/2b4437d2/docs/checkins/2026-11-06-2b4437d2.md

### D13. 32779db2

D13a Task: Finder/mds CPU thread. [PR 251](https://github.com/djbclark/djbclark-ade/pull/251) merged. PR 231 open. Froze Apple daemons and fixed the NeoFinder first scan. Installed removemacai.

D13b State: PR 231 worktree is clean at bf4259ee.

D13c Footprint outside the repo: `launchctl disable` on 53 Apple daemons. watchdogd SIGSTOPs 16 daemons. removemacai 1.1.4 is installed and its profile approval is pending.

D13d Overlap: PR 231 builds on load-watch.

D13e Recommendation: PR 231 (ii) or (i), about one agent turn. Everything else (iv).

D13f Must-know: do not move `bin/apple_daemon_ban.sh`. The Data volume is 96% full (20 GB free). The NeoFinder first real run is 2026-11-07 at 03:45.

D13g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/32779db2/docs/checkins/2026-11-06-32779db2.md

### D14. 3846a46e

D14a Task: rename a Paseo workspace to "herdr4paseo remote issue". Done.

D14b State: nothing in flight.

D14c Footprint outside the repo: the Paseo workspace title only.

D14d Overlap: none. It uses relay.py and read the autorename SKILL.md.

D14e Recommendation: (iv).

D14f Must-know: needs the new relay.py path if it moves.

D14g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/3846a46e/docs/checkins/2026-11-06-3846a46e.md

### D15. 3ac46de6

D15a Task: tendcf and nix2cf lead. Its harness fixes were [PR 224](https://github.com/djbclark/djbclark-ade/pull/224) (merged), PR 263 (closed) and [PR 272](https://github.com/djbclark/djbclark-ade/pull/272) (merged).

D15b State: nothing in progress in djbclark-ade. Three detached slices are running (B1a).

D15c Footprint outside the repo: site-private memory notes and bigteam state.

D15d Overlap: tendcf work builds on acp-dispatch, acp-run, relay.py, route_agent.py, the quota gates, load-watch admit, deadline, session_log.py and cfenginewatch.

D15e Recommendation: (iv) if the acp-dispatch and acp-run CLI stays or AGENTS.md is updated. Keep the PR 263 branch.

D15f Must-know: the slices need acp-dispatch until they exit. Q9 is pending (E5).

D15g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/3ac46de6/docs/checkins/2026-11-06-3ac46de6.md

### D16. 501a7e0d

D16a Task: TUI consolidation plan. `docs/tui-consolidation.md`, PR 283. Handed to 0dc43dbd on 11-04.

D16b State: PR 283 is closed. The branch docs/tui-consolidation is kept.

D16c Footprint outside the repo: state in `~/.local/state/tui-consolidation/`.

D16d Overlap: docs/. The plan describes many candidates but changed none of them.

D16e Recommendation: (ii). No time needed.

D16f Must-know: open decisions were handed to 0dc43dbd: a Claude Console org for omp credit, Cursor and xAI fallbacks, and an acp-run login guard.

D16g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/501a7e0d/docs/checkins/2026-11-06-501a7e0d.md

### D17. 6eb6d3f6

D17a Task: CFEngine upstream watcher. Intake for [core issue 55](https://github.com/djbclark/core/issues/55) and [issue 56](https://github.com/djbclark/core/issues/56). Prep for [cfengine/core PR 6424](https://github.com/cfengine/core/pull/6424). The slice never launched (admission refused).

D17b State: the prep worktree `~/src/cfengine-core-6424-prep-wt` is clean at fdad2cdc.

D17c Footprint outside the repo: fleet-watch registration, Tier 1 `standalone-3fd9`, bigteam evidence and claims.

D17d Overlap: docs/ only. The role builds on cfenginewatch, watch, fleet-watch, bigteam, acp-dispatch, relay.py, route_agent and deadline.

D17e Recommendation: (ii) report, (iv) keep watching. The remaining 6424 work is about 30 to 60 min after the pause.

D17f Must-know: claims cfengine-6424-prep-20261106 and checkin-6eb6d3f6-20261106. Do not auto-rearm `jobs/code.json`.

D17g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/6eb6d3f6/docs/checkins/2026-11-06-6eb6d3f6.md

### D18. 7c58015b

D18a Task: fleet lead. [PR 258](https://github.com/djbclark/djbclark-ade/pull/258) `/helm lead` merged. aiuse 3.13.1 released. Paseo daemon restart. fleet-watch `phantom` check. The paseo#5951 comment. Many picklists.

D18b State: PRs 261, 270 and 294 are open. questions-please PR 1 and one-offs `oc-go-key-idle` are open.

D18c Footprint outside the repo: site-public home-agents.md and fleet-watch phantom, site-private memory notes, the aiuse release, one daemon restart, `paseo agent archive 285bea53`, a Beeper message to Patrick.

D18d Overlap: skills/helm, session-finder (261), watch SKILL.md, quota gates (270).

D18e Recommendation: 270 (ii) about 10 min. 294 (ii) about 5 min. 261 (ii) if relay.py stays. lead.md (iv).

D18f Must-know: `stop-broadcast.py` (pid 39128) was still running and ends by itself. No pushed SHA in checkin-done.txt.

D18g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/7c58015b/docs/checkins/2026-11-06-7c58015b.md

### D19. 7c96a0ca

D19a Task: autorename "no transcript" bug. The cause was a stale inherited CLAUDE_CODE_SESSION_ID. [PR 259](https://github.com/djbclark/djbclark-ade/pull/259) merged 2a5499c4.

D19b State: nothing pending. The seat is safe to archive.

D19c Footprint outside the repo: Tier 1 `standalone-84d4` and bigteam job records.

D19d Overlap: skills/autorename.

D19e Recommendation: (iv).

D19f Must-know: relay.py, fleet.py, session-find.py and ade_claims.py still trust the stale env id. The follow-up is not started.

D19g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/7c96a0ca/docs/checkins/2026-11-06-7c96a0ca.md

### D20. 9e5b46d1

D20a Task: land [PR 252](https://github.com/djbclark/djbclark-ade/pull/252) (merged) and PR 254.

D20b State: PR 254 at e0250889 has local-review clean, a marker and green CI, by its account. adversary-pr254f is still running and is redundant.

D20c Footprint outside the repo: Tier 1 `standalone-9fed`, adhoc state, local-review artifacts, the PR 254 body.

D20d Overlap: none listed. The habits gate may be "non-ADE". It builds on acp-dispatch, relay.py, fleet.py, local-review, baton and self-slash.

D20e Recommendation: (ii), minutes.

D20f Must-know: the habits worktree carries a foreign ` M .cursor/hooks.json`. It will reap adversary-pr254f on request.

D20g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/9e5b46d1/docs/checkins/2026-11-06-9e5b46d1.md

### D21. ac95a703

D21a Task: Pi continuation of 9e5b46d1. Repaired the nested escaped backticks in PR 254 and pushed e0250889. Its adversary round APPROVEd that head.

D21b State: review ownership transferred to 9e5b46d1. The lead owns the merge.

D21c Footprint outside the repo: a `~/.pi/agent/AGENTS.md` note, Tier 1, claims, `pr254-backtick-ac95a703/` state.

D21d Overlap: none in the code. docs/handoffs are evidence.

D21e Recommendation: (ii).

D21f Must-know: claim pr254-nested-backticks-ac95a703 is still active despite the transfer. The lead should reconcile it with 9e5b46d1.

D21g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/ac95a703/docs/checkins/2026-11-06-ac95a703.md

### D22. ba920539

D22a Task: techno-euphora SIGINT mask. Fixed. The parent committed c5f93919 on dann/peer-mail-async-window, with 193 tests passing and the mutant failing.

D22b State: done. Report only.

D22c Footprint outside the repo: n2-mask-fix-pi-report.md and claim checkin-ba920539.

D22d Overlap: docs/ only.

D22e Recommendation: (ii).

D22f Must-know: do not remove `.n2-mask-evidence/` on its authority. Do not push the later te-async-wt HEAD as its work. Note that 0b68fe51 says the probe did not reproduce the leak, while ba920539 reports the mutant leaking 1. These are different runs; neither report reconciles them.

D22g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/ba920539/docs/checkins/2026-11-06-ba920539.md

### D23. bcff073a

D23a Task: Paseo upstream watcher "watch paseo 1j". Registered and tested.

D23b State: getpaseo/paseo issue 8780 event deferred under the stop.

D23c Footprint outside the repo: Tier 1 `paseo-workspace-accent`, fleet-watch registration, claim checkin-bcff073a.

D23d Overlap: docs/ only. The role builds on paseowatch, session-handoff, relay.py, fleet.py and watch.

D23e Recommendation: (ii) report, (iv) passive watching.

D23f Must-know: 8780 brief at `~/.local/state/fleet-watch/upstream-paseo-paseo-8780-20261106t153851-relay.md`. The predecessor c987a634's worktree is not inherited.

D23g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/bcff073a/docs/checkins/2026-11-06-bcff073a.md

### D24. c3cbe51a

D24a Task: Plektra Titan 2 key remap and backlight work. Upstream [plektra issue 171](https://github.com/pkb-rocks/plektra/issues/171), [PR 172](https://github.com/pkb-rocks/plektra/pull/172), [issue 173](https://github.com/pkb-rocks/plektra/issues/173), and draft PRs 125 to 127 re-pushed.

D24b State: the Beeper newline needs a live key capture on the phone. adb has been disconnected since the Paseo restart. Sitting A has not started.

D24c Footprint outside the repo: Tier 1 `standalone-b380`, bigteam state, the phone build.

D24d Overlap: none edited. It uses acp-dispatch, relay.py, autorename, self-slash, load-watch admit and deadline.

D24e Recommendation: (iv).

D24f Must-know: two relay sends to 7c58015b timed out with no record.

D24g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/c3cbe51a/docs/checkins/2026-11-06-c3cbe51a.md

### D25. ce04246a

D25a Task: install the best Claude Cloud skills and docs, and answer questions about it. Done.

D25b State: no djbclark-ade edits.

D25c Footprint outside the repo: Claude.app 4.16336.0, the `anthropic-agent-skills` marketplace and two plugins in `~/.claude`, a `~/src/anthropics-skills` clone, `~/s` links.

D25d Overlap: none.

D25e Recommendation: (iv).

D25f Must-know: it saw ` M .gitignore` in the shared checkout at start. That change is now gone.

D25g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/ce04246a/docs/checkins/2026-11-06-ce04246a.md

### D26. ebd6ed1a

D26a Task: fleet-migrate tool. Partial offline planner, guards, storage and a refusal-only CLI. 98 tests. NOT an operational tool.

D26b State: CI passed at fb776204 and e6fd50a0. No current-head review. The frontier review route was refused (Pi is frontier-ineligible).

D26c Footprint outside the repo: a `~/.pi/agent/AGENTS.md` note, Tier 1 `fleet-migrate-1103`, claim fleet-migrate-1103.

D26d Overlap: non-Claude TUI, session-finder (planned), acp-dispatch, docs, README and CI.

D26e Recommendation: preserve the branch and do not merge. (iii) and (iv) are not justified. The time cannot be estimated.

D26f Must-know: never migrate Dann Home. Queued relay receipts are not delivered. The review-route question is pending (E3).

D26g Report: https://github.com/djbclark/djbclark-ade/blob/feat/fleet-migrate/docs/checkins/2026-11-06-ebd6ed1a.md

### D27. f111c672

D27a Task: Coding bot link. [PR 233](https://github.com/djbclark/djbclark-ade/pull/233) and [PR 244](https://github.com/djbclark/djbclark-ade/pull/244) merged. 245 and 268 closed. frdminc/peer-link PRs 1 to 4 merged. The live round trip passed on 11-02.

D27b State: PR 269 has an open BLOCK.

D27c Footprint outside the repo: the `~/.local/bin/coding-bot` link, `~/.config/peer-link/{trust,peers}.json`, vault secrets, the mailbox repo, the bot box, the site-public item 40.

D27d Overlap: `bin/coding-bot` and its test are on the list.

D27e Recommendation: re-home PR 269 into peer-link, about 2 to 3 h. (iii) would be 3 to 5 h.

D27f Must-know: keep branch `coding-bot-peer-link`. Repoint the symlink and item 40 if coding-bot moves.

D27g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/f111c672/docs/checkins/2026-11-06-f111c672.md

### D28. ff08899e

D28a Task: load watcher "watch load t". Investigated the 11-06 wake storm (peak 394). The cause was the helm continue broadcast plus Chrome.

D28b State: the event was open at 10:30 (load 203, churn 76k). No all-clear yet.

D28c Footprint outside the repo: `watcher.json` and Tier 1 `load-spike-monitor-t`.

D28d Overlap: builds on load-watch, loadwatch, relay.py and load-watch admit.

D28e Recommendation: (iv).

D28f Must-know: the absolute plist path (B4a) and the clear command (B4b).

D28g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/ff08899e/docs/checkins/2026-11-06-ff08899e.md

### D29. w20:pN

D29a Task: aiuse features (provider select, TUI header, the opencode rename, deepseek/codewhale). Done at 79c0797.

D29b State: clean.

D29c Footprint outside the repo: the aiuse cache.

D29d Overlap: none (relay.py and fleet.py calls).

D29e Recommendation: (iv).

D29f Must-know: relay 20261106-104034-7945bb is pending.

D29g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-pN/docs/checkins/2026-11-06-w20-pN.md

### D30. w20:pQ

D30a Task: blank Paseo OpenCode dropdown. Fixed by hand. Filed getpaseo/paseo issue 8780. PR 281 adds the patch to `bin/opencode-plugin-guard`.

D30b State: PR 281 is open with CI green and adversary APPROVE. local-review was blocked by load.

D30c Footprint outside the repo: a one-time hand patch (Paseo reverted it) and a site-private memory note.

D30d Overlap: `bin/*opencode*`, docs.

D30e Recommendation: (i) if opencode support goes, else (iii), 15 to 25 min plus 5.

D30f Must-know: relay 20261106-103419-be8b11 is pending.

D30g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-pQ/docs/checkins/2026-11-06-w20-pQ.md

### D31. w38:p8

D31a Task: Pi first-class in ADE. PRs [273](https://github.com/djbclark/djbclark-ade/pull/273), [274](https://github.com/djbclark/djbclark-ade/pull/274), [275](https://github.com/djbclark/djbclark-ade/pull/275), [276](https://github.com/djbclark/djbclark-ade/pull/276), [277](https://github.com/djbclark/djbclark-ade/pull/277) and [280](https://github.com/djbclark/djbclark-ade/pull/280) merged. aiuse 3.14.0.

D31b State: nothing in flight. One open item outside the repo: the `~/AGENTS.md` item 15 edit, blocked on quota.

D31c Footprint outside the repo: the Pi subagent symlink, the `hand` links, Pi profiles, CodexBar openai enabled, aiuse.

D31d Overlap: central to non-Claude TUI support, acp-run, acp-dispatch, session-finder, autorename, route_agent and self-slash.

D31e Recommendation: (iv). Keep agent_guard.py.

D31f Must-know: symlinks dangle if the repo paths move. Do not message ebd6ed1a again without new content.

D31g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w38-p8/docs/checkins/2026-11-06-w38-p8.md

### D32. w20:p0

D32a Task: get DeepSeek Harness (`dsh`) working (native binding repair, secretspec wrapper, YOLO cordis patch, zsh `dsh()`). Then reported dsh lessons to 0dc43dbd and reverted an uncommitted `ensure_dsh_wrapper` hunk on its instruction.

D32b State: dsh boot and chat verified. Site-public 3913c57 is on origin. No djbclark-ade edits.

D32c Footprint outside the repo: see B8f.

D32d Overlap: none in the repo. The dsh work is the non-Claude TUI area the retirement covers.

D32e Recommendation: (ii), done.

D32f Must-know: `ade-git-guard` and `deadline` are not on PATH. Its report says the shared-checkout stash list was empty, while every other report shows `prwait-wip2`.

D32g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-p0/docs/checkins/2026-11-06-w20-p0.md

### D33. w20:p12

D33a Task: none assigned. It answered the 0dc43dbd retirement survey (`ack tr-w20p12`, no overlap), the helm stop, and this check-in.

D33b State: report only.

D33c Footprint outside the repo: none.

D33d Overlap: none.

D33e Recommendation: (ii).

D33f Must-know: it saw the dirty shared `.gitignore` `+.aider*` become djbclark's local commit 9946ed38 (section F6).

D33g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-p12/docs/checkins/2026-11-06-w20-p12.md

### D34. w20:pS

D34a Task: issue 278 architecture and path forward. Wrote the checkpoint and recovery contract. [PR 282](https://github.com/djbclark/djbclark-ade/pull/282) merged 8a3b2c8a, with CI, adversary and local Codex review clean. Docs only.

D34b State: nothing in flight. Branch docs/278-recovery-architecture is clean; its two commits show only because of the squash merge.

D34c Footprint outside the repo: claims codex-278-recovery (released) and checkin-w20-pS (active), bigteam, local-review and pr-wait state, /tmp files. Provider logs under `~/.omp/logs` may hold sensitive data and must not be bulk-published.

D34d Overlap: docs only (README, checkpoint.md, context-hygiene.md, paseo-only-rearchitecture.md, queue.md). `docs/checkpoint.md` plans to retire acp-dispatch and acp-run after migration.

D34e Recommendation: (ii), zero time.

D34f Must-know: keep both worktrees and branches. Note that 01BvGHM3 (PR 290) also edits `docs/checkpoint.md` sections F and G.

D34g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-pS/docs/checkins/2026-11-06-w20-pS.md

### D35. w20:p11

D35a Task: fix the YAML front matter of the OpenCode `/hand` command and add its changelog fragment. [PR 286](https://github.com/djbclark/djbclark-ade/pull/286) merged 2026-11-06 after local-review and an adversary marker.

D35b State: nothing in flight. Branch `fix/opencode-hand-frontmatter` at 3dbc039e kept, not deleted.

D35c Footprint outside the repo: `~/.config/opencode/command/hand.md` carries the same YAML fix, applied live. An earlier Venice/OpenCode setup (`~/.local/bin/venicecode` wrapper, isolated `XDG_CONFIG_HOME`) was never committed anywhere.

D35d Overlap: builds on `opencode/commands/hand.md` (non-Claude TUI support). Keep it consistent with `docs/hand-alias.md` wherever commands end up.

D35e Recommendation: (ii), zero time.

D35f Must-know: nothing running, no claims, no schedules.

D35g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/w20-p11/docs/checkins/2026-11-06-w20-p11.md

### D36. c688cc (answering for 7c54a88c)

D36a Task: formatted one Herald speech message for the watch agent about the tendcf Q10 CMDB loader interlock question. Done. No queue entry or PR.

D36b State: reports a clean shared checkout with no worktrees, no stashes and no divergence from origin/master. That conflicts with every other report (the shared checkout has 9946ed38 ahead, stash `prwait-wip2` and over 100 worktrees), so treat its section c as unreliable.

D36c Footprint: none, in or outside the repo.

D36d Overlap: none.

D36e Recommendation: (iv), no changes made.

D36f Must-know: nothing running, no claims, no schedules.

D36g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/c688cc/docs/checkins/2026-11-06-c688cc.md

### D37. ed6863c7

D37a Task: wind-down after the 2026-11-02 quota exhaustion. It committed the `.gitignore` change (ignore `.aider*`) as 9946ed38 and pushed it as branch `gitignore-aider`.

D37b State: says the shared checkout is clean, no PRs, nothing running. It does not mention that 9946ed38 also sits as a local commit on the shared checkout's master (see F1).

D37c Footprint: `.gitignore` only.

D37d Overlap: none.

D37e Recommendation: (i) stop and discard; `gitignore-aider` can be reviewed on its own.

D37f Must-know: nothing running, no claims, deadlines or schedules.

D37g Report: https://github.com/djbclark/djbclark-ade/blob/checkin/ed6863c7/docs/checkins/2026-11-06-ed6863c7.md

## E. Held decisions for djbclark

### E1. From 0dc43dbd (agent-TUI retirement; reply as `ack tr-7c58015b`)

E1a Q1, machine-side uninstall of retiring TUIs (binaries, crush-acp/venicecode forks, brew-fast-upgrade passes, shell wrappers, Paseo providers qwen-code and glm-acp-agent; local state backed up first). Options: 1 yes, all decided (rec). 2 yes, list first. 3 no (the router keeps a never-route list).

E1b Q2, muse. Options: 1 retire (rec; unused, disabled since 10-08). 2 keep.

E1c Q3, 147 private memory notes that mention retired TUIs. Options: 1 move to an archive folder agents do not read (rec; the lessons are in docs/tui-lessons-learned.md). 2 leave. 3 delete.

E1d Q4, the bin/ade-backup-stores credential exclusions. Options: 1 keep as a named exception (rec). 2 remove after uninstall.

E1e Q5, copilot CLI fallback. Options: 1 the fallback is Paseo's Copilot provider; remove copilot CLI support (rec). 2 keep the copilot CLI.

E1f Note: 0dc43dbd said work on already-decided TUIs would start without waiting. The 2026-11-06 pause supersedes that.

### E2. From 1e61c979: D1 probes T9 (schedule across sleep) and T10 (which creation paths open a Desktop tab)

E2a Options: 1 unattended; T10 via an isolated test daemon plus paseo-screen; T9 via one `pmset sleepnow` at a time djbclark picks (rec). 2 T10 on the live Desktop with a throwaway agent while djbclark watches; T9 as in 1. 3 skip both and move to D2.

### E3. From ebd6ed1a (fleet-migrate, branch feat/fleet-migrate at 7be0d42b)

E3a Context: full Linux CI passed at fb776204, and 98 migration tests passed at e6fd50a0. The brief allowed only a Pi/Astra frontier review, and acp-dispatch refuses Pi as frontier-ineligible.

E3b Options: 1 authorize an ordinarily admitted Claude Opus high read-only adversary route, then continue offline implementation and CI only (rec). 2 keep Pi/Astra only and wait for normal admission. 3 narrow to an offline-contract-only PR, still with independent current-head review.

### E4. From f111c672 (reply as `ack dann-eve-cutover`)

E4a Question: should Dann 7 move Dann<->Eve onto frdminc/peer-link now? The Coding link has run on peer-link since 11-02. peer-link fixes two live security holes in techno-euphora's copy: secret theft through registry.json, and ssh_dir injection.

E4b Options: 1 yes, start the cut-over as one Dann 7 slice and remove peer-comms only after Dann<->Eve passes end to end (rec). 2 not yet; wait for PR 269 and a few more days. 3 no, keep techno-euphora's copy for good.

### E5. From 3ac46de6 (tendcf Q9; reply as `ack tendcf-q9-3ac46de6`)

E5a Context: pastebin's goal file still carries fixture trust (tier consented, local_yes_required true, dummy advisor and host keys).

E5b Q9a, consent tier. Options: 1 operator, local_yes_required false (rec; djbclark's own VM, and the only tier the first build serves). 2 managed, false. 3 managed, true (the first build refuses this until Step 9).

E5c Q9b, device identity key (ed25519, goal file `host`). Options: 1 generate it in the first build's install step, root 0600 in /opt/tendcf/var, with the public half put into the goal file by a reviewed PR before the first adopt (rec). 2 generate it now by hand over SSH. 3 keep the dummy until DC-1 enrollment is designed.

### E6. From bcff073a (reply as `ack paseo-8780-resume`)

E6a Context: a new getpaseo/paseo issue 8780 comment (another Linux/Bun stale-binding confirmation). Brief: `~/.local/state/fleet-watch/upstream-paseo-paseo-8780-20261106t153851-relay.md`.

E6b Options: 1 keep idle and defer the event (rec under the stop). 2 authorize resuming preparation for this event only, then stop.

### E7. From w20:pQ (reply as `ack bridge-guard-lr281`)

E7a Context: [PR 281](https://github.com/djbclark/djbclark-ade/pull/281) is open at c8403793 with CI green and an adversary APPROVE marker. bin/local-review was refused twice by the load gate (load 130 to 230, from the lead's mass wake). Load is now about 18.

E7b Options: 1 wait and rerun local-review later, no bypass (rec). 2 local-review with --no-load-gate now. 3 merge on CI plus adversary only, waiving the review rule. 4 investigate the load first, then retry.

E7c New: the w20:pQ report adds that PR 281's fate depends on whether opencode support survives the split. If it does not, (i) discard.

### E8. New questions raised by reports

E8a 9e5b46d1: stop the redundant read-only adversary round `adversary-pr254f`? It asks for "the word" to reap it.

E8b PR 254 readiness: 9e5b46d1 and ac95a703 say merge-ready, but 1e61c979 says a real Cursor security finding blocks it. Update 11:20: 9e5b46d1 now agrees head e0250889 is not merge-ready (an open Cursor Security MEDIUM thread) and offers to repair it after the pause.

E8c f111c672: re-home PR 269 into frdminc/peer-link and keep only a short `tell-coding-bot` skill in djbclark-ade, or drop it?

E8d 1e61c979: the lander and feeder stay booted out until told. Resume them or retire them?

E8e 0dc43dbd: fold the unfinished TUI retirement (wave 3 and later) into the split, using `tui-retire/PLAN.md`?

E8f 01BvGHLzD4: the `/retro` PR-title trust ruling.

E8g 501a7e0d (handed to 0dc43dbd): link a Claude Console org for omp's monthly API credit; Cursor fallback via the Cloud Agents API and xAI via opencode; an acp-run guard refusing omp/opencode while a Cursor, Antigravity or Anthropic-subscription login is active.

E8h 1e61c979 and 7c58015b: the fate of PRs 208, 214, 260, 261 and identity-intervening-agent depends on which of acp-run, acp-dispatch, route_agent, the quota gates and session-finder survive.

E8i 01BvGHLy: whether 292 and 293 are closed or rebased depends on whether load-watch, claude-quota-guard, coding-bot and acp-dispatch survive.

E8j 2b4437d2: djbclark's yes to swap the live herdr-harness plugin for the real-shell trial.

E8k 0dc43dbd: whether bin/pr-policy moves out with the non-ADE parts.

### E9. djbclark's answers, 2026-11-06 about 11:20 (relayed to each agent; all stay paused)

E9a adversary-pr254f: let it finish. Moot: 9e5b46d1 had already stopped it on 1e61c979's earlier order, with no report; not re-run.

E9b paseo#8780 (bcff073a): defer, stay idle.

E9c PR 281 (w20:pQ): wait until after the split; its fate follows whether opencode support survives.

E9d D1 T9/T10 (1e61c979): unattended, after the pause lifts.

E9e fleet-migrate (ebd6ed1a): shelve; keep the branch and re-scope after the split.

E9f Dann<->Eve (f111c672): yes, move it onto frdminc/peer-link as one Dann 7 slice; remove techno-euphora peer-comms only after an end-to-end pass. Dann 7's tab is closed; the slice waits.

E9g tendcf Q9 (3ac46de6): Q9a operator tier, local_yes_required false; Q9b generate the device key in the first build's install step.

E9h TUI retirement (0dc43dbd): Q1 yes, uninstall all decided TUIs (local state backed up first); Q2 retire muse; Q3 move the 147 notes to an archive folder agents don't read; Q4 keep the ade-backup-stores credential exclusions as a named exception; Q5 the fallback is Paseo's Copilot provider, and copilot CLI support is removed.

E9i The unfinished TUI retirement (wave 3 and later) is folded into the split session's scope, using `~/.local/state/bigteam/tui-retire/PLAN.md`.

E9j PR 269 (f111c672): re-home the wrapper into frdminc/peer-link; djbclark-ade keeps only a short `tell-coding-bot` pointer skill. After the pause: one repair round there, repoint `~/.local/bin/coding-bot` and home-agents.md item 40, close PR 269 with a pointer.

E9k Lander and feeder (1e61c979): stay booted out until the split ends, then decide.

E9l Still open: E8f to E8k (they depend on what the split keeps).

## F. Unowned items

F1 The shared checkout `~/src/djbclark-ade` master carries local unpushed commit 9946ed38 "Ignore aider editor files" (author Daniel JB Clark, 2026-11-06 10:44, per ff08899e and ce04246a). Owner resolved: ed6863c7 says it made this commit and pushed it as branch `gitignore-aider` (D37), so it was committed in the shared checkout, against standing order 9. 0dc43dbd, 19ece915, 1e61c979, 23adbb25, 7c96a0ca, ce04246a, ff08899e and w38:p8 each say it is not theirs. Decision needed: land `gitignore-aider` by PR, or drop it, then reset the shared checkout's master to origin/master.

F2 Stash `prwait-wip2` (`stash@{0}: On prwait-adversary-gate`). No reporting agent owns it.

F3 `.n2-mask-evidence/` in `~/src/te-async-wt`. Reports disagree. 0b68fe51 lists its own probe files there. ba920539 says it was "not created by me" and must not be removed on its authority. So it belongs to 0b68fe51 by that report, but no one has decided its disposition.

F4 The uncommitted 3-line change in `tests/test_acp_dispatch_refused_resume.py` in `~/src/djbclark-ade-route-scope-wt`, made by 1e61c979's slice and left as is.

F5 ` M .cursor/hooks.json` (a graft hook path rewrite) in `~/src/djbclark-ade-habits-subshell-wt`. Both 9e5b46d1 and ac95a703 say it is not theirs.

F6 An earlier ` M .gitignore` in the shared checkout. ce04246a says it is now gone. f111c672, ebd6ed1a and w20:pS also saw it and say it is not theirs. w20:p12 reports that this dirty `+.aider*` change became djbclark's local commit 9946ed38 (F1).

F7 Worktree `~/src/djbclark-ade-dispatch-notice-wt` and branch fix/dispatch-completion-notice belong to c987a634, which did not report (bcff073a).

F8 Claim `pr254-nested-backticks-ac95a703` is still active after the ownership transfer to 9e5b46d1 (ac95a703).

F9 Stale `admit-wait-257` deadline record (state done), seen in 01BvGHLzD4's container.

F10 Untracked `.ignore` and `graft/` in `~/src/paseo` and `~/src/herdr4paseo`, and `.ignore` in `~/ops/site-dann`. Reports 1057582a, 2507bcbf, 3846a46e and 042d0c8d say these are not theirs.

F11 Plektra `~/src/plektra-djbclark` has ` M .gitignore` and `?? .codex/` from before c3cbe51a's work.

F12 Branch `claude/issue-279-linux-ports` (superseded) and the `-1-sched` base branch. Owner 01BvGHLy; listed here only because of the deletion ordering rule (C2).

## G. djbclark's manual items

G1 Click Install on the RemoveMacAI profile in System Settings. `removemacai off` has not deleted anything yet (32779db2).

G2 Paste for the pastebin sudo-secretspec upgrade (pastebin is on .4, the others are on .5) (042d0c8d).

G3 Phone wireless debugging for c3cbe51a. adb has been disconnected since the Paseo restart, and the Beeper newline needs a live key capture.

G4 paseo4herdr: the Paseo GUI check and the real-shell trial (yes to swap the live plugin) (2b4437d2).

G5 fresh-worktrees 3.1.1 apply, and paseo-runner stage 2 (tabbed UI). 1057582a also lists a phone-side check that Settings, Plugins lists all 14 plugins.

G6 Data volume is 96% full (20 GB free). The cause was not investigated (32779db2).

G7 Answer the held decisions in section E. In particular T9 needs a `pmset sleepnow` time that djbclark picks (E2).

G8 The shared checkout commit 9946ed38: push it or drop it, at djbclark's discretion (23adbb25).

G9 The `~/AGENTS.md` item 15 edit (copy / copy-colors meanings) needs Opus 5.5 or better and is blocked on quota (w38:p8).

## H. Stragglers

H1 Checked the directory against the expected set: 32779db2, 7c54a88c, ed6863c7, w20:p0, w20:p11, w20:p12, w20:pM, w20:pS, w36:pB, w38:p8.

H2 Present: 32779db2, w38:p8, and the late arrivals w20:p0, w20:p12, w20:pS and w20:p11.

H3 Absent at 11:30: w20:pM and w36:pB (herdr panes; delivery unverified, not resent). The request to 7c54a88c was answered by Paseo agent df4a2ed6 as c688cc (D36); ed6863c7 answered as Paseo agent 7df4c112 (D37).

H4 Not asked on purpose: Dann tabs 428f5f02, 193014a8 and d2a505dd (techno-euphora only).

H5 Others named in reports but without a report: c987a634 (predecessor of bcff073a), d8891c91 ("watch load s", replaced by ff08899e), 1d003359 (predecessor of 9e5b46d1), and 01BvGHLzKz (the cloud lead, whose report was not in this directory).

## I. Cross-cutting findings

I1 `ade-git-guard claim ls` does not exist. It falls through to `git claim` (0dc43dbd, 1057582a, 3846a46e, 501a7e0d, 7c96a0ca, ce04246a, ff08899e, c3cbe51a, 9e5b46d1). The working listing is `bin/ade_claims.py list` (w38:p8, 19ece915, ebd6ed1a).

I2 `deadline` and `ade-git-guard` are not on PATH for some agents (2b4437d2, 32779db2, 23adbb25, ba920539, bcff073a, 9e5b46d1, w20:pN). Others ran `bin/deadline ls` by repo path. Several agents warn that the fleet-wide `deadline ls` output is very large and should be filtered (6eb6d3f6, 0b68fe51, ac95a703).

I3 relay.py is the most shared dependency. It hung or timed out for 042d0c8d, 2507bcbf, c3cbe51a and 19ece915. Several acks are queued and unverified: 20261106-102251-406062, 20261106-102716-45a8a6, 20261106-104034-7945bb, 20261106-103419-be8b11, 20261106-095032-c8117e, 20261106-095208-37438c, 20261106-095422-b9997c, 20261106-102800-e5f4e6.

I4 Tools that projects outside djbclark-ade depend on:
I4a tendcf and nix2cf: acp-dispatch `--kind frontier`, acp-run, relay.py, route_agent and the quota gates, load-watch admit, deadline, session_log.py, cfenginewatch.
I4b CFEngine: cfenginewatch, watch, fleet-watch.
I4c Paseo upstream: paseowatch.
I4d Plektra: acp-dispatch, relay.py, autorename, self-slash.
I4e paseo4herdr: acp-dispatch, relay.py, self-slash.
I4f Pi: the pi/ extension, `hand` links, agent_guard.py.
I4g sudo-secretspec, aiuse, paseo-runner: relay.py only, plus acp-dispatch/acp-run as a client.

I5 Stale CLAUDE_CODE_SESSION_ID: a /baton successor keeps its predecessor's id. PR 259 fixed autorename only. relay.py, fleet.py, session-find.py and ade_claims.py still trust the env var, and the `backend_for` tie-break still reads it (7c96a0ca). A related mis-attribution bug from PR 248 is the target of identity-intervening-agent (1e61c979).

I6 Worktree counts disagree because they were taken at different times: 89 (7c58015b), 92 (0dc43dbd), 104 (9e5b46d1), 108 (1e61c979 and w20:pQ), 115 before its own (w38:p8). w20:pQ counted 25 `checkin-*` worktrees among its 108. 1e61c979 says most belong to other sessions or finished slices. Since 31 reports used a check-in worktree or branch, about 30 of the latest count are check-in worktrees. The rest are a mix of live PR worktrees (sections C and F) and finished slices. No report counted the stale ones exactly.

I7 The load gate was the main blocker on 11-06. The helm "continue" broadcast woke about 25 agents and pushed load to 394 (ff08899e). That blocked 0dc43dbd wave 3, 1e61c979's slices, the f111c672 repair, w20:pQ local-review and the 6eb6d3f6 slice. PR 294 adds a stagger rule.

I8 Adversary markers go stale after a master merge. PRs 291, 292, 293 and 290 all need a re-confirm on the current head before merge.

I9 Three Claude Code cloud sessions (01BvGHLy, 01BvGHLzD4, 01BvGHM3) touched nothing on the Mac. Their work is only in PR branches.

I10 Many agents never edited djbclark-ade and use it only as a toolbox: 042d0c8d, 0b68fe51, 1057582a, 19ece915, 23adbb25, 2507bcbf, 2b4437d2, 3846a46e, 6eb6d3f6, ba920539, bcff073a, c3cbe51a, ce04246a, ff08899e, w20:p0, w20:p12, w20:pN.

I11 Where the split itself would do planned work: if non-Claude TUI support is deleted wholesale, that covers most of 0dc43dbd's remaining retirement waves. Several items survive the split as Paseo-native ADE core: ade-recovery (290), D1 (d1-prep), pr-policy and ade-sched.
