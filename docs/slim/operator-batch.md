# Operator batch for the final merge (compiled 2026-11-07)

Compiled from `docs/slim/log.md`, the twelve reports under `docs/slim/reports/` and `PLAN.md` F (Wave 6). Four phases, labelled A to D; every item is one line: what, the exact command where a source gives one, the source in parentheses, "(decision)" where you choose. "Unverified" is kept wherever a source says it. Nothing here was run; the commands are copied, not tested.

Two placements differ from a literal reading of the request, both because a source says so:
- The throwaway-PR tests T0-T3 and the ruleset sit in **B** (after the final PR is on master), not A: `workflow_run` runs master's copy of the workflow, so the Action cannot run for any PR before the merge (wave4-E8 E3, E4). The App (E1) and the environment (E2) stay in A.
- Hook-line edits (the C2 list) and the `launchctl bootout` calls come first in **C**, before `ade update`; wave3-E3 F1 and wave3-E4 F1 say a left-over hook line runs a missing script on every prompt or Stop once the files are gone, so do them ahead of `ade update` (or earlier, in A, if you prefer).

## A. Before the final merge reaches the Mac

Paseo daemon, plugins, resume, quota pause
- A1. Upgrade the Mac's Paseo daemon to 0.15.x in a quiesced window per `docs/queue.md`; an unfinished turn is lost on restart until terminal persistence is verified (PLAN.md F Wave 3 row; evidence F recorded 0.14.x).
- A2. Install the J6 plugins, each after reading the Sonnet source summary (trusted, unsandboxed daemon code): tell-agent, asks, questions-please, baton, session-guard, usage-auto-resume, vitals, skills, pr-radar, session-janitor, plan-auto, zerosub (only if you run several Claude subscriptions), `getpaseo/claude-code-entrypoint-env`, and `sm1ee/session-recovery` as the thirteenth (PLAN.md J6, I3; wave4-E7 H2).
- A3. Install asks and questions-please at least a day before the helm deletion lands; the one still used after a week stays, the other goes in the follow-up PR (D5) (wave3-E4 F4; PLAN.md J6).
- A4. Keep Paseo's native "Resume agents after restart" OFF while evaluating `session-recovery` (PLAN.md J6, I4).
- A5. Verify session-guard and usage-auto-resume live: a session that hits the Claude limit pauses and continues after the reset; the quota deletions (E7) depend on it (wave4-E7 H2; PLAN.md D4).
- A6. One bounded native-resume trial: turn it on for one daemon restart in a quiet window, fleet idle, `load-watch admit` refusing launches; leave it ON if it behaves, turn it OFF after a mass wake; the write-up must say the trial cannot show the busy-fleet mass wake; the result decides parked PR 290 (operator decision 4a, 2026-11-07: run it) (PLAN.md J6, J9, I4).
- A7. Verify for one day before the REPLACE deletions merge (PLAN.md F Wave 3 row).

GitHub merge gate (App and environment; the order is wave4-E8 E4)
- A8. Create the GitHub App `ade-merge-gate` in the GitHub UI (Settings, Developer settings, GitHub Apps): webhook inactive; Commit statuses read and write, Checks read and write, Pull requests read-only; "Only on this account"; note the App ID and Client ID; generate a private key; install on `djbclark-ade` only; check with `gh api repos/djbclark/djbclark-ade/installation --jq '.app_slug, .app_id'` (wave4-E8 E1).
- A9. Create the `merge-gate` environment limited to `master`: `echo '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' | gh api -X PUT repos/djbclark/djbclark-ade/environments/merge-gate --input -`, then `gh api -X POST repos/djbclark/djbclark-ade/environments/merge-gate/deployment-branch-policies -f name=master -f type=branch` (wave4-E8 E2). No required reviewers on it.
- A10. Store the key and client id: `gh secret set MERGE_GATE_PRIVATE_KEY --env merge-gate --repo djbclark/djbclark-ade < ~/Downloads/ade-merge-gate.*.private-key.pem` and `gh variable set MERGE_GATE_CLIENT_ID --env merge-gate --repo djbclark/djbclark-ade --body '<the Client ID, Iv23...>'`; then `rm ~/Downloads/ade-merge-gate.*.private-key.pem` (or keep it in `sudo-secretspec`, never in a tracked file) (wave4-E8 E2).
- A11. Confirm the Tests check names the ruleset will pin (expect `pytest-linux 15368`, `context-policy 15368`): `gh api repos/djbclark/djbclark-ade/commits/$(git rev-parse origin/master)/check-runs --jq '.check_runs[] | [.name, .app.id] | @tsv'` (wave4-E8 E2).

Web search stack (must precede `ade update`)
- A12. Nothing to do (operator ruling 2026-11-07, step 6: keep `bin/firecrawl-router` in djbclark-ade): `com.djbclark.firecrawl-mcp` keeps running the router through the `~/.local/bin/firecrawl-router` symlink, and Hermes keeps its 18805 backend; `ade update` leaves the router in place. Check after the merge that `curl -i http://127.0.0.1:18804/mcp` still answers (wave3b G8 superseded).

site-djbclark edits (order 11: each needs your explicit yes)
- A13. Edit the site-djbclark consumers of the retired `web-get` and the `fallback-chains` ladder only (the router stays): `skills/firecrawl/SKILL.md` (its `web-get` mentions), `home-agents.md:24`, `cursor/home-agents.mdc:311`; `roles/shared_mcp` and `skills/firecrawl/scripts/live-suite/common.py` need nothing (decision, order 11).
- A14. Fix `fleet-watch:120`, which still says "Skill: /paseowatch." (a deleted skill) (wave3b B, G5).
- A15. Decide whether the `paseo` profile gets a worker fallback (`UPR_FALLBACK=worker`), a site-djbclark change (wave3b B, G5) (decision).
- A16. Decide whether to add the four moved tests (`tests/test_barnowl_skill.py`, `tests/test_bigteam_prune.py`, `tests/test_change_hermes_{auto,lock}.py`) to a site-djbclark workflow; none runs in CI there today (wave2-E1 E24) (decision).
- A17. Optional: reword `home-agents.md:52`, `cursor/home-agents.mdc:41` and `roles/site_agents/README.md:21-26,59` (they describe the old relay router and sweep) (wave3-E3 F4e) (decision).

Final PR merge gate: C7 and C1 re-run on the Mac, output pasted into the final PR (PLAN.md F Wave 6, I8; the commands are the Wave 2 batch's, in log.md)
- A18. C7.1 sleeping herdr panes: `~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper list` and `... log | tail -20`; expect nothing sleeping or orphaned (log, Wave 2 batch 1).
- A19. C7.2 resumable acp-dispatch records: `ls -la ~/.local/state/bigteam/*/jobs/ | grep -v '\.done'` and `launchctl list | grep -i acp-dispatch`; expect every record `.done` and no launchd job, no `acp-dispatch.*` runner or `auto-resume` one-shot label (log, Wave 2 batch 2; wave4-E6 J1).
- A20. C7.3 worktrees and pastures: `git worktree list`, then `git -C PATH status --short` per path, and `cow list --json`; a dirty one is its owner's to migrate or yours to waive by name (log, Wave 2 batch 3; the log notes `bin/cow-pasture ls` and `acp-dispatch ls` do not exist).
- A21. C7.4 queued relay acks: `relay.py --pending --summary`; expect empty, or retire each with `relay.py --retire ID --reason "slim-down C7"` (log, Wave 2 batch 4). Run it before the merge: the shim has no `--pending`.
- A22. C7.5 bigteam inboxes: `find ~/.local/state/bigteam -name 'inbox*' -type f -newer ~/.local/state/bigteam`; expect none (log, Wave 2 batch 5).
- A23. C1 live jobs and processes: `launchctl list | grep com.djbclark` and `pgrep -fl 'acp-run|acp-dispatch'`; expect deadline-sweep, pr-policy, load-watch listed and no acp-run process (log, Wave 2 batch 6).
- A24. Adhoc adversary record: `ls ~/.local/state/bigteam/adhoc-2026-11-02/jobs/` and `launchctl list | grep adversary-pr254f` (log, Wave 2 batch 10; passed 2026-11-06, re-run for the gate).
- A25. Paste the output of A18-A24 as one block into the final PR (PLAN.md F Wave 6).

## B. At the merge

- B1. Merge site-djbclark's intake branch `slim-intake/2026-11` into its master (a direct-commit repo; the five files edited outside the moved set are AGENTS.md, bin/bg-offload, claude/README.md, cursor/home-agents.mdc, roles/watchdogd/templates/watchdogd.d/hermes-quota.toml.j2), then pull it on the Mac at `~/ops/site-public-djbclark`, before `skill-everywhere --all` in C (wave2-E1 E; log "Operator batch for the final merge" 1).
- B2. Check the final PR carries the adversary marker for its current head (`<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->`), CI green, A25 pasted (AGENTS.md code-review rule 1; PLAN.md J7).
- B3. Merge the final PR: `gh pr merge N --squash --match-head-commit <reviewed sha>`; remove worktrees and branches only after `gh pr view N --json state` reads `MERGED` (AGENTS.md rule 1; PLAN.md J7).
- B4. Tag the merge (decision): the sources give no tag name or command for the final merge; the earlier `pre-slim-2026-11-06` tag was pushed with `gh api` because the cloud proxy drops tag pushes (log, Wave 0).
- B5. Delete the `slim/*` branches after MERGED; command form unverified in the sources (the earlier deletions were done with `gh api`) (PLAN.md F Wave 6; log, Wave 0 step 3a).
- B6. Test T0 without the ruleset (statuses appear): worktree `throwaway/marker-approve`, a draft PR whose body carries an APPROVE marker for its head, then `gh run list --workflow adversary-marker.yml --limit 3` and `gh api "repos/djbclark/djbclark-ade/commits/$H/statuses" --jq '.[] | [.context, .state, .creator.login] | @tsv'`; expect `adversary-marker success ade-merge-gate[bot]` (full commands: wave4-E8 E3 T0).
- B7. Create the ruleset: write `/tmp/ruleset.json` (`bypass_actors` empty; required checks `adversary-marker` pinned to the App ID, `pytest-linux` and `context-policy` pinned to 15368), `sed -i.bak "s/APP_ID/<the App ID>/" /tmp/ruleset.json`, `gh api -X POST repos/djbclark/djbclark-ade/rulesets --input /tmp/ruleset.json --jq '.id, .enforcement'`, `gh api repos/djbclark/djbclark-ade/rules/branches/master --jq '.[] | .type'` (JSON in full: wave4-E8 E5).
- B8. Re-check T0 under the ruleset: `gh pr view N --json mergeStateStatus,statusCheckRollup` must not show `adversary-marker` expected or missing; if it does, apply C6 (uncomment `MARKER_POST_AS: check-run` in the `marker` job's last step, land it as a PR) and re-run `gh workflow run adversary-marker.yml -f pr=N` (wave4-E8 E3 T0; research item 18 is unverified).
- B9. T1: a throwaway PR that edits `adversary-marker.yml` into an always-green job; expect `BLOCKED` and `gh pr merge N --squash --match-head-commit "$(git rev-parse HEAD)"` refused (wave4-E8 E3 T1).
- B10. T2: a throwaway PR adding `.github/workflows/spoof.yml` with `permissions: {statuses: write}`; expect `BLOCKED` and the merge refused (wave4-E8 E3 T2).
- B11. T3: a fork PR at the same sha as T0's head from a second GitHub account; expect `failure` "marker not written by a trusted user" (it can turn our head red, never green) (wave4-E8 E3 T3).
- B12. Clean up each throwaway: `gh pr close N --delete-branch`, then `git -C ~/src/djbclark-ade worktree remove ~/src/djbclark-ade-tmK-wt`; delete the three branches if `--delete-branch` did not (wave4-E8 E3, G4).
- B13. Optional: if branch protection also lists required status checks, remove them once the ruleset is verified; check with `gh api repos/djbclark/djbclark-ade/branches/master/protection/required_status_checks --jq '.checks'` (404 = none) (wave4-E8 E6).

## C. After the merge, on the Mac

Hook lines in `~/.claude/settings.json` (the C2 list), before `ade update`
- C1. Remove the `jev_effort_hook.py` hook entry (`"$HOME"/ops/site-private/bin/hook-deadline 4 "$HOME"/.claude/hooks/jev_effort_hook.py`) and `rm ~/.claude/hooks/jev_effort_hook.py` (wave2-E2 E2).
- C2. Remove the two live `prior_art_nudge.py` lines (PostToolUse/PostToolUseFailure and UserPromptSubmit) (wave3-E10 G2).
- C3. Remove the `relay_prose_nudge.py` Stop hook entry (wave3-E3 F1).
- C4. Remove the `autorename_nudge.py` UserPromptSubmit entry (wave3-E4 F1).
- C5. Quota nudge: remove the `quota_nudge.py` UserPromptSubmit line (`"$HOME"/ops/site-private/bin/hook-deadline 2 "$HOME"/src/djbclark-ade/claude/hooks/quota_nudge.py`) once session-guard is verified (recommended; it is inert now), and keep or drop `"$HOME"/.claude/hooks/cswap_quota_context.sh` (it reads `cswap`, not the guard) (decision) (wave4-E7 H4).

Stop the jobs and remove state, before `ade update`
- C6. Remove the harvested evidence dirs `~/src/djbclark-ade/.skillopt-sleep` and `~/src/djbclark-ade/.skillopt-sleep-handoff`, and the same in any live worktree (the two `.gitignore` lines then go in D4) (wave3-E10 G0).
- C7. `launchctl bootout gui/$UID/com.djbclark.claude-fleet-governor; launchctl bootout gui/$UID/com.djbclark.claude-quota-guard; rm ~/Library/LaunchAgents/com.djbclark.claude-fleet-governor.plist ~/Library/LaunchAgents/com.djbclark.claude-quota-guard.plist`; optional: `~/.local/state/ade/fleet-governor.json`, `quota-guard.json`, `gate-profile.json`, `gate-profile.log` (wave4-E7 H1).
- C8. `launchctl bootout gui/$(id -u)/com.djbclark.acp-dispatch-reap; rm ~/Library/LaunchAgents/com.djbclark.acp-dispatch-reap.plist`, after A19 shows no `acp-dispatch.*` runner left (wave4-E6 J1).
- C9. `launchctl bootout gui/$UID/com.djbclark.skillopt-sleep` and `rm ~/Library/LaunchAgents/com.djbclark.skillopt-sleep.plist`; `~/.local/bin/skillopt-sleep` (installed by `uv tool`), `~/.skillopt-sleep*` and `~/.local/state/skillopt-sleep` are yours to remove (wave3-E10 G1).
- C10. `launchctl bootout gui/$UID/com.djbclark.rumination-watch; rm -f ~/Library/LaunchAgents/com.djbclark.rumination-watch.plist` (wave3-E5 G2).
- C11. `launchctl bootout gui/$UID/com.djbclark.routing-recalibrate; rm -f ~/Library/LaunchAgents/com.djbclark.routing-recalibrate.plist` (wave3-E5 G3).
- C12. `launchctl bootout gui/$UID/com.djbclark.session-history-update; rm -f ~/Library/LaunchAgents/com.djbclark.session-history-update.plist` (wave3-E5 G4; wave3-E3 F2 is the same job).
- C13. `launchctl bootout gui/$UID/com.djbclark.context-budget; rm -f ~/Library/LaunchAgents/com.djbclark.context-budget.plist`; before `ade update`, because `context-budget-check uninstall` no longer exists (wave3-E5 G5).
- C14. The per-target CPU watchers (opencode-cpu-watch, codexbar-cpu-watch): `for l in $(launchctl list | awk '$3 ~ /^com\.djbclark\..*-cpu-watch$/ {print $3}'); do launchctl bootout gui/$UID/$l; rm -f ~/Library/LaunchAgents/$l.plist; done` (wave3-E5 G1; log Wave 2 batch 6).
- C15. The `watch` job from Wave 3b: the log lists "watch (Wave 3b)" but no label or plist path; the form would be `launchctl bootout gui/$UID/com.djbclark.watch` (unverified); also archive `~/.local/state/watch/` (log Wave 2 batch 6; wave3b G5).
- C16. Lander and feeder (J11, retire): `launchctl bootout gui/$UID/com.djbclark.ade-lander; launchctl bootout gui/$UID/com.djbclark.ade-feeder`, then remove both plists from `~/Library/LaunchAgents/` (path by the same convention, unverified); the scripts stay in `~/.local/state/bigteam/deepseek-review-2026-10-30/` as history (PLAN.md J11, F Wave 4 row).
- C17. `rm` the dangling `~/.local/bin/{web-get,web-digest}` (the `firecrawl-router` link stays: the router is kept, 2026-11-07) (wave3b G8).
- C18. `launchctl bootout gui/$(id -u)/com.djbclark.zcode-key-auth; rm ~/Library/LaunchAgents/com.djbclark.zcode-key-auth.plist; rm -r ~/.local/state/zcode-key-auth` (wave2-E9 D, zcode line).
- C19. `acpdispatch.n2maskfix.reset` is a one-shot that already exited; confirm with `launchctl list | grep n2maskfix` and remove its plist if still present (log Wave 2 batch 6; plist path unverified).
- C20. `sudo rm /etc/sudoers.d/acp-dispatch-pmset` (wave4-E6 J2).
- C21. `herdr plugin unlink djbclark.herdr-sleeper` (form unverified against herdr's CLI; check `herdr plugin --help`; drain sleeping panes first per A18) (wave2-E2 E1).

Update and relink
- C22. `ade update` (wave2-E1 E, step 2; it removes the moved directories, so their links dangle).
- C23. `~/src/djbclark-ade/bin/skill-everywhere report` first, then `~/src/djbclark-ade/bin/skill-everywhere --all`, which relinks the 14 moved skills from the site root `~/ops/site-public-djbclark/skills` (dialogue, research and retro call `report` by name); then `/reload-skills` in running Claude sessions (wave2-E1 E; log batch 1; wave3-E10 G3).
- C24. Relink by hand the five unlinked skills from their source repos (`~/src/sudo-secretspec/skills/sudo-secretspec`, `~/src/sipb-agent-skills/skills/{forgejo,hyades-docker}`, `~/src/loopback-port-shim/skills/forgejo-ci`, `~/src/sipb-llms/skills/sipb-llm-bench`) in every target skills dir, or `npx skills add` them (wave2-E1 E16).
- C25. `~/src/djbclark-ade/bin/skill-everywhere --remove siyuan siyuan-article-import siyuan-excalidraw siyuan-markdown`; reinstall with `npx skills add zhiluop/siyuan-skills` only where wanted (wave2-E1 E17).
- C26. Run `tools/book-to-kb/install.sh` in site-djbclark to repoint the `book-to-kb` links to the kept packaged tool (ruling D2 "keep the better one"; the moved skill copy was deleted) (log Wave 2 progress; batch 2).
- C27. Relink to site-djbclark (under `~/ops/site-public-djbclark`): `~/.local/bin/{swift,xcodebuild}` to `bin/heavy-shim`, `~/.local/bin/codium-ai` and `~/.local/bin/change-hermes` to `bin/`, `~/.claude/commands/teach.md` to `claude/commands/teach.md` (wave2-E1 E13, E18-E20).
- C28. `rm` the dead links `~/.local/bin/{jev,seat-name,ade-scan-state,cow-pasture}` and any `opencode-ralph-tui*` copies (wave2-E2 E3).
- C29. `rm` dangling links `skills-everywhere` and `skillopt-sleep` in every target skills dir (`~/.claude/skills`, `~/.agents/skills`, `~/.config/opencode/skills`, Hermes' external dir, `~/.grok/skills`, `~/.omp/agent/skills`), and `~/.claude/commands/{paseo-screen,retro,steps,skillopt-sleep,session-finder-all}.md` (wave3-E10 G3, G4; wave3-E3 F1).
- C30. `rm` dangling `~/.claude/skills/session-finder` and `~/.claude/skills/peer-relay` if `skill-everywhere` did not, and `~/.zcode/commands/session-finder{,-all}.md` if installed (wave3-E3 F1).
- C31. `rm` dangling `~/.local/bin/{self-slash,paseo-self,paseo-new-seat,paseo-bypass-watch,opencode-self-compact}` and the `helm`, `helm-all`, `autorename` command links under `~/.claude`, `~/.codex`, `~/.pi`, zcode and grok (wave3-E4 F2).
- C32. `rm ~/.pi/agent/extensions/autorename-bridge.ts ~/.omp/agent/extensions/autorename-bridge.ts` (Pi and omp load them at startup) (wave3-E4 F2b).
- C33. `find ~ -maxdepth 4 -type l -name loadwatch -path '*skills*' 2>/dev/null`, and `rm` each hit (wave3-E5 G8).
- C34. `rm` dangling `~/.agents/skills/ade-paseo*` and `~/.claude/skills/ade-paseo*` links (wave3b C).

Paseo skills and config
- C35. Paseo skill selection switch: `npx skills add getpaseo/paseo`, or switch each Paseo home's `agents.skills.selection` in `~/.paseo/config.json` from `{"mode":"custom","skills":[]}` to `{"mode":"all"}`; if upstream's broad triggers steal `handoff`/`dialogue` requests, narrow to `paseo`, `paseo-help`, `paseo-plugin` (decision) (wave3b C; `docs/skill-everywhere.md` 3a; `paseo reload` rejects a top-level `"skills"` key).
- C36. Done on the branch (2026-11-07, Wave 3b merge): the template's six overrides are renamed to Paseo's `paseo*` names, `user-invocable-only`; mirror that in the live `~/.claude/settings.json` when you install Paseo's bundle (C35).
- C37. Paseo `additionalDirectories` step: add `~/.local/state/bigteam` to the Claude provider's `additionalDirectories` override in Paseo's config, only if the first live `acp-dispatch` run (C68) asks before reading the brief or writing the report (the slice reads BLOCKED, exit 4) (wave4-E6 J4).
- C38. Remove glm-acp-agent's custom ACP provider entry from the Paseo home's `config.json` if one exists (wave3b G7).
- C39. Optional: `opencode auth login` and choose the zai coding-plan provider (key `ZAI_CODING_PLAN_API_KEY` via `sudo-secretspec`), then `opencode models`; add a routing row only if wanted (decision) (wave3b G6).

Hosts and services that name old paths
- C40. Repoint the Mac's `~/.ssh/authorized_keys` forced command for the Grok Bot box key to `/Users/djbclark/ops/site-public-djbclark/bin/change-hermes-ssh-gate` (wave2-E1 E20; log batch 4).
- C41. Pastebin (pastebin.xvm.mit.edu): its `authorized_keys` names `barnowl/scripts/bo-ssh` by the old path; point it at pastebin's own site-djbclark checkout (it needs one; SKILL.md:181 assumes the Mac layout) (wave2-E1 E2; log batch 4).
- C42. Re-render the watchdogd role on the Mac (the rendered `watchdogd.d/hermes-quota.toml` still names the old `change-hermes` path) (wave2-E1 E23; log batch 4).
- C43. Grok Bot box: its `skills-sync/sync.sh` reads djbclark-ade `origin/master` only, so the moved skills drop out unless it also reads site-djbclark (decision) (wave2-E1 E22; log batch 5).
- C44. Repoint `~/.local/bin/coding-bot` to the peer-link install once the transfer lands (E9j); it dangles until then (wave4-E6 J3).
- C45. Restart any running `nohup app-tamer-ab run` so it uses the new `bin/app-tamer-ab` path (wave2-E1 E21).
- C46. Load watcher: `~/src/djbclark-ade/bin/load-watch watcher show`; if it says "relay channel" or names a dead agent, from the load-watcher Paseo agent run `~/src/djbclark-ade/bin/load-watch watcher set --name "<title>"` then `~/src/djbclark-ade/bin/load-watch watcher test` (expect `sent to paseo <id>`) (wave3-E5 G7).
- C47. Find-and-tell live check: in a Paseo agent's worktree `timeout 120 sh -c 'while :; do :; done' &`, wait ~20 s, then `LW_STATE_DIR=$(mktemp -d) LW_LOAD_PER_CORE=0 LW_SUSTAIN_S=0 LW_MIN_CORES=0.5 ~/src/djbclark-ade/bin/load-watch sample --dry-run -v`; keep `--dry-run`; `com.djbclark.load-watch` needs no reinstall (wave3-E5 G9, G10).

Backups and archives (back up first, then archive; the sources give the tarball command only, no archive command)
- C48. Back up: `tar czf ~/tui-retire-backup-$(date +%F).tgz` of the directories listed in C49-C61 (wave2-E9 D); the Wave 3b form is `tar czf ~/tui-retire-backup-$(date +%F)-3b.tgz ~/.pi ~/.zcode` (wave3b G1); include `~/.grok` (wave4-E9c D1).
- C49. pi: `npm -g uninstall pi-acp @earendil-works/pi-coding-agent`; archive `~/.pi`; `rm ~/.pi/agent/prompts/hand.md` and the extension link `~/.pi/agent/extensions/subagent` (path inferred, check with `ls -l ~/.pi/agent`) (wave2-E9 D; wave3b G2).
- C50. zcode: `npm -g uninstall zcode-acp-server` and the zcode CLI (package `zcode-app-cli`, command unknown, look it up); archive `~/.zcode`; remove the links under `~/.zcode/commands/` (hand.md and the other nine) (wave2-E9 D; wave3b G3).
- C51. grok CLI: archive `~/.grok` (sessions, memory-v2, memtrace, worktrees.db); remove the `~/.grok/skills` links, `~/.grok/hooks` and the `~/.grok/config.toml` ignore entries; uninstall the grok CLI as installed (`npm`/`brew`/vendor installer, not determined); nothing for grok-bot (wave4-E9c D1-D4).
- C52. `~/.gemini`: archive the CLI leftovers only (`~/.gemini/settings.json`, `~/.gemini/tmp`, `~/.gemini/antigravity-cli`, `~/.gemini/oauth_creds.json` after confirming no tool uses it); never touch `~/.gemini/antigravity-acp` or `~/.gemini/antigravity` (kept by `bin/ade-backup-stores`) (wave3b G3; log "Review note", which corrects wave2-E9 D's wholesale `~/.gemini` archive).
- C53. agy: `brew uninstall` the agy CLI (cask/formula name: look it up); archive `~/.local/share/agy-acp-server` and `~/.local/share/agy-acp-home`; remove `~/.local/bin/refined-antigravity-acp` (wave2-E9 D, agy line, minus `~/.gemini`).
- C54. crush: remove `~/.local/bin/crush-acp`, `~/src/crush-acp`, `crush()` in `~/.bashrc`; archive `~/.config/crush`, `~/.local/share/crush`, `~/.local/share/crush-acp` (wave2-E9 D).
- C55. goose: `brew uninstall block-goose-cli`; remove `~/.local/bin/goose-scout`; archive `~/.config/goose`, `~/.config/goose-scout` (wave2-E9 D).
- C56. kiro: `brew uninstall --cask kiro-cli`; remove `kiro-cli()` in `~/.bashrc`; archive `~/.semantic_search` (wave2-E9 D).
- C57. devin: `brew uninstall --cask devin-cli`; archive `~/.config/devin` (wave2-E9 D).
- C58. cline: `npm -g uninstall cline` (prefix `~/.local`), remove `~/.local/bin/cline`; archive `~/.cline` (wave2-E9 D).
- C59. copilot CLI, qwen-code, aider, muse: install method not recorded (look it up); archive `~/.copilot`, `~/.qwen` (wave2-E9 D).
- C60. venicecode: remove `~/.local/bin/venicecode`, `~/.local/lib/venicecode`, `~/.config/opencode/venicecode.json`, `~/.config/venice-opencode-isolated`, `venicecode()` in `~/.zshrc`; and `~/ops/site-private-djbclark/bin/venicecode-upgrade` plus `run_venicecode_pass` in brew-fast-upgrade (site edits, order 11) (wave2-E9 D).
- C61. dsh: remove `~/.local/bin/dsh`, `~/.local/lib/dsh`, `~/.dsh`, `dsh()` in `~/.zshrc`, `pnpm remove -g @deepseek-ai/dsh`; and `ensure_dsh_wrapper` in `roles/site_agents/templates/brew-fast-upgrade.sh.j2` plus site-djbclark commit 3913c57's `dsh_repair_native_binding.py` (site edits, order 11) (wave2-E9 D).
- C62. Remove the skill links the retired TUIs hold in `~/.gemini/antigravity-cli/skills`, `~/.copilot/skills`, `~/.qwen/skills`, `~/.config/devin/skills`, `~/.cline/skills`; the goose/pi/zcode links live in `~/.agents/skills`, which codex also uses, so do not remove that directory; then `bin/skill-everywhere --check` should list only the surviving TUIs (wave2-E9 D).
- C63. Move the 147 site-private memory notes about retired TUIs to an archive folder agents do not read, for example `site-private/memory-archive/retired-tuis/` (decision on timing) (wave2-E9 E). Kiro, Windsurf, AdaL: nothing machine-side (wave3b G4).
- C64. `cow remove` the pastures under `~/.cow/pastures` when done (wave2-E2 E4).

Verification on the live Mac
- C65. `cd ~/src/djbclark-ade && bin/review-launch --check --mode review; echo "rc=$?"`, then the same with `--mode read-only`; `cat ~/.local/state/review-launch/check-*.json | python3 -m json.tool | grep -E '"(status|outcome|claude_version)"|accepted'`; expect rc 0 both and paste the table into `docs/slim/log.md`; a `claude-md readable` row is the accepted exposure; rc 3 is inconclusive (re-run), rc 77 means do not use review-launch on that version (wave4-E8 G1).
- C66. First real review: `bin/review-pr N; echo "rc=$?"`, paste the marker line into the PR body, then `gh workflow run adversary-marker.yml -f pr=N` and `gh pr checks N --watch --required` (wave4-E8 G2).
- C67. `bin/route_agent.py services --check-models` (expect exit 0; a MISSING line is a model id to correct in `config/routing.toml`; false MISSING lines are expected for Claude's `opus`/`fable`/`sonnet` aliases and Cursor's `default` until mapped to Paseo's ids), then `bin/route_agent.py show` (wave4-E7 H3).
- C68. One live dispatch: `acp-dispatch claude --model sonnet --kind code --perm read-only --name e6-live -p "List the top-level files of this repository." -C ~/src/djbclark-ade --task e6-live`; expect exit 0, `boundary: review-launch`, a report ending DONE (wave4-E6 J5).
- C69. Context-budget schedule (J3, keep): `paseo schedule create --cron "50 3 * * *" --timezone "$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')" --name context-budget --provider claude/<model> --cwd ~/src/djbclark-ade "Run ~/src/djbclark-ade/bin/context-budget-check --instruction-lint. Report its exit code and output in one paragraph; change nothing. Exit 1 is a budget breach or a rise, 3 a directory it could not measure."`, then `paseo schedule ls`; the model is your pick (decision) (wave3-E5 G6, C3).
- C70. Optional Paseo schedule line (reads Paseo upstream events; check `paseo schedule create --help` first, `--mode` is not in the docs page): `paseo schedule create --cron "0 */4 * * *" --name paseo-upstream-pending --provider claude/claude-sonnet-5-5 --cwd ~/src/paseo "Read ~/.local/state/fleet-watch/upstream-paseo.json. If its .pending list is empty, say so and end. Otherwise report each pending event (repo, number, event, login, age) in a short list for the operator and follow ~/ops/site-private-djbclark/prompts/paseo-contribution-review.md for reading only. Change nothing, post nothing upstream, send nothing." (decision) (wave3b B, G5).
- C71. Close PR 270 (`quota-surplus`, parked): `gh pr close 270` (command form not in the sources) (log "Operator batch gains"; PLAN.md D4).
- C72. Open decisions: whether to narrow the claim guard to add/commit in a foreign workspace, a security call of about 2,000 lines (wave4-E8 F3); whether to build the thin Paseo `worktree.create.after` plugin hook for `ade_claims.py new --ttl` (wave4-E8 F4); PR 290 `ade-recovery` after the native-resume trial A6 (PLAN.md J9) (decision).
- C73. After `ade update` and the relinks: `graft build` in `~/src/djbclark-ade` (the graph cache under `graft/` is ignored and local; the cloud lead cannot run it) so `graft ask`/`graft map` match the slimmed tree (PLAN.md E11, "`graft build` last").
- C74. Done on the branch (2026-11-07, operator decision 1a): the merged `.claude/settings.json` is committed; nothing to paste.

## D. Two weeks later (the follow-up PR, after one live cycle, or sooner when every C3 file is migrated or waived and the `relay.py`/`acp-dispatch` logs show no caller)

- D1. Remove the relay shim (`skills/session-finder/relay.py`; wave3-E3 G1 dates it to 2026-11-20), the acp-dispatch shim, and `acp-run` with `tests/test_acp_run_*`; keep `bin/review-launch` and its tests, which are permanent (PLAN.md F Wave 6, I1).
- D2. Migrate aiuse (`djbclark/aiuse`, order 11: ask first): `src/aiuse/collectors/acp_usage.py` reads `~/.local/state/acp-run/` JSONL turn logs, and nine more files name acp-run/acp-dispatch (log, Wave 2 closed, C3 scan).
- D3. Re-confirm every C3 consumer is migrated or waived per file: tendcf and nix2cf AGENTS.md (frdminc/tendcf#43 and frdminc/nix2cf#6, merged), Plektra and paseo4herdr (no file names relay.py or acp-dispatch), site-djbclark `bin/fleet-watch` (on the intake branch) (log, C3 scan; wave3-E3 F3, F4).
- D4. Remove the `.skillopt-sleep` and `.skillopt-sleep-handoff` lines from `.gitignore`, after C6 (wave3-E10 G0).
- D5. Remove whichever of asks / questions-please you stopped using after a week (decision) (PLAN.md J6).
- D6. Upstream filings for gaps found in Paseo (a quota-pause primitive, a workspace claim primitive), if still missing (PLAN.md F Wave 6).

## Lost on purpose, until you act

Until you do the steps above, these stay gone or inert by design: Jev's effort nudge and shadow logging, the herdr sleeper (Paseo's `agents.idleRuntimeCleanup` replaces it), `ade-scan-state`, `seat-name` and the cow pastures; the retired TUIs' routes (agy/Google AI Pro through `acp-run`, the copilot reserve, pi's API pool, the zai/qwen/crush/devin pools, zcode and per-run strip enforcement) and the grok CLI's realtime-web pool; the relay's herdr/Orca/tmux pane routes, outbox, deferred sends, expected-ack ledger, `--via` fallback and prose nudge, plus session-finder's search half and `launch.py`; helm, self-slash, autorename tab placement, the paseo-new-seat auto-accept guarantee and the bypass watcher; the per-process CPU watcher, rumination-watch, session-load-watch, the monthly routing recalibrate and pane delivery for find-and-tell; the nightly skill-edit cycle (SkillOpt-Sleep), the prior-art nudge, `skill-get`, the frontmatter fixer and failover's model chain; the pi subagent extension, the zcode wrappers, the web-get/web-digest/Firecrawl router ladder (its MCP on 18804 lives until you re-point it) and the six vendored `ade-paseo*` skills' patches; auto-resume after a quota stop, reroute, cursor-cloud through dispatch, checkpoint mode, the slice deadline and the enforced read-only sandbox for non-Claude providers (now best effort); the fleet governor's pause, the quota guard's levels and state file, gate profiles and `claude-cost-whatif`; pr-wait's Codex gates (J8: findings are advisory and nothing enforces that the lead reads them), the report-only default, `--local-codex`, the local review's load gate and lock, and the claims verbs `show`, `find` and `set-state`.
