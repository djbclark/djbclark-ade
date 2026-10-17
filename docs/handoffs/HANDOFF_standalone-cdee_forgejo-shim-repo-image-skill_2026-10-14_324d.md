---
schema_version: 1
handoff_id: 324d
parent_handoff_ids: [14f9]
lineage: deterministic
chain: [standalone-cdee]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 08bcfa8dc7befed79039cf0b7131a85309b2460e
created_at: 2026-10-14T10:30:00-04:00
writer: claude-code
---
# Handoff — Forgejo CI: shim fixed, public shim repo, own CI image, forgejo-ci skill

## The Goal
Run the private Plektra repo's full CI (Gradle + about 1,400 Robolectric tests) reliably on SIPB's Hyades libkrun runner (forgejo.mit.edu, label `ubuntu`), give SIPB and libkrun accurate tickets, and leave the work documented and reusable (a public repo, a CI image, an agent skill). The parent handoff (14f9) ended with the hang root-caused and tickets filed; this session finished the flaky-test fix, then moved the work into its permanent shape.

## Where We Are
1. **The shim works.** `loopback-port-shim.c` (232 lines, MIT) fixes four libkrun TSI bugs (port-0 listener unreachable #818; a blocked recv/accept holds the socket lock so send/shutdown/getpeername block #819/#926; a listener closed during a blocked accept is not released #929; always-on SO_REUSEPORT #860). Full Plektra suite: 1,417 tests, **1 failure, `CornerButtonThemeTest`** (also fails on GitHub Actions and a laptop), runs 229, 230, 241.
2. **Public shim repo, now the only home:** https://forgejo.mit.edu/djbclark/loopback-port-shim (local `~/src/loopback-port-shim`, branch `main`, head `01f6467`, MIT). Contents: shim, `Makefile` (`make`, `make check`, verified on Ubuntu 24.04), `tests/` (probes, `java-churn/`), `docs/` (`shim-by-default.md`, `runner-notes.md`, ticket texts in `docs/tickets/`), `skills/forgejo-ci/` (canonical), `ci/probes/` and `ci/tools/` (probe workflows and tooling; they find `forgejo-api`/`git-forgejo` through `FORGEJO_SCRIPTS`, default `~/src/djbclark-ade/skills/forgejo/scripts`). The README has "What is not in this repository" (local-timings.md, the generated workflow, the general forgejo skill, pre-move history, pointers for old tickets).
3. **Own CI image:** `ghcr.io/djbclark/ci-image-plektra@sha256:90a5de59e4a7efaa70b4de6af3221023151a2087cfb2689cecfe18a6a1cf602e` (public, amd64; canonical Forgejo repo `djbclark/ci-image-plektra`, GitHub build mirror, local `~/src/ci-image-plektra`): `cirruslabs/android-sdk:36` + JDK 17 + node 18 + `/usr/local/lib/portshim.so` built from the new repo at a pinned commit. Run 240/242 probes pass (checkout works, shim fixes the blocked-recv stall, 20/20 reuse rounds); run 241 full suite on the first build (setup step 0.2 s instead of about 100 s, compile 4 m 25 s unchanged).
4. **Tickets:** SIPB/hyades#3 filed 2026-10-14 (asks SIPB to ship the shim precompiled and opt-in in the ci-images; body edited to point at the new repo; comments 28 on #2 and 30 on #3). All links in libkrun #819, #860, #926, #929 and SIPB/hyades #2, #3 were edited to point at the new repo (permalinks at commit `41a87c8`). No replies seen yet; nothing auto-watches.
5. **Skill:** `skills/forgejo-ci` (symlink in djbclark-ade to the new repo) is linked into every TUI via `skill-everywhere`; the general `forgejo` skill stays in djbclark-ade and points to it. `skills/forgejo/examples/plektra/` is now only a pointer README (old-name to new-path table; local-timings.md stays there).
6. **Cleanup done at the end:** 13 throwaway probe/bench branches on `djbclark/plektra-djbclark` deleted (kept `bench/mit-ci`, `plk/main`; runs 229, 230, 238-240, 242 still readable). `~/s` farm layout gained a `ci:` group (site-djbclark `tools/s-farm/layout.conf`).
7. **Git state:** djbclark-ade `master` head `08bcfa8`, pushed. Dirty files in it are **not mine**: `skills/autorename/*`, `skills/helm/*`, `tests/test_autorename_tab_label.py`, `tests/test_helm_question_status.py`. In `~/ops/site-djbclark`: `.zcode/`, `claude/commands/orca-tidy.md` (not mine). In `~/ops/site-private`: a Shizuku draft and `memory/reference/reference_djbclark_ade.md` (not mine).

## What We Tried
1. **Flaky MockWebServer tests** (this session's start): three TSI behaviours, not one. First guess "the shim still fails 3 of 20" in the reuse probe was wrong: the failures were stale listeners left by earlier no-shim runs on the same port (libkrun#929 corrected). A Python keep-alive repro was negative. Fixes that worked: poll() before blocking reads/accepts, never reuse a port soon, nanosecond seed (the old seed repeated within a second).
2. **Alternative job images** (run 239 and per-label run 238): `eclipse-temurin:17` saves nothing (no gcc, git, SDK); `mingc/android-build-box` is 5.9 GB; `cirruslabs/android-sdk:36` has the SDK but JDK 21 and no node, so it became the base of our own image.
3. **Doc moves, near misses:** my first automated edit of SIPB/hyades#3 would have deleted the "What I am asking for" heading and item 1 (a sentence-boundary bug); caught in the preview, redone as an exact-string replacement. The first draft of the SIPB request said "about 270 lines" and "MIT-compatible"; the file is 232 lines with no licence, corrected before filing. A BSD `sed` failure once filed an empty issue (parent session); the GNU-tools-first and `[ -s file ]` rules came from that.
4. **`make check` had only run on macOS** until the final sweep; now run in Ubuntu 24.04 (passes, with cosmetic unused-`write()` warnings).

## Key Decisions
1. **Public repo on forgejo.mit.edu** (not GitHub) for the shim, so SIPB sees it where the ticket is; chosen by the operator. **MIT licence** picked by me without asking (the draft had offered "however you prefer"); disclosed, the issue still offers to relicense.
2. **Image hosted on public ghcr.io, built by GitHub Actions** (operator choice) rather than forgejo.mit.edu's registry (runner pull credentials unverified) or a local emulated amd64 build.
3. **Opt-in, never global** shim: global preload risks `EINTR`/`SA_RESTART` surprises (untested prediction), doesn't reach Go/static binaries, and 4 concurrent VMs share the host loopback port space (#860). Rejected for now; asked SIPB only for a precompiled opt-in `.so`.
4. **Single source of truth = the new repo** (operator: "move to just using the new repo"). Old djbclark-ade path kept as a pointer README (tickets already link to it), skill `forgejo-ci` symlinked from djbclark-ade (hub chain unchanged). The general `forgejo` skill (token, forgejo-api, git-forgejo) deliberately stays in djbclark-ade because its scripts live there.
5. **Left as-is on purpose:** probe workflows in `ci/probes/` still fetch pinned djbclark-ade commits (permanent); old handoffs and a skillopt digest still cite old paths (dated records).

## Evidence & Data
1. Runs: 229/230 full suite 1 failure (shim); 238 shim on ubuntu/alpine/rocky; 239 alternative images; 240 and 242 own-image probes pass; 241 full suite on own image, 1417 tests, 1 failed, 5 skipped, step 3 m 2 s, setup 0.2 s, compile 4 m 25 s.
2. okhttp churn loop: about 30% failures and 150 s per 150 iterations without the shim, 0 of 800 and 1 s per 800 with it.
3. Image check output (GitHub Actions "Verify the pushed image"): root, OpenJDK 17.0.20.1, node v18.19.1, git 2.43.0, `/usr/local/lib/portshim.so` 21792 bytes, `ANDROID_HOME=/opt/android-sdk-linux`, `platforms/android-36`.
4. Files: `~/src/loopback-port-shim/` (all of the above), `~/src/ci-image-plektra/{Dockerfile,.github/workflows/build.yml,README.md}`, `docs/queue.md` items 4-6 in the Forgejo section (all DONE), memory `project_forgejo_ci_matrix_state.md`.
5. Commits (djbclark-ade, latest first): `08bcfa8`, `14db4f9`, `b82e1a2`, `de9f4c4`, `530d417`, `da6d68f`, `f26b337`, `24f5128`. Shim repo: `01f6467`, `3c106a8`, initial import. Image repo: pin-to-new-repo commit and initial.

## Operator Feedback
1. Label each list item once (`1.1` alone, no `1.` plus `1.1`); always GNU `g*` tools (brew), BSD only when needed; "We don't need to over-optimize for speed"; document everything and keep it in a skill; "move to just using the new repo, point old stuff and doc at it" and "be sure 2.4 is in the repo doc" (the not-here list); tickets only after testing finishes and after showing the draft.

## Where We're Going
1. **Next action (optional, when ready): check for replies** to the tickets and answer them: `gh issue view 926 -R libkrun/libkrun --comments`, same for 819, 860, 929, 924, 818; `~/src/djbclark-ade/skills/forgejo/scripts/forgejo-api GET /repos/SIPB/hyades/issues/3/comments` and `.../issues/2/comments`. If SIPB agrees, help them build the precompiled `.so` into the ci-images Dockerfiles (SIPB/ci-images); if they decline, point Plektra's workflow at the own image (`DERIVE_IMAGE=ghcr.io/djbclark/ci-image-plektra@sha256:90a5de59… ci/tools/push-bench.sh asis BRANCH`).
2. **Shim globally** (deferred by the operator): needs `SA_RESTART`/`EINTR` tests, per-job port ranges, and an answer for Go and other static binaries; design notes in `~/src/loopback-port-shim/docs/shim-by-default.md`.
3. **When the shim changes:** edit it in `~/src/loopback-port-shim`, bump `SHIM_SHA` in `~/src/ci-image-plektra/Dockerfile`, push (GitHub Actions rebuilds), read the new digest from the run's "Verify the pushed image" step, update `docs/`, the project memory and the workflow.
4. Cosmetic: `reuse-probe.c` has unused-`write()`-result warnings under gcc on Linux.
5. Not mine, leave alone: the dirty files listed in Where We Are item 7.

## Detached jobs
none (no bigteam job records owned by this session; no `run_in_background` task is running).

## Quick Start
```bash
cd ~/src/loopback-port-shim && git log --oneline -5 && make check   # Linux only is meaningful; macOS just builds
~/src/djbclark-ade/skills/forgejo/scripts/forgejo-api GET /repos/SIPB/hyades/issues/3/comments | jq -r '.[]|.user.login+": "+.body'
gh issue view 926 -R libkrun/libkrun --comments | tail -20
# run a probe on the runner (private test repo, base branch bench/mit-ci), then wait for it:
cd ~/src/loopback-port-shim && ci/tools/push-probe.sh ci/probes/probe-ownimage.yml probe/ownimage3
WAIT_MAX=600 ci/tools/wait-run.sh <sha-printed-above> /tmp/out.log
```
