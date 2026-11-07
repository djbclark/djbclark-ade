### Fixed
- `adversary-marker`: read the PR body's last editor from `userContentEdits(first: 1)` (connection is newest-first, live probe 2026-11-07) after GitHub removed the GraphQL `lastEditedBy` field, which had made every gate run fail with `undefinedField` (PR 302).
