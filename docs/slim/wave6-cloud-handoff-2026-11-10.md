# Wave 6 cloud handoff — 2026-11-10

Snapshot: **2026-11-10** (America/New_York). Orderly paste-back from the
bigmac Mac agent into cloud, verified on Linux, ready for a successor agent.
**No deletion PR. No invented `waived` / APPROVE / Pi `accepted=true`.**

Companion evidence notes: [`mac-live-2026-11-10.md`](mac-live-2026-11-10.md),
[`wave6-follow-up.md`](wave6-follow-up.md),
[`outside-migration-proposals-2026-11-10.md`](outside-migration-proposals-2026-11-10.md).

## A. Verified on this cloud host

1. Reconstructed archive under `~/tmp/wave6-mac-from-bigmac-20261110/`.
2. SHA256 matched:
   `18eab71cc7227a3f7eaa1a5a096e6dd2049a06ef33971d042995c844ce236155`.
3. Every `MANIFEST.json` member hash matched (47 entries); refuse-overwrite
   layout intact. Initial capture **and** `recapture/` both present.
4. Read `evidence.json`, `gate-final.json`,
   `outside-migration-proposals.md`, pool proofs, C3 proofs, fleet-watch
   proof. Linux host did **not** re-run Darwin probes.

## B. Gate (artifact) — still blocked

`wave6-delete-check --evidence …` **exit 1**. Reasons:

1. Seven C3 rows `None` (not invented waived): `tendcf`, `nix2cf`,
   `cfengine`, `paseo4herdr`, `sudo_secretspec`, `aiuse`,
   `site_public_home_agents`.
2. `mac_acp_dispatch_idle: want true, got False` — live lead
   `0cc34651-d6e5-4d88-b4cd-8166038da11e` still listed under
   `ade.via=acp-dispatch` (two other listed sessions closed).
3. `soft_deadline: 2026-11-10 < 2026-11-20` — no `--allow-early`.

Also green / already done: `--inventory` `callers_remaining=0`; five C3
rows `migrated` (`paseo_upstream`, `plektra`, `pi`, `paseo_runner`,
`aiuse_config_opencode_go`); Mac process/launchd idle on follow-up for
relay/acp-run/acp-dispatch **binaries** (label listing is the B2 hold).

Extra outside client (not a C3 key): 
`~/ops/site-private-djbclark/bin/fleet-watch` still defines `UPSTREAM_RELAY`
and calls `relay.py` (`proofs/outside-fleet-watch-relay.txt`).

## C. Operator decisions (ordered)

Ask **one card at a time**. Cheapest unlock first.

### C1 + C2 — historical waives (ask first; NOT granted)

Dated handoffs only. Does **not** authorize outside code edits.

Proposed lines (copy into `docs/slim/log.md` + the matching `c3_proofs`
files only after the operator says yes):

- **C1 `paseo4herdr`:**
  `2026-11-10: waive Wave 6 C3 paseo4herdr for immutable dated handoff references; do not rewrite those records or reinstall retired tools.`
- **C2 `sudo_secretspec`:**
  `2026-11-10: waive Wave 6 C3 sudo_secretspec for preserved dated handoff references; new runtime callers use native Paseo.`

Reply options: `yes C1+C2` · `C1 only` · `C2 only` · `neither` · rewrite lines.

(Alias in earlier notes: A1+A2 = C1+C2.)

### A3–A7 — outside migrations (order 11 each)

| ID | Key | Next |
|---|---|---|
| A3 | `tendcf` | Active `AGENTS.md` shim/frontier → native ADE routing; claimed WT PR |
| A4 | `nix2cf` | Same as tendcf; separate claimed WT |
| A5 | `cfengine` | Classify `cfengine-all` active vs historical; then migrate active |
| A6 | `aiuse` | Update live teaching; decide retained-reader waive separately; keep logs |
| A7 | `site_public_home_agents` | Opus-only `home-agents.md` upkeep (lines 6,53,57,64) |

### X — extras before deletion

| ID | Item | Next |
|---|---|---|
| X1 | `fleet-watch` | Migrate off `UPSTREAM_RELAY`/`relay.py` (order 11) |
| X2 | B2 label | After lead `0cc34651…` work ends: clear inherited label, recapture B2 |
| X3 | Date gate | Hold until 2026-11-20 **or** explicit `--allow-early` after C3+Mac complete |

## D. Pi pools (do not flip)

| Pool | accepted | Note |
|---|---|---|
| cursor / zai | true | Already accepted |
| grok | **false** | HTTP 402 Grok Build balance exhausted |
| antigravity | **false** | Manual OK; auto aiuse mapping / latch unproven |
| sipb | **false** | Parked (`docs/pi-services.md`) |
| go | **false** | `opencode-go/minimax-m3` unavailable after refresh |

Manual Antigravity inference is **not** automatic-routing acceptance.

## E. Hard stops for every successor

1. Do **not** invent APPROVE markers, C3 `waived` statuses, or Pi
   `accepted=true`.
2. Do **not** open a Wave 6 deletion PR until `wave6-delete-check --evidence`
   exits 0 **and** the operator confirms.
3. Keep `relay.py`, `acp-dispatch`, `acp-run`, and `review-launch` intact.
4. Outside repos need order-11 yes (`AGENTS.md` standing order 11).
5. Preserve archived logs and dated handoffs; never rewrite history to clear
   probes.

## F. Resume prompt (copy for a successor agent)

Paste the fenced block below into a new agent session:

```
RESUME — Wave 6 / Pi Mac evidence handoff (2026-11-10 bigmac → cloud).

Read first (in order):
- docs/slim/wave6-cloud-handoff-2026-11-10.md  (this handoff)
- docs/slim/mac-live-2026-11-10.md
- docs/slim/outside-migration-proposals-2026-11-10.md
- docs/slim/wave6-follow-up.md
- docs/queue.md Carried item 1
Verified archive (optional local): ~/tmp/wave6-mac-from-bigmac-20261110/
  SHA256 18eab71cc7227a3f7eaa1a5a096e6dd2049a06ef33971d042995c844ce236155
  (initial + recapture/ preserved; MANIFEST verified on cloud Linux)

State:
- §A callers green (callers_remaining=0).
- Mac live captured; wave6-delete-check --evidence still exit 1.
- C3: 5 migrated / 7 open. Open: tendcf, nix2cf, cfengine, paseo4herdr,
  sudo_secretspec, aiuse, site_public_home_agents.
- Extra: fleet-watch still calls relay.py.
- B2 not drained: live lead 0cc34651-d6e5-4d88-b4cd-8166038da11e has
  inherited ade.via=acp-dispatch (do not stop/relabel from cloud).
- Soft deadline 2026-11-20; no --allow-early granted.
- Pi grok/antigravity/sipb/go stay accepted=false.

Next (operator-gated; one card at a time):
1. Ask C1+C2 historical waives (paseo4herdr, sudo_secretspec) — proposed
   lines are in the handoff doc / outside-migration-proposals. NOT granted.
2. After yes: record waive lines in docs/slim/log.md + c3_proofs files;
   never invent waives.
3. Then seek order-11 yes for A3–A7 + fleet-watch migrations (outside repos).
4. After Mac lead finishes: confirm B2 label drain + recapture.
5. Deletion PR only when wave6-delete-check --evidence exits 0 AND operator
   confirms. Keep relay.py, acp-dispatch, acp-run, review-launch.

Hard stops: no invented APPROVE / waived / Pi accepted=true; no deletion PR
early; no outside edits without order 11; preserve handoffs/logs.

Unrelated hygiene observed (not repaired): sudo-secretspec doctor fail,
Hermes doctor timeout, missing ade-claim plugin — handle via normal owners.
```
