---
name: hyades-docker
description: >-
  Host websites and services on SIPB Hyades (hyades.mit.edu, sites at
  NAME.sipb.cloud): OCI (Docker) images run as libkrun microVMs, driven by an SSH
  console (create/start/logs/setconf, volumes, groups, update tokens). Covers
  building and pushing images to the forgejo.mit.edu registry (podman preferred
  over docker), deploying from Forgejo CI with SIPB/hyades-action, hyades.json,
  MIT login via Petrock headers, exposed ports, full distros (bootc, NixOS), quotas
  and the console's known bugs. Use when a task mentions Hyades, sipb.cloud,
  hyades-action, updtoken, deploying a container at MIT, or /hyades-docker.
---

# Hyades (SIPB): deploying container images as microVMs

Canonical source: `skills/hyades-docker/` in `~/src/djbclark-ade` (written 2026-10-14).
Hyades is SIPB's free MIT hosting service, successor to Scripts and XVM: one large
NixOS server runs each user's OCI images as **libkrun microVMs** (rootless podman +
crun/krun, not containers), reverse-proxied by Caddy at `https://NAME.sipb.cloud`.
Not for static sites (use Athena), GPU/large compute (ORCD), commercial use, or
uptime stricter than ~5 min/month. Quotas per user: 10 microVMs, 4 vCPU, 32 GiB RAM
(8 GiB per microVM), 40 GiB disk (images + containers + volumes; a weekly check
emails you and prunes unused images), 2 groups; more via sipb-hyades-root@mit.edu.

**Sources** (read the local copy first; refresh with `scripts/hyades-refresh-docs`):

1. The user guide, https://hyades.mit.edu/inessential.html: local source
   `references/upstream/inessential.md`. Landing page https://hyades.mit.edu/.
2. Console help, every topic: `references/console-help.txt`; what each command
   really runs, limits and verified behaviour: **`references/console.md`**.
3. https://forgejo.mit.edu/SIPB/hyades: `references/upstream/hyades-README.md`
   (architecture, admin notes, intentionally unsupported list), `console.py` (the
   console), `quadlet.txt` (unit template). Issues: https://forgejo.mit.edu/SIPB/hyades/issues.
4. https://forgejo.mit.edu/SIPB/hyades-action: `references/upstream/hyades-action.yml`.
5. https://forgejo.mit.edu/SIPB/ci-images: the CI runner's label images (see `forgejo-ci`).
6. Petrock (MIT login): https://petrock.mit.edu/about/#user-information.
7. Contacts: hyades@mit.edu, Mattermost `sipb/channels/hyades`, Matrix
   `#_mm_sipb_hyades-development:matrix.mit.edu`; SIPB meets Mondays 7:30 PM, W20-557.

## Tools

1. **`scripts/hyades CMD [ARGS]`**: one console command over SSH
   (`djbclark@hyades.mit.edu`, key already in `authorized_keys`; override with
   `HYADES_USER`/`HYADES_HOST`). **The console exits 0 even on errors**; the wrapper
   exits 1 on a traceback, `Error:`, `*** Unknown syntax`, a missing unit. `-g GROUP`
   runs it in a Moira group account. No args: interactive console (needs a terminal).
   Read-only, safe to run any time: `list`, `getconf [NAME]`, `status NAME`,
   `logs NAME`, `lsvol`, `df`, `timetravel`, `help`. **Never `--help`**: it is a
   live service; `hyades help CMD`.
2. **`scripts/hyades-registry ENGINE-ARGS`**: one podman (docker only if podman is
   absent, or `HYADES_ENGINE=docker`) command logged in to `forgejo.mit.edu` with the
   token from sudo-secretspec, through a throwaway auth file: `hyades-registry push
   forgejo.mit.edu/djbclark/app:latest`. Never a bare `podman login`: it leaves the
   token base64 in `~/.config/containers/auth.json`. **On this Mac use
   `HYADES_ENGINE=crane` (or `skopeo`)**, which needs no VM (2026-10-14):
   `HYADES_ENGINE=crane hyades-registry append --platform linux/amd64 -b BASE -f
   layer.tar -t forgejo.mit.edu/djbclark/NAME:TAG` (layer: `gtar --owner=0
   --group=0 --numeric-owner -cf layer.tar etc`).
3. **`scripts/hyades-update-token check | trigger | rotate --yes`**: the account's
   update token in sudo-secretspec (`DJBCLARK_HYADES_UPDATE_TOKEN`), never printed.
4. **`scripts/hyades-ci-secrets OWNER/REPO --yes`** (or `--user --yes`,
   `--dry-run`): sets the `PACKAGE_TOKEN` and `UPDATE_TOKEN` Actions secrets that
   hyades-action reads.
5. `scripts/hyades-refresh-docs`: re-snapshot the upstream docs and the full help.

**Podman over docker.** Hyades itself is podman, the guide recommends it, and
everything here works the same with either, so use `podman`; fall back to `docker`
only where podman is unavailable. **On this Mac podman 6.1.4 is installed as a
client only (brew, 2026-10-14) and there is deliberately no `podman machine`:
djbclark does not want local VMs.** Never run `podman machine init/start`, install
podman-desktop, or start any other local VM without asking. A macOS podman client
with no connection can do nothing, not even `login` or `images`, so **build and push
in Forgejo CI** (hyades-action, below; the runner is podman/buildah on Hyades' CI
host). A remote Linux podman host would also work (`podman system connection add`).
Hyades is x86_64: when building on Apple Silicon anywhere, use
`--platform linux/amd64`.

**VM-free image tools (brew, installed 2026-10-14):**

1. `crane` (go-containerregistry): talks to registries directly. `crane manifest`,
   `crane config --platform linux/amd64 IMAGE | jq .config.User` (check an image's `USER` before `exec`, see
   console bug #5), `crane ls` (tags), `crane copy` (mirror docker.io into
   forgejo.mit.edu), `crane delete`, and **image building without a VM**: `crane append
   -b BASE -f layer.tar -t NEW` plus `crane mutate NEW --entrypoint ... --cmd ...` is
   enough for a script or static binary on a base image (`--platform linux/amd64`).
2. `skopeo`: inspect/copy/sync/delete between registries and archive formats
   (`docker-archive:`, `oci:`, `dir:`), reading the same `auth.json` format as podman
   (`--authfile`), with signature policy support.
3. `hadolint`: lint a `Dockerfile` before pushing it to CI (`hadolint Dockerfile`).

Authenticated use (private packages, pushes): `HYADES_ENGINE=crane hyades-registry
CRANE-ARGS` or `HYADES_ENGINE=skopeo hyades-registry SKOPEO-ARGS` (tool 2) does the
throwaway login for you; never hand-roll one. Public images need no login.

## Rules

1. **Mutations are outward-facing on a shared MIT service**: `create`, `setconf`,
   `edit`, `start/stop/restart/kill`, `delete`, `rmvol`, `impvol`, `update`,
   `updtoken`, `wordpress`, `entergp` (creates a group account) need djbclark's go-ahead
   unless the task already asked for them. Never touch a microVM you did not create
   without asking.
2. **No state survives a stop except volumes.** Every start begins from a pristine
   image. Put databases and uploads in `volumes`.
3. **`exposeports` is DANGEROUS** (public internet, shared port namespace across all
   users): prefer `ports` (HTTPS via Caddy); ask before exposing anything.
4. **One update token per account**: `updtoken`/`rotate` invalidates the old one
   everywhere. Store it once, reuse it in every repo (or set it at user level).
5. **Least-scope tokens.** CI push: a `write:package`-only token. Hyades console
   `login` (private images): a separate `read:package`-only token, so Hyades never
   holds write access.
6. Security vulnerabilities go to sipb-hyades-root@mit.edu, never the public tracker.
   Filing any issue is outward-facing: show djbclark the draft first. **SIPB issues
   are two-tier** (djbclark, 2026-10-14): a short human-readable issue upstream and a
   full AI-oriented one in the public fork `djbclark/hyades`, linked both ways:
   `forgejo-two-tier-issue` (forgejo skill). Drafts live in `tickets/N-slug/`
   (`title.txt`, `human.md`, `ai.md`).
7. `tmprun` with a script on stdin must end the script with `exit`; never kill the
   SSH client (`timeout`) while it runs: the microVM is orphaned and keeps using quota.
   Stop an orphan with `scripts/hyades stop 'libpod-<container id>*'` (id from `df`).

## hyades.json (`~/.config/hyades.json`; `getconf`/`setconf`, or `edit`)

A map of microVM name to:

| Key | Meaning |
|---|---|
| `image` | OCI ref, lower case, registry included (`docker.io/...`, `forgejo.mit.edu/OWNER/NAME`) |
| `ports` | `{SUBDOMAIN: PORT}`: `https://SUBDOMAIN.sipb.cloud` → PORT in the microVM (≤10). Custom domains: email sipb-hyades-root@mit.edu |
| `volumes` | `{VOLUME: /mount/path}`; a volume may be shared by several microVMs |
| `envs` | `{VAR: "value"}` |
| `network` | `""` = own isolated network; `"other"` = share `other`'s network (same localhost) and start after it. Point the app at its database's network, not the reverse |
| `exposeports` | `[TCP/UDP port, ...]` published on the host (≤10; see rule 3) |

Scripted edit: `scripts/hyades getconf NAME > c.json`, change it with `jq`, then
`scripts/hyades setconf NAME "$(jq -c . c.json)"` and `scripts/hyades restart NAME`
(`setconf` regenerates units but does not restart).

## Deploying

**A public image:** `create NAME docker.io/OWNER/IMAGE PORT`, then `start NAME`;
`status`/`logs` to check; site at `https://NAME.sipb.cloud`. `wordpress NAME` is a
one-command WordPress (SQLite) with its volume.

**Build locally, push, run** (the guide's flow, with our helpers):

On a machine with a working podman (not this Mac; see above):

```bash
podman build --platform linux/amd64 -t forgejo.mit.edu/djbclark/myapp:latest .
scripts/hyades-registry push forgejo.mit.edu/djbclark/myapp:latest
scripts/hyades create myapp forgejo.mit.edu/djbclark/myapp 8000   # then: start myapp
scripts/hyades update     # later pushes: pull now instead of waiting for the daily run
```

Packages are public unless the owner's profile is private; a private image needs a
one-time interactive `hyades login forgejo.mit.edu` with a read-only token.

**From Forgejo CI** (`.forgejo/workflows/main.yml` in a forgejo.mit.edu repo):

```yaml
on:
  push:
    branches: [main]
jobs:
  build-and-push:
    runs-on: ubuntu
    steps:
      - uses: https://github.com/actions/checkout@v7
      - uses: https://forgejo.mit.edu/SIPB/hyades-action@main
        with:
          package_token: ${{ secrets.PACKAGE_TOKEN }}
          update_token: ${{ secrets.UPDATE_TOKEN }}   # optional: omit = no instant update
          # containerfiles: ./Dockerfile   tags: latest   (defaults)
```

The action mounts a tmpfs on `/var/lib/containers/storage`, builds with
`redhat-actions/buildah-build@v3` (`--network=host`) as image `${{ github.repository }}`,
pushes to `forgejo.mit.edu` as `${{ github.actor }}` with `package_token`, then
`curl -X POST -H "X-Token: <update_token>" https://hyades.mit.edu` (Caddy hands the
POST to your trigger socket, which runs `podman auto-update`). So the microVM's image
is `forgejo.mit.edu/OWNER/REPO` (must be lower case), and the package token must
belong to whoever pushes. Secrets, once:

```bash
~/src/djbclark-ade/skills/forgejo/scripts/setup-token forgejo.mit.edu PACKAGE   # write:package only
scripts/hyades-update-token rotate --yes        # only if no token is stored yet (rule 4)
scripts/hyades-ci-secrets djbclark/myapp --yes  # or --user --yes for every repo
```

Then `create myapp forgejo.mit.edu/djbclark/myapp PORT` and `start myapp` after the
first successful run. Watch runs with the `forgejo` skill (`forgejo-api GET
/repos/O/R/actions/runs`); runner quirks (slow virtiofs disk, ignored
`working-directory:`, loopback TSI bugs) are the `forgejo-ci` skill's.

## More

1. **MIT login (Petrock):** on any `*.sipb.cloud` site `/hlogin` starts Touchstone
   login and `/hlogout` ends it (14-day cookie). Your app reads `X-Forwarded-Anonymous`
   (`true` = not logged in, other headers are junk), `X-Forwarded-Email`,
   `-Affiliation`, `-Name`, `-Given-Name`, `-Family-Name`. Redirect `/hlogin` to a
   landing page. Caddy also blocks a long list of AI-crawler user agents on every
   site, so `web-get`/Crawl4AI/Claude fetches of a `sipb.cloud` site may be refused:
   test with `curl` and a browser user agent.
2. **Volumes:** `lsvol`, `rmvol VOL`, `expvol VOL > v.tar`, `impvol VOL < v.tar`.
   Copy to a group: `ssh djbclark@hyades.mit.edu expvol V | ssh djbclark@hyades.mit.edu entergp G impvol V`.
   Edit files in volumes with `tmprun` + a stdin script (all volumes at `/mnt/VOL`);
   `exec` is broken (see `references/console.md`).
3. **Groups:** `entergp GROUP` (any member gets full access: use an officers-only
   list). Moira list must be a non-hidden "Moira Group" (WebMoira or `blanche`).
4. **Full distros:** bootable containers (e.g. `quay.io/fedora/fedora-bootc`) or a
   NixOS `dockerTools.streamLayeredImage` (`./result | podman load`, not `podman
   import`); set `KRUN_INIT_PID1=1` (NixOS also `PATH=/run/current-system/sw/bin`).
   Fixed kernel, no modules, TSI networking (TCP/UDP only: no VPNs, raw sockets).
   If systemd-resolved breaks DNS, hardcode `18.0.70.160`, `18.0.72.3`, `18.0.71.151`
   in `/etc/resolv.conf`. Details: `references/upstream/inessential.md`.
5. **Not supported by design:** static hosting, a sql.mit.edu replacement (use SQLite
   or your own PostgreSQL microVM), remctl, non-Linux kernels, public IPs per microVM
   (XVM), running `docker-compose.yml` directly (translate it to hyades.json).
6. **Backups:** btrbk snapshots of the host (`timetravel` shows your config's); the
   server applies updates Mondays 4:20.

## Overlap with other skills

| Need | Skill |
|---|---|
| Forgejo token, API calls, PRs, issues, git push, Actions secrets in general | `forgejo` (`forgejo-api`, `git-forgejo`, `setup-token`) |
| A job on the Hyades CI runner (`runs-on: ubuntu`) is slow, hangs or needs Java/Android | `forgejo-ci` |
| Deploying an image to Hyades, the console, hyades.json, update tokens, the registry push | this skill |
