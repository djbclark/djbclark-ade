---
schema_version: 1
handoff_id: d165
parent_handoff_ids: [a621]
lineage: deterministic
chain: [standalone-b457]
repo: kool-ade
workspace: main
branch: master
head_sha: e048e19
created_at: 2026-10-25T09:25:00-0400
writer: claude-code
---
# Handoff — wave 1 lead: O2 build and three adversary rounds in flight

## The Goal
Lead of kool-ade's ADE queue build wave 1: drive PRs 51, 52, 53 and 59 to merge-ready. Every merge needs
djbclark's explicit yes and is pinned with `gh pr merge --squash --match-head-commit <reviewed sha>`.

## Where We Are
1. PR 62 (launchd label with a slash) merged as `e15aeb9`. PRs 55, 58 merged earlier.
2. PR 59 (ade-git-guard): round 9 BLOCKed 7df76ad; djbclark adopted redesign O2 (`reference-transaction` + `pre-push` hooks
   in the common git dir, fail-open on a crash, humans exempt, plus a fail-closed shim). Build slice `o2-build-pr59` is
   working in `wt-iso-w1` (branch `build/iso-w1-2026-10-24`, local merge of master `9e03ffe`, unpushed as of 09:16). The PR head on
   GitHub is still 7df76ad. `wt-iso-w1` holds stray uncommitted files that are not ours: do not stage them.
3. PRs 53/51 repaired twice (53 `ea29b4f`, 51 `d286260`); adversary round 4 `adv-pr53-r4` is working. Preliminary notes:
   F2/F3 correct; LOW `paseo_tab_taken` raises TypeError on terminal `ls` null/number (never-fatal contract); NIT on kept==own slug
   docs; LOW stale `paseo_tab_context` docstring/dead branch. Tests, mutants and PR 51 docs still to check.
4. PR 52 (`8da9a56`, MERGEABLE): I fixed round 2's BLOCK G1 myself (handoff template decided_in bullet: a PR is a Markdown
   link inside the observation, never ending the line with `)`; Basic Memory 0.24.1's `is_observation` drops `[category] ... ](..)`
   lines that end in `)`). Round 3 `adv-pr52-r3` was dispatched, no report yet.
5. Jev-vs-GLiDE review done; Jev-only shadow restored (`~/.config/jev/backends` removed). Stray `fastino-glide` skill deleted
   (backup in `~/.local/state/ade/stale-drafts/`). origin/master is now `e048e19` (PR 65 merged by a peer).

## What We Tried
1. PR 59 guard as an argv-spelling shim: nine adversary rounds each found another spelling; round 9 BLOCK (F1, F2) ended it.
   Why it failed: a PATH shim cannot enumerate git's ways to move a ref; the hook layer sees the ref transaction itself.
2. Dispatch to codex `gpt-6-astra`: exit 5, headroom 0%. Used Fable via the claude route for the design consult.
3. First PR 52 edit script asserted the wrong anchor (`- \`- decided_in`); fixed by matching the backtick start.
4. `acp-dispatch-wait` / `check` read PR 62's slice as "lost" (PR 62 bug, now fixed); waited on report files with `bin/wait-file` instead.
5. Pinned merge of PR 62 failed on a conflict; merged master into the branch and asked djbclark to re-approve the new head.

## Key Decisions
1. O2 over: keeping the argv shim only (rejected: whack-a-mole), a sandbox (rejected: out of scope, "seatbelt not a sandbox"). Measured on git 2.56.0:
   the hook blocks fetch, `branch -f`, `update-ref` even with `--attr-source`/`--shallow-file`; `-c core.hooksPath=...` bypasses it, so the shim
   refuses hook-disabling config keys, `push --no-verify`, non-allowlisted commands in a foreign workspace, and judges `branch -m/-c` destinations.
   Record: `docs/queue.md` "ade-git-guard (PR 59): redesign O2 adopted"; consult: `frontier-pr59-design-report.md`.
2. PR 59 gets ONE more adversary round with a NEW brief: argv spelling out of scope; ref writes without a transaction, hook disabling via
   config, no-ref harms in a foreign tree, owner false refusals.
3. PR 51 is not redundant; merge order 53 before 51.
4. Jev: shadow, Jev-only (djbclark).

## Evidence & Data
Task dir `$D=~/.local/state/bigteam/ade-queue-build-2026-10-24`: `o2-build-pr59-{brief,report}.md`, `adv-pr53-r4-{brief,report}.md`,
`adv-pr52-r3-{brief,report}.md`, `frontier-pr59-design-report.md`, `repair2-prs-51-52-53-report.md`, `jev-dual1-review-report.md`.
Worktrees under `$D`: `wt-iso-w1` (59), `wt-tabs-s2` (53), `wt-tabs-docs` (51), `wt-bm-w2w5` (52), `wt-queue`.
Tests run this stretch: none by me; reports carry theirs. Heads: PR 51 `d286260`, 52 `8da9a56`, 53 `ea29b4f`, 59 `7df76ad` (GitHub).
Relays queued (not yet delivered): `20261025-091456-f635a2` to w2Q:p3 (relay.py bug, ownership), `20261025-091606-8dd488` to w2F:p45 (Go policy PRs 64/65).
Quota guard level is `tight` (this lead runs on Sonnet 5.5).

## Operator Feedback
Merge only with an explicit yes naming the head sha. Number card options. Links as markdown. Times in New York AM/PM. No unrequested todo items.

## Where We're Going
1. Re-arm the three waiters (Detached jobs below), read each report as it finishes.
2. `o2-build-pr59` DONE: verify the branch is pushed and CI is green, then dispatch the ONE adversary round on PR 59 (new brief, Opus via
   `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high -C $D/wt-iso-w1`). No merge without djbclark's yes.
3. `adv-pr53-r4` DONE: if BLOCK, repair and re-review the repair; else ask djbclark per PR (53 first, then 51). `adv-pr52-r3`: same for 52.
4. `relay.py --pending` to check the two queued relays; sequence the "Verified peer messaging" build items after the w2Q:p3 fix.
5. Close each finished job record (`.closed=(now|floor)`), update Tier 1.

## Detached jobs
1. `$D/jobs/o2-build-pr59.json`; report `$D/o2-build-pr59-report.md`; `.done` `$D/o2-build-pr59-report.md.done` (absent at 09:25, report `STATUS: working`);
   rearm `~/src/djbclark-ade/bin/acp-dispatch-wait $D/jobs/o2-build-pr59.json $D/o2-build-pr59-report.md.done`. Sonnet build of redesign O2 on PR 59; read, then adversary round.
2. `$D/jobs/adv-pr53-r4.json`; report `$D/adv-pr53-r4-report.md`; `.done` absent (report `STATUS: working`);
   rearm `~/src/djbclark-ade/bin/acp-dispatch-wait $D/jobs/adv-pr53-r4.json $D/adv-pr53-r4-report.md.done`. Opus round 4 on PRs 53 and 51; read VERDICT and VERDICT PR51 lines.
3. `$D/jobs/adv-pr52-r3.json`; report `$D/adv-pr52-r3-report.md` (not yet written); `.done` absent;
   rearm `~/src/djbclark-ade/bin/acp-dispatch-wait $D/jobs/adv-pr52-r3.json $D/adv-pr52-r3-report.md.done`. Opus round 3 on PR 52 `8da9a56`.
Each rearm is its own `run_in_background` call; the waiters of the old session do not survive. Then set the record's `owner` to the new session id.

## Quick Start
```bash
D=~/.local/state/bigteam/ade-queue-build-2026-10-24
cd ~/src/djbclark-ade && git fetch origin && git log --oneline origin/master -3
for p in 51 52 53 59; do gh pr view $p --json headRefOid,state -q '"PR '$p' \(.state) \(.headRefOid[:7])"'; done
grep -E '^(STATUS|VERDICT)' $D/o2-build-pr59-report.md $D/adv-pr53-r4-report.md $D/adv-pr52-r3-report.md
```
