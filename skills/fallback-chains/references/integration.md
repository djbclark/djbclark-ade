# Integration backlog

Status: safe pass done 2026-10-10. The traffic chain was not changed. Do not change which model answers live traffic unless the operator asks.

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
2. MoA is off the picker. `default_preset: free-advice` still does not exist. That is harmless while no preset is enabled. An explicit `/moa` still runs the aggregator.
3. `ai-model-switch.py` refuses to write `model` or `fallback_providers`. Its plist stays disabled. Loading the plist no longer makes it a writer.
4. A cron or `delegate_task` pin drops `fallback_providers`. A gateway session pin does not. The two rules are easy to mix up.
5. Thirty `no_agent` cron jobs do not call a model. The unused model pins were cleared to null on 2026-10-10. The keys remain. A null is not a pin.
6. Compression has a pinned model and no LLM fallback. A stall uses the deterministic summary.
7. `scripts/check.py` lists the live layers and exits non-zero on a cycle, a same-vendor pair, a missing MoA preset while MoA is on, or a second writer. It does not edit. On 2026-10-10 it exits 1 because of the chains the safe pass did not change.
8. `route_agent.py` is a dispatcher, not a failure chain. Do not fold it in by accident.

## Done

2026-10-10 safe pass. No hop in the interactive, cron, or LiteLLM chains was changed.

1. MoA preset `default` set to `enabled: false`. Phantom `moa.enabled` removed.
2. `ai-model-switch.py` refuses to write the Hermes chain. Plist was already disabled.
3. Eighteen unused `no_agent` cron pins cleared with `hermes cron edit --unpin`.
4. `scripts/check.py` added. It prints the layers and fails on the remaining cycles and same-vendor pairs.
