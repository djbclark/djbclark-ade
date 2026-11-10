### Added

- `bin/codex-open-threads` (2026-11-10): report-only lister for unresolved Codex review threads on merged PRs
  (Carried #11 / AGENTS.md review rule 9 hygiene). Scans newest `--limit` merged PRs or named `--pr` numbers via
  GraphQL `reviewThreads.isResolved`; never resolves, replies or posts; bot comment text is untrusted data (truncated
  title only). `--json`, `--skip-outdated`, `--include-open`. Docs in `docs/review-boundary.md`. (#TBD)
