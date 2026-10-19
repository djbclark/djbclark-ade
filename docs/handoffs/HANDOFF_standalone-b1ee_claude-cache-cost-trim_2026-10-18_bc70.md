---
schema_version: 1
handoff_id: bc70
parent_handoff_ids: []
lineage: none
chain: [standalone-b1ee]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: 0570f8012b516439e10f0bc22df23d36ecb4ed89
created_at: 2026-10-18T21:02:17-04:00
writer: claude-code
---
# Handoff — Claude Code cache-cost trim, /doctor cleanup, loose ends

## The Goal

djbclark asked whether graphify would save money compared with graft, and then how to cut Claude Code's
cache cost ("3a"). The session measured where the money goes and had a Fable 5.1 review check the
recommendations. Then it implemented everything Fable accepted, ran a /doctor cleanup and a loose-ends
sweep. **All of that is done, committed and pushed.** Only follow-up watching and three
operator-deferred items remain.

## Where We Are

1. Measured with `bin/claude-cost-mix`: ~$1,677 a week at list price. Cache reads 46.6%, 1-hour writes
   37.4%, output 15.9%. The fixed preamble was 17.2% of cost.
2. The fresh-session preamble went from **46.3k to 22.9k** in this repo and from 39.9k to **22.7k** in
   `~` (measured with `bin/context-budget-check --dry-run`, 2026-10-18 ~20:55).
3. The report, with an Outcome section, is `docs/claude-cache-cost-research-report.md`. Every
   setting changed, with how to undo it, is in `docs/disabled-skills.md` (sections "Second pass
   (2026-10-18)" and "Skills hidden by setting").
4. graphify was not adopted; graft is kept (memory `project_graphify_evaluated_not_adopted.md` in this
   project's auto-memory).

Files changed this session, by repo:

1. djbclark-ade:
   1. New: `bin/claude-cost-mix`, `bin/claude-cost-whatif`, `bin/context-budget-check`,
      `config/context-budget.toml`, `launchd/com.djbclark.context-budget.plist`.
   2. Edited: `claude/hooks/context_size_nudge.py`, `bin/self-slash`,
      `claude/hooks/bash_habits_gate.py`, `claude/hooks/cswap_quota_context.sh`,
      `claude/agents/fable-deep.md`, `.claude/settings.json` (graft hooks removed), `AGENTS.md`
      (condensed; order 7 now points at the routing policy).
   3. Docs: `docs/disabled-skills.md`, `docs/apply-toolchain-prompt.md`, `docs/model-routing.md`,
      `docs/skills.md`, `docs/upstream-issues.md`.
   4. Tests: `tests/test_claude_cost_mix.py`, `tests/test_context_budget_check.py`,
      `tests/test_bash_habits_gate.py`, `claude/hooks/handoff-tools/tests/test_context_size_nudge.py`.
2. site-djbclark:
   1. `home-agents.md` (= `~/.claude/CLAUDE.md`): f84da4e, then 6158c2f.
   2. `cursor/home-agents.mdc`: bd8d349.
   3. `macos/graft-hook-timeout-fix/graft-hook-guard.sh` and `graft-hook-timeout-fix.py`: c6d133a and
      76d589e (`strip-project`).
3. site-private:
   1. `memory/MEMORY.md`: condensed in 7b9c871.
   2. `feedback_self_compact.md` and `feedback_context_prompts_early.md`: 8bbb79f.
   3. `reference_agent_rules_ops_housekeeping.md`: dbaa4fb.
   4. Todo note "Trim bezalel MCP sub-services...".
   5. Two notes left uncommitted by session ad8c47d1, committed as written.
4. Outside git:
   1. `~/.claude/settings.json`: backups `settings.json.bak-2026-10-18-cachecost` and `-doctor`.
   2. `~/.claude.json`: `mcpServers.firecrawl.alwaysLoad=false`.
   3. `~/CLAUDE.md` now links to `~/ops/site-djbclark/home-agents.md`.
   4. `~/.local/bin/claude-cost-mix` and `context-budget-check` symlinks.
   5. LaunchAgent `com.djbclark.context-budget`.

Tests: all run through `~/ops/site-private/bin/bg`, rc read from a file.

| Test file | Result |
|---|---|
| `test_claude_cost_mix` | 4 passed |
| `test_context_budget_check` | 21 passed |
| `test_context_size_nudge` | 36 passed |
| `test_bash_habits_gate` | 115 passed |

Dirty files in djbclark-ade that are **not this session's**: `skills/graft/SKILL.md`, `skills/paseo*`,
`bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_...`. Leave them alone.

## What We Tried

1. **The first cost split was wrong.** It priced every cache read at a flat 0.1x and got reads 71%,
   navigation 16%. Opus and Sonnet 5.5 reads cost 0.05x and Fable 0.025x. Retracted the same day;
   `claude-cost-mix` now prices each request by its own model.
2. **The first compaction simulation over-saved (−19%).** It never reset the simulated drop at real
   compactions. Fixed with a reset when context falls below 0.6x the previous request.
3. **Moving skill folders aside** (the 2026-10-10 method) does not hold: `bl skill update` and the
   paseo CLI re-link the folders. Replaced with `skillOverrides`.
4. **A `chmod --reference` on BSD** stripped the graft guard's execute bit for seconds. It was
   restored, and `bash_habits_gate.py` now denies GNU-only flags on BSD tools (3595268).

## Key Decisions

1. Kept the 1-hour cache TTL everywhere. Rejected 5 minutes everywhere (+30%) and sub-agents on 5
   minutes (+2.8%).
2. **Rejected** `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS=100000`: it loses money below ~127k, given the
   ~104k post-compaction floor (Fable section 4.2).
3. `autoCompactWindow` set to 300k; compaction fires at ~267k (the window less its 33k buffer).
   Rejected 200k (+1%) and 150k (+17%).
4. At a task boundary over 150k, prefer handoff then `/new` over `/compact`: a fresh session re-writes
   ~46k, while a compaction re-writes ~72k, makes a summariser call and leaves ~104k.
5. Denied in Claude Code: claude.ai Firecrawl, Drive and Calendar; bezalel (djbclark); siyuan.
   Kept: Gmail, Context7, arxiv and cow (djbclark: leave on), crawl4ai.
6. Hid skills from the model with `skillOverrides` and set the listing budget to 0.007. Plugins
   composio and claude-powerline turned off.
7. Graft's per-prompt pack: off. The guard skips it unless `GRAFT_PROMPT_HOOK=1`, and `strip-project`
   removes project copies at session start (`~/src/Graft` is exempt).

## Evidence & Data

1. Tools:
   1. `bin/claude-cost-mix --days 7 [--json]`.
   2. `bin/claude-cost-whatif 7` (TTL and threshold simulations).
   3. `bin/context-budget-check --dry-run`.
2. Fable review (scratchpad only, may be cleaned):
   `/private/tmp/claude-501/-Users-djbclark-src-djbclark-ade/cc7ee65d-33b4-47aa-a2c6-be517ffb3f8e/scratchpad/cachecost-fable-review.md`.
   Its conclusions are carried into the report's Outcome section and into `docs/disabled-skills.md`.
3. Upstream:
   1. Filed https://github.com/anthropics/claude-code/issues/103330 (user `deniedMcpServers` labelled
      "enterprise policy").
   2. Commented https://github.com/trailhq/Trail-Code/issues/497#issuecomment-6257408007 (no opt-out
      for graft's per-prompt pack). Drafts are in `docs/upstream-issues.md`.

## Operator Feedback

1. "You may use Fable and Opus freely" for this work. Fable was 29% under pace on 2026-10-18.
2. Each answer in the walks:
   1. `claude-cost-mix` goes in the toolchain prompt.
   2. Report moved to `docs/`.
   3. bezalel: deny it and add a todo to trim its sub-services.
   4. Home MEMORY.md: "coordinate with the other agent, it may be done and just forgotten to commit"
      (it was).
   5. Repoint `~/CLAUDE.md`.
   6. Mark the stale model-routing claims superseded.
   7. Condense the Cursor `.mdc`.
   8. /doctor: clean up everything.
   9. Order 7 points at model-routing.
   10. arxiv and cow stay on.
   11. Keep the CLAUDE.md condense and restore the `--body-file` clause.
   12. Post the #497 comment and file the Claude Code bug.

## Where We're Going

1. **Next action: after ~2026-10-25, re-run `bin/claude-cost-mix --days 7` and compare with the
   2026-10-18 baseline** ($1,677 a week; reads 46.6%, writes 37.4%; preamble share 17.2%; 77
   compactions a week). Look at:
   1. the preamble share (expected to fall roughly by half);
   2. the compaction count (the 300k window may raise it; payback needs dozens of requests per cycle);
   3. whether "/new at boundary" shows up as more, shorter sessions.

   If compactions loop, raise the window back with `autoCompactWindow`, or use a per-model setting.
2. Read the nightly budget-check results in `~/.local/state/context-budget/*.json`; it pings Hermes
   on a breach or a 2k rise.
3. Operator-deferred, not oversights:
   1. bezalel scope trim, then decide whether to re-enable it (Basic Memory `main/todo`).
   2. Context7 re-check on or after 2026-10-24 (`docs/queue.md:670`).
   3. djbclark runs `/doctor` interactively once to see which skill descriptions the 7k cap drops.
4. Optional: `.claude/helpers/graft-hooks.cjs` in this repo is tracked but no longer referenced.
5. Optional: watch https://github.com/anthropics/claude-code/issues/103330 and Trail-Code#497 for
   replies.

## Detached jobs

None. No bigteam job records are open for this session. The LaunchAgent
`com.djbclark.context-budget` (03:50 daily) is a standing job, not a session job.

## Quick Start

```bash
cd ~/src/djbclark-ade
bin/claude-cost-mix --days 7                 # compare with the baseline above
bin/context-budget-check --dry-run           # fresh-session preamble now (~22.9k repo, ~22.7k ~)
ls ~/.local/state/context-budget/            # nightly results
rg -n 'Second pass|Skills hidden by setting' docs/disabled-skills.md   # what is off, how to undo
```
