### Security

- `secret_read_gate` no longer fails open when crafted slow Bash globs exhaust the analysis budget: a shared first-pass
  cap and a cached set-aside retry (pattern-only) keep later words reachable, and a second timeout fails closed
  (issue 284 / queue Carried #1 residual).
