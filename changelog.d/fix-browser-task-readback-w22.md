### Added

- `ade-browser-task` completion readbacks for `issue-access` (repository GET:
  `issue_creation_policy` collaborators-only with issues still enabled; a missing
  REST field records `field-missing` and stays not done) and `github-app-create`
  (App slug/permissions via `GET /apps/{slug}` plus the operator-visible
  installation list restricted to exactly the configured repository), and a
  bounded `poll` loop that reruns the readback on an interval until
  completed/expired. Browser replies and deadline registrations still never prove
  completion (2026-11-12). (#N)
