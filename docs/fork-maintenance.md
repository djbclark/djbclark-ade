# Fork maintenance

## Foundation (2026-11-18)

`config/forks.toml` records fork enrollment separately from install recipes.
Its catalog IDs refer to the existing catalog; required-feature IDs are desired
guarantees, **not** passing tests or claims that fixes are deployed. CFEngine and
libntech share tendcf's existing overlay manifest; ADE does not copy that queue.

```
bin/ade-fork status --json
bin/ade-fork check --id paseo --json
```

Both commands are read-only and run no subprocesses, probes, adapters or tests.
`status` exits 0 on a valid policy; `check` exits 1 because qualification and
promotion are not implemented in this foundation. Invalid/unreadable policy or
unknown IDs exit 2. JSON schema version 1 keeps `policy_valid`, `eligible` and
`authorized` separate; all runtime/candidate revision fields are null (unknown).
`--policy PATH` inspects another policy but cannot override installer protection.

The installer reads the registry beside its own resolved module, independently
of catalog `--root`, source overrides or caller environment. Enrolled catalog
IDs are blocked in install planning, forced repair/reinstall, system install
execution and update planning/execution/retry. Missing, empty, malformed or
unsupported policy blocks **all** generic installer execution. An explicit
`ade-install update --id paseo` reports a blocked row, not an unknown ID.
The guards re-read the policy at the execution boundary, including retries;
they do not trust a previously prepared command. No allow/force bypass exists.

This protection covers ADE's component installer, not commands run outside ADE.
It does not change Cafe, Brew, the desktop updater, installed plugin paths or
runtime settings. It does not assert a hostile-code security boundary against
an actor able to rewrite ADE itself, re-enroll under a different ID, or invoke
a package manager directly. Existing nonmanaged components retain their recipes.

ADE-owned plugins will track qualified immutable snapshots of master, as chosen
by the operator, rather than loading the mutable reference checkout. Their
runtime paths are unchanged by this foundation.

## Delivery sequence and acceptance

1. **Foundation:** enrollment inspection plus ADE installer containment; prove
   managed install/update/force/system/retry commands cannot run, damaged policy
   holds writes, catalog overrides cannot disable protection, and unmanaged
   recipes still execute. CI and adversary review precede a PR.
2. **Qualification:** trusted feature contracts, immutable source/dependency/
   patch/recipe/artifact receipts, check freshness and exact-head evidence.
   Candidate code cannot redefine its own passing criteria. Missing, pending,
   skipped or mismatched checks hold qualification.
3. **Transactions:** separate merge/publication/channel/install/activation
   permissions, compatibility-group lock and monotonic deployment generations,
   durable journal, stage/activate/verify/recover adapters. Retry the exact
   artifact; reject stale jobs and changed authorization.
4. **Plugin pilot:** qualify one controlled low-risk plugin with no irreversible
   state migration, contain Cafe's scheduled/startup/queued updates, install an
   exact qualified snapshot, prove failed-candidate retention and recovery.
5. **Paseo:** reuse fork desktop CI and the existing external
   `paseo-local-upgrade`. Verify desktop/CLI/daemon/plugin identities together,
   constrain future and staged upstream installers, preserve quiescence and the
   separately required initial cutover/daemon-interruption authorization.
6. **CFEngine/libntech:** coordinate with its lead, consume the existing tendcf
   overlay, inventory shipped changes outside it, test the coupled dependency
   closure, preserve strict JSON/embedded NUL/backslash/Mustache/CMDB guarantees
   and deployment consent. No upstream submissions without the specific review.

Latest means newest **eligible** candidate on the enrolled channel, not newest
published artifact. Revisions in receipts advance with successful updates and
are not permanent freezes. Enrollment is not activation permission. Artifact
rollback requires state compatibility; an unsafe migration holds automatic
activation. A rollback must not silently discard session data.

Patch retirement starts with a candidate signal (merged PR, patch ID, subject)
and finishes only with reviewed removal plus a passing upstream artifact **without**
that downstream patch. Regression contracts remain after retirement.

Primary research: [PR sync action](https://github.com/kuma0128/sync-upstream-action),
[GitHub workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[StGit](https://github.com/stacked-git/stgit),
[git-imerge](https://github.com/mhagger/git-imerge),
[Copybara](https://github.com/google/copybara),
[Renovate Git refs](https://docs.renovatebot.com/modules/datasource/git-refs/).
Native Git integration PRs and existing build/install mechanisms are the default;
additional patch managers or repository-transform tools are not prerequisites.
