### Changed

- Record versioned fork deployment baselines, exact recovery direction, reservation intent and uncertain release in the same Journal; require explicit rollback resume and release reconciliation authority. (#0)

- Preserve original held reservation context for confirmed settled failures and separately authorized same-process recovery; reject unknown outcomes without re-BEGIN or token persistence. (#0)
