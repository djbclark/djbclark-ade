# Integration backlog

Status: not started. Do not implement this unless the operator asks.

## Goal

One fallback system that is easy to query, easy to change, robust, and documented in the `fallback-chains` skill so a later request can find it.

Today there is no such system. Query means re-read the sources in `SKILL.md`. Change means edit Hermes config, LiteLLM config, or the two scripts, then update `inventory.md` in the same turn.

## What a single system has to cover

These are separate chains today. A unified query or edit has to know which layer it is talking about, or it will change the wrong one.

1. Hermes interactive `fallback_providers`, plus session pins that change only the primary.
2. Hermes cron fleet default, and the rule that a job pin drops that chain.
3. Hermes side routes: compression, MoA, `delegate_task`.
4. LiteLLM `router_settings.fallbacks`.
5. `herdr-ai` default-model fallback, which then walks a LiteLLM chain.
6. `acp-run` Claude transport fallback (not a model chain).

## Observed gaps

Recorded 2026-10-10 from the inventory. These are facts to design against, not an approved task list.

1. `grok-sub` / `xai-oauth` was removed from the Hermes interactive chain on 2026-10-06, but cron and most gateway sessions are pinned to xAI. The exclusion comment and the pins disagree.
2. MoA `default_preset: free-advice` does not exist. The only preset is `default`. MoA is enabled and is not the request path (`model.provider` is `cline2`).
3. `ai-model-switch.py` is disabled, but its candidate list can rewrite `fallback_providers` if the plist is loaded again. A unified system has to own that writer or keep it disabled on purpose.
4. A cron or `delegate_task` pin drops `fallback_providers`. A gateway session pin does not. The two rules are easy to mix up.
5. Thirty `no_agent` cron jobs do not call a model. Eighteen of them still store an unused model pin.
6. Compression has a pinned model and no LLM fallback. A stall uses the deterministic summary.
7. No single command lists or edits every layer. `hermes fallback list` covers only the Hermes interactive chain.
8. `route_agent.py` is a dispatcher, not a failure chain. Do not fold it in by accident.

## Done

None.
