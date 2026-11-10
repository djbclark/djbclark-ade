# Hardening drift check (setup-plan S6)

Transitional unit for Carried #35 / setup-plan **S6**: check in a
`[hardening]` policy and `bin/ade-harden observe` (`just harden-check`) that
reads every configured setting back from the GitHub API and exits nonzero on
drift. **Observe-only**: no live ruleset writes, no interaction-limit
auto-renew, no `just harden` apply. Live apply / authorized renew stay for a
follow-up (setup-plan contract §7). S5a injection-gate canary stays deferred
(operator 2026-11-08).

Snapshot: 2026-11-10.

## Entry points

| Piece | Role |
|---|---|
| `config/hardening.toml` | Owners, defaults, forks profile, interaction-limit wants, explicit `[[hardening.repo]]` rows |
| `config/hardening.schema.json` | Structural schema (documented; validated in-process by `ade-harden check`) |
| `bin/ade_harden.py` / `bin/ade-harden` | Loader + observe-only gh read-back |
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
- **apply** — always refused in this unit (including `--yes` / `--reapply` /
  `--renew`).

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

Deferred in this unit: Forgejo, S5a gate canary, issue `collaborators_only`
REST read-back (no field yet — S7), deep probe of every unlisted fork,
daily `ade-sched` / CI wiring, hermes-ping on drift.

## Related

- Plan: [setup-plan.md](setup-plan.md) S5 / S6 (contract §7).
- Argon Section E check table: [security/argon-injection-review-2026-11-07.md](security/argon-injection-review-2026-11-07.md).
- Merge-gate setup (S8): [github-setup.md](github-setup.md).

## Scheduled check (2026-11-10)

Install the daily read-only job with `just harden-check-install` (or `bin/ade-sched install config/launchd/com.djbclark.harden-check.plist --set __STATE__=$HOME/.local/state/ade`). It runs `ade-harden observe` only — never apply/reapply.
