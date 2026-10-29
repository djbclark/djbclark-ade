# Native Go context guard — 2026-10-25

This is an OpenCode **V2** promise plugin (`id` + `setup`), using the native
session context/tool hooks, primary step events and safe-point compaction API.
It has no V1 adapter or runtime npm dependency. Its policy comes from
`../../config/go-model-policy.json`, resolved against the real plugin path.

| Model class | Warn | Compact after 32k growth | Handoff ceiling | Hard trigger |
| --- | ---: | ---: | ---: | ---: |
| Routine Go | 64k | 96k | 112k | 128k |
| Costly or unclassified Go | 32k | 64k | 80k | 96k |

These are conservative **local policy starting points**, not vendor defaults or
measured optimal thresholds. Count each fresh primary request's input plus cache
read/write tokens; ignore output, reasoning and lifetime totals. Nudges appear
once per tier. A five-minute cooldown, persisted pending requests and native
`session.compaction.ended` confirmation prevent repeated summary charges. After
compaction, less than 10% reduction or a still-over-hard-limit baseline stops
automatic retries. Unreadable state/event streams disable automatic writes;
uncertain writes wait for native confirmation. No global environment or last-seen
session guesses are used. Model and provider changes preserve session-level
pending, cooldown, failure and ineffective-compaction state; only model
measurements are reset. Non-Go periods disable automatic writes without
erasing the conversation's admission history.

## Automatic handoff trigger

At a **task boundary** (the native `session.idle` event, which carries no
`created` timestamp and is handled before the staleness guard), the guard
escalates an over-long session into a mandatory handoff directive when either
condition is met:

- the last measured input context meets the model class's **handoff ceiling**
  (112k routine / 80k advisory), or
- the session has completed `handoff_after_compactions` (2) compactions.

When due, the guard wakes the model with
`ctx.session.prompt({ prompt: { text }, delivery: "steer" })`, escalating the
wording across retries, and `onContext` surfaces a handoff-level notice into the
next request's system messages. The policy is validated once at load: a bad
`handoff_cooldown_seconds` (below a 300 s floor), `handoff_after_compactions`,
`handoff_max_wakes` or either `handoff` ceiling fails closed (no automatic
wake), and a malformed or unreadable persisted record does too. A wake is capped
at `handoff_max_wakes` (3) per session, is refused for a child (subagent) session
and for a session whose live model no longer matches the recorded Go model, and
is never sent in a dispatched slice (`ACP_RUN_AGENT=1`). A child or dispatched
session also never gets the mandatory directive in its context notice: it is
softened to a "finish and report back to your parent" wording with no "start a
fresh session" or lifecycle command, until a primary Go session is confirmed.
An ineffective-compaction (blocked) session is exactly the one that must hand
off rather than loop compactions, so handoff outranks `blocked` in the context
notice. The directive routes the model through the handoff skill and
`self-slash "/new"`; it never instructs a raw `/new`, `/clear`, `/reset` or
`--finish --successor`, and it always carries "Never clear a parent session".

## Install and activate

After the reviewed change is in the canonical checkout, link the directory into
OpenCode's user plugin discovery directory, preserving any existing entry:

```python
from pathlib import Path
source = Path.home() / "src/djbclark-ade/opencode-plugins/go-context"
target = Path.home() / ".config/opencode/plugins/ade-go-context"
target.parent.mkdir(parents=True, exist_ok=True)
if target.is_symlink():
    assert target.resolve() == source.resolve(), "existing plugin link differs"
elif target.exists():
    raise RuntimeError("existing plugin entry must be reviewed")
else:
    target.symlink_to(source, target_is_directory=True)
```

New OpenCode locations load it through V2 plugin discovery. Existing servers
may retain already-loaded plugins. Confirm setup with the read-only status RPC:

```bash
opencode api --standalone post '/api/rpc/ade.go-context/status?location[directory]=/absolute/project' --data '{"input":{"sessionID":"ses_probe"}}'
```

`output.ready: true` proves that this location loaded the guard; `known: false`
is expected for a nonexistent probe session. Status never looks up or compacts
the probe session. A cold `/api/plugin` listing may be empty before plugin
initialization; it is not sufficient negative evidence. Use status on the actual
server/location before relying on the guard. Do not restart a
server or interrupt another session to activate a cost guard. Installation and
native loading are separate evidence from offline guard tests.

The custom `ade_compact` tool uses the current native tool context's session ID.
The plugin never rewrites shell commands or registers an `execute.before` hook:
native command permission matching must see the original command. Permission
request lists are not effective rulesets. Use `ade_compact` for manual native
compaction; supported host controllers can pass an explicit validated session
and directory to the RPC helper without changing a shell permission resource.
Automatic, tool and RPC calls share one
admission check; an absent plugin fails closed. JavaScript/codemode tools use `ade_compact`; their source is never
rewritten. ACP launches scrub inherited native scope before creating the child.
`/new`, `/clear`, `/reset` and Claude-style compact focus text are refused by the
native path. At a finished-task boundary, write an owned durable handoff; cycle
to a new session only through a supported, acknowledged host controller.

This plugin controls context growth, not model entitlement. The expensive-model
advisory gate lives in `acp-dispatch` and `acp-run`; direct native UI selection
is outside that gate. Do not use native UI or `opencode run` to evade it.
Do not enable speculative background compaction or Go balance overage.

## Offline verification

Run `tests/test_go_context_plugin.py` through the repository's `bg`/CI workflow.
It executes `node --test` with fake native APIs, separate durable state and a
controllable clock. No paid inference or production compaction is needed.
Primary contracts: [compaction](https://opencode.ai/v2/docs/compaction),
[native plugin hooks](https://opencode.ai/v2/docs/build/plugins), and
[discovery](https://opencode.ai/v2/docs/plugins); checked against installed
OpenCode V2.1.4 and the current native SDK declarations on 2026-10-25.

The native RPC validator rejects JSON Schema regex patterns by default. Session
IDs are validated by the guard before any lookup/write; keep RPC transport
schemas simple. Verify the real RPC adapter, not only an SDK mock or cold
plugin listing, when changing this surface.

On 2026-10-25, OpenCode 2.1.4 also loaded the directory symlink through global
plugin auto-discovery in a fresh isolated HOME and returned `ready: true`,
`known: false` through the status RPC, without an explicit plugin config entry.
That probe made zero inference or compaction calls. Run local native probes as
targeted pytest tests through `bg`; a CI-first repository does not admit an
arbitrary Python script as a targeted test.

For admission diagnostics, use the structured `load-watch` fields (`load1`,
`per_core`, `cores`); the raw load average printed by a `bg` hold is not itself
a per-core reading.

On 2026-10-25, a second native OpenCode 2.1.4 read-only probe used the actual
`acp-run` sanitizer's temporary `OPENCODE_CONFIG_DIR`, with project config
disabled and only the trusted guard symlink retained. Native auto-discovery
returned `ready: true`, `known: false`; no inference or compaction was requested.
