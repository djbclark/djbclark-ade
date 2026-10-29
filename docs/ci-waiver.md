# CI waiver

Summary (2026-10-28): `bin/ci-waiver` mechanically proves narrow CI waivers; an independent adversary's exact-head review substitutes for pending or absent CI.

## A. Classification and evidence

A1. Run `bin/ci-waiver classify --pr N --repo OWNER/NAME --json` from the repository
with the PR's base, head and master history available locally. For an offline Git
fixture, use `classify --base REF --head REF --repo OWNER/NAME --json`; merge
classification still needs GitHub evidence (tests supply a fake `gh`). Output is
an object containing `class`, `reasons`, and the full classified `head`.

A2. `docs-only` requires a nonempty diff containing only `WAIVABLE_PATHS`:
`CHANGELOG.md` and `docs/handoffs/**`. The diff is from the merge base to the head,
with rename detection disabled so both sides of a rename are examined. The
allowlist and workflow `paths-ignore` entries must stay identical.

| Path | Read audit, 2026-10-28 | Why waivable |
|---|---|---|
| `CHANGELOG.md` | Searched every file in `tests/`, `.github/workflows/` and `bin/` for `CHANGELOG` and inspected the hits. `bin/ade-update:173` reads committed changelogs to display new entries. `tests/test_ade_update.py:110,124` writes and reads `CHANGELOG_V1/V2` in freshly created fixture repos, never this repository's changelog. The relay test's mention is a docstring. No workflow reads it. | Informational release text; changing the real file cannot affect these tests' fixture changelogs. The updater displays content rather than executes it. |
| `docs/handoffs/**` | Same exhaustive search for `docs/handoffs` found only `bin/ade-scan-state-doc`'s static explanatory text. Tests and workflows do not read this tree. Also inspected the generic GNU-tool scanner: `bin/gnu-tools-check` explicitly excludes `*/handoffs/*`; its tests create their own fixture files. | Historical handoff records, with no executable/test input consumer found. |

A3. Reproduce the audit with `rg -n 'CHANGELOG|docs/handoffs' tests/ .github/workflows/ bin/`;
inspect consumers rather than treating all mentions as reads. Fixtures containing a
file of the same name do not read the repository's actual file. Re-audit before
expanding the allowlist or adding a consumer. Other `docs/*.md`, `skills/**` and
`AGENTS.md` are outside the allowlist. Hard exclusions always deny a waiver:
`.github/**`, `tests/**`, `config/**`, `bin/pr-wait`, and `bin/ci-waiver`.

A4. `master-merge` requires exactly two parents: previous topic head H0 first,
master commit T second. H0 must have a nonempty set of completed green checks
with at least one success, using `pr-wait`'s exact-SHA check-runs and commit-status
reader. T must be an ancestor of GitHub's current master and have a completed
successful `test.yml` push run on master; the latest matching run/attempt wins.
`git merge-tree --write-tree` computes the machine merge of H0 and T. Every
nonwaivable path must match that tree, including modes and deletions. Conflicts
on nonwaivable paths are rejected. Hand resolutions of allowlisted files alone
are permitted. No GitHub comments or commit-message claims establish greenness.

A5. Everything else is `none`: examples include `touches-nonwaivable:code.py`,
`not-a-merge`, `h0-not-green`, `master-not-green`, `hand-edited:code.py`, and
`shallow-history`. Missing objects, unreadable checks and any Git/GitHub error
deny a waiver. The tool never fetches, edits a worktree or cancels a CI run;
`merge-tree` can write Git objects. Exit 0 means a classification was printed,
including `none`; exit 2 means invalid usage. Consumers must check the class.

## B. Independent review and waiter behavior

B1. The author obtains an independent adversary review of the exact head from
`omp --model anthropic/claude-opus-5-5 --effort high` or stronger. An agent able
to request a waiver may never approve its own work. The PR body needs BOTH live
markers (replace placeholders; the classifier, not the reviewer, chooses class):

```text
<!-- ci-waiver:v1 {"class":"docs-only","head":"<40-hex>","reviewer":"<independent agent id>"} -->
<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->
```

B2. `pr-wait` reclassifies the current head on each poll with a live waiver.
Markers in fenced blocks (indent at most three) or single-line inline code are
documentation, not live approvals. The parser shares the adversary parser's
balanced-JSON boundaries, strict duplicate-key handling and code masking; a
partly masked JSON object is malformed. Its documented CommonMark limits also
apply here (AGENTS.md rule 1). Wrong version, invalid class, shortened head or
empty reviewer is `ci-waiver-malformed`. A different full head/class or a denied
classification is `ci-waiver-mismatch`; missing current-head live APPROVE is
`ci-waiver-needs-adversary`. Malformed always blocks, even beside a valid marker.

B3. A valid waiver sets `ci_state` and `ci.state` to `waived` and immediately
satisfies the CI wait, including pending or absent checks. No failed check is
waived. Without a waiver, `ci-pending`, `no-checks`, and `ci-none-succeeded`
remain unchanged. Waivers imply adversary-required. Codex/security review and
unresolved-finding gates remain in force. `pr-wait`'s exit codes are unchanged;
read `merge_ready` and `merge_blockers` before merging.

## C. Workflow filtering and the master backstop

C1. Both push and pull-request triggers ignore exactly the allowlist. GitHub
[documents that all matching paths suppress the workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-excluding-paths).
No test job is started for such a PR; an externally required check may remain
Pending. The waiver handles pending and absent checks; absence never proves a
waiver. The classifier still denies workflow/test/waiver machinery changes.

C2. `push.branches: [master]` remains, and full CI still runs after a master-merge
whose squash changes nonignored paths. This post-merge backstop, with red runs
reported by existing fleet notices, is why master-merge waivers are acceptable.
**Design defect in the original wording:** push `paths-ignore` necessarily also
skips docs-only merges on master, so it cannot run on *every* merged commit.
The implementation preserves the explicitly requested filters and branch
trigger; it does not claim an unconditional master run. Fleet reporting itself
is unchanged and was not live-verified in this slice.

C3. Never use `[skip ci]` to request a waiver: a squash merge can copy commit
messages into its body, accidentally skipping the master push backstop as well.
Use the marker instead. GitHub documents [commit-message skip behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
The authorized merger supplies an explicit clean subject/body, after reading
the review gates:

```sh
gh pr merge N --squash --match-head-commit REVIEWED_FULL_SHA --subject 'Describe the reviewed change' --body 'Describe the reviewed change and validation.'
```

C4. This implementation PR cannot waive itself: it changes hard-excluded paths.
The lead obtains the independent adversary verdict before opening the PR,
replaces the changelog's `(#NNN)` placeholder, and verifies the hosted
Linux/macOS runs before merging.
