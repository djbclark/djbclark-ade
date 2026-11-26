# CI runners: WarpBuild is fallback-only

**Update 2026-11-25 (operator ruling via Paseo fork build 3 lead `afd98dd (afd98ddc-8604-4b0e-ac1b-13f7b58e6c62)`):** *"Let's change the rules to only use warpbuild if github isn't available or is failing. As I recall the speedup was not that substantial?"*

- **Active rule:** Default and stay on GitHub-hosted runners (`macos-26` for macOS and `ubuntu-latest` for Linux, both free on public repos). Use [WarpBuild](https://www.warpbuild.com/docs/ci/quick-start) **only as a fallback when GitHub-hosted runners are unavailable or failing** (for example: a GitHub Actions runner outage, missing runner capacity/architecture, or a job that OOMs or fails on the GitHub-hosted runner's 3 vCPU / 7 GB spec).
- **Speedup promotion rule removed:** The prior `> 10 min` and `>= 1.5x` (50% faster) promotion gate is retired. Do not move passing GitHub-hosted jobs to WarpBuild for speed alone; revert fallback jobs back to GitHub-hosted once GitHub runners are available and passing.
- On 2026-11-25, Paseo's `fork-desktop-build.yml` was also switched from `warp-macos-26-arm64-6x` back to free GitHub-hosted `macos-26`.

**History (superseded defaults):** On 2026-11-22 (operator ruling via lead `4184015 (41840155-eb9e-4a7d-b449-a3b439d0daee)`), all four `frdminc` repos with any WarpBuild job (`warpbuild-pilot`, `tendcf`, `paseo`, `sudo-secretspec`; all public) were audited (**US$4.83 in 30 days**, 11 jobs, 71 billed minutes, 91% macOS 6x/12x, all from branch-only or one-off pilot workflows, none from default-branch CI) and moved to free runners (`sudo-secretspec` `ci/base` `linux-ci.yml`, `paseo` `fork-desktop-build.yml`; `warpbuild-pilot` `test.yml` is `workflow_dispatch` only; `tendcf` `spike/macos-check8-warp` deleted). The WarpBuild **spend cap is an operator-chosen target of US$10/month** for the `frdminc` org (2026-11-22), **not yet set**: the WarpBuild sign-in was refused, so an agent could not set it, and a hard-cap setting is unconfirmed (the operator sets it in the console at <https://app.warpbuild.com>; per-job cost is on Insights > Spend, CI tab; the app may offer only budget alerts, so confirm the setting exists before relying on it). Billing rounds each job up to whole minutes with a 1-minute floor.

The earlier **2026-11-13** snapshot (which promoted jobs `> 10 min` and `>= 1.5x` / 50% faster on WarpBuild) is superseded by the 2026-11-25 fallback-only rule above. In the 2026-11-13 pilot (section C), `djbclark-ade` measured only 1.07x on Linux and 1.22x on macOS and stays on GitHub-hosted runners under `djbclark`.

## A. Labels (WarpBuild's own mapping, `mcp__warpbuild__suggest_runner_labels`)

Use a `warp-*` label only as a fallback when GitHub-hosted runners are unavailable or failing; mapping `ubuntu-latest` or `macos-26` to WarpBuild for jobs GitHub-hosted runners already run costs more than free.

| GitHub-hosted | WarpBuild |
|---|---|
| `ubuntu-latest`, `ubuntu-24.04` | `warp-ubuntu-2404-x64-4x` |
| `macos-latest`, `macos-26` | `warp-macos-26-arm64-6x` |

Same-size mapping for other labels; go bigger (`8x`, `12x`) only when a smaller runner cannot complete the job (for example, OOM). Change only `runs-on`.
Leave self-hosted labels and `runs-on` expressions alone and list them in the PR.

## B. How to use WarpBuild as a fallback

1. Confirm GitHub-hosted runners are actually unavailable or failing for the job (record the outage, error, OOM, or failed run link). Do not switch passing jobs for speed.
2. The WarpBuild GitHub app must be installed on the **organization** and have access to the repository. A personal-account repo cannot use WarpBuild (section C).
3. Public repo: the org's Default runner group (id 1, where WarpBuild registers) must allow public repositories
   (`gh api -X PATCH orgs/<org>/actions/runner-groups/1 -F allows_public_repositories=true`, needs `admin:org`: add it with
   `gh auth refresh -s admin:org` and drop it afterwards, or use the web UI). That opens every runner in the group to every repo the group
   reaches, so also set group 1 to `visibility=selected` listing only the fallback repos, and install the app on "Only select repositories".
4. Edit `runs-on` on only the affected secret-free job(s), confirm the fallback job starts on a `warp-*` runner, and switch `runs-on` back to GitHub-hosted once GitHub-hosted runners recover or the job passes there.
5. MCP server (user scope): `claude mcp add --transport http --scope user warpbuild https://mcp.warpbuild.com/mcp && claude mcp login warpbuild`
   (the old `docs/apply-toolchain-prompt.md` is archived under `docs/history/`, so the entry lives here). Prefer `--scope local` in the repo
   being configured, or `claude mcp remove warpbuild` after setup: at user scope its vendor-written instructions load into every session, and
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

WarpBuild bills per minute; the 4x Linux and 6x macOS sizes cost more per minute than GitHub-hosted (free on public repos) and are only used as a fallback when GitHub-hosted runners are unavailable or failing. Moving a job gives WarpBuild (a third party) its VM, so it sees every secret and token in the job.

1. **Never move** a job that has `secrets.*`, an `environment:` or any write permission, whatever its duration (here: `adversary-marker.yml`
   `marker`, the merge gate, and `roster.yml` `publish`). Only read-only, secret-free jobs qualify.
2. Public repo: Settings -> Actions -> General -> "Approval for running fork pull request workflows from contributors" -> "Require approval
   for all external contributors". It covers fork `pull_request` runs only: never run `pull_request_target`, `workflow_run` or `issue_comment`
   jobs that check out or execute PR code, and never on WarpBuild.
3. A fork PR reads its own workflow file, so it can pick the biggest `warp-*` label, a matrix or a long `timeout-minutes`, all billed to
   the owner. Read the PR's `.github/` diff before approving a fork run, and set a spend and concurrency cap in the WarpBuild console.
4. Standard `warp-*` runners are ephemeral VMs. Public repos use no snapshot runners (`;snapshot.key=…`), and no `snapshot-save` outside a
   push to the default branch: PR runs can read a snapshot by its alias.
