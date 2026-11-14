### Fixed

- `ade-worker-run`: a successor lead that inherited several WORKERS windows from its predecessors is no longer stuck. A `--window-middle` for new work opens a new window beside the inherited ones (the "second window" typo refusal now applies only to windows the lead itself placed), and with no `--window-middle` the repo (`--repo`, or the one derived from `--cwd`, else the current directory) narrows several owned windows to that repo's; several of one repo are still refused, and the refusal says to pass `--repo` or `--window-middle`. (#680)
