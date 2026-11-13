# CI runners: WarpBuild for long jobs

Snapshot **2026-11-13** (operator ruling, card answers): every GitHub Actions job estimated to take **more than 10 minutes** runs on
[WarpBuild](https://www.warpbuild.com/docs/ci/quick-start) runners; jobs of 10 minutes or less stay on GitHub-hosted runners.
Applies to the operator's active repositories (not archived ones, third-party forks, or repos with no recent CI).

## A. Labels (WarpBuild's own mapping, `mcp__warpbuild__suggest_runner_labels`)

| GitHub-hosted | WarpBuild |
|---|---|
| `ubuntu-latest`, `ubuntu-24.04` | `warp-ubuntu-2404-x64-4x` |
| `macos-latest`, `macos-26` | `warp-macos-26-arm64-6x` |

Same-size mapping for other labels; go bigger (`8x`, `12x`) only where a measured gain justifies it. Change only `runs-on`.
Leave self-hosted labels and `runs-on` expressions alone and list them in the PR.

## B. How to switch a repository

1. The WarpBuild GitHub app must be installed on the **organization** and have access to the repository.
2. Public repo: the org's Default runner group must allow public repositories
   (`gh api -X PATCH orgs/<org>/actions/runner-groups/1 -F allows_public_repositories=true`, needs the `admin:org` scope).
3. Edit `runs-on` of each job over 10 minutes (use `gh run view --json jobs` durations), open a PR titled
   "Switch CI to WarpBuild runners", confirm a job starts on a `warp-*` runner and compare durations, then merge.
4. MCP server (user scope): `claude mcp add --transport http --scope user warpbuild https://mcp.warpbuild.com/mcp && claude mcp login warpbuild`
   (the old `docs/apply-toolchain-prompt.md` is archived under `docs/history/`, so the entry lives here).

## C. Personal accounts are not supported

WarpBuild registers its runners through its GitHub app at **organization** level. The MCP's `get_onboarding_status` reports
`personal_account_not_supported: true` for `djbclark` (a `User`), even with the app installed on it, and personal accounts have no org runner
groups to allow public repositories on. On 2026-11-13, PR #655 (`djbclark/djbclark-ade`, public, personal account) moved `pytest-linux` and the
macOS leg to WarpBuild labels: the jobs stayed `queued` with no runner assigned, and `GET /runner_instance` listed zero instances.
WarpBuild's [FAQ](https://www.warpbuild.com/faq) says the same ("requires a GitHub organization and cannot be installed on a personal account"), and
its [migration guide](https://www.warpbuild.com/migrate/github-hosted-to-warpbuild) says it registers runners in the org's Default runner group (id 1).
So a repository owned by a personal account stays on GitHub-hosted runners; moving it needs a transfer to an organization (operator's call).

## D. API access

`https://api.warpbuild.com/api/v1`, `Authorization: Bearer wkey-…` (a key with the `ci` scope from <https://app.warpbuild.com/settings/api-keys>).
The `WARPBUILD_API_KEY` in `sudo-secretspec` is a 36-character UUID with no `wkey-` prefix; it gets 403 from `/runner_instance` and
`/reports/billing/ci`, so it is not a usable API key until replaced. The MCP's OAuth session (`mcp__warpbuild__call_api`) works without it.

## E. Cost and exposure

WarpBuild bills per minute; the 4x Linux and 6x macOS sizes cost more per minute than GitHub-hosted and are only worth it where the job is
long. Public repos on self-hosted runners: set Settings -> Actions -> General -> "Fork pull request workflows" to require approval for
all outside collaborators, and keep secrets out of jobs that run fork code.
