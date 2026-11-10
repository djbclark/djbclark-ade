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

1. **Rule 10** — `CHANGELOG.md` has `## Unreleased`; trusted `changelog-fold --check`
   (beside this script, never from `--repo`) passes; after an in-memory fold (same
   whole-file dedup as `changelog-fold`) Unreleased has at least one `- ` entry.
   Fragment files alone are not enough: an interrupted fold can leave fragments whose
   entries already sit under a dated section.
2. **CI** — `.github/workflows/test.yml` and `adversary-marker.yml` are present;
   trusted `ade-roster --check` passes (same local gate CI's `context-policy` runs);
   inspected `bin/ade-roster` is present as content settle (not executed).
3. **`ade-update`** — inspected `bin/ade-update` exists and advertises `--check`;
   sibling `bin/changelog-fold` is present (content settle; not executed).
4. **Tag slot** — no local semver tag `vX.Y.Z` / `X.Y.Z` and no `## X.Y.Z` CHANGELOG
   section yet (`slim-*` / `pre-slim-*` tags are ignored).

Helpers always resolve from the trusted script's `bin/` (`Path(__file__).resolve().parent`)
and take `--repo` / `--root` pointing at the inspected tree — an untrusted checkout must
not supply the code that runs.

On success it prints the dry-run plan (fold N fragments; move Unreleased under
`## X.Y.Z - DATE`; create tag `vX.Y.Z` at HEAD) and exits 0. It never performs those
steps (`plan.performed` is always `[]`; `would_push_tag` is always false).

## Still operator / other PRs

- **Actually tagging** — operator only, after this gate is green on the intended head
  and the lead folds Unreleased into a dated section through a normal PR.
- **Daily `ade-update --check` timer** — Mac launchd / Linux systemd install paths
  (open install PRs); **not** installed by this gate, and not installed from a cloud
  agent on the Mac.
