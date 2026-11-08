# Dynamic Pi defaults

2026-11-08. Pi's `ade/auto` virtual model selects a **physical model and effort
for a task**, using the existing ADE routing policy and fresh named-pool quota.
It does not rewrite the global default on every request or interrupt a running
response. The virtual selection remains `ADE Auto`; the task's physical route
is stored in Pi's branch state, including across compaction and resume. An ADE-owned
custom entry supplies direct summaries without depending on Pi's internal state-entry tag.

## A. Operator interface

A1. Select `ade/auto` in Pi or the Paseo model selector. A new automatic session
starts with kind `code`. `/ade-task research` establishes an explicit next task;
other kinds are `code`, `bulk`, `mechanical`, `judgment` and `frontier`. A kind
without a qualified Pi route stops visibly instead of borrowing a weaker tier.

A2. `/ade-task code --native-tools` excludes vendor-CLI bridges. Cursor runs its
own inner tool loop, so it is unsuitable for work requiring Pi's direct tool
hooks. The command requires an idle session with no queued messages and sends
no model request. Ordinary follow-ups, steering messages, tool continuations
and retries are not task boundaries.

A3. Selecting a physical model pins it: automatic defaults do not change it.
Select `ade/auto` again to opt back in. In Paseo, use its native model selector
so its persisted settings agree with Pi. An internal model change that Paseo
does not observe can be superseded by old Paseo resume metadata; this extension
does not modify the native daemon to conceal that limitation.

A4. `bin/pi-default --kind code` prints a JSON decision without inference.
`--native-tools` requires direct Pi tools, `--exclude-service NAME` excludes a
pool, and `--models-json FILE` supplies available physical IDs (`-` reads stdin).
Without that list the command requests the normal native Pi catalog; catalog
inclusion is not entitlement proof and startup discovery can resolve configured
credential commands. Exit 0 means a choice, 1 no qualified route, 2 invalid or
unavailable input. JSON includes the pool, provider, physical model, thinking
level, reason and quota age; no credentials or provider error text.

A5. Ordinary router plans print native `paseo run --provider pi/PROVIDER/MODEL`
commands for Pi choices, translating explicit effort to `--thinking` and using
`--no-wait`. Append the task text, `--title`, an existing `--workspace` and the
matching session `--cwd`; put each assigned execution worktree in its brief.
The transitional `acp-dispatch` shim does not launch Pi.

## B. Model policy and reassessment

B1. Concrete profiles and fitness ranks remain in `config/routing.toml`. The
router already combines fitness, headroom, pace, expected unused capacity and
quality bands. Pi uses that same decision code. The startup choice is a policy,
not a fixed preference for Z.ai or whichever provider has the largest percentage.

| Qualified Pi path | Uses | Effort |
| --- | --- | --- |
| Retained Cursor CLI, Composer 2.5 | Code, research, bulk, mechanical when its inner tools are suitable | Provider-managed |
| Z.ai Coding Plan, GLM 5.3 Flash | Direct Pi code, research, bulk, mechanical | High for substantive work; low for mechanical |

B2. These are conservative fitness priors plus the recorded basic service
checks, not a comparative runtime benchmark. Cursor describes Composer 2.5's
improvements to sustained work and instruction following in its
[release report](https://cursor.com/blog/composer-2-5). Z.ai documents that Flash
receives three times GLM 5.3's Coding Plan quota and supports higher reasoning
effort in its [model documentation](https://docs.z.ai/guides/vlm/glm-5.3-flash).
[Artificial Analysis's measured comparison](https://artificialanalysis.ai/models/comparisons/glm-5-3-flash-vs-minimax-m3)
supports keeping Flash in the shortlist rather than replacing it with Minimax
merely because the latter also passed a smoke. None of these sources tests this
exact Pi/Paseo integration, and public token prices are not subscription costs.

B3. Judgment and frontier keep the stronger, separately metered vendor routes
and existing gates. No judgment qualification is inferred for the two Pi rows.
Go awaits account scoping. Grok subscription and Antigravity OAuth paths passed
basic native tool checks on 2026-11-08; their continuation, quota and routing
acceptance remain separate work ([service status](pi-services.md)). Neither is
added to this automatic shortlist by those checks. OpenAI API and Anthropic API
billing blocks remain separate from
Codex and Claude subscriptions. SIPB is parked. Disabled/reserved pools and
archived TUIs are never automatic fallbacks. Hermes's chain is unchanged.

## C. Failure and recovery

C1. Unknown, stale, incomplete or approval-required quota cannot qualify a
measured-only Pi profile. A missing physical model also excludes its route.
An explicit model pin remains explicit; this is automatic routing policy,
not a restriction on the operator's manual model selection.

C2. A confirmed quota or billing failure for the task's actual physical route
is observed from the persisted physical assistant error at the next request
boundary, even when Pi does not retry it. That request first latches the pool
off, then may select another qualified pool. A branch receipt prevents an old
error from re-latching a pool after explicit operator recovery. Generic transport failures, a bare 429, or quota
words in prompts/tool output do not justify spending a different pool.

C3. `bin/pi-default --block-service zai --reason quota` records the same latch
without inference. The state is locked and replaced atomically with mode 0600
at `~/.local/state/ade/pi-defaults/blocks.json`. It contains only pool, failure
class and timestamp. Both ordinary routing and ADE Auto honor it. Malformed
state holds Pi routes and is preserved for inspection.

C4. `bin/pi-default --clear-block zai` removes only that latch after the operator
has established recovery. A fresh positive balance does not by itself clear a
known enforced-spend block. No reset is invented from a retry backoff. Other
pools and unrelated state are retained.

## D. Rollout and rollback

D1. Load `pi-extensions/dynamic-defaults/index.mjs` by Pi's normal extension
settings, then make `ade/auto` the new-session default through the public
settings API. Existing sessions and physical selections stay in place; do not
restart paid work. Validate native catalog discovery, two-request choice
retention, an explicit new task and persisted resume before claiming live use.

D2. To roll back, restore the previous new-session default and remove only this
extension path from the current extension list. Keep later settings, physical
credentials, session history, failure latches and other extensions. The
recorded previous default for this rollout is Z.ai GLM 5.3 Flash, low.

D3. 2026-11-08 pre-install validation: a real installed-SDK canary retained
Cursor Composer 2.5 across two requests, selected Z.ai Flash low at an explicit
mechanical task with `--native-tools`, and retained that choice after reopening
the persisted session. This validates the extension through Pi's public SDK;
it does not claim the global default is installed or a Paseo resume is tested.

D4. 2026-11-08 activation: the reference checkout was fast-forwarded to merged
[PR 315](https://github.com/djbclark/djbclark-ade/pull/315), preserving its unrelated
Graft edits byte-for-byte under the operator's explicit approval. The public
settings API registered the extension and made `ade/auto` the new-session
default while preserving unrelated settings. Fresh normal Pi RPC startup
reported `ade/auto`; one ordinary CLI request without an explicit model selected
Cursor Composer 2.5 and completed successfully. This establishes the normal
startup path in addition to D3's SDK checks. Existing sessions were not restarted;
no native Paseo resume validation or additional pool qualification is claimed.

D5. 2026-11-08 native Paseo validation: a new Pi agent selected `ade/auto`,
completed a bounded file task through Cursor Composer 2.5, and ended idle.
Reloading its underlying Pi process retained the same agent, native session
file and virtual selection. A follow-up returned the test nonce from the
conversation; the saved task epoch, physical Cursor route and recorded effort
remained unchanged, with no Pi-native tool calls recorded in that continuation.
This establishes one native reload/resume path. Cursor owns its inner tool loop,
so this observation is not an independent audit of those tools or an acceptance
result for other providers. No additional pool or automatic route was enabled.
