---
schema_version: 1
handoff_id: b457
parent_handoff_ids: []
lineage: none
chain: [standalone-b457]
repo: kool-ade
workspace: main
branch: master
head_sha: 24c989077788b91ebef0792293672d7ed2c9cc5c
created_at: 2026-10-24T09:00:00-0400
writer: claude-code
---
# Handoff — PR 27 and PR 31 merged; tabs, isolation and Basic Memory design rulings recorded

## The Goal
The /steps loop ("keep doing more /steps until there is nothing left to do") on kool-ade: drive the Phase 0 scan PR (27) and the Claude fleet-governor PR (31) to merge under the repo's review rules, record djbclark's three direct requests (Paseo tabs and `-pt` names with a name-history store; heavier use of cow pastures/worktrees for isolation; better use of Basic Memory), and make sure Claude quota is never exhausted before a reset.

## Where We Are
1. PR 31 merged (d3b2122, adversary APPROVE eaab5bf, Codex clean). `bin/claude-fleet-governor --install` done; launchd `com.djbclark.claude-fleet-governor` loaded, level `tight` (state `~/.local/state/ade/fleet-governor.json`; seven agents stay downshifted until the level is `ok`, then restore). The Claude weekly window reset 2026-10-24 10:00Z: 67% left, next reset 2026-10-30 09:59Z (aiuse).
2. PR 27 merged (24c9890, adversary APPROVE 7129031 after 69 rounds). Open at merge by djbclark's ruling ("merge now, follow-up PR"): Codex P2s 4365722733 (FIFO `CLAIM` blocks the scan) and 4367121323 (shallow bundle), adversary LOW/INFO items; all in docs/queue.md "ade-scan-state follow-up after PR 27".
3. Basic Memory upgraded 0.23.2 -> 0.24.1 (GHSA-4gfv-c2mm-mvj2; index backup `~/.basic-memory/backup-2026-10-23/`; foreign Host 421, foreign Origin 403 verified). Sessions need `/mcp` reconnect.
4. Design reports (all recommendations accepted by djbclark, recorded in docs/queue.md and proposal section 8: I0 isolation gate, M1 memory track): `~/.local/state/bigteam/adhoc-2026-10-23/design-{tabs,isolation,basicmemory}-report.md`. Nothing from them is built.
5. Pending peers: 23ca18d7 (rework-2 lead) is archived, so it was NOT notified (a send would unarchive it); djbclark-ade-64 (e934e0e6) was notified. Pastures phase0-scan and claude-governor removed; queue-docs, pr-wait, codex-*, review-selfslash etc. belong to others.

## What We Tried
1. Union-merging a diff3-style conflict with a regex kept the base section and a stray `|||||||` marker (PR 31 CHANGELOG): redone with `git merge-file --union ours base theirs`; do that, never regex diff3.
2. A one-row conflict where both sides inserted into the same README line: `--union` duplicated the row; resolved by applying both inserts to the base row with difflib.
3. Acp-dispatch records are under `adhoc-<date>`: after midnight a hard-coded `J` pointed at the previous day's jobs dir and the waiter exited 1; use the `record:` path printed by the dispatch.
4. Repeated "repair re-introduces the class" on PR 27 (17 rounds) was cut by implementing a principle ("the git dir must point back to this checkout") rather than patching variants.

## Key Decisions
1. djbclark: accept all design recommendations (tabs 10, isolation 7, Basic Memory 8); upgrade Basic Memory today; merge PR 27 at the approved head with the P2s queued.
2. PR 31 and PR 27 merged with macOS `pytest` red from two master-wide tests (`tests/test_self_slash.py::...passes_no_mode`, fixed by PR 35; `tests/test_acp_dispatch_quota_d2.py::...test_agy_exit0_quota_in_log_is_a_quota_stop`, date-dependent, new); same failures on master's own runs. Precedent: PR 33.
3. A docs-only merge of master into an approved PR head gets a cheap read-only adversary round (adv-scan-69 style) rather than skipping the head-SHA rule.

## Evidence & Data
Reports in `~/.local/state/bigteam/adhoc-2026-10-23/` and `adhoc-2026-10-24/` (adv-scan-65..69, adv-gov-14/15, fix-27-r65..67, design-*); briefs and scripts in `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/`. Basic Memory usage: 1.0% of 3,074 Claude sessions made any MCP call; 680 notes; zero decision notes.

## Operator Feedback
Times in America/New_York AM/PM with a 3-letter day name when not today; numbered lists; queue extra work until quota resets; every agent checks the quota before spending.

## Where We're Going
1. **Start the queued builds now that the weekly window has reset** (check `aiuse --available --json` and `bin/claude-fleet-governor status` first; governor level `tight` means Sonnet/omp workers only, no Opus/Fable Agent-tool sub-agents): first the ade-scan-state follow-up PR (docs/queue.md section), then I0 isolation W1-W8, Paseo tabs slices 8,1,2 then 3-7, Basic Memory W2-W8 (Q2-Q8), all `acp-dispatch ... --kind code`, Sonnet 5.5, adversary on W1/W3 of I0.
2. Microvm inventory (podman, kev, laya, hyades-docker): docs/queue.md entry, start after the above are underway.
3. Restore the seven downshifted Paseo agents only when the governor level is `ok` (it does this itself); verify `launchctl list | rg fleet-governor`.
4. Fix the date-dependent `test_agy_exit0_quota_in_log_is_a_quota_stop` and land PR 35 so master CI is green.
5. Ask djbclark nothing open: no question is pending.

## Detached jobs
none (all of this session's job records are closed).

## Quick Start
```
cd ~/src/djbclark-ade && git pull --ff-only
rg -n "follow-up after PR 27|Paseo tabs|Heavier use of Hermes|better use of Basic Memory" docs/queue.md
aiuse --available --json 2>/dev/null; bin/claude-fleet-governor status
```
