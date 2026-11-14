### Changed

- `load-watch admit` gained a swap-ins gate (`--max-swapins`, `LW_MAX_SWAPINS_S`, default 300/s; swap-ins above 20/s also corroborate the 1000/s page-ins line), a free-memory floor that scales with the RAM (35 MB per GiB above 4 GiB, clamped to 300..1000: 980 on 32 GB), a starvation valve for `admit --wait` (a caller refused for 5 minutes on soft gates only is admitted, at most once per 2 minutes machine-wide; hard gates never yield; prints `admit ok forced=starved ...`) and a tuning log (`admit-log.jsonl`, `LW_ADMIT_LOG`) with `load-watch admit-log summary [--days N]` (#695)
