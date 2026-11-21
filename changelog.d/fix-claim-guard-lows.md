### Fixed

- Git guard: the `owner.agent` rule of #886 applies only while the claim has no `owner.session`, so a nested `claude -p` or a successor with its own session that inherits the owner's `PASEO_AGENT_ID` is refused again; the self-owner refusal offers `bind-owner` only when it can succeed (empty `owner.agent` or the caller's own Paseo agent id) and otherwise advises `release` plus a new claim (#PR)
