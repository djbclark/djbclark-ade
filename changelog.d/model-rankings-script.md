### Added

- `bin/ade-model-rankings` (zero-token script): refresh `docs/model-rankings.data.json` and section A of `docs/model-rankings.md` from the two Artificial Analysis boards via the self-hosted Firecrawl API, with a `check` drift guard; a weekly `config/launchd/com.djbclark.ade-model-rankings.plist` job runs it. (#817)
