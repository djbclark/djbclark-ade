---
schema_version: 1
handoff_id: 9464
parent_handoff_ids: [a7e7]
lineage: deterministic
chain: [standalone-20d5]
repo: sudo-secretspec
workspace: djbclark-ade
branch: sudo-main
head_sha: 0839caf
created_at: 2026-10-23T06:05:00-04:00
writer: claude-code
---

# Handoff — 1b landed, `.29` released, and why 3b cannot be built as specified

## The Goal

Close the adversary findings against the `sudo-secretspec` release path
(`packaging/release.py` + `.github/workflows/sudo-release.yml`). The operator's
queue, decided through `/steps` on 2026-10-20, was: cut `.29` → remove the stale
HEAD keg → land finding 1b → write this handoff → implement finding 3b.

Everything before 3b is done. 3b is where the next session starts, and it starts
with a design question, not with code.

## Where We Are

| Item | State |
|---|---|
| `0.19.1-sudo.29` | **Released.** `/tmp/sudo27/release29.rc` = `rc=0`; bottle poured and `brew test` green on `Cellar/sudo-secretspec/0.19.1-sudo.29` |
| Stale `HEAD-7c1f700` keg | **Removed** (operator-approved). 44 MiB back; `.29` is now the only keg and is the linked one, `outdated: false` |
| Finding 1b (archive↔tag tree binding) | **Landed** on `sudo-main` as `9e1312e`, pushed with `0839caf`. 118 tests pass on Python 3.13 |
| Finding 3b (attest the source digest outside the build job) | **Open, and blocked on a design choice** — see below |
| Carried findings 5–8, F3.1 | Still as filed; F3.1 accepted by design |
| Review record | `~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md`, now 2,155 lines, pushed `0e48d53` with an addendum covering 1b and the 3b blocker |

`sudo-main` is clean and in sync with `origin/sudo-main` at `0839caf`.

**The installed boundary is still `0.19.1-sudo.28`** while brew holds `.29`.
Upgrading it is `sudo /opt/homebrew/opt/sudo-secretspec/libexec/sudo-secretspec
install` — a lifecycle command that authenticates interactively and replaces the
live privilege boundary. It was deliberately not run as part of this queue; it is
not blocking anything.

## What We Tried

1. **3b exactly as the reviewer specified it — abandoned on evidence.** The
   finding asks for `source.sha256` to be computed and attested "in a job that
   runs no cargo and no brew", with `fetch_bottle` verifying *that job's*
   attestation. `fetch_bottle` cannot do that. The only identity it can pin is
   the certificate identity, and `verify_attestation`
   (`packaging/release.py:1105-1132`) builds it as
   `https://github.com/<fork>/.github/workflows/<BOTTLE_WORKFLOW>@<ref>` — the
   **workflow file**, not the job.

   Not taken from reading the code. Verified against a real predicate: the `.28`
   bottle JSON's own attestation, `gh attestation verify --format json`, rc=0, in
   `/tmp/sudo27/att28/att.json`. `buildDefinition.externalParameters.workflow.path`,
   `runDetails.builder.id`, and the certificate's SAN / `buildSignerURI` /
   `buildConfigURI` all name `sudo-release.yml` and nothing finer.
   `runDetails.metadata.invocationId` names the *run*, which two jobs share.
   **No field anywhere in the predicate or the certificate identifies a job.** A
   second job in `sudo-release.yml` would therefore mint attestations
   indistinguishable from the bottle job's.

   (A false start inside this: `gh api
   repos/frdminc/sudo-secretspec/attestations/sha256:<source archive digest>`
   returns 404. That is correct, not a failure — the source archive itself is
   never attested; only the bottle tarball, its JSON, and `source.sha256` are.
   Go through the bottle JSON release asset instead.)

2. **Running the packaging tests with whatever `python3` resolves to — two
   wasted runs.** `~/ops/site-private/bin/bg -- python3 -m pytest` picked 3.15,
   which has no pytest (`rc=1`). `/usr/bin/python3` is Xcode's **3.9.6**, which
   *does* have pytest and reports **9 failed, 109 passed** — every failure being
   `extractall(filter="data")`, which did not exist before 3.12. Both readings
   look exactly like the cherry-pick having broken something and neither is.
   The command that works, and matches what `sudo-release.yml` pins:

       uv run --python 3.13 --with pytest python -m pytest tests/sudo_packaging/ -q

   Fixed at the source: `sudo-secretspec` `AGENTS.md` now carries a "Python
   packaging tests" subsection naming the command and the interpreter trap
   (commit `0839caf`).

3. **`brew cleanup` for the stale HEAD keg — does not apply.** `brew cleanup
   --dry-run sudo-secretspec` reports nothing; brew keeps HEAD kegs
   deliberately. `brew uninstall --force sudo-secretspec` would take *both*
   kegs. The keg directory had to go directly, after confirming nothing links
   into it (`find … -lname '*HEAD-7c1f700*'` empty) and that
   `/usr/local/bin/sudo-secretspec` is a 5.9 MB regular file, not a symlink into
   it.

4. **Committing this handoff into `~/src/djbclark-ade` directly — refused on
   sight.** That shared checkout is on another session's branch
   (`fix/firecrawl-host-allowlist` at `0fef6cf`) with their uncommitted edits.
   This file was written through a throwaway `git worktree` of `origin/master`
   at `/tmp/ade-handoff-9464`, which touches neither their working tree nor
   their HEAD.

## Key Decisions

1. **1b is a real binding, so `source.sha256` is no longer load-bearing.** 1b
   extracts the published archive under `filter="data"`, requires exactly one
   root named `<repo>-<version>`, fingerprints every file, directory and symlink
   (mode + content sha256; symlinks by target hash), and compares that against a
   `git archive` of `refs/tags/<tag>` fingerprinted identically.
   `describe_tree_mismatch` names up to five paths per kind. This trusts CI for
   nothing. Proved both directions before it was written: GitHub's real `.28`
   archive and a local `git archive` of its tag agree on **601 entries, zero
   differences**; the reviewer's own forgery (hostile `build.rs`, genuine pax
   `comment`) is refused and names `build.rs`.

   Rejected: keeping the pax `comment` check as the binding. The `comment`
   record is data *inside* the archive, so whoever serves the bytes chooses it —
   an accident check, which is all the narrowed docstrings now claim.

2. **`filter="data"` is passed explicitly even though 3.14 defaults to it.**
   Probed 2026-10-20: on **3.13**, which `sudo-release.yml` pins, an unfiltered
   `extractall` writes a `../../escaped.txt` member *outside* the destination
   with only a `DeprecationWarning`; 3.14 refuses. The argument is what makes
   the refusal independent of which Python runs the release. An earlier claim of
   mine that the argument is unconditionally "load-bearing" was wrong on 3.14
   and was corrected in both the code comment and the test docstring.

3. **The `xcode-27` runner is GitHub-hosted.** `.28`'s certificate reads
   `internalParameters.github.runner_environment: github-hosted`, which
   independently confirms what Part 1 of the review already stated. I had once
   described it as "self-hosted macOS" in a brief; that was wrong and never
   reached any committed doc. F1.1 remains the real risk — that an unrecognized
   *label* can fall through to self-hosted pools — not a claim about what it
   resolved to.

4. **The djbclark-ade branch divergence is the operator's call, not mine.**
   Re-verified 2026-10-20: local `master` was ahead 9 / behind 17, and `git
   cherry -v origin/master master` shows **8 of the 9 are already upstream as
   patch-equivalents** (the repo lands work through squashed PRs). Only
   `adc2012` ("handoff: a project's AGENTS.md may redirect the output dir",
   `skills/handoff/SKILL.md`, +4/−1) is origin-missing. The `djbclark-ade-db`
   peer confirmed the dirty files there are a third session's and offered an
   `update-ref` realignment; I declined it, because it rewrites a branch pointer
   in a checkout another session is actively working in. Reported, not fixed.

## Evidence & Data

- Release: `/tmp/sudo27/release29.rc` → `rc=0`. `brew info --json=v2` →
  `installed kegs: ['0.19.1-sudo.29']`, `linked_keg: 0.19.1-sudo.29`,
  `outdated: False`.
- Tests: `/tmp/sudo27/t1b3.rc` → `rc=0`, `118 passed in 0.86s` (uv, Python
  3.13). Contrast `/tmp/sudo27/t1b2.rc` → `rc=1`, `9 failed, 109 passed`
  (Xcode 3.9.6).
- Attestation: `/tmp/sudo27/att28/att.json`, from `gh release download
  v0.19.1-sudo.28 -R frdminc/sudo-secretspec --pattern '*.bottle.json'` then
  `gh attestation verify … --format json` (rc=0). The field table is reproduced
  in the site-private addendum.
- Commits this session: `sudo-secretspec` `9e1312e` (1b), `0839caf`
  (`AGENTS.md` interpreter note); `site-private` `0e48d53` (addendum).
- Tree-equivalence probe: `/tmp/sudo27/probe5/tree_probe.py` (601/601),
  `live.py` (real match + forgery caught), `filter313.py` (3.13 vs 3.14
  defaults), `/tmp/sudo27/probe4/len_probe.py` (six `Content-Length` shapes).
  These are `/tmp` scratch; the durable evidence is the tables in the
  site-private doc.

## Operator Feedback

From the `/steps` walk of 2026-10-20, all honoured:

1. Fix the six findings, note F3.1 as accepted-by-design — done at `c2150cb`.
2. Number every question-card option label — now `skills/steps/SKILL.md` §2
   item 2a, and memory `feedback_number_question_card_options.md`.
3. "1. Cut .29 once the review clears" — done, `rc=0`.
4. "1. Append both to the existing site-private doc" — done, `0e48d53`.
5. "3. Implement both" (1b **and** 3b), explicitly reversing my recommendation
   to leave them noted — 1b done; 3b is the open item below.
6. "1. Remove it after .29 pours" (the stale HEAD keg) — done.
7. "1. Keep working, handoff before 3b" — this document.

## Where We're Going

1. **THE NEXT ACTION: put the 3b design choice to the operator**, because both
   answers are defensible and the wrong one means rework. The finding as written
   is not implementable (see *What We Tried* 1). The two forms:

   1.1 **A separate workflow file** — `source-digest.yml`, triggered on the same
   tag, running no cargo and no brew, attesting only `source.sha256`. Its cert
   identity differs from `sudo-release.yml`'s, so `fetch_bottle` *can* pin it
   and the separation becomes genuinely checkable. Cost: a second workflow, a
   second attestation to fetch, and a cross-workflow ordering dependency on a
   tag push.

   1.2 **The reviewer's own escalation (c)** — "stop trusting CI's digest at all
   and make finding 1(b) the real check, at which point `source.sha256` becomes
   belt-and-braces rather than load-bearing." 1b now exists and does exactly
   that, locally, trusting CI for none of it. Under this reading 3b is largely
   answered, and what remains is to stop describing the attested
   `source.sha256` as evidence of anything stronger than "CI saw these bytes" —
   in the code comments and in `packaging/README.md`.

   My recommendation is **1.2**: it is already true, it removes a trust
   assumption rather than adding a mechanism, and 1.1 buys a provenance
   distinction that 1b has made redundant.

2. **Adversary pass on whichever 3b lands, scoped to `git show <fix sha>` only.**
   Non-negotiable here: three repairs in a row on this very file each introduced
   a defect of the class the previous review had just named
   (`memory/feedback_re_review_every_repair.md`). Tell it to assume the fix
   broke something, name the exception types `__main__` catches, and
   mutation-check every new guard (remove it, run its one test, expect `rc=1`).

3. **Cut `.30` to prove 3b end-to-end.** Nothing short of a real release
   exercises the attestation path.

4. **Report to djbclark (do not fix) the djbclark-ade divergence** — decision 4
   above. One commit, `adc2012`, is the whole of it.

5. **Optional, operator-timed:** upgrade the installed boundary `.28` → `.29`
   with `sudo /opt/homebrew/opt/sudo-secretspec/libexec/sudo-secretspec install`
   (interactive, replaces the live boundary; `--adopt-existing` is *not* needed
   for an upgrade).

6. **Carried, unchanged:** findings 5 (the CI gate watches `linux-ci.yml` and
   only that, so the day `agent-ci.yml` lands in `ci/base` its run is silently
   ignored), 6 (two `BOTTLE_FILENAME_RE` gaps), 7 (two cosmetic failure modes),
   8 (F3.4's residual plus one test of an unreachable branch), and F3.1.

## Detached jobs

None. No `bigteam` job record is owned by this session
(`~/.local/state/bigteam/*/jobs/*.json` yielded nothing open for it), and no
sub-agent was left mid-flight.

## Quick Start

```bash
# state
git -C ~/src/sudo-secretspec log --oneline -3          # 0839caf, 9e1312e, 48b709f
git -C ~/src/sudo-secretspec status -sb                # clean, in sync

# the tests (the ONLY interpreter that is right)
cd ~/src/sudo-secretspec && ~/ops/site-private/bin/bg -- \
  uv run --python 3.13 --with pytest python -m pytest tests/sudo_packaging/ -q \
  > /tmp/t.log 2>&1; echo "rc=$?" > /tmp/t.rc; cat /tmp/t.rc   # expect rc=0, 118 passed

# the 3b evidence, if it needs re-checking
python3 -I -c "import json;d=json.load(open('/tmp/sudo27/att28/att.json'));\
a=d[0] if isinstance(d,list) else d;\
print(a['verificationResult']['statement']['predicate']['runDetails']['builder']['id'])"

# the review record (2,155 lines; the addendum is the last ~70)
gtail -75 ~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md

# the code
# packaging/release.py:1105   verify_attestation -- the per-workflow cert identity
# packaging/release.py:578     tree_entries
# packaging/release.py:607     extracted_tree      (the filter="data" extraction)
# packaging/release.py:638     tag_tree            (git archive of refs/tags/<tag>)
# packaging/release.py:672     archive_facts       (the one memoised download -> digest, commit, tree)
# packaging/release.py:762     require_archive_matches_tag
# packaging/release.py:837     describe_tree_mismatch
```

Clean up the worktree this handoff was written in, once it is committed:
`git -C ~/src/djbclark-ade worktree remove /tmp/ade-handoff-9464`.
