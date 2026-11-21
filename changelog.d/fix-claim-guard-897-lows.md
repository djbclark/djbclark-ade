### Fixed

- Git guard: the session-bound refusal advice says to release only once the owning session has finished, and the docs no longer claim `bind-owner` never clears a session (any `--owner-session` value replaces or clears it; `bind-owner --owner-agent` alone leaves it) (#905)
