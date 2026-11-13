# CI runners: WarpBuild for long jobs

Snapshot **2026-11-13** (operator rulings, card answers). A GitHub Actions job moves to
[WarpBuild](https://www.warpbuild.com/docs/ci/quick-start) runners only when **both** hold:

1. It takes **more than 10 minutes** on GitHub-hosted runners.
2. A measured pilot shows WarpBuild **at least 50% faster** (operator, 2026-11-13: "Let's put a minimum 50% faster and each project can see
   if its stuff gets past that gate"). Faster means GitHub-hosted time divided by WarpBuild time is at least 1.5, so the WarpBuild run takes
   at most two thirds as long.

Everything else stays on GitHub-hosted runners. Each project measures its own jobs (section B) and moves only the jobs that pass. Applies to the
operator's active repositories (not archived ones, third-party forks, or repos with no recent CI). djbclark-ade itself failed the gate
(section C pilot: 1.07x Linux, 1.22x macOS) and stays on GitHub-hosted runners under `djbclark`.

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
3. Measure before moving anything: copy the repo's tree (secret-free workflows only) into `frdminc/warpbuild-pilot` (add it nowhere else),
   run each job over 10 minutes once on its `warp-*` label and once on its GitHub-hosted label, and compare job durations
   (`gh run view --json jobs`). Only jobs at 1.5x or better pass the gate. A personal-account repo that passes needs a transfer to an
   organization first (section C; the operator decides per repo, and the transfer audit has to cover the merge-gate App, rulesets and the
   org's installed apps).
4. Edit `runs-on` of each passing job, open a PR titled "Switch CI to WarpBuild runners", confirm a job starts on a `warp-*` runner and
   compare durations again, then merge.
5. MCP server (user scope): `claude mcp add --transport http --scope user warpbuild https://mcp.warpbuild.com/mcp && claude mcp login warpbuild`
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

### Org pilot (2026-11-13): it works in an organization

`frdminc/warpbuild-pilot` (public, runner group 1 = selected repositories, "Allow public repositories" on) ran this repo's Tests workflow
twice, once with `warp-*` labels and once on GitHub-hosted twins of the same tree (test.yml only; same 7 `adversary-marker` test failures on
both sides because that workflow file was left out of the copy). Jobs started within seconds on `warp-4x-x64-…` and `warp-6x-arm64-…` runners.

| Job | WarpBuild | GitHub-hosted | Gain |
|---|---|---|---|
| pytest-linux (suite 794 s vs 851 s) | `warp-ubuntu-2404-x64-4x` 13.4 min | `ubuntu-latest` 14.4 min | about 7% |
| macOS pytest (suite 1361 s vs 1646 s) | `warp-macos-26-arm64-6x` 23.1 min | `macos-latest` 28.1 min | about 18% |

Evidence: runs 43514103522 (warp) and 43514108143 (GitHub) in that repository. Speed-up: 1.07x Linux, 1.22x macOS, both below the
1.5x gate, so djbclark-ade was not transferred (an audit for the transfer, kept in the lead's state, found the private `ade-merge-gate`
App cannot follow the repo to an org).

## D. API access

`https://api.warpbuild.com/api/v1`, `Authorization: Bearer wkey-…` (a key with the `ci` scope from <https://app.warpbuild.com/settings/api-keys>).
Pass a key from a file or the environment, never on argv. The name `WARPBUILD_API_KEY` stays declared in `sudo-secretspec` with no
value: the UUID first stored there got 403 from `/runner_instance` and `/reports/billing/ci` and was deleted (operator, 2026-11-13). Store a
`wkey-` key there only when a script needs the API. The MCP's OAuth session (`mcp__warpbuild__call_api`) works without one.

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
