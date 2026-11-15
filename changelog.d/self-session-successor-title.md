### Changed

- `bin/ade-self-session handoff` now gives the successor the predecessor's title (`agent run --title=`) and the labels `ade.predecessor`, `ade.chain` and `ade.role`, so `paseo ls` still names a chain's current lead; `accept` and `finish` read the name and labels back and repair a loss, a Paseo refusal is recorded in the handoff record's `identity`, never fatal. New options `--title` and `--role`. (#726)
