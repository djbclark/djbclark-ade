# NATS record-only ruling — 2026-11-20

The operator decided (Fable 5.2 consult, relayed by ADE lead f0012d80): **NATS is the record, not the prompt.** The
host (`paseo send`) carries a prompt into a turn; NATS records who holds a role, what was sent, and what was received.
This is already the implemented design: `bin/ade_coord_wake.py` runs `paseo send` for a content-free nudge, and the
plugin manifest says "no delivery hook or model ack inference" (`plugins/ade-coord/paseo-plugin.json`).

## The principle

A thing belongs in NATS only if all three hold: it must still be true after every agent involved is gone; it can be
retried blindly without harm; and the layer can observe its outcome itself. A report, a role record and a receipt pass.
A prompt fails all three (gone when the turn ends, a second copy runs the instruction twice, NATS cannot see whether a
turn ran). Working rule: **payload in the record, pointer in the prompt** — anything whose loss matters must be
recoverable by a pull from the record.

## Scope (what this ruling authorizes and forbids)

- **Record-only:** role record, relationship, report, receipt, inbox, outbox, artifacts, operations. No change.
- **Proceed now:** cross-agent re-handoff (Carried 103 / PR #823) runs on `paseo send`; it does not wait for NATS. Its
  successor is unenrolled by construction, so its record stays local, shaped so it can be published later unchanged.
- **Not authorized:** a directed delivery command, dynamic enrollment, a wake/reaper path, or a retirement-ruling change
  for stuck enrolled owners. No NATS work blocks the supervisor re-handoff.

## The honest re-handoff record (minimal contract)

1. Write the local handoff record before the `finish` send.
2. One stable message id per re-handoff — the handoff token — reused in every retry, the ack request and any later report.
3. Name each stage in host terms (send accepted, peer acked, first turn verified, finish completed, predecessor
   archived). Never use `ADE-inbox-recorded` or `processed`; those are NATS receipts.
4. Keep an unknown send unknown until an ack or an inspect resolves it; retry only with the same id.
5. Treat any NATS copy as a projection, never a gate — a broker outage must not stop a re-handoff.
6. The record grants no contact authority (`contact_authority:false`).
7. Label attestations: a supervisor's `--quiesced` is asserted-by-the-supervisor, unverified.
8. State the NATS status in the record: "not recorded, no enrolled role".

## What would be needed before directed delivery (all gated on widening enrollment first)

1. Refusing contact (Carried 92): online check at send time, never config.
2. A delivery command: role-addressed, intent-before-network, epoch-fenced, expiring, idempotent receipt.
3. Dynamic enrollment with an authority rule for who may enroll whom.
4. A steady-state controller + wake + reaper on every host.
5. A retirement ruling for stuck enrolled owners (the accepted protocol forbids timeout takeover).
6. The cost seen whole: about the size of the first rollout, buying nothing for a same-host prompt.

## Plan/doc gaps the consult found (filed for a follow-up PR)

1. **Liveness (the material one):** the plan never names who runs the controller in steady state; enrolled roles
   suppress acks and the controller is off, so a report waits until its owner next reads the inbox. Decide before
   enrollment widens.
2. `role watch` is listed in B5 but not built.
3. B5 under-lists the real surface (missing role create/transfer, buffer/flush, intake, shared operations, artifacts,
   jobs, `handoff transfer`, wakes, the relationship query).
4. `DELIVERY.md` says "exactly these two-token pairs" but omits eight commands.
5. E3/E8 wording ("staged enrollment" as a rollout stage, "all goals in this plan") over-claims against the status line
   that says broader enrollment is separately gated.
6. C1 forbids takeover on quota exhaustion/idleness, which collides with Carried 70 unless supervisor re-handoff stays
   unenrolled-roles-only.
7. `docs/nats-coordination.md` is stale against the final acceptance ("no plugin installed", wake "defaults off until
   pilot approval", "pilot gate" wording, an unconditional "every 30 seconds" intake).

Source: the Fable 5.2 consult report at
`~/.local/state/agent-reports/f0012d80-c58c-4488-9e1e-1361c321f399/nats-consult-report.md` (advisory, read-only, no code
changed).
