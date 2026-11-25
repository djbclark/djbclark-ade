### Changed

- Updated `pi-extensions/venice` to dynamically load Venice.ai's full online text model catalog from `https://api.venice.ai/api/v1/models` on load/reload with a 15-minute on-disk cache, `PI_OFFLINE=1` support, and bundled shortlist fallback (#1004)
