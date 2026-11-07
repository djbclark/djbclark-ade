# Wave 4 E8 (S-git) report, 2026-11-06

Writer: one Claude agent (Opus 5.5) in its own worktree, branch `worktree-agent-ae4c82a968f7e7be0`. The worktree was created
at master `fb3b9de`, not on the slim branch, so before any commit of mine the branch was **fast-forwarded** (no rebase, no
merge commit) to `claude/determined-maxwell-uvddaz` at `594fd3d`, which carries the brief. Nothing pushed, nothing posted to
GitHub. Commits: `9f92ba3` (the Action and the moved parser), `232c4b1` (review-launch, review-pr), `9daa692` (deletions and
reference edits), `f94153f` (D9), `bde841f` (review-boundary.md, fragment, check-run fallback), and this report.
Brief: `docs/slim/briefs/wave4-E8-gate.md`.

Places where this slice departs from the brief, each argued where it falls: **A6** (the kill targets the child's own
session, not "the launcher's own process group"), **A7** (review-launch is ~750 lines, not ~300), **B2** (three-dot diff,
not `BASE..HEAD`), **C4** (the unreadable outcome is named `unreadable` / `adversary-unreadable`, because the brief bans the
old word), **D1** (the moved tests are 81 functions / 2,559 cases, not "111"), **E2** (the Tests check names are
`pytest-linux` and `context-policy`, not `test`), **F1** (D9 removes the uncalled verbs and adds expiry; it does **not**
narrow the guard's rules), and **J0** (a live `claude -p` works in this container, so the self-check was also run live).

## A. review-launch

A1. **Interface** (`bin/review-launch`, brief 1a): `review-launch --mode review|read-only -C WORKTREE --schema FILE (-p TEXT
| -f FILE) [--head SHA] [--model M] [--max-turns N] [--timeout S] [--json]` and `review-launch --check [--mode M] [--json]`.
stdout carries only the run's `structured_output` JSON (or, with `--json`, one run record); every note goes to stderr.
Exit 0 / 2 / 3 / 77 / 124 as the brief; `--check` exits 0 passed, 77 a read not refused or a tripwire, 3 inconclusive, 124.

A2. **The exact argv** (cwd = the realpath of the worktree; the prompt is argv after `--`, so one starting with `-` is never
a flag, and the launcher never writes it into the worktree):

```
claude -p --output-format stream-json --verbose --tools Read,Grep,Glob --permission-mode default --setting-sources "" \
       --strict-mcp-config --no-session-persistence --settings SETTINGS --json-schema SCHEMA [--model M] [--max-turns N] -- PROMPT
```

`--mode read-only` passes `--tools Read,Grep,Glob,WebFetch,WebSearch`. No `--add-dir`, no `--mcp-config`, no `--bare`. The
binary is `claude` on PATH (or `$REVIEW_LAUNCH_CLAUDE`). `--permission-mode default` is accepted by 2.1.319 although its
`--help` lists `manual` and not `default` (probed 2026-11-06: an unknown value is a parse error, `default` gives init
`permissionMode: "default"`).

A3. **SETTINGS** (compact, sorted keys, the exact bytes the cache key hashes):

```json
{"disableAllHooks":true,"hooks":{},"permissions":{"blockReadsOutsideWorkingDirectories":true,"deny":["Read(~/.config/gh/**)","Read(~/.ssh/**)","Read(~/.claude.json)","Read(~/.claude/projects/**)","Read(~/.aws/**)","Read(~/.netrc)","Read(~/.config/sudo-secretspec/**)","Read(~/.gnupg/**)","Read(~/.git-credentials)","Read(~/.docker/config.json)","Read(~/.kube/**)","Read(~/.config/gcloud/**)","Read(~/.npmrc)","Read(~/.pypirc)","Read(~/Library/Keychains/**)"],"disableBypassPermissionsMode":"disable"}}
```

`~/.local/state/**` is deliberately NOT denied: `bin/review-pr`'s worktrees live under `~/.local/state/review-launch/wt/`,
and a deny rule there would refuse reads inside the worktree under review (caught while writing review-pr).

A4. **Refused before anything runs (exit 2)**: any of `--permission-mode`, `--dangerously-skip-permissions`,
`--allow-dangerously-skip-permissions`, `--add-dir`, `--mcp-config`, `--settings`, `--setting-sources`, `--tools`,
`--allowedTools`/`--allowed-tools`, `--disallowedTools`, `--plugin-dir`, `--agents` in the launcher's own argv (none is an
option; nothing is passed through); an environment variable whose name matches
`permission_?mode|bypass_?permissions|skip_?permissions|dangerously` with a value; a worktree that is missing, `/`, `$HOME`
or an ancestor of `$HOME`; with `--head`, a HEAD other than SHA or a `git status --porcelain --untracked-files=all` that
shows anything but `?? .review-launch/…`; a schema that does not parse to an object; an empty prompt; no passing self-check.
The child's environment drops every name matching the removed local review's `SECRET_ENV_RE`
(`token|secret|passw|credential|api_?key`, `^GH_`, `^GITHUB_`); HOME, PATH and CLAUDE_CONFIG_DIR stay.

A5. **Init assertions** (the first `type: system, subtype: init` event, wherever it falls; 2.1.319 emits a `ui_invalidate`
event first): `set(tools)` equals the mode's set plus `StructuredOutput` exactly (no extra, no missing, no duplicate);
`mcp_servers == []`; `permissionMode == "default"`; `realpath(cwd)` is the worktree; `additional_directories` absent or
`[]`. Not asserted: `skills`, `slash_commands`, `agents`, `plugins` (built-ins appear). Tripwire (77, the run killed at
once) also on: an assistant event before any init; a `system` event whose subtype starts with `hook`; a `tool_use` outside
the allowlist; a Read `file_path`, Grep/Glob `path`, or Glob `pattern` / Grep `glob` that is absolute, `~`-rooted or climbs
with `..` and resolves (realpath, so symlinks count) outside the worktree; a stream with no init at all. The refusals in
`result.permission_denials[]` are logged to stderr. `result.is_error`, no result event, or no `structured_output` is exit 3.

A6. **Kill** (brief 1d said `os.killpg` "on the launcher's own process group"): the child is started with
`start_new_session=True` and the kill is `os.killpg(child)` plus SIGKILL of every descendant seen by a `ps -A -o
pid=,ppid=,lstart=` snapshot each second (start time checked, as the removed local review did), at the end, at the timeout,
on a tripwire and on SIGTERM/SIGHUP/SIGINT. Killing the launcher's own group would kill its caller (review-pr, the
dispatch shim, an interactive shell) when they share it; a test pins that the caller's group survives. A descendant that
inherits stdout no longer stalls the read: once the leader has exited (2 s grace) or 15 s after the result event, reading
stops and the kill runs (found by the test, which hung at the 900 s timeout before the fix). macOS and Linux: `ps` and
`os.killpg` only, no `/proc`.

A7. **Size**: 753 lines, against the brief's "~300": about 120 are the docstring (review rule 8 wants the exit codes and the
contract in the usage text), the rest is the stream reader, the path checks and the self-check.

A8. **Self-check paths and what (vi) showed.** The check makes a temp dir with `wt/inside.txt` (the control, must be READ) and
`outside/secret.txt` holding a random canary (`rl-canary-<32 hex>`), and asks the model to Read or Glob: (i) that outside
file, (ii) `~/.config/gh/hosts.yml`, (iii) `~/.ssh` (Glob), (iv) `~/.claude.json`, (v) `~/.claude/projects` (Glob), (vi)
`~/.claude/CLAUDE.md`. The verdict comes from the stream (a target is `refused` when its tool_use id is in
`permission_denials` or its result carries `permission_decision: deny`; the worst call per target counts), never from the
model's answer, and the canary must not appear anywhere in the raw stream. A home path that does not exist is `absent`
(nothing to expose) unless it was refused. Cache: `~/.local/state/review-launch/check-<sha256 of claude --version, SETTINGS,
the fixed argv, the launcher file>.json` (0600, atomic), one per mode.
- **On the fake** (`tests/fixtures/fake-claude-review`): the passing shape refuses (i)-(vi) and reads the control; the
  `readable_md` shape reads (vi), which is recorded in `accepted_exposures` and the check still passes; `leak` (the canary
  appears), `leak_quiet` (read, no canary), `trip` (a Bash call) fail (77) and `control_fails`, `skip:outside-temp` are
  inconclusive (3); each failure refuses every later launch with exit 2 until a check passes.
- **Live, this Linux container, Claude Code 2.1.319, 2026-11-06** (J0): `--check` passed in both modes; (i)-(v) and **(vi)
  were all refused** (`~/.claude/CLAUDE.md` exists here, 778 bytes, and the Read tool was denied, so no accepted exposure);
  the control was read; `~/.config/gh/hosts.yml` does not exist here and was still refused, so the key denies before it
  looks at existence. Re-run with the final launcher: passed again. Whether `~/.claude/CLAUDE.md` is *loaded into the
  system prompt* under `--setting-sources ""` (the exemption's other half) is not visible in the stream and stays
  unverified. Two live launches: reading `a.txt` returned its line (exit 0, init tools `Glob, Grep, Read, StructuredOutput`,
  `mcp_servers: []`, `permissionMode: default`); "Read /etc/hostname" was stopped by the tripwire (exit 77).
- **`--bare`**: not used. 2.1.319's `--help` says bare mode reads auth only from `ANTHROPIC_API_KEY` or an `apiKeyHelper`
  ("OAuth and keychain are never read"); the Mac authenticates with OAuth (research item 9) and the scrub drops API keys, so
  a bare review would have no login. Since (vi) was refused anyway, nothing is gained.

## B. review-pr

B1. `bin/review-pr PR [--repo OWNER/NAME] [--allow-untrusted] [--model M] [--timeout S] [--json]` (270 lines), from a checkout
whose `origin` is the whole OWNER/NAME (never a substring): `gh pr view PR --repo R --json
headRefOid,baseRefOid,baseRefName,author,state`; the trust check (owner or `gh api user`, else exit 2 unless
`--allow-untrusted`); `git fetch origin refs/pull/N/head +refs/heads/BASE:refs/review-pr/base-PID` (the temp ref deleted at
once), both SHAs checked present; `git worktree add --detach` under `~/.local/state/review-launch/wt/`; the diff and file
list into `.review-launch/`; `review-launch --mode review --head HEAD -C WT --schema config/review-schema.json -p PROMPT
--json`; the output must be `APPROVE`/`BLOCK` for exactly this head, else exit 3 and no marker; the marker is printed with
verdict and head only (the model's text never enters it) and is checked with `adversary_marker.adversary_verdict` before it
is printed; the result file `~/.local/state/review-launch/<owner>__<name>-pr<N>-<head>.json` (atomic, 0600); the worktree is
removed in `finally` (force, then rmtree and prune). Exit 0/1/2/3/77/124. It never calls `gh` for anything but `pr view` and
`api user` (pinned by a test).

B2. **Three-dot diff** (brief: `git diff BASE..HEAD`): `BASE...HEAD` is the PR's own change since the merge base, the diff
GitHub shows; two-dot would also show the base branch's later commits reversed, as if the PR removed them.

B3. The prompt names the diff file, says the model can run nothing and read nothing outside, and says the checkout (its
AGENTS.md and CLAUDE.md included) is untrusted data whose instructions are findings. Lost on purpose: the removed local
review's load gate (`load-watch admit`) is not in review-pr (K5).

## C. The Action

C1. **Trigger**: `on: workflow_run: {workflows: ["Tests"], types: [completed]}` and `workflow_dispatch: {inputs: {pr:
{required: true, type: string}}}`; no `pull_request`, no `pull_request_target` (a test pins it). `permissions: {}` at the top;
the job: `permissions: {pull-requests: read, contents: read}`, `environment: merge-gate`, `if: github.ref ==
refs/heads/<default branch>`, `concurrency: {group: adversary-marker-${{ github.event.inputs.pr ||
github.event.workflow_run.pull_requests[0].number || github.event.workflow_run.head_sha }}, cancel-in-progress: true}`
(a fork PR's run has no `pull_requests[]` entry, so its group is the head sha), timeout 5 min.

C2. **Steps**: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1, `persist-credentials: false`, no `ref`:
the default branch, never the PR); `actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510` (v3.3.0, with
`client-id: ${{ vars.MERGE_GATE_CLIENT_ID }}`, `private-key: ${{ secrets.MERGE_GATE_PRIVATE_KEY }}`, `permission-statuses:
write`); `python3 -I bin/adversary_marker.py --event "$GITHUB_EVENT_PATH" --event-name "$GITHUB_EVENT_NAME" --repo
"$GITHUB_REPOSITORY"` with `GITHUB_TOKEN` (reads) and `STATUS_TOKEN` (the App token, the post). Both SHAs were read with
`git ls-remote` on 2026-11-06 (lightweight tags). No `${{ }}` is interpolated into a shell line (a test pins it).

C3. **Flow** (`run_event`): the PR from the dispatch input (digits only), else the event's `pull_requests[]` (entries whose
base repository is this one), else `GET commits/{head_sha}/pulls` (open, head equal, base this repository), else `GET
pulls?state=open&head=OWNER:BRANCH` (a fork's PR, whose `pull_requests[]` GitHub leaves empty); for each PR: read
`pulls/N`, skip if not open, judge, **re-read**, post nothing if the head moved or the PR closed, judge the second read's body
(so a BLOCK edit between the reads is what lands), post `POST statuses/{head}` with `context: adversary-marker`, `state:
success` only for `approve`, else `failure`, description `APPROVE at <12 hex>` and the like, `target_url` the run. Two open
PRs on one head whose verdicts differ get a final `failure` naming both. A `Tests` run whose conclusion is failure is judged
the same (a test pins it).

C4. **Outcomes** (`outcome()`, derived from `gate()` so a pass has one predicate): `approve`, `block`, `other-head`,
`missing`, `malformed`, `unreadable`; `--body-file` mode exits 0, 1, 1, 1, 2, 2. The old waiter called the last one
`adversary-fetch-failed`; the brief bans that word, so `gate()` names it `adversary-unreadable` and `gate(None)` (nothing
collected) is now `adversary-unreadable` and blocks (the waiter skipped the branch for None; the Action has no
"not collected" state, so failing closed is the only reading).

C5. **What fails closed**: an event it cannot read, a dispatch input that is not a positive integer, any event but
`workflow_run`/`workflow_dispatch`, a head that is not 40 hex, an API error on any read or on the post (job exit 2, no
success posted, the required check stays missing); no App token (no post); a moved head (no post: the push's own Tests run
decides); a PR that edits or removes `test.yml` (no `workflow_run`, no status); a dispatch from another ref (the job's `if`,
and the environment's branch policy denies the key). What it cannot show by itself: that the ruleset pins the App (E3).

C6. **Fallback for research item 18**: `MARKER_POST_AS: check-run` in the step's env posts the same verdict as a check run
(`POST check-runs`, name `adversary-marker`, `conclusion` success/failure); the App then needs "Checks: write". One env line
and one permission; the ruleset entry does not change (the check name is the context).

C7. Tests: 48 for the Action's logic and the workflow file (`tests/test_adversary_marker.py` after the moved block),
against `CannedApi` and the CLI's `--api-answers`.

## D. The port

D1. `bin/pr-wait:263-1047` (the "adversary verdict" banner through `adversary_from_doc`, 785 lines) is in
`bin/adversary_marker.py:48-832` **byte for byte** (`diff` of the two ranges is empty, checked before the deletion). The
waiter's `assess()` adversary branch is `gate()` (unchanged but the C4 rename). The brief's "111 marker tests": I count
**81 test functions** in `tests/test_pr_wait.py` that exercise the marker parser and its gate (lines 1560-1949, 2086-2404,
2562-2583, 2601-2929), **2,559 collected cases** with their parametrisations; I could not reproduce 111. They moved to
`tests/test_adversary_marker.py` with only `load_module()` (now the imported module) and the `gate()` helper's last lines
changed. Before the deletion the same `-k` selection ran in both files: **2,559 passed in the old file, 2,559 passed in the
new** (rc 0 both). Not moved: the 12 `test_main_*` tests (they drive the waiter's polling loop through a fake `gh`: mid-wait
body edits, label changes, one fetch per poll; K1), and the two `test_null_*_review` tests (Codex threads, K1).

## E. The ruleset and the App (operator; exact commands)

E1. **The App** (GitHub UI): Settings → Developer settings → GitHub Apps → New GitHub App: name `ade-merge-gate`, homepage
`https://github.com/djbclark/djbclark-ade`, Webhook: uncheck Active, Repository permissions: **Commit statuses: Read and
write**, **Pull requests: Read-only** (Metadata read-only is implied), "Only on this account". Create; note the **App ID**
(the ruleset's `integration_id`) and the **Client ID**; "Generate a private key" (a `.pem` download). Install App → Only
select repositories → `djbclark-ade`. Check: `gh api repos/djbclark/djbclark-ade/installation --jq '.app_slug, .app_id'`.

E2. **The environment, its branch policy, the key and the client id**:

```sh
echo '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' \
  | gh api -X PUT repos/djbclark/djbclark-ade/environments/merge-gate --input -
gh api -X POST repos/djbclark/djbclark-ade/environments/merge-gate/deployment-branch-policies -f name=master -f type=branch
gh api repos/djbclark/djbclark-ade/environments/merge-gate/deployment-branch-policies --jq '.branch_policies[].name'   # master
gh secret set MERGE_GATE_PRIVATE_KEY --env merge-gate --repo djbclark/djbclark-ade < ~/Downloads/ade-merge-gate.*.private-key.pem
gh variable set MERGE_GATE_CLIENT_ID --env merge-gate --repo djbclark/djbclark-ade --body '<the Client ID, Iv23…>'
rm ~/Downloads/ade-merge-gate.*.private-key.pem     # or keep it in sudo-secretspec; never in a tracked file
```

No required reviewers on the environment (they would stop every run). Confirm the Tests check names first (E5 uses them):
`gh api repos/djbclark/djbclark-ade/commits/$(git rev-parse origin/master)/check-runs --jq '.check_runs[] | [.name, .app.id] | @tsv'`
(expected `pytest-linux 15368`, `context-policy 15368`; the brief's `test` is not a job name in `.github/workflows/test.yml`).

E3. **The throwaway-PR tests, in order** (after the final PR is merged: `workflow_run` runs master's copy of the workflow,
so the Action cannot run for any PR before it is on master). Each in its own worktree (order 9); `N` is the PR number.

T0, the App's status reaches the head and (after E5) satisfies the pin (research item 18, unverified):
```sh
git -C ~/src/djbclark-ade fetch origin
git -C ~/src/djbclark-ade worktree add -b throwaway/marker-approve ~/src/djbclark-ade-tm0-wt origin/master
cd ~/src/djbclark-ade-tm0-wt && date -u +%FT%TZ > throwaway-marker.txt && git add throwaway-marker.txt
git commit -m "throwaway: adversary-marker App status (do not merge)" && git push -u origin HEAD
H=$(git rev-parse HEAD)
gh pr create --draft --title "throwaway: marker App status (do not merge)" \
  --body "<!-- adversary-verdict:v1 {\"verdict\":\"APPROVE\",\"head\":\"$H\"} -->"
gh run list --workflow adversary-marker.yml --limit 3          # after Tests completes
gh api "repos/djbclark/djbclark-ade/commits/$H/statuses" --jq '.[] | [.context, .state, .creator.login] | @tsv'
#   expect: adversary-marker  success  ade-merge-gate[bot]
```
After E5: `gh pr view N --json mergeStateStatus,statusCheckRollup` must not report `adversary-marker` as expected/missing.
If it does (the status does not match `integration_id`), apply C6 (add `MARKER_POST_AS: check-run` to the step's `env`,
give the App "Checks: write", accept the new permission on the installation) and re-run with
`gh workflow run adversary-marker.yml -f pr=N`.

T1, a PR that edits `adversary-marker.yml` into an always-green job:
```sh
git -C ~/src/djbclark-ade worktree add -b throwaway/marker-edit ~/src/djbclark-ade-tm1-wt origin/master
cd ~/src/djbclark-ade-tm1-wt
python3 - <<'EOF'
import re, pathlib
p = pathlib.Path(".github/workflows/adversary-marker.yml")
t = p.read_text()
t = re.sub(r"run: python3 -I bin/adversary_marker\.py.*",
           'run: gh api "repos/$GITHUB_REPOSITORY/statuses/$HEAD" -f state=success -f context=adversary-marker -f description=spoof',
           t)
t = t.replace("STATUS_TOKEN: ${{ steps.app-token.outputs.token }}",
              "GH_TOKEN: ${{ github.token }}\n          HEAD: ${{ github.event.workflow_run.head_sha }}")
p.write_text(t)
EOF
git commit -am "throwaway: always-green adversary-marker (must NOT pass the ruleset)" && git push -u origin HEAD
gh pr create --draft --title "throwaway: marker workflow edit (do not merge)" --body "no marker on purpose"
gh workflow run adversary-marker.yml --ref throwaway/marker-edit -f pr=N   # a dispatch of the edited file from its branch
```
Expect: the PR's edited file never runs on `workflow_run` (master's copy does, and posts `failure`, "no adversary-verdict:v1
marker"); the dispatch from the branch is skipped by the job's `if` (and could not reach the key anyway);
`gh pr view N --json mergeStateStatus` stays `BLOCKED`; `gh pr merge N --squash --match-head-commit "$(git rev-parse HEAD)"`
is refused.

T2, a PR that adds a spoofing workflow with `permissions: {statuses: write}`:
```sh
git -C ~/src/djbclark-ade worktree add -b throwaway/marker-spoof ~/src/djbclark-ade-tm2-wt origin/master
cd ~/src/djbclark-ade-tm2-wt && cat > .github/workflows/spoof.yml <<'EOF'
name: spoof
on: pull_request
permissions:
  statuses: write
jobs:
  spoof:
    runs-on: ubuntu-latest
    steps:
      - env:
          GH_TOKEN: ${{ github.token }}
          HEAD: ${{ github.event.pull_request.head.sha }}
        run: gh api "repos/$GITHUB_REPOSITORY/statuses/$HEAD" -f state=success -f context=adversary-marker -f description=spoof
EOF
git add .github/workflows/spoof.yml && git commit -m "throwaway: spoofed adversary-marker status (must NOT pass)" && git push -u origin HEAD
gh pr create --draft --title "throwaway: spoofed status (do not merge)" --body "no marker on purpose"
gh api "repos/djbclark/djbclark-ade/commits/$(git rev-parse HEAD)/statuses" --jq '.[] | [.context, .state, .creator.login] | @tsv'
#   expect two: adversary-marker success github-actions[bot] (the spoof) and adversary-marker failure ade-merge-gate[bot]
```
Expect, with E5 active: `mergeStateStatus` stays `BLOCKED` (only the App's status counts) and the merge is refused.
Clean up each: `gh pr close N --delete-branch`, then `git -C ~/src/djbclark-ade worktree remove ~/src/djbclark-ade-tmK-wt`.

E4. **Order**: E1, E2, merge the final PR, T0 without the ruleset (statuses appear), E5, T0's merge-state check, T1, T2.

E5. **The ruleset** (`bypass_actors` empty, so admins are held as branch protection holds them now):

```sh
cat > /tmp/ruleset.json <<'EOF'
{
  "name": "merge-gate",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "bypass_actors": [],
  "rules": [
    {"type": "required_status_checks",
     "parameters": {
       "strict_required_status_checks_policy": false,
       "do_not_enforce_on_create": false,
       "required_status_checks": [
         {"context": "adversary-marker", "integration_id": APP_ID},
         {"context": "pytest-linux", "integration_id": 15368},
         {"context": "context-policy", "integration_id": 15368}
       ]}}
  ]
}
EOF
sed -i.bak "s/APP_ID/<the App ID from E1>/" /tmp/ruleset.json      # GNU or BSD sed: -i.bak works on both
gh api -X POST repos/djbclark/djbclark-ade/rulesets --input /tmp/ruleset.json --jq '.id, .enforcement'
gh api repos/djbclark/djbclark-ade/rules/branches/master --jq '.[] | .type'
```

E6. **Branch protection**: left as it is (PR required, enforced for admins, since 2026-10-31); the ruleset only adds the
required checks, and both apply. If branch protection also lists required status checks today, remove them there once the
ruleset is verified, so one source names them:
`gh api repos/djbclark/djbclark-ade/branches/master/protection/required_status_checks --jq '.checks'` (404 = none). Moving the
PR rule into the ruleset (a `pull_request` rule) is optional and not needed.

## F. D9: the claim registry

F1. **Callers** (`grep -rn "ade_claims\|ade-git-guard claim" bin skills tools libexec .github`, 2026-11-06):
`bin/ade-git-guard` (runs `ade_claims.py guard`, `install`, now `list`); `libexec/git-hooks/pre-push` (`hook-push`) and
`libexec/git-hooks/reference-transaction` (`hook-ref`); comments only in `bin/acp-dispatch:824` and
`bin/claude_identity.py:2`. No caller of the CLI verbs `new`, `show`, `find`, `list` or `set-state` (the W2/W3 wiring that
would create claims was never built, `docs/git-guard.md` "Integration status").

F2. **Done**: `show`, `find` and `set-state` removed from the CLI (their library functions stay: the guard, the hooks and
the tests use them). `list` kept as the body of `ade-git-guard claim ls [--state active|released|merged|expired] [--json]`
(C5 fixed; the listing now ends with `expires_at`). `new` kept although nothing calls it: without it nothing can create a
claim, and it is the call a Paseo hook (F4) would make. **Expiry**: `new --ttl HOURS` (default 72, 0 never) stamps
`expires_at`; an active claim past it is `expired`, read and never written: `claim_state_active` is false, `list_claims
("active")` leaves it out (so `find_claim`, `claims_for_branch`, the hooks and the guard all treat the workspace as
unclaimed, and another owner may claim the path), `list` shows `expired`. Read with `.get`: a record with no `expires_at`
never expires, and one that does not parse keeps the claim active. `ade_claims.py`: 2,334 → 2,342 lines; `ade-git-guard` 158
→ 175. Tests: `test_cli_new_and_list` (was `..._show_find_list_set_state`), `test_ade_git_guard_claim_ls_lists_what_the_registry_holds`,
`test_an_expired_claim_guards_nothing_and_frees_its_path`, `test_expiry_is_read_with_get_...` (6 cases),
`test_ttl_sets_or_omits_the_expiry_...`; the schema test lists `expires_at`; the reclaim test's CLI exit-4 check uses `new`.

F3. **Not done, decided differently**: the brief's "KEEP owner + expiry + refuse-add/commit-in-a-foreign-workspace; delete
the rest" could also be read as narrowing the guard itself to add/commit in a foreign workspace, deleting shim rules 0
(fail closed on unknown options, hook-config), 2 (the shared checkout's destructive forms), 3 (linked-worktree stash) and 4
(worktree and rename targets) with most of `tests/test_ade_git_guard.py`. I did not: the brief's own parenthesis scopes
"the rest" to "the lifecycle verbs nothing calls" and keeps "a verb with a live caller", and `guard` has one (the shim);
those rules are what nine adversary rounds built, and AGENTS.md order 9's staged enforcement names exactly them. Dropping
them is a security decision for the operator, not a slimming one. If wanted, it is a follow-up slice: keep
`_ws_decision`'s foreign-workspace refusal and the hooks, delete `shared_destructive`, `_target_decision`,
`_template_decision`, `_redirect_decision` and the GitCall parser beyond what add/commit need (roughly 1,000 lines of
`ade_claims.py` and 1,000 of tests).

F4. **The plugin decision** (research wave3 item 4: a ~100-line Paseo plugin on `worktree.create.before/after`).
*For*: Paseo creates every agent worktree, so its hook is the one place that sees each workspace born with its owner (the
agent id), which is exactly the W2/W3 wiring that never happened; claims would exist for every Paseo worktree without any
launcher remembering to make one, and the release could follow the agent's archive instead of a TTL. *Against*: Paseo never
sees a `git` call, so the enforcement (the shim, the ref hooks) must stay in git whatever happens; a plugin would move only
creation and release into a second runtime (TypeScript in the daemon, against a 0.15.x plugin API this wave did not test),
the registry would still need the Python reader, and the daemon on the Mac is an operator-side install. *Recommendation*:
keep the registry and the enforcement in git and Python; when the wiring is built, make it a thin plugin hook whose only job
is to run `ade_claims.py new --ttl` on `worktree.create.after` (and, with a small `release` verb added back then, on
archive). Lifecycle in Paseo, enforcement in git; until then the TTL keeps orphaned claims from guarding forever.

## G. Operator steps

G1. **On the Mac, after the final merge** (CI cannot vouch for the installed version; the check is per version):
```sh
cd ~/src/djbclark-ade && bin/review-launch --check --mode review; echo "rc=$?"
bin/review-launch --check --mode read-only; echo "rc=$?"
cat ~/.local/state/review-launch/check-*.json | python3 -m json.tool | grep -E '"(status|outcome|claude_version)"|accepted'
```
Expected rc 0 both; paste the target table into `docs/slim/log.md`. A `claude-md readable` row is the accepted exposure
(record it); any other row not `refused` (or `absent`) is a failed boundary: do not use review-launch on that version.

G2. **The first real review** (any open PR of the operator's):
```sh
bin/review-pr N; echo "rc=$?"                  # prints the marker line; findings on stderr
#   paste the marker line into the PR body, then:
gh workflow run adversary-marker.yml -f pr=N
gh pr checks N --watch --required
```

G3. The App, the environment, the throwaway PRs and the ruleset: E1-E6, in E4's order. G4: delete the three throwaway
branches if `--delete-branch` did not. G5: the template note in K6.

## H. Reference edits in KEEP files (ruling 11)

H1. Edited: `bin/deadline_wait.py` (docstring: its one Python user is now `load-watch admit`), `tests/conftest.py`
(comment), `tests/test_deadline_wrappers.py` (the `pr-wait` kind removed; its cases run through `admit`, which shares
`deadline_wait.py`; `KINDS = ["admit", "dispatch"]`), `docs/deadline.md` (the example runs `gh pr checks --watch
--required`; the waiter row, the callers list and the known-gaps paragraph), `docs/dispatch-footer.md` item 20 ("the lead
reads CI": **the merger should check E6 did not also edit this line**), `docs/orchestration-practices.md:140`,
`docs/threat-model.md` 4.3 (the parser's new home; the Action is a control only once the ruleset lands),
`claude/agents/adversary.md` (the gate is the Action), `bin/ade-retro:151`, `bin/claude_identity.py:132,136` and
`tests/test_claude_identity.py:146`, `tests/test_deadline.py` (section headers that named review rounds "local-review
round N" now say "local Codex review round N").

H2. Left on purpose: `skills/bigteam/SKILL.md:753-795` (E6 deletes the file this wave); `docs/paseo-only-rearchitecture.md`
(149-181, 243: a dated plan of record, E11's docs list decides it); `docs/tui-lessons-learned.md:40,142` (C6 evidence).
`git grep` for the four banned words outside the exemptions now finds only those three files.

## I. Merger's lines (shared files this slice may not touch)

I1. `README.md:78` (the `bin/` row): drop the `local-review` and `pr-wait` entries; add `review-launch` (the review boundary,
`docs/review-boundary.md`), `review-pr` (rule 11's local review: prints the marker), `adversary_marker.py` (the merge
gate's parser and the Action's logic). `README.md:371`: "Adversary markers read by `bin/pr-wait`" → "read by
`bin/adversary_marker.py` (the `adversary-marker` Action)".

I2. `AGENTS.md` (E11's rewrite), the sentences that change: rule 1 ":213-216" "`pr-wait`'s report-only default is a property
of the *tool* … `adversary-required` label on the PR." (no report-only mode remains: the ruleset requires the status);
":217" "`pr-wait` reads that marker and reports it as `adversary` / `adversary_warnings`" → the Action reads it and posts
`adversary-marker`; ":228" "the two shapes `pr-wait` blanks" → "the parser blanks"; property 4 ":256" "`malformed` and
`adversary-fetch-failed` always block, with or without the opt-in" → "`malformed` and an unreadable PR always fail the
check"; the merge sentence gains `gh workflow run adversary-marker.yml -f pr=N` after a body edit and `gh pr checks N --watch
--required`; rule 9 ":309-311" "Check with `bin/pr-wait` … exit 124 means the enforcer stopped it" → per J8, Codex threads
are advisory: the lead reads them, nothing gates on them; rule 11 ":338-347" whole: the local review is `bin/review-pr`
(Claude through `review-launch --mode review`), exit 0/1/2/3/77/124, untrusted authors refused unless `--allow-untrusted`,
the marker printed for the body. The Code review section's "Readers" list loses `pr-wait`.

I3. `docs/queue.md:268-275, 539-563, 622, 2112` describe the waiter's follow-ups and history: mark them moot (the tool is
gone). `docs/skills.md`: no row names either tool. `CHANGELOG.md`: nothing (the fragment carries it).

I4. Fragment lines, in `changelog.d/claude-determined-maxwell-uvddaz.md` (`changelog-fold --check`: 56 fragments valid):
`### Added` review-launch, review-pr, the Action; `### Removed` pr-wait and local-review; `### Changed` the claims. Each ends
`(#0)`.

## J. Tests

J0. Environment: this container's `claude` (2.1.319) answers `claude -p` through the session's proxy (`apiKeySource:
none`), against the brief's "no claude login"; every test still runs against `tests/fixtures/fake-claude-review` and a fake
`gh`, and the live runs (A8) are evidence, not tests. No `gh` API call was made and nothing was posted.

J1. **Targeted** (brief section 4, in the worktree): `bin/pytest -q tests/test_review_launch.py tests/test_adversary_marker.py
tests/test_ade_claims_quote.py tests/test_ade_git_guard.py tests/test_acp_dispatch_load_gate.py tests/test_deadline_wrappers.py`
→ **12 failed, 3,265 passed, 1 skipped** (184 s), rc 1. The 12 are exactly the baseline's: the 10
`test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[...]` and the 2
`test_deadline_wrappers.py::...[dispatch]`. **New failures: none.** Also run: `tests/test_ade_git_hooks.py` and
`tests/test_claude_identity.py` beside the claims files: the 45 baseline hook failures, nothing new.

J2. **Full suite** (detached worktree `/tmp/w4e8-verify` at `bde841f`, the baseline's command: `uv run --with pytest --with
pytest-timeout --with pyyaml --with 'agent-client-protocol>=0.9,<1.0' python -m pytest tests/ -q --timeout=120`):
**70 failed, 7,197 passed, 30 skipped, 1,409 subtests passed in 1,140 s**, rc 1 (2026-11-07, while two sibling slices ran
their own full suites on the same machine). Against the baseline's 166: **no new failure**; every one of the 70 is in the
baseline list. 65 baseline rows no longer fail: they are files earlier slices deleted (`test_self_slash*`,
`test_bigteam_prune`, `test_ade_scan_state`, `test_session_relay`, `test_launch_turns`, this slice's `test_local_review`)
or tests that now pass on the slim branch (`test_acp_dispatch*`, not this slice's). Log: the lead can re-run the same
command; the comparison was made by matching the `FAILED` lines against `docs/slim/baseline.md`'s full list.

J3. New test files: `tests/test_review_launch.py` (100 cases: argv, settings, environment, refusals, `--head`, every init
and tripwire shape, exit 3 and 124, the descendant kill in the group and in a new session, the self-check's passing,
exposure-accepting, failing and inconclusive shapes and its cache key, and review-pr end to end against a bare origin and a
fake `gh`), `tests/test_adversary_marker.py` (2,559 moved + 48 new). Deleted: `tests/test_pr_wait.py` (0 baseline
failures), `tests/test_local_review.py` (6 baseline failures, all its kill tests). `.github/workflows/test.yml` lists no
test file, so nothing to remove there.

## K. Lost on purpose

K1. The waiter's **Codex gates** (J8, the operator's ruling): the head-anchored finding count, the unresolved-thread gate
(GraphQL `reviewThreads`), the `codex-review-state:v1` consistency check, the `@codex review` request and re-request with
its push-stamp and clock-skew machinery, the stuck-review detection, the per-head lock and request state. Codex findings
stay visible as threads; the lead reads them before merging; nothing enforces it. Also its `main()` tests (12, the polling
loop) and the two null-review tests.

K2. The **report-only default** and the `adversary-required` label: the ruleset makes the marker mandatory for every PR.

K3. The removed local review's **Codex run** (`codex review --base`), its transcript bindings (`workdir:`, `sandbox:
read-only`, the `exec` block), the P0-P3 finding parser, the generated-file filter and the refusal-wording list: the review
is Claude's now, its verdict structured output, its boundary proven by the init event instead of a transcript line.

K4. The **`--local-codex` flow** (`pr-wait --local-codex`, the head-named result file read by the waiter, the
`local-codex-*` blockers): review-pr's result file is a record for the lead, read by nothing.

K5. The local review's **load gate** (`load-watch admit --wait`, exit 75) and its one-run-per-head lock (exit 4):
review-pr has neither (a Claude review is a remote call, not local CPU; two concurrent runs for one head each make their own
worktree and file the same name, the later one wins).

K6. **Claims verbs removed**: `ade_claims.py show`, `find`, `set-state` (F2). Not removed: `new`, `list`, `guard`,
`install`, `hook-ref`, `hook-push`. The brief's "the template" (README rows and template are the merger's) needs nothing
from this slice.
