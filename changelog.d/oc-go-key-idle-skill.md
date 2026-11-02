### Changed

- `oc-go-key` skill: `use` reloads an OpenCode server only when it has no active session (a mid-turn reload left a Paseo seat stuck "running"); a busy server is deferred with exit 3, `oc-go-key reload`/`pending` and `--wait-idle S` finish it (#264).
