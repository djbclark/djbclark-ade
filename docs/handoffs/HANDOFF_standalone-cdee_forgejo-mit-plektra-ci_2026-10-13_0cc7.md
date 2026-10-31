---
schema_version: 1
handoff_id: 0cc7
parent_handoff_ids: []
lineage: none
chain: [standalone-cdee]
repo: kool-ade
workspace: main
branch: master
head_sha: d94d4fa0d0974d9551ae70d68fb2b922c8400db8
created_at: 2026-10-13T18:12:00-0400
writer: claude-code
---
# Handoff — Forgejo skill, forgejo.mit.edu token, Plektra CI comparison

## The Goal
1. Give agents API access to https://forgejo.mit.edu (Forgejo 16.0.5): token in
   `sudo-secretspec` as `DJBCLARK_FORGEJO_MIT_EDU_TOKEN`, a universal skill in
   kool-ade. **Done and verified** (`forgejo-api whoami` returns the login).
2. Use the private test repo `djbclark/plektra-djbclark` on forgejo.mit.edu (a copy of
   the GitHub fork of Plektra) to **compare Gradle compile/test times: github.com vs
   forgejo.mit.edu vs local**, without starting new github.com or local builds just to
   test (operator rule). **Not done: two of three columns are empty** (below).
3. A local-agent <-> Forgejo-CI workflow with **no agent on the server** (operator:
   "we don't need claude installed on the other end"): local agent pushes, opens PRs,
   reads run logs and comments through the skill's scripts. Built, partly exercised.

## Where We Are
**Skill `skills/forgejo/`** (committed and pushed to `djbclark/kool-ade` master):
`scripts/setup-token` (declare + browser + `sudo-secretspec set` + verify),
`forgejo-api` (stdlib client, mutations need `--yes`), `tea-forgejo` (tea with the secret
on `GITEA_INSTANCE_URL`/`GITEA_TOKEN`), `git-forgejo` + `git-askpass` (HTTPS git via
`GIT_ASKPASS`, `credential.helper=` cleared), `ci-step-times` (per-step times from
Forgejo or GitHub), `SKILL.md`, and `examples/plektra/` (derived CI, probe, comparison,
SIPB report and Matrix post drafts, local timings). Linked into every installed TUI via
`skill-everywhere`; hubs in `~/ops/site-djbclark` and `~/ops/site-private` committed.
`fj` and `tea` are installed globally with brew; `docs/apply-toolchain-prompt.md` is at
5.10 with both (operator said yes). `pyforgejo` deliberately not global: use
`uv run --with pyforgejo` (operator chose that).

**MIT test repo:** branches `plk/main` (full copy), `bench/mit-ci` (plk/main + the
adapted `.forgejo/workflows/ci.yml`, **without** BENCHSTEP markers), `probe/runner`
(diagnostics). Local clone `~/src/plektra-djbclark` gained a `forgejo` remote (config
only; the clone's branches and files were not touched).

**The blocker:** the SIPB runner (`sipbphus`, label `ubuntu`) cannot run Gradle. Every
TCP connect to 127.0.0.1 or ::1 is refused inside a job (Python and Java agree), so
"Could not connect to the Gradle daemon" (run 170). Likely cause, from libkrun docs
and issue https://github.com/libkrun/libkrun/issues/818 (open, no fix PR): the job runs
in a libkrun microVM with no NIC, so TSI proxies sockets and `bind(port 0)+listen()`
lands on a different port in the VMM. The issue's reporter says
`--annotation krun.use_passt=1` (real virtio-net via passt, TSI off) fixes it, and that
fixed-port listeners work. **Not verified on SIPB's host.** The write-up for SIPB is
`skills/forgejo/examples/plektra/sipb-loopback-report.md`; a 1702-character Matrix post
is `.../sipb-matrix-post.md`. **Neither has been sent** (they go to people at MIT in
the operator's name).

## What We Tried
1. **Probe with `runs-on: ubuntu-latest`** (run 168): waited 4+ minutes `waiting`,
   never picked up, cancelled. The label is `ubuntu` (found in `SIPB/hyades`
   `docs/inessential.md`). A wrong label fails silently.
2. **Full adapted CI on MIT** (run 170): setup OK (~80 s: apt JDK 17, cmdline-tools,
   `sdkmanager` platform 36 + build-tools 36.0.0), then Gradle daemon connect failure
   after 1.5 s.
3. **Probe 171:** aborted at the first failing step because act runs steps with
   `bash -e`; the Gradle variants never ran. **Probe 172:** loopback table obtained
   (only 203.0.113.1 on `dummy0` connects), variants still skipped by `-e`.
   **Probe 173:** my edit put two lines after `continue-on-error: true`, YAML folded
   them: failed at once. **Probe 174:** `unshare -n sh -c 'ip link set lo up && ...'`
   hung over 5 minutes; cancelled with `POST .../actions/runs/174/cancel`. **Never put
   `unshare -n` in a job.** `ip link set lo up` has no effect.
4. **Gradle daemon logs:** first looked in `~/.gradle/daemon` (no task lines, no
   Plektra). The real ones are `~/.cache/gradle/daemon/8.13/daemon-*.out.log`.
5. **`ci-step-times` v1** parsed `Success - Main <step> [Ns]` lines; the Forgejo job
   log endpoint carries only the first step's `⭐ Run` marker, so it returned nothing.
   Rewritten to use `BENCHSTEP` markers or Gradle's own `BUILD ... in`.
6. **tea env login** with `GITEA_SERVER_URL`/`GITEA_SERVER_TOKEN` failed ("no available
   login"); `GITEA_INSTANCE_URL` + `GITEA_TOKEN` works (verified with a dummy token
   against a public endpoint, and with the real token via `tea-forgejo whoami`).
7. A first claim in the skill that a runtime `add` causes `template-check` drift was
   wrong here: `template-check` says "no tracked declaration source configured".
   Corrected and pushed.

## Key Decisions
1. **Personal access token, not OAuth2.** OAuth2 exists (auth code + PKCE, refresh)
   but tokens expire and refresh tokens rotate; a static secret store cannot follow,
   and `tea`/`fj` keep OAuth results in plaintext config. Rejected for agents.
2. **Own thin skill, no third-party skill or MCP server.** Checked: `magnus919/agent-skills`
   `forgejo-cli` (best, but third-party Python receiving the token, expects
   `FORGEJO_AGENT_TOKEN`), an mcp.directory `tea` cheat sheet, printing-press
   `pp-forgejo`, MCP `@ric_/forgejo-mcp` (103 tools, unnecessary). None adopted.
3. **Private normal repo + `git push`**, not a pull mirror (mirrors are read-only, so
   no branches/PRs on MIT) and not public. Operator chose this.
4. **Probe before building:** a tiny workflow first, to find whether a runner exists
   (operator chose this). It found one, and its label.
5. **`fj auth` and `tea login add` are forbidden for agents** (plaintext token files).
6. **MIT workflow is derived by script** from the repo's `ci.yml` so every Gradle step
   stays identical (`examples/plektra/derive-forgejo-ci.py`); only the label, checkout
   URL, a timed toolchain setup, an added compile-only step and `BENCHSTEP` markers
   differ; `upload-artifact@v4` dropped (unsupported on Forgejo).
7. **No new GitHub or local builds** (operator): the GitHub column comes from the next
   real PR's CI; the local column is mined from recorded builds.

## Evidence & Data
Runner facts (run 169): AMD EPYC, `nproc` 16, 62 GB RAM, 931 GB disk, Ubuntu 26.04.1,
root with sudo, runner v13.1.0, image `forgejo.mit.edu/sipb/ci-images:ubuntu`, no
Java/Android SDK, job starts in under 1 s, Android/Gradle/Maven hosts reachable
(0.13-0.24 s), `openjdk-21-jdk-headless` and 17 installable. Project: Gradle 8.13,
AGP 8.11.0, Kotlin 2.0.21, compileSdk 36, CI uses JDK 17.

Local baseline (94 recorded builds; `examples/plektra/local-timings.md`, comparable set
in section 4, summary in `examples/plektra/comparison.md`):
cold compile+configure (4-test run) 4 m 30 s; cold fresh full `testStableDebugUnitTest`
8 m 34 s (best), 11 m 53 s, 13 m 53 s (load 156); warm full run 2 m 17 s to 3 m 56 s
(about 3 min is tests); `lintStableDebug` 2 m 48 s warm to 6 m 31 s fresh tree.
Caveats: local daemon capped at 2 CPUs (`-XX:ActiveProcessorCount=2`), JDK 21, load
12-175 on 8 cores, Gradle's printed time includes the machine-wide Gradle slot wait
(a "1 h 11 m" row was 3 m 56 s of work), local plus remote build cache.
GitHub: zero runs ever (`ci.yml` is `pull_request` only; the other three workflows are
`workflow_dispatch`; upstream PR runs sit at `action_required`).
MIT run ids: 168 cancelled, 169 probe ok, 170 CI (Gradle connect failure), 171 to 173
probe failures, 174 cancelled. Commits this session in kool-ade: bc4811a, cf07a69,
faed249, d6ddd61, 2eeb63d, 6159bd8, d365663, d94d4fa.

## Operator Feedback
1. "If there is a forgejo CLI you can install it, ditto with python APIs." Installed
   `fj` and `tea`; explained why `pyforgejo` stays on-demand; operator confirmed that.
2. "You can make it a global install, that would be better." Brew installs are global.
3. "We don't need to do this with claude installed on the other end, we can do it in
   the way you think is best."
4. "Don't kick off new github.com or local builds just to test."
5. Asked for the Matrix post under 1900 characters and the web link to the report;
   gave both (post not sent).

## Where We're Going
1. **Operator decides whether to send the SIPB message** (Matrix post
   `skills/forgejo/examples/plektra/sipb-matrix-post.md`; report at
   https://github.com/djbclark/djbclark-ade/blob/master/skills/forgejo/examples/plektra/sipb-loopback-report.md).
   Sending is outward-facing: only on the operator's word. Nothing else on the MIT
   column can move until loopback works.
2. **When SIPB says it is fixed**, confirm first with the probe
   (`examples/plektra/probe-loopback.yml`, push it to `probe/runner`; takes under 3 min),
   then run the real benchmark: regenerate the workflow with markers, commit on top of
   `bench/mit-ci`, push (see Quick Start), read with `ci-step-times forgejo`. Repeat
   2-3 times for a spread (shared 16-vCPU microVM) and fill `comparison.md`.
3. **GitHub column:** after the next real PR on `djbclark/plektra-djbclark` finishes CI:
   `skills/forgejo/scripts/ci-step-times github djbclark/plektra-djbclark RUN_ID`. The
   first steps ("Run core modifier regression tests" etc.) are directly comparable
   with the same steps on MIT; the compile-only step exists only on MIT.
4. **Exercise the agent loop end to end** once Gradle runs: open a PR on the MIT repo
   (`POST /repos/djbclark/plektra-djbclark/pulls`), let `.forgejo/workflows/ci.yml`
   run on `pull_request`, read the failure log, comment, push a fix. The PR and comment
   endpoints are written in `SKILL.md` but **untested**.
5. Optional: delete branch `probe/runner` on MIT after SIPB replies; keep
   `bench/mit-ci`.
6. Not mine, leave alone: uncommitted `skills/autorename/*`, `skills/helm/*`,
   `tests/test_autorename_tab_label.py`, `tests/test_helm_question_status.py` in
   kool-ade belong to another agent.

## Detached jobs
none. No bigteam job records are open for this session. The sub-agent
`a4b902bc2f188eb6c` (local timings) finished and its report is saved as
`examples/plektra/local-timings.md`. No `run_in_background` task is still running; no
run is queued on forgejo.mit.edu (last run 174 is cancelled).

## Quick Start
```bash
cd ~/src/djbclark-ade && git pull
S=skills/forgejo/scripts
$S/forgejo-api whoami                                   # token works?
$S/forgejo-api GET "/repos/djbclark/plektra-djbclark/actions/runs?limit=5"
# after SIPB fixes loopback: build the marker workflow and push it to bench/mit-ci
python3 -I skills/forgejo/examples/plektra/derive-forgejo-ci.py ~/src/plektra-djbclark plk/main > /tmp/ci.yml
cd ~/src/plektra-djbclark && P=$(git rev-parse refs/remotes/forgejo/bench/mit-ci 2>/dev/null || git ls-remote forgejo refs/heads/bench/mit-ci | cut -f1)
# build a commit with /tmp/ci.yml at .forgejo/workflows/ci.yml on top of $P using a temp
# GIT_INDEX_FILE + git commit-tree (as in this session; do not touch the working tree), then:
~/src/djbclark-ade/$S/git-forgejo -C ~/src/plektra-djbclark push forgejo <sha>:refs/heads/bench/mit-ci
~/src/djbclark-ade/$S/ci-step-times forgejo djbclark/plektra-djbclark <RUN_ID>
# cancel a stuck run (the runner is shared):
$S/forgejo-api POST /repos/djbclark/plektra-djbclark/actions/runs/<ID>/cancel --yes
```
