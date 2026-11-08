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

The Pi SDK streamer-discovery repair is
[upstream PR 13](https://github.com/stnly/pi-grok/pull/13). Until upstream includes
it, the normal Pi package installation uses
`git:github.com/djbclark/pi-grok@fix/pi15-compat-loader`. This is a temporary fork
branch, not a version pin. Once upstream includes the fix, return to its normal
source through Pi's package manager, retaining the existing `xai-oauth` OAuth
credential and session history. Do not enable both copies of the extension.
The fix passed source review, full fork tests/typecheck, and an actual Pi SDK
load before installation; the later tool checks establish runtime use separately.

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

Grok and Antigravity remain manual service paths. Their successful basic checks
do not add them to `ade/auto`; named-pool freshness, identity, failure handling
and continuation acceptance must precede a routing-policy change.

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
is deliberately disabled; ClinePass remains reserved for Hermes/Hindsight.
These observations are dated acceptance results, not universal entitlement
or billing guarantees. Runtime profiles require their own smoke checks.

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
