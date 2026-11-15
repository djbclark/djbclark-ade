### Changed

- `load-watch release` exits 66 (EX_NOINPUT) for a reservation that does not exist and keeps 1 for a lock or write failure; `load-watch admit --wait S --refused-since EPOCH` (env `LW_REFUSED_SINCE`, the flag wins; cap `LW_STARVE_REFUSED_SINCE_MAX_S`, 3600 s) starts the starvation valve's 300 s clock at the caller's own hold start, so `bg`'s 420 s chunks can reach it. Hard gates and the one-forced-admit-per-120 s gap are unchanged. (#712)
