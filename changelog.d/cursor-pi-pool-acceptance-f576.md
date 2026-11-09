### Added

- Added `config/pi-pool-acceptance.toml` and `bin/ade-pi-pools` so automatic Pi routing (`ade/auto` / `bin/pi-default`) refuses pools the operator has not flipped to `accepted=true`; `check` exits 2 while any routing Pi service is unaccepted (#418).
