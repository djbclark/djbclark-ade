# NATS JetStream execution ledger — issue 779

A1. Active objective: implement every goal in the approved NATS plan, including CI, two-host pilot, activation and recovery verification. Planning completion does not satisfy this objective.

A2. Lead: `64881586-eb24-4a5f-9087-a2df8441ca5d`. Broker target: existing NixOS `vps-hub`, over Tailscale. No Google provisioning or paid Temporal trial.

A3. Plan: [implementation contract](nats-jetstream-implementation-plan.md). Runtime source is authoritative; record actual evidence below.

## B. Current work

| Slice | State | Workspace / evidence |
|---|---|---|
| Protocol conformance and coordination library | Pushed; eight Linux integration cases green; independent review pending | `258a247f4e4336274dfe34e94761c16dee763658`, [CI](https://github.com/djbclark/djbclark-ade/actions/runs/44317508893) |
| Baseline and resource audit | Worker `78743358-b5b0-437e-a126-b3649e35541c` working, return path acknowledged | Report `nats-baseline-audit-report.md` in D1 |
| Hub NixOS module | Pushed, disabled on host; VM fixture repaired after first CI failure | `0eef699a2b981d91350db20cb598cc46cd1cdc06`, [VM and full hub build green](https://github.com/djbclark/site-djbclark/actions/runs/44320520909); actual package conformance added at13d4ab56 |
| Delivery/outbox integration | Green after independent B1/B2 repairs, lifecycle added | `888a016342e49209931407cf6bc8aa85ec6b26a8`, [22 Linux cases green](https://github.com/djbclark/djbclark-ade/actions/runs/44322393004) |
| ADE resource/claim/handoff/plugin adapters | Worker8035 active, resource review repairs plus opt-in integration | `/Users/djbclark/src/djbclark-ade-nats-adapters-64881586-wt` |
| Network backup and isolated recovery | Root pushed proof, CI pending | `/Users/djbclark/src/djbclark-ade-nats-integration-64881586-wt`; docs/nats-recovery.md |
| CI/adversary/pilot | Protocol CI passed; hub CI running; reviews and live pilot pending | No activation or live delivery claims |
| Optional Temporal microtest | Pending independent ready slot | Isolated CI, no paid model calls |

## C. Verified preflight

C1. Published ADE base: `d6a847044942bb9f5f9b572600a318a90b45c649`. Published site base: `81c6b8115bb11753bf57ee02cc2adc34d6e0ccad`. Worker workspaces are clean at these recorded bases; shared checkouts are not used for development.

C2. Live hub SSH succeeds; Tailscale is active. Reported available memory exceeds 23 GB; `/var/lib` resides on persistent root with about 280 GB free. Configuration revision reported `2441b383617619e2a95df7da1c834ece4e12b2a1`. These are preflight facts, not a NATS deployment proof.

C3. Fresh routing selected Codex everyday coding profile with 91% binding-window headroom. Claude is short. Re-plan before every new launch; these readings do not authorize a future batch.

C4. Initial agent admission was refused for memory churn; subsequent normal admission succeeded. Do not bypass load, quality or permission gates.

## D. Evidence locations

D1. Worker briefs/reports: `/Users/djbclark/.local/state/agent-reports/64881586-eb24-4a5f-9087-a2df8441ca5d/nats779/`.

D2. Record commits, CI run URLs, review verdicts, activation/recovery results and unverified cases as each becomes available. Never infer deployment from merged code or broker availability from configuration alone.

## E. Current technical findings

E1. The single-node protocol proof rejected a staged stale-owner receipt after ownership transfer. This does not establish clustered failover safety. Sparse-array canonicalization and successor intake after a prior owner's receipt are explicitly included in delivery follow-up.

E2. The first infrastructure VM run exposed an invalid fake Tailscale unit: its upstream ExecStart needed an explicit empty reset before replacement. The fixture now documents and uses that reset. This failure preceded broker assertions; it was not a broker success.

E3. Local SQLite intent, report bytes and artifact bytes must precede broker I/O. Receipt stages represent durable transport/inbox/disposition evidence, never model comprehension. An unknown external operation outcome remains unknown until reconciliation.

E4. Tool procedure: route a single judgment with `route_agent.py route --kind frontier --json`; a wave uses `plan --kinds ...`, with documented placement arguments. There is no `--task` argument. Capture quota/router JSON to a private scratch file and print only needed fields; do not stream full quota output into the session.

E5. Independent Astra review closed delivery B1/B2 and found two resource-ledger race/recovery blockers in7ff2d719. Worker repair772b3962 is pushed; renewed review/CI required. Do not treat the earlier five green resource tests as proof of those missing interleavings.
