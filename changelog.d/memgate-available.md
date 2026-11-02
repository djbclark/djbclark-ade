### Fixed

- `load-watch admit`'s memory gate counts memory available without compressing or swapping on macOS (free + file-backed + purgeable pages, the file-cache term of Linux MemAvailable), not only free + speculative pages, which read 82 MB on an idle Mac and refused every launch for ~1.5 h (#230).
