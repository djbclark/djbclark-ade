---
name: fallback-chains
description: >-
  Use when asked about fallback chains, including the web search and fetch
  failover ladder and its pause rule. Update snapshot.
---

# Fallback chains on this machine

Canonical source: `skills/fallback-chains/` in `~/src/djbclark-ade`.
Every TUI copy is a symlink through `skill-everywhere`. Edit only here.

`model-routing` chooses who runs a task. This skill is what runs when that
choice fails, plus every other chain that is not the Hermes request path.
Load both when a change touches either.

## Update rule

The files under `references/` are a dated snapshot, not the live chain.
Before answering a fallback question, or after changing any chain:

1. Re-read the live sources in Quick Reference. Do not answer from the snapshot alone.
2. If a live source differs from `references/inventory.md`, update that file in the same turn and set its date.
3. If the change is a step toward the single-system goal, record it in `references/integration.md` (done, dropped, or still open). Do not start that work unless asked.
4. After a chain change, run `python3 scripts/check.py` from this skill directory. It prints the live layers and exits non-zero on a cycle, a same-vendor pair, a missing MoA preset while MoA is on, or a second writer. A non-zero exit is the remaining traffic-chain debt until that pass is asked for.

The web access chain has its own snapshot, `references/web-access.md`, with its own change list (its section 7). `scripts/check.py` does not cover it.

A chain change means any of: Hermes `model`, `fallback_providers`, `auxiliary`, `cron`, or `moa`; a cron job pin; LiteLLM `router_settings.fallbacks`; `herdr-ai`'s default-model fallback; `acp-run`'s transport fallback; enabling or disabling `ai-model-switch`.

## Quick reference

Re-read these. Extract provider, model, effort, and thinking only. Do not copy secrets, keys, or URLs that embed credentials.

1. `~/.hermes/config.yaml` — `model`, `fallback_providers`, `agent.reasoning_effort`, `auxiliary`, `cron`, `moa`.
2. `~/.hermes/cron/jobs.json` — agent jobs: `provider`, `model`, `no_agent`, enabled. A pinned job does not walk `fallback_providers` (`cron/scheduler.py`).
3. `~/.litellm/config.yaml` — `router_settings.fallbacks` and any per-hop `reasoning_effort`.
4. `~/src/djbclark-ade/bin/herdr-ai` — `fallbacks` / `ask_model`. Default model only; an explicit model does not fall back.
5. `~/src/djbclark-ade/tools/acp-run/acp-run` — `fallback_cli`. Transport retry, not a model chain. `--no-fallback` disables it.
6. `launchctl list | rg 'ai-model-switch|litellm'` — the switcher is a chain only if its plist is loaded. A `.disabled` plist is dormant. As of 2026-10-10 the script also refuses to write `model` or `fallback_providers`.
7. `python3 ~/src/djbclark-ade/skills/fallback-chains/scripts/check.py` — query command. Exit 0 is clean. Exit 1 is a cycle, a same-vendor pair, MoA on with a missing preset, or a second writer.
8. Hermes gateway session pins, when the question is about live chats: `~/.hermes/state.db` table `sessions`, column `model_override`. Counts only. A session pin changes the primary; it does not drop `fallback_providers` (that drop is the cron and `delegate_task` rule in `scoped_fallback_chain`).

There is no separate version field. The model id is the version. List effort and thinking only where a config or source field sets them. `agent.reasoning_effort` is global, not per hop.

## Current shape

Six live layers, not one system. The dated tables are in `references/inventory.md`.

1. Hermes interactive failure chain, plus gateway session pins that change only the primary.
2. Hermes cron: unpinned agent jobs walk the fleet default then `fallback_providers`; a pin does not.
3. Side routes: compression pin, MoA (configured, not the request path), unpinned `delegate_task`.
4. LiteLLM `router_settings.fallbacks`, its own chains.
5. `herdr-ai` default-model fallback, which then walks the matching LiteLLM chain.
6. `acp-run` Claude transport fallback only.

`route_agent.py` scores which agent to dispatch. It is not a failure chain.

## Web access chain

Snapshot: `references/web-access.md` (2026-10-11). Live check: `~/src/djbclark-ade/bin/web-get check`.

1. Each client walks its own ladder of web search and fetch providers (Exa, Parallel, Jina, built-in tools, the Crawl4AI MCP for JavaScript pages, the low-credit Firecrawl connector, Composio), then the shell ladder `web-get search|fetch` (on PATH; search exa → parallel → jina-mcp → jina-search → composio, fetch exa → parallel → jina-reader → crawl4ai → wayback), then the Wayback Machine and archive.today. Hermes has its own ladder.
2. One rung failing is fine if a later rung answers. `web-get` exit 5 means every provider failed.
3. **Pause rule (operator, 2026-10-11).** When the whole ladder fails for a page or search the task needs, pause the dependent work: stop scheduling dependent steps, checkpoint, report each failed URL or query with every rung's error, and wait for the operator or the provider. Never continue without the source, summarize from memory, or drop it. Detail: `references/web-access.md` section 1.

## Integration goal

The single system is not built. The 2026-10-10 safe pass turned MoA off, stopped `ai-model-switch` from writing the chain, cleared unused script-job pins, and added `scripts/check.py`. It did not change which model answers live traffic. The backlog is `references/integration.md`. Do not implement the traffic pass from this skill unless asked.
