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
2. Public repo: the org's Default runner group (id 1, where WarpBuild registers) must allow public repositories
   (`gh api -X PATCH orgs/<org>/actions/runner-groups/1 -F allows_public_repositories=true`, needs `admin:org`: add it with
   `gh auth refresh -s admin:org` and drop it afterwards, or use the web UI). That opens every runner in the group to every repo the group
   reaches, so also set group 1 to `visibility=selected` listing only the switched repos, and install the app on "Only select repositories".
3. Edit `runs-on` of each job over 10 minutes (use `gh run view --json jobs` durations), open a PR titled
   "Switch CI to WarpBuild runners", confirm a job starts on a `warp-*` runner and compare durations, then merge.
4. MCP server (user scope): `claude mcp add --transport http --scope user warpbuild https://mcp.warpbuild.com/mcp && claude mcp login warpbuild`
   (the old `docs/apply-toolchain-prompt.md` is archived under `docs/history/`, so the entry lives here). Prefer `--scope local` in the repo
   being switched, or `claude mcp remove warpbuild` after setup: at user scope its vendor-written instructions load into every session, and
   `send_setup_report` sends repo details to WarpBuild.

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
Pass a key from a file or the environment, never on argv. The `WARPBUILD_API_KEY` in `sudo-secretspec` is a 36-character UUID with no `wkey-`
prefix; it gets 403 (authenticated-but-refused, or a different key type, not proof it is dead) from `/runner_instance` and
`/reports/billing/ci`. Identify it in the WarpBuild console and revoke or replace it. The MCP's OAuth session (`mcp__warpbuild__call_api`)
works without it.

## E. Cost and exposure

WarpBuild bills per minute; the 4x Linux and 6x macOS sizes cost more per minute than GitHub-hosted and are only worth it where the job is
long. Moving a job gives WarpBuild (a third party) its VM, so it sees every secret and token in the job.

1. **Never move** a job that has `secrets.*`, an `environment:` or any write permission, whatever its duration (here: `adversary-marker.yml`
   `marker`, the merge gate, and `roster.yml` `publish`). Only read-only, secret-free jobs qualify.
2. Public repo: Settings -> Actions -> General -> "Approval for running fork pull request workflows from contributors" -> "Require approval
   for all external contributors". It covers fork `pull_request` runs only: never run `pull_request_target`, `workflow_run` or `issue_comment`
   jobs that check out or execute PR code, and never on WarpBuild.
3. A fork PR reads its own workflow file, so it can pick the biggest `warp-*` label, a matrix or a long `timeout-minutes`, all billed to
   the owner. Read the PR's `.github/` diff before approving a fork run, and set a spend and concurrency cap in the WarpBuild console.
4. Standard `warp-*` runners are ephemeral VMs. Public repos use no snapshot runners (`;snapshot.key=…`), and no `snapshot-save` outside a
   push to the default branch: PR runs can read a snapshot by its alias.
