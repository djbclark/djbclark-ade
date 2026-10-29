# CI waiver

Summary (2026-10-28; repaired 2026-10-29, cut to `docs-only` the same day): trusted master code mechanically classifies one narrow CI waiver class, `docs-only`. A merge of master is not waived (A4). A waiver changes the waiter report; the operator's pinned merge yes remains the authority.

## A. Classification and evidence

A1. The waiver decision is valid only from a `pr-wait` byte-identical to GitHub's
master snapshot. For every present marker it reads the full SHA from
`gh api --hostname github.com repos/OWNER/REPO/branches/master`, using the PR's
repository argument. It fetches exactly that SHA from
`https://github.com/OWNER/REPO.git` into a fresh private bare Git directory,
with system/global/inherited Git configuration disabled, empty templates,
disabled hooks and only HTTPS transport allowed. The checkout is never used as
Git cwd or as an object directory; its remote/URL config, objects, pack indexes,
commit graphs, alternates and replace refs cannot supply evidence. No checkout
refs or objects are changed. The resolved commit must equal the API SHA.
Both `bin/pr-wait` and `bin/ci-waiver` are read from that same commit; the waiter
must match its own bytes. The classifier runs with `python -I` in the private
temporary directory. Failure is `ci-waiver-untrusted-tool`. No PR-owned Python
helper is imported. Before the initial waiver machinery lands on master,
waivers fail closed; this PR cannot waive itself. Concurrent local tracking-ref
updates cannot select or mix master versions. An intentionally rewritten waiter
could omit its own self-check: the operator must select a trusted master-identical
copy before relying on its report.

For manual inspection use the trusted classifier's
`classify --repo-dir /ABS/REPO --pr N --repo OWNER/NAME --json`. Online PR mode
ignores `repo-dir`: it creates another fresh private bare store and fetches the
API's master, base and head SHAs from the explicit GitHub HTTPS URL. Every SHA
must be a full commit SHA and each fetch must resolve to exactly that SHA, even
when history already supplied the object. All diffs and ancestry use this store.
There are no alternates or templates. `GIT_*` is stripped before installing
known isolation settings; replacements and grafts are disabled, as are
`core.commitGraph`, `gc.writeCommitGraph` and `fetch.writeCommitGraph`. Any fetch
failure denies classification; it never falls back to checkout evidence.

`classify --repo-dir /ABS/REPO --base REF --head REF --json` is a separate offline
fixture mode which reads that repository, refuses `info/grafts` and disables
replacement objects/commit graphs. `--pr` and `--base/--head` are mutually
exclusive; `pr-wait` only invokes `--pr` in a private directory, never offline
mode. Output contains `class`, `reasons`, the full classified `head` and `master`
(the fetched current master SHA online, null offline); a successful proof also
contains `merge_tree`, the prospective tree against that master or explicit offline base.
`pr-wait` carries these unchanged in `ci_waiver.classification`. Online
classification requires base ref master, a base SHA ancestral to current master
and none of the timeline events `base_ref_changed`, `base_ref_deleted` or
`automatic_base_change_succeeded` (GitHub records a retarget under any of them;
other or future event names are not recognized). The timeline is read through all
pages. A non-master base ref or off-master base SHA fails closed. A stale ancestor
base is accepted, but all classification checks run against both it and fetched
current master; either failure refuses the waiver.

Trust remains in GitHub's API responses, `gh`, the runner's Git binary and its
HTTPS trust environment. A malicious executable shim or compromised GitHub/API
can corrupt that anchor. This isolates local checkout state; it does not
authenticate executables or GitHub, or the author-controlled reviewer identity.

A2. `docs-only` requires a nonempty diff containing only `WAIVABLE_PATHS`:
`CHANGELOG.md` and `docs/handoffs/**`. Online, run the following checks for both
the API base and fetched current master; offline, use only the explicit base.
`git merge-base --all base head` must return
exactly one ancestor; multiple bases are `multiple-merge-bases`. Before path checks,
any merge commit in `git rev-list --min-parents=2 ancestor..head` refuses the waiver
as `merge-in-pr-history`, even below a linear docs-only tip. Merges already shared
by base and head are outside that range and do not by themselves refuse a waiver.
The diff is from that unique ancestor to head, with rename detection disabled so
both sides of a rename are examined. A candidate must also have a clean
`git merge-tree --write-tree base head` result; its nonempty tree diff against base
must pass the same allowlist, hard exclusions and file-mode checks. Conflicts or
an unsafe result are `merge-result-not-docs-only`; Git errors also deny a waiver.
Online these operations run in the private store; offline they use the fixture repo.
Before these proofs, online mode also refuses `master-touched-pr-paths` when
any path in the API base-to-head diff was renamed (either endpoint), deleted or
had its mode changed on API base..master. This is deliberately blunt: even a
benign docs-to-docs rename or chmod denies the waiver. Ordinary content changes
on master still undergo the clean merge-tree proof. This is an endpoint diff,
not an audit of intermediate changes later undone on master. The allowlist and
workflow `paths-ignore` entries must stay identical. Allowlist matching
is exact and case-sensitive without Unicode/path normalization; `changelog.md`,
`Docs/Handoffs/` and casefold-equivalent Unicode paths do not qualify.

| Path | Read audit, 2026-10-28 | Why waivable |
|---|---|---|
| `CHANGELOG.md` | Searched every file in `tests/`, `.github/workflows/` and `bin/` for `CHANGELOG` and inspected the hits. `bin/ade-update:173` reads committed changelogs to display new entries. `tests/test_ade_update.py:110,124` writes and reads `CHANGELOG_V1/V2` in freshly created fixture repos, never this repository's changelog. The relay test's mention is a docstring. No workflow reads it. | Informational release text; changing the real file cannot affect these tests' fixture changelogs. The updater displays content rather than executes it. |
| `docs/handoffs/**` | Same exhaustive search for `docs/handoffs` found only `bin/ade-scan-state-doc`'s static explanatory text. Tests and workflows do not read this tree. Also inspected the generic GNU-tool scanner: `bin/gnu-tools-check` explicitly excludes `*/handoffs/*`; its tests create their own fixture files. | Historical handoff records, with no executable/test input consumer found. |

A3. Reproduce the audit with `rg -n 'CHANGELOG|docs/handoffs' tests/ .github/workflows/ bin/`;
inspect consumers rather than treating all mentions as reads. Fixtures containing a
file of the same name do not read the repository's actual file. Re-audit before
expanding the allowlist or adding a consumer. Other `docs/*.md`, `skills/**` and
`AGENTS.md` are outside the allowlist. Hard exclusions always deny a waiver:
`.github/**`, `config/**`, `bin/pr-wait`, `bin/ci-waiver`, every `.git*`
control component (including nested attributes/modules files), all nested `tests/`,
`conftest.py`, `test_*.py`, files named `pyproject.toml`, `pytest.ini`, `.pytest.ini`,
`pytest.toml`, `.pytest.toml`, `setup.cfg`, `tox.ini`, `uv.lock`, `uv.toml` or
`requirements*.txt` at any depth; root `pytest.py`, `pytest/`, `_pytest/`; and the explicit
`claude/hooks/handoff-tools/tests/` tree (also covered by nested `tests/`). Only exclusions are NFC-normalized and case-folded (with slash/path normalization); absolute and parent-traversing paths are rejected.
This open-ended denylist is an additional fence over the entire PR diff, not the
safety proof: every changed path must also match `WAIVABLE_PATHS` positively, so an
omitted configuration name cannot authorize a change.
There is no blanket configuration exclusion. Waivable files must be ordinary nonexecutable files; symlinks, gitlinks and executable/mode
changes are rejected. Regular file additions and deletions remain allowed.

A4. **Why not master-merge (2026-10-29).** An earlier design also waived a
`master-merge` class: a merge commit of the PR's former head H0 and a master commit
T, waived when both parents had green CI and the merge equalled Git's machine merge.
It was removed after five independent adversary rounds, each finding a new HIGH in
the one part the repository cannot check itself, the provenance of the earlier
green run:

1. Round 1: H0's "green" could be forged (a workflow-dispatch run that skipped
   the tests, a posted commit status, an unrelated bot check) and was not tied
   to this PR's history.
2. Round 2: a green run could belong to a different base whose `test.yml` the
   attacker controls.
3. Round 4: a workflow run's `pull_requests[]` is recomputed from the current
   PRs of that head branch, not from the triggering event, so a run borrowed from
   another PR against another base passed.
4. Round 5: the "no retarget" evidence checked only `base_ref_changed`; GitHub's
   automatic retarget of a stacked PR records `base_ref_deleted` plus
   `automatic_base_change_succeeded`, so a borrowed run passed again.

(Round 3's HIGH, a forged local commit graph, was an isolation hole shared by both
classes; it is fixed by the private GitHub-fetched store of A1, which docs-only
keeps.) The common cause is that GitHub's API exposes current metadata, not an
immutable record of what a run tested, so the provenance of an earlier green run
cannot be proven from the API alone and the set of ways to forge it is open-ended.
Round 6 then found a criss-cross hole in the docs-only classifier itself: two
incomparable merge bases let Git's single chosen base show only docs while the
clean virtual-base merge reverted code and tests. A2 now refuses multiple merge
bases and any merge in the PR's own `ancestor..head` history before checking paths,
and separately validates the clean merge-tree result against API base and current master. A merge of
master therefore keeps ordinary CI even when its chosen-base diff contains only
docs (`merge-in-pr-history`, or `multiple-merge-bases` when applicable).
The removed master-merge code and its tests
remain in this PR's history (head `72dad2aa`) if a stronger provenance source,
such as an immutable run record, ever makes the class worth revisiting.

A5. Everything else is `none`: examples include `touches-nonwaivable:code.py`,
`multiple-merge-bases`, `merge-in-pr-history`, `merge-result-not-docs-only`,
`master-touched-pr-paths`, `no-changes`, `pr-base-retargeted`,
`base-not-on-master` and `shallow-history`. Missing objects, unreadable evidence
and any Git/GitHub error deny a waiver. Online classification fetches only into
its private store; offline mode uses its given repository. Neither mode edits a
worktree or cancels a CI run. Exit 0 means a classification was printed,
including `none`; exit 2 means invalid usage. Consumers must check the class.

## B. Independent review and waiter behavior

B1. The author obtains an independent adversary review of the exact head from
`omp --model anthropic/claude-opus-5-5 --effort high` or stronger. An agent able
to request a waiver may never approve its own work. The code cannot authenticate
this: agents share one GitHub account and the body is author-controlled. It only
rejects identical `reviewer`/optional `author` strings (trimmed and case-folded)
and unknown keys. Omitting or lying about `author` can bypass that comparison.
The optional report hash was deliberately omitted: an author can compute the
same hash, so it adds no authentication. The operator's pinned merge yes, after
reading the actual independent report, is the authority; a waiver only changes
what `pr-wait` reports. The PR body needs BOTH live
markers (replace placeholders; the classifier, not the reviewer, chooses class):

```text
<!-- ci-waiver:v1 {"class":"docs-only","head":"<40-hex>","reviewer":"<independent agent id>"} -->
<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->
```

B2. For each present marker `pr-wait` verifies trusted master code and reclassifies
the current head. Waiver markers inside fences, inline code (including multiline
spans), blockquotes/lazy continuations or indented blocks are malformed, not live.
The same strict live-text reading is required of the adversary APPROVE used by a
waiver: quoted, indented or multiline-code approvals do not count. The ordinary
adversary report retains its documented legacy limits, and a same-head BLOCK
still wins anywhere in the raw body. Balanced JSON boundaries and duplicate-key checks
are shared; partially masked JSON is malformed. The only keys are `class`, `head`,
`reviewer`, and optional `author`. Unknown keys, wrong version, invalid class,
shortened head, empty reviewer or equal reviewer/author are `ci-waiver-malformed`.
Different full head/class or denied classification is `ci-waiver-mismatch`;
missing current-head live APPROVE is `ci-waiver-needs-adversary`. Malformed always
blocks, even beside a valid marker. Untrusted or unavailable tooling blocks with
`ci-waiver-untrusted-tool`.
Fenced waiver templates in a PR body are malformed too; keep format examples
in repository documentation rather than the PR body.

B3. A valid waiver sets `ci_state` and `ci.state` to `waived` and immediately
satisfies the CI wait, including pending or absent checks. No failed check is
waived. Without a waiver, `ci-pending`, `no-checks`, and `ci-none-succeeded`
remain unchanged. Waivers imply adversary-required. Codex/security review and
unresolved-finding gates remain in force. `pr-wait`'s exit codes are unchanged;
read `merge_ready` and `merge_blockers` before merging. This is a point-in-time
report: the merger must recheck `gh pr checks` immediately before merging, refuse
any new red check and obtain the operator's yes pinned to this exact head.

## C. Workflow filtering and the master push run

C1. Both push and pull-request triggers ignore exactly the allowlist. GitHub
[documents that all matching paths suppress the workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-excluding-paths).
No test job is started for such a PR; an externally required check may remain
Pending. The waiver handles pending and absent checks; absence never proves a
waiver. The classifier still denies workflow/test/waiver machinery changes.

C2. `push.branches: [master]` remains. Push `paths-ignore` necessarily also skips
docs-only merges on master, so master's push CI does not run on *every* merged
commit; the filters match the requested allowlist and nothing claims an
unconditional master run. The classifier checks the unique-ancestor PR diff and clean merge-tree result
against both API base and fetched current master for allowlisted paths, hard
exclusions and safe modes. It reports the master SHA it proved; this alone
cannot prove a bypassing caller's eventual merge or workflow filtering decision.
The merge wrapper below verifies the actual commit after merge. Fleet reporting
was not live-verified in this slice.

C3. Never use `[skip ci]` to request a waiver: a squash merge can copy commit
messages into its body, accidentally skipping the master push backstop as well.
Use the marker instead. GitHub documents [commit-message skip behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
For `ci_state: waived`, the authorized merger MUST use ONLY a trusted master-identical
wrapper after the operator's yes pinned to the reviewed full head (2026-10-29):

```sh
bin/ci-waiver merge N --head REVIEWED_FULL_SHA --repo OWNER/NAME
```

Never use `gh pr merge` for a waived PR. Ordinary PRs keep
`gh pr merge --squash --match-head-commit SHA`. This wrapper-only rule is procedural:
**nothing enforces it; bypassing the wrapper does not prevent the master race.**

The wrapper fetches master into a private store, requires its own bytes to match
`bin/ci-waiver` there, and executes that master's `bin/pr-wait` with `--no-request`,
`--timeout 0`, `--ci-grace 0` and the pinned head. This single poll posts no review
request. It requires a successful waiter exit, `merge_ready: true` and a valid
current-head docs-only marker and classification. Codex, open-finding, independent
adversary and failed-check gates still apply. It reclassifies against fresh master,
requires docs-only and the same head, and checks its bytes against that master too.
It recreates the merge-tree in its own private store and requires the same proof.
It rechecks `gh pr checks` before writing (pending/absent may be waived; failed,
cancelled or unknown checks refuse). Exit 1 is accepted only with separately empty
exact-head check-runs and status API lists.

It creates `git commit-tree MERGE_TREE -p PROVED_MASTER -p REVIEWED_HEAD` with the
caller's Git author/committer identity and message `Merge reviewed docs-only PR N`
plus `Reviewed head SHA`, avoiding PR text and `[skip ci]`. **Waived PRs land as
merge commits, not squashes**: the exact proved tree is pushed directly and the
second parent makes the reviewed head reachable so GitHub marks the PR merged.
Immediately before pushing it requires the API PR to remain open, unmerged, on
master and at the reviewed head. It pushes once to the explicit GitHub HTTPS URL
as `COMMIT:refs/heads/master`, with no force or force-with-lease, authenticating
through `gh auth git-credential` (no token in argv).

**The fast-forward-only push PREVENTS the master race on the wrapper path.** If
master advances incompatibly after proof, Git rejects the push; nothing lands and
`merge-race-lost` tells the operator to re-run. A benign intervening master advance
is rejected by the push too; the post-push parent check does not reject a benign
race after landing. It is a verification formality, requiring parents exactly
`[proved master, reviewed head]`, the proved tree and a nonempty safe allowlisted
first-parent diff. Parent mismatches report actual first-parent paths.

After a successful push, GitHub's API must report `merged: true` with exactly the
created commit and unchanged head/base. The wrapper queries at most five times,
one second apart, to allow marking delay; it NEVER pushes again. An identity
mismatch, unknown write result, marking delay beyond the bound or transient fetch
failure exits 1 with inspect-only `gh pr view` and read-only recovery commands:

```sh
bin/ci-waiver verify N --sha LANDED_FULL_SHA --repo OWNER/NAME
```

`verify` checks PR merge identity and master ancestry, reconstructs the docs-only
proof from the landed parents, and checks the actual commit. It does not merge,
push or request reviews. Only a **proved mismatch of a commit on master** prints
`REVERT: SHA`. Retargets do not print a revert recipe. Recovery fetches master,
requires `git merge-base --is-ancestor SHA origin/master` (STOP if nonzero), starts
`git switch -c BRANCH origin/master`, then runs `git revert -m1 SHA`; the printed
push and revert PR commands require manual execution in a clean claimed workspace.
The wrapper never reverts or pushes a revert automatically. A write error gets a
re-verify hint, never REVERT merely because a command failed. Exit 0 for merge or
verify means the actual merge was verified, not that later master pushes or
workflow filtering were proved. Classifier exit 0 only means it printed a
classification, including `none`.

C4. This implementation PR cannot waive itself: it changes hard-excluded paths.
The lead obtains the independent adversary verdict before opening the PR,
replaces the changelog's `(#NNN)` placeholder, and verifies the hosted
Linux runs before merging (macOS only when requested by name).

C5. GitHub documents a [300-file path-filter limit](https://docs.github.com/en/enterprise-server@3.19/actions/reference/workflows-and-actions/workflow-syntax#git-diff-comparisons).
Code outside the first 300 matches can therefore
leave the workflow skipped (inference from that limit, not exercised live here).
The classifier inspects the complete Git diff and still denies such a mixed PR;
the master push backstop itself can be skipped. It is not unconditional.

C6. PRs targeting a branch other than master fail `base-not-master`, including
docs-only PRs. Missing evidence, unreadable timeline or branch responses and any
Git or `gh` error fail closed too.
