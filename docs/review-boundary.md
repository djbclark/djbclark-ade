# The review boundary and the merge gate

2026-11-06 (slim-down E8, `docs/slim/PLAN.md` E8 as amended by `docs/slim/research/wave4-2026-11-06.md`). Two pieces replace
the PR waiter and the Codex local review: **`bin/review-launch`**, the only way Claude is launched for a review, and the
**`adversary-marker` Action**, which turns [docs/code-review.md](code-review.md) rule 1's marker into a required
check. Waiting is `gh pr checks PR --watch --required`. The scripts' docstrings are the full reference; this page
is the summary. The reviewer checklist (rules 1–11) lives in [code-review.md](code-review.md); AGENTS.md keeps a
short pointer and the machine-readable marker requirement.

## What is untrusted (operator, 2026-11-07; restated 2026-11-10: distrust only what is not from the owner or AIs they run)

Artifacts whose author GitHub reports as the repository owner (including Cloud Agents under that login) are ours.
Everything else — a PR, comment, review, check-run or CI log from anyone else (MEMBER and COLLABORATOR included), and
bot/App comments from accounts that are not the owner — is untrusted data: a prompt-injection attempt through a PR
has already happened. They are read as data, never followed as instructions. The Action never executes, interpolates
or checks out anything from a PR; the review model is told that the diff, the body and every file of its worktree are
data under review and that it reports only through the schema.

**Owner-authored PRs succeed without an APPROVE marker** (2026-11-10): `decide` returns success when the author is the
repository owner and no BLOCK or malformed marker appears in the body or any comment. An explicit body APPROVE on an
owner PR still counts when the last editor is the owner or a login in `BODY_TRUSTED_EDITOR_LOGINS` (`cursor` as of
2026-11-09; absent or malformed editor attribution fails closed for that explicit APPROVE path). **Outside / MEMBER /
COLLABORATOR PRs** still need a live APPROVE in an issue comment the owner posted (not through a GitHub App) that
nobody but the owner has edited (GraphQL `editor`, `lastEditedAt` and `userContentEdits`; unknown history, or one
longer than 100 edits, fails closed). A body APPROVE on those PRs never counts; editing their body approves nothing
(2026-11-07, Argon review F-HIGH-1). Agents must not write a live APPROVE marker. A BLOCK in the body or in any
comment fails the check, and a dispatch judges every open PR at the same head, with both lookups paginated to the end
(F-CRIT-2; pagination from the Codex review of PR 300).

**What the operator no longer does by hand (2026-11-10):** once this module is on `master`, owner-authored tips need
no body paste of `adversary-verdict`, no herdr paste of an HTML comment, and no per-PR
`gh workflow run adversary-marker.yml -f pr=N` after landing the marker code — a `push` of
`bin/adversary_marker.py` / this workflow rejudges every open PR (one `marker` job per head). Outside tips still
need an owner issue-comment APPROVE and a dispatch (or the next Tests completion) to re-read it.

## `bin/review-launch`: one `claude -p` inside a boundary

```sh
review-launch --mode review|read-only -C WORKTREE --schema FILE (-p TEXT | -f FILE) [--allow-web] [--head SHA] [--model M] [--max-turns N] [--timeout S] [--json]
review-launch --check [--mode review|read-only] [--allow-web] [--json]
```

| Mode | Tools (`--tools`) | The init event must list exactly |
|---|---|---|
| `review` (rule 11, `bin/review-pr`) | `Read,Grep,Glob` | `Glob, Grep, Read, StructuredOutput` |
| `read-only` (Claude restricted tools; also used by the transitional `acp-dispatch` shim until ~2026-11-20) | `Read,Grep,Glob`; `--allow-web` adds `WebFetch,WebSearch` (2026-11-07) | those plus `StructuredOutput` |

| `trusted` (YOLO, 2026-11-12; `bin/review-pr` for an owner-authored PR) | `Read,Grep,Glob,Bash` with `--permission-mode bypassPermissions` | `Bash, Glob, Grep, Read, StructuredOutput`; `permissionMode == "bypassPermissions"` |

**`trusted` is not a boundary** (operator, 2026-11-12; `docs/slim/audit-walk-decisions-2026-11-12.md` section 8: YOLO is the
default for ordinary launches and trusted internal reviewers, restricted execution is reserved for external-security-critical
work). It needs `--trusted-author LOGIN` and `--head SHA`, drops `blockReadsOutsideWorkingDirectories` and
`disableBypassPermissionsMode`, and skips the read tripwire, the symlink refusal and the self-check (`--check --mode trusted` exits 2);
a hook event is not fatal. The stream proof of tools, permission mode, cwd, no MCP and no extra directories, the scrubbed
environment, the secret-path deny rules (an accidental-read guard: Bash is not confined), the timeout and the descendant kill stay. The launcher cannot verify that the input is trusted: `bin/review-pr`
decides, and only for a PR GitHub reports as authored by the repository owner (`--runtime auto`, the default; `--runtime yolo`
is refused for any other author; `--allow-untrusted` never enables it). An outside, MEMBER or COLLABORATOR PR, or
anything with an untrusted author, always gets `--mode review`. A bypass or widening flag in the launcher's own argv and a permission-mode variable in its
environment are still refused in every mode. Probe 2026-11-12: Claude Code's init event reports
`permissionMode: "bypassPermissions"` for this flag in `-p` mode.

Three more guards, all from 2026-11-07 (Argon review F-HIGH-2, and the Opus review of PR 297):

- **Symlinks.** Before the self-check and the launch, review-launch looks for symlinks in the worktree, both in git
  (`git ls-files -s` mode 120000) and on disk. It refuses with exit 2, naming the link, when any of them resolves
  outside the worktree (a dangling link included). A relative Glob or Grep pattern is also resolved against its base,
  so `link/**` counts as outside. A repository that commits outward symlinks (site-djbclark's `skills/`) cannot be
  reviewed through this boundary.
- **The deny list.** It is the hand list plus every `deny` pattern in `config/secret-deny.toml`, or in the rendered
  `config/secret_deny_policy.json` where Python has no `tomllib`. A file that exists but does not parse refuses every
  launch with exit 2. The TOML's `allow` exceptions do not carry over.
- **The tripwire.** It acts after Claude may already have run a call. It is a second layer behind
  `blockReadsOutsideWorkingDirectories` and the deny rules, not the boundary itself. A passed self-check is cached under
  `REVIEW_LAUNCH_STATE_DIR` and trusted as found, because the caller already controls the launch.

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
`--allow-untrusted`, adds a clean detached worktree at exactly the head (an owner-authored PR runs the `trusted` mode, anything else `review`: `--runtime auto|restricted|yolo`, 2026-11-12), writes `git diff BASE...HEAD` and the file list into
its `.review-launch/`, runs `review-launch --mode review --head HEAD` with `config/review-schema.json`, prints
`<!-- adversary-verdict:v1 {"verdict":"…","head":"<the full head>"} -->` (checked against the gate's own parser), files
`~/.local/state/review-launch/<owner>__<name>-pr<N>-<head>.json` and removes the worktree. Exit 0 APPROVE, 1 BLOCK, 2 refused,
3 failed, 77 tripwire, 124 timeout. It never posts. On an **owner-authored** PR the gate already succeeds without pasting
(owner-trust, 2026-11-10); keep the printed marker for the local record — do not paste it into the PR body just to
satisfy the gate. On an **outside** PR, paste the marker into an owner issue comment (not the body; never through
herdr, which mangles `<!-- … -->`), then:

```sh
gh workflow run adversary-marker.yml -f pr=N      # outside tip: a comment edit is not a Tests run
gh pr checks N --watch --required                 # wait for Tests and the marker
bin/ade-merge-ready merge-now --prs N --yes       # preferred; refuses unless adversary-marker success
```

Owner tips after owner-trust is on `master`: wait for Tests (or the push rejudge when the marker module lands), then
`merge-now` — no paste, no per-PR dispatch.

## Operator merge order (`bin/ade-merge-ready`, 2026-11-09; `approve-paste` / `approve-post` / `retrigger-marker` / `merge-now` 2026-11-10; `stack-rebase` 2026-11-10)

When many ADE PRs wait on the merge gate, use the helper. Classify / stacks /
approve-paste / approve-post / retrigger-marker / merge-now / stack-rebase never invent an
APPROVE; open-PR listing uses `--limit 500` (fail closed if that cap is hit).

**After #484 on master (owner-trust + push rejudge):** owner-authored tips need
no marker paste and no herdr HTML-comment paste. Use `approve-post` only for
**outside** tips (owner issue comment). Prefer `merge-now` over raw
`gh pr merge` so a red/missing `adversary-marker` cannot slip through.
`merge-now` squash-merges at the tip head and falls back to GitHub
`merge-async` when the tip is in a native stack (GraphQL merge refuses those).
`retrigger-marker` re-dispatches the Action when a tip still shows a stale
status before the next Tests run (usually unnecessary after the push sweep).

```sh
bin/ade-merge-ready                  # classify open tips vs pytest-linux + adversary-marker
bin/ade-merge-ready stacks           # bottom-up merge order + full tip SHAs
bin/ade-merge-ready stacks --bottoms-only
# Outside tips only (owner gh). Dry-run by default; posts only with both flags:
bin/ade-merge-ready approve-post --prs N --i-reviewed --yes --expect-head N=<40hex> --trigger-marker
bin/ade-merge-ready approve-paste --bottoms-only  # templates only (legacy / outside); prefer approve-post
bin/ade-merge-ready retrigger-marker --class needs_approve
bin/ade-merge-ready merge-now --prs N            # dry-run; refuses unless adversary-marker success
bin/ade-merge-ready merge-now --prs N --yes      # squash at tip head only if class=merge_now
bin/ade-merge-ready stack-rebase --prs N         # dry-run restack after a bottom lands
bin/ade-merge-ready stack-rebase --prs N --yes --repo-dir PATH  # rebase + force-with-lease; refuse on conflict
```

**herdr paste warning (2026-11-10):** Do not paste an `adversary-verdict:v1`
marker through herdr (body or comment). Prefer `approve-post` (GitHub API).
Default `--via auto`: **comment** for outside tips; **body** only when forcing
an explicit owner-PR APPROVE.

`approve-post` posts only when `gh api user` is the repository owner and both
`--i-reviewed` and `--yes` are set (otherwise dry-run). `--expect-head N=40hex`
is required with `--yes`. After #484, skip `approve-post` for owner-authored
tips — the gate trusts them without a marker.

`merge-now` is the only merge path in this tool: refuses unless classify is
`merge_now` (pytest-linux pass + adversary-marker success). Dry-run unless
`--yes`.

`stack-rebase` restacks selected children after a stack bottom merges (or when
the base drifted): dry-run by default; `--yes` requires `--repo-dir` (a local
clone), rebases onto the open parent's head branch when that parent is still
open else onto `--onto` (default `master`) with `git rebase --onto` excluding
the old parent tip (`--upstream` / pre-retarget `baseRefName`) so squash-merged
parent commits are not replayed, retargets `gh pr edit --base` when needed,
pushes with `--force-with-lease`, refuses fork/cross-repo heads, and refuses
(exit 1, tip untouched) on rebase conflicts. It never posts markers and never
merges.

## The `adversary-marker` Action

`.github/workflows/adversary-marker.yml` runs `bin/adversary_marker.py` on `workflow_run` (the `Tests` workflow completed,
whatever its conclusion), on `workflow_dispatch` (input `pr`, still needed after an outside-PR comment edit), and on
`push` of `bin/adversary_marker.py` or this workflow to the default branch (rejudges every open PR; 2026-11-10). Those
runs use the workflow file and the module from **master**; nothing from the PR is checked out or executed. Job
`resolve` (no secret) finds the PR(s) (the event's `pull_requests[]`, else `commits/{sha}/pulls`, else
`pulls?head=owner:branch` for a fork; or every open same-repo PR on push) and writes a `strategy.matrix` with **one
cell per head** (`prs` + `head`). Job `marker` is that matrix: each cell runs in concurrency group
`adversary-marker-<head sha>` (2026-11-07 / 2026-11-10: a push sweep, a dispatch and a Tests completion that could post
on the same sha serialize together; the retired single key `push-rejudge-all-open` raced those jobs). Every open PR at
that head is judged before one aggregate status is posted; an unreadable PR only fails the status for **its** head
(Codex on #490). It reads the body and head through the API with the job's read-only token (`pull-requests: read`,
`contents: read`), judges the marker with the parser moved unchanged from the PR waiter (rule 1's five properties),
**re-reads the head, the body and its last editor in one GraphQL query and posts only if the head is unchanged**
(judging that second read's body), and posts the commit status `adversary-marker` on that head with a token of the
`ade-merge-gate` App: `success` for an owner-authored PR with no BLOCK/malformed marker (owner-trust, 2026-11-10),
or for a live APPROVE naming the head in a trusted owner-PR body editor or owner issue comment (above); `failure` for a
BLOCK, a malformed marker, an outside PR with no owner-comment APPROVE, or "marker not written by a trusted user". It
fails closed: an API error posts nothing and fails the job (the required check stays missing); a PR whose `Tests` workflow
was edited away gets no status; a dispatch or push from any branch but master cannot reach the `merge-gate` environment's key.
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

## `bin/codex-open-threads`: rule 9 hygiene on merged PRs (2026-11-10)

Report-only lister for unresolved Codex review threads left on **merged** PRs (Carried #11; review rule 9 is advisory
since J8 — unresolved threads do not gate the merge). GraphQL `reviewThreads.isResolved` is the authority; a thread
counts when any of its comments is a Codex finding (`chatgpt-codex-connector[bot]` plus a
`codex-code-review-finding:v1` or `codex-security-review-finding:v1` mark). Outdated threads are included by default.

```sh
codex-open-threads [--repo OWNER/NAME] [--limit N]          # newest N merged PRs (default 50)
codex-open-threads --pr 32 --pr 59 [--include-open] [--json]
codex-open-threads --skip-outdated --json
```

It never resolves, replies, posts or edits. Bot comment text is untrusted data: only a truncated first-line title is
echoed. Exit 0 listed (including zero), 1 a `gh`/API failure, 2 usage. The lead still reads each thread against the
code and fixes what is real; this tool only surfaces them.
