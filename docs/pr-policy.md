# pr-policy: who may open pull requests on djbclark's repositories

`bin/pr-policy` (2026-11-04, operator request: "only accept PRs from me, everyone else can only do draft PRs for me
to approve, and make that the default for any future repos"). Config: [`config/pr-policy.toml`](../config/pr-policy.toml).

## What it enforces

1. **GitHub, owners `djbclark` and `frdminc`**: every live repository with pull requests turned on gets
   `pull_request_creation_policy=collaborators_only`, GitHub's "Pull requests: Collaborators only" setting
   ([changelog, 2026-02-13](https://github.blog/changelog/2026-02-13-new-repository-settings-for-configuring-pull-request-access/)).
   Only users with write access can open a pull request; everyone else can still read, comment and open issues.
   Archived repositories are read-only and are skipped; one that is unarchived is picked up on the next run.
2. **Any open pull request from someone not trusted is kept a draft**, so it cannot be merged until djbclark marks
   it ready. On GitHub that is `convertPullRequestToDraft` (GraphQL), for a pull request opened before the setting
   (on 2026-11-04, [frdminc/ShizukuTendCF#24](https://github.com/frdminc/ShizukuTendCF/pull/24), from a since-deleted
   account). On Forgejo, which has no collaborators-only setting (Forgejo 17.0.1 on forgejo.mit.edu, 2026-11-04: the
   repository options carry only `has_pull_requests` on or off), it is a `WIP: ` title prefix, the server's draft
   marker (`WORK_IN_PROGRESS_PREFIXES`); the tool checks that the pull request reads `draft: true` afterwards. An
   author who removes the prefix gets it back on the next run.
3. **Repositories created later** are covered by the launchd job `com.djbclark.pr-policy`, which runs
   `apply --yes --notify --quiet` every 600 s. GitHub has no account-level default for this setting, so a new
   repository is open to outside pull requests for at most one interval.

GitHub has no "outsiders may open drafts only" mode: on GitHub an outsider cannot open a pull request at all, and
the route left to them is an issue (or a fork they link from one). The pull request limits GitHub added later
(June to October 2026: a cap on open pull requests per user without write access, drafts counted, exemptions) are
not used: they bound volume, they do not stop it.

## Trust

| Forge | Trusted author |
|---|---|
| GitHub | the token's login; `trusted_authors`; anyone whose repository permission is `write` or `admin` (`maintain` reads as `write`) |
| Forgejo | the token's login; the repository owner; `trusted_authors`; an invited collaborator (`GET /repos/O/R/collaborators/U` is 204) with `write`, `admin` or `owner` permission |

Forgejo's permission endpoint answers `owner` for its site admins on every repository (2026-11-04: `xy` and
`almonds` on `djbclark/barnowl`, neither a collaborator), so permission alone never makes a Forgejo author trusted.
A bot gets no exemption for being a bot (an app installed on someone else's fork is not one djbclark chose); list
it in `trusted_authors` (for example `"dependabot[bot]"`) to keep its pull requests ready. On 2026-11-04 no bot had
opened a pull request on these repositories in six months.

## Commands

| Command | Does |
|---|---|
| `pr-policy plan [--json] [--only github\|forgejo]` | what `apply` would change; read-only |
| `pr-policy apply --yes [--notify] [--quiet]` | makes the changes; without `--yes` it is `plan`. `--notify` sends one `hermes-ping` per run that changed something or hit an error not reported before; `--quiet` prints nothing when nothing changed |
| `pr-policy install [--ade DIR] [--dry-run]` | renders [`config/launchd/com.djbclark.pr-policy.plist`](../config/launchd/com.djbclark.pr-policy.plist) into `~/Library/LaunchAgents` and bootstraps it; refuses a linked worktree unless `--ade` is given |
| `pr-policy uninstall` | boots the job out and removes its plist; state is kept |

Exit codes: 0 done or nothing to do, 1 an API or secret error (the other changes still ran), 2 usage or config
error, 69 `install`/`uninstall` off macOS.

Before a change the tool re-reads the repository itself: the repository listing lags a PATCH by seconds
(2026-11-04: all nine `frdminc` repositories listed `all` right after a successful PATCH), and without the re-read
the next run would report a change it did not make.

## Credentials and safety

1. Tokens are the sudo-secretspec names in the config (`GITHUB_TOKEN`, djbclark's `repo`-scope token;
   `DJBCLARK_FORGEJO_MIT_EDU_TOKEN`), read with `sudo-secretspec get` once per run, held in memory, never printed or logged.
   `get`, not `run`, is deliberate (AGENTS.md review rule 3): `run` would hand every declared secret to the job and to
   each child it starts, `hermes-ping` included.
2. A token goes only to its own API origin, scheme and host both, over https (plain http is allowed for 127.0.0.1
   only, for the tests); redirects are not followed, and a pagination link to another origin is refused.
3. State in `~/.local/state/pr-policy/` (`PR_POLICY_STATE_DIR`): `changes.jsonl`, one line per change made (before,
   after, URL, result); `state.json`, the error keys already reported, recorded only once `hermes-ping` succeeded so a
   failed ping is retried next run (written atomically); `run.log`, the job's output.

## Reverting

1. One repository: add `owner/name` to `exempt_repos` in the config (otherwise the job sets it back), then
   `gh api -X PATCH repos/OWNER/NAME -f pull_request_creation_policy=all`.
2. Everything: `pr-policy uninstall`, then set `policy = "all"` in a scratch copy of the config and run
   `pr-policy apply --yes --config COPY --only github`.

## First run (2026-11-04)

127 live GitHub repositories set to `collaborators_only` (119 `djbclark`, 8 `frdminc`; `frdminc/Shizuku-API` is
archived and was left alone), [frdminc/ShizukuTendCF#24](https://github.com/frdminc/ShizukuTendCF/pull/24) made a
draft, and [djbclark/barnowl#4](https://forgejo.mit.edu/djbclark/barnowl/pulls/4) on Forgejo made a draft. Verified
afterwards by reading every repository's setting back and by a `plan` that found nothing to change.
