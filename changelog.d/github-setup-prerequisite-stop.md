### Fixed

- Stopped `ade-github-setup apply --yes` before App ID discovery and ruleset operations when environment or deployment-branch-policy setup failed, preserving the prerequisite failure and reporting `refused-prerequisite`. (#556)
