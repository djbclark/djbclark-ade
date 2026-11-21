### Fixed

- Git guard: the session-bound refusal advice says to release only once the owning session has finished, and the docs no longer claim `bind-owner` never clears a session (an explicit empty `--owner-session` does; a plain `bind-owner --owner-agent` does not) (#905)
