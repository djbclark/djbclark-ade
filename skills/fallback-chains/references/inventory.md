# Fallback-chain snapshot

Verified 2026-10-17 against the live sources in SKILL.md. Re-read those sources before using this file. If they differ, update this file in the same turn.

No hop has a separate version field. The model id is the version. Effort and thinking are listed only where a config or source field sets them. The only global effort knob is `agent.reasoning_effort: medium`.

## a. Hermes interactive failure chain

Source: `~/.hermes/config.yaml`. An unpinned session walks this when the primary fails. No per-hop effort or thinking field.

| Hop | Vendor | Model | Effort | Thinking |
|---|---|---|---|---|
| a1. Primary | xai-oauth | `grok-4.7` | medium (global) | not set |
| a2. Fallback 1 | cline2 | `cline2-pass/deepseek-v4-flash` | not set | not set |
| a3. Fallback 2 | xai-oauth | `grok-4.7` | not set | not set |

a4. Re-checked 2026-10-23 against `~/.hermes/config.yaml`: fallback 1 was `litellm-local` / `gemini-free-lite` until that day and moved to `cline2` deepseek-v4-flash (the gemini-free pool failed too often for side work; operator). A comment in the file says `xai-oauth` was removed from the chain on 2026-10-06; that comment is stale, since a3 is `xai-oauth`.

## b. This class of session pins

A `/model` pin changes the primary. It is not the cron/`delegate_task` rule that drops `fallback_providers`. Counts are from `~/.hermes/state.db` `sessions.model_override` on 2026-10-10 and will drift.

| Case | Count | Vendor | Model | Effort | Thinking |
|---|---|---|---|---|---|
| b1. Desktop chat that produced this snapshot | 1 | xai-oauth | `grok-4.7` | medium (global) | not set |
| b2. Gateway sessions | 82 | xai-oauth | `grok-4.6` | not set | not set |
| b3. Gateway sessions | 1 | xai-oauth | `grok-4.7` | not set | not set |
| b4. Gateway sessions | 1 | cline2 | `cline2-pass/deepseek-v4-flash` | not set | not set |
| b5. Gateway sessions with no override | 11 | follow a1–a3 | | | |

b6. No Hermes profiles exist (`~/.hermes/profiles` absent), so there is no second profile chain.

## c. Cron

Fleet default, used only by unpinned agent jobs: vendor `xai-oauth`, model `grok-4.7`. No per-job effort is stored. A job with its own provider or model is pinned and does not walk `fallback_providers`. Same-provider credential-pool rotation still applies. Source: `cron/scheduler.py` in the Hermes checkout.

| Job | State | Chain |
|---|---|---|
| c1. Gmail index twice-daily summary | enabled, unpinned | `xai-oauth` / `grok-4.7`, then a2–a3 |
| c2. Shizuku forks utilities add-ons Newsletter | enabled, unpinned | same as c1 |
| c3. memory-curator-decision-reminder | enabled, pinned | `cline2` / `cline2-pass/deepseek-v4-flash` only |
| c4. Memory curator (daily) | enabled, pinned | same as c3 |
| c5. Memory architecture research status watchdog | disabled, unpinned | would have been c1's chain |
| c6. Memory architecture v2 and Link spike status | disabled, unpinned | would have been c1's chain |

The other 30 cron jobs are `no_agent` scripts. They do not call a model. On 2026-10-10 the 18 that stored an unused `xai-oauth` / `grok-4.6` pin were cleared with `hermes cron edit --unpin`. The keys remain and the values are null. A null is not a pin. The two agent jobs above were not touched.

## d. Side routes that are not the main chain

d1. Compression is pinned to `cline2` / `cline2-pass/deepseek-v4-flash`, timeout 300. There is no `auxiliary.compression.fallback_chain`. A stall skips the model and uses the deterministic summary. No other auxiliary task is configured.

d2. MoA is off the picker. `moa.presets.default.enabled` is false, which is the flag Hermes reads. `default_preset` is still `free-advice`, and that preset does not exist, so Hermes resolves `default`. That is harmless while no preset is enabled. Interactive `model.provider` is `cline2`, not `moa`. An explicit `/moa` runs preset `default`: reference and aggregator are both `openai-codex` / `gpt-5.5`. The dead `opencode-go` / `kimi-k3` aggregator was removed on 2026-10-17. MoA stayed off: `litellm-local` / `clinepass-deepseek` fell through to reserve `grok-sub`, direct `cline2` returned HTTP 402, and `openai-codex` / `gpt-5.5` returned a model-entitlement rejection. Do not point this aggregator at `grok` or `copilot`; those are reserve pools.

d3. There is no `delegation` block. An unpinned `delegate_task` child inherits the parent's chain. A child given its own provider or model does not. Source: `scoped_fallback_chain`.

## e. LiteLLM proxy

Live under launchd `com.djbclark.litellm`. Re-read 2026-10-10. The earlier rows in this section listed gemini self-loops and `grok-4.6` hops. Those hops are not in the live file. Do not put them back without reading the file again.

Alias to model. Vendor is the model prefix or the API host. No secrets. Only `go-glm-flash` sets effort (`reasoning_effort: none`). `grok-4.20-0309-non-reasoning` is non-thinking by the model id.

| Alias | Vendor | Model |
|---|---|---|
| clinepass-deepseek | clinepass | `deepseek-v4-flash` |
| clinepass-minimax-m3 | clinepass | `minimax-m3` |
| clinepass-kimi-k3 | clinepass | `kimi-k3` |
| grok-sub | xai-oauth, via the local proxy | `grok-4.20-0309-non-reasoning` |
| gemini-free | gemini | `gemini-3.7-flash` |
| gemini-free-lite | gemini | `gemini-3.1-flash-lite` |

`watchdogd-mock` is defined and is not in any chain. `gemini-free` and `gemini-free-lite` have no fallback entry.

Each listed alias except those two falls back to the other real aliases, never to itself. The graph is still cyclic, because those lists point at each other. Consecutive hops often share a vendor. `scripts/check.py` exits non-zero on that. Those chains were not changed in the safe pass.

## f. Other agents

f1. `herdr-ai` falls back only for its default model, and only on a hard failure. The chain is `gemini-free-lite` → `gemini-free` → `gemini-free-lite`. That is a cycle. An explicit model does not fall back. No effort or thinking is set. Those two aliases have no LiteLLM fallback entry, so a LiteLLM failure of either alias stops there. `clinepass-*` is refused.

f2. `acp-run` has one transport fallback, not a model chain. A Claude ACP handshake failure retries as `claude -p`, keeping the requested model, or `sonnet` if none was requested. `--no-fallback` disables it. Every other agent has no CLI fallback.

## g. Looked at, not a live chain

g1. `ai-model-switch.py` is not a live chain. Its plist is `com.djbclark.ai-model-switch.plist.disabled` and launchd does not have it loaded. As of 2026-10-10 the script refuses to write `model` or `fallback_providers` even if the plist is loaded again. It can still print the pick it would have made.

g2. `route_agent.py` scores which agent to dispatch. It is not a failure chain, and it is not currently rewriting `fallback_providers`.

## h. Checker

`python3 ~/src/djbclark-ade/skills/fallback-chains/scripts/check.py` prints the live layers and exits non-zero on a cycle, a same-vendor pair, a missing MoA preset while MoA is on, a `no_agent` job that still stores a model id, or `ai-model-switch` being able to write the chain.

On 2026-10-10, after the safe pass, it exits 1. The remaining failures are the chains that were not changed: the Hermes `cline2` pair, LiteLLM same-vendor runs and a cycle, and the `herdr-ai` cycle. MoA and the second writer are clean.
