### Fixed

- `load-watch admit`'s memory gate counts available memory on macOS (free + speculative + inactive + purgeable, like Linux MemAvailable); free + speculative alone read 82 MB on an idle Mac with ~3.9 GB reclaimable and refused every launch for ~1.5 h (#230).
