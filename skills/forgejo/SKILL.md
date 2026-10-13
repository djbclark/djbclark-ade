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
5. **Gradle does not run there yet.** Inside the job every TCP connect to
   127.0.0.1 or ::1 is refused (also 0.0.0.0-bound to the container IP; only an
   address bound on `dummy0`, 203.0.113.1, connects). Gradle's daemon, test
   workers and Kotlin daemon all use loopback, so the build fails with "Could not
   connect to the Gradle daemon" (run 170). `ip link set lo up` changes nothing;
   `unshare -n` hung the job (cancel it). Cause is probably libkrun TSI
   (libkrun#818, open); host fix `krun.use_passt=1`. Needs SIPB: see `examples/plektra/sipb-loopback-report.md`.
6. The job-log endpoint carries only the first step's `⭐ Run` marker, and there
   is no per-step API: `examples/plektra/forgejo-ci.yml` prints `BENCHSTEP`
   markers and `scripts/ci-step-times` reads them (or Gradle's `BUILD ... in`).

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
