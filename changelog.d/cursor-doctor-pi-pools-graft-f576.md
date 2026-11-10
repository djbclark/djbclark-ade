### Added

- `ade-install doctor` warns on UNACCEPTED Pi pools from
  `config/pi-pool-acceptance.toml` (`warn`, exit 0; accepted Cursor/Z.ai stay
  quiet; never writes `accepted=true`); documents hard-dep `graft --version`
  missing as a doctor fail (#NNN).
