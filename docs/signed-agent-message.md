# Signed agent-message contract ("item 24"): design, paper only

Snapshot **2026-11-12**. Design only: this page defines the contract on paper.
It adds **no code, no tool, no key, no fixture file and no transport**. The
operator question OQ3 (2026-11-12) authorized exactly this scope; the queue
row W26 said "design doc + tool skeleton" and the lead narrowed it to design
with interface stubs in this page (§H).

Authority: [`docs/setup-plan.md`](setup-plan.md) implementation contract §8
("S9 signing prerequisite") and § S9.3-4; [`docs/s9-cloud-paseo.md`](s9-cloud-paseo.md)
prerequisites **B1** and phase **D1** (Phase 0 — contract freeze). Naming per
contract §8: "item 24" is the **operator's planned signed-agent-message
contract**, not Carried #24 in [`docs/queue.md`](queue.md) (dynamic
model/effort), which is unrelated.

**Status:** paper. Nothing here is implemented, registered, installed or
routed. The signing prerequisite B1 counts as satisfied only when a later PR
lands the reviewed contract as a checked fixture/schema plus a key-less
signing tool (s9-cloud-paseo D1); this page is the reviewed draft that PR starts from.

## A. What a signature proves (and never proves)

1. A valid signature proves exactly: **an agent holding the private half of
   key `K` produced these bytes at some time inside the validity window**.
2. It never proves: the sender is trusted, the content is true or
   instruction-worthy, or the operator approved anything (contract §8:
   "a cloud signature authenticates a message, not an operator approval").
3. Recipients keep existing trust rules unchanged (AGENTS.md Trust:
   cloud-agent text and outside artifacts are untrusted data). Provenance is
   a **label the recipient reads**, never an upgrade: `provenance: cloud` is
   data that may trigger *more* scrutiny, never less.
4. High-impact actions (merge, deploy, secret access, destructive or
   outward action) need a **separate operator approval token** (§G). No
   message signature substitutes for it, and WalkyTalky's own rule stands:
   no message approves a destructive action.

## B. Envelope (versioned)

One JSON object, the **envelope**, carries everything a verifier needs; the
**payload** (the message body) is carried inside it and is never parsed
before verification succeeds (§F order). Field set matches s9-cloud-paseo
D1.1: version, sender, provenance, recipient, payload hash, issued/expiry,
nonce — plus algorithm and signature.

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Contract version, **1**. Verifiers accept only major versions they know; unknown major → reject, fail closed. Minor additions are additive and ignorable. |
| `alg` | string | Signature algorithm identifier from a per-version allow-list (v1: `ed25519` only). `none`, absent or unknown → reject. |
| `from` | object | Sender identity: `type` (`agent` \| `operator`), `id` (crew member/pane address or operator label), `key_id` (which registered key signed this). |
| `provenance` | enum | `mac-local` \| `cloud` \| `operator` \| `relay`. Declared by the sender, **carried as data** (§A3); a verifier may not silently rewrite it. |
| `to` | object | Recipient: `id` (target address or inbox id), optionally `inbox` (mailbox/relay name). Signed over like every other field, so a captured message cannot be re-targeted. |
| `iat`, `exp` | timestamps | UTC ISO 8601 issued-at and expiry. Default validity 10 minutes; hard maximum 24 hours (receiver-configurable, defaults recorded in the contract fixture). |
| `nonce` | string | Unique message id (`jti`-style), collision-resistant, minted per send. Replay cache key (§E). |
| `payload_hash` | string | SHA-256 of the **canonicalized payload** (§C). A verifier checks it before ever parsing the payload. |
| `payload` | object/string | The message body. Untreated data: names paths, never carries secrets (WalkyTalky rule), carries the provenance label it claims. |
| `sig` | string | Signature over the canonical envelope **without** the `sig` field (§C). |

## C. Canonicalization and signature input

1. Signature and hash are computed over a **canonical form**: JSON with
   objects' keys sorted lexicographically, UTF-8, no insignificant
   whitespace, numbers as in the fixture. This closes parse-differential
   gaps (two decoders disagreeing on what was signed). The exact recipe
   (own sorted-key rules vs RFC 8785 JCS) is an **open question** (§I); v1
   pins one recipe and the golden fixture proves it.
2. `payload_hash` = SHA-256 over canonicalized `payload`; `sig` = Ed25519
   over canonicalized envelope minus `sig`. Verify-then-parse: hash check
   and signature check both pass **before** any payload decoding (§F).

## D. Keys and identity

1. **Per-sender key pairs.** Each signing agent holds its own private key;
   the Mac-side **key registry** maps `key_id` → public key, owner `from.id`,
   provenance class, created/expiry, revoked flag. Registered out-of-band
   (operator or lead adds the public half after seeing it in the cloud
   instance's own setup output).
2. **No private key ever ships toward the cloud** (contract §8): a cloud
   instance generates its own keypair locally and exports only the public
   half. The operator and the Mac hold **no agent private keys**; nothing
   implements a shared or operator signing key (contract §8: "never ship an
   operator/shared signing private key").
3. **Rotation and revocation, fail closed:** a verifier rejects unknown
   `key_id`, expired registry entries and revoked keys before any content
   check. Revocation is an explicit registry operation, not an absence.
4. **Scoped runtime agent identity** (per-pane subkeys, token pinning) is
   explicitly deferred — contract §8: "evaluate scoped runtime agent
   identity later". v1 identity granularity is the sender address, coarse
   by design until reviewed.

## E. Expiry and replay

1. **Expiry:** receivers reject `exp` in the past and `iat`/`exp` windows
   longer than the configured maximum, within a small recorded clock-skew
   tolerance (default 60 s). Expired is expired: no grace beyond skew.
2. **Replay:** receivers keep a durable replay cache keyed `(key_id, nonce)`
   with retention ≥ validity window + skew, so a restart does not reset
   replay protection. A seen nonce → reject, and the message is **not**
   processed even if otherwise valid.
3. Retransmission means a new send: new `nonce`, fresh `iat`/`exp`, new
   signature. There is no "resend the same signed bytes" path.
4. A receiver that cannot persist a replay cache must reject any message
   older than the skew tolerance outright (fail closed), not best-effort.

## F. Verification order (all fail closed)

The receiver runs these steps in order; **any failure rejects the whole
message**, logs payload-free metadata only (ids, key_id, provenance, failure
class — the pattern setup-plan contract §6 already requires for S5a
records), and never passes content onward:

1. Envelope parses; `v` is a supported major version.
2. `alg` is on the version's allow-list.
3. `key_id` exists in the registry, is neither expired nor revoked.
4. `exp`/`iat` pass the expiry and window checks (§E1).
5. Replay cache misses on `(key_id, nonce)` (§E2).
6. Canonicalized payload hashes to `payload_hash`.
7. `sig` verifies over canonicalized envelope minus `sig`.
8. Only now: payload made available as **untrusted data**, tagged with its
   `provenance`; recipient's ordinary trust rules apply unchanged.

Disabled, unavailable or malformed verifier output cannot authorize anything
downstream — mirrors the S5a rule that missing evidence is not a pass.

## G. Operator approval tokens (separate mechanism)

1. **Shape:** a second signed object, an *approval assertion*: `v`, operator
   `key_id`, `action_type`, `action_digest` (SHA-256 of the canonicalized
   action request — target, parameters), `iat`/`exp` (short: minutes, not
   hours), `nonce` (single use), operator signature. Same canonicalization
   and key registry; different type field so the two objects are never
   confused.
2. **Binding:** an approval authorizes **exactly** the action whose digest
   matches — not a message, not a session, not a class of actions. One-time
   use with a durable spent-token store on the Mac; reuse → reject.
3. **Flow:** the operator mints an approval locally (operator-run tool, §H)
   for a specific high-impact action; the actor on the Mac checks it against
   the canonical action request at execution time. Cloud agents may *carry*
   an approval they were given; a cloud signature never *creates* one, and
   carrying one upgrades nothing else in the message (§A4).
4. A token bound to an action the operator has not seen specified is a
   verification failure, not a judgment call.

## H. Tool interfaces (stubs in this page only — no code in this PR)

Paper interfaces for the later build PR (s9-cloud-paseo B1.2: a signing tool
the cloud profile could ship **without** private keys or authority). argv
lists, JSON stdout, no shell strings; none of this exists yet:

| Interface | Signature (paper) | Notes |
|---|---|---|
| `ade-sign-message` | `--key-id K --exp SECONDS`, envelope fields via stdin JSON; emits signed envelope | Reads its private key through the secretspec path; refuses to run with no key registered. The cloud profile may install this binary with **no keys present**. |
| `ade-verify-message` | envelope on stdin; exit 0 → provenance/failure metadata JSON; nonzero → failure class (`version`\|`alg`\|`key`\|`expiry`\|`replay`\|`hash`\|`signature`) | Never prints the payload on failure; writes payload-free log records (§F). |
| `ade-sign-approval` | operator-run only; `--action-file` (canonical action request), `--exp SECONDS`; emits approval assertion | Guarded so only the operator path can mint (local registry check, not just convention). |
| `ade-check-approval` | assertion + canonical action request on stdin; exit 0 only on digest match, unspent, unexpired | Consumes the nonce durably on success. |
| `ade-sign-keys` | `list` \| `add --key-id --from-id --provenance --pubkey-file --expires` \| `revoke --key-id` | `add`/`revoke` require operator confirmation; no private-key import or export path exists. |

## I. Open questions (decided before any build PR)

1. Canonicalization recipe: own sorted-key rules vs RFC 8785 JCS (§C1).
2. Key registry storage: `config/` (reviewed, versioned) vs local state;
   and the out-of-band registration UX for a cloud instance's fresh key.
3. Expiry defaults per provenance class (is `cloud` shorter than
   `mac-local`?).
4. Whether approval assertions share the envelope version field or carry
   their own version line (§G1; lean: own line).
5. Replay-cache home per receiver (Paseo inbox store vs per-tool state).
6. Whether `relay` provenance needs a second signature from the relay
   itself, or is derivable (deferred to the transport weigh-in, D3).

## J. Transport neutrality and what this does not change

1. The envelope is self-contained: any transport — GitHub mailbox, Tailscale
   relay (vps-primary/Hyades), future Paseo remote, or a later WalkyTalky
   adoption — carries opaque bytes and cannot alter signed content without
   detection. The transport choice itself stays with s9-cloud-paseo **D3**,
   after this contract is reviewed; this contract predates it (contract §8
   ordering).
2. Nothing changes for existing readers: WalkyTalky, `paseo send`, dispatch
   footers and review tools are untouched (contract preamble: keep existing
   readers unchanged until adoption is reviewed). No message path on the
   Mac starts verifying these envelopes in this PR.
3. Threat anchors unchanged: [`docs/threat-model.md`](threat-model.md)
   cloud-agent push/PR threats and AGENTS.md Trust (outside artifacts are
   untrusted) apply verbatim to verified messages (§A, §F8).

## K. Exit criteria for the later build PR (what "B1 done" means)

1. Contract fields and canonicalization pinned as a checked-in **unsigned**
   example JSON Schema + golden fixture (no key material) — s9-cloud-paseo D1.1.
2. The §H tools implemented with the stub signatures above, installable with
   no keys; verifier exit codes and payload-free logging as specified (§F, §H).
3. Operator approval tooling local-only (§G, §H); cloud profile wiring stays
   out until s9-cloud-paseo D4's manifest work and the B3 headroom gate.
4. Still no transport, no mailbox/relay process, no routing row, no cloud
   launcher, no pairing — those gates live in s9-cloud-paseo C and D3-D5.

## Pointers

| Doc | Role |
|---|---|
| [`docs/setup-plan.md`](setup-plan.md) § S9.3-4, contract §8 | Authority: signing prerequisite, key rules, approval-token rule |
| [`docs/s9-cloud-paseo.md`](s9-cloud-paseo.md) B1, C, D1, D3 | Where this fits: prerequisite, non-goals, Phase-0 freeze, transport weigh-in |
| [`docs/threat-model.md`](threat-model.md) | Cloud-agent threats this must not weaken |
| [`docs/queue.md`](queue.md) Carried #24 | The *other* item 24 — unrelated, do not fold (contract §8) |
