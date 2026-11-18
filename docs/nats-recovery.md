# NATS backup and isolated recovery

A1. `bin/ade-coord-backup` snapshots `ADE_COORD_V1` and
`OBJ_ADE_ARTIFACTS_V1` over authenticated NATS into a private directory on the
backup host. It never reads the broker's filesystem. Run it on a different
existing host from `vps-hub`; a second directory on the hub is not off-host
protection. Schedule the command with the existing machine scheduler, not a
recurring model prompt.

A2. Supply `ADE_NATS_URL` and `ADE_NATS_TOKEN` through the existing managed
secret environment boundary. The native CLI receives its token in `NATS_TOKEN`,
never in argv, a URL, the manifest or logs. The tool isolates NATS context
configuration and emits only counts and safe status. Resolve current `nats`
from PATH or the explicitly managed `ADE_NATS_CLI` executable.

A3. With that environment injected, the command is:

```text
python3 bin/ade-coord-backup create /ABSOLUTE/NEW/BACKUP --generation INDEPENDENT_GENERATION
python3 bin/ade-coord-backup verify /ABSOLUTE/BACKUP --generation INDEPENDENT_GENERATION
```

A4. Preserve the generation manifest and independently observed role/stream
high-water evidence on another host. A manifest supplied by the restored
broker itself cannot establish that its data is current. A hash detects
corruption against a trusted manifest; it is not an authenticity signature.
Do not edit the snapshot, renumber sequences, discard operation intents or
convert this isolated proof into production authority.

A5. The coordination snapshot is taken before the object snapshot. Reports
must only reference artifacts uploaded and verified before report publication.
Artifact expiry and destructive cleanup stay disabled during the pilot.
Snapshot integrity alone does not prove application consistency; the recovery
proof also checks actual role, report, receipt and artifact bytes.

A6. Restore only to a separately provisioned, empty, isolated loopback broker,
with its own `ADE_NATS_RECOVERY_TOKEN` environment credential:

```text
python3 bin/ade-coord-backup restore-isolated /ABSOLUTE/BACKUP --generation INDEPENDENT_GENERATION --isolated-url nats://127.0.0.1:PORT
```

A7. The tool refuses non-loopback destinations, nonempty brokers, generation
mismatch, changed/missing/extra files and symlinks. Success explicitly returns
`production_authority: false`. This is a guardrail for an operator-created
isolated broker; a loopback address alone cannot identify a production broker
or prove the absence of a forwarder. Never point it at production or an SSH
forward to production.

A8. Production disaster recovery additionally requires stopping all previous
writers, reconciling external operations and independent high-water evidence,
issuing a deliberately reconciled coordination generation, updating clients,
and one reviewed cutover. OS rollback must retain current coordination data.
Do not run independently writable brokers for the same live roles.

B1. The Linux workflow `.github/workflows/nats-recovery.yml` resolves current
released server/CLI and maintained clients, creates a real report/artifact and
inbox receipt, takes network snapshots, restores to another broker, verifies
the retained records/bytes, and checks generation/corruption/destination
refusals. It uses two processes on one CI host. Actual off-host backup and
two-host live recovery remain rollout acceptance work until recorded.

B2. Primary API evidence: native [backup/restore command definitions](https://github.com/nats-io/natscli/blob/main/cli/backup_command.go),
[environment flags](https://github.com/nats-io/natscli/blob/main/nats/main.go),
and [stream JSON output](https://github.com/nats-io/natscli/blob/main/cli/stream_command.go).
Current CLI backup inspection/validation commands have additional server-format
requirements; this tool verifies its own hashes and performs an actual restore
instead of inferring compatibility from those inspection commands.
