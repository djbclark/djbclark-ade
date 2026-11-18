# NATS coordination fault conformance

The Linux `nats-coordination.yml` job runs the real current released broker and
latest maintained clients. `test/faults.test.js` adds seven isolated fault cases;
CI logs, rather than this document, establish their execution result.

| Case | Fault and asserted recovery |
| --- | --- |
| Coordination capacity | Lower actual stream `max_bytes` with `DiscardNew`, reject a new report, retain prior role/report/receipts, raise capacity and reconcile the persisted same ID once. |
| Object Store capacity | Lower actual object stream capacity, reject an upload without accepting its report, retain old artifact bytes, restore capacity and publish from persisted bytes. |
| Filesystem full | Fill a dedicated 32 MiB Linux tmpfs until an actual write returns `ENOSPC`; require the broker write path to report disk-full too. New report remains buffered in SQLite on another filesystem. Free the filler, restart the broker, reopen local state and verify old role/report/receipts/artifact plus the same pending ID. |
| Established partition | A TCP proxy observes the actual report/receipt publish frame, withholds its response while a separate connection verifies the broker commit, then severs both socket ends. Restore connectivity, observe reconnect and reconcile one report and one processed receipt. |
| Crash/restart | Kill a real SQLite publisher process after its durable intent transaction; SIGKILL the actual broker, restart on the same store and reopen publisher/inbox state before reconciliation and processing. |
| Handoff and delayed ack | Publish concurrently with role transfer while a real consumer holds an earlier report. Ack after transfer; successor still intakes and processes both retained reports, and stale predecessor receipt fails. |
| Older restore | Stop the broker and copy its store, restart and advance ownership, durably advance an independent generation file, kill broker and restore the older copy. Restored old authority exists under the obsolete generation; the separately retained generation rejects it. |

The ENOSPC fixture reserves 8 MiB for its coordination stream inside the 32 MiB
tmpfs; production stream limits remain unchanged. Disk pressure is induced by
actual filesystem allocation, independently of that stream limit.

The ENOSPC test refuses absent/non-tmpfs filesystems and any filesystem over
64 MiB. It never fills general runner storage. The workflow mounts only its
`RUNNER_TEMP/nats-fault-tmpfs`, and its always-run cleanup unmounts that path.
Every fixture logs broker PIDs and reaps owned children; proxy cleanup destroys
only its own sockets. Test deadlines and subprocess shutdown bounds fail a stuck
fixture instead of silently treating it as a pass.

These are process, TCP, broker-capacity and bounded-filesystem faults. The cold
copy is a stopped-broker store snapshot, not an online snapshot API exercise.
Neither tmpfs nor SIGKILL establishes power-loss/physical-disk durability. The
second clients use independent connections; they do not constitute a physical
second-host deployment. Native Paseo plugin unload/reload, real queued wakes,
credential enrollment and the two-host pilot remain deployment evidence owned
by the lead. No synthetic native endpoint is labelled actual Paseo behavior.
