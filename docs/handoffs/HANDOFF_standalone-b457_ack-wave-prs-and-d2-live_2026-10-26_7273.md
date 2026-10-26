---
schema_version: 1
handoff_id: 7273
parent_handoff_ids: [299c]
lineage: inferred
chain: [standalone-b457]
repo: djbclark-ade
workspace: djbclark-ade (lead session fd720445-c4ae-49fa-ae0a-cf2980a49ee8)
branch: master (shared checkout); work in worktrees, see Where We Are
head_sha: de17d82ddf90da6323f6645df0b208527d775930
created_at: 2026-10-26T17:05:23-04:00
writer: claude-code
---
# Handoff — ADE ack wave: PRs 75/84/85 merged, PR 87 in repair, D2 live

## The Goal
Continues the chain `standalone-b457` (parent handoff 299c, the ack-build wave: PR 75, slices A/B/C); lineage inferred from the matching work, since this session's start prompt did not name the parent.

Drive the relay ack-build wave and the gates, model-tiers and prior-art workstreams to approved, merged PRs: an adversary review per repair round, and djbclark's explicit yes before every merge not pre-approved.

## Where We Are
Merged this window (all squash, each pinned with `--match-head-commit` to the reviewed head, Hermes-pinged): PR 82 (f78d2b7), PR 75 relay prose-nudge (88f29b1, at c94c025), PR 84 gate profile (2dd4a50, at 4ffd78d after a master merge; djbclark re-approved the new head), PR 85 D2 prior-art shadow hook (de17d82, at db90b18). Worktrees for 75, 84, 85 removed.

D2 is now LIVE in `~/.claude/settings.json` (PostToolUse, PostToolUseFailure, UserPromptSubmit; djbclark said "Install now", 2026-10-26). 29 lines added, none removed; backup `/tmp/settings.json.before-d2`; smoke test through the exact command: exit 0, silent, one record. Records land in `~/.claude/state/prior-art-shadow/<session>.jsonl`; turn off with `PRIOR_ART_SHADOW=0` in the settings `env` block. Check that a real session produced records (`ls ~/.claude/state/prior-art-shadow`).

**PR 87 (expect-notx, https://github.com/djbclark/djbclark-ade/pull/87), branch `feat/expect-ack-no-transcript`, worktree `~/src/djbclark-ade-expect-notx-wt`, head `466df5b9742d5cf16554a238eeaad419836fab57`.** Adversary r4: `APPROVE at 0b1e0a1`. CI was green at 1a87f88. Codex then left a valid P2 (thread open): an ack arriving during a blocking send (a Hermes turn) hit a `reserved` record that the resolver ignored, so the sender went OVERDUE. Slice N5 repaired it in 466df5b (merge of master 8958e0c + code; 769 relay tests pass; five mutants each killed alone; report `notx-repair-N5-report.md`: `expect_stamp`, a fresh `reserved` record accepted under the identical conjunction and turned `acked`+`early`, `note_links_and_expect` does not overwrite it, `expect_release` drops it when the send did not happen). Adversary round 5 (narrow, Opus) is RUNNING on 1a87f88..466df5b: job `adv-notx-r5`.

## What We Tried
1. First D2 repair for Codex's subagent P2 (b2c811b) compared the subagent's `task_seq` with the parent's: adversary r6 BLOCK (a subagent ahead of the parent skips the reset; the parent's idle rule wrongly resets a working subagent). Replaced by a dedicated `prompt_seq` that only the main agent's UserPromptSubmit advances and a subagent's `prompt_seq_seen`, reset when it DIFFERS (7df8ed6, r7 APPROVE). Lesson, same as before: comparing two independently advancing counters is the bug class; a dedicated counter removed it.
2. `gh pr checks --watch` dies on `connection reset by peer` (the flaky tunnel, see memory `project_slow_tunnel_private_mac_hypothesis`): its rc=1 is not a CI failure. Replaced with `/tmp/ciwatch/poll.py PR...` (polls `gh pr view --json statusCheckRollup` every 60 s, tolerates errors). Recreate if /tmp is cleared.
3. The Linux CI E2BIG class returned in D2 (a 200 KB bytes parametrize id lands in PYTEST_CURRENT_TEST): fix is explicit `ids=`. Any new test with a huge parametrize value needs `ids=`.
4. A `perm read-only` adversary dispatch to omp is refused (no verified read-only mode): use `--perm all` with a read-only brief. The bg interpreter has no pytest: use `bg uv run --quiet pytest`.

## Key Decisions
Expect-notx merges BEFORE Codex's PR 79 (both edit `skills/peer-relay/SKILL.md` item 10; PR 79's owner rebases onto it). Non-blocking adversary notes were left as documented limits rather than another code round (D2: a subagent's `task_seq` can go backwards on a reset; a working subagent is reset by a user prompt, by design). A new head after a pre-approved merge needs a fresh yes from djbclark (PR 84, PR 85 were asked again). The 5 `tests/test_go_model_policy.py::test_direct_acp_refuses_before_handshake[*]` failures under bg (`No module named 'acp'`) are environmental and fail on master too (adversary verified on a scratch master checkout).

## Decisions
- [decision] D2 subagent task sync uses a dedicated prompt counter, not task_seq comparison; rejected: comparing task_seq (b2c811b, BLOCKED); because two counters advance independently; in [PR 85](https://github.com/djbclark/djbclark-ade/pull/85).
- [decision] An ack that arrives during a blocking send is kept as `acked`+`early` on the reservation; rejected: a separate early_ack field the open step consumes; because one record and one state keeps ack_sweep unchanged; in [PR 87](https://github.com/djbclark/djbclark-ade/pull/87).
- [decision] Expect-notx merges before PR 79; rejected: PR 79 first; because the SKILL.md item-10 clash is cheaper for the PR that merges second to resolve and PR 87 is already merged with master.
- [ruling] "1. Merge at 4ffd78d (Recommended)" for PR 84 (djbclark, 2026-10-26)
- [ruling] "1. Merge on green at aa3f101 (Recommended)" then "1. Merge at db90b18 (Recommended)" for PR 85 (djbclark, 2026-10-26)
- [ruling] "1. Expect-notx first (Recommended)" for the PR 79 ordering (djbclark, 2026-10-26)
- [ruling] "1. Install now (Recommended)" for the live D2 hook (djbclark, 2026-10-26)

## Relations
- continues [[HANDOFF_standalone-b457_ack-build-slices-pr75_2026-10-25_299c]]
- decided_in [[HANDOFF_standalone-b457_ack-wave-prs-and-d2-live_2026-10-26_7273]]

## Evidence & Data
Adversary verdicts: D2 r5 `APPROVE at 50156c6`, r6 `BLOCK at b2c811b`, r7 `APPROVE at 7df8ed6`; expect-notx r3 `APPROVE at 6bcd51f`, r4 `APPROVE at 0b1e0a1`. D2 tests 319 pass; four mutants each fail exactly their own test. Reports under `~/.local/state/bigteam/adhoc-2026-10-25/` (`adv-*-report.md`, `notx-repair-N4/N5-report.md`, `model-tiers-design-report.md`). PR 87 CI at 1a87f88: pytest, pytest-linux, context-policy all SUCCESS.

## Operator Feedback
djbclark interrupted one AskUserQuestion (PR 84 merge) and re-ran it through `/steps`; no other correction. Standing: merges only on his yes (pre-approvals pin a head); numbered option labels; hermes-ping on each PR milestone.

## Where We're Going
1. **Wait for adversary r5 on PR 87** (job below), read `adv-notx-r5-report.md`. If `APPROVE at 466df5b`: reply to and resolve the open Codex thread on PR 87 (GraphQL `addPullRequestReviewThreadReply` + `resolveReviewThread`; thread id from `reviewThreads`), update the PR body (verdict + SHA 466df5b + delta), check CI at the new head with `/tmp/ciwatch/poll.py 87`, then ask djbclark for the merge yes pinned to the head. If BLOCK: repair slice (Sonnet, brief file, absolute `-f`), re-review.
2. After PR 87 merges: tell Codex's PR 79 owner (`ad1224d`, branch `chore/relay-closure-01a173a2`) to rebase for the SKILL.md item-10 clash, via `session-finder/relay.py` and verify delivery (standing order 10).
3. Gates follow-up PR (worktree from master): A1 RecursionError in `read_toml`; A2 lock-path silence/`clear` unlink without lock + name path; A3 unfloored-key docs overclaim; A4 `extend` expired_notified. Then model-tiers S1 (away frontier allowance + away-advice text; design `docs/model-tiers-design.md` on branch `docs/model-tiers-design`, worktree `~/src/djbclark-ade-model-tiers-wt`, no PR yet), S2..S5. Before ACTIVATING the away profile ask djbclark for absence start/end and exact allowances (values ruled: judged use on for both frontier models, frontier-1 2 per wave, 4 frontier Agent-tool calls/day, frontier-2 1 per wave). Item-32 wording (design C7.1) and a sharper `pkill -f` example for item 33 go to an Opus 5.5 session only; I never edit `~/CLAUDE.md`.
4. Queue (last): fix the recurring `tests/test_self_slash.py::SelfSlashPaseoTests::test_finish_is_allowed_for_a_non_holder_and_with_the_override` temp-dir flake (CI also hit `tests/test_self_slash_codex.py::CodexWaiterTests::test_detached_waiter_has_its_own_process_session`, Errno 39 on tmpdir cleanup; same class).
5. site-djbclark follow-ups: fleet-watch ledger keyed `id@created` (PR 82 merged), `--no-ack` on fleet-watch `upr_send_line` (~908) and `upr_relay` (~955).
6. Held: Cerevisor queue item 4 / E1 transcript analysis (re-plan with `route_agent.py plan`; E1 reads D2's own_code records once they exist).
7. Leave `fix/relay-tui-receipt` and `fix/self-slash-codex` alone (djbclark).

## Detached jobs
1. `adv-notx-r5` — `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r5.json`; report `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r5-report.md`; done file `...adv-notx-r5-report.md.done` (does not exist yet, running). Rearm (own `run_in_background` Bash call, timeout 7200000): `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r5.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-25/adv-notx-r5-report.md.done`, then `acp-dispatch check <record>`. It is the narrow Opus adversary round on PR 87's N5 repair; act per Where We're Going item 1, then close the record (`.closed=(now|floor)`).

## Quick Start
```bash
cd ~/src/djbclark-ade-expect-notx-wt && git status --short && git log -3 --format='%h %s'
gh pr view 87 --json headRefOid,state,mergeable --jq '.headRefOid+" "+.state+" "+.mergeable'
acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-25/jobs/adv-notx-r5.json
python3 /tmp/ciwatch/poll.py 87      # background; recreate from this doc's What We Tried item 2 if /tmp is gone
ls ~/.claude/state/prior-art-shadow  # D2 live-record check
```
