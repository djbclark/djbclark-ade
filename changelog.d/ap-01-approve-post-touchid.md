### Changed

- `ade-merge-ready approve-post` (real run, `--yes`) now asks djbclark for fresh Touch ID/password through `sudo-ask -k` (else `sudo -k /usr/bin/true`) before its first post: the dialog names the repo and every `PR N head <40-hex>`; a refusal, failure, timeout or a selection too long for one dialog posts nothing and exits 3. Dry-run and the other subcommands are unchanged and there is no bypass flag or env var. It stops an agent approving its own PR through this tool, not one using djbclark's `gh` token directly (#731).
