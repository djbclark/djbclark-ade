# ade-claim (Paseo plugin)

Thin daemon plugin for [wave4-E8 F4](https://github.com/djbclark/djbclark-ade/blob/master/docs/slim/reports/wave4-E8.md): on Paseo's waiting hook `worktree.create.after`, run `python3 …/bin/ade_claims.py new --ttl` so every Paseo-created worktree gets a registry claim. Enforcement stays in `ade-git-guard` and the git hooks; this plugin only creates claims.

**Not installed on the operator Mac yet** (2026-11-09): scaffold only; install with `paseo plugin install /absolute/path/to/plugins/ade-claim` after review.

Manifest: `id` is `ade-claim` (lowercase/hyphen only); `requirements.paseo` is `>=0.14.0` (not a top-level `paseoVersion`).

## Hook payload (Paseo ≥0.14)

From [paseo.sh/docs/plugins/hooks](https://paseo.sh/docs/plugins/hooks#worktreecreateafter): `{ worktree: { path, branch, sourceCheckout } }`. There is no workspace or agent id yet; `base_sha` and `remote.origin.url` are read with `git -C <path>` in the hook handler. Claim ids append an 8-hex suffix per creation so a recreates/released claim cannot exit 3 and abort the worktree. Owner binding (`--owner-agent`, `ADE_CLAIM_ID`) is left for a later `agent.create.after` / W3 slice.

## Environment

| Variable | Purpose |
|---|---|
| `ADE_CLAIMS_PY` | Absolute path to a **trusted** `ade_claims.py` (required when the plugin is not installed from a checkout that also contains `bin/ade_claims.py`) |

The hook never runs `sourceCheckout/bin/ade_claims.py`: an untrusted worktree must not supply the helper the daemon execs. Resolution order: `ADE_CLAIMS_PY`, then walk parents of the plugin install directory for `bin/ade_claims.py`.

## Tests

```sh
cd plugins/ade-claim && npm test
```

CI also runs `tests/test_ade_claim_plugin.py` (node `--test` wrapper).
