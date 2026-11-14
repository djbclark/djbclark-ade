### Changed

- `bin/ade-auto-permit`: an agent labelled `ade.kind=external-review` (one that judges untrusted GitHub artifacts for prompt injection) is never auto-approved, in any mode, even with `ade.lead`, as a descendant or under `--all-local`: its requests stay pending (`skip` / `sensitive-sender`), matching peer-trust rule 4; the sweep asks Paseo for that label each pass and fails closed when the answer is missing or malformed. (#710)
