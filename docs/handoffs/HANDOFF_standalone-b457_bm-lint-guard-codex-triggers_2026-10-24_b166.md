---
schema_version: 1
handoff_id: b166
parent_handoff_ids: [70ab]
lineage: deterministic
chain: [standalone-b457]
repo: kool-ade
workspace: main
branch: master
head_sha: 61672be
created_at: 2026-10-24T21:48:43-04:00
writer: claude-code
---
# Handoff — bm-lint PR 55 repairs, ade-git-guard held, Codex review triggers

## The Goal
Continue chain `standalone-b457` (ADE queue build, wave 1) via bigteam task
`ade-queue-build-2026-10-24` (`T=~/.local/state/bigteam/ade-queue-build-2026-10-24`):
land `bin/bm-lint` (PR 55), push `ade-git-guard` once it has an adversary verdict,
make `bin/pr-wait` request the Codex review itself, then coordinate a Codex review of the
Paseo workspace-accent PR with herdr tab `paseo-workspace-t`.

## Where We Are
| Slice | Worktree under `T` | Head | State |
|---|---|---|---|
| bm-lint, PR [55](https://github.com/djbclark/djbclark-ade/pull/55) | `wt-bm-w3` (`build/bm-w3-2026-10-24`) | pushed 0f677c5 (adversary r4 APPROVE); local 8484b52 NOT pushed | r5 adversary BLOCKed 8484b52; repair slice `bm-w3-r6` running |
| ade-git-guard (I0 W1) | `wt-iso-w1` | 0845004 NOT pushed (560 tests pass) | no adversary verdict; held |
| pr-wait fix | none | none | approved, not started |

Master was fast-forwarded to origin/master 61672be (PRs 32/34/36/37/38 and queue docs are in).
Open PRs 51, 52, 53 (tabs docs, Basic Memory drift, `paseo_tab_name`) are untouched this session.
`wt-bm-w3` shows ` M bin/bm-lint`: that is `bm-w3-r6` editing; do not touch it until its report exists.
`wt-iso-w1` has uncommitted files that are not ours and must never be committed:
`.claude/settings.json`, `.cursor/hooks.json`, and a stray untracked file named `-`.

Tests: bm-lint 55 pass at 8484b52 (via `bg`); guard 560 pass at 0845004; nothing run since.

## What We Tried
1. bm-lint went through five adversary rounds. R3 BLOCK: an unreadable note was dropped silently, so a
   store could print "ok, no findings"; fixed in 0f677c5 and approved in r4. Then Codex's PR review raised a
   P2 (bin/bm-lint, around line 492, thread on PR 55) plus a symlinked-directory gap; 8484b52 fixed both by
   counting http(s) PR/issue/commit links as decision provenance (`EXTLINK_RE`, `PROVENANCE_PATH_RE`, `cites`)
   and listing directory symlinks under `skipped`. R5 then BLOCKed 8484b52: `urlsplit()` raises ValueError on an
   NFKC-unstable netloc such as `https://example.com：8080/pull/1`, which crashes the whole run, and the
   top-level `except Exception` prints note text to stderr. `bm-w3-r6` is the repair.
2. ade-git-guard: Opus refused round 2 as cyber content; the round-2 reroute to Codex gave a provisional BLOCK
   (repaired in 0845004); round 4 on Codex gpt-6-astra was cut off by OpenAI's cyber safeguard, leaving a
   71-byte stub `adv-iso-w1-r4-report.md` and no verdict. Do not re-dispatch the same reviewer expecting a
   different answer.
3. Waiting on `bin/pr-wait` for PR 55 head 0f677c5 for 45 min ("codex-stuck", exit 3): nobody had asked Codex
   to review the push. A manual `@codex review` fixed it (memory `reference_codex_review_triggers.md`).
4. Bare `sed` is hook-blocked (use `gsed`); `| cut ||` and `sleep N` chains are hook-blocked: wait on
   background notifications instead.

## Key Decisions
1. djbclark: guard gets "one narrow fourth repair" (done, 0845004); after the vendor cutoff, "Do 2, and open
   that link": apply for Daybreak access (page opened in his browser:
   https://platform.openai.com/settings/organization/status-and-access) and hold the guard unpushed.
2. djbclark: `bm-w3-fleet-watch.patch` (weekly `bm-lint` in site-djbclark `fleet-watch`) goes up "after bm-lint
   merges"; it stays parked in `T`.
3. djbclark: PR 55's Codex P2 plus the symlink-directory gap are fixed now (8484b52, then r6).
4. djbclark: "Make pr-wait request the review itself": `bin/pr-wait` posts `@codex review` once when the head
   has no Codex review and none was requested since the push; after ~10 min of "Running" it re-requests once,
   then reports openai/codex#55890. Small PR in kool-ade, own adversary round, CHANGELOG line.
5. Rejected: re-reading the guard adversary result from the Codex stub, or merging the guard on the strength of
   the provisional BLOCK-repair.
6. Answer given to djbclark's late question ("is Codex refusing PRs at all, or just security-sensitive ones, or
   a specific project?"): two separate problems. (a) The Codex GitHub PR bot is not refusing anything: it
   reviews on PR open or draft-to-ready, not on push, and manual requests are sometimes stuck "Running"
   (openai/codex#55890). (b) Codex or Opus used as OUR adversary on the guard hit vendor cyber safeguards,
   because the slice is a shell-command parser built to block bypasses; the same Opus did five bm-lint rounds.
   Not verified: whether the safeguard is org/project-scoped, or whether the PR bot's security review would
   object to the guard. Report that to him if he asks again.

## Evidence & Data
1. Real-store lint counts that must stay stable (`bin/bm-lint --json` on `~/ops/site-private/memory`):
   dead-path 165, dead-subtree 3, duplicate-title 3, empty-project 8, missing-type 298, orphan-notes 34,
   oversize-note 4, stale-handoff 1, unresolved-relation 53.
2. Codex PR review timing: first review ~12 s after open on PRs 48-55; manual re-request on PR 55 completed in
   ~96 s (code) and ~4 min (security); on PR 31, 6 of 11 manual requests produced no review in 30 min.
3. Unconfirmed guard gaps hinted by Codex before it was cut off: (a) an unquoted heredoc delimiter joined across
   a backslash-newline hides the following git command; (b) ANSI-C quoting with NUL yields a command word
   different from bash's. Verify both against 0845004 before the next adversary round.
4. Reports and briefs in `T`: `adv-bm-w3-r2..r5-report.md`, `bm-w3-r6-brief.md`, `adv-iso-w1-r3-report.md`,
   `adv-iso-w1-r4-report.md` (stub), `codex-pr55-findings.txt`, `bm-w3-fleet-watch.patch`.

## Operator Feedback
1. "Codex reviews seem to not be working, investigate or tell me if current behavior is normal, do web
   searches." (answered above; memory `reference_codex_review_triggers.md`.)
2. "When you are done with this codex-fixing work, communicate with herdr tab paseo-workspace-t and coordinate
   getting its PR reviewed by codex."
3. "So I don't think I totally understand the problem - is codex refusing to look at PRs at all, or just
   security-sensitive ones, or just security-sensitive ones for a specific project?" (answered in Key Decisions 6;
   he may want it restated in plain words.)

## Where We're Going
1. **THE next action:** wait for `bm-w3-r6` (see Detached jobs). Then in `wt-bm-w3`: run the tests with
   `~/ops/site-private/bin/bg`, commit by path with `git-commit-own`, update the CHANGELOG bm-lint line
   (keeps `#55`) for the new behaviours, and dispatch adversary round 6 on the delta since 8484b52
   (`acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high`, name `adv-bm-w3-r6`,
   read-only brief).
2. On a round-6 APPROVE: push the branch, update the PR 55 body (verdict line + reviewed head SHA, disclosed
   follow-ups), resolve the Codex thread for the P2 after the code fix, post `@codex review` (a push does not
   trigger one), run `bin/pr-wait 55`, read CI and Codex state, then **ask djbclark before merging**
   (`gh pr merge --squash --match-head-commit <sha>`). After the merge, offer `bm-w3-fleet-watch.patch`.
3. Build the `pr-wait` change (Key Decisions 4) as its own small PR with an adversary round.
4. Guard: stays unpushed until djbclark has Daybreak access; then run the adversary (Codex frontier or other),
   check the two gaps in Evidence 3, repair, and push; PR number will be the next free number (its CHANGELOG
   line says `#56`: recheck at push, `gh pr list --state all --limit 3`). A second BLOCK: stop and ask him.
   Wave 2 (I0 W2/W3/W4/W5/W6-W8, tabs slices 3-7, Basic Memory W4 and W6-W8) waits on a guard APPROVE except
   slices that do not depend on it.
5. Last: message herdr tab `paseo-workspace-t` (session `paseo-d4`, cwd `~/src/paseo`, branch
   `feat/workspace-identity-accent`, upstream PR https://github.com/getpaseo/paseo/pull/7817) with
   `python3 -I ~/src/djbclark-ade/skills/session-finder/relay.py paseo-d4 "<one line>"` only. The Codex app is
   installed for djbclark's own repos, not getpaseo/paseo: offer a local Codex review of the branch diff
   (`acp-dispatch codex --kind frontier`, advises only) or a fork PR. Never post on upstream unless he asks.
6. When Claude quota allows nothing heavier: `tight` guard level on 2026-10-24: Sonnet leads, no Fable/Opus
   Agent-tool sub-agents.

## Detached jobs
1. `T/jobs/bm-w3-r6.json`: repair of the r5 BLOCK in `bin/bm-lint` (no `urlsplit` on note links, per-note parse
   failure goes to `skipped`, top-level `except` prints only the class name, regression tests incl. a canary).
   Report `T/bm-w3-r6-report.md` (`STATUS: working` at handoff). `.done` `T/bm-w3-r6-report.md.done`
   (absent at handoff). Rearm:
   `~/src/djbclark-ade/bin/acp-dispatch-wait T/jobs/bm-w3-r6.json T/bm-w3-r6-report.md.done`
   (expand `T` yourself; the record's `.rearm` is the same line). Start it as its own
   `run_in_background` call, set the record's `owner` to `$CLAUDE_CODE_SESSION_ID`, then
   `acp-dispatch check` the record; act per Where We're Going 1.

## Quick Start
```bash
T=~/.local/state/bigteam/ade-queue-build-2026-10-24
ls $T/bm-w3-r6-report.md.done; ~/src/djbclark-ade/bin/acp-dispatch check $T/jobs/bm-w3-r6.json
git -C $T/wt-bm-w3 log --oneline -3; git -C $T/wt-iso-w1 log --oneline -2
gh pr list --json number,title,headRefOid
```
