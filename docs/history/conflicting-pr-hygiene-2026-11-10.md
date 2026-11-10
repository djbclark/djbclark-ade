# Open PRs conflicted with `master` (2026-11-10)

Snapshot from `gh pr list --state open --limit 200` filtered to
`mergeable=="CONFLICTING"` and `baseRefName=="master"`. Re-probe before acting;
mergeability changes when `master` moves.

Probe:

```bash
gh pr list --repo djbclark/djbclark-ade --state open --limit 200 \
  --json number,title,mergeable,baseRefName \
  --jq '.[]|select(.mergeable=="CONFLICTING" and .baseRefName=="master")|{n:.number,t:.title}'
```

## Inventory and guidance

| PR | Branch | Draft | Title (short) | Suggested action |
|----|--------|-------|---------------|------------------|
| [290](https://github.com/djbclark/djbclark-ade/pull/290) | `claude/issue-278-checkpointing` | yes | `ade-recovery` plugin + `paseo-checkpoint` (issue 278) | **Park / supersede split:** full plugin stays parked per Carried #2 and PLAN J6/J9 until the native-resume trial (operator batch A6) lands. D1 measurement is **not** blocked on rebasing this branch — use [471](https://github.com/djbclark/djbclark-ade/pull/471) (`bin/ade-recovery-d1`, observe-only preflight, mergeable on `master`). After the trial: **close** #290 if Paseo native resume + tier-1 records suffice; **rebase** onto current `master`, refresh checks and the adversary marker, only if a gap remains. Do not merge both #290 and #471 for the same D1 scope. |
| [270](https://github.com/djbclark/djbclark-ade/pull/270) | `quota-surplus` | yes | quota-surplus watchdog | **Close** per slim-down ledger (operator ruling: PR 270 closed); quota guard retired with the slim-down. |
| [269](https://github.com/djbclark/djbclark-ade/pull/269) | `coding-bot-peer-link` | no | coding-bot over peer-link | **Rebase or close:** if `bin/coding-bot` is still wanted, rebase and re-run Tests; if peer-link path was abandoned, close with a note in `docs/queue.md`. |
| [256](https://github.com/djbclark/djbclark-ade/pull/256) | `open-clean-env` | no | `bin/open-clean` | **Rebase** if the gate is still desired; otherwise close. Conflicts are likely from slim-down edits around launch tooling. |
| [231](https://github.com/djbclark/djbclark-ade/pull/231) | `mds-client-probe` | no | load-watch mds probe | **Superseded:** Wave 6 port is [517](https://github.com/djbclark/djbclark-ade/pull/517) (`cursor/mds-probe-wave6-f576`). Close #231 once #517 merges; do not rebase this tip. |
| [227](https://github.com/djbclark/djbclark-ade/pull/227) | `bottom-config-uncapped-command` | no | bottom fork Command column doc | **Superseded:** skill moved to site-djbclark (slim E1 / #297); tip would re-add it here. Demanual + proposed site-djbclark patch: [bottom-config-uncapped-command-2026-11-10.md](bottom-config-uncapped-command-2026-11-10.md) (`cursor/bottom-config-uncapped-f576`). Close #227 once that hygiene PR merges; do not rebase this tip. |
| [208](https://github.com/djbclark/djbclark-ade/pull/208) | `astra-readonly` | no | acp-run read-only advise slices | **Do not call superseded yet:** `tools/acp-run` still implements `--perm read-only` and `bin/acp-dispatch` still supports read-only advise; Carried #33 leaves shim/`acp-run` **removal** to a follow-up PR after one live cycle (Wave 6). Assess whether #208's tip adds anything beyond that existing implementation: **close** only if the tip is redundant with current `acp-run`/`acp-dispatch` (or with `bin/review-launch` for review-shaped advise); **rebase** only if a real gap remains. After the delete follow-up lands, surviving advise belongs on Paseo / `review-launch`, not a rebase of this PR. |
| [194](https://github.com/djbclark/djbclark-ade/pull/194) | `finder-consent-agents-cleanup` | no | AGENTS.md lean rewrite | **Rebase** if the prose trim is still desired — `AGENTS.md` changed heavily in E11 (2026-11-07); expect a full re-read, not a mechanical merge. |

## Related (not conflicting on this snapshot)

- [471](https://github.com/djbclark/djbclark-ade/pull/471) — `cursor/ade-recovery-d1-f576`, base `master`, **MERGEABLE** at probe time: ships observe-only D1 preflight while #290 stays parked; prefer merging or closing #471 on its own merits before touching #290's branch.

## Hygiene workflow

1. Decide **close**, **rebase**, or **supersede** per row (default for retired shims: close).
2. For a rebase: fresh worktree from `origin/master`, `git fetch origin <branch>`, rebase, push with lease, re-run `adversary-marker` and Tests.
3. Update Carried #2 in `docs/queue.md` when #290 or #471 closes.
4. Re-run the probe command above after bulk merges to refresh this list.
