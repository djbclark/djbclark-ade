# Hyades console: every command, what it really does

The verbatim `help` text is in `console-help.txt` (captured over SSH; refresh with
`scripts/hyades-refresh-docs`). The help is one line per command and has no
sub-pages, so the "full text" of each item is below: the underlying call, read from
`upstream/console.py` (commit in `upstream/SOURCE.md`), and what was verified live on
2026-10-14 as `djbclark`.

Every command works as `ssh djbclark@hyades.mit.edu CMD ARGS` (the console runs
`SSH_ORIGINAL_COMMAND` through the same parser and exits) or via `scripts/hyades CMD ARGS`.
**The console always exits 0, even on a traceback or a podman error**: the wrapper
turns the error markers back into exit 1. Arguments are split on single spaces by
the console (no shell, no quoting), and SSH joins your argv with spaces first.

Names (microVM, subdomain, volume, network) must match `[a-z0-9_][a-z0-9_-]*`;
images `[a-z0-9.:/_][a-z0-9.:/_-]*` (lower case only: an image ref with an upper-case
owner fails); env var names `[a-zA-Z0-9_]+`; no newlines in paths or values.

## Read-only

| Command | Runs | Notes |
|---|---|---|
| `list` | prints the keys of `~/.config/hyades.json` | configured microVMs, running or not |
| `getconf [NAME]` | `json.dumps` of the whole config or one entry | the scripting read; unknown NAME prints a `KeyError` traceback |
| `status NAME` | `systemctl --user status NAME` | unit is `NAME.service`, generated from `NAME.container`; shows the image pull and container lines too |
| `logs NAME` | `journalctl --user -xeu NAME` | whole journal for the unit, no pager over SSH; `-x` adds the `░░` catalogue lines |
| `stats` | `podman stats` | **streams forever**: `timeout 10 scripts/hyades stats` |
| `df` | `podman system df -v` | images, containers and volumes with sizes; the 40 GiB quota counts all three |
| `lsvol` | `podman volume ls` | |
| `timetravel [DATE]` | no DATE: lists btrbk snapshot ids under `/.snapshots` holding your `hyades.json`; DATE: prints `hyades.json` from snapshot `hyades.DATE` | snapshots are kept `2d 2w 2m *y`; empty list on a new account. Only the config, not volumes: for volume restores email sipb-hyades-root@mit.edu |
| `expvol VOL` | `podman volume export VOL` | tar to stdout: `scripts/hyades expvol VOL > vol.tar` |
| `help [CMD]`, `?` | `cmd.Cmd` help | one line each |

## Changing microVMs (each rewrites Quadlet files and runs `systemctl --user daemon-reload`)

| Command | Runs | Notes |
|---|---|---|
| `create NAME IMAGE [PORT]` | adds `{image, ports: {NAME: PORT}, volumes: {}, envs: {}, network: "", exposeports: []}`, then `regenerate` | **does not start it**. With PORT, `https://NAME.sipb.cloud` → PORT; fails if subdomain NAME is taken by anyone. Docker Hub images need the `docker.io/` prefix |
| `setconf NAME JSON` | replaces entry NAME with JSON, saves, `regenerate` | the scripting write: `scripts/hyades setconf NAME "$(jq -c . conf.json)"` (verified: JSON survives SSH). Does not restart: follow with `restart NAME` |
| `edit [v]` | `rnano` (or `rvim` with `v`) in a bubblewrap sandbox on `~/.config/hyades.json`, then reload + `regenerate` | interactive only; Ctrl-X exits nano. A JSON syntax error is printed as a traceback and the old in-memory config stays |
| `regenerate` | rebuilds `~/.config/containers/systemd/*.container` from the config (atomic `exch` swap) + `daemon-reload` | enforces the limits: ≤10 microVMs, ≤10 subdomains and ≤10 `exposeports` per microVM, `network` must name an existing microVM; reserves each exposed port under `/srv/ports` (fails if another user holds it) |
| `delete NAME` | `stop`, removes the Quadlet file, frees its subdomain sockets and exposed ports, drops the entry | **volumes survive**: `rmvol` them yourself |
| `wordpress NAME` | `create NAME docker.io/soulteary/sqlite-wordpress 80`, adds volume `NAME_wordpress` at `/var/www/html`, `start` | finish setup at `https://NAME.sipb.cloud/` |

## Running

| Command | Runs | Notes |
|---|---|---|
| `start NAME`, `stop NAME`, `restart NAME`, `kill NAME` | `systemctl --user start/stop/restart/kill NAME` | units have `Restart=on-failure` (5 s), start limit 10 per 120 s, `TimeoutStartSec=300`, `AutoUpdate=registry`. `stop` discards everything outside volumes. Lingering is enabled, so microVMs run while you are logged out |
| `exec NAME CMD` | `podman exec -it NAME -- CMD` | **broken as of 2026-10-14**: `Error: krun: chown /dev/pts/N: Operation not permitted: OCI permission denied`, with or without `ssh -tt`, from the interactive console too (tested on `djbclark-rustpad`). Also CMD is passed as ONE argv element, so `exec NAME ls /` would look for a program named `ls /`. Use `tmprun` instead |
| `tmprun IMAGE [CMD]` | `podman run --rm -it -v VOL:/mnt/VOL ... IMAGE -- CMD` with every volume of every microVM mounted under `/mnt` | **with CMD it is broken**: `--` lands after the image, so the guest runs `--` (`Couldn't execute '--': ENOENT`). **Without CMD it works**, so feed a script on stdin: `printf 'ls /mnt; df -h\n' \| scripts/hyades tmprun docker.io/library/alpine` (verified: guest kernel 6.12.109, `nproc` 4). The warning "input device is not a TTY" is harmless. The pulled image stays until the weekly `podman system prune -a -f` |
| `update` | `podman auto-update` | pulls newer images for every unit and restarts what changed. Hyades also does this daily, and on `POST https://hyades.mit.edu` with `X-Token` |

## Registry, keys, tokens, groups

| Command | Runs | Notes |
|---|---|---|
| `login REGISTRY` | `podman login --authfile ~/.config/containers/auth.json REGISTRY` | interactive (prompts user and password); needed only for private images. Use a **read:package-only** token, never the push token. Do not script it by piping a token into `ssh -tt`: the remote pty can echo it into your output |
| `editssh [v]` | `rnano`/`rvim` on `~/.ssh/authorized_keys` | interactive; add public keys only. First login must be Kerberos (`kinit USER@ATHENA.MIT.EDU; ssh -K USER@hyades.mit.edu`) |
| `updtoken` | deletes **all** trigger sockets, makes `podman-auto-update-trigger@TOKEN.socket`, prints `Your update token is <32 hex>` once | one live token per account: rotating breaks every repo holding the old one. Use `scripts/hyades-update-token rotate --yes`, which stores it without printing |
| `entergp GROUP [CMD]` | `sudo entergp GROUP [CMD]` | needs membership of Moira group GROUP (a non-hidden list with "Moira Group" ticked in WebMoira, or `blanche`); creates the group account on first use (max 2 groups per user). With CMD it runs one console command in the group account: `scripts/hyades -g GROUP list` |
| `exit`, `EOF` (Ctrl-D) | leave the console | |

## Bugs worth filing (not filed; ask djbclark first)

1. `exec`: krun cannot chown the pty (above); and CMD is one argv element.
2. `tmprun IMAGE CMD`: `--` after the image becomes the command.
3. Exit status is always 0, so scripts cannot detect failure.

Tracker: https://forgejo.mit.edu/SIPB/hyades/issues (security issues to
sipb-hyades-root@mit.edu instead). djbclark already filed #2, #3 and #4 there (CI
runner; see the `forgejo-ci` skill).
