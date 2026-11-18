# Fork watch inventory

`bin/ade-fork-inventory` projects the curated `config/forks.toml` plus GitHub forks
owned by `djbclark`, `djbcsipb`, and `frdminc` into one private effective registry:
`~/.local/state/djbclark-ade/forks/registry.json`. It queries metadata only; it
never updates code, pins, consumers or runtime configuration. Private fork names
stay in this mode-0600 local projection, inside a mode-0700 directory. Console
output contains counts and coverage booleans only. No private projection belongs
in the public ADE repository.

Schema version 1 has `generated_at` (UTC), `owners` keyed by all three owners,
and `components`. Each coverage object has literal `complete`, `scope`, and
`error`. Each component has `id`, GitHub `upstream_repo` and `fork_repo` slugs,
their canonical HTTPS `upstream` and `fork` URLs, nullable `base_tag`, literal
`watch_releases` and `private`, and `catalog_ids`. A null base tag means unknown;
it is not the latest tag. There are no executable installed-version commands.
The watcher derives `fork:<repo-name>` from `fork_repo`, not from `id`.

GitHub discovery uses the [RepositoryOwner connection](https://docs.github.com/en/graphql/reference/repos#repositoryowner)
with `isFork: true`, explicit owner affiliation, cursor pagination and rate
budget checks. Archived forks remain inventoried with release watching disabled.
Curated rows cover mirrors and ADE's own master snapshots, and define the owner's
intended synchronization source. That can differ from GitHub's original fork
parent: PR Radar follows `omercnet/paseo-plugins`, while its GitHub network parent
is `gpambrozio/paseo-plugins` (verified 2026-11-18). Optional `github_parent_repo`
preserves the observed lineage, and `upstream_source` says `curated` or
`github-parent`. Curated overrides retain discovered privacy/archival metadata.
Discovery is metadata inventory,
never a feature contract or permission to promote a newly discovered component.

`complete` means the full connection visible to the current authenticated
credential, not proof that GitHub disclosed every private repository. The scope
is explicitly `credential-visible`; the operator must ensure the credential has
access to all intended private repositories. Restricted credentials can silently
hide repositories. This limitation must remain visible in coverage reporting.

An unavailable owner, missing parent, bad cursor, duplicate, malformed response,
or exhausted budget marks that owner's coverage incomplete and retains its last
known rows. It never drops known forks because a partial query succeeded. Fresh
complete discovery replaces that owner's prior discovered rows; curated rows
remain. Malformed prior snapshots hold the
entire write. The process serializes refreshes, atomically replaces the snapshot,
and fsyncs it and its directory. Exit 0 means all credential-visible connections
complete, 1 means an incomplete snapshot was saved, and 2 means refresh held.

The sibling-owned upstream-release watcher reads this file with `--registry`.
It must warn on incomplete coverage, preserve its prior state, and open no alerts
for uncovered owners. Its first baseline requires a complete snapshot. Release
alerts live in the private central `djbclark/upstream-releases` repository, one
issue per upstream/tag including betas; registry refresh itself sends no alerts.
Scheduling and live watcher installation are separate from this source command.
