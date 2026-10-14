---
title: Inessential Hyades
---

Hyades is a free service at MIT that provides website hosting and flexible compute resources. Some cool things you can host or run with Hyades include:

- A WordPress blog
- Your club or lab's website
- A Minecraft server
- A database server for your web app
- An entire Linux distro as a VM, accessible over SSH
- Another nested copy of Hyades itself, if you're that kind of crazy person 😼

There are also some things that Hyades is *not* suitable for, such as:

- Static site hosting: This is intentionally unsupported by Hyades since it's already provided by [Athena](https://mit.service-now.com/esc?id=kb_article&sysparm_article=KB0029735).
- Running large computations or training ML models: Hyades doesn't have any GPUs anyways. Check out [ORCD](https://orcd.mit.edu/) for large compute clusters instead.
- Your AI slop startup's website: Please don't use Hyades for commercial purposes.
- Hosting websites that require extremely high availability: Hyades aims to have at most five minutes of downtime per month, but if you have stricter requirements you should use some paid professional hosting provider instead.

Hyades is developed and maintained by [SIPB](https://sipb.mit.edu/), MIT's student computing club, which you might know from Hydrant and Courseroad. Hyades is the modern successor to SIPB's [Scripts](https://scripts.mit.edu/) and [XVM](https://xvm.mit.edu/) projects, which were groundbreaking when they were created back in the 2000s but nowadays mostly obsoleted by Hyades.

Lastly, Hyades is (we hope) easy to use! The only prerequisites you need are knowing how to SSH and how to edit a JSON file. With Hyades, you don't have to worry about the annoyances of managing a server, and Hyades automatically handles:

- Updates
- Backups
- TLS certificates
- MIT auth integration

## Technical background

This is the part of the guide where we will throw a lot of technical jargon at you. Feel free to skip it, or read it if you want to gain a slightly better understanding of Hyades than "type some weird commands and the website magically appears yay".

Hyades runs your websites and compute workflows as *microVMs*, which are very barebones and fast virtual machines. In contrast, traditional VMs include lots of features like virtual GPUs that are unnecessary for running websites. Note that Hyades does *not* use containers (such as Docker containers).[^1] Containers differ from VMs by sharing the same kernel as the host machine whereas VMs run a new kernel per VM. This means containers are faster and use less memory than VMs, but significantly less secure. In just the first half of 2026, there have already been several infamous Linux kernel bugs such as [Copy Fail](https://copy.fail/) which can be used to break out of containers, but not VMs. MicroVMs offer the same security as a VM, but with a comparable performance overhead as containers, so it's the best of both worlds!

Hyades stores microVMs on disk as *Docker images*, which are compressed archives containing the files for your microVM. (You might also see them called "OCI images" or "container images" which are just a genericized term for the same thing, like "Kleenex" vs. "tissue".) Admittedly this is a bit confusing, since Hyades doesn't run the Docker images as Docker containers but rather as microVMs. Hyades uses Docker images because they have a lot of existing tooling and there are lots of prebuilt Docker images available on the internet.

## Logging in

Ironically for a website hosting platform, the Hyades console is not a website but rather a command-line shell accessible over SSH. You can either log in with a Kerberos ticket or an SSH key, although you must first log in with Kerberos in order to add your SSH public key.

First, open a terminal and obtain a Kerberos ticket (with `USERNAME` replaced with your Kerberos username):

```bash
kinit USERNAME@ATHENA.MIT.EDU
```

If you don't have `kinit` on your computer, you can alternatively SSH into an Athena dialup which will obtain a Kerberos ticket automatically.

Now on the machine with the Kerberos ticket (either your computer or a dialup), SSH into the Hyades server:

```bash
ssh -K USERNAME@hyades.mit.edu
```

(Tip: If you're on MIT Wi-Fi, you can omit the `.mit.edu`)

You should be greeted with this:

```
=== Welcome to the Hyades console ===

Type ? or help to show help
User guide: https://hyades.mit.edu/inessential.html

(hyades) 
```

Note that this is *not* a Bash shell and instead has its own set of commands. Type `?` to show the list of commands and `? COMMAND` to get documentation about a specific command.

To make future logins more convenient, you can add your SSH public key to Hyades using the `editssh` command, which edits your `~/.ssh/authorized_keys` file. Make sure you add your SSH *public* key and not your private key. You don't need to use a dialup to SSH into Hyades when using an SSH key.

To exit the console, hit Ctrl-D or type `exit`.

## Hyades by example

### Your first microVM

For our first example, we will set up [Rustpad](https://github.com/ekzhang/rustpad), a simple collaborative document editor, on Hyades. First, come up with a silly name for your new site, which will be accessible at https://NAME.sipb.cloud.

In the Hyades console, run:

```
create NAME docker.io/ekzhang/rustpad 3030
```

This command downloads the [ekzhang/rustpad Docker image](https://hub.docker.com/r/ekzhang/rustpad). Note that you *must* prefix [Docker Hub](https://hub.docker.com/) images with `docker.io` since otherwise Hyades won't know which site to download the image from (the world is larger than just the Docker Hub!). The 3030 tells Hyades that our website runs on port 3030. Also, note that this does not start the microVM yet. To actually start it, run:

```
start NAME
```

(Tip: There's tab completion for both commands and arguments)

Now visit https://NAME.sipb.cloud and your site should be up!

You can get the current status of your microVM:

```
status NAME
```

And its logs:

```
logs NAME
```

Importantly, on Hyades, microVMs have no persistent state by default. Every time you `start` a microVM, it starts out with a pristine copy of the OCI image, and `stop` discards any files that have been modified. For Rustpad, when you `stop` the microVM, all the documents that you and your friends have edited on there are lost.

### Persistent storage

Hold up! That doesn't seem very useful if a website has its memory wiped all the time! Fortunately, we can store files that persist across stops and starts using *volumes*.

Rustpad can save documents on disk in its database, so we need to put its database in a volume. We also need to tell Rustpad to save its database there using the environment variable `SQLITE_URI`.

Run the `edit` command (or `edit v` to use Vim) and edit the `"volumes"` and `"envs"` like this:

```json
{
    "rustpad": {
        "image": "docker.io/ekzhang/rustpad",
        "volumes": {
            "rustpad_db": "/db"
        },
        "envs": {
            "SQLITE_URI": "/db/rustpad.db"
        },
        "network": "",
        "ports": {
            "rustpad": 3030
        },
        "exposeports": []
    }
}
```

Now press Ctrl-X to exit and then restart Rustpad:

```
restart NAME
```

Now your documents will still be accessible even after a restart!

When you're done with this part of the guide, you can delete the Rustpad microVM if you want:

```
delete NAME
```

This doesn't delete any volumes attached to the microVM, so you should do that manually:

```
rmvol rustpad_db
```

### WordPress

Simply run `wordpress NAME`. You might have to wait a minute, and then visit https://NAME.sipb.cloud/ to finish setting up your site.

### Building an app locally

In this example we will build and deploy a very simple Python web app to Hyades. You'll need to have [Podman](https://podman.io/) (recommended) or [Docker](https://www.docker.com/products/docker-desktop/) installed on your machine.

Here is the web app, `main.py`:

```py
from http.server import BaseHTTPRequestHandler, HTTPServer

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        body = f"Hello, world!\n{self.headers.items()}"
        self.wfile.write(body.encode('utf-8'))

HTTPServer(("", 8000), SimpleHandler).serve_forever()
```

First, we need to write a Dockerfile, which is basically a glorified Bash script that builds the app in an isolated environment. Create the file `Dockerfile` with these contents:

```dockerfile
FROM docker.io/ubuntu:26.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y python-is-python3
RUN apt-get clean
COPY main.py /
ENTRYPOINT ["python"]
CMD ["main.py"]
```

To learn more about building Docker images and writing Dockerfiles, check out the [Docker docs](https://docs.docker.com/get-started/docker-concepts/building-images/).

Now, build the app with `podman build . -t forgejo.mit.edu/USERNAME/project-database`. forgejo.mit.edu is a code hosting platform and container registry run by SIPB. (If you're using Docker, run the same commands but with `docker` instead of `podman`.)

Now visit [forgejo.mit.edu](https://forgejo.mit.edu) and sign in. Go to your user settings, click on "Applications", and generate a new access token with access to all repos and "read and write" permission for packages. Copy the token, and run `podman login forgejo.mit.edu` using your Kerberos username and the token as the password.

Next, push the image to the MIT Forgejo using `podman push forgejo.mit.edu/USERNAME/project-database`. By default your Docker image will be public, but you can make it private by changing profile visibility to private.

Lastly, SSH into Hyades and create a new microVM:

```
create projectdb forgejo.mit.edu/USERNAME/project-database 5000
```

If your image is private, generate a new token with read-only access to packages and then run `login` in the Hyades console using your new token as the password. (You should avoid reusing the token from earlier so that Hyades doesn't have write access.)

If you push a new image, run `update` on Hyades to pull and use the updated image. Hyades also automatically updates all images daily.

Phew! That was a lot just to deploy our simple app onto Hyades. But most of this uses standard Docker or Podman tools, so there's plenty of resources available online.

### Building an app using the Forgejo CI

Cool, we just locally built a Docker image for our app! But, it's kind of annoying to do that all the time, so luckily the MIT Forgejo has a CI system that can run builds every time we do a Git push.

Let's set up a CI workflow for the Python web app above. First, on the MIT Forgejo, create a new repository, clone it to your computer, and add the Dockerfile and `main.py`. Forgejo reads CI workflows from the directory `.forgejo/workflows`, so additionally create a `.forgejo/workflows/main.yml` with the following:

```yml
name: Build and push Docker image
enable-email-notifications: true

on:
  push:
    branches:
      - main

jobs:
  build-and-push:
    runs-on: ubuntu
    steps:
      - name: Checkout
        uses: https://github.com/actions/checkout@v7

      - name: Build and deploy
        uses: https://forgejo.mit.edu/SIPB/hyades-action@main
        with:
          package_token: ${{ secrets.PACKAGE_TOKEN }}
          update_token: ${{ secrets.UPDATE_TOKEN }}
```

We also need to give the CI workflow permission to push to your packages and trigger an automatic update on Hyades. First add your access token from earlier as a CI secret by clicking on "Settings → Actions → Secrets". Call the new secret `PACKAGE_TOKEN`. Now SSH into Hyades and run `updtoken` to get your `UPDATE_TOKEN` and add it to the secrets as well.

Finally, commit these three files and do a Git push. Now if you visit the "Actions" tab of your repo, you should see the CI pipeline running!

The `with:` block supports several optional parameters:

- `containerfiles`: Build a Dockerfile other than `./Dockerfile`
- `tags`: Set a tag other than `latest`
- If `update_token` is omitted, then an auto-update on Hyades will not be triggered

### Multi-VM websites

Sometimes you might need to run multiple coordinated microVMs to host a complicated web app. A common example is if your app uses a standalone database like PostgreSQL. In this example, we will set up the [Vikunja task manager](https://github.com/go-vikunja/vikunja) using Redis for caching. The Vikunja docs site provides [Docker Compose examples](https://vikunja.io/docs/full-docker-example/) which we'll adapt for Hyades.

First let's create the two microVMs:

```
create vikunja docker.io/vikunja/vikunja 3456
create redis docker.io/redis
```

Now we can edit their configs to add the necessary volumes and environment variables:

```json
{
    "vikunja": {
        "image": "docker.io/vikunja/vikunja",
        "ports": {
            "vikunja": 3456
        },
        "volumes": {
            "vikunja": "/app/vikunja/files",
            "vikunja-db": "/db"
        },
        "envs": {
            "VIKUNJA_SERVICE_PUBLICURL": "https://vikunja.sipb.cloud",
            "VIKUNJA_SERVICE_SECRET": "klajklewjrklmwlkamtklemerwlkm",
            "VIKUNJA_DATABASE_PATH": "/db/vikunja.db"
        },
        "network": "redis",
        "exposeports": []
    },
    "redis": {
        "image": "docker.io/redis",
        "ports": {},
        "volumes": {
            "redis": "/data"
        },
        "envs": {},
        "network": "",
        "exposeports": []
    }
}
```

Note that we used the `network` field to add `vikunja` to the `redis` microVM's network, since by default microVMs are completely isolated from each other. This adds a dependency for `vikunja` on `redis` so that Hyades will first wait for `redis` to start up, then start `vikunja` reusing the `redis` network. (If we had instead added `redis` to the `vikunja` network, then Hyades would start up `vikunja` which would throw an error and stop because it can't reach Redis, and `redis` would never start up.)

Now let's start up `vikunja`:

```
start vikunja
```

### Exposing TCP ports

All our examples so far have been websites using HTTPS. We can also use Hyades to host networked services that use TCP or UDP, such as a Minecraft server. In this example, we'll set up a relay for [Syncthing](https://syncthing.net/):

```json
{
    "relaysrv": {
        "image": "docker.io/syncthing/relaysrv",
        "ports": {},
        "volumes": {
            "relaysrv": "/var/strelaysrv"
        },
        "envs": {},
        "network": "",
        "exposeports": [
            22067,
            22070
        ]
    }
}
```

Note that we use `exposeports` instead of `ports` here. `exposeports` is DANGEROUS and exposes your service to the public internet, so make sure you fully understand the security implications before using it. Additionally, all Hyades users share the same port namespace, so you may have to use a different port if the one you want is already reserved.

## Groups

So far, your microVMs and websites have been tied to your user, but what if you want to host a site for a club or student group? Hyades integrates nicely with mailing lists, so you can give everyone in a list access to a shared group account.

More specifically, Hyades uses Moira groups, but you can easily make a Moira mailing list also a group. Visit [WebMoira](https://groups.mit.edu/webmoira/), select a list, click "Edit", and check the box "Moira Group". (Alternatively you can use `blanche`.) Note that you must be an owner of the list to do this, and the group must not be hidden for Hyades to see its members.

Now back in the Hyades console, run:

```
entergp GROUP
```

This should drop you in a new Hyades console, but for your shared group account. Note that Hyades allows *any member* of the group, not just the owners, to access the group account, so you probably don't want to use your club mailing list but rather a list with just the officers.

## Working with volumes

As mentioned before, Hyades uses volumes for persistent storage. To list all your volumes, run:

```
lsvol
```

To edit a volume, first get an interactive shell on a microVM that uses that volume:

```
exec NAME bash
```

Once you're in the shell, you may need to first install a text editor.

You can also edit a volume using `tmprun ubuntu`, which will spawn a temporary Ubuntu microVM with all your volumes mounted under `/mnt`.

To delete a volume, run:

```
rmvol VOL
```

Lastly, you can export and import volumes using `expvol` and `impvol` respectively. For example, to copy a volume from your account to a group account, run on your own machine:

```bash
ssh USERNAME@hyades.mit.edu expvol VOL | ssh USERNAME@hyades.mit.edu entergp GROUP impvol VOL
```

## Quotas

Hyades has several per-user quotas:

| Resource | Quota |
| --- | --- |
| Number of microVMs | 10 |
| vCPUs | 4 |
| RAM | 32 GiB |
| RAM (per microVM) | 8 GiB |
| Disk | 40 GiB |
| Groups | 2 |

If you need a higher quota, email [sipb-hyades-root@mit.edu](mailto:sipb-hyades-root@mit.edu).

## MIT auth integration

Hyades integrates with MIT's authentication system using [Petrock](https://petrock.mit.edu/), another SIPB project. This is a bit like Scripts' port 444 certificates feature.

For any *.sipb.cloud site, visiting `/hlogin` (for instance, https://hyades-test.sipb.cloud/hlogin) will redirect the user to Petrock. Your site should additionally redirect `/hlogin` to a nice landing page for the logged-in user. Similarly, `/hlogout` will log out the user. By default, users will remain logged in for 14 days.

You can use the following HTTP headers to get information about a logged-in user:

| Header | Description |
| --- | --- |
| `X-Forwarded-Anonymous` | `true` if the user is not logged in, otherwise `false`. If `true`, then the remaining headers will be filled with junk data! |
| `X-Forwarded-Email` | The user's email. |
| `X-Forwarded-Affiliation` | The user's affiliation. |
| `X-Forwarded-Name` | The user's full name. |
| `X-Forwarded-Given-Name` | The user's first name. |
| `X-Forwarded-Family-Name` | The user's last name. |

See the [Petrock docs](https://petrock.mit.edu/about/#user-information) for more details.

## Full docs for `hyades.json`

Throughout this guide we've been editing the `~/.config/hyades.json` file, which is basically `docker-compose.yml` but in JSON and much simpler. Here is the full documentation for that file:

- `image`: The OCI image for your microVM.
- `ports`: A map consisting of `NAME` and `PORT` pairs such that `NAME.sipb.cloud` gets reverse-proxied to `PORT` in your microVM. For custom domains, email [sipb-hyades-root@mit.edu](mailto:sipb-hyades-root@mit.edu).
- `volumes`: A map from volume names to mount paths. Volumes can be shared among multiple microVMs.
- `envs`: A map from environment variable names to values.
- `network`: If set to the empty string, then the microVM gets its own isolated network. Otherwise, if set to the name of another microVM, this microVM shares a network with the other microVM. Basically, they share the same localhost. This also makes Hyades start the current microVM after the microVM that provides its network is up.
- `exposeports`: An array of TCP or UDP ports to expose from the container. This is potentially DANGEROUS and usually you should use `ports` instead.

## Running a full Linux distro on Hyades

There are two main ways to run a full Linux distro on Hyades: bootable containers and NixOS. Since Hyades is based on ephemeral microVMs with persistent volumes, it's not possible to use a traditional Linux distro with a persistent root filesystem on Hyades.

Some additional limitations include:

1. microVMs on Hyades use a special, non-customizable kernel and you can't load additional kernel modules.
2. microVMs use TSI (transparent socket impersonation) for networking which only supports UDP and TCP, so low-level networking stuff like VPNs or raw sockets won't work on Hyades.

### Bootable containers

[Bootable containers](https://bootc.dev/) are an increasingly popular way to deploy Linux distros, used by projects such as [Bazzite](https://bazzite.gg/) and [Blue95](https://blues.win/95/).

First, find a bootable container image for the OS you want to run, for instance `quay.io/fedora/fedora-bootc`. Note that a regular image like `docker.io/fedora` will *not* work for this since it's missing software such as systemd which are needed to fully boot up the OS.

On Hyades, create the microVM as usual but make sure you add the environment variable `KRUN_INIT_PID1=1` for your microVM. Now start up the microVM and run `exec NAME bash` to get a root shell.

Before bootup, a `/etc/resolv.conf` is generated with the MIT nameservers, but it might get clobbered by systemd-resolved, resulting in broken DNS. If that happens, edit `/etc/resolv.conf` to use hardcoded MIT nameservers:

```
nameserver 18.0.70.160
nameserver 18.0.72.3
nameserver 18.0.71.151
options edns0
```

You may also need to edit the `hosts:` line in `/etc/nsswitch.conf` to make DNS resolution stop using systemd-resolved.

You can preinstall software by writing a Dockerfile and building it with the Forgejo CI.

### NixOS

[NixOS](https://nixos.org/) has good support for building layered OCI images. Note that this approach only supports NixOS, not arbitrary Linux distros.

First, add the following package to your flake outputs:

```nix
packages.${system}.default = pkgs.dockerTools.streamLayeredImage {
  contents = [ self.nixosConfigurations.HOSTNAME.config.system.build.toplevel ];
  config.Entrypoint = [ "/init" ];
  extraCommands = ''
    rm -f etc
    mkdir etc
  '';
  includeNixDB = true;
};
```

Then, set `boot.isContainer = true;` in your NixOS config. You can also import the `"${nixpkgs}/nixos/modules/profiles/minimal.nix"` module to make the final image slightly smaller.

If you want SSH, enable it on a port other than 22 and make a volume on Hyades mounted at `/etc/ssh/keys` for the SSH host keys:

```nix
services.openssh = {
  # Put host keys in a volume instead
  generateHostKeys = false;
  extraConfig = ''
    HostKey /etc/ssh/keys/ssh_host_rsa_key
    HostKey /etc/ssh/keys/ssh_host_ed25519_key
  '';
};
```

To get networking inside the microVM, add:

```nix
networking = {
  # Disable dhcpcd which makes networking really slow
  dhcpcd.enable = false;
  # Stop NixOS from clobbering krun's /etc/resolv.conf
  resolvconf.enable = false;
};
```

Now build it with `nix build`, which will produce a shell script `result` that assembles the Docker image when run. Load it into Podman (or Docker) with `./result | podman load` (do *not* use `podman import`) and push it to your favorite OCI image registry.

Finally, on Hyades, set the environment variables `KRUN_INIT_PID1=1` and `PATH=/run/current-system/sw/bin` and try booting it up! Like with bootable containers, you can run `exec NAME bash` to get a root shell.

## Bugs

If you encounter any bugs, please report them on the [Hyades bug tracker](https://forgejo.mit.edu/SIPB/hyades/issues). The one exception is security vulnerabilities, which should instead be disclosed via email to [sipb-hyades-root@mit.edu](mailto:sipb-hyades-root@mit.edu).

[^1]: Technically this is false. Hyades uses Podman and krun which runs the microVM *inside* a container.
