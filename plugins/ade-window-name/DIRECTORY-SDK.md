# Finite naming SDK adaptation (source preparation)

The deployed entry still uses the ordinary implementation. `window-workflow.mjs`
shares the actual asynchronous metadata and naming workflow between ordinary
`name-lib.mjs` and the prepared semantic callback factory. Metadata is reread
before decisions and before title changes. Explicit titles, first-agent checks,
background windows, retry decisions, dry runs and cancellation remain effective.
Title writes stay awaited. The semantic seam propagates SDK/proof errors and has
no raw process fallback.

`lazy-hooks.mjs` prepares synchronous registration and an immediate disposer;
it performs no helper or module loading until an actual event. This is not yet
wired into the entry: the committed public SDK export exists, but its selected
private producer/namespace isolation prerequisite remains pending. Absent/false
`managedSource` preserves ordinary compatibility; malformed values refuse. The
selected namespace must deny raw imports independently of this metadata.

The dedicated Linux CI includes ordinary naming tests and synthetic semantic
callback controls. These tests do not attest native namespace, Python/helper
closure, actual daemon ownership or qualification.

Selected cancellation is fail-closed: SDK rejection retains the same original
error even if an external abort races it. A successful helper result observed
after abort produces a local cancellation rejection and no title change. The
ordinary route retains its fulfilled aborted-skip behavior. Neither route replays
a helper to classify a failure.
