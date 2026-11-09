# GitHub setup (setup-plan S8)

Transitional unit for Carried #35 / setup-plan **S8**: check in the
`ade-merge-gate` App manifest, a `[github]` config, and
`bin/ade-github-setup` with **observe / plan / dry-run** first. Live
`apply --yes` (App create, environment POST, ruleset POST, secret store) and
`just harden-check` stay for a follow-up. S5a injection classifier stays
deferred (operator 2026-11-08).

Snapshot: 2026-11-09.

## Entry points

| Piece | Role |
|---|---|
| `config/github.toml` | Owner, repo, App names, environment, secret/variable *names*, required checks |
| `config/github.schema.json` | Structural schema (checked by `ade-github-setup check`) |
| `.github/app-manifest.json` | GitHub App Manifest (webhook inactive; statuses+checks write; PRs read) |
| `bin/ade_github_setup.py` / `bin/ade-github-setup` | Loader, observe, plan, dry-run |
| `just github-setup*` | Thin recipes over the bin tool |

While `config/ade.toml` is absent, the transitional file is the source. If
`ade.toml` appears without a folded `[github]` table, `ade-github-setup`
refuses the transitional file so there is no dual source (same pattern as
`ade-install`).

## Commands

```
ade-github-setup check [--root DIR] [--json]
ade-github-setup observe [--root DIR] [--json] [--local]
ade-github-setup plan [--root DIR] [--json]
ade-github-setup apply [--root DIR] [--json] [--dry-run|--yes]
```

- **check** — validate TOML + manifest permissions / inactive webhook.
- **observe** — local always; with network, `gh` probes installation via
  `GET /user/installations` (+ that installation's repositories; operator
  credentials — not the App-JWT `repos/.../installation` endpoint),
  `merge-gate` environment + branch policy, secret/variable *name* presence,
  and ruleset name. Never reads secret values. `--local` skips `gh`.
- **plan** — print-only S8 steps (browser App create, environment, stdin
  secret store, ruleset, deferred harden/verify).
- **apply** — defaults to `--dry-run` (payloads printed). `--yes` is refused
  in this unit.

Just recipes: `just github-setup-check`, `github-setup-observe`,
`github-setup-plan`, `github-setup` / `github-setup-dry` (dry-run apply).

## Secrets never on argv

Review rule 3: a private key never appears in argv, a log, or a tracked file.
`ade-github-setup` refuses argv that looks like PEM material or secret flags
(`--private-key`, `--pem`, `--client-secret`, `--token=…`, …). Refuse
messages name only the normalized flag (never an equals-form value). Store
the key with a stdin redirect:

```sh
gh secret set MERGE_GATE_PRIVATE_KEY --env merge-gate --repo OWNER/REPO \
  < ade-merge-gate.private-key.pem
```

Config holds the secret *name* only (`private_key_secret`).

## Manifest

`.github/app-manifest.json` matches `docs/review-boundary.md` operator setup:

- name `ade-merge-gate`, `public: false`
- `hook_attributes.active: false` (webhook inactive; placeholder URL for the API)
- `default_permissions`: statuses write, checks write, pull_requests read, metadata read
- `default_events: []`

Create flow (manual confirm): open
https://github.com/settings/apps/new and submit the checked-in manifest JSON
(or use a follow-up that posts it). Then install on the configured repository
only, note App ID + Client ID, and continue with environment / secrets /
ruleset as in `docs/slim/reports/wave4-E8.md` section E.

## Related

- Plan: [setup-plan.md](setup-plan.md) S8 (and S7 for browser-only steps).
- Merge gate: [review-boundary.md](review-boundary.md).
- Operator batch A8–A11 / B7: [slim/operator-batch.md](slim/operator-batch.md).
