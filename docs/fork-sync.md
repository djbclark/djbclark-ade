# Native Git fork sync

`bin/ade-fork-sync plan --id COMPONENT` reads the fixed foundation enrollment,
queries GitHub release/default-branch metadata and resolves exact remote objects.
It does not fetch, change a checkout, push, or open a PR. `apply` always returns
JSON `status=held`, exit 1: foundation policy has no operation grants. There is
no policy-path, root, receipt, candidate-file or allow override. Invalid and
unavailable inputs hold. A plan is observation, never authority.

## Integration API

`SyncSpec(component, fork, upstream, base_ref, channel, strategy)` is trusted
configuration supplied by a future enrollment adapter, not parsed from candidate
code. URLs are credential-free GitHub HTTPS repository identities. `Sync(runner,
authority).discover(spec)` returns immutable `Plan` with fork base, upstream ref,
raw tag object, peeled commit, and deterministic integration branch.
`apply(plan, workspace, publication_remote, unattended=False)` stages and publishes
only after `authority.permits(spec, operation) is True` for stage, publish and
pull-request. The authority provider must re-read trusted policy, bind caller,
component and exact operation, and serialize component operations. It must not
accept candidate evidence as permission. Default provider denies all operations.
For unattended use it additionally requires `app-token-ci` authority attesting a
separately provisioned GitHub App token with access to the fork and CI trigger
chain. This module neither obtains credentials nor treats GITHUB_TOKEN as that
attestation. The CLI cannot reach this mutation API until policy support lands.

The caller owns a clean exclusive task workspace at the recorded base with
complete ancestry (fresh isolated clone, or owned task worktree). No shared
checkout is accepted by contract. An exclusive adjacent lock protects API retries
in that workspace; policy adapter must supply the cross-workspace component lock.
Commands are argv-only, shell=False, captured and bounded to 120 seconds. Runner
injection returns subprocess.CompletedProcess with integer status and string
stdout/stderr; malformed responses hold. No candidate hooks are run by merge.

Stable channels use GitHub `/releases/latest`, reject draft/prerelease metadata,
and hold without a release; branch channels explicitly use `branch:NAME`.
No semver interpretation, downgrade inference, or release-to-branch fallback.
Tags record both tag object and peeled commit: moved tags invalidate plans.
Branches changing after planning also hold. Patch queues and master snapshots
require an owner-managed adapter; this engine never merges and reapplies patches.

Integration branches are `ade-sync/COMPONENT/DIGEST` and use a two-parent merge
commit, preserving fork patches and upstream ancestry. Contribution branches
remain separate. Upstream is fetch-only. There is no upstream mirror mutation;
any future mirror adapter must prove ancestry and advance FF only, holding on
rewinds or divergence. Default branches are never publication targets. Push is a
normal non-force Git push to the configured fork URL and exact candidate ref.
Conflicts retain MERGE_HEAD, index stages, worktree and adjacent diagnostic text;
no reset, abort, overwrite or publication follows. Fork-base/upstream changes
hold before publication; remote ref mutation cannot be made atomic across Git
servers, so qualification must recheck both identities after staging too.

Retries validate existing remote candidate two-parent identity, reuse its PR,
and never replace history. Conservatively any other open PR to the integration
base holds (including unrelated contributions); inventories at the query limit
hold rather than guess. A retry after a local-only merge reuses the exact two-parent local candidate;
it never rewrites the local branch. PR API
failures after push preserve the branch for a later retry. External messages,
release text and PR bodies are data and never command input. Generated PR text
contains no live adversary marker; normal review and CI remain required.

Output `pr_pending` records exact head/base/upstream/PR with `qualified=false`.
The independent core-release qualification/journal adapter must invalidate prior
qualification whenever head changes, then require exact-head CI and review.
No merge, promotion, installation or activation is performed by this engine.

## Workflow and rollout

`.github/workflows/fork-sync.yml` runs synthetic Linux tests on the dedicated
branch or manual dispatch, plus foundation tests when present. No cron, model,
App integration, cross-repository mutation or token installation is enabled.
After trusted enrollment and App provisioning, a separately reviewed daily/manual
job can discover, stage, publish one PR, and let normal downstream CI run. It
must retain held diagnostics and journal exact identities; missing token or
authority must remain held rather than operational success.

Primary documentation: [Git push](https://git-scm.com/docs/git-push),
[GitHub triggering workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
