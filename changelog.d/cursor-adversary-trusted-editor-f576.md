### Changed

- Owner-authored PR body APPROVEs stay trusted when the last editor is a login in
  `BODY_TRUSTED_EDITOR_LOGINS` (`cursor`), so a Cursor Cloud rewrite of the PR body does not void a live
  marker; outside/MEMBER/COLLABORATOR PRs are unchanged and still need an owner comment (#319).
