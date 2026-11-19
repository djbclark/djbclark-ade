### Added

- Prepare a portable CI coordination runtime with dependency provenance, native NATS CLI checksums and atomic artifact installation without enrolling roles. (#779)

- Include the enrolled-role instructions in the portable coordinator runtime (#779)
- Verify the current coordination source against the broker package from published hub configuration. (#779)
- Audit only installed production dependencies when building the runtime bundle. (#779)
- Supply an isolated bounded filesystem for deployment-package disk-full conformance. (#779)
