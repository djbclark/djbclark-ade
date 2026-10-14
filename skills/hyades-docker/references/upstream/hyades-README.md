# Hyades

Hyades is a SIPB project to provide flexible compute resources and dynamic website hosting for the MIT community. It's intended to be the successor to [Scripts](https://scripts.mit.edu/) and [XVM](https://xvm.mit.edu/).

If you're interested in using Hyades, check out the [user guide](docs/inessential.md).

## Architecture

Hyades runs workloads as [libkrun](https://github.com/libkrun/libkrun) microVMs, which combine the security of VMs with the low overhead of containers. libkrun also reuses large parts of the container ecosystem such as OCI (Docker) images.

Hyades consists of four components:
1. hyades: A very large server for running the microVMs. Originally we wanted to run workloads on a Kubernetes cluster but that proved to be too complicated.
2. forgejo: A container registry server (currently forgejo.mit.edu)
3. sipbphus: A CI server using the Forgejo Runner
4. A server for disk backups, currently on the Proxmox cluster.

The main server runs [Nixathena](https://forgejo.mit.edu/SIPB/nixathena). The [Hyades console](src/hyades.py) is a command-line app (similar to the `scripts` command) instead of a website and accessible over SSH. Users can only use the Hyades console and don't have arbitrary shell access.

Users can configure their microVMs using a declarative `docker-compose.yml`-like format except it's JSON and somewhat simpler. The Hyades console translates this into [Quadlet](https://docs.podman.io/en/latest/markdown/podman-container.unit.5.html) which systemd then translates into service units. systemd also handles auto-updates for Docker images.

For web services, we have wildcard DNS record for *.sipb.cloud that points to the main server. Hyades uses the Caddy web server, which reverse-proxies https://blah.sipb.cloud to the Unix socket `/srv/sockets/blah`, and [socat](src/socat.py) reverse-proxies that to the correct microVM port using network namespace magic. We also support custom domains on request.

Hyades supports shared group accounts using Moira groups and has a [script run using sudo](src/entergp.fish) for switching to a group account.

Obviously this architecture has zero scalability, other than buying beefier hardware, but hopefully we won't have to scale?

Since Hyades runs untrusted workloads, we take security very seriously. Hyades use microVMs instead of ordinary containers and defense-in-depth so that breaking out of the Hyades console or a microVM only gives an attacker access to an ordinary user on the host. Even then, they still cannot compromise other user's microVMs or even see what other users are running due to `hidepid` and namespace tricks.

Further reading:
- https://hosted-files.sched.co/kvmforum2021/e4/libkrun_More_than_a_VMM_in_Dynamic_Library_Form.pdf

## Installation

Boot with `nomodeset` to solve the "Video mode not supported; Analog" issue.

Note that as of July 2026 there's a bug where `nixos-generate-config` hardcodes `/dev/sda` instead of a UUID for the `hardware-configuration.nix` which you should fix manually.

Otherwise it's basically just installing NixOS. Note that you should make `/nix` and `/var/log` subvolumes so that they don't get backed up.

## Local dev environment

```bash
nixos-rebuild build-vm --flake .#hyades
result/bin/run-hyades-vm -m 4G -smp 8 -device vhost-vsock-pci,guest-cid=3
```

Now you can `ssh sipb@vsock%3`. Note that SSH using Kerberos tickets won't work since the VM doesn't have a Kerberos keytab.

Run `nix run .#test.basic` to run tests.

## Admin guide

You can SSH into the Hyades and Siphphus servers using `ssh sipb@hyades.mit.edu` and `ssh sipb@siphphus.mit.edu` respectively.

The Hyades server automatically applies updates every Monday at 4:20. Remember that it's a production server and hosts important websites, so you should **not** update it at other times except for emergency security updates.

Commits to this repo are not automatically deployed to the Hyades or Siphphus servers, so you will need to SSH in and run `git pull` in the `/etc/nixos` directory. You will then have to wait until next Monday for the new commits to be applied.

To add custom domains, edit `/etc/caddy/custom_domains` and then run `sudo systemctl reload caddy`.

Note that Hyades applies resource limits via cgroups to all users including the `sipb` user, so if you need to run a resource-intensive command, you should disable the limits using `sudo systemctl set-property --runtime user-1000.slice CPUQuota=""` or `TasksMax=""`.

## TODO

- Figure out the *.hyades.mit.edu subsubdomain situation
- Upstream the crun and libkrun patches
- Use HDDs for mastodon-backup
- CI caching
- More architectures and OSes for CI?
- virtiofs performance tweaks (or just use tmpfs?)
- Security hardening
- Upstream a solution for https://github.com/nixos/nixpkgs/issues/450289
- Fish-style tab completion for console
- Improve Hyades console error messages
- Friendly web UI or GUI
- Monitoring for microVMs (i.e. get a notification on failure)
- Fix *.sipb.cloud connection refused inside microVMs
- Ask upstream libkrunfw to enable Landlock
- docker-compose-style healthchecks

## Intentionally unsupported

While Hyades is intended to be the successor to Scripts and XVM, we intentionally do not support the following features to keep things simple:

- Static site hosting: Use Athena instead or any of the many free static site hosting services.
- A replacement for sql.mit.edu: You can use SQLite instead, or run your own PostgreSQL instance.
- remctl integration: Use SSH instead
- MicroVMs that use kernels other than Linux: Technically libkrun has FreeBSD support but it seems too niche and complicated to support.
- Giving microVMs their own public IPs: Use XVM instead
- Running docker-compose.yml files

## History

Back in 2015, [slz](https://www.lsha.net/) proposed setting up a SIPB Kubernetes cluster to replace Scripts and XVM, sort of like SIPB's own version of AWS. After five years of experimenting with OpenStack (dropped for being too complicated), Ceph, and Kubernetes, SIPB had its own [cluster management system](https://github.com/sipb/homeworld), [load balancer](https://github.com/sipb/spike), and Kubernetes running on some actual servers. Then, the pandemic struck and destroyed all their momentum. Various people tried reviving the project, but the [second](https://github.com/sipb/hyades) and [third](https://github.com/sipb/tryades) attempts also stalled. During summer 2026, some SIPB members attempted Hyades once again, but without any Kubernetes (which is overkill unless you're Google) or fancy distributed systems stuff and simply used a single very large server.
