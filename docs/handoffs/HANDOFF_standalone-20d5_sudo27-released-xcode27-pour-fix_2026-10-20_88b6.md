---
schema_version: 1
handoff_id: 88b6
parent_handoff_ids: [4422]
lineage: deterministic
chain: [standalone-20d5]
repo: kool-ade
workspace: kool-ade
branch: master
head_sha: 9d34c1f3cde724b995684088ea5390548be5b763
created_at: 2026-10-20T06:05:00-04:00
writer: claude-code
---
# Handoff — v0.19.1-sudo.27 published, the pour failed, the xcode-27 fix is pushed and proven

## The Goal

1. Resume chain standalone-20d5 from parent 4422 (`/baton`), which had parked with "next action: none
   required" and the next release named as the first live run of the tag-only paths.
2. Run `/loose` over the session; the audit found the chain's three optional items still open.
3. Via `/steps` the operator chose, in order: cut `0.19.1-sudo.27` now; delete the merged `bottle-ci`
   branch; run an adversary review on the released head; read the overdue SkillOpt-Sleep night rows.
4. After the release published but could not pour, the operator chose to fix the runner tag rather than
   compile locally, and to file the adversary review privately.

All four are done. The next release will pour on this Mac; nothing in this chain is blocked.

## Where We Are

1. **sudo-secretspec — `v0.19.1-sudo.27` is published**:
   https://github.com/frdminc/sudo-secretspec/releases/tag/v0.19.1-sudo.27 (2026-10-20T09:04:09Z, not a
   draft; assets `sudo-secretspec-0.19.1-sudo.27.arm64_tahoe.bottle.tar.gz` and the matching
   `.bottle.json`). Everything 4422 wanted watched on a first live tag run **worked**:
   1. `publish-bottle` succeeded in 8s (job 118548908185).
   2. Both `gh attestation verify` calls passed — tarball *and* JSON — with
      `--cert-identity .../sudo-release.yml@refs/tags/v0.19.1-sudo.27`, `--source-ref refs/tags/v0.19.1-sudo.27`,
      `--source-digest 1374f90d1d079e805875b72799daed654824fc38`, `--deny-self-hosted-runners`.
   3. The `'!v*-sudo.*'` filters held: exactly one workflow ran on the tag,
      https://github.com/frdminc/sudo-secretspec/actions/runs/39397974266 (success). None of the 14
      upstream `v**` tag workflows fired.
2. **The pour failed, and that refuted 4422's Evidence item 1.** `brew reinstall --force-bottle` ended
   ``Error: `--force-bottle` passed but frdminc/sudo-secretspec/sudo-secretspec has no bottle!``. The
   bottle block carries only `arm64_tahoe` (macos-latest is still macOS 26) while this Mac is macOS
   27.0.1 = `arm64_golden_gate`, Homebrew 7.0.10. 4422 predicted `find_matching_tag` would accept
   `:tahoe` as older-compatible but noted it had never actually been poured; it has now, and Homebrew
   refuses. **The installed boundary is still `0.19.1-sudo.26`** and `release.py` refuses to re-run
   because the tag and Release exist.
3. **The fix is pushed and proven**: sudo-main **1b9c210** points the `bottle` job at `runs-on: xcode-27`
   (GitHub-hosted macOS 27 arm64, GA 2026-10-15; `actions/runner-images#14404` documents the label),
   with the evidence, its date and the F1.3 risk in a comment. Proven **before** any release depends on
   it, which is the adversary's first recommended mitigation:
   https://github.com/frdminc/sudo-secretspec/actions/runs/39402115948 — `workflow_dispatch` on
   sudo-main, `bottle` green in **7m57s**, runner image `xcode-27-arm64/20261012.0260`,
   `arm64_golden_gate` 23 times in the job log, `publish-bottle` correctly **skipped** (dispatch, not a
   tag push). Local checkout is on sudo-main at 1b9c210, clean.
4. **`bottle-ci` is deleted from origin** (`git push origin --delete bottle-ci`; `ls-remote | grep -c`
   now 0). It was fully merged at 90a067e.
5. **The adversary review is filed privately**: site-private **ff05c7b**,
   `docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md` (40,814 bytes) with the path added
   to `.githooks/private-paths`. Verdict `APPROVE (76edcc1 with the uncommitted sudo-release.yml
   change)`; 3 MEDIUM, 11 LOW, none blocking. It regenerates N5/N6/N7/I1, whose text 4422 had lost with
   an ephemeral scratchpad.
6. **kool-ade 803a11e** (pushed): `docs/queue.md`'s "Resurface 2026-10-14" sub-item 1 is read and
   answered in place, replacing its own incorrect metering claim.
7. **site-djbclark ba99cc5** (pushed): home-agents item 21 now reads `git commit -m MSG -- <paths>`;
   `cursor/home-agents.mdc` kept in step; `home-agents.md` back under budget at 13,495 bytes / 121 lines.
8. **Not mine, left alone in kool-ade**: a large in-flight dirty set from another session
   (`bin/acp-dispatch`, `tools/acp-run/acp-run`, `CHANGELOG.md`, two deleted `tests/test_acp_*.py`,
   the paseo-* and graft SKILL.md edits, `.agents/skills/fastino-glide/`). Master moved from 94cc58d to
   9d34c1f under me during the session.

## What We Tried

1. **Recommended deferring the release on quota grounds — wrong premise, retracted.** The operator asked
   whether GitHub runners or a GitHub quota were the constraint. They are not:
   `frdminc/sudo-secretspec` is **PUBLIC** (`gh repo view` → `"visibility":"PUBLIC"`), so Actions
   minutes are free and unmetered, macOS runners included, and the last five runs were all green. A
   Forgejo/Hyades failover could not substitute in principle either: Hyades runners are Linux libkrun
   microVMs and a macOS bottle needs a macOS runner.
2. **`git commit -- <paths> -m "msg"` fails**: `error: pathspec '-m' did not match any file(s)`. The
   instruction's own wording (`always git commit -- <your paths>`) read as a complete form and invited
   it. Fixed at the source in ba99cc5 (item 7 above), both copies.
3. **`gh repo view ... | head` with `echo "rc=$?"` was denied by `bash_habits_gate`** — the status would
   have been `head`'s. Re-run writing to a log plus an `.rc` file.
4. **Claimed `bin/skillopt-sleep` did not exist** off one guessed path (rc=127). It is at
   `~/.local/bin/skillopt-sleep` (`command -v`), was retracted in the same reply, and its `status`
   output is in the queue.md findings.
5. **The release did not start when launched**: `bg` admission-gated it at load 21.65 on 8 cores
   (threshold 12), waiting up to 6h. The dominant consumer was another session's `dust` scan at 354%
   CPU (the `diskfree` skill). Correct response was to wait — not `BG_LOAD_WAIT=0`, not killing another
   session's work — and it self-started as the 1-minute load fell.
6. **The task notification said "exit code 0" while `/tmp/sudo27/release.rc` said `rc=1`.** Exactly the
   trap 4422 recorded. The rc file is what matters; the release had published and then failed at the pour.
7. **The first site-private commit was refused by its pre-commit hook** ("site-private holds private
   material only. Not on the private list"). Resolved as the hook instructs — the operator had already
   chosen site-private, so the path joined `.githooks/private-paths` in the same commit. The file was
   staged and survived the refusal; the interim copy under `~/.local/state/adversary-reviews/` was
   removed only after ff05c7b was pushed.

## Key Decisions

1. **Chosen**: cut `.27` now, once GitHub was shown not to be a constraint. **Rejected**: wait for a few
   hours, fail over to `/forgejo-ci`, review-first, leave it for the next real release.
2. **Chosen**: the one-line `runs-on: xcode-27` swap. **Rejected**: a matrix over `macos-latest` +
   `xcode-27` (`fetch_bottle` already globs `*.bottle.json` and returns a list, so the merge side may
   take it, but artifact naming, per-asset attestation and `publish-bottle`'s download all become
   per-runner, plus the 91 packaging tests) and queueing it with no change. Nothing else consumes this
   bottle — CI only ever runs `brew install --build-bottle` to build it — so dropping the tahoe bottle
   costs nothing today.
3. **Chosen**: leave the installed boundary at `.26` and fix the runner. **Rejected**:
   `brew reinstall --build-from-source` (the whole crate graph compiled locally, which is the load-40
   path the operator rejected when the bottle work began, and the machine was already at load 15-22).
4. **Chosen**: prove the label by `workflow_dispatch` before any release relies on it (adversary F1.3
   fix 1). **Not done**: F1.3 fix 2, a wall-clock deadline for `watch_run`.
5. **Chosen**: file the adversary review in **site-private**. **Rejected**: `frdminc/sudo-secretspec`
   itself and kool-ade docs — both public, and publishing unfixed MEDIUM findings about a signing
   and release path is a disclosure decision; and leaving it untracked under `~/.local/state/`, which is
   how the previous round's text was lost.
6. **Chosen**: read the night rows now. **Rejected**: flag the queue item stale, drop it, or leave it.
7. **Chosen**: delete `bottle-ci`. **Rejected**: keep it as a development marker.
8. **Chosen**: handoff, then keep working. **Rejected**: archive this Paseo workspace now; keep working
   with no handoff.

## Evidence & Data

1. **Release**: tag/Release/assets and job IDs as in Where We Are 1-3. Probe run 39402115948;
   released head 76edcc1 (`Update Homebrew formula for v0.19.1-sudo.27`), stamp 1374f90.
2. **Adversary**: 3 MEDIUM — **F1.3** (`timeout-minutes: 90` bounds execution, not queue time; an
   unmatched `runs-on` label leaves the job queued ~24h *after* the tag and Release are public, because
   `release.py:349-353` `watch_run` has no deadline), **N6** (the tag archive is hashed three times and
   is not bound to the local tag commit — the strongest of the four regenerated), **F3.1** (the signing
   job is the job that runs untrusted third-party code). LOW: N5, N7, I1 (unquoted `{{version}}` in the
   justfile, three places), F1.1, F1.2, F1.4, F1.5, F3.2, F3.3, F3.4. The swap itself weakens nothing
   cryptographic — the attestation identity pins the workflow ref and never named the runner.
3. **SkillOpt-Sleep night rows** (`nights.jsonl` 101 rows / 49 nights, `attempts.jsonl` 288 rows, since
   2026-10-14), now in `docs/queue.md`: metering is wider than the item claimed (agy 126 metered/1.21M,
   crush 53/623k, hermes 46/824k, zcode 13/2.90M on 10-16); `source` is the transcript source while
   `tui` is the answering backend (opencode shows `prompts: 0` in night rows against 45 answered
   attempts); 2 accepted proposals in seven nights (acp_dispatch 10-14, codex 10-18); the 10-19 night
   stopped on `deadline 06:30 passed` after 247 prompts and 25.7M tokens for 0 proposals, and on 10-19
   and 10-20 only the `claude` source ran; night 49 was `replay: mock` with 0 sessions harvested.
   Backend faults: agy builds `gemini-3.8-flash-medium` (the `@medium` effort glued onto the name; the
   runner has `gemini-3.8-flash`), agy `antigravity/claude_gpt` (7) and `antigravity/gemini` (6) not in
   `aiuse --available`, zcode `project_token_login_failed` x4 classified transient plus one rc=124 after
   914s, claude refused 6 times at `headroom 4.0% <= floor 5.0%`, opencode-go answering at 2.8-5.2%
   headroom against a 0.0% floor.
4. **Tests**: none run locally this session. CI: the probe run and the tag run are the evidence above.

## Operator Feedback

1. "Is the problem that we are out of github runners available, or is there a github runner quota we are
   running into? If so we can wait if the wait is just a few hours, otherwise we can failover to
   /forgejo-ci" — answered: neither; public repo, free unmetered runners. Then: cut it now.
2. "Paseo doesn't support quit, when running in it the workspace should be archived instead, but there
   should be a picklist asking the user he wants to archive or continue so the user has time to see what
   has been done in the workspace." **This already exists** in a peer's open PR
   https://github.com/djbclark/djbclark-ade/pull/19 (branch `paseo-lifecycle-2026-10-20`), whose `loose`
   Rule 4 is retitled "close by asking: handoff and continue, finish and archive, or keep working" and
   whose option 2 writes the final results as the last message before ending. Adversary `APPROVE (head
   9de301d)` after 7 rounds with 3 Codex passes folded in; Cursor Approval Agent passed; `pytest`,
   `pytest-linux` and Cursor Security Agent were still pending. Not merged — it is the peer's PR.
3. Fix the runner tag rather than compile locally; file the review in site-private; handoff then keep
   working.

## Where We're Going

1. **Next action: give `release.py`'s `watch_run` a wall-clock deadline** (adversary F1.3 fix 2):
   `~/src/sudo-secretspec/packaging/release.py:345-355` calls `gh run watch --exit-status` with
   `capture=False, check=False` and no timeout, so a queued-forever job blocks the operator's terminal
   for up to a day with the tag and Release already published. Fail with `BOTTLE_FALLBACK_HINT` instead.
   Read the finding first: `ggrep -n -A30 'F1.3' ~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md`.
2. **The real end-to-end proof is the next release**: `cd ~/src/sudo-secretspec && ~/ops/site-private/bin/bg just release 0.19.1-sudo.28`.
   With 1b9c210 the bottle should be `arm64_golden_gate` and `brew reinstall --force-bottle` should pour,
   taking the installed boundary from `.26` to `.28`. If the pour still fails, the fallback is
   `just release VER --build-from-source` (the serial is published by then; release.py's message says how).
3. **Merge PR #19 once its checks are green** (`gh pr checks 19 -R djbclark/kool-ade`), which is what
   makes Rule 4's archive-or-continue picklist canonical rather than branch-only. The peer owns it; ask
   before merging.
4. **Remaining adversary findings**, all in the site-private doc, none blocking: N6 (MEDIUM), F3.1
   (MEDIUM), N5, N7, I1, F1.1, F1.4, F1.5, F3.2, F3.3, F3.4. F1.4 and F1.5 both want a
   `sw_vers`/`RUNNER_ENVIRONMENT` assertion in the bottle job so a silent label remap fails in CI
   instead of at the pour — the cheapest real hardening left.
5. **SkillOpt-Sleep follow-ups** now that sub-item 1 is answered (`docs/queue.md`, the item headed
   "Resurface 2026-10-14"): its sub-items 2 (denied backends) and 3 (the `-C` strip gap) are still
   unraised, and the agy bad-model-id and zcode `project_token_login_failed` faults in Evidence 3 are
   concrete bugs nobody owns.
6. **The 10-19 night's deadline stop** (247 prompts, 25.7M tokens, 0 proposals, `stopped: deadline 06:30
   passed`) is worth one look at whether the chain's budget or deadline needs changing before another
   night spends that much for nothing.

## Detached jobs

none — this session owns no bigteam job records (the Step 1 query over
`~/.local/state/bigteam/*/jobs/*.json` for `owner == $CLAUDE_CODE_SESSION_ID` without `closed` returned
nothing). The release and probe were `run_in_background` tasks of this session, both finished and read
from their `.rc` files; they are not promised to outlive the session and nothing here depends on them.

## Quick Start

```bash
# release state: tag .27 published, boundary still .26, bottle job now on xcode-27
git -C ~/src/sudo-secretspec log --oneline -3 origin/sudo-main
sudo-secretspec --version; sw_vers -productVersion
gh release view v0.19.1-sudo.27 -R frdminc/sudo-secretspec --json tagName,assets

# the proof that the fix works (bottle green on xcode-27-arm64, arm64_golden_gate)
gh run view 39402115948 -R frdminc/sudo-secretspec --json status,conclusion,jobs

# the next action (F1.3 fix 2)
ggrep -n -A30 'F1.3' ~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md
ggrep -n -B5 -A20 'def watch_run' ~/src/sudo-secretspec/packaging/release.py

# the peer's PR that makes the Paseo archive picklist canonical
gh pr checks 19 -R djbclark/kool-ade
```
