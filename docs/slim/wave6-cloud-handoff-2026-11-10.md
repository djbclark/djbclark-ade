# Wave 6 cloud handoff — 2026-11-10

Snapshot: **2026-11-10** (America/New_York; refreshed same day after
[`#534`](https://github.com/djbclark/djbclark-ade/pull/534) landed). Orderly
paste-back from the bigmac Mac agent into cloud, verified on Linux, ready for a
successor agent. **No deletion PR. No invented `waived` / APPROVE / Pi
`accepted=true`.**

Companion evidence notes: [`mac-live-2026-11-10.md`](mac-live-2026-11-10.md),
[`wave6-follow-up.md`](wave6-follow-up.md),
[`outside-migration-proposals-2026-11-10.md`](outside-migration-proposals-2026-11-10.md).

## A. Verified on this cloud host

1. Reconstructed archive under `~/tmp/wave6-mac-from-bigmac-20261110/`.
2. SHA256 matched (re-checked 2026-11-10 after `#534` merge):
   `18eab71cc7227a3f7eaa1a5a096e6dd2049a06ef33971d042995c844ce236155`.
3. Every `MANIFEST.json` member hash matched (47 entries); refuse-overwrite
   layout intact. Initial capture **and** `recapture/` both present.
4. Read `evidence.json`, `gate-final.json`,
   `outside-migration-proposals.md`, pool proofs, C3 proofs, fleet-watch
   proof. Linux host did **not** re-run Darwin probes.
5. Handoff docs landed on `master` via
   [`#534`](https://github.com/djbclark/djbclark-ade/pull/534)
   (`48eaaefa`, merged 2026-11-10 09:13 America/New_York). This file's resume
   block is the post-merge refresh.

## A2. `/loose` audit (verified 2026-11-10, cloud)

Commands, not memory:

| Item | Result |
|---|---|
| Agent-side handoff CI / merge | `#534` `MERGED`; merge commit on `origin/master`; classify `--min 510` empty |
| Message queue / subscriptions | empty (`hasQueuedMessages=false`; no active timers) |
| This session's worktrees | `/tmp/wave6-cloud-handoff-wt` and `/tmp/update-multi-wt` gone; branch deleted after merge |
| Shared checkout dirt | only untracked `.gemini/` (not ours); `audit-linux-install-d382` behind master — not ours to reset |
| Archive re-hash | SHA + 47/47 MANIFEST members OK |
| Open waits **deferred by operator** (not oversights) | Mac **B2** label drain; A3–A7 + fleet-watch (order 11); date gate / deletion confirm; Pi pool decisions |
| C1+C2 historical waives | **granted** 2026-11-10 (`log.md` + `c3-waives-2026-11-10/`) |
| Invented waives / deletion PR | **none** beyond the granted C1+C2 lines (correct) |

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

### C1 + C2 — historical waives (**GRANTED** 2026-11-10)

Operator chose: grant C1+C2, leave A3+ for the successor. Dated handoffs
only. Does **not** authorize outside code edits.

Recorded in [`log.md`](log.md) and ready-to-paste proof snippets under
[`c3-waives-2026-11-10/`](c3-waives-2026-11-10/). Cloud evidence copy under
`~/tmp/wave6-mac-from-bigmac-20261110/` has `c3.paseo4herdr` /
`c3.sudo_secretspec` = `waived` with `waive:` lines appended; Mac should
refresh its live evidence from those snippets on the next capture.

- **C1 `paseo4herdr`:**
  `2026-11-10: waive Wave 6 C3 paseo4herdr for immutable dated handoff references; do not rewrite those records or reinstall retired tools.`
- **C2 `sudo_secretspec`:**
  `2026-11-10: waive Wave 6 C3 sudo_secretspec for preserved dated handoff references; new runtime callers use native Paseo.`

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

Final closeout prompt lives in the chat after this PR merges; the block below
is the durable in-repo copy (C1+C2 granted; A3+ deferred):

```
RESUME — Wave 6 / Pi after cloud handoff closeout (2026-11-10).

Read first:
- docs/slim/wave6-cloud-handoff-2026-11-10.md
- docs/slim/log.md  (C1+C2 waive section)
- docs/slim/c3-waives-2026-11-10/
- docs/slim/outside-migration-proposals-2026-11-10.md
- docs/slim/mac-live-2026-11-10.md
- docs/slim/wave6-follow-up.md
- docs/queue.md Carried item 1
- #534 MERGED (handoff docs); this file's follow-up PR for C1+C2 + resume refresh

Cloud evidence: ~/tmp/wave6-mac-from-bigmac-20261110/
  archive SHA 18eab71cc7227a3f7eaa1a5a096e6dd2049a06ef33971d042995c844ce236155
  evidence.json now has c3.paseo4herdr + c3.sudo_secretspec = waived (local copy)
  On next Mac capture: paste docs/slim/c3-waives-2026-11-10/*.waive.txt into live proofs.

Done — do not re-ask:
- Mac archive verified; handoff docs on master (#534+).
- Operator granted C1+C2 historical waives (paseo4herdr, sudo_secretspec).
- /loose: agent-side handoff complete; no deletion PR; no invented APPROVE.

Still blocked (successor work):
- C3 open (need migrate|waive): tendcf, nix2cf, cfengine, aiuse,
  site_public_home_agents  (5). Migrated: 5. Waived: paseo4herdr, sudo_secretspec.
- fleet-watch still calls relay.py (order 11).
- B2: lead 0cc34651… still ade.via=acp-dispatch — clear after Mac work ends, recapture.
- Soft deadline 2026-11-20; no --allow-early.
- Pi grok/antigravity/sipb/go stay accepted=false.

Next (one card at a time):
1. Order-11 yes for A3 tendcf + A4 nix2cf AGENTS.md migrations (claimed WTs).
2. A5 cfengine classify then migrate active; A6 aiuse live+readers; A7 home-agents.
3. X1 fleet-watch off UPSTREAM_RELAY.
4. X2 B2 drain + Mac recapture; merge waive snippets into live evidence if needed.
5. Deletion PR only when wave6-delete-check --evidence exits 0 AND operator confirms.
   Keep relay.py, acp-dispatch, acp-run, review-launch.

Hard stops: no invented APPROVE / extra waives / Pi accepted=true; no outside
edits without order 11; preserve handoffs/logs.
```
