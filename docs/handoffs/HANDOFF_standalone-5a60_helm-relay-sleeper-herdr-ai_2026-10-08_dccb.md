---
schema_version: 1
handoff_id: dccb
parent_handoff_ids: []
lineage: none
chain: [standalone-5a60]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: d3cc9c1e4384725f5576da49736bd260b814c2c1
created_at: 2026-10-08T23:30:00-04:00
writer: claude-code
---
# Handoff — helm relay session: herdr-sleeper restore flags, herdr-ai, herdr-tidy, job records

## The Goal

One Claude session (helm relay, herdr pane `w2E:p1`, tab `helm-relay-t`) ran the `/helm-all` loop and orchestrated five bigteam threads: (1) herdr-sleeper restored panes must come back with the same flags for every TUI and Hermes, with a self-reloading watcher and a safe stray sweep; (2) `herdr-ai`, a popup that turns natural language into Herdr commands; (3) a safe way to close idle herdr panes (landed as the `herdr-tidy` skill); (4) job records so background work survives `/handoff` then `/new`; (5) orca-tidy feasibility. Threads 3 and 4 are done. Threads 1 and 2 have slices finishing; thread 5 is an issue to build.

## Where We Are

1. **djbclark-ade** master at `d3cc9c1`, pushed. Clean after 6bdd320 (herdr-ai committed).
2. **herdr-sleeper** (`~/src/herdr-sleeper`, HEAD `3bdc4cb`): uncommitted slices A, C, C-fix, D, D-fix on `herdr-sleeper`, `tests/test_herdr_sleeper_plugin.py`, `herdr-plugin.toml` (`.gitignore` and `.ignore` changes are graft's, leave them). Central suite after D-fix: **683 passed, 3 skipped** (`~/.local/state/bigteam/sleeper-restore-flags/pytest-d-fix-central.log`). Reports: `report-all-kinds.md` (D), `report-wake-fix.md` (C-fix), `report-d-fix-resumed.md` (D-fix, written by the resumed session), `review-ACD.md` (the combined review; findings 1 and 2 were must-fix). CLAIM at `~/.local/state/bigteam/sleeper-restore-flags/CLAIM` (pane id in it is stale; the session was `w2E:p1`).
3. **herdr-ai** built (906-line Python, 81 tests, keybind `prefix+alt+i` applied in `~/.config/herdr/config.toml`, backup `config.toml.bak-herdr-ai`, LiteLLM client key `herdr-ai` created live and committed in site-djbclark `7c4524c`). Adversarial review by zcode at `~/.local/state/bigteam/herdr-ai-cmd/report-review.md`: 1 must-fix (control characters in model-sourced strings can rewrite the printed plan), 3 should-fix (`--env` on auto-class verbs, untyped `any*` group, no overall index deadline), 6 nits. Fix slice brief: `brief-fix.md`.
4. **herdr-tidy** landed (Fable sub-agent): commits `53f35e8`, `8833bdc`, `b7f8b3a`; site-djbclark `9dde30f`, `41b9a07`; site-private `a8c7477`. First pass closed 16 panes, ledger `~/.local/state/session-finder/closed.jsonl`. Report: `~/.local/state/bigteam/herdr-safe-close/report.md`. Six operator decisions left (drafts in w22:p6 and w23:p7, staged `/quit` in w25:p1, typed `claude` in w2A:p6, the Cursor Qwen prompt in w2A:p4 since answered, jobtest gone).
5. **Job records** landed: `05e5f4b` (bigteam Step 4 "Jobs and records", handoff "Detached jobs", baton re-arm). Verified: `/new` is `/clear`, same process, background tasks survive it and notify the new session; quitting kills them.
6. **fleet Orca handle** fixed: `1d55502`. **bigteam skill** rules added: `d3cc9c1` (report before optional checks; budget timeouts; resume a cancelled slice with `acp-run --resume`).
7. **home-agents.md** condensed to 19,184 bytes (site-djbclark `e0fbad4`, site-private `5062534`).
8. **orca-tidy**: feasible with workarounds; issue https://github.com/djbclark/djbclark-ade/issues/1; report `~/.local/state/bigteam/orca-tidy-feasibility/report.md`. Orca's open listener on TCP 6768 is intentional (operator).

## What We Tried

1. **D-fix slice at `--timeout 1700`**: cancelled at 1704 s during its mutation check, after the suite passed; the report was the brief's last step and was lost. Fixed by resuming the session (`acp-run claude --resume <sessionId> --perm deny -p "write your report now"`, 48 s) and by the bigteam rules in `d3cc9c1`. Do not re-task a cancelled slice before trying the resume.
2. **Helm answers to sessions that vanish**: three times this session `helm.py answer/skip` returned "no session with id" because the session had quit or its id changed between the question and the answer (physiboard ee80ad72 quit on its own; the job-records `jobtest` throwaway; the Cursor pane w2A:p4 answered by the operator). Nothing went through; no harm. Helm fix owed (below).
3. **Named pipes for cross-session notifications**: rejected during the job-records investigation (64 KiB buffer, writer blocks without a reader, the reader is itself a background process). Records on disk plus `.done` markers won.
4. **Brief assumptions the herdr-ai builder refuted** (good outcome, keep in mind): the stale tab id `w27:t3D`; `~/.local/bin/herdr-sleeper` on PATH is the OLD standalone script with stale rows, not the plugin; handoff chain files have no `# ` heading and `redirect:` is relative to `~/.local/state/handoffs/`; `gemini-free` 429s often, so the fallback is lite → gemini-free → lite.

## Key Decisions

1. herdr-tidy is a separate skill from helm (helm relays and never closes). autorename moved into djbclark-ade with a symlink from site-djbclark, not merged into tidy.
2. D-fix: finding 1 exactly as reviewed (lsof-scoped strays, fail closed, sweep only from `startup`); finding 2 both (a) snapshot key == live pane id and (b) terminal-id time vs Herdr server start; finding 4 repair default-on for all kinds except codex.
3. herdr-ai: model sees only an index (snapshot digest, fleet session titles, handoff chain names, sleeper labels, last 6 lines per pane); plan validated against the snapshot; auto for focus/rename/create/split/move/swap/resize/zoom; one `y` for everything else; never `clinepass-*`; the model is `gemini-free-lite` on LiteLLM :4000. Review on a differently sourced vendor (zcode/GLM) before commit.
4. herdr-sleeper journal untouched by tidy closes; sleeper changes arrive as numbered requests (`requests-from-tidy.md`).
5. Orca-tidy as a `--host` mode of tidy.py, not a fork (issue #1).
6. Rejected: scheduling a recurring prompt for helm; auditing non-Claude/cold sessions without asking; posting the Herdr discussion #631 comment without an explicit go.

## Evidence & Data

1. Pools at last probe: Claude 5h 83% left, weekly 61%, Fable 69%; zai 62%/92%; qwen 99%; agy gemini 100%; cursor 26% (tight); copilot 20%.
2. Slice costs: herdr-ai build 776 s / $2.89; D-fix 1704 s / $5.57 (cancelled) + resume 48 s; job-records 505 s / $1.20; fleet handle fix 104 s / $0.67.
3. herdr-ai live: index 0.5-1.0 s (builder) vs 2.72 s (reviewer, under load); model 0.65-5 s, two timeouts of 12 dry-runs; 19 log lines in `~/.local/state/herdr-ai/log.jsonl`.
4. Helm bugs seen this session: lists its own session (w2E:p1) as BLOCKED on its own AskUserQuestion; auto-audit sent physiboard about a dozen duplicate `/loose` messages; ids vanish between question and answer; duplicate herdr panes for ACP sessions; mac-workspace flicker; ended chain ids.

## Operator Feedback

1. "Never choose for him": helm relays, every answer is his; one item per AskUserQuestion; audit warm idle Claude sessions without asking, ask for cold or non-Claude.
2. Outward-facing actions (posting the #631 comment) need an explicit go. The Orca listener on 6768 is on purpose.
3. Fix the cause of a tool mistake in the same turn (done for the timeout: `d3cc9c1`).
4. Context: he picked `/compact` twice and then `/handoff then /new` at 244k.

## Where We're Going

1. **herdr-ai COMMITTED** (6bdd320, pushed; fix slice applied all review findings, 150 tests, ruff clean, `report-fix.md`). Remaining: ask the operator to press `ctrl+a alt+i` and type "go to the sleeper tab" (only his terminal proves the popup); if the key does not fire, `herdr config check` and the `[[keys.command]]` block near line 341 of `~/.config/herdr/config.toml`.
2. **herdr-sleeper, re-review**: DONE at handoff time. `~/.local/state/bigteam/sleeper-restore-flags/report-d-fix.md` (12.6 KB, 416 s): finding 1 SAFE (scope filter `herdr-sleeper:2832`, fail closed 2784-2795 and 2819-2822, sweep only from startup 2930/3352; residuals are pid reuse in a millisecond window and a v0.1.0 `watcher.pid` record with no lock flag, both negligible); finding 2 SAFE with residuals (read its NOTES before deploy and decide whether any residual needs a follow-up slice). Proceed to docs (item 3).
3. **herdr-sleeper docs slice B**: `brief-docs.md` exists in that directory; before dispatch append: the three requests in `requests-from-tidy.md` (list prints `manual:` for asleep entries whose pane is gone; `forget <key>`; pane-gone event at reconcile), and a note that `~/.local/bin/herdr-sleeper` on PATH is the old standalone script. Targets: README lines 52/96 and LESSONS 4.3 stale focus-wake wording, LESSONS candidates from `report-all-kinds.md`, `~/src/djbclark-ade/docs/{upstream-issues,agent-sleep}.md`. Owner files only; tests not needed.
4. **herdr-sleeper integrate and deploy**: commit by path in `~/src/herdr-sleeper` (`herdr-sleeper`, `tests/test_herdr_sleeper_plugin.py`, `herdr-plugin.toml`, README, LESSONS; not `.gitignore`/`.ignore`), push; atomic copy to `~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper` (temp + `mv -f`), bump `plugins.json` 0.1.0 → manifest 0.1.1 (or higher), point `~/.local/bin/herdr-sleeper` at the plugin copy, commit by path in djbclark-ade, push; `herdr-sleeper startup` right away (pid 9764 is the sleeper-plugin-lab session's watcher, NOT a stray; 26732 is the deployed watcher); check `herdr-sleeper version`; `~/.local/bin/hermes-ping "herdr-sleeper: deployed restore-flags for all kinds, self-reloading watcher, scoped stray sweep, wake y/N stub"`; draft the Herdr discussion #631 comment and **ask before posting**; append DONE to the CLAIM; memory note.
5. **Helm loop**: restart `/helm-all` in the new session (`python3 -I ~/ops/site-private/skills/helm/helm.py scan --ended`, then plain `wait` in the background, one at a time; skip the session's own pane). Relay Fable's six decisions once (handoff section Where We Are 4). Fix list for helm.py (djbclark-ade `skills/helm/helm.py`): exclude its own session; auto-audit must not resend `/loose` (it sent ~12 to physiboard); keep ids stable between question and answer; dedupe herdr panes for ACP sessions; mac-workspace flicker; ended chain ids. Consider one Sonnet slice scoped to `helm.py` + `tests/test_fleet_tidy.py`.
6. **orca-tidy**: build per issue #1 when the operator wants it (Sonnet slice, `--host` mode in `skills/herdr-tidy/tidy.py`, hazards in the issue).
7. **acp-run grace deadline** (optional, operator to decide): send "wrap up and write your report" N minutes before `--timeout` instead of cancelling cold (`~/ops/site-private/bin/acp-run`, git in site-djbclark `tools/acp-run/`).
8. **Stale CLAIM pane ids**: `sleeper-restore-flags/CLAIM` and `herdr-ai-cmd/CLAIM` say `w27:p3Q`; the session pane was `w2E:p1`. Cosmetic.

## Detached jobs

none. Every slice of the previous session finished before the switch; no background task or waiter is relied on.

## Quick Start

```bash
cd ~/src/djbclark-ade && git status -s && git log --oneline -3
ls -la ~/.local/state/bigteam/herdr-ai-cmd/report-fix.md ~/.local/state/bigteam/sleeper-restore-flags/report-d-fix.md
cat ~/.local/state/bigteam/herdr-ai-cmd/report-review.md | head -60     # the findings the fix slice applies
cat ~/.local/state/bigteam/sleeper-restore-flags/report-d-fix-resumed.md  # what D-fix changed
H="python3 -I $HOME/ops/site-private/skills/helm/helm.py"; $H scan --ended
```
