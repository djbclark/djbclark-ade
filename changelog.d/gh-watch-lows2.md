### Fixed

- The Bash gate's gh watcher rule also sees `env -i "VAR=$X" gh ...` (quoted assignment), `env -iu X`/`sudo -Hu me` (combined options), `nice --adjustment N`, `command -p gh`, `exec -a NAME gh` and `gh>log run watch 9`; a test now pins the four-candidate limit. (#694)
