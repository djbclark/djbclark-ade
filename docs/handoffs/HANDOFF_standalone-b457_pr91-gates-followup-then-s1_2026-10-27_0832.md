---
schema_version: 1
handoff_id: 0832
parent_handoff_ids: [7bcd]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 195d81de05a3139d7e3af2f42847093f6266d9d4
created_at: 2026-10-27T11:58:00-04:00
writer: claude-code
---
# Handoff — PR 87/88 merged, PR 91 gates follow-up awaiting merge yes, model-tiers S1 next

## The Goal
Drive the ADE ack wave and the gates and model-tiers workstreams to approved, merged PRs: an adversary review per repair round (omp Opus 5.5 high while the Claude gate is tight), Codex review and green CI, and djbclark's explicit yes pinned to the final head before every merge.

## Where We Are
1. PR 87 (relay `--expect-ack` for transcript-less senders plus Hermes gateway caller identity) merged as `5011bd0` on djbclark's yes, pinned to `f29d7d9`. PR 88 (quota-rejected dispatch recovery) merged as `22982622` on his yes, pinned to `091964e`. The PR 87 worktree is removed.
2. Adversary rounds 11 and 12 BLOCKed PR 87's docs for overstating the Hermes identity trust (pid reuse admits an outside shell; the lock file lives at least 7 days and until a later relay prunes it, not "up to 7"; gateway.pid is JSON); repaired docs-only in `fe6b9a0` and `2681e7b`; round 13 `APPROVE at 2681e7b`. The Codex P2 #2 thread was replied to and resolved.
3. PR 91, https://github.com/djbclark/djbclark-ade/pull/91, head `b217cb18f1831f47a5b2f92061080cf5031d606b`, worktree `/Users/djbclark/src/djbclark-ade-gates-followup-wt` (branch `fix/gates-followup-2026-10-27`): fixes round-2 findings A1-A4 of the gate profile (PR 84). Built by an omp Sonnet 5.5 high slice (agy's Claude pool was at 0% headroom, so the acp-dispatch preflight refused it). Tests: 487 passed through `bg`, new tests mutation-checked. Adversary `APPROVE at b217cb1` (P3: the unlocked `clear` fallback fires on any OSError, accepted and stated in the PR body). `pr-wait 91`: merge_ready yes (CI 5/5 after a rerun of the macOS job, which hit the 30-minute job cap and was cancelled with no test failure; Codex 0 findings). djbclark was pinged for the merge yes (hermes-ping); not answered yet.
4. Model-tiers S1 (away frontier allowance) is NOT started. Design: branch `docs/model-tiers-design` (`git show origin/docs/model-tiers-design:docs/model-tiers-design.md`, section D, table row S1; worktree `/Users/djbclark/src/djbclark-ade-model-tiers-wt`, 1 ahead and 24 behind master). It stacks on PR 91 (same files: `config/gates.toml`, `bin/claude-quota-guard`, `claude/hooks/frontier_agent_gate.py`, `docs/gates.md`).
5. Relay link to `w2Q:p3` (Codex, did the activation of canonical ADE and merged PRs 79, 88, 90) is proven both ways (my `ack w2Q:p3` delivered, its `ack 1706651a` came back). Five older relays to `w2F:p45` and `w2Q:p3` all read `delivered`; replies were not confirmed.
6. All three watchers (cfengine, paseo, load) are registered and idle. No work for them.

## What We Tried
1. Dispatching the gates follow-up to agy's Claude pool: refused by the acp-dispatch preflight, "headroom 0.0% < minimum 10.0%". The `aiuse` listing shows only agy's Gemini windows (89% weekly), and I did not send locking and expiry code to Gemini Flash. Routed to omp Sonnet 5.5 high (the router's pick for code with the expiring Claude API credits).
2. Starting `bin/pr-wait 91` seconds after `gh run rerun --failed`: it saw only 2 checks (the rerun's macOS check-run was not yet registered) and reported `ci-none-succeeded`. Not a pr-wait bug; start it after `gh pr checks 91` lists the rerun.
3. The first merge of master into PR 87 left a CHANGELOG conflict and a dropped blank line; fixed in `f29d7d9`.

## Key Decisions
Gates follow-up built before S1 and S1 stacked on it, because both edit the same gate files (djbclark approved the plan, 2026-10-27). The P3 on PR 91 was accepted rather than fixed, stated in the PR body; if djbclark wants it fixed, the repair is small (`_state_lock` reports why and `unlocked_ok` applies only to ELOOP, EISDIR, ENXIO). Codex is used only for a frontier astra consult unless another of its models is clearly right (djbclark, 2026-10-27).

## Decisions
- [decision] Gates follow-up PR 91 built on omp Sonnet 5.5 high; rejected: agy Claude pool; because acp-dispatch found it at 0% headroom.
- [decision] Accept adversary r1's P3 (unlocked clear on any OSError) on PR 91; rejected: repairing before merge; because it needs transient fd or memory exhaustion plus a microsecond race and the PR body states it.
- [ruling] "We should avoid using codex except for frontier astra model unless we are really sure another one of its models is clearly the right choice for a job." (djbclark, 2026-10-27)
- [ruling] "There are 5 pools I am gifting to you, at least for the next month - 2 opencode go $40 subs and 2 clinepass $10 subs, plus I think $10 Amazon Bedrock for llama4. When your VPS is up, we should set them up there, remove setup for them on my computers" (djbclark, 2026-10-27)
- [ruling] "you can use some portion of my other subscriptions without asking, and esp. use anything that would otherwise go to waste due to it expiring soon that is mine" (djbclark, 2026-10-27)
- [ruling] "continue with as much as you feel comfortable doing without me, and batch up questions both here and in/for your other thought threads that I can answer during breaks" (djbclark, 2026-10-27)

## Relations
- continues [[HANDOFF_standalone-b457_pr87-adversary-r11-pending_2026-10-27_7bcd]]
- decided_in [[HANDOFF_standalone-b457_pr91-gates-followup-then-s1_2026-10-27_0832]]

## Evidence & Data
PR 87 final head `f29d7d9`: relay and fleet-tidy suites 824 passed, 119 subtests; merge `5011bd0`. PR 91: 487 passed, 11 subtests; adversary report `~/.local/state/bigteam/adhoc-2026-10-25/adv-gates-fu-r1-report.md`; slice report `gates-followup-report.md` in the same directory; brief `gates-followup-brief.md`. Quota at 11:48 AM ET: Claude 7d 74% used (26% left), agy Gemini 89% left, codex 80%, omp credits 47%. The aiuse listing: `aiuse --available --json`, `.available[]`. Memory written: `project_gifted_pools_and_standing_latitude_2026-10-27.md` (this project's memory directory).

## Operator Feedback
djbclark is at work and asked for batched questions. Batch (all unanswered): (1) merge yes for PR 91 pinned to `b217cb1`; (2) the away profile: absence start and end and exact allowances (ruled values: judged use on for both frontier models, frontier-1 2 per wave, 4 frontier Agent-tool calls a day, frontier-2 1 per wave), needed only before activating it; (3) which VPS "your VPS" is and whether it is up, plus the Bedrock details, before any pool setup or removal from his computers (nothing was changed); (4) the CI macOS job's 30-minute cap timed out once on a slow runner: raise it, or leave it.

## Where We're Going
1. THE next action: check whether djbclark answered for PR 91 (`gh pr view 91 --json state,mergeCommit`; his yes arrives in the conversation). If he said yes, `gh pr merge 91 --squash --match-head-commit b217cb18f1831f47a5b2f92061080cf5031d606b`, then `git worktree remove ~/src/djbclark-ade-gates-followup-wt`, `hermes-ping`. Do NOT merge without his yes.
2. Build model-tiers S1 while waiting, in a new worktree off `origin/master` (or off PR 91's branch until it merges): read section D of the design (`git show origin/docs/model-tiers-design:docs/model-tiers-design.md`, sections C1-C6 and D row S1), write a brief file, route with `bin/route_agent.py plan --kinds code --exclude claude,codex` (last time omp Sonnet 5.5 high; adversary via `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high`), mutation-check tests, open a PR, adversary round, Codex, ask djbclark for the merge yes. Do not activate the away profile without his answers to batch item 2.
3. Prefer pools about to expire when routing (his standing latitude); keep batching questions.
4. Queue (last): the recurring `tests/test_self_slash.py` temp-dir flake and `tests/test_self_slash_codex.py` Errno 39 flake; site-djbclark follow-ups (fleet-watch ledger keyed `id@created`, `--no-ack` on `upr_send_line` and `upr_relay`); Cerevisor item 4 held; leave `fix/relay-tui-receipt` and `fix/self-slash-codex` alone.
5. The Item-32 wording (design C7.1) and the `pkill -f` example for item 33 go to an Opus 5.5 session only; I never edit `~/CLAUDE.md`.

## Detached jobs
none (all job records of this session are closed: adv-notx-r11/r12/r13, gates-followup, adv-gates-fu-r1).

## Quick Start
```bash
cd ~/src/djbclark-ade
gh pr view 91 --json state,headRefOid,mergeCommit
bin/pr-wait 91          # after gh pr checks 91 lists every check
aiuse --available --json 2>/dev/null > /tmp/aiuse.json   # .available[] usable_now, headroom_percent
bin/route_agent.py plan --kinds code --exclude claude,codex --json
git show origin/docs/model-tiers-design:docs/model-tiers-design.md > /tmp/mt-design.md   # section D
```
