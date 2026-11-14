### Fixed

- The Bash gate's gh watcher rule also sees `rtk proxy gh run watch`, `env -i VAR=x gh ...` and `nice -n N gh ...`; dispatch-footer item 26 names the GraphQL rate-limit bucket, and the remaining undetected shapes are listed in docs/bash-habits-gate.md. (#PR)
