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
   `forgejo-api whoami`, `forgejo-api GET /repos/OWNER/REPO/issues`. **Never run it (or `tea-forgejo`) with `--help`**:
   it is a live-service CLI. Usage: `forgejo-api [--host H] METHOD /PATH [--data '{json}'|@file.json] [--yes] [--dry-run]`;
   a comment is `POST /repos/O/R/issues/N/comments --data @body.json --yes`, with `body.json` made by
   `jq -Rs '{body: .}' < text.md > body.json` and checked with `[ -s body.json ]` first (2026-10-14: a `--help` on a POST
   was run by mistake; it posted nothing, this line is the fix).
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

## forgejo.mit.edu CI

Moved to the **`forgejo-ci` skill** (2026-10-14): runner facts, job-image selection (our own `ghcr.io/djbclark/ci-image-plektra`),
the loopback `LD_PRELOAD` shim for libkrun TSI bugs (Gradle daemon, okhttp MockWebServer, WebSocket tests), probe tooling,
ticket etiquette and the SIPB/libkrun ticket map. The evidence behind it, unchanged, is in
`docs/runner-notes.md` in the new public repo **https://forgejo.mit.edu/djbclark/loopback-port-shim** (local `~/src/loopback-port-shim`), which
is also where the shim, probes, probe workflows and `ci/tools/` scripts now live (`skills/forgejo/examples/plektra/` is only a pointer). Compare runs with
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
