---
schema_version: 1
handoff_id: 79fd
parent_handoff_ids: [b166]
lineage: deterministic
chain: [standalone-b457]
repo: kool-ade
workspace: main
branch: master
head_sha: edd5b9684bd28a13635f134b8f95306a1ec2bd0c
created_at: 2026-10-25T02:20:00-0400
writer: claude-code
---

# Handoff — bm-lint and pr-wait merged, ade-git-guard redesign running

## The Goal

ADE queue build wave 1: land `bin/bm-lint` (PR 55, done), make `bin/pr-wait` post `@codex review` itself
(PR 58, done), land `bin/ade-git-guard` (PR 59, I0 W1) with an adversary APPROVE on its current head, then
coordinate a Codex review of Paseo PR 7817 with herdr tab `paseo-workspace-t` (last in the queue).
Standing: ask djbclark before every merge; a second BLOCK on the guard means stop and ask.

## Where We Are

Merged this session (each with `--match-head-commit` and djbclark's explicit yes):
PR 55 `bm-lint` squash 3d0c2e2; PR 58 `pr-wait` Codex request squash 7c3b73c. Queue follow-ups for both are in
`docs/queue.md` (commit 5ba1b66, "bm-lint (PR 55) and pr-wait (PR 58) follow-ups").

PR 59 `ade-git-guard`, branch `build/iso-w1-2026-10-24`, head **fdaad513466df896d9a9090e732622f9020fc816**, is
BLOCKed (Opus round 7, B1-B7, below). The redesign slice `iso-w1-r7fix` is running (see Detached jobs); its
worktree `T/wt-iso-w1` has no guard edits yet at 02:12 EDT (it started 02:11).
`T` = `~/.local/state/bigteam/ade-queue-build-2026-10-24`.

Round 7 findings (`T/adv-iso-w1-r7-report.md`): B1 `heads/X` destination not normalised (`pull . main:heads/wtb`);
B2 `--set-upstream` wrongly treated as taking a value; B3 `--multiple --no-multiple`; B4 `remote -v update` skips
fetch judgement; B5 default remote assumed `origin` (a single remote `up` breaks it); B6 clustered short options
(`config -zf`, `format-patch -ko`) write into another claim's tree; B7 docs/docstring/CHANGELOG overstate. F6: fetch
tests only hit the checked-out branch, where git itself returns 128.

`~/src/djbclark-ade` master = origin/master = edd5b96 (fetched 02:15); local dirty state is only the untracked
`.agents/skills/fastino-glide/` (another agent's). `wt-iso-w1` also holds foreign uncommitted files that must NEVER
be committed: `.claude/settings.json`, `.cursor/hooks.json`, a stray untracked file named `-`.

Open PRs (others'): 60 relay.py residuals, 53 tabs-s2, 52 bm-w2w5, 51 tabs-docs.

Tests last run: guard 607 passed (bash 3.2 PATH, 322 s) at fdaad51; pr-wait 93; bm-lint 63. After the redesign the
guard suite must be re-run.

## What We Tried

1. Guard judged fetch/pull/remote-update by parsing git's argument spellings (refspecs, `--set-upstream`,
   `--multiple`, default remote). Seven rounds of repair each reopened the class (Codex found 3 P1 bypasses, Opus r7
   found B1-B7). FAILED because the parser re-implements git's own option grammar. Redesign: ask git itself.
2. pr-wait first located the Codex request by timeline position. FAILED (r1 A1): GitHub orders `committed` items
   by commit date, which is forgeable. Replaced by server stamps: earliest check-suite `created_at` and latest
   `head_ref_force_pushed` for the head. Two more repairs (no-stamp adoption bypass, then adoption ignoring the push
   stamp) before round 5 APPROVE.
3. bm-lint: `urlsplit` crashed on hostile input (r5 BLOCK); replaced with `url_path()`. macOS CI Python 3.14 parses a
   100000-deep list, so the deep-nesting test accepts either outcome.
4. Bash 3.2 (`/bin/bash`) cannot parse `case` inside `$( )`: 505 macOS CI failures on the guard; `print_usage`
   function now replaces it. Test the guard with `PATH=/bin:/usr/bin:$PATH`.
5. Different-vendor review: GLM-5.3 on zcode (`ACP_OPERATOR_APPROVED=route-override`, model id
   `builtin:zai-coding-plan\GLM-5.3`) APPROVEd guard head 0845004 (round 5). z.ai weekly and the grok TUI then had
   0% headroom (z.ai resets 2026-10-28), so Opus ran round 7 and was not cut off by a safeguard.
6. Process slips: one bare `sed` (hook blocked; use `gsed`), one `pgrep -f` for a read-only check, and a waiter
   started as `( ... ) &` inside a background call (it survived; a second `pr-wait 58` then exited 4).

## Key Decisions

1. djbclark chose "Redesign fetch/pull judgement" after the second guard BLOCK (rejected: ship with documented
   limits, drop fetch/pull from the guard).
2. Redesign contract (`T/iso-w1-r7fix-brief.md`): only while a foreign claim exists, run `git fetch --dry-run
   --porcelain` (lists ref destinations without writing; verified) with a short timeout; unresolved means refuse rc
   77; delete the spelling parsers; sweep every short-option match (B6); tests assert rc 77 AND ref unchanged on
   non-checked-out claimed branches including `pull`; mutation-check each test; fix docs overstatements (B7, C5).
3. PR numbers collided (56 and 57 were other sessions'); CHANGELOG lines were renumbered (#59 guard, #58 pr-wait),
   each needing a narrow adversary round on the number-only delta. Reserve a PR number before writing CHANGELOG.
4. Verdict quote rule: `VERDICT: APPROVE|BLOCK <sha>` must name the PR's current head; every repair is re-reviewed.

## Evidence & Data

Reports in `T/`: `adv-iso-w1-r7-report.md`, `iso-w1-r7fix-brief.md`, `adv-prwait-r5-report.md`,
`bm-w3-fleet-watch.patch` (parked). Job records in `T/jobs/*.json` (all done except `iso-w1-r7fix`). Disclosed
guard LOWs from r5: D1 `--check` gated on the text mentioning git; D2 a prose line before `To` makes the push
dry-run unresolved. Quota at session start: Claude 5h 6%, 7d 46%, quota-guard "tight"; omp credits about 48%; z.ai
0% (resets 2026-10-28); grok TUI 0%; codex 66%. No memory file was written this session.

## Operator Feedback

"Can we just have a different vendor look at the daybreak-needed-for-codex items? Maybe an open weight model like
zai/zcode GLM5.3 that is less touchy with security stuff?" (done: GLM did round 5). Card picks: merge PR 55 now,
Opus first for the guard reviewer, merge PR 58 now, redesign fetch/pull judgement.

## Where We're Going

1. **Rearm the waiter for `iso-w1-r7fix`**, read its report, then in `T/wt-iso-w1` run the guard tests:
   `PATH=/bin:/usr/bin:$PATH ~/ops/site-private/bin/bg uv run --with pytest python -m pytest -q tests/test_ade_git_guard.py > out.log 2>&1; echo rc=$? > out.rc`
   (background; about 5 minutes). Commit ONLY our files via `git-commit-own`: `AGENTS.md CHANGELOG.md README.md
   bin/ade-git-guard bin/ade_claims.py tests/test_ade_git_guard.py docs/git-guard.md`. Push.
2. New adversary round on the new head: `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment
   --effort high` (fall back to a Cursor or opencode agent if a vendor safeguard cuts it off). A second BLOCK: stop
   and ask djbclark. On APPROVE: post `@codex review`, run `bin/pr-wait 59`, update the PR 59 body (quote the verdict
   line with the head SHA; label GLM vs Opus rounds), ask djbclark before merging
   (`gh pr merge 59 --squash --match-head-commit <sha>`), then record the guard's LOW follow-ups in `docs/queue.md`.
3. Offer djbclark the parked weekly `bm-lint` hook-up (`T/bm-w3-fleet-watch.patch`, a `fleet-watch` change in
   site-djbclark, a public repo: "goes up after bm-lint merges", which has now happened).
4. Message herdr tab `paseo-workspace-t` (session `paseo-d4`, cwd `~/src/paseo`, branch
   `feat/workspace-identity-accent`, upstream PR https://github.com/getpaseo/paseo/pull/7817):
   `python3 -I ~/src/djbclark-ade/skills/session-finder/relay.py paseo-d4 "<one line>"` only; offer a local Codex
   review (`acp-dispatch codex --kind frontier`, advises only). Never post upstream unless asked.
5. Wave 2 (I0 W2-W8, tabs slices 3-7, Basic Memory W4/W6-W8) waits on a guard APPROVE except independent slices;
   check `docs/queue.md` first.

## Detached jobs

1. `~/.local/state/bigteam/ade-queue-build-2026-10-24/jobs/iso-w1-r7fix.json`: guard redesign slice (Sonnet 5.5
   high via omp, cwd `T/wt-iso-w1`, brief `T/iso-w1-r7fix-brief.md`, pid 29363 started 02:11 EDT 2026-10-25, no git
   writes by the slice). Report: `~/.local/state/bigteam/ade-queue-build-2026-10-24/iso-w1-r7fix-report.md`
   (`STATUS: working` at 02:13). `.done`: `.../iso-w1-r7fix-report.md.done`, does not exist yet. Rearm (own
   `run_in_background` call, long timeout):
   `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/ade-queue-build-2026-10-24/jobs/iso-w1-r7fix.json /Users/djbclark/.local/state/bigteam/ade-queue-build-2026-10-24/iso-w1-r7fix-report.md.done`
   then `acp-dispatch check <record>` (1 partial, 3 no report: re-task, never reconstruct; 4 BLOCKED). Close the
   record with `.closed=(now|floor)` after acting. All other records of this session are done and read.

## Quick Start

```bash
T=~/.local/state/bigteam/ade-queue-build-2026-10-24
~/src/djbclark-ade/bin/acp-dispatch check $T/jobs/iso-w1-r7fix.json
git -C $T/wt-iso-w1 status -s          # guard edits plus the 3 foreign files (never commit those)
gh pr view 59 --json headRefOid,mergeable,statusCheckRollup
```
