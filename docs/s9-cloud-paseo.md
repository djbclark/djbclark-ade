# S9 cloud agents ↔ Paseo: design slice (no live wiring)

Snapshot **2026-11-10**. Design and phased-experiment planning only.
Authority for the product intent remains
[`docs/setup-plan.md`](setup-plan.md) **§ S9** ("Cloud agents talk to Paseo
agents, and Paseo agents run them") plus implementation contract **§8**
("S9 signing prerequisite"). This page does not replace that section; it
scopes what a first design PR may hold and what must wait.

**Status:** design. No install profile, no inbound mailbox or relay, no
Paseo provider or skill that starts a cloud agent, no routing-table row, no
daemon pairing, and no message-signing private key. Build of any of those
waits on the prerequisites below and on operator headroom.

## A. What S9 is (cite)

From [`docs/setup-plan.md`](setup-plan.md) S9 (operator, 2026-11-07; plan
now, build last, only with headroom):

1. **Outbound:** Paseo agents start and manage cloud agents (Cursor Cloud,
   Claude Code cloud, Codex cloud) through thin, Paseo-callable tools
   (start / status / send / stop / fetch-result). `bin/cursor-cloud`
   (2026-10-20) is the existing Cursor model; the others are still to be
   checked for reachability from the Mac.
2. **Inbound:** cloud agents cannot reach the Mac's Paseo daemon, so they
   need a mailbox (private GitHub), a controlled relay (vps-primary /
   Hyades over Tailscale), or a future Paseo remote/relay feature.
3. **Signing:** every message uses the agent-to-agent scheme decided for
   **item 24** (signed messages plus separate operator approval tokens for
   high-impact actions). Cloud messages carry provenance and never count
   as operator approval.
4. **Optional later weigh-ins:** (a) a stripped `just install --profile
   cloud` with no secrets, keys, or scheduled jobs; (b) a Paseo daemon
   inside each cloud instance paired as a remote host — experiment only,
   adopted only if pairing stays within signed-message authority.

Contract §8 (same file): “Item 24” in S9 means the **operator's planned
signed-agent-message contract**, not Carried #24 in `docs/queue.md`
(dynamic model/effort by token efficiency). Versioned sender/provenance,
recipient, payload integrity, expiry and replay handling must exist before
choosing a transport. A cloud signature authenticates a message, not an
operator approval.

## B. Prerequisites (hard gates)

Nothing in S9 installs, routes, or experiments for real until all of these
are true. Paper design (this page) may land earlier.

### B1. Item-24 message signing

1. A versioned signed-agent-message contract is written and reviewed
   (sender identity, provenance label, recipient, payload integrity,
   expiry, replay handling).
2. A signing **tool** exists that the eventual cloud profile could ship
   **without** private keys or authority (setup-plan S9.4a / contract §8).
3. Separate **operator approval tokens** are defined for high-impact
   actions; cloud signatures never substitute for them.
4. No operator or shared signing private key is ever shipped into a cloud
   instance.

Until B1 lands, inbound and outbound message paths stay design-only.

### B2. S5a deferred (2026-11-08)

1. Setup-plan originally ordered S9 after the injection-classifier gate
   (**S5a**). The 2026-11-08 operator ruling deferred new prompt-injection
   **security implementation** (`docs/setup-plan.md` "Current operator
   policy"; queue Carried #35; `docs/tui-security-and-pi-migration.md`).
2. **Consequence for this slice:** do not start S5a construction, reader
   adoption, or fleet-watch hold wiring here. Keep S5a's typed-verdict /
   action-matrix contracts (setup-plan implementation contract §6) as
   **design dependencies** that a later S9 build must still respect when
   security work is un-deferred: cloud-sourced text stays untrusted;
   classifier output never becomes trust or operator approval; disabled /
   unavailable / timeout / malformed gate output cannot authorize
   high-impact dispatch.
3. Un-deferral of S5a (or an explicit operator rewrite of the S9 order)
   is a prerequisite for any S9 phase that carries untrusted outside
   content onto Mac agents or fleet upstream paths.

### B3. Headroom gate

1. Setup-plan S9.3: build only if the plan's **headroom** allows;
   otherwise S9 stays a plan.
2. Headroom here means spare capacity after S1–S8 (and any un-deferred
   security work), not a quota percentage alone: operator judgment that
   the lead and the machine can absorb another subsystem without starving
   Pi acceptance, install/reconcile, or merge-gate work.
3. No agent opens an S9 implementation PR, install recipe, or routing
   change without that explicit headroom yes. This design PR is not that
   yes.

### B4. Ordering reminder

S9 stays **last** after S1–S8, item-24 signing, and S5a (when not deferred
away). Earlier setup slices may continue; they must not quietly absorb S9
live wiring.

## C. Non-goals (this PR and until prerequisites clear)

1. **No live wiring.** No mailbox poller, Tailscale relay, webhook, or
   Paseo plugin that delivers cloud → Mac messages.
2. **No install.** No `just install --profile cloud`, no cloud setup-hook
   recipe, no secrets or keys in a cloud image.
3. **No routing.** No new `config/routing.toml` / effective-config service
   row that dispatches to a cloud agent as a Paseo provider; no change to
   `route_agent.py` Choice.dispatch for cloud beyond the existing
   documented `cursor-cloud launch` template.
4. **No new cloud launchers.** Claude Code cloud and Codex cloud wrappers
   are not added here; reachability checks stay future work.
5. **No daemon pairing.** No Paseo remote-host experiment against a cloud
   container; no pairing credential minted.
6. **No APPROVE / merge from the drafting agent.** Owner and adversary
   review remain the merge gate; this page is documentation.
7. **No claiming Carried #24.** Dynamic model/effort (queue #24) is a
   different item; do not fold it into S9 signing work.

## D. Phased experiments (paper only — do not install or route)

Each phase is a **design / probe write-up**. Running it for real requires
B1–B3 (and for content-bearing paths, B2 un-deferred or rewritten). Exit
criteria are what a later build PR must prove; this slice only names them.

### D1. Phase 0 — Contract freeze (docs / fixtures only)

1. Freeze the item-24 message schema fields (version, sender, provenance,
   recipient, payload hash, issued/expiry, nonce) as a checked-in example
   JSON Schema or golden fixture — **unsigned**, no key material.
2. Document the provenance labels cloud vs Mac vs operator-token.
3. Exit: schema reviewable without a transport; CI may validate fixture
   shape only.

### D2. Phase 1 — Outbound surface inventory (read-only probes)

1. Document the existing Cursor path: `bin/cursor-cloud` verbs (launch,
   status, list, models, run, usage), `autoCreatePR` always false, key
   via `sudo-secretspec` only (`tests/test_cursor_cloud.py` pins).
2. Paper checklist for Claude Code cloud session API and Codex cloud:
   create / send / archive or equivalent; whether the Mac can reach them;
   what identity they present.
3. Sketch the thin Paseo-callable tool shape (argv list, JSON stdout, no
   `shell=True`) without implementing it.
4. Exit: a comparison table with dated probe results; still no skill and
   no provider registration.

### D3. Phase 2 — Inbound path weigh-in (design choice, no deploy)

1. Compare mailbox-on-GitHub vs controlled relay vs future Paseo remote
   against: latency, blast radius if a cloud agent is prompt-injected,
   whether signatures verify before any Mac agent sees the body, and
   whether high-impact actions still need a separate operator token.
2. Require fail-closed behavior when signature, expiry, or replay checks
   fail.
3. Exit: a written pick (or explicit defer) with threat notes tied to
   `docs/threat-model.md` §4.4; no poller or relay process started.

### D4. Phase 3 — Cloud install profile sketch (manifest only)

1. Draft the component list for `just install --profile cloud`: AGENTS.md,
   skills, policy readers, `adversary_marker.py`, review-launch, the
   item-24 **tool binary with no keys**.
2. Explicitly exclude: secrets, operator keys, scheduled jobs, Mac-only
   screen/daemon tools, any path that could approve Mac agents.
3. Exit: a profile table in-repo; no `just` recipe that applies it.

### D5. Phase 4 — Daemon pairing experiment (gated, optional)

1. Only after B1–B3 and a written scope that pairing cannot start, steer,
   or approve Mac agents beyond signed provenance-labelled messages.
2. Open questions from setup-plan S9.4b remain open until probed: outbound-
   only pairing through egress proxies; short-lived container lifetime;
   what the pairing credential can do on the Mac daemon.
3. Reject any pairing that exceeds signed-message authority (contract §8).
4. Exit: adopt or abandon with dated evidence; default remains S9 items 1
   and 2 (tool + inbound path) without a cloud-side daemon.

## E. What already exists (do not re-invent in S9)

1. **`bin/cursor-cloud`** — Cursor Cloud Agents launcher; lead opens PRs,
   cloud agent does not (`autoCreatePR` false).
2. **`route_agent.Choice.dispatch`** — already emits a
   `cursor-cloud launch --repo … --ref … --prompt-file …` template for the
   `cursor-cloud` service row; that is documentation of today's path, not
   S9 completion.
3. **Trust rules** — GitHub artifacts and cloud-agent text are untrusted
   input (AGENTS.md Trust); S9 must preserve that, never weaken it with a
   signature-as-approval mistake.

## F. Pointers

| Doc | Role |
|---|---|
| [`docs/setup-plan.md`](setup-plan.md) § S9, contract §8 | Product intent and signing prerequisite |
| [`docs/queue.md`](queue.md) Carried #35 | Setup plan home; S9 last / headroom |
| [`docs/tui-security-and-pi-migration.md`](tui-security-and-pi-migration.md) | 2026-11-08 security deferral |
| [`docs/threat-model.md`](threat-model.md) | Cloud-agent push / PR threats |
| [`docs/orchestration-practices.md`](orchestration-practices.md) | When cloud agents are an option for slices |

## G. Recommendation

Keep S9 as a **deferred build**. Land design and Phase-0 fixtures when useful;
do not start Phases 1–4 for real until item-24 signing exists, S5a is
un-deferred or the operator rewrites the order, and headroom is explicitly
granted. Prefer finishing S1–S8 and Pi acceptance work first.
