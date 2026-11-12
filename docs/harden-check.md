# Hardening drift check (setup-plan S6)

Transitional unit for Carried #35 / setup-plan **S6**: check in a
`[hardening]` policy and `bin/ade-harden observe` (`just harden-check`) that
reads every configured setting back from the GitHub API and exits nonzero on
drift. **Observe-only**: no live ruleset writes and no `just harden` apply.

Snapshot: 2026-11-12. Since the 2026-11-10 observe-only unit, S6 adds Forgejo
read-back, an operator drift notification, the interaction-limit renewal
(setup-plan contract §7: the one mutation a check may authorize), and the S5a
gate canary. S5a itself shipped in #576; OQ2 un-deferred it on 2026-11-12.

## Entry points

| Piece | Role |
|---|---|
| `config/hardening.toml` | Owners, defaults, forks profile, interaction-limit wants, explicit `[[hardening.repo]]` rows |
| `config/hardening.schema.json` | Structural schema (documented; validated in-process by `ade-harden check`) |
| `bin/ade_harden.py` / `bin/ade-harden` | Loader + observe-only gh read-back |
| `bin/ade_harden_coverage.py` | Forgejo read-back, renewal, notification, gate canary |
| `just harden-check*` | Thin recipes over the bin tool |

While `config/ade.toml` is absent, the transitional file is the source. If
`ade.toml` appears without a folded `[hardening]` table, `ade-harden` refuses
the transitional file so there is no dual source (same pattern as
`ade-github-setup` / `ade-install`).

## Commands

```
ade-harden check [--root DIR] [--json]
ade-harden observe [--root DIR] [--json] [--local]
ade-harden apply …   # refused (exit 2)
```

- **check** — validate `config/hardening.toml` (including the GitHub
  `interaction_limits.expiry` enum: `one_day` … `six_months`).
- **observe** — local always; with network, `gh api` probes each
  `[[hardening.repo]]` (PR/issue units, wiki/projects/discussions, Actions
  fork-PR approval + workflow permissions, optional merge-gate ruleset name),
  `GET /user/interaction-limits`, and an owner inventory for uncovered
  non-fork repos. `--local` skips `gh`. Exit **1** on `drift` / `missing` /
  `uncovered`; exit **0** when only `ok` / `unknown` / `deferred` remain.
  Print-only remediation lines are built with `shlex.join` so a hostile
  `--root` tree cannot inject shell metacharacters into a copied hint.
- **apply** — always refused (including `--yes` / `--reapply`). Repo settings
  and rulesets are never written by a check.
- **renew** — the interaction-limit renewal. Dry-run unless `--apply`. See
  below.

Just recipes: `just harden-check-config`, `harden-check`, `harden-check-local`.

## What is compared

Wanted values come from `[hardening.defaults]` (profile `active`) or
`[hardening.forks]` (profile `fork`), with per-repo overrides. Each finding
names `target`, `setting`, `wanted`, `found`, and a print-only remediation
hint (`just harden <option> --repos …`) — the hint does **not** run apply.

| Surface | API (header `X-GitHub-Api-Version` from config, default `2026-03-10`) |
|---|---|
| PR access | `GET /repos/{owner}/{repo}` → `has_pull_requests`, `pull_request_creation_policy` |
| Fork units off | same; `disabled` wants `has_pull_requests`/`has_issues` false |
| Wiki / projects / discussions | `has_wiki`, `has_projects`, `has_discussions` |
| Actions fork-PR approval | `…/actions/permissions/fork-pr-contributor-approval` |
| Default token / PR approve block | `…/actions/permissions/workflow` |
| Merge-gate ruleset (when enabled) | `GET …/rulesets` by name; enforcement / bypass when present |
| Interaction limits | `GET /user/interaction-limits` (limit + expiry floor); **never PUT** |
| Inventory | authenticated `GET /user/repos?affiliation=owner` (login owner) or `GET /orgs/{owner}/repos?type=all` (includes private); uncovered non-forks lack `[[hardening.repo]]`; forks noted as covered by `[hardening.forks]` |

Deferred: issue `collaborators_only` REST read-back (no field yet — S7) and a
deep probe of every unlisted fork.

## Coverage added 2026-11-12

**Forgejo.** `[hardening.forgejo]` with `base_url` (https only) makes
`observe` read each `[[hardening.repo]]` back through an `fj api` argv list
and compare `has_pull_requests`, `has_issues`, `has_wiki` and `has_projects`.
The token is never on an argv: the caller injects it with
`sudo-secretspec run` (key name `forgejo_token`). Unset `base_url` leaves the
`forgejo` finding `deferred`, as before.

**Notification.** `ade_harden_coverage.render_notification` renders the
actionable findings (drift, missing, uncovered) as a notice for the operator.
It prints; it never posts. CI runs `ade-harden observe --local` on every
change (`.github/workflows/test.yml`, the `context-policy` job) and fails the
job when that local report has actionable findings.

**Interaction-limit renewal.** `ade-harden renew` (dry-run by default;
`--apply` to write) is the separately authorized operation from setup-plan
contract §7. It renews only when the current limit is exactly the configured
`limit` and the expiry is inside `min_remaining_days`, sends only
`{"limit", "expiry"}` — the body on stdin, never on the command line — and
reads the limit back afterwards. It never changes the limit's value and never
touches another setting. `observe` itself never writes; when a renewal is due
it reports `interaction_limits.renewal` as `drift` so the notice names it.

**Gate canary.** `[hardening.canaries]` with `corpus` (a path outside the
repo; payload text is never committed) runs one benign and one injection
canary through `bin/ade-injection-gate classify`. The corpus rows record
`id`, `source`, `label`, `surface` and `expected`; the check fails when a
canary's decision differs from `expected`, the gate is unavailable, or the
latency exceeds the gate's `max_ms`. With no corpus configured the finding
stays `deferred`, which does not fail the check. The canary never authorizes
adoption: the gate's own measurement report keeps `adoption_authorized:
false`.

## Related

- Plan: [setup-plan.md](setup-plan.md) S5 / S6 (contract §7).
- Argon Section E check table: [security/argon-injection-review-2026-11-07.md](security/argon-injection-review-2026-11-07.md).
- Merge-gate setup (S8): [github-setup.md](github-setup.md).

## Scheduled check (2026-11-10)

Install the daily read-only job with `just harden-check-install` (or `bin/ade-sched install config/launchd/com.djbclark.harden-check.plist --set __STATE__=$HOME/.local/state/ade`). It runs `ade-harden observe` only — never apply/reapply.
