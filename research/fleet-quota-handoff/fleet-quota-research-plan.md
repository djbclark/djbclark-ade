# Fleet quota failure recovery — research plan

A. Scope and provenance

A1. Operator request: “Do a web search on best practices to handle when a rate or quota limit hits many paseo agents at a random point and another agent needs to do a handoff to another vendor of all of them without losing context and maintaining the communications they had with each other and trying to re-attach to any background processes, subagents, or acp agents connected with them. You are doing this research to hand off to Astra when you are done.”

A2. Snapshot: 2026-11-03. Deliverable: evidence-backed research and a self-contained Astra design-review handoff, not an implementation or live migration. No software installed; no task agents archived, interrupted, resumed, rerouted, or replaced. One separate Gemini local read-only audit was commissioned.

A3. Workspace: /Users/djbclark/src/djbclark-ade-fleet-quota-research-wt; branch research/fleet-quota-handoff; base 78aa363047e0b34a25bc19542dcbfc9bb5d8ec21; exclusive claim fleet-quota-research. The shared checkout has a foreign .gitignore edit; left untouched. Its stale, unrelated Tier 1 pointer was read, not resumed or rewritten.

B. Hypotheses and refutation

B1. A transcript-only vendor switch is insufficient for loss-aware recovery of a connected fleet. Refutation: a verified Paseo mechanism that transactionally transfers durable state, outstanding tool calls, peer routing and child ownership. Search found Continuity; examine its advertised boundary rather than assume it is complete.

B2. Separating logical task identity from provider session identity, plus durable checkpoints and a message ledger, can preserve recoverable task/communication state. Refutation: replay or ownership semantics that necessarily lose acknowledged work, duplicate side effects, or permit concurrent writers. Arbitrary unrecorded/private model state is explicitly outside the guarantee.

B3. Surviving jobs should be observed/rebound rather than relaunched. Refutation/limit: session-scoped terminal cleanup, destroyed parent runtime, missing job handles, PID reuse, provider-native opaque child state, or a process already dead. Classify each case rather than promise generic reattachment.

C. Method

C1. Standard-scope engineering research. Prioritize primary Paseo/ACP docs, framework persistence docs, vendor error semantics, and original tmux/reptyr documentation. Different frameworks are architectural analogies, not evidence of Paseo implementation.

C2. Lead live-search preflight passed: web-get search “RFC 9110 HTTP Semantics” through Firecrawl; opened https://www.rfc-editor.org/rfc/rfc9110.html through exa-api (full response saved initially to /tmp/quota-rfc-probe.json). PROBE-OK https://www.rfc-editor.org/rfc/rfc9110.html | RFC 9110: HTTP Semantics.

C3. Search MCP tools were not exposed to this Pi session. Used ADE bin/web-get, whose search selected shared Firecrawl and whose fetch selected exa-api. Search responses and provider attempt metadata are saved under searches/ and sources/. Search logs are the exact `target` strings in searches/s*.json; fetch timestamps are file provenance plus evidence date_fetched. No snippets are cited as evidence. Some site-filtered results were poor/noisy; only fetched primary pages support claims.

C4. Cost/scope choice: no all-vendor fan-out. Lead performs web retrieval/synthesis; one Gemini 3.8 Flash high local capability audit via acp-dispatch; Astra is intended for subsequent frontier design review. Local audit does not perform web research and is not an independent web-source review. Formal full research-skill multi-role/Grok adjudication is not claimed.

C5. Tool-use lessons applied to this run: web-get fetch does NOT have --out; inspect its local parser usage before supplying flags, and persist JSON via a subprocess file handle. Long dispatch preflight/fetch operations must be backgrounded with a PID and durable receipt, even when --detach --no-wait is requested. A timed-out wrapper is not proof of completion or absence; inspect durable record/marker before any read or retry. No pipe-based exit-status interpretation.

D. Verification and limits

D1. Quote checks use saved full fetched text, reference/claim coverage checks and counter-evidence notes. No live fault injection, fleet migration, process reparenting, or provider adoption test was authorized or attempted. Research is not proof of installed capability.

D2. Continuity repository README and official plugin catalog page were both fetched and saved. They agree on bounded context transfer to a same-workspace fresh agent; neither establishes fleet-wide ownership transfer. Report is not auto-opened: the current explicit-open-only standing rule takes precedence over older report-skill open behavior.

D3. The existing queue item “Quota-aware automatic cross-vendor subagent routing” is related, not proof of existing fleet disaster recovery. Stale Orca guidance in that historical entry must not be revived.
