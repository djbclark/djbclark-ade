# ade-claim (Paseo plugin)

Thin daemon plugin for [wave4-E8 F4](https://github.com/djbclark/djbclark-ade/blob/master/docs/slim/reports/wave4-E8.md):

| Wave | Hook | Behaviour |
|---|---|---|
| W2 | `worktree.create.after` | Run `python3 …/bin/ade_claims.py new --ttl` so every Paseo-created worktree gets a registry claim. |
| W3 | `agent.open.before` | If a claim exists for the agent's cwd, merge `ADE_CLAIM_ID=<claim id>` into the launch env. |
| W3 | `agent.create.after` | Bind `owner.agent` / `owner.record` to the new agent id via `ade_claims.py bind-owner`. |

Enforcement stays in `ade-git-guard` and the git hooks; this plugin only creates claims and binds identity.

**Not installed on the operator Mac yet** (2026-11-09): scaffold + W3 draft; install with `paseo plugin install /absolute/path/to/plugins/ade-claim` after review.

Manifest: `id` is `ade-claim` (lowercase/hyphen only); `requirements.paseo` is `>=0.14.0` (not a top-level `paseoVersion`).

## Why open.before for ADE_CLAIM_ID

Paseo's `agent.create.after` is a **notification** (does not wait, cannot change the request). Env injection belongs on a waiting request-changing hook:

- `agent.create.before.env` applies only to the initial launch and is **not saved**.
- `agent.open.before.env` is re-derived on every open (create's first launch and resumes).

So W3 exports `ADE_CLAIM_ID` from `agent.open.before`, and uses `agent.create.after` only to stamp the claim's owner once the agent id exists. See [paseo.sh/docs/plugins/hooks](https://paseo.sh/docs/plugins/hooks).

## Hook payloads (Paseo ≥0.14)

- **worktree.create.after**: `{ worktree: { path, branch, sourceCheckout } }`. No workspace or agent id yet; `base_sha` and `remote.origin.url` are read with `git -C <path>`. Claim ids append an 8-hex suffix per creation so a recreate/released claim cannot exit 3 and abort the worktree.
- **agent.open.before**: `{ request: { agentId, cwd, env, … } }` — return `{ …request, env: { …env, ADE_CLAIM_ID } }` or `undefined`.
- **agent.create.after**: `{ agent: { id, cwd, … } }` — side effect only (`bind-owner`); failures are logged, never thrown (creation already finished).

Claim lookup: prefer `<git-dir>/ade-claim` (pointer from W2), else `ade_claims.py list --json --state active` filtered by path.

## Environment

| Variable | Purpose |
|---|---|
| `ADE_CLAIMS_PY` | Absolute path to a **trusted** `ade_claims.py` (required when the plugin is not installed from a checkout that also contains `bin/ade_claims.py`) |

The hooks never run a checkout-local `bin/ade_claims.py`: an untrusted worktree must not supply the helper the daemon execs. Resolution order: `ADE_CLAIMS_PY`, then walk parents of the plugin install directory for `bin/ade_claims.py`.

## Tests

```sh
cd plugins/ade-claim && npm test
# or from repo root:
bin/pytest -q tests/test_ade_claim_plugin.py
```

CI also runs `tests/test_ade_claim_plugin.py` (node `--test` wrapper). No live Paseo daemon or Mac plugin install is required.
