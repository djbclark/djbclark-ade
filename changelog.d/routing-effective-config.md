### Changed

- Runtime router initialization and default reload now consume the versioned effective config, honoring unified/local routing overrides after the existing pure shape validation. Explicit legacy file reads remain isolated; routing source provenance is reported. No shipped policy values, frontier bounds, quota/acceptance gates, or live config changed.
