---
name: forgejo
description: >-
  Use a Forgejo instance (forgejo.mit.edu by default) from an agent: issues,
  pull requests, repos, any /api/v1 endpoint, with the token held in
  sudo-secretspec. Use when a task mentions Forgejo, forgejo.mit.edu, Codeberg,
  `fj`, `tea`, or needs a Forgejo/Gitea API token set up or rotated.
---

# Forgejo

Canonical source: `skills/forgejo/` in `~/src/djbclark-ade` (written 2026-10-13).
Default host `forgejo.mit.edu` (Forgejo 16.0.5, Gitea-1.22-compatible API, probed
2026-10-13). API docs for any instance: `https://HOST/api/swagger`.

## Tools (installed globally, 2026-10-13)

1. `scripts/forgejo-api` — stdlib Python, one call to `/api/v1`. Re-runs itself
   under `sudo-secretspec run`; mutations need `--yes`, `--dry-run` prints the plan.
   `forgejo-api whoami`, `forgejo-api GET /repos/OWNER/REPO/issues`.
2. `scripts/tea-forgejo` — `tea` (brew, v0.16.0) with the secret mapped onto its
   env login (`GITEA_INSTANCE_URL` + `GITEA_TOKEN`), so nothing lands in
   `~/.config/tea`. Best for `issues`, `pulls`, `releases`, `api`.
2a. `scripts/git-forgejo` — git over HTTPS with the secret: `git-forgejo -C DIR
   push forgejo BRANCH`. The token reaches git only through a `GIT_ASKPASS`
   helper (`git-askpass`, holds no secret) and `credential.helper=` is cleared so
   the keychain never stores it. Keep remote URLs token-free
   (`https://HOST/OWNER/REPO.git`). Plain `git push` will prompt and fail by design.
3. `fj` (brew `forgejo-cli`, Forgejo-native) — fine **unauthenticated** (public
   repos). **Do not `fj auth add-token` / `fj auth login` for agents:** it keeps
   the token in its own plaintext key file, outside sudo-secretspec.
4. `pyforgejo` (PyPI, typed client) — a library, so install it on demand:
   `uv run --with pyforgejo python script.py` under `sudo-secretspec run`.
   Not installed globally: pip-style global installs into the brew Python would
   break its externally-managed marker, and uv caches it after the first use.

## Token setup

Run `scripts/setup-token [HOST]`. It declares `DJBCLARK_FORGEJO_MIT_EDU_TOKEN`
(optional, so `check` stays green on hosts without it), opens the token page in
the default browser, lets `sudo-secretspec set` take the pasted value, then
verifies it with `GET /user` and prints only the login. The name is
`DJBCLARK_<HOST upper-cased, . and - as _>_TOKEN`.

The declaration is a runtime `add`. On this machine `sudo-secretspec
template-check` says "no tracked declaration source configured" (2026-10-13), so
there is nothing to mirror it into and no drift is reported. If a tracked source
is ever configured, mirror the declaration there, or remove it with `delete` then
`undeclare`.

## Token or OAuth2?

**Personal access token (chosen).** Static, scoped, revocable, no expiry unless
set: exactly what `sudo-secretspec` stores. OAuth2 exists on the instance
(authorization code + PKCE, refresh tokens; `tea login add --oauth` and
`fj auth login` use it) but its access tokens expire and its refresh tokens
rotate, which a static secret store cannot follow, and both CLIs would keep the
result in plaintext config. Use OAuth2 only for a human at a keyboard, never for
agents.

## forgejo.mit.edu CI (probed 2026-10-13, test repo `djbclark/plektra-djbclark`)

Runner: SIPB's `sipbphus` (Forgejo Runner v13.1.0), docs in `SIPB/hyades`
(`docs/inessential.md`) and `SIPB/ci-images`. Read these before debugging.

1. **Label is `runs-on: ubuntu`**, not `ubuntu-latest` (a job on the wrong label
   waits forever, no error). Image `forgejo.mit.edu/sipb/ci-images:ubuntu`:
   Ubuntu 26.04, root with `sudo`, git, node 22, podman, nix. **No Java, no
   Android SDK** (`apt-get install` works; Android/Gradle/Maven hosts reachable).
2. **No default actions host:** write `uses: https://github.com/actions/checkout@v4`.
   `upload-artifact@v4` is unsupported on Forgejo.
3. Workflows live in `.forgejo/workflows/`; when that directory exists
   `.github/workflows` is ignored. The job starts within a second of the push.
4. Hardware seen by a job: AMD EPYC, `nproc` 16, 62 GB RAM, 931 GB disk. It is a
   libkrun microVM, shared with other users, so repeat runs for timings.
5. **Gradle needs the port-0 shim there.** Inside the job a listener bound to port 0
   cannot be connected to (even from the same process): libkrun TSI bug libkrun#818;
   fixed-port binds work. Gradle's daemon, test workers and Kotlin daemon all bind
   port 0, so unshimmed builds die with "Could not connect to the Gradle daemon"
   (runs 168-174, 176). SIPB does not want `krun.use_passt=1` (nested passt). **Fix,
   verified in runs 175 and 177 (Gradle daemon, forked test worker, 4+ test steps
   `BUILD SUCCESSFUL`):** `examples/plektra/loopback-port-shim.c` is an `LD_PRELOAD`
   shim that rewrites port-0 `bind()` to a random port in 20000-32000. In the job:
   `apt-get install -y gcc libc6-dev`, `gcc -shared -fPIC -O2 -o /usr/local/lib/portshim.so
   shim.c -ldl`, `echo /usr/local/lib/portshim.so >> /etc/ld.so.preload` (root).
   **An `LD_PRELOAD` written to `$GITHUB_ENV` does not reach Gradle's daemon (run 176)**;
   `/etc/ld.so.preload` does. `derive-forgejo-ci.py` adds this step. `--no-daemon` does
   not help (Gradle forks a single-use daemon over the same socket). `examples/plektra/sipb-loopback-report.md`
   has the report and the 2026-10-13 update.
   **Second TSI bug, found 2026-10-14 (runs 189-205): `shutdown(2)`, `getsockopt` and `getpeername`
   block while another thread is blocked in `accept()` or `read()` on the same socket.** Java's
   `ServerSocket.close()`/`Socket.close()` call `shutdown()` first, so okhttp MockWebServer tests
   hung the test worker forever (the full `testStableDebugUnitTest` step stalled until its
   timeout; the runner then logs `context deadline exceeded` tearing the container down; **disk speed
   was not the cause: as-is, tmpfs and loop storage all hung identically**). The shim therefore also
   wraps `listen`/`close`/`dup2`/`dup3` (fd table of listeners, because asking the socket would block) and
   `shutdown()` (no-op on listeners, otherwise real call in a helper thread, 300 ms wait; `SHIM_SHUTDOWN=passthrough|noop`
   for experiments; build with `-pthread`). With it the full suite completes (run 203: 1,417 tests, 3 m 27 s,
   7 failed = the known `CornerButtonThemeTest` plus about six flaky MockWebServer tests, `unexpected end of stream`,
   different ones each run, also with `shutdown()` a no-op, so a TSI loopback data issue not fixed by the shim).
   Diagnosis tools: `heartbeat.sh` (jstack of the test worker and Gradle daemon every 75 s), `run-matrix.sh`
   (`MATRIX_MODE=diag`, `DIAG_CMD`), `push-probe.sh`, `probe-shutdown*.yml`, `probe-accept.yml`.
6. The job-log endpoint carries only the first step's `⭐ Run` marker, and there
   is no per-step API: `examples/plektra/forgejo-ci.yml` prints `BENCHSTEP`
   markers and `scripts/ci-step-times` reads them (or Gradle's `BUILD ... in`).

7. **Resources per job (probed 2026-10-13, `examples/plektra/resource-probe.sh`,
   `limits-probe.sh`, `disk-probe.py`; run on the Mac too to compare):** 16 vCPU
   (EPYC at 3.0 GHz, 1 thread/core, KVM) and 62.8 GiB RAM, no swap, no cgroup
   limits (the VM is the cap), CPU steal 0.01 %. Versus an M1 Air: 2.0x cores,
   3.9x RAM, 2.6x all-thread compute, 0.85x one-thread compute. **Disk is the weak
   spot:** `/`, `/tmp` and the workspace are all virtiofs (no guest block device, so
   SSD vs HDD is not detectable; nosync write = fsync write = 177 MiB/s, i.e. write-through
   FUSE). Small files: about 1.6-2.3k creates/s, 13-15k stats/s, 4-5k opens/s, which is
   0.14x, 0.034x, 0.075x of the Mac. **`/dev/shm` is a 32 GiB tmpfs: 29-33x faster than
   virtiofs on small-file operations** (51k creates/s, 380k stats/s, 117k open+read/s),
   so put `GRADLE_USER_HOME`, the Android SDK and the checkout there for speed.
   Other limits: soft `nofile` 1024 (hard 4096), `kernel.pid_max` 16384,
   `inotify.max_user_instances` 128, virtio balloon present, PSI off.

`examples/plektra/` holds the workflow derived from the repo's GitHub `ci.yml`
(`derive-forgejo-ci.py` keeps every Gradle step identical) and the probe
history. Compare runs with
`scripts/ci-step-times forgejo OWNER/REPO RUN` and `... github OWNER/REPO RUN`.

## Agent loop (local agent <-> Forgejo CI, no agent on the server)

1. Branch and commit locally, `git-forgejo push forgejo BRANCH`.
2. `forgejo-api POST /repos/O/R/pulls --yes --data '{"head":"BRANCH","base":"plk/main","title":"..."}'`.
3. Poll `GET /repos/O/R/actions/runs` for the run, then `.../runs/ID/jobs` and
   `.../actions/jobs/JOB/logs` for failures; comment with
   `POST /repos/O/R/issues/N/comments --yes`.
4. Fix, push again, repeat. Cancel runs you no longer need
   (`POST .../actions/runs/ID/cancel --yes`): the runner is shared.

## Rules

1. Never print the token; `get`/`export` stream values (see `sudo-secretspec`).
2. Prefer least scope: `read:*` for browsing, add `write:*` only for the task.
3. Mutations (create issue/PR, merge, delete) are outward-facing on a shared MIT
   service: confirm with djbclark first unless the task already asked for them.
4. Rotate by re-running `setup-token`; `set` overwrites.

## Existing skills checked (2026-10-13)

None adopted; ours is a thin layer so no third-party code receives the token.
`magnus919/agent-skills` `forgejo-cli` (MIT, Python, guarded mutations,
`FORGEJO_AGENT_TOKEN` env) is the best of them and a good reference for endpoint
coverage; an mcp.directory `forgejo` skill is a `tea` cheat sheet; printing-press
`pp-forgejo` wraps a Node CLI with a local SQLite mirror.
