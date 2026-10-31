---
schema_version: 1
handoff_id: 4422
parent_handoff_ids: [9eaf]
lineage: deterministic
chain: [standalone-20d5]
repo: kool-ade
workspace: kool-ade
branch: master
head_sha: 0b5f1a2847f52814a871b4f969a5b3d7951d12c8
created_at: 2026-10-18T22:32:53-04:00
writer: claude-code
---
# Handoff — sudo-secretspec releases pour a CI-built, attested bottle; .26 released and installed

## The Goal

1. Resume chain standalone-20d5 (parent 9eaf: routing overhaul + release CI gate, all done).
2. Via /steps, the operator chose to cut `v0.19.1-sudo.26` now and upgrade the installed boundary.
3. After that release compiled secretspec locally (load 40 on 8 cores), djbclark (relayed by djbclark-ade-4d): build
   the macOS bottle on GitHub macOS runners and have release.py install it, with a local build only as a fallback.
4. Follow-ups the operator chose: attestations before merge; upstream `v**` tag workflows skip `-sudo` tags; fix
   load-watch's incident attribution.

All done. Nothing open in this chain needs action before the next release.

## Where We Are

1. sudo-secretspec (frdminc/sudo-secretspec):
   1. `v0.19.1-sudo.26` released: https://github.com/frdminc/sudo-secretspec/releases/tag/v0.19.1-sudo.26, gate
      https://github.com/frdminc/sudo-secretspec/actions/runs/39181237627 (linux + macos green), tap commit 7c1f700.
   2. Installed boundary upgraded .25 -> .26 via `sudo-ask /opt/homebrew/opt/sudo-secretspec/libexec/sudo-secretspec
      install`; `doctor: OK`, `check` rc 0.
   3. sudo-main fast-forwarded to **90a067e** (pushed; was 7c1f700), from branch `bottle-ci` (still on origin). It adds:
      `bottle` job (macos-latest arm64, contents read + id-token/attestations write, attests tarball AND JSON),
      `publish-bottle` job (only job with contents: write, push-to-tag only, needs packaging+bottle, no --clobber,
      concurrency groups), archive commit-id check (`git get-tar-commit-id` == GITHUB_SHA on tag push), release.py
      `fetch_bottle`/`bottle_entry`/`verify_attestation` (`--cert-identity ...sudo-release.yml@refs/tags/<tag>`,
      `--source-digest <tag commit>`, `--deny-self-hosted-runners`), `verify_release_assets`, `merge_bottle` with a
      regenerated-block compare, `brew reinstall --force-bottle`, `--build-from-source` fallback through bg from
      `$HOME`, `find_run --event push` + refuse multiple matches; justfile `set positional-arguments`; `'!v*-sudo.*'` in
      14 upstream tag workflows. 91 packaging tests. CI for head:
      https://github.com/frdminc/sudo-secretspec/actions/runs/39189516047; dispatch proof:
      https://github.com/frdminc/sudo-secretspec/actions/runs/39189493509.
   4. Local checkout is on sudo-main, clean.
2. site-djbclark (pushed): c237ed9 `bg` lets `just release*`/`release.py` run in a load-watch `ci`-mode repo
   (`--local-tests` still refused), tests/test_bg_ci_mode.py 37 passed; 3e9d9c0 home-agents item 2 says the atomic
   temp file goes in the same directory (also cursor/home-agents.mdc).
3. kool-ade (pushed): 0b5f1a2 load-watch briefs attribute the repo from the heavy processes' cwd (or nearest
   ancestor's), say whether they ran under bg and by which rule; 19 load_watch tests; full suite on GitHub CI
   https://github.com/djbclark/djbclark-ade/actions/runs/39186083335 (1754 passed).
4. Peer djbclark-ade-4d set `HOMEBREW_MAKE_JOBS=1` in /opt/homebrew/etc/homebrew/brew.env and `[build] jobs = 1` in
   /Volumes/mac256usb/Caches/Homebrew/cargo_cache/config.toml. It asked to be told when the bottle work landed; it had
   exited by then (socket gone), so the news went to Hermes instead.

## What We Tried

1. First `bg just release` was refused rc=3 (sudo-secretspec registered `ci`); the task notification said exit 0. Fixed
   in bg (c237ed9), not by BG_ALLOW_LOCAL_CI_ONLY.
2. Asked whether "not CI-only" meant flipping the repo to `local`: the operator meant only that nothing on GitHub was
   blocking; everything possible stays on CI. No registry change.
3. Built bg.new in the scratchpad and `mv -f` across filesystems: not atomic. Instruction fixed (3e9d9c0).
4. Review 1 (d590e7b) found the build job held contents: write and --clobber re-uploads; fixed in 62d2af7. Review 2
   retracted review 1's "artifact names are immutable" (upload-artifact `overwrite: true` exists) and found the
   unattested JSON whose `cellar` Homebrew writes unescaped into formula Ruby (N1), decoy-ref ls-remote (N2), gh
   prefix match before 2.102 (N3); fixed in 90a067e.
5. A combined `rev-parse | cut && ...` was denied by bash_habits_gate (pipe status); reran with `;` and rc files.

## Key Decisions

1. Chosen: bottle built on GitHub macOS runners and poured; rejected: keep the local brew compile (load 40).
2. Chosen: bg exemption for releases in ci-mode repos; rejected: registry `local` for sudo-secretspec, a one-off
   override.
3. Chosen: attestations before merge (operator); rejected: merge first / skip.
4. Chosen: `'!v*-sudo.*'` negative tag pattern in upstream workflows (2 lines per file, easy upstream merges);
   rejected: fixing go-static (devenv `dotenv.resolved` error, red on every tag since .20) or leaving them.
5. Slice decisions kept: `--force-bottle` enforces "never silently compile"; release.py waits for the bottle before
   the tap moves; ls-remote check dropped for the archive commit id; `--deny-self-hosted-runners` added; block compare
   is normalised-structural, not bytes.

## Evidence & Data

1. Bottle compatibility: runner builds `arm64_tahoe` (macOS 26.6); this Mac is `arm64_golden_gate` (27.0.1);
   Homebrew `find_matching_tag` returns `:tahoe` (older-compatible). Not poured over the live install.
2. Attestation proof: correct ref/digest exit 0; wrong ref, wrong digest, tampered tarball, shortened workflow name
   each exit 1.
3. Reports: /Users/djbclark/.local/state/bigteam/adhoc-2026-10-18/{sudo-bottle-ci,sudo-bottle-fix,sudo-bottle-attest,sudo-bottle-n123,loadwatch-attrib}-report.md;
   security reviews in this session's scratchpad (adversary-report.md, adversary2-report.md under
   /private/tmp/claude-501/-Users-djbclark-src-kool-ade/82c4844a-d21f-40fa-98ac-4793616a6919/scratchpad/,
   ephemeral; the slice reports quote their findings).
4. Tests: packaging 91 passed (bg, single file); CI green as linked above; no full cargo suite on this Mac.

## Operator Feedback

1. "Release now"; then "2, and also let's fix the repo so it is not CI-only"; clarified "everything possible should go
   to CI, it sounded like github itself was disallowing something".
2. Upgrade the boundary now; attestations before merge; skip upstream tag workflows on -sudo tags; fix load-watch.
3. 32c0 handoff: leave it to its owner.

## Where We're Going

1. **Next action: none required.** The next real release (`just release 0.19.1-sudo.27` in ~/src/sudo-secretspec,
   through `~/ops/site-private/bin/bg`) is the first live run of the tag-only paths: publish-bottle, the archive
   commit-id check, attestation verify with `refs/tags/<tag>`, and the `!v*-sudo.*` filters (only sudo-release.yml and
   Linux CI should run on the tag). Watch that run; if publish-bottle or verify fails, the fallback is
   `just release VER --build-from-source` (but the serial is then already published; release.py's message says how).
2. Optional hardening left from review 2 (info/low, not blocking): N5 a tag-ref dispatch is indistinguishable in the
   attestation; N6 the tag archive is hashed three times and not bound to the local tag commit; N7
   `verify_release_assets` passes the file name to `gh release download --pattern` (a glob); I1 `{{version}}` still
   spliced unquoted in the justfile; slice note: no "rest of formula unchanged" diff after the bottle merge. The
   full text was in adversary2-report.md (scratchpad, ephemeral); rerun an adversary review on 90a067e to regenerate.
3. Optional: delete the merged `bottle-ci` branch on origin (`git -C ~/src/sudo-secretspec push origin --delete
   bottle-ci`) — outward-facing, ask first.
4. Not mine, left alone in kool-ade: paseo skill edits + `.paseo-managed-files.json`, `skills/graft/SKILL.md`,
   `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_…` (another session's).

## Detached jobs

none (all five records under ~/.local/state/bigteam/adhoc-2026-10-18/jobs/ from this session are closed).

## Quick Start

```bash
git -C ~/src/sudo-secretspec log --oneline -3 origin/sudo-main
gh run list -R frdminc/sudo-secretspec -L 5 --json headBranch,conclusion,url
sudo-secretspec --version; sudo-secretspec doctor
```
