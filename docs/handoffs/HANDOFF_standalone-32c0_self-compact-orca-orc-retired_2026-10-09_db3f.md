---
schema_version: 1
handoff_id: db3f
parent_handoff_ids: []
lineage: none
chain: [standalone-32c0]
repo: djbclark-ade
workspace: you-can-compact-yourself
branch: djbclark/you-can-compact-yourself (worktree; work landed on master)
head_sha: 4c0252d0bce4a0b528e2b3cef2c199e160ca7374
created_at: 2026-10-09T08:14:00-04:00
writer: claude-code
---
# Handoff: self-compact in Orca, Orca parity easy wins, /orc + herdr-orchestration retired

## The Goal

1. Let a Claude session compact itself in Orca as well as herdr (`bin/self-slash`), and make that the standing habit at natural boundaries.
2. List which ADE capabilities work in herdr but not Orca. Close the easy ones.
3. Operator question, answered: `/orc` and `/orc-meta` were unused (last run 2026-08-13). They are retired, along with `orc_watchdog.py` and the `herdr-orchestration` skill (last used 2026-08-15). Before deleting them, everything still useful went into the live skills.

## Where We Are

Everything requested is done, pushed and verified. Nothing is in flight.

1. **djbclark-ade (master):**
   1. 585c4ab: `self-slash` Orca backend and the hint-text filter.
   2. af2904c: parity gaps queued.
   3. be52f2e: `loose`/`steps` self-compact wording.
   4. 4b7ae85: Orca easy wins.
      1. `launch.py close` runs `orca terminal close`.
      2. Orca notes added to bigteam Step 0, session-finder rung d and autorename.
      3. 8 tests in `tests/test_launch_orca_close.py`.
   5. ce5298b and 4c0252d: retirement and port.
   6. 268065e: another session's (ClaudeHelm) self-slash commit. It swept in the retirement's staged deletes and moves; ce5298b's message records this.
2. **site-djbclark:**
   1. a077c82: self-compact rule in `home-agents.md` and the `.mdc` copy, and in `context_size_nudge.py`.
   2. 3605d31, 888765d, 354e20d: retirement.
   3. Latest commit: the nudge tests clear `HERDR_PANE_ID`/`ORCA_TERMINAL_HANDLE` in an autouse fixture.
3. **site-private:**
   1. de91f33: `memory/feedback_self_compact.md`.
   2. d787b33: `memory/project_orc_and_herdr_orchestration_retired.md` plus pointer fixes.
   3. Latest commit: the slash-command reference note now records `/compact` as verified in Orca.
4. **Local leftovers deleted (operator-approved):** `~/.claude/hooks/orc-watchdog/`, `~/.claude/state/orc-*`, and `~/.claude/commands/orc*.md`. `skill-everywhere --remove herdr-orchestration` has been run.
5. **This worktree branch** was fast-forwarded to origin/master with `git reset --keep`. Its local commit 218f993 had the same patch-id as 4b7ae85.

## What We Tried

1. Treating Orca's JSON `draft` field as the input box: it reports Claude's grey hint text (`Try "..."`) as a draft. Dropped. `self-slash` reads the screen tail and filters hint text instead (both hosts).
2. Rebasing the worktree onto master was blocked by another agent's unstaged graft files. Sub-agents cherry-picked from temporary worktrees or worked in `~/src/djbclark-ade` instead. Never stash those files.
3. Running the nudge-hook tests inside Orca or herdr: two tier tests failed because of the env switch added this session. My earlier "15 passed" claim was wrong for in-pane runs. Fixed with an autouse fixture; 15 now pass inside Orca.

## Key Decisions

1. **Self-compact:** reworded the other session's existing "compact tool" rule rather than adding a second rule. The operator asked to avoid duplicate text.
2. **Autorename in Orca:** no `orca terminal rename`. Orca already shows Claude's title, and pinning it would hide the status glyph. That Orca follows a fresh rename is inferred; it was not tested live.
3. **Retirement:**
   1. Chosen: option 4.2, which also retires herdr-orchestration, rather than 4.1 (keep it, reworded).
   2. Dated reports, handoffs and `research/` were left untouched.
   3. herdr-sleeper's `exclude = ["orc","orc-meta"]` was kept, because the operator's live sleeper config still names them.
4. **Port destinations:** the full port table, from each source section to file:line, is in the retirement report. Summary:
   1. model-routing: the Fable gate, credits, renamed models, herdr TUI gotchas, backticks in prompts.
   2. bigteam: "done = real artifact, merged" and "only the orchestrator launches".
   3. herdr-tidy: the self-close wrapper.
   4. session-finder: handoff prompts must name the tool's own state.
   5. autorename: now holds `workspace-layout.md` and `relocate-pane.sh`.

## Evidence & Data

1. Self-slash log `~/.local/state/self-slash.log`:
   1. This session's `/compact` was sent at 07:39:16 and compacted.
   2. The aiuse Orca session also used it, at 07:42:43.
   3. In herdr it correctly refused a real draft ("do 1c and 2c").
2. Usage counts (Claude transcripts):

   | command | sessions | last run |
   |---|---|---|
   | `/orc` | 12 | 2026-08-13 |
   | `/orc-meta` | 1 | 2026-08-13 |
   | `/helm` | 5 | 2026-10-09 |
   | `/bigteam` | 9 | 2026-10-09 |

3. Tests:
   1. `tests/test_launch_orca_close.py`: 8 pass, but only against a faked `orca` CLI.
   2. `test_context_size_nudge.py`: 15 pass inside Orca, run through `bg`, rc=0.

## Operator Feedback

1. "Remember to do so at opportune moments": self-compact via `self-slash` at natural boundaries is standing say-so (`memory/feedback_self_compact.md`).
2. On retirement: "Do 2, but make sure anything useful in all of them gets ported to djbclark-ade currently used skills". Done.

## Where We're Going

1. **Next action:** check `launch.py close` against a real Orca terminal once.
   1. Start a throwaway with `launch.py start` in Orca, then run `launch.py close <id>` and confirm with `orca terminal list --json`.
   2. Tests so far used only a faked `orca`.
2. The remaining Orca parity gaps are queued in `docs/queue.md` ("Herdr-only ADE capabilities, Orca parity gaps"). The `/orc` port no longer applies:
   1. acp-run reports agent state only to herdr.
   2. helm and fleet show non-Claude Orca TUIs as `unknown`; `tidy.py`'s Orca status merge could be reused.
   3. `where.py` uses a possibly stale `$ORCA_TERMINAL_HANDLE`.
   4. `launch.py start_tui` (zcode/muse) refuses in Orca.
3. Optional: the public repo `djbclark/claude-orchestration-skills` still publishes `herdr-orchestration`. Retiring it there is the operator's call; it was not asked for.
4. Optional: herdr-sleeper's default exclude list and `docs/agent-sleep.md` still name `orc`/`orc-meta`. They are harmless; drop them if the live sleeper config is cleaned.

## Detached jobs

None. All three sub-agents of this session finished and their reports were read. Reports are in this session's scratchpad: `parity-report.md`, `orc-usage-report.md` and `orc-retire-report.md`. They are not durable; the facts they hold are recorded above and in the commits.

## Quick Start

```bash
cd ~/src/djbclark-ade && git pull --ff-only && git log --oneline -8
rg -n "Orca parity gaps" docs/queue.md
cat ~/ops/site-private/memory/project_orc_and_herdr_orchestration_retired.md
tail -5 ~/.local/state/self-slash.log
```
