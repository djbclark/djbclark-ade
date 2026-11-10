### Changed

- `wave6-delete-check` FAILCLOSEs when C3/Mac evidence omits non-empty proof files (`c3_proofs` / `mac_proofs`); `docs/slim/wave6-follow-up.md` C3 rows list operator probes and proof requirements (queue Carried item 33) (#417).

### Fixed

- Mac B1 idle evidence capture now records `cmd:` + `verified: no match` (and exit status) so successful idle probes leave non-empty `mac_proofs` files; empty redirects still FAILCLOSE (#417).
