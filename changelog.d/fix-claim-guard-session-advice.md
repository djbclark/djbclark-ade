### Fixed

- Git guard: the self-owner refusal no longer offers `bind-owner` when the claim has an `owner.session` (a plain bind-owner exits 0 but does not clear a session, so the caller stayed refused); it advises `release` plus a new claim and says the claim is bound to a session (#897)
