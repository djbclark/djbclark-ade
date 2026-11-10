### Added

- Made `research_check.py claims` namespace-aware across sibling runs under the same parent (bare unique cross-run ids and `[slug/E####]` cites); `claims` rejects duplicate ids inside a cited sibling, and `numbers` accepts figures quoted only in cited-sibling evidence (#387).
