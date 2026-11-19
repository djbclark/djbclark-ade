# Finite directory SDK adaptation (source preparation)

The deployed entry still uses the ordinary implementation. `semantic-hooks.mjs`
contains the asynchronous business callbacks for the finite seven-operation SDK.
It accepts its operation function only from a fixed source route; hook payloads
cannot select commands, imports, environment or facts. `lazy-hooks.mjs` registers
hooks synchronously and returns an immediate disposer; loading waits until an
actual event, rejected loading is sticky, and effects are awaited.

Ordinary hosts retain their existing behavior. Absent/undefined or false
`managedSource` is ordinary compatibility data. A nonboolean value refuses;
true selects only the SDK once the selected namespace is integrated. That flag
is never native authority. The selected private namespace must independently
refuse raw process/import escapes even when source metadata is missing or copied.
The SDK export at Paseo f48ab405e228136e5393e0e4bc4eb3d5ed9edaa4 exists,
but its new selected producer/namespace is pending; executable entry wiring is
therefore held. No raw fallback after SDK/proof failure is permitted.

Business callbacks preserve mode rereads, unowned new claims, ownership checks,
awaited create/install order, open-before environment patches, owner binding and
archive release. Unknown results escape without replay or compensation after a
possible write. Install business refusals retain the old soft-failure behavior.
Registry reads use the strict selected dispatcher through the SDK; the ordinary
implementation retains its historical tolerance.

Tests use explicitly synthetic sealed files and descriptive SDK results. They
provide business/control-flow regression evidence only, never native owner,
Python closure, helper settlement or feature qualification evidence.
