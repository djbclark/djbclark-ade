# Managed Go accounts

Each provider resolves only its named managed credential immediately before Pi starts the request. Model enumeration and credential discovery do not contact sudo-secretspec. A resolution failure stops execution before transport; no other account or ambient key is tried.

The resolver reports fixed messages for caller abort, its own 10-second deadline, a missing or inaccessible executable, broker audit-policy denial, bounded numeric exit status, oversized output, process termination, invalid results and empty stdout. Caller cancellation takes precedence over a simultaneous deadline. Timeout detection uses an owned AbortSignal deadline rather than assuming every SIGTERM is a timeout.

Raw subprocess errors, stdout, stderr, and error causes never leave the resolver. Only integer exit statuses 1–255 are interpolated. The recognized denial diagnostic is the broker's `audit denied:` prefix, optionally following `audit attempt failed:` or `audit terminal failed:`; unknown diagnostics retain a numeric exit code or the generic execution failure.

Validation uses mock errors plus real Pi against an isolated HTTP fixture in CI, proving discovery makes no broker call and failed preflight makes no HTTP request.
