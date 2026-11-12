# Audit data, 2026-11-11

Baseline: `fb3b9deb044cfde79cdc7ab2623224e2d8d7658a` (remote tag pre-slim-2026-11-06).
Initial merged slim snapshot: `63beae7de4d95db4936a5dde7c5a4c2edb858f01` (#297).
Audited master: `bc2a112a6e16f304d273f69b16d22c93e558dc6f`.

- historical-ledger.csv: all 627 historical ledger rows plus 119 unlisted observations. Proposed dispositions are historical, NOT current authorization. Rulings and later changes supersede them. Path checks do not classify deletion: rows include descriptions, globs, line references and installed/external paths.
- tracked-path-changes.csv: exhaustive Git tracked-path diffs for initial slim, subsequent changes, and net baseline-to-audit. Rename detection disabled deliberately: a move appears as deletion plus addition; consult the human report before interpreting capability loss. Additions included to expose replacements and restorations. Tests/docs/config are included. No installed-machine state inferred.
- post-slim-commits.csv: all 195 first-parent commits after #297 through the audit pin, including work outside the slim plan. This avoids selectively overlooking later changes.

These files supplement ../change-audit-2026-11-11.md. They contain no live probes or secrets.
