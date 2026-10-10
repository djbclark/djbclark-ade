# Fallback-chain snapshot

Verified 2026-10-10 by reading the live sources in `SKILL.md`. Re-read those sources before using this file. If they differ, update this file in the same turn.

No hop has a separate version field. The model id is the version. Effort and thinking are listed only where a config or source field sets them. Hermes global effort is `agent.reasoning_effort: medium`.

## a. Hermes interactive failure chain

Source: `~/.hermes/config.yaml`. An unpinned session walks this when the primary fails. No per-hop effort or thinking field.

| Hop | Vendor | Model | Effort | Thinking |
|---|---|---|---|---|
| a1. Primary | cline2 | `big-pickle` | medium (global) | not set |
| a2. Fallback 1 | cline2 | `cline2-pass/deepseek-v4-flash` | not set | not set |
| a3. Fallback 2 | opencode-go | `deepseek-v4-pro` | not set | not set |
| a4. Fallback 3 | openai-codex | `gpt-5.5` | not set | not set |

a5. `grok-sub` / `xai-oauth` is absent from this list. A comment in that file says it was removed on 2026-10-06. That comment is stale relative to cron and session pins, which do use xAI.

## b. This class of session pins

A `/model` pin changes the primary. It is not the cron/`delegate_task` rule that drops `fallback_providers`. Counts are from `~/.hermes/state.db` `sessions.model_override` on 2026-10-10 and will drift.

| Case | Count | Vendor | Model | Effort | Thinking |
|---|---|---|---|---|---|
| b1. Desktop chat that produced this snapshot | 1 | xai-oauth | `grok-4.7` | medium (global) | not set |
| b2. Gateway sessions | 82 | xai-oauth | `grok-4.6` | not set | not set |
| b3. Gateway sessions | 1 | xai-oauth | `grok-4.7` | not set | not set |
| b4. Gateway sessions | 1 | cline2 | `cline2-pass/deepseek-v4-flash` | not set | not set |
| b5. Gateway sessions with no override | 11 | follow a1–a4 | | | |

b6. No Hermes profiles exist (`~/.hermes/profiles` absent), so there is no second profile chain.

## c. Cron

Fleet default, used only by unpinned agent jobs: vendor `xai-oauth`, model `grok-4.7`. No per-job effort is stored. A job with its own provider or model is pinned and does not walk `fallback_providers`. Same-provider credential-pool rotation still applies. Source: `cron/scheduler.py` in the Hermes checkout.

| Job | State | Chain |
|---|---|---|
| c1. Gmail index twice-daily summary | enabled, unpinned | `xai-oauth` / `grok-4.7`, then a2–a4 |
| c2. Shizuku forks utilities add-ons Newsletter | enabled, unpinned | same as c1 |
| c3. memory-curator-decision-reminder | enabled, pinned | `cline2` / `cline2-pass/deepseek-v4-flash` only |
| c4. Memory curator (daily) | enabled, pinned | same as c3 |
| c5. Memory architecture research status watchdog | disabled, unpinned | would have been c1's chain |
| c6. Memory architecture v2 and Link spike status | disabled, unpinned | would have been c1's chain |

c7. The other 30 cron jobs are `no_agent` scripts. They do not call a model. Seventeen enabled ones still store an unused `xai-oauth` / `grok-4.6` pin, one paused job stores the same unused pin, and the rest store nothing.

## d. Side routes that are not the main chain

d1. Compression is pinned to `cline2` / `cline2-pass/deepseek-v4-flash`, timeout 300. There is no `auxiliary.compression.fallback_chain`. A stall skips the model and uses the deterministic summary. No other auxiliary task is configured.

d2. MoA is `enabled: true`, but `default_preset: free-advice` does not exist. The only preset is `default`, with references `openai-codex` / `gpt-5.5` and `opencode-go` / `deepseek-v4-pro`, and the top-level aggregator is `opencode-go` / `kimi-k3`. Interactive `model.provider` is `cline2`, not `moa`, so this is not on the request path.

d3. There is no `delegation` block. An unpinned `delegate_task` child inherits the parent's chain. A child given its own provider or model does not. Source: `scoped_fallback_chain`.

## e. LiteLLM proxy

Live under launchd `com.djbclark.litellm`. These are the proxy's own `router_settings.fallbacks`. Only one hop sets effort: `go-glm-flash` sends `reasoning_effort: none`. `grok-sub`'s model id is `grok-4.20-0309-non-reasoning`, so thinking is off by the model name. Nothing else sets thinking.

| Alias | Hops |
|---|---|
| e1. `gemini-free-lite` | `gemini` / `gemini-3.1-flash-lite` → `gemini` / `gemini-3.7-flash` → `gemini` / `gemini-3.1-flash-lite` |
| e2. `gemini-free` | `gemini` / `gemini-3.7-flash` → `gemini` / `gemini-3.1-flash-lite` |
| e3. `gemini-flash-lite` | `gemini` / `gemini-3.1-flash-lite` → `gemini` / `gemini-3.7-flash` |
| e4. `gemini-pro` | `gemini` / `gemini-3.1-pro-preview` → `gemini` / `gemini-3.7-flash` |
| e5. `go-glm-flash` | `opencode-go` / `glm-5.2` (effort none) → `opencode-go` / `kimi-k3` |
| e6. `go-kimi` | `opencode-go` / `kimi-k3` → `opencode-go` / `glm-5.2` |
| e7. `grok-sub` | `xai-oauth` / `grok-4.20-0309-non-reasoning` → `xai-oauth` / `grok-4.6` → `xai-oauth` / `grok-4.20-0309-non-reasoning` |
| e8. `grok-4.6` | `xai-oauth` / `grok-4.6` → `xai-oauth` / `grok-4.20-0309-non-reasoning` |
| e9. `grok-4.7` | `xai-oauth` / `grok-4.7` → `xai-oauth` / `grok-4.6` |
| e10. `grok-4.5` | `xai-oauth` / `grok-4.5` → `xai-oauth` / `grok-4.6` |
| e11. `grok-sub-reasoning` | `xai-oauth` / `grok-4.6` → `xai-oauth` / `grok-4.20-0309-non-reasoning` |

e12. `watchdogd-mock` is defined and is not in any chain.

## f. Other agents

f1. `herdr-ai` falls back only for its default model, and only on a hard failure. The chain is `gemini-free-lite` → `gemini-free` → `gemini-free-lite`. An explicit model does not fall back. No effort or thinking is set. Each hop then walks the matching LiteLLM chain in section e. `clinepass-*` is refused.

f2. `acp-run` has one transport fallback, not a model chain. A Claude ACP handshake failure retries as `claude -p`, keeping the requested model, or `sonnet` if none was requested. `--no-fallback` disables it. Every other agent has no CLI fallback.

## g. Looked at, not a live chain

g1. `ai-model-switch.py` is not running. Its plist is `com.djbclark.ai-model-switch.plist.disabled` and launchd does not have it loaded. Its candidate order is dormant code, not the live Hermes chain. Re-enabling that plist would make it a live writer of `fallback_providers`.

g2. `route_agent.py` scores which agent to dispatch. It is not a failure chain, and it is not currently rewriting `fallback_providers`.
