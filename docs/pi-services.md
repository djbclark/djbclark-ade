# Pi service compatibility

Snapshot: 2026-11-08. Pi is the general-purpose third-party TUI; vendor
clients remain where their monthly plans require them. Hermes is unchanged.
Codex subscription access and OpenAI API credits are separate pools.

## Cursor through its vendor CLI

Install the latest `npm:@netandreus/pi-cursor-provider` using `pi install`.
The extension uses Cursor's own CLI login and executes its tool loop inside
that child CLI. Pi tool hooks do not observe that inner tool loop. This is
functional integration, not an additional security boundary.

Set `CURSOR_AGENT_PATH` in the Pi runtime environment to the absolute path of
`bin/pi-cursor-agent`. The launcher adds Cursor's documented `--force` only
for print-mode requests, retaining explicit denials, model selection,
workspace, and cached CLI authentication. Catalog/login commands are unchanged.
Do not inject `CURSOR_API_KEY` into this bridge: its upstream catalog code
puts that environment value in command arguments. Use the retained CLI login.
Normal `cursor-agent` must be on PATH; no binary or version path is pinned.

## Grok subscription through Pi and the vendor ACP client

2026-11-08: both paths completed a bounded request with actual file read/write
operations. Pi used `xai-oauth/grok-4.7-build-fast`; the official Grok Build ACP
client used `grok-4.7-build-fast`. Pi's `pi-grok` OAuth extension explicitly
uses Grok's subscription gateway, `cli-chat-proxy.grok.com`, rather than the
xAI API-key endpoint. The operator restored Grok Build as a manual vendor-plan
path on 2026-11-08 to use the remaining allowance of the cancelled SuperGrok
subscription. Its [official announcement](https://x.ai/news/grok-build-cli)
documents subscription access and ACP support. The `grok` entry remains in
`never_route` ([routing policy](model-routing.md), B10); restoring access does
not renew the cancelled plan or authorize automatic dispatch. The two clients
consume the same subscription pool;
they are not two allowances. An API key or separate API credits are a different
pool. Successful requests do not measure the exact debit or qualify every model.

The Pi SDK streamer-discovery repair was
[upstream PR 13](https://github.com/stnly/pi-grok/pull/13), merged 2026-11-08 and
released in pi-grok 0.13.1 (`dd01214`). On 2026-11-10 the Mac returned to the
normal source `git:github.com/stnly/pi-grok` through Pi's package manager
(`pi remove` of the temporary fork branch, then `pi update`), keeping the existing
`xai-oauth` OAuth credential and session history. Only one copy of the extension
is installed; the temporary fork has been archived and is no longer referenced.
After the switch, `pi --list-models grok` lists the `xai-oauth` Grok models, and a
non-interactive `pi -p --model xai-oauth/grok-4.7` request authenticated and
reached xAI, which answered 402 "Grok Build usage balance exhausted"; that is a
subscription balance state, not a login or extension failure.

## Antigravity through Pi

2026-11-08: `pi-antigravity` was installed normally, Google OAuth completed, and
`antigravity/gemini-3.8-flash` completed a bounded native Pi read/write task.
The provider uses its own normal Google sign-in; this does not convert the
Google subscription into Gemini API-key credits. Do not count the Pi client as
a second Google AI Pro allowance. Treat its use as sharing subscription capacity
with the native `antigravity-argon` gated frontier fallback until account and
model-window quota mapping establish otherwise; manual Pi work can consume
headroom needed by that fallback. The basic check did not verify separate
Flash/Argon windows. The check does not establish
continuation/resume reliability, comparative coding quality, every model's
entitlement, or a measured subscription debit.

The installed package reports a TypeBox dependency warning under Pi 1.5.
The issue is tracked upstream in
[issue 116](https://github.com/Rahularya01/pi-antigravity/issues/116) and
[issue 119](https://github.com/Rahularya01/pi-antigravity/issues/119).
The provider loaded and the task succeeded despite the warning; it was neither
suppressed nor fixed by editing the installed package. Keep optional search and
image resources disabled unless separately chosen.

2026-11-21 (operator): Antigravity is off Pi. "I think we need to keep the antigravity paseo provider/agy, Pi only seems to work with agy API pre-paid money or something. For now we should remove antigravity from pi and route to the native antigravity adapter in paseo." `[pools.antigravity] accepted = false` in `config/pi-pool-acceptance.toml`, `route_agent.provider_models("pi")` drops every `antigravity/*` id (`PI_EXCLUDED_NAMESPACES`), `bin/pi_defaults.py` skips one, and no Pi `[[service]]` names one; all Antigravity routing is the `antigravity-neon` and `antigravity-argon` services on Paseo's native `antigravity` provider (`docs/model-routing.md` B7, B7a). The paragraph below is the 2026-11-19 evidence, kept as history.

Grok remains a manual service path. Antigravity was accepted for automatic routing
since 2026-11-19 (`config/pi-pool-acceptance.toml`), on this evidence: a fresh
`aiuse sample --force` antigravity reading (Gemini 5-hour 4.8 %, weekly 3.4 %), model
identity confirmed in both `pi --list-models` and `paseo provider models pi`
(`antigravity/gemini-4-neon`, 1M context / 262K output, tools and reasoning enabled),
and clean failure handling — a Neon turn that the backend refused ended with one
specific `Antigravity API error … Resource has been exhausted`, not a hang or a
silent success. Continuation on Neon specifically is **not** re-verified: Neon was
out of quota at review time, so the older 2026-11-08 bounded native task remains the
continuation evidence. Re-check continuation after a Neon quota reset. Grok keeps
the stricter gate: named-pool freshness, identity, failure handling and continuation
acceptance must precede any routing-policy change there. `bin/ade-pi-pools check`
and `bin/pi-default` refuse automatic routing to an unaccepted pool
([dynamic defaults](pi-defaults.md) B4).

## SIPB's 32k context

Install `pi-extensions/service-context/index.mjs` as a Pi extension through
Pi's configured extension paths. For provider ID `sipb` only, its
`before_agent_start` handler omits the optional skill catalog from the
structured prompt. AGENTS/context files, custom and appended instructions,
MCP sections, and the active tool selection remain intact. Skill files remain
available through file tools; only their large automatic catalog is omitted.
This changes prompt size, not filesystem, process, or network authority.

Declare the actual model context as 32768 and a bounded output allowance.
Use the existing authenticated SIPB proxy if its protocol adaptations are
needed. Never inflate the advertised window to bypass a context error.
Pi's compaction check precedes this hook; the hook is not a replacement for
compaction or a guarantee that an arbitrary task will fit. Launch a fresh
session when first selecting this profile and validate actual request usage.
Serialize SIPB inference on its shared GPU; a model catalog is not inference
acceptance. No proxy service or credential is installed by this module.

## Evidence and remaining limits

The migration investigation established native Pi tool/report completion for
Go, Z.ai, and DeepSeek, and Google tool calls followed by a later completed
response. Google free-tier multi-step runs need pacing. OpenAI API spending
and Anthropic API balance were independently blocked; their vendor monthly
pools are separate. Zen free rejected its free quota. OpenRouter's tested
shared free models did not establish a reliable task loop. Venice spending
is deliberately disabled; ClinePass automatic spending remains reserved for
Hermes/Hindsight (manual Pi exception below).
These observations are dated acceptance results, not universal entitlement
or billing guarantees. Runtime profiles require their own smoke checks.

## ClinePass emergency manual access (2026-11-15)

The operator authorized manual Pi selection of the primary ClinePass account.
`pi-extensions/clinepass/index.mjs` registers provider `clinepass`, using Pi's
built-in OpenAI Chat Completions streamer against `https://api.cline.bot/api/v1`.
It resolves `CLINE_API_KEY` through `sudo-secretspec` at request time. No key is
stored in settings or source. The operator subsequently authorized the second
account: provider `clinepass-t-e` resolves only `CLINE_PASS_KEY_2_TE`. Select
`clinepass-t-e/cline-pass/deepseek-v4.1-flash` for that account. Both provider
identities persist in session history; neither switches accounts automatically.
The t-e account also passed native read/write tools and a saved-session
continuation using DeepSeek V4.1 Flash.
Missing credentials, authentication failures and exhausted balance are visible
Pi errors, without switching to another provider.

The 15 text/tool model definitions in `pi-extensions/clinepass/models.json` are
from [Cline's generated subscription catalog](https://github.com/cline/cline/blob/main/sdk/packages/llms/src/catalog/catalog.generated.ts),
checked 2026-11-15 against its [ClinePass guide](https://docs.cline.bot/getting-started/clinepass).
They retain the literal `cline-pass/` wire namespace and published context/output
limits. Input is conservatively text-only; image support is not qualified here.
Zero cost metadata denotes subscription billing, not unlimited quota or measured
debit. General `/models` discovery includes pay-as-you-go models and is not used
as subscription entitlement evidence. Catalog membership does not establish
account-level availability of every model; the live check used DeepSeek only.

Add this extension's absolute `index.mjs` path to Pi's user extension list using
its public `SettingsManager` (`getExtensionPaths`, `setExtensionPaths`, `flush`),
preserving all other settings. Explicit CLI selection is
`pi --provider clinepass --model cline-pass/deepseek-v4.1-flash`;
Paseo's provider/model identifier is `pi/clinepass/cline-pass/deepseek-v4.1-flash`.
Existing interactive Pi sessions need `/reload` to discover the new extension.
No running agents are restarted. This does not change the new-session default.

ClinePass stays in `never_route` and out of ADE Auto (`route`/`plan` enforce both: `never_route` for the curated row since 2026-11-22, with the techno-euphora repo scope of [model-routing.md](model-routing.md) B8a as the one exception, and the `accepted = false` row of the Pi pool acceptance). The previous reservation
for Hermes/Hindsight continues to apply to automatic spending; this manual
exception spends the same subscription allowance. Rollback removes only this
extension path from the current extension list, retaining all later settings,
credentials and session history.

Live evidence: the primary key completed a streamed DeepSeek V4.1 Flash request;
a native Pi session executed `read` and `write` tools. The first response omitted
the source's trailing newline; a follow-up after reopening the saved session
corrected it byte-for-byte and recalled the earlier nonce. No other model is live-qualified.

## Optional SIPB request-shape diagnostics

Set `ADE_PI_REQUEST_METADATA_DIR` in the Pi process environment to an owned
private directory to record one atomic, mode 0600 JSON file per SIPB request.
The hook observes the final provider payload and does not change it. It saves
only model ID, stream flag, serialized byte count, per-role serialized content lengths,
tool names, max-token fields, backend context and reasoning effort. It saves
no prompt text, tool arguments, headers or credentials. Other providers and
sessions with the variable unset write nothing. A diagnostic write failure
prints a fixed warning and leaves the request intact. These measurements do
not prove how the remote server applies a requested context window.

Snapshot: 2026-11-08. SIPB responses and primitive tool execution worked, but
bounded task completion under the full ADE instructions did not pass on the
tested Qwen and Gemma profiles. Requesting a 32k backend context did not
establish a task-level repair. Keep this route out of automatic work routing.
An experimental post-tool task reminder was rejected after it repeated
completed work and review found stale-request behavior; it is not shipped.

## Three named OpenCode Go accounts (2026-11-15)

`pi-extensions/go-accounts/index.mjs` exposes three manual provider identities:

| Pi provider | Managed credential name |
| --- | --- |
| `opencode-go-djbclark` | `OPENCODE_GO_API_KEY_DJBCLARK` |
| `opencode-go-dclark` | `OPENCODE_GO_API_KEY_DCLARKUS` |
| `opencode-go-t-e` | `OPENCODE_GO_API_KEY_TECHNOEUPHORA` |

Select an account with Pi's model selector, for example
`pi --provider opencode-go-djbclark --model deepseek-v4.1-flash`.
Paseo uses `pi/opencode-go-djbclark/deepseek-v4.1-flash` (substitute the
other named account). Account identity is part of the saved model selection;
concurrent sessions can use different accounts without changing global auth.
No account is an automatic fallback and none is added to ADE Auto. Existing
unqualified `opencode-go` credentials/defaults and the retired OpenCode service
remain unchanged.

The extension reuses the installed Pi native Go provider: model metadata,
Go-specific session headers and all native streaming APIs are retained.
It resolves the host's public provider export through its package manifest
because Pi's source-extension loader aliases SDK roots but not subpath imports.
No second SDK copy, hard-coded version path or copied model catalog is used.
Each account resolves only its named key through `sudo-secretspec` at request
time; catalog enumeration does not read keys. Broker failures produce a fixed
account-labelled error rather than forwarding stderr or choosing ambient auth.

Add the extension's absolute path using Pi's public SettingsManager, preserving
the rest of the extension list and defaults. Existing sessions can `/reload`;
refresh Paseo's native provider snapshot for its selector. Rollback removes only
this extension path; retain credentials and session history.

`~/.local/bin/oc-go-key` resolves to the one-offs tool that changes the retired
OpenCode service's active Console credential. It is not a Pi account switcher.
[PR 481](https://github.com/djbclark/djbclark-ade/pull/481) archived that teaching.

Alternatives checked: [pi-account-switcher](https://pi.dev/packages/pi-account-switcher)
changes active runtime/global credential state;
[pi-multiprovider](https://github.com/monotykamary/pi-multiprovider) offers
session pinning and automatic cross-account failover. Neither is installed here:
this operator request enables explicit account access, preserving account boundaries
and existing managed-key ownership. Pi's own provider supports Go already, so
[pi-opencode-go-provider](https://github.com/monotykamary/pi-opencode-go-provider)
is not needed for transport. The [official Go guide](https://opencode.ai/docs/console/go/)
documents the current inference endpoints and subscription/Extra Usage distinction.

Live DeepSeek V4.1 Flash checks: djbclark and t-e authenticated and executed native
read/write tools, then retained their named identity after reopening saved
sessions and recalled the earlier nonce. dclark authenticated but returned a five-hour Go usage limit;
no Extra Usage setting was changed. The old and current usage GET paths returned
HTTP 403 from this machine, so no fresh numeric balance is claimed. Model
listing is not proof every listed model is entitled or currently usable.

## Durable extension installation paths (2026-11-16)

Install ADE extensions from the durable `~/src/djbclark-ade/pi-extensions/`
checkout, never from a task worktree. Pi settings retain absolute paths after
worktree removal, and Pi can silently omit those extensions. This removes their
providers from fresh Pi processes even while Paseo still shows cached models.
Use the public SettingsManager to replace only the stale entries; preserve
other settings, account identities and saved conversations. Reload existing Pi
sessions and refresh Paseo's provider snapshot after repairing paths.

Full `bin/ade-install doctor` checks explicit absolute and `~/` extension paths
in `~/.pi/agent/settings.json`. Missing targets or invalid settings fail doctor;
it never edits settings, loads extensions or reads credentials. Relative paths,
package sources, globs and enable/disable patterns remain Pi's responsibility.
This check detects missing targets, not provider health or quota exhaustion.

Settings, Paseo's model catalog and an already-running Pi registry are separate.
A catalog refresh does not reload extensions inside an existing Pi process.
For a stuck Paseo tab, first verify that it has no active turn or pending
permissions, then use the SDK's `refreshAgent(agentId)` to reopen that saved
session. This retains its agent/native-session identity and transcript; do not
send a probe prompt into the unfinished task or create a replacement tab.
Reapply the intended model and effort and verify the resulting snapshot.
`/reload` applies to interactive Pi; built-in TUI commands are not executed by
Pi's RPC `prompt` command.

`paseo provider diagnostic pi --json` refreshes the global model catalog.
Workspace catalogs are separate: refresh only the affected workspace with
`refreshProvidersSnapshot({cwd, providers: ['pi']})`, then compare its entries
with a fresh Pi catalog. Recurring catalog staleness is tracked upstream in
[getpaseo/paseo PR 7733](https://github.com/getpaseo/paseo/pull/7733).
