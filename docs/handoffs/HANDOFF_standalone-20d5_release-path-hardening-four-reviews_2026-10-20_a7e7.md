---
schema_version: 1
handoff_id: a7e7
parent_handoff_ids: [88b6]
lineage: deterministic
chain: [standalone-20d5]
repo: sudo-secretspec
workspace: kool-ade
branch: sudo-main
head_sha: 6ce267478c7c4d9117dec5db87fd8ae7a9abe693
created_at: 2026-10-20T12:50:37-04:00
writer: claude-code
---

# Handoff — the sudo-secretspec release path, hardened across four adversary reviews

## The Goal

Close the adversary findings on `sudo-secretspec`'s release path, and make the
path's documented claims match what its code actually proves. Then exercise it
end to end with a real cut, because nothing had run it since `.28` — the
release whose pour failure started this chain.

Operator rulings this session, in the order they were given:

1. "Fix the six, note F3.1" — fix N6, N7, I1, F3.2, F3.3, F3.4; leave F3.1 as
   the accepted-by-design structural finding.
2. "From now on, number options so it is easy to reffer to them from here" —
   every question-card option label starts with its number. Landed in
   `skills/steps/SKILL.md` §2 item 2a (`a873329`) and
   `memory/feedback_number_question_card_options.md`.
3. Cut `.29` once the review clears.
4. **Implement both 1b and 3b** — reversing my inference that they were the
   same class as the accepted F3.1.
5. Remove the stale `HEAD-7c1f700` keg after `.29` pours.
6. Keep working; write this handoff before starting 3b.

## Where We Are

`origin/sudo-main` is at `6ce2674` (the `.29` stamp commit). Four hardening
commits landed before it:

| SHA | What |
|---|---|
| `507f04c` | closed six findings — **BLOCK**ed on re-review |
| `055b47d` | one download, claims narrowed, redirect pin |
| `dc8789d` | the four LOW items from `055b47d`'s review |
| `c2150cb` | `Content-Length` gate (the LOW from `dc8789d`'s review) |

**Release `0.19.1-sudo.29` is in flight** as of this writing: tag pushed, CI
gate green on both jobs, the bottle job at the attest/upload step. Log and
exit code: `/tmp/sudo27/release29.log`, `/tmp/sudo27/release29.rc` (the `.rc`
file is the authority — a background task notification misreported exit 0 for
a release that had failed, earlier in this chain).

**Finding 1b is implemented but NOT on `sudo-main`.** It is committed as
`a7e5759` in a detached worktree at `/tmp/sudo27/wt-1b`, held back
deliberately so it could not interfere with the running release. 118 tests
pass there; ruff check and format clean.

All four adversary reports are appended verbatim, in order, to
`~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md`
(2,088 lines, pushed as `e6f64e4`), with a reading-order table and a statement
of what each pass changed. They previously existed only in `/tmp`.

## What We Tried

**Three repairs in a row each introduced a new defect of the class the
previous review had just named.** This is the most expensive thing learned
here and it is now `memory/feedback_re_review_every_repair.md`:

1. `507f04c`'s fix for N6c added an unretried `urlopen` in
   `require_archive_matches_tag`, sitting in the documented post-publication
   404 window. `urllib.error.HTTPError` is an `OSError`, and `__main__`
   catches only `ReleaseError` and `CalledProcessError` — so a transient 404
   printed a traceback after the tag and Release were pushed.
2. `dc8789d`'s fix for that compared against the **raw** `Content-Length`
   header, so `int(declared)` raised an uncaught `ValueError` on
   `Content-Length: ` or a proxy's folded `40, 40`. Same class, same window,
   in the hunk written to close it.
3. `dc8789d` also shipped a test that proved nothing: it asserted only on
   `_OPENER`'s shape, so reverting the call site to `urllib.request.urlopen`
   left all 104 tests green. The reviewer proved it in a mirror checkout,
   where the suite then reached the live network.

**Approaches rejected, with the reason:**

- **Making `find_run`'s uniqueness check unconditional** (the obvious fix for
  F3.3) broke `test_find_run_without_a_workflow_keeps_the_newest_match`.
  Reverted for the review's narrower fix: `ci_gate` names `linux-ci.yml`. The
  residual is carried as previous-finding 5 — the gate now watches that
  workflow *and only that*, so the day `agent-ci.yml` lands in `ci/base` its
  run is silently ignored. `overlay_paths` in `scripts/github-ci-run:56`
  already lists it.
- **Gating the short-body check on the raw header** — see above. Replaced by
  `response.length`, which is what `http.client` itself parsed.
  `/tmp/sudo27/probe4/len_probe.py` proves the discriminator across six header
  shapes: `None` for all three bad shapes, non-`None` with the unread
  remainder for a real cut transfer.
- **`install_opener` for the redirect pin.** It mutates
  `urllib.request._opener` at *import* time, and `sudo-release.yml` imports
  `release.py` inside the bottle job — so importing a formula rewriter changed
  that process's redirect policy. Replaced with a module-private `_OPENER`,
  which also made the wiring testable.
- **Claiming `filter="data"` is load-bearing unconditionally.** It is not on
  this Mac: Python 3.14 already defaults to `data`. Probed on 3.13, which
  `sudo-release.yml` pins, an unfiltered `extractall` escapes the destination
  with only a `DeprecationWarning`. The comment and the test now state that
  split rather than the blanket claim, and the test says it cannot distinguish
  the argument from the default on 3.14.
- **An earlier version of the traversal test checked one guessed path two
  levels up** and would have passed on a real escape. It now diffs
  `tmp_path.rglob("*")` before and after.

## Key Decisions

1. **1b is a real binding now, not a narrowed claim.** The pax `comment`
   record is data *inside* the archive, so whoever serves the bytes chooses
   it — the reviewer built an archive with a hostile `build.rs` and the
   genuine commit id that passed the check unchanged. `a7e5759` extracts the
   archive and compares its **tree** against `git archive` of the tag with
   GitHub's own `<repo>-<version>/` prefix. The pax check is kept, because it
   gives a precise diagnosis for the common accidents.
   *Rejected:* leaving it narrowed (my recommendation; the operator chose to
   implement).
2. **Checked that the two sides agree on the real thing before writing the
   code.** GitHub's real `v0.19.1-sudo.28` archive and `git archive` of its
   tag fingerprint to **601 entries each, zero differences**
   (`/tmp/sudo27/probe5/tree_probe.py`). Had they disagreed in any
   tracked-visible way, a tree binding would fail every release.
3. **`tree_entries` records only what git tracks** — path, executable bit,
   symlink target, content digest. No mtimes, no uid/gid, no directories.
   That is what makes a reported difference always real and an irrelevant one
   never reported. A symlink is its target *string*, so swapping a symlink for
   a copy is a difference.
   *Rejected:* comparing tar bytes (GitHub's gzip is not byte-stable — the
   2023 change moved every archive), and reimplementing git tree hashing
   (modes, sorting, submodules).
4. **The tree comes off the same memoised download** as the digest and the
   commit. Adding a second fetch is exactly the defect `055b47d` closed.
5. **Every post-publication failure is a `ReleaseError` carrying
   `RESUME_BY_HAND_HINT`.** A failing `git archive` in `tag_tree` returns
   `None` rather than raising, so it reports through the same `_require`.
6. **1b held out of `sudo-main` while `.29` ran.** `just release` executes
   `packaging/release.py` from the working tree.
7. **The kool-ade master divergence is reported, not fixed.** See Where
   We're Going item 5.

## Evidence & Data

- Tests: **118 passing** in `/tmp/sudo27/wt-1b`
  (`tests/sudo_packaging/test_release.py`); 111 on `sudo-main` at `c2150cb`.
  Run with `~/ops/site-private/bin/bg pytest <file> -q` — a whole directory is
  refused with rc=3 as a full suite.
- Mutation-checked guards (remove it, run its test, expect rc=1): the
  short-body check, the `CalledProcessError` wrapper, `build_opener`'s
  handler, the tree comparison, the raw-header gate (3 parametrised cases).
  The `filter="data"` argument is **not** mutation-provable on Python 3.14 and
  the test says so.
- Probe evidence: `/tmp/sudo27/probe/` (pax forgery, 2-downloads),
  `probe2/` (8 redirect shapes, live github→codeload chain),
  `probe3/` (9 `Content-Length` shapes, the mirror-checkout mutation),
  `probe4/len_probe.py` (the `response.length` discriminator),
  `probe5/` (601-entry tree match, the live forgery, 3.13-vs-3.14 filter
  defaults). The durable copies of these tables are inline in the
  site-private doc.
- `brew info`: `linked_keg: 0.19.1-sudo.28`, installed
  `['0.19.1-sudo.28', 'HEAD-7c1f700']`. Boundary at `0.19.1-sudo.28`.
- `sudo-secretspec template-check` exits 1 by design on this Mac — the
  tracked template is the stock scaffold declaring zero secrets against 77
  runtime. Recorded in `memory/project_secretspec_template_check_drift_is_expected.md`.
  **Do not "repair" it.**

## Operator Feedback

- Option labels carry their number, always (ruling 2 above). He answers by
  ordinal and may sequence them ("3rd then 2nd").
- "Implement both" overrode my recommendation to leave 1b/3b noted. The
  lesson: do not infer the scope of a new decision from an earlier one
  (F3.1) without asking — I had folded three findings into one accepted
  category and he unfolded them.

## Where We're Going

1. **THE NEXT ACTION: read `/tmp/sudo27/release29.rc`.** If `rc=0`, `.29` is
   published and poured. If non-zero, read `/tmp/sudo27/release29.log` and
   follow the justfile RESUME RULES — the tag is already pushed, so **do not
   re-run `just release`**; finish by hand with `brew update --force && brew
   reinstall frdminc/sudo-secretspec/sudo-secretspec`.
2. **Land 1b on `sudo-main`.** `git -C ~/src/sudo-secretspec cherry-pick
   a7e5759` (or `git am` from the worktree), re-run the tests, push. Then
   `git worktree remove /tmp/sudo27/wt-1b`.
3. **Remove the stale HEAD keg** (operator-approved, after `.29` pours).
   `brew uninstall --force sudo-secretspec` would take *both* kegs, so this is
   a targeted removal of the `HEAD-7c1f700` cellar directory plus `brew
   cleanup`. It is unlinked, and the installed boundary under `/usr/local` is
   a separate copy brew never touches.
4. **Implement 3b** — the operator approved it and it is the last open
   finding. Compute and attest the source digest in a CI job that runs no
   cargo and no brew (the `packaging` job already exists, or add a two-step
   `source-digest` job), and have `fetch_bottle` verify *that* job's
   attestation. Why: an attestation proves "this workflow produced these
   bytes", never "these bytes predate the third-party code" — the bottle job's
   filesystem stays writable between the build step and the attest step. 3b
   **cannot be verified without cutting a release after it**, so plan for
   `.30`. Get an adversary pass on it (see Decisions, and the memory note).
5. **Report, do not fix, the kool-ade master divergence.** `master` is
   ahead 8 / behind 16 of `origin/master` with another session's uncommitted
   edits (`CHANGELOG.md`, `bin/acp-dispatch`, `tools/acp-run/*`,
   `tests/test_acp_*`). The `djbclark-ade-db` peer verified `c179f42` and
   `fb81bdf` are patch-equivalent to origin and that the only local-master
   commit origin lacks is `adc2012` — neither it nor the dirty files are
   theirs. Their suggested realignment (cherry-pick `adc2012` in a pasture,
   push, then `git update-ref refs/heads/master origin/master`) is sound but
   rewrites a branch pointer in a checkout a third session is working in, so
   it is djbclark's call.
6. **Carried adversary findings, unchanged and filed** (site-private doc,
   §"Reading order"): previous 5 (the `linux-ci.yml`-only gate), 6 (two
   `BOTTLE_FILENAME_RE` gaps), 7 (two cosmetic failure modes), 8 (F3.4's
   residual plus one test of an unreachable branch). F3.1 stays accepted by
   design; 1b is being closed, 3b is item 4.

## Detached jobs

None. No open `bigteam` job records are owned by this session (checked). The
`.29` release runs as a `run_in_background` child of this session and is **not**
promised to outlive it — if this session ends, read
`/tmp/sudo27/release29.rc`/`.log` to learn where it got to, and treat a missing
`.rc` as "it died with the session, state unknown: check `gh release view
v0.19.1-sudo.29` and the tap".

Two adversary sub-agents ran and both delivered; their reports are the two
appended sections of the site-private doc. Nothing is waiting on a sub-agent
and no sub-agent report begins `BLOCKED:`.

## Quick Start

```bash
# 1. Where did .29 get to?
cat /tmp/sudo27/release29.rc; tail -40 /tmp/sudo27/release29.log
gh release view v0.19.1-sudo.29 -R frdminc/sudo-secretspec

# 2. Land 1b (after .29 is settled)
cd ~/src/sudo-secretspec
git cherry-pick a7e5759
~/ops/site-private/bin/bg pytest tests/sudo_packaging/test_release.py -q > /tmp/t.log 2>&1; echo "rc=$?" > /tmp/t.rc
cat /tmp/t.rc   # expect rc=0, 118 passed
git push origin sudo-main
git worktree remove /tmp/sudo27/wt-1b

# 3. The stale keg (operator-approved)
HOMEBREW_NO_INSTALL_FROM_API=1 brew info --json=v2 frdminc/sudo-secretspec/sudo-secretspec \
  | python3 -I -c "import json,sys;f=json.load(sys.stdin)['formulae'][0];print(f.get('linked_keg'),[i['version'] for i in f['installed']])"
# expect .29 linked; then remove the HEAD-7c1f700 cellar dir only

# 4. The reviews, in order
open ~/ops/site-private/docs/sudo-secretspec-release-path-adversary-review-2026-10-20.md
```

Do not run `just release-dry` casually: `stamp.py` rewrites `Cargo.toml` and
`Cargo.lock` and the recipe commits `chore: stamp workspace <version>`.
