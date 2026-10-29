# CI waiver

Summary (2026-10-28; repaired 2026-10-29): trusted master code mechanically classifies narrow CI waivers. A waiver changes the waiter report; the operator's pinned merge yes remains the authority.

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
API's master, base and head SHAs, then the merge parents and any H0 run-base SHA,
from the explicit GitHub HTTPS URL. Every SHA must be a full commit SHA and each
fetch must resolve to exactly that SHA, even when history already supplied the
object. All diffs, ancestry, workflow-blob reads and `merge-tree` use this store.
There are no alternates or templates. `GIT_*` is stripped before installing
known isolation settings; replacements and grafts are disabled, as are
`core.commitGraph`, `gc.writeCommitGraph` and `fetch.writeCommitGraph`. Any fetch
failure denies classification; it never falls back to checkout evidence.

`classify --repo-dir /ABS/REPO --base REF --head REF --json` is a separate offline
fixture mode which reads that repository, refuses `info/grafts`, disables
replacement objects/commit graphs and cannot certify master-merge without PR
history. `--pr` and `--base/--head` are mutually exclusive; `pr-wait` only invokes
`--pr` in a private directory, never offline mode. Output contains `class`,
`reasons` and the full classified `head`. Both online classes require base ref
master, a base SHA ancestral to current master and no `base_ref_changed` timeline
event. A stale/non-master API base fails closed before docs-only classification.

Trust remains in GitHub's API responses, `gh`, the runner's Git binary and its
HTTPS trust environment. A malicious executable shim or compromised GitHub/API
can corrupt that anchor. This isolates local checkout state; it does not
authenticate executables or GitHub, or the author-controlled reviewer identity.

A2. `docs-only` requires a nonempty diff containing only `WAIVABLE_PATHS`:
`CHANGELOG.md` and `docs/handoffs/**`. The diff is from the merge base to the head,
with rename detection disabled so both sides of a rename are examined. The
allowlist and workflow `paths-ignore` entries must stay identical. Allowlist matching
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
`conftest.py`, `test_*.py`, files named `pyproject.toml`, `pytest.ini`, `setup.cfg`,
`tox.ini`, `uv.lock` or `requirements*.txt` at any depth, and the explicit
`claude/hooks/handoff-tools/tests/` tree (also covered by nested `tests/`). Only exclusions are NFC-normalized and case-folded (with slash/path normalization); absolute and parent-traversing paths are rejected.
There is no blanket exclusion for other configuration files: they still need
the class proof. Waivable files must be ordinary nonexecutable files; symlinks, gitlinks and executable/mode
changes are rejected. Regular file additions and deletions remain allowed.

A4. `master-merge` requires exactly two parents: former PR head H0 first and
master commit T second. H0 must occur in this PR's commit list AND have a
`test.yml` pull-request run associated with this PR whose `pull_requests` entry
names base ref `master` and supplies a nonempty base SHA ancestral to current
master. A `base_ref_changed` event anywhere in the PR's timeline refuses either
class. There is no force-push/synchronize timeline fallback; a push run alone does not prove PR history. Both parents' runs must
name exactly `.github/workflows/test.yml`, and that file in each run's `head_sha`
tree must equal the file at current master. Missing workflow objects fail closed.
The latest matching `test.yml` run/attempt on exactly H0 must be
completed/successful, with a nonempty job list whose EVERY job is completed with
conclusion `success`. Skipped, neutral, pending, workflow-dispatch, commit statuses
and unrelated bot checks cannot establish greenness. T must be an ancestor of current master
and have a latest completed successful `test.yml` push run on master, with every
job successful too. Earlier success cannot hide a failed rerun.

The online machine merge runs in the same private GitHub-fetched bare store,
without alternates, worktree, `info/attributes` or checkout merge-driver config.
System/global/environment Git attributes and configuration are disabled;
`--attr-source=<empty tree>` plus `-c core.attributesFile=/dev/null` ignores committed
attributes too. Unsupported Git refuses rather than falling back. These tests run
on both workflow platforms; local evidence is Git 2.56.0 on macOS (2026-10-29),
while Linux execution must be checked in CI. Every nonwaivable path must match the
machine tree, including modes/deletions. Nonwaivable conflicts are rejected even
when the head committed the exact conflict-marker blob. Only allowlisted text
files may be hand-resolved.

A5. Everything else is `none`: examples include `touches-nonwaivable:code.py`,
`not-a-merge`, `h0-not-green`, `master-not-green`, `hand-edited:code.py`, and
`shallow-history`. Missing objects, unreadable checks and any Git/GitHub error
deny a waiver. Online classification fetches only into its private store; offline
mode uses its given repository and a temporary alternate-backed merge store. Neither
mode edits a worktree or cancels a CI run. `merge-tree` writes only temporary
objects. Exit 0 means a classification was printed,
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

## C. Workflow filtering and the master backstop

C1. Both push and pull-request triggers ignore exactly the allowlist. GitHub
[documents that all matching paths suppress the workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-excluding-paths).
No test job is started for such a PR; an externally required check may remain
Pending. The waiver handles pending and absent checks; absence never proves a
waiver. The classifier still denies workflow/test/waiver machinery changes.

C2. `push.branches: [master]` remains, and full CI still runs after a master-merge
whose squash changes nonignored paths. This post-merge backstop, with red runs
reported by existing fleet notices, is why master-merge waivers are acceptable.
When T is older than the current master tip, squash-merging combines the topic
with newer master changes and yields a tree neither H0 nor T tested. The classifier
proves the parent combination and machine merge, not that final squash tree.
The operator's exact-head pinned yes accepts this stale-parent semantic-merge
risk after reading the independent report and the current check results; it does
not certify the final squash tree as pretested. The post-merge push run is the
backstop, subject to the path-filter limits below.
**Design defect in the original wording:** push `paths-ignore` necessarily also
skips docs-only merges on master, so it cannot run on *every* merged commit.
The implementation preserves the explicitly requested filters and branch
trigger; it does not claim an unconditional master run. Fleet reporting itself
is unchanged and was not live-verified in this slice.

C3. Never use `[skip ci]` to request a waiver: a squash merge can copy commit
messages into its body, accidentally skipping the master push backstop as well.
Use the marker instead. GitHub documents [commit-message skip behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
The authorized merger supplies an explicit clean subject/body, after reading
the review gates and rechecking checks immediately beforehand:

```sh
gh pr checks N
gh pr merge N --squash --match-head-commit REVIEWED_FULL_SHA --subject 'Describe the reviewed change' --body 'Describe the reviewed change and validation.'
```

C4. This implementation PR cannot waive itself: it changes hard-excluded paths.
The lead obtains the independent adversary verdict before opening the PR,
replaces the changelog's `(#NNN)` placeholder, and verifies the hosted
Linux/macOS runs before merging.

C5. GitHub documents a [300-file path-filter limit](https://docs.github.com/en/enterprise-server@3.19/actions/reference/workflows-and-actions/workflow-syntax#git-diff-comparisons).
Code outside the first 300 matches can therefore
leave the workflow skipped (inference from that limit, not exercised live here).
The classifier inspects the complete Git diff and still denies such a mixed PR;
the master push backstop itself can be skipped. It is not unconditional.

C6. A docs-only master tip has no `test.yml` push run. Merging that tip as T fails
`master-not-green` until a later code commit has a green master push run. This is
an intentional availability loss, not permission to use a workflow-dispatch run.

C7. PRs targeting a branch other than master fail `base-not-master`, including
docs-only PRs. Missing historical evidence, unsupported attributes isolation or
unreadable job evidence fail closed too.
