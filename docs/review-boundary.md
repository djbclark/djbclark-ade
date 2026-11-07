# The review boundary and the merge gate

2026-11-06 (slim-down E8, `docs/slim/PLAN.md` E8 as amended by `docs/slim/research/wave4-2026-11-06.md`). Two pieces replace
the PR waiter and the Codex local review: **`bin/review-launch`**, the only way Claude is launched for a review, and the
**`adversary-marker` Action**, which turns AGENTS.md review rule 1's marker into a required check. Waiting is
`gh pr checks PR --watch --required`. The scripts' docstrings are the full reference; this page is the summary.

## What is untrusted (operator, 2026-11-07: "any GitHub artifacts not directly from us are suspect")

A PR's diff, body, title, commits and commit messages, branch name, issue and PR comments, review comments, bot
and App comments (Codex, Cursor, Copilot included), check-run output and CI logs are all untrusted data, whoever
the author: a prompt-injection attempt through a PR has already happened. They are read as data, never followed as
instructions. The Action never executes, interpolates or checks out anything from a PR; the review model is told
that the diff, the body and every file of its worktree are data under review and that it reports only through the
schema; and only a body whose **last editor** is the repository owner, or an OWNER, MEMBER or COLLABORATOR author
who edited it last, can approve. The operator approves an outside PR by editing its body. (The looser trust the
repository gives its own agents on the machine, AGENTS.md's orders, does not extend to anything that came through
GitHub.)

## `bin/review-launch`: one `claude -p` inside a boundary

```sh
review-launch --mode review|read-only -C WORKTREE --schema FILE (-p TEXT | -f FILE) [--head SHA] [--model M] [--max-turns N] [--timeout S] [--json]
review-launch --check [--mode review|read-only] [--json]
```

| Mode | Tools (`--tools`) | The init event must list exactly |
|---|---|---|
| `review` (rule 11, `bin/review-pr`) | `Read,Grep,Glob` | `Glob, Grep, Read, StructuredOutput` |
| `read-only` (the dispatch shim's Claude restricted mode) | `Read,Grep,Glob,WebFetch,WebSearch` | those plus `StructuredOutput` |

Every launch is `claude -p --output-format stream-json --verbose --tools … --permission-mode default --setting-sources ""
--strict-mcp-config --no-session-persistence --settings SETTINGS --json-schema … [--model] [--max-turns] -- PROMPT`, in the
worktree, with no `--add-dir`. SETTINGS turns on `permissions.blockReadsOutsideWorkingDirectories` (Read, Grep and Glob are
confined to the worktree in every mode, bypass included), `disableAllHooks`, `disableBypassPermissionsMode: "disable"`, and
deny rules for the secret paths (`~/.ssh`, `~/.config/gh`, `~/.claude.json`, `~/.claude/projects`, `~/.aws`, `~/.netrc`,
`~/.config/sudo-secretspec`, …) as a second layer. The environment loses every token, secret, password, credential, API-key,
`GH_*` and `GITHUB_*` variable; `HOME`, `PATH` and `CLAUDE_CONFIG_DIR` stay.

The boundary is **proven from the run's own stream**, never assumed: the init event (found by `subtype == "init"`; it is
not the first line) must show the exact tool set, `mcp_servers == []`, `permissionMode == "default"` (Claude silently
downgrades a refused bypass to `acceptEdits`), the worktree as `cwd` and no additional directories; a hook event, a tool
outside the set, or a Read/Grep/Glob path outside the worktree ends the run at once. Built-in skills, agents and plugins
appear in init whatever the settings and are not asserted. The child runs in its own session; at the end, at the timeout
and on a tripwire its process group and every descendant seen are killed.

| Exit | Launch | `--check` |
|---|---|---|
| 0 | the structured output is on stdout (with `--json`: one run record) | passed |
| 2 | refused: a bypass flag or variable, a missing, dirty or wrong-head worktree, `/` or `$HOME`, a bad schema, no passing self-check | n/a (usage) |
| 3 | no structured output (`is_error`, no result, claude failed, or the launcher got SIGTERM/SIGHUP/SIGINT: the run is killed, never 128+N) | inconclusive (the control read failed, a target was not tried, the model declined): re-run `--check` |
| 77 | **tripwire**: the run left the boundary | a read outside was not refused, or a tripwire |
| 124 | `--timeout` (default 900 s) | timeout |

**The self-check.** Before the first launch for a given `claude --version`, settings and launcher, the same flags run a
canned prompt that reads a temp file outside its worktree, `~/.config/gh/hosts.yml`, `~/.ssh/`, `~/.claude.json`,
`~/.claude/projects/` and `~/.claude/CLAUDE.md`, plus a control file inside. Each outside read must be refused (judged from
`permission_denials` and the stream, never from the model's own answer), the control must be read, and the outside file's
random canary must appear nowhere. `~/.claude/CLAUDE.md` is Claude Code's documented exemption: if it is readable it is
recorded under `accepted_exposures`, not failed. The check runs on the launch's own `--model` and the result is cached per model in
`~/.local/state/review-launch/check-<sha256>.json` (the key hashes the Claude version, the settings, the fixed argv, the model
and the launcher; 2026-11-07: a check on an unavailable default model tripped on its `fallback` notice); a failed or missing check refuses every launch until
`review-launch --check` passes. `--bare` is not used: it would hide CLAUDE.md but never reads OAuth or the keychain, so the
Mac's review would have no login.

Evidence (2026-11-06, the slim-down's Linux cloud container, Claude Code 2.1.319, `apiKeySource: none`): `--check` passed in
both modes; every outside target was **refused**, `~/.claude/CLAUDE.md` included (so no accepted exposure there), and the
control was read. A live launch that read `a.txt` returned its content (exit 0); one told to read `/etc/hostname` was
stopped by the tripwire (exit 77). The Mac's own check is an operator step (below): CI cannot vouch for the version there.

## `bin/review-pr PR`: rule 11's local review

From a checkout of the repository, after the push: it reads the PR (`gh pr view --json headRefOid,baseRefOid,baseRefName,
author,state`), refuses an author who is neither the repository owner nor the authenticated gh user unless
`--allow-untrusted`, adds a clean detached worktree at exactly the head, writes `git diff BASE...HEAD` and the file list into
its `.review-launch/`, runs `review-launch --mode review --head HEAD` with `config/review-schema.json`, prints
`<!-- adversary-verdict:v1 {"verdict":"…","head":"<the full head>"} -->` (checked against the gate's own parser), files
`~/.local/state/review-launch/<owner>__<name>-pr<N>-<head>.json` and removes the worktree. Exit 0 APPROVE, 1 BLOCK, 2 refused,
3 failed, 77 tripwire, 124 timeout. It never posts. Paste the marker into the PR body, then:

```sh
gh workflow run adversary-marker.yml -f pr=N      # a body edit is not a Tests run: re-check the marker
gh pr checks N --watch --required                 # wait for Tests and the marker
gh pr merge N --squash --match-head-commit <the head the marker names>
```

## The `adversary-marker` Action

`.github/workflows/adversary-marker.yml` runs `bin/adversary_marker.py` on `workflow_run` (the `Tests` workflow completed,
whatever its conclusion) and on `workflow_dispatch` (input `pr`). Both run the workflow file and the module from **master**;
nothing from the PR is checked out or executed. Job `resolve` (no secret) finds the PR (the event's `pull_requests[]`, else
`commits/{sha}/pulls`, else `pulls?head=owner:branch` for a fork) and outputs its number; job `marker` runs in the
concurrency group `adversary-marker-<that number>` (a newer run for the PR cancels an older one; a sha two PRs share never
merges their groups), reads the body and head through the API with the job's read-only token (`pull-requests: read`,
`contents: read`), judges the marker with the parser moved unchanged from the PR waiter (rule 1's five properties, 2,559
test cases), **re-reads the head, the body and its last editor in one GraphQL query and posts only if the head is
unchanged** (judging that second read's body), and posts the commit status `adversary-marker` on that head with a token of
the `ade-merge-gate` App: `success` only for a live APPROVE naming the head in a body last edited by a trusted user (above),
`failure` for a BLOCK, another head, no marker, a malformed one, or "marker not written by a trusted user". It
fails closed: an API error posts nothing and fails the job (the required check stays missing); a PR whose `Tests` workflow
was edited away gets no status; a dispatch from any branch but master cannot reach the `merge-gate` environment's key.
`MARKER_POST_AS: check-run` on the step posts the same verdict as a check run (the fallback below); the token step asks
for both `statuses: write` and `checks: write`, so the App must have both.

## Operator setup (once; nothing here is done by an agent)

1. **The App.** GitHub → Settings → Developer settings → GitHub Apps → New: name `ade-merge-gate`, Webhook off, repository
   permissions **Commit statuses: Read and write**, **Checks: Read and write** and **Pull requests: Read-only**,
   installable on this account only. Note
   the App ID and the Client ID; generate a private key. Install it on `djbclark/djbclark-ade` only. Both write
   permissions are needed: the workflow's token step requests both, and token creation fails if the App lacks one.
2. **The environment.**
   ```sh
   echo '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' \
     | gh api -X PUT repos/djbclark/djbclark-ade/environments/merge-gate --input -
   gh api -X POST repos/djbclark/djbclark-ade/environments/merge-gate/deployment-branch-policies -f name=master -f type=branch
   gh secret set MERGE_GATE_PRIVATE_KEY --env merge-gate --repo djbclark/djbclark-ade < ade-merge-gate.private-key.pem
   gh variable set MERGE_GATE_CLIENT_ID --env merge-gate --repo djbclark/djbclark-ade --body '<the Client ID>'
   ```
   (the key goes through stdin, never argv; delete the downloaded `.pem` afterwards or keep it in `sudo-secretspec`).
3. **Prove the App's status counts** (research item 18 is unverified) and the spoofing and shared-sha cases (T0-T3), with throwaway PRs, before
   the ruleset: `docs/slim/reports/wave4-E8.md`, section E, has the exact commands.
4. **The ruleset** (required checks pinned to their sources; `bypass_actors` empty, so admins are held too):
   ```sh
   gh api -X POST repos/djbclark/djbclark-ade/rulesets --input ruleset.json
   ```
   with `ruleset.json` as in the E8 report (section E): `adversary-marker` pinned to the App's ID, the Tests jobs
   `pytest-linux` and `context-policy` pinned to GitHub Actions (`integration_id` 15368). Branch protection (PR only,
   admins included) stays as it is.
