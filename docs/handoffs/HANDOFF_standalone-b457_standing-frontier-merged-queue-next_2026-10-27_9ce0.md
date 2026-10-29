---
schema_version: 1
handoff_id: 9ce0
parent_handoff_ids: [0832]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: f7688fc45cedd966df20808bdb4eb20bacdda636
created_at: 2026-10-27T17:30:00-04:00
writer: claude-code
---
# Handoff — PR 91, 95, 96 and 97 merged; the frontier allowance is a standing rule; queue next

## The Goal
Drive the ADE ack wave and the gates and model-tiers workstreams to approved, merged PRs: an adversary review per repair round (omp Opus 5.5 high while the Claude gate is tight), Codex review and green CI, and djbclark's explicit yes pinned to the final head before every merge.

## Where We Are
1. Merged on djbclark's yes, each pinned to its reviewed head: PR 91 (gates follow-up A1-A4), PR 95 (model-tiers S1, away frontier allowance, `bed646d`), PR 96 (frontier hook `timeout 15` + `onFailure block`, `53752fc`), PR 97 (the frontier allowance as a STANDING baseline, `f7688fc`). Main checkout `~/src/djbclark-ade` is fast-forwarded to `f7688fc`, clean. All task worktrees except the handoff one are removed.
2. The live `~/.claude/settings.json` frontier hook entry now carries `"timeout": 15, "onFailure": "block"` (edited on his yes, 2026-10-27). Verified: valid JSON, hook exits 0 on a plain Agent call under PATH `python3` and `/usr/bin/python3`, `bin/ade-template-check` 0 findings.
3. PR 97 as built: `config/gates.toml` `[frontier]` is the ruled baseline (judged use on for both frontier models with a reason, `frontier1_per_wave` 2, `frontier2_per_wave` 1, 4 frontier-1 Agent-tool calls per NY day, `*_min_left` floors unchanged); `FRONTIER_DEFAULTS` stays all-closed (missing or corrupt gates.toml = closed); `ade_gates.baseline_limit` lets a frontier "higher" baseline rise only to its floor bound; `route_agent plan`'s 2-claude-slices cap holds only while `ade_gates.judged_pool_block` passes (shared with acp-dispatch); `read_guard_state` is FIFO-safe; the daily nudge needs a guard state under 30 min old. Three adversary rounds (r1 BLOCK, r2 APPROVE, r3 APPROVE at `2c2cc46`). Area suites 1303 passed at `ce68aca`.
4. Pools: Dann 6 (`495e0645`) owns the gifted-pools setup on `dann.dclark.us` with Dann VPS 2 (`88286468`) working under it; its three questions to djbclark are batched below. Relay links to Dann 6, Dann VPS 2 and the context-visibility session (`37f55ad9`, agent `ab4e97be`) are proven both ways.
5. No open job records of this session (13 stale finished records closed during this handoff). The `pr-wait` and waiters are done.

## What We Tried
1. `bg bash -lc '...'` and `bg python3 -m pytest` both failed: `bg` refuses a shell wrapper as a "full suite", and `python3` here is 3.15 without pytest. What works: `bg pytest -q -p no:cacheprovider <test files>` with the redirect on the calling shell.
2. A repair slice found `governor_hold` could not carry the planner guard (it reads the fleet-governor file, not the quota-guard state); the fix reused `judged_pool_block` instead.
3. Filling the CHANGELOG PR number after opening the PR moves the head (PR 96 needed an extra adversary round for it). For PR 97 the number was predicted (next issue/PR number after 96 was 97, checked with `gh api .../issues?sort=created`) and filled before `gh pr create`; that worked.
4. A bare `sed` in a Bash command was refused by the hook (use `gsed`); the whole command did not run, so nothing was half-done.

## Key Decisions
Standing frontier rule instead of an away profile because djbclark is not going away but wants frontier use open when required; caps stay the ruled ones; closing it is a reviewed PR (procedure in docs/gates.md, verified by the adversary). The `RecursionError` P3 on PR 97 was accepted for the merge and is to be fixed later (his answer: "Do 1, but make sure 2 gets folded in at a later point").

## Decisions
- [decision] Frontier allowance is the `[frontier]` baseline in gates.toml bounded by `[floors.frontier]`; rejected: raising `FRONTIER_DEFAULTS` in code; because a missing or corrupt gates.toml must mean closed.
- [decision] The planner's per-wave 2 on claude depends on the same guard checks as acp-dispatch; rejected: an unguarded planner cap; because the ruling says tight/critical stops the allowance.
- [decision] Accept the `RecursionError` P3 for the PR 97 merge; rejected: fixing it first; because it needs a hostile same-user writer and only crashes the planner (and djbclark chose to merge and fold the fix in later).
- [ruling] "I changed plans not going to be away but Frontier model use should still be open when required" (djbclark, 2026-10-27)
- [ruling] "Do 1, but make sure 2 gets folded in at a later point." (djbclark, 2026-10-27)
- [ruling] "You should have standing position to do your own self-slash compacts and handoff/new/baton cycles at what you feel are appropriate moments without asking me first." (djbclark, 2026-10-27)

## Relations
- continues [[HANDOFF_standalone-b457_pr91-gates-followup-then-s1_2026-10-27_0832]]
- decided_in [[HANDOFF_standalone-b457_standing-frontier-merged-queue-next_2026-10-27_9ce0]]

## Evidence & Data
Merges: PR 91 (gates follow-up), PR 95 `bed646d`, PR 96 `53752fc`, PR 97 `f7688fc`. PR 97 reports in `~/.local/state/bigteam/adhoc-2026-10-27/`: `adv-standing-r1-report.md` (BLOCK), `adv-standing-r2-report.md`, `adv-standing-r3-report.md` (APPROVE at `2c2cc46`), `frontier-standing-report.md`, `standing-repair1-report.md`, `standing-repair2-report.md`. Memory written (this project's memory dir): `project_gifted_pools_and_standing_latitude_2026-10-27.md` (updated), `feedback_self_compact_handoff_standing_permission.md`. Quota at last probe (early afternoon): Claude 7d about 77% used (tight per the fleet governor, projected 106% at reset 2026-10-30T09:59Z); the planner's pick for code is omp Sonnet 5.5 high.

## Operator Feedback
Standing permission (2026-10-27): do my own self-slash compacts and handoff/new/baton cycles at appropriate moments without asking. Standing latitude from earlier: use his other subscriptions, especially expiring ones, without asking; batch questions for his breaks. Batch for his next break (all unanswered):
1. Bedrock (Dann 6 Q1): the vault already has `AWS_BEARER_TOKEN_BEDROCK` (account djbcmit 828035973072, us-east-1, expires Oct 2027). Is that enough for the roughly $10 llama4 pool, or is there a new credit, account or model id? If a specific llama4 model or region is wanted, which?
2. opencode-go (Dann 6 Q2): the gift is 2 x $40 subscriptions but the vault holds one key (`OPENCODE_GO_API_KEY`, `oc_` prefix). Is there a second key to collect, or do the two share one?
3. VPS (Dann 6 Q3, confirm): "set up on the VPS" means the VPS hosts these pools (a LiteLLM-style gateway, opencode-go, Bedrock access) and the Mac's matching setup is removed once each is verified on the VPS? Anything specific the VPS pools should feed?
Relay each answer to Dann 6 (`495e0645`) through `relay.py` with `--expect-ack`.

## Where We're Going
1. THE next action: the `RecursionError` one-liner (his "2 folded in later"): in a new worktree off `origin/master`, change `bin/ade_gates.py` `read_guard_state` to `except (ValueError, RecursionError):` (as `read_profile_file` already does, about line 379), add a failing test first (a guard-state file `b"[" * 32768 + b"]" * 32768` must return None, run in a child with a timeout; the planner must not crash on it), one-token adversary (omp Opus: `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high`), CHANGELOG line ending with the PR number (predict it: next number after the last issue/PR), PR-body marker, `@codex review`, `bin/pr-wait N`, ask for his merge yes pinned to the head.
2. Queue, in order: (a) `relay.py` fix so an `--expect-ack` record whose sender has no readable transcript (tx:null) closes when the peer's ack is proven delivered (follow-up to PR 87; failing test first; asked Dann 6 for the record JSON; needs an adversary round); (b) the context-visibility in Paseo plus compact/handoff discipline audit: brief `/Users/djbclark/.local/state/ade-briefs/context-visibility-and-handoff-audit-2026-10-27.md` from session `ab4e97be` (relay id `37f55ad9`, ack `ctxvis-1027` done; it confirmed I am the intended LEAD "ade-queue-build"); examine, search, discuss with djbclark, fix; its findings so far: Paseo's meter ignores `autoCompactWindow` 300000 (upstream getpaseo/paseo#4949), 48 auto-compactions Oct 23-27 all at the wall (~267k), self-slash `/compact` used once; (c) add `docs/queue.md` entries for (a), (b) and the `RecursionError` fix in one docs-only PR (needs his merge yes); (d) test_self_slash.py temp-dir flake and test_self_slash_codex.py Errno 39 flake; (e) site-djbclark follow-ups (fleet-watch ledger keyed `id@created`, `--no-ack` on `upr_send_line` and `upr_relay`); Cerevisor item 4 held; leave `fix/relay-tui-receipt` and `fix/self-slash-codex` alone.
3. Pools: Dann 6 owns and monitors; no pool removal from the Mac until each pool is verified on the VPS; when his answers to the batch above arrive, relay them to Dann 6.
4. The Item-32 wording and the `pkill -f` example for item 33 go to an Opus 5.5 session only; I never edit `~/CLAUDE.md`.
5. Use compact (`bin/self-slash "/compact <focus>"`) or this handoff cycle at natural boundaries without asking (standing permission).

## Detached jobs
none (all job records of this session are closed).

## Quick Start
```bash
cd ~/src/djbclark-ade
git log --oneline -3                       # expect f7688fc at or near the top
gh pr list --state open --json number,title
git worktree add -b fix/guard-state-recursion-2026-10-27 ~/src/djbclark-ade-recursion-wt origin/master
rg -n 'def read_guard_state' -A22 bin/ade_gates.py     # the line to change
bin/route_agent.py plan --kinds code --exclude claude,codex --json
python3 skills/session-finder/relay.py --pending --text
```
