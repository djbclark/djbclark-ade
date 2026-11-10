### Security

- `secret_read_gate` no longer fails open when crafted slow Bash globs exhaust the analysis budget: a shared first-pass
  cap and a cached set-aside retry keep later words reachable; deferred words get a pattern-only check then a real
  walk (or fail closed) so walk-dependent secrets (`id_*`, `*`) are never allowed on pattern-only alone after
  set-aside, a deferred walk truncated by `GLOB_S` / the entry bound fails closed, a first-pass relative/cwd or
  absolute/tilde walk truncated the same way fails closed (absolute deep globs keep the pattern fallback only when
  that shared budget did not truncate), and a second timeout fails closed (issue 284 / queue Carried #1 residual)
  (#413).
- `secret_read_gate` keeps `_glob_budget_hit` sticky across brace alternatives (so `{,id_*}` / `{,*}` cannot clear a
  prior truncate) and latches the same fail-closed path when `MAX_GLOB_HITS` truncates a walk (#413).
