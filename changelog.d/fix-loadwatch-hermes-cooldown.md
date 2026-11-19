### Fixed

- `bin/load-watch` no longer stamps a Hermes cooldown after a *failed* `hermes-ping`: `churn_alert` and `operator_notice` set `cd["churn"]` / `cd[key]` only when the ping succeeded, so one transient failure no longer silences the operator page for the whole 6 h cooldown (the page is retried on the next sample). A shared `hermes_ping()` helper now sends every operator line and reports delivery; `gping` no longer raises out of a timed-out ping. (#803)
