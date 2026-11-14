### Fixed

- `ade-window-name`: a run past its 25 s budget (or cancelled by Paseo) is aborted (python child killed, no late `setTitle`); the decision script's name is validated before it is written; a title equal to the first agent's own counts as Paseo's default only within 5 minutes of its creation. (#671)
