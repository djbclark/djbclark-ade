---
schema_version: 1
handoff_id: 4583
parent_handoff_ids: []
lineage: none
chain: [standalone-rework2]
repo: kool-ade
workspace: main
branch: master
head_sha: 3ffa82e
created_at: 2026-10-23T11:30:00-0400
writer: omp
---
# Handoff — token post-mortem shipped: quota guard, lead rule, successor flow; this lead moves to Opus

## The Goal

djbclark, 2026-10-21/23, in Paseo workspace `djbclark-ade-rework-2-pw` (agent `1dddc3ac`, omp
`anthropic/claude-fable-5-1` high): find out why the Claude weekly window ran out on 2026-10-20
(the Fable lead in `djbclark-ade-rework-p`, agent `6ebd939`), decide whether `aiuse` was wrong, and
change routing so an orchestrator never exhausts Claude again (a weaker lead model, weaker
sub-agents). Then own the two recommendation slices the peer lead had dispatched, drive them to
merge, and move this session itself off Fable. Rulings on the way: Paseo workspaces end `-pw`
(tabs `-t`, panes `-p`); the old workspace is closed when no longer needed; a lead switches its own
model from now on, never asks the operator to.

## Where We Are

1. **Post-mortem, verified from raw data** (not the peer's summary): `aiuse` was right and timely
   (weekly 58% at 00:06Z → 100% at 16:51Z on 10-20, `conserve` alert from 06:xxZ, nothing acted on
   it). The volume driver was the lead's **579 background-notification turns** against 49 operator
   prompts and 45 compactions, each re-reading a 150-200k context on Fable/Opus. Memory:
   `~/.claude/projects/-Users-djbclark-src-kool-ade/memory/project_claude_weekly_exhaustion_2026-10-20.md`
   (peer's), queue entry in `docs/queue.md` "Follow-ups from PRs 29 and 30" (mine, `330cade`).
2. **PR 30 merged** `2eeeb7a`: `bin/self-slash --finish --successor PROVIDER/MODEL` (Paseo): handoff →
   `paseo run "/baton" --workspace <id>` as a top-level agent → verify → archive self → archive the
   old workspace only when proven unneeded. 4 adversary rounds (round 1 HIGH: `paseo workspace archive`
   deletes a Paseo-owned worktree and kills terminals), 143 tests. Handoff skill Step 9 and
   `context_size_nudge.py` name the successor form for Fable or a tight/critical guard.
3. **PR 29 merged** `9ba3c54`: `bin/claude-quota-guard` (levels from `aiuse --available --json` plus
   the newest snapshot; an exhausted Claude is an ABSENT `--available` row; stale data → watch + one
   ping; exit 0-3 level, 10 unreadable, 64, 69), `claude/hooks/quota_nudge.py`, routing policy `[lead]`
   = Opus 5.5 high / Sonnet 5.5 high for pipelines / never Fable, adversary rounds via
   `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment` (omp judgment-eligible rank 2,
   so `ACP_OPERATOR_APPROVED=route-override` is no longer needed). 10 adversary rounds, 6 Codex passes
   (3 P1s fixed), 355 tests.
4. **Installed live (2026-10-23 11:26 EDT)**: `~/Library/LaunchAgents/com.djbclark.claude-quota-guard.plist`
   bootstrapped (state `running`, first check `ok: weekly 83% left`), state file
   `~/.local/state/ade/quota-guard.json`; `~/.claude/settings.json` UserPromptSubmit now carries
   `context_size_nudge.py` (was missing live) and `quota_nudge.py` (backup
   `~/.claude/settings.json.bak-2026-10-23-quota`).
5. **Harness fixes on master**: `acp-dispatch` refuses `--perm read-only`/`deny` for an agent whose
   `acp-run --info` `perm_modes` lacks it, before any record (`473ea82`, 3 tests); rule 21 corrected
   (`~/.agents/AGENTS.md` `e6e933a`, `.mdc` `c3aeadc`, memory `c278b3a`): after `git apply --cached`,
   commit with NO pathspec. `home-agents.md` is 13,616 bytes, over its 13,500 budget (it was 13,550
   before): a condense is due.
6. `~/src/djbclark-ade` master = `3ffa82e` = origin/master, clean (another session committed its relay.py
   work and fast-forwarded). Pastures `lead-model`, `quota-guard`, `queue-rework2` removed; `ade-update`,
   `phase0-scan`, `queue-docs` belong to peer `6ebd939`.
7. Peer `6ebd939` (chain `standalone-329d`, now on Sonnet after an in-place downshift) still drives PR 27
   and PR 20 and is building `bin/claude-fleet-governor` (branch `claude-fleet-governor-2026-10-23`): the
   actor that reads the guard's state and downshifts running agents through the daemon's
   `set_agent_model_request`. It hands off and tells this workspace when done.

## What We Tried

1. `acp-dispatch omp … --perm read-only` for the first adversary round: acp-run has no verified
   read-only mode for omp, the record went no-report in 2 s. Fixed in `473ea82`; every later round
   ran `--perm all` with a read-only brief and a tree/status check before and after (all unchanged).
2. `git apply --cached` for a shared CHANGELOG.md followed by `git commit -m MSG -- <paths>`: the
   pathspec committed the working tree, so a peer's hunk went to master (`473ea82`), retracted in
   `f14f88e` with plumbing (`git commit-tree`). Rule 21 now says no pathspec after `apply --cached`.
3. Bounding the review loop: PR 29 needed rounds 2-10 because each fix opened new edge cases
   (snapshot fallback, malformed input, stale data, windowless rows). What ended it: fixing P1/MEDIUM
   only, answering P2/LOW on the PR and queuing them. Two hypothetical-shape P2s from Codex pass 6 are
   answered and queued, not fixed.
4. Three waiters per head (CI, Codex, adversary) are the notification multiplier the post-mortem
   found; replaced by one `pr-wait.sh` per PR (CI + Codex marker + findings JSON), queued for `bin/`.

## Key Decisions

1. Lead model: Opus 5.5 high; Sonnet 5.5 high for pipeline-driving; never Fable (peer's recommendation,
   djbclark approved). Rejected: keep leads on Fable with a lower effort (effort changes keep the cache,
   but Fable's per-token weight is the problem).
2. Adversary rounds on omp Opus (API credits) by default; Sonnet override only at `tight`.
3. Guard rulings: a projected-exhaustion alert is ignored while the weekly window is `pace_early`; one
   ping per level per reset period (no clamp on drop); stale data (>3 h) raises to `watch`, suppresses
   level pings, pings once per stale episode; persistent unreadable pings once on the second
   consecutive failure.
4. Successor rulings: automatic close of the old workspace stays the default but only for a proven,
   `local`-isolation, terminal-free, agent-free workspace found by exactly one cwd match; worktree
   workspaces are never auto-archived; the successor's cwd is the target workspace's own.
5. Extra levers (effort rule for pipeline leads, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, one waiter per
   PR) were queued, not folded into PR 29: djbclark's answer to the option card never arrived (he
   interrupted with the workspace/baton corrections) and the PR was already in review.

## Evidence & Data

1. Peer log (`paseo logs 6ebd939`, 11,918 lines): 579 `[Task notification]`, 152 `[Task]`, 45
   `[Compacted]`, 49 `[User]`.
2. aiuse snapshots `~/.cache/aiuse/snapshots/2026-10-20T*.json`: weekly 58 → 100 (16:51Z); Fable cap
   48 → 98.
3. Slice records and reports: `~/.local/state/bigteam/adhoc-2026-10-23/` (`jobs/*.json` all closed;
   `quota-guard-report.md` with `## Fix 1`-`## Fix 8`, `lead-model-report.md` with `## Fix 1`-`2`,
   `adv-quota-guard-{2..10}-report.md`, `adv-lead-model-{1..4}-report.md`, `pr29-r{2..6}-findings.json`,
   `pr-wait.sh`, PR bodies `pr-quota-guard-body.md`, `pr-lead-model-body.md`). Test logs under
   `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/{quota-guard,lead-model}-work/`.
4. Inherited (not mine) working-tree edits saved from the pastures:
   `adhoc-2026-10-23/{quota-guard,lead-model}-inherited-skill-everywhere.patch`,
   `quota-guard-inherited-untracked-mcp.json`.

## Operator Feedback

1. "The way you opened this didn't work. It opened a new entire paseo window instead of just a
   workspace, and I had to manually type continue" → successor always `paseo run --workspace <id>`,
   never `--new-workspace`; built into PR 30.
2. "-p conflicts with herdr panes, let's use -pw for paseo workspaces" → memory
   `feedback_herdr_tab_pane_naming_convention.md` (site-private `66f5d38`).
3. "update any subagents to report to this workspace" → records re-owned, waiters re-armed here.
4. "close the old workspace when it is no longer needed" → PR 30 does it with proof; the old
   `djbclark-ade-rework-p` (`wks_f70e3a0b7088d428`) still hosts `6ebd939`: not yet.
5. "I'll switch to opus when you complete the handoff work here, lmk when to do it, also in the
   future you should handle switching it" → memory `feedback_lead_switches_its_own_model.md`
   (site-private `17b4e44`); this handoff's Step 9 is the first live run of PR 30.
6. "The prompt suggested a handoff, but it didn't do any work yet. also the second option suggested
   sonnet but you previously suggested opus" → corrected: lead = Opus 5.5 high.

## Where We're Going

1. **THE next action (the successor, on Opus 5.5 high, after `/baton`)**: read
   `~/.local/state/self-slash.log` for the successor run's outcome and confirm this agent `1dddc3ac`
   was archived and its workspace kept (same workspace). If the log shows `successor: … NOT archived`
   (exit 11), the old agent is still there: archive it by hand (`paseo agent archive 1dddc3ac-869c-4900-b3e0-e951c5b21e8b`)
   and note the failure under `docs/queue.md` item 5 (PR 30 queued findings).
2. When peer `6ebd939` reports PR 27 and PR 20 merged and hands off: read
   `~/.local/state/handoffs/chains/standalone-329d/SESSION_LOG.md`, adopt its open items; then, once
   `6ebd939` is archived and `paseo ls --json` shows no other agent in `wks_f70e3a0b7088d428` and
   `paseo terminal ls --workspace wks_f70e3a0b7088d428 --json` is empty, `paseo workspace archive wks_f70e3a0b7088d428`.
3. `docs/queue.md` "Follow-ups from PRs 29 and 30": items 1-3 (effort rule, `CLAUDE_CODE_SUBAGENT_MODEL`,
   `bin/pr-wait`) are each one small Sonnet slice; 4-5 are the queued findings; 6 depends on the peer's
   fleet-governor branch.
4. Watch the guard for a week: `~/src/djbclark-ade/bin/claude-quota-guard status` and
   `~/.local/state/ade/claude-quota-guard.launchd.log`; the hook prints `[quota-guard <level>]` only
   above `ok`.
5. `~/ops/site-djbclark/home-agents.md` condense (over budget by 116 bytes; procedure in that file's
   header: prove no date, pointer or link was lost).

## Detached jobs

none (every record under `~/.local/state/bigteam/adhoc-2026-10-23/jobs/` owned by this session is
closed; the peer's records are its own).

## Quick Start

```bash
cat ~/.local/state/self-slash.log | tail -n 20
paseo ls --json | jq -r '.[] | select(.cwd|test("kool-ade")) | "\(.shortId) \(.status) \(.provider) \(.name[0:40])"'
~/src/djbclark-ade/bin/claude-quota-guard status
jq . ~/.local/state/ade/quota-guard.json
~/.claude/hooks/handoff-tools/.venv/bin/python ~/.claude/hooks/handoff-tools/session_log.py read --state-root ~/.local/state/handoffs --dir ~/.local/state/handoffs/chains/standalone-329d
gsed -n '6,48p' ~/src/djbclark-ade/docs/queue.md
```
