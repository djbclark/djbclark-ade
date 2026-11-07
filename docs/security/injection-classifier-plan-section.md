# S5a draft: a typed classifier as an extra injection gate

This file holds the exact text proposed for a new `docs/setup-plan.md` section
**S5a**, to be inserted after S5. It is on this branch for review; folding it
into `docs/setup-plan.md` happens with the build PR. Written 2026-11-07, after
`docs/security/injection-classifier-eval-2026-11-07.md` (same branch) measured
the gate on real traffic shapes.

---

## S5a. A typed classifier as an extra injection gate

The hardening in S5 reduces who can write outside content; this section adds a
cheap probabilistic reader-side gate for the content that still reaches agents.
It is built and measured **before** the final code and security reviews of any
reader that gets it (the order the operator set 2026-11-07): a gate that has
not been measured on our own traffic is a false sense of security, not a gate.

1. **What the gate is.** `bin/ade-injection-gate` — one shared tool every
   outside-content reader calls (`fleet-watch`, `pr-policy`, `review-pr`,
   `skills/loose`, the Jira and firecrawl readers, and any agent brief that
   carries quoted outside text). It sends the text as `state` with one fixed
   `choice` question (injection vs benign, the eval's prompt shape) and
   returns the probability distribution, the `decide` at the thresholds
   below, and the latency. The classifier is Jev (TypeSafe hosted,
   `jev-latest`) — the only
   one of the three measured models that separates injection from benign text
   (2026-11-07 eval: 32% recall at the 0.9 bar, 1.3% FP, 163 ms p50, ~$0.00003
   per call). Kev-0.8B and Laya were measured near-chance on this task and are
   NOT used for the gate (they stay in their existing judgment roles). The
   classifier is probability-only, no tools, no text generation, so the
   payload can steer nothing (S3 of the eval: no tool-using model ever sees a
   payload).

2. **Thresholds (the skill's own).** Act only at `p(injection) >= 0.9`
   (treat as injected: strip, quarantine or refuse) or `p(injection) <= 0.1`
   (treat as ordinary text, still tagged untrusted — a low score is NOT trust).
   Between 0.1 and 0.9 the gate returns `escalate`: tag the text untrusted,
   add it to the shadow log, and let the reader's existing untrusted-data rules
   carry on. The gate never approves anything and never lowers a tag.

3. **Fail-closed rules.**
   - Classifier unreachable (the helper's exit 3, a restart window): the caller
     treats the text as **untrusted with the gate unavailable** — never as
     clean — and logs the miss; the S6 drift job alerts when the gate has been
     unavailable for more than 1 hour of calls.
   - Any error, timeout or malformed answer is the same as `escalate`, never
     `benign`.
   - The gate runs **before** the text enters an agent context, not inside it:
     the reader calls `ade-injection-gate` on the fetched artifact and passes
     on text + verdict + provenance, so even a wrong `benign` leaves the
     Trust-section rules (data, never instructions) intact.

4. **What it does per surface** (from the eval's per-surface results; the
   eval doc is authoritative for why):
   - **PR/issue bodies, titles and comments (own repos, S1.1-S1.3):** tag +
     shadow-log, not block — recall below the 0.9 bar means a block would
     create false confidence; provenance (`author_association`) stays the
     primary control.
   - **Dependabot PR bodies and CI logs (S1.4-S1.5):** tag; the gate's value
     here is triage ordering, not blocking.
   - **firecrawl / web-search results (S4.1):** tag; too high FP risk on
     ordinary technical text to block.
   - **CFEngine Jira text (S3.1):** tag + escalate-to-operator on
     `p >= 0.9`.
   - **fleet-watch notices (S1.7 upstream):** escalate on `p >= 0.9` — this
     is the zero-click dispatch path of Argon F-CRIT-1, so any confident
     injection verdict holds the dispatch for the operator.
   - **Agent-to-agent `paseo send` messages:** the gate does not mediate peer
     messages (trust model, AGENTS.md Trust); the `"djbclark approved"`
     chain is fixed out-of-band (F-CRIT-1), not by a classifier.

5. **Config (`config/ade.toml`).**
   ```toml
   [hardening.injection_gate]
   enabled = true            # false = pass-through with tag "unverified"
   model = "kev"             # jevlike alias; "jev" for latency-critical callers
   act_high = 0.9            # p(injection) >= this -> injection verdict
   act_low = 0.1             # p(injection) <= this -> ordinary text (still untrusted)
   model = "jev"             # jevlike-style alias for api.typesafe.ai; kev/laya measured unusable (eval 2026-11-07)
   fail_closed = true        # never false in production; tested in CI
   shadow = true             # log verdicts beside the reader's outcome
   surfaces = ["pr", "issue", "comment", "ci-log", "dependabot", "web", "jira", "fleet-watch"]
   ```

6. **S6 drift check for the gate.** `just harden-check` (S6) gains a
   `gate-health` probe: one benign canary text and one disclosed-payload
   canary (from the eval's corpus, ids recorded, payload text never committed)
   through `ade-injection-gate`; the check fails if the canary answers `benign`
   at `p <= 0.1`, if the benign canary answers `injection` at `p >= 0.9`, if
   latency exceeds `max_ms`, or if the gate is unreachable — so a silently
   degraded or switched-off gate is caught daily, not discovered during an
   incident.

7. **Order of work.** The gate is built and measured (the eval doc's method,
   rerun monthly on fresh benign traffic) **before** the final code and
   security review of each reader that adopts it; new readers adopt it at
   review time, not after.
