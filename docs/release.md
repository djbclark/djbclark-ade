# Release readiness (first tag)

Snapshot **2026-11-10**. Carried #15 in [`docs/queue.md`](queue.md): cut a first release
tag once CI, code-review rule 10 (changelog fragments) and `ade-update` are settled, and
schedule a daily `ade-update --check` through `bin/ade-sched`.

## Dry-run gate (this PR)

[`bin/ade-release-ready`](../bin/ade-release-ready) validates those in-repo preconditions
**without** creating or pushing a tag and **without** writing `CHANGELOG.md` or folding
fragments:

```
~/src/djbclark-ade/bin/ade-release-ready                 # text report; exit 0 ready, 1 not
~/src/djbclark-ade/bin/ade-release-ready --json          # one JSON object
~/src/djbclark-ade/bin/ade-release-ready --version 0.1.0 --date 2026-11-10
```

It checks:

1. **Rule 10** — `CHANGELOG.md` has `## Unreleased`; `changelog-fold --check` passes;
   Unreleased and/or valid `changelog.d/` fragments have something to ship.
2. **CI** — `.github/workflows/test.yml` and `adversary-marker.yml` are present;
   `ade-roster --check` passes (same local gate CI's `context-policy` runs).
3. **`ade-update`** — `bin/ade-update` exists and advertises `--check`; sibling
   `bin/changelog-fold` is present.
4. **Tag slot** — no local semver tag `vX.Y.Z` / `X.Y.Z` and no `## X.Y.Z` CHANGELOG
   section yet (`slim-*` / `pre-slim-*` tags are ignored).

On success it prints the dry-run plan (fold N fragments; move Unreleased under
`## X.Y.Z - DATE`; create tag `vX.Y.Z` at HEAD) and exits 0. It never performs those
steps (`plan.performed` is always `[]`; `would_push_tag` is always false).

## Still operator / other PRs

- **Actually tagging** — operator only, after this gate is green on the intended head
  and the lead folds Unreleased into a dated section through a normal PR.
- **Daily `ade-update --check` timer** — Mac launchd / Linux systemd install paths
  (open install PRs); **not** installed by this gate, and not installed from a cloud
  agent on the Mac.
