### Changed

- Graft files in git is now ADE policy (operator, 2026-11-14): commit the portable `.ignore`, keep `/graft/` gitignored
  (its cache embeds local paths), forks keep their upstream's layout; the graft `.gitignore` papercut draft drops
  `/.ignore` from the exclude recipe and asks upstream for the `/.graft/` switch and a docs note on `.ignore`. (#702)
