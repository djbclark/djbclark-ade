# Repo-local device QA harness convention (`qa/`)

Status: adopted 2026-11-25 (coordinated with Plektra; reference implementation in
[djbclark/plektra-djbclark `qa/`](https://github.com/djbclark/plektra-djbclark/blob/a6b43d5eb7a3062e6afd40b5fec1ba3d5c5d8740/qa/README.md)).

## Summary

Repositories that carry a host-driven device or human-in-the-loop (HITL) QA harness
(such as Android phone testing over ADB / FIRERPA) place it under a visible repo-root
**`qa/`** directory with a small, uniform discovery pair so any human or AI agent can
find, set up, and run it without repository-specific hunting.

## Canonical layout and minimal contract

| Path | Required | Purpose |
|---|---|---|
| `qa/README.md` | Yes | Scope of what the harness tests, supported device targets/transports, quick-start runner commands, and the explicit boundary between local harness glue and upstream app hooks. |
| `qa/SETUP.md` | Yes | Copyable, self-contained AI/operator setup guide: host/device prerequisites, target resolution (always pass explicit device serials such as `adb -s <target>`), secret/certificate handling (variable names via `sudo-secretspec`, never committed secrets or `.env` files), and a concrete smoke check with its pass criterion. |
| `qa/Justfile` | Recommended | Standard runner entrypoint with predictable recipes (`qa-connect`, `qa-demo`, `qa-run <suite>`, plus optional `qa-prep` / `doctor`). Heavy local builds or test runs follow `~/CLAUDE.md` item 34 (`~/ops/site-private-djbclark/bin/bgrun`). |
| `qa/AGENTS.md` | Optional (recommended on forks) | Short scoped discovery pointer (`SETUP.md` for first run/setup; `README.md` for running suites or editing the harness). On forks, keeps upstream's root agent-file layout untouched (`~/CLAUDE.md` item 20); add a `qa/CLAUDE.md -> AGENTS.md` symlink inside the fork-only `qa/` tree where helpful. |

## Discovery rule

1. **ADE-owned repositories:** add a one-line pointer in repo-root `AGENTS.md` naming
   `qa/README.md` and `qa/SETUP.md` so fresh-session context budgets stay small
   ([context-hygiene.md](context-hygiene.md)).
2. **Forks (upstream-tracked root layout):** keep upstream's root agent files intact
   (`~/CLAUDE.md` item 20) and place the short scoped `qa/AGENTS.md` (with optional
   `qa/CLAUDE.md -> AGENTS.md`) inside `qa/`.
3. **Machine discovery:** checking for repo-root `qa/README.md` + `qa/SETUP.md`
   (and `qa/AGENTS.md` when present) is the canonical signal; no separate manifest file
   is required.

## Multiple implementations and upstream boundary

1. **Multiple QA implementations in one repo are allowed** when they serve distinct
   roles (for example, upstream automated input-replay flows alongside a fork-local
   guided HITL harness in `qa/`); `qa/README.md` and `qa/SETUP.md` state clearly when
   to use each.
2. **Upstream PR boundary:** keep host harness code, FIRERPA/transport glue, and
   lab-specific device facts out of upstream PRs. Propose only lightweight, app-native
   testability hooks (such as stable UI/accessibility tags) aligned with upstream
   architecture. Track any temporary fork-only patches in [fork-picks.md](fork-picks.md).

## Reference implementation (2026-11-25)

- [Plektra `qa/README.md`](https://github.com/djbclark/plektra-djbclark/blob/a6b43d5eb7a3062e6afd40b5fec1ba3d5c5d8740/qa/README.md)
- [Plektra `qa/SETUP.md`](https://github.com/djbclark/plektra-djbclark/blob/a6b43d5eb7a3062e6afd40b5fec1ba3d5c5d8740/qa/SETUP.md)
- Discovery pair (`qa/README.md` + `qa/SETUP.md`), scoped `qa/AGENTS.md` / `qa/CLAUDE.md`,
  and `qa/Justfile` recipes `qa-connect`, `qa-demo`, `qa-run`.
