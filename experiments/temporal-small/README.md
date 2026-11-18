# Optional bounded Temporal experiment

A1. This isolated CI experiment asks one useful question: what does Temporal
provide beyond a durable queued task when the task later gains a retry,
human approval wait and worker restart? It does not change the NATS decision.

A2. A fake SQLite endpoint commits an effect under a stable operation ID, then
loses the response. Temporal retries the activity; endpoint idempotency prevents
a second effect. The workflow waits for a simulated approval signal, the worker
stops, and a new worker replays history and completes. Temporal does not make an
arbitrary external effect exactly once; the endpoint still needs its idempotency key.

A3. The test uses `TestWorkflowEnvironment.createLocal()` in Linux CI and
downloads a disposable development server. It creates no Temporal Cloud or
Google account/project, consumes no trial and makes no paid model calls. There
is no cloud subscription or post-trial dependency. Do not add credentials.

A4. Budget: one small experiment within the plan's half-day cap. Stop expanding
it once the stated question is answered. This is workflow/worker replay proof,
not a Temporal Cloud availability, full-server disaster-recovery, physical-host
crash, scale or comparative performance benchmark. It cannot establish an
implementation-time multiple from execution latency.

A5. Current SDK dependencies resolve during CI; the workflow records the exact
lock file. No local installation or server on the Mac is needed. Official
[test environment API](https://typescript.temporal.io/api/classes/testing.TestWorkflowEnvironment)
documents the local disposable server and the distinction from its time-skipping
test server. Use actual CI results before recording successful behavior.
