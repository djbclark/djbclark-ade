### Changed

- Graft files in git is now ADE policy (operator, 2026-11-14): commit the portable `.ignore`, keep `/graft/` gitignored
  (its cache embeds local paths); the graft `.gitignore` papercut draft drops `/.ignore` from the exclude recipe and
  narrows the upstream ask to the `/.graft/` switch.
