### Fixed
- `adversary-marker`: read the PR body's last editor from `userContentEdits(last: 1)` after GitHub removed the GraphQL `lastEditedBy` field, which had made every gate run fail with `undefinedField` (PR 302).
