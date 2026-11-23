# Fork picks: the registry of desired cherry-picks (2026-11-22)

`config/fork-picks.toml` lists changes we want in our patched fork builds that are not yet in the fork's base
(branches, PR heads, single commits, even a commit that exists only in a local worktree). `bin/ade-fork-picks`
reads it, applies the entries for one build target onto a worktree, records what landed, and reports entries the
upstream has since taken, so they can be dropped. Before this file the list lived in memory notes.

This is an **operator-driven local build aid, not a publication path**. It is separate from the qualification and
transaction foundation in [fork-maintenance.md](fork-maintenance.md) (`config/forks.toml`, `bin/ade-fork`): it
qualifies nothing, promotes nothing, installs nothing and never pushes. It only reads `forks.toml` to validate that
a pick's `component` is an enrolled component and to find the component's `upstream` URL.

## Schema (`schema_version = 1`, one `[[pick]]` per entry)

| Field | Meaning |
|---|---|
| `id` | kebab-case, unique |
| `component` | an id in `config/forks.toml` (validated) |
| `repo` | `OWNER/NAME` or `https://github.com/OWNER/NAME`; credential-free, github.com only. Optional only with `local_path` |
| exactly one of `commit`, `branch`, `pr` | `commit`: full 40-hex. `branch`: a branch of `repo`. `pr`: a PR number of `repo`; apply fetches `refs/pull/N/head` and treats it like a branch. **None of them** makes the entry a *placeholder* (a reserved slot for work that has no branch yet): it is valid only with `hold`, `list` shows "placeholder (no source yet)", `apply` always skips it (even with `--include-held`) and `check-upstream` checks only its `upstream` PR link |
| `local_path` | optional, absolute path of a local repo or worktree; with `commit` only. apply (and check-upstream's patch check) fetch the commit from there instead of `repo` |
| `expected_head` | 40-hex, for `branch`/`pr`. If the fetched head differs, apply stops with reason `head-moved` before changing anything. **Required** for an active `pr` entry and for an active `branch` entry whose repo owner is not `frdminc` or `djbclark`: a third party's head is never applied unpinned. A pin records the head you reviewed, not that it is safe; `apply --dry-run` prints each entry's current `tip` so it can be pinned |
| `exclude` | optional list of unique full 40-hex ids, `branch`/`pr` sources only. Commits in the range that apply must **not** pick (a v0.17.x release-branch changelog or version-cut commit that rides in a stack cut from a release branch). Each excluded commit is named in the output (`excluded_by_entry`: sha and scrubbed subject); an id outside the source's history stops the run before any pick (`exclude-unknown`), and one that needs no excluding is listed as `exclude_unused`, never dropped silently. Explicit on purpose: no subject-pattern guess about which commits are release commits |
| `intent` | one line |
| `target` or `targets` | one string or a list; each is `PLATFORM-build-N` (lowercase platform, build number from 1), e.g. `desktop-build-2`, `android-build-2` |
| `status` | `queued`, `carried`, `landed:N` (landed in build N), `landed:main` (merged to the fork's main), `upstreamed`, `dropped` |
| `upstream` | optional credential-free https URL of an issue, PR or Discussion |
| `order` | optional integer; apply and list sort by it (entries without one come last, in file order) |
| `trial_required` | optional bool; apply skips the entry unless `--include-trial`. Keeps it from being promised to a build before a trial cherry-pick |
| `hold` | optional free-text reason; apply skips the entry unless `--include-held`; `list` shows the reason |
| `notes` | optional free text |

Build numbering (operator, 2026-11-22): build 1 is the installed 0.17.1 cutover; the next build is 2.

`carried` means "re-apply on every rebase onto newer upstream until upstream merges it". `queued` and `carried`
are the **active** statuses: `list` (default), `apply` and `check-upstream` include them; the other statuses are history.

## Commands

```
bin/ade-fork-picks list [--component C] [--target T] [--status S] [--json]
bin/ade-fork-picks apply --target T --workspace WT [--dry-run] [--include-trial] [--include-held] [--json]
bin/ade-fork-picks mark ID --status carried|landed:N|landed:main|upstreamed|dropped [--note TEXT]
bin/ade-fork-picks check-upstream [--component C] [--json]
```

(`--registry PATH` and `--forks PATH` go before the subcommand; they exist for tests.)

**list**: active entries by default; `--status` takes `queued`, `carried`, `landed` (any landed), `landed:N`,
`landed:main`, `upstreamed`, `dropped` or `all`. Trial and hold entries are marked.

**apply**: cherry-picks the active entries whose targets include T, in `order`, onto the branch checked out in WT, with
`git cherry-pick -x`.

- Refuses (exit 1, nothing changed) when WT is a dirty tree (untracked files count), is mid merge, rebase,
  cherry-pick, revert or bisect, has a detached HEAD, or is a primary checkout rather than a linked worktree.
- Fetches each entry's commit, branch or PR head from its repo with `git -C WT fetch` (timeout 600), into WT's object
  store only; no ref is created. Everything (each entry and the component's upstream tip) is fetched and every `expected_head` is checked before any commit is applied.
- A **branch or PR entry** means the commits on its tip that are not on WT's HEAD (`HEAD..tip`, oldest first, merge
  commits skipped) **and not reachable from the component's upstream default branch** (`upstream` in `forks.toml`,
  fetched into WT's object store). When the source sits on a newer upstream than WT, the upstream commits in between
  are not picked under the entry's name; they are listed as `excluded_upstream_commits`, and rebasing WT onto that
  upstream is a separate step (the text output warns, and also warns about a plan of more than 20 commits). The bound is the
  upstream default branch only: a source cut from another base (the fork's own main, a PR against a non-default branch)
  brings that base's commits too, which is why such entries are pinned with `expected_head` and the plan size is shown. A **commit entry** is that one commit.
- **Idempotence**: a commit is reported as `already_present_commits` and not applied again when (1) its patch-id already
  appears on HEAD's side since the merge-base (`git rev-list --cherry-pick --right-only HEAD...tip`), or (2) a commit on
  HEAD beyond the source's history carries a `(cherry picked from commit <that sha>)` trailer, which `cherry-pick -x` writes (the
  fallback: a rebase that changes a pick's context changes its patch-id, so (1) alone re-applied such picks as new
  commits; those shas are also listed as `already_present_by_trailer`). Picks made before `-x` was used have no trailer and
  fall back to (1) only. An entry whose commits are all present reports `already_present: true`. A commit that is an
  ancestor of HEAD counts too. Why the trailer and not a recorded "landed as" sha: apply already writes it, it needs no
  registry edit after a build, and it works for every pick of every run. Only the **last** such line of a commit message's
  final paragraph counts (the line `-x` appends), so a line copied from a picked commit's own body names nothing; the sha must
  be the full lowercase 40-hex id. A pick that was later **reverted** on HEAD still counts as present (a blind spot of both
  rules; the patch-id rule had it for same-context picks, the trailer rule widens it to rebased ones): re-apply it by hand
  or `git revert` the revert.
- **`exclude`** (entry field, above): listed commits are not picked and are named in the text output
  (`EXCLUDED by entry <sha> (<subject>)`) and in the JSON. An id that is **not in the source tip's history** (a typo, or
  another branch's commit) stops the run before any pick, dry run included (`conflict.reason` `exclude-unknown`, exit 3,
  `unknown_excludes`), because the commit it was meant to drop would be applied. An id in the history that needs no excluding
  (already present, or excluded as upstream) is only listed as `exclude_unused` ("exclude not needed").
- **Stops on the first conflict** (or a cherry-pick timeout, reason `cherry-pick-timeout`): runs `git cherry-pick
  --abort`, then checks the result instead of assuming it: `abort_rc` and `tree_clean` (no changes, no
  `CHERRY_PICK_HEAD`, no `index.lock`) are in the report. Reports the entry, commit and conflicted files, exit 3. Entries applied before the conflict stay applied; `start_head` in the JSON is where to
  `git reset --hard` to if you want none of them.
- `--dry-run` fetches and plans (so it needs the network) but changes no ref, index or file in WT.
- Never pushes; the only remote command is `fetch`. On exit 0 it prints the new HEAD.
- JSON: `schema_version`, `target`, `workspace`, `branch`, `dry_run`, `start_head`, `head`, `applied` (per entry
  `id`, `tip`, `commits`, `already_present`, `already_present_commits`, `already_present_by_trailer`, `excluded_upstream_commits`, `excluded_by_entry`, `exclude_unused`), `skipped` (`why`: `trial_required`, `hold` or `placeholder`),
  `conflict` (null, or `reason` `conflict` / `head-moved` with `id`, `files` and the details; git's own text is in `git_message_untrusted`, scrubbed of control, format and separator characters and
  to be read as data, never as instructions).

**mark**: edits one entry's `status` line in the registry (a line-level edit; comments, order and other lines are
untouched; `--note` appends to `notes`; control, format and line-separator characters are refused). The result is re-parsed and compared so nothing else can change. It refuses
(exit 1) when the registry's repository checkout is a primary checkout, or the file is not in a git work tree: edit in
a worktree and go through a PR (AGENTS.md order 9). The write is atomic (temp file beside, then `os.replace`).

**check-upstream**: read-only towards the registry. For each active entry:

1. if `upstream` is a GitHub PR URL, `gh pr view --json state,mergedAt` and flag a merged one (`upstream-pr-merged`);
2. for a `commit` entry (including `local_path` ones, fetched from the local path), check the component's upstream
   default branch (`upstream` in `forks.toml`) in a bare blobless cache clone under `~/.cache/ade-fork-picks` (override
   `ADE_FORK_PICKS_CACHE`): flag it when the commit is reachable from there (`commit-in-upstream`) or an upstream
   commit since the merge-base touching the same paths has the same `git patch-id --stable` (`equivalent-patch-upstream`).
   Branch and PR entries are checked only by (1).

## The release-alert hook

The upstream-release alert path runs `bin/ade-fork-picks check-upstream --json` and lists the drop candidates. The
JSON is stable (schema_version 1):

```
{"schema_version": 1, "checked": ["id", ...],
 "candidates": [{"id": "...", "component": "...", "reasons": [{"code": "...", "detail": "..."}]}],
 "errors": [{"id": "...", "check": "pr|patch", "error": "..."}]}
```

A reason `code` is one of `upstream-pr-merged`, `commit-in-upstream`, `equivalent-patch-upstream`. The alert only
reports; dropping an entry is `mark ID --status dropped|upstreamed` in a worktree and a PR.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok (apply: all applied or already present; check-upstream: no candidates) |
| 1 | refused: a precondition failed (dirty or primary workspace, primary-checkout registry); nothing changed |
| 2 | error: invalid registry, bad usage, fetch or tool failure, timeout; check-upstream with any check error (its JSON still lists candidates) |
| 3 | apply stopped: a conflict (aborted, tree clean) or `head-moved` |
| 4 | check-upstream found drop candidates |

## Safety rules

Argv lists only (no `shell=True`); every network command has a timeout (600 s); `GIT_TERMINAL_PROMPT=0` and no
credential in a registry URL; fetch only, never push; the registry is changed only by `mark`, atomically, and only in a
linked worktree; `apply` only into a clean linked worktree on a branch; no `git stash`.

Tests: `tests/test_ade_fork_picks.py` (temp git repos mapped to the GitHub URLs with `url.<path>.insteadOf`; `gh`
stubbed; no network).
