### Added

- `just install` asks the three setup-plan S3a Hermes paths on a tty
  (`ADE_HERMES_CHOICE=skip|self|ai` otherwise) and `ade-install hermes-choice`
  records the answer in the install state dir without editing tracked config.
  `skip` prevents Hermes apply/probes; `self` and `ai` apply, then with `--yes` run
  `just hermes-setup --self` or `just hermes-setup`. Scoped `doctor hermes`
  adds observe-only checklist probes after the catalog probe passes
  (config, skills root, claude-collaboration, `claude mcp list`; the
  tell_chief_of_staff pointer stays optional) (#591).
