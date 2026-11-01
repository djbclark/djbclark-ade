### Fixed

- `relay.py` sends to a **working** claude, codex, omp, opencode or pi Paseo agent at once through `paseo send --behavior steer`, which queues the text inside the agent's running turn without interrupting it (the daemon's `steerOrReplaceActiveTurn` "steered", read from the installed 0.15.0-beta.1 bundle, 2026-11-01); before, a working codex, omp, opencode or pi agent was queued until idle and two records to a working omp agent expired unsent after 6 h. A queued record now also sends at once when its target is such an agent and still working (the deliverer no longer waits for an idle that may never come). Only a provider that cannot steer (cline, ACP) is still queued, because a send would replace its running turn, and a record of that kind still unsent at its expiry is `expired` with "NOT DELIVERED ..." in the record, `deferred.log` and the sender's notice, instead of the false "working: it takes the text when its turn ends" (#228).

### Removed

- `relay.py --steer` (steer is now the behavior for every provider that can steer; `--idle S` still waits for idle first) (#228).
