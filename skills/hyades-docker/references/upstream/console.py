# flake8: noqa: E501 PLW1510

import json
import os
import readline
from cmd import Cmd
from getpass import getuser
from pathlib import Path
from random import randrange
from re import compile
from secrets import token_hex
from shutil import rmtree
from string import Template
from subprocess import CalledProcessError, run
from time import sleep
from traceback import format_exc


def check_newline(s):
    if "\n" in s:
        raise ValueError(f"{s} cannot contain new line")


name_re = compile(r"[a-z0-9_][a-z0-9_-]*")


def check_name(s):
    if not name_re.fullmatch(s):
        raise ValueError(
            f"{s} can only contain lowercase letters, numbers, hyphens, and underscores"
        )


image_re = compile(r"[a-z0-9\.:/_][a-z0-9\.:/_-]*")


def check_image(s):
    if not image_re.fullmatch(s):
        raise ValueError(
            f"{s} can only contain lowercase letters, numbers, dots, colons, slashes, hyphens, and underscores"
        )


var_re = compile(r"[a-zA-Z0-9_]+")


def check_var(s):
    if not var_re.fullmatch(s):
        raise ValueError(f"{s} can only contain letters, numbers, and underscores")


def reddit(file, arg):
    if "v" in arg:
        editor = ["rvim"]
    else:
        editor = ["rnano", "-ET4"]
    run(
        [
            "bwrap",
            "--unshare-all",
            "--ro-bind",
            f"/run/current-system/sw/bin/{editor[0]}",
            f"/run/current-system/sw/bin/{editor[0]}",
            "--ro-bind",
            "/nix/store",
            "/nix/store",
            "--bind",
            file,
            file,
            *editor,
            file,
        ]
    )


# Print out any user messages
message_file = Path("~/message").expanduser()
if message_file.exists():
    print(message_file.read_text())
    input("Press enter to confirm you have read that message.")
    message_file.unlink()

# Allow running microVMs even when not logged in
run(["loginctl", "enable-linger"])

# Load Quadlet template
with open("/etc/quadlet") as f:
    template = Template(f.read())


storage_path = Path("~/.local/share/containers/storage").expanduser()
storage_path.mkdir(parents=True, exist_ok=True)
image_path = storage_path / "overlay"
if not image_path.exists():
    try:
        # Put images on a separate subvolume to exclude them from backups
        run(["btrfs", "subvolume", "create", image_path], check=True)
    except (FileNotFoundError, CalledProcessError):
        # No btrfs (i.e. in a VM)
        image_path.mkdir(exist_ok=True)


quadlet_path = Path("~/.config/containers/systemd").expanduser()
quadlet_path.mkdir(parents=True, exist_ok=True)
tmp_quadlet_path = Path("~/.config/containers/systemd.tmp").expanduser()

hyades_conf = {}
conf_path = Path("~/.config/hyades.json").expanduser()


def save_conf():
    with open(conf_path, "w") as f:
        json.dump(hyades_conf, f, indent=4)


def load_conf():
    global hyades_conf
    with open(conf_path) as f:
        hyades_conf = json.load(f)


if not conf_path.exists():
    save_conf()
else:
    try:
        load_conf()
    except json.decoder.JSONDecodeError:
        print(format_exc())


username = getuser()
histfile = Path("~/.hyades_history").expanduser()


class HyadesConsole(Cmd):
    intro = """=== Welcome to the Hyades console ===

Type ? or help to show help
User guide: https://hyades.mit.edu/inessential.html
"""
    prompt = f"(\x1b[36m{username}\x1b[0m@\x1b[34mhyades\x1b[0m) "

    def onecmd(self, line):
        try:
            if line == "hyades":
                print(
                    int.to_bytes(
                        11612522591240974585034247332730751830094887225168553688626135407572704439185311074937402030920487835399674650420578021979064658006718942622471413529697304043069223460789255838806701973249425278267728462762885531128866408970,
                        93,
                    ).decode("utf-8")
                )
                x = 0
                while True:
                    x = (x << 12) & ~((-1) << 60) | (
                        randrange(1 << 12) & randrange(1 << 12)
                    )
                    print(
                        f"{'\x1b[1A\x1b[2K' * 6}    \x1b[34m{''.join(['\n' + ' ' * (3 - i // 12) if i % 12 == 11 else '/' if x & (1 << i) else ' ' for i in range(60)])}\x1b[0m"
                    )
                    sleep(0.15)
            return super().onecmd(line)
        except KeyboardInterrupt:
            # Allow using Ctrl-C here to interrupt
            pass
        except Exception:  # noqa: BLE001
            print(format_exc())
            return False

    def preloop(self):
        if histfile.exists():
            readline.read_history_file(histfile)

    def postloop(self):
        readline.write_history_file(histfile)

    def completedefault(self, text, line, beginidx, endidx):
        if line.count(" ") > 1:
            # Don't try to complete second arg
            return []
        return [name for name in hyades_conf if name.startswith(text)]

    def do_regenerate(self, arg):
        "regenerate: Regenerate internal files from Hyades config"
        rmtree(tmp_quadlet_path, ignore_errors=True)
        tmp_quadlet_path.mkdir(parents=True)
        if len(hyades_conf) > 10:
            raise ValueError("Cannot create more than 10 microVMs")
        for name, conf in hyades_conf.items():
            check_name(name)
            check_image(conf["image"])
            if len(conf["ports"]) > 10:
                raise ValueError(f"Cannot have more than 10 subdomains for {name}")
            for subdomain, port in conf["ports"].items():
                check_name(subdomain)
                int(port)
            volumes = []
            for vol, path in conf["volumes"].items():
                check_name(vol)
                check_newline(path)
                volumes.append(f"Volume={vol}:{path}")
            envs = []
            for var, val in conf["envs"].items():
                check_var(var)
                check_newline(val)
                envs.append(f"Environment={var}={val}")
            if conf["network"]:
                check_name(conf["network"])
                if conf["network"] not in hyades_conf:
                    raise ValueError(
                        f"{name} cannot join network of nonexistent microVM {conf['network']}"
                    )
                network = f"Network={conf['network']}.container"
            else:
                network = ""
            if len(conf["exposeports"]) > 10:
                raise ValueError(f"Cannot expose more than 10 ports for {name}")
            for port in conf["exposeports"]:
                # Reserve TCP/UDP ports
                # If this fails then abort generating the Quadlets
                Path("/srv/ports", str(int(port))).touch()
            quadlet = template.substitute(
                {
                    "NAME": name,
                    "IMAGE": conf["image"],
                    "PORTS": json.dumps(conf["ports"]),
                    "AFTER": f"After=socat@{name}.service\nWants=socat@{name}.service"
                    if conf["ports"]
                    else "",
                    "VOLUMES": "\n".join(volumes),
                    "ENVS": "\n".join(envs),
                    "NETWORK": network,
                    "EXPOSEPORTS": "\n".join(
                        f"PublishPort={int(port)}:{int(port)}"
                        for port in conf["exposeports"]
                    ),
                }
            )
            quadlet_file = tmp_quadlet_path / f"{name}.container"
            with open(quadlet_file, "w") as f:
                f.write(quadlet)
        # Atomic swap old and new directories
        run(["exch", quadlet_path, tmp_quadlet_path])
        # Reload systemd to detect new files
        run(["systemctl", "--user", "daemon-reload"])

    def do_list(self, arg):
        "list: Get list of microVMs"
        print("\n".join(hyades_conf.keys()))

    def do_getconf(self, arg):
        "getconf NAME?: Get configuration for microVM (useful for scripting)"
        print(json.dumps(hyades_conf if arg == "" else hyades_conf[arg], indent=4))

    def do_setconf(self, arg):
        "setconf NAME: Set configuration for microVM (useful for scripting)"
        name, conf = arg.split(" ", 1)
        hyades_conf[name] = json.loads(conf)
        save_conf()
        self.do_regenerate("")

    def do_create(self, arg):
        "create NAME IMAGE PORT?: Create new microVM"
        args = arg.split()
        name, image = args[0], args[1]
        ports = {}
        if len(args) > 2:
            ports[name] = int(args[2])
            if Path("/srv/sockets", name).exists():
                raise ValueError(f"Subdomain {name} already taken by another microVM")
        check_name(name)
        if name in hyades_conf:
            raise ValueError(f"microVM {name} already exists")
        # image cannot contain newlines since they're removed by split()
        hyades_conf[name] = {
            "image": image,
            "ports": ports,
            "volumes": {},
            "envs": {},
            "network": "",
            "exposeports": [],
        }
        save_conf()
        self.do_regenerate("")

    def do_edit(self, arg):
        "edit: Edit Hyades config"
        reddit(conf_path, arg)
        load_conf()
        self.do_regenerate("")

    def do_lsvol(self, arg):
        "lsvol: List all volumes on disk"
        run(["podman", "volume", "ls"])

    def do_rmvol(self, arg):
        "rmvol VOL: Delete volume from disk"
        run(["podman", "volume", "rm", arg])

    # TODO: We need Podman 6.1.0 for podman volume rename
    # https://github.com/podman-container-tools/podman/issues/28189
    # def do_mvvol(self, arg):

    def do_expvol(self, arg):
        "expvol VOL: Export volume to stdout"
        run(["podman", "volume", "export", arg])

    def do_impvol(self, arg):
        "impvol VOL: Import volume from stdin"
        # Create volume if not exists or otherwise the import fails
        run(["podman", "volume", "create", "--ignore", arg])
        run(["podman", "volume", "import", arg, "-"])

    def do_exec(self, arg):
        "exec NAME CMD: Execute command inside microVM"
        name, cmd = arg.split(" ", 1)
        check_name(name)
        run(["podman", "exec", "-it", name, "--", cmd])

    def do_start(self, arg):
        "start NAME: Start microVM"
        run(["systemctl", "--user", "start", arg])

    def do_stop(self, arg):
        "stop NAME: Stop microVM"
        run(["systemctl", "--user", "stop", arg])

    def do_restart(self, arg):
        "restart NAME: Restart microVM"
        run(["systemctl", "--user", "restart", arg])

    def do_kill(self, arg):
        "kill NAME: Kill microVM"
        run(["systemctl", "--user", "kill", arg])

    def do_status(self, arg):
        "status NAME: Get status of microVM"
        run(["systemctl", "--user", "status", arg])

    def do_logs(self, arg):
        "logs NAME: Get logs of microVM"
        run(["journalctl", "--user", "-xeu", arg])

    def do_stats(self, arg):
        "stats: Monitor resource usage of microVMs"
        run(["podman", "stats"])

    def do_df(self, arg):
        "df: Get disk usage of images and volumes"
        run(["podman", "system", "df", "-v"])

    def do_updtoken(self, arg):
        "updtoken: Generate a token for triggering updates"
        sockdir = Path("~/.config/systemd/user/sockets.target.wants").expanduser()
        rmtree(sockdir, ignore_errors=True)
        sockdir.mkdir(parents=True)
        token = token_hex(16)
        # Manually make symlink because `systemctl enable` links to the Nix store
        # https://github.com/NixOS/nixpkgs/issues/344371
        os.symlink(
            "/etc/systemd/user/podman-auto-update-trigger@.socket",
            sockdir / f"podman-auto-update-trigger@{token}.socket",
        )
        run(
            [
                "systemctl",
                "--user",
                "start",
                f"podman-auto-update-trigger@{token}.socket",
            ]
        )
        print(
            f"Your update token is {token}. Store it somewhere safe since you will not be able to view it again! It will be invalidated if you generate a new token."
        )

    def do_tmprun(self, arg):
        "tmprun IMAGE CMD?: Run a temporary microVM with all volumes mounted"
        runcmd = ["podman", "run", "--rm", "-it"]
        for conf in hyades_conf.values():
            for vol in conf["volumes"]:
                check_name(vol)
                runcmd.append("-v")
                runcmd.append(f"{vol}:/mnt/{vol}")
        args = arg.split(" ", 1)
        check_image(args[0])
        runcmd.append(args[0])
        if len(args) > 1:
            runcmd.append("--")
            runcmd.append(args[1])
        run(runcmd)

    def do_delete(self, arg):
        "delete NAME: Delete microVM (does NOT delete its volumes)"
        check_name(arg)
        self.do_stop(arg)
        # We can't just pass missing_ok=True since we need to catch other exceptions like PermissionError
        try:
            (quadlet_path / f"{arg}.container").unlink()
        except OSError as e:
            print(e)
        for subdomain in hyades_conf[arg]["ports"]:
            check_name(subdomain)
            try:
                Path("/srv/sockets", subdomain).unlink()
            except OSError as e:
                print(e)
        for port in hyades_conf[arg]["exposeports"]:
            try:
                Path("/srv/ports", str(int(port))).unlink()
            except OSError as e:
                print(e)
        run(["systemctl", "--user", "daemon-reload"])
        del hyades_conf[arg]
        save_conf()

    def do_login(self, arg):
        "login REGISTRY: Authenticate to OCI image registry"
        # Save credentials to a persistent file for auto-updates
        run(
            [
                "podman",
                "login",
                "--authfile",
                Path("~/.config/containers/auth.json").expanduser(),
                arg,
            ]
        )

    def do_update(self, arg):
        "update: Check all images for updates"
        run(["podman", "auto-update"])

    def do_wordpress(self, arg):
        "wordpress NAME: One-command installer for WordPress"
        check_name(arg)
        print(f"Creating {arg}...")
        self.do_create(f"{arg} docker.io/soulteary/sqlite-wordpress 80")
        hyades_conf[arg]["volumes"][f"{arg}_wordpress"] = "/var/www/html"
        save_conf()
        self.do_regenerate("")
        print(f"Starting {arg}...")
        self.do_start(arg)

    def do_entergp(self, arg):
        "entergp GROUP CMD?: Enter a Moira group account and optionally run a command"
        run(["sudo", "entergp", *arg.split(" ", 1)])

    def do_editssh(self, arg):
        "editssh: Edit ~/.ssh/authorized_keys"
        Path("~/.ssh").expanduser().mkdir(exist_ok=True)
        reddit(Path("~/.ssh/authorized_keys").expanduser(), arg)

    def do_timetravel(self, arg):
        "timetravel DATE?: Get Hyades configuration at a previous date"
        if arg == "":
            for dir in Path("/.snapshots").iterdir():
                if (dir / "mit" / username / ".config/hyades.json").exists():
                    print(dir.suffix[1:])
        else:
            print(
                Path(
                    "/.snapshots",
                    f"hyades.{int(arg)}",
                    "mit",
                    username,
                    ".config/hyades.json",
                ).read_text()
            )

    def do_exit(self, arg):
        "exit: Exit the Hyades console"
        return True

    # https://stackoverflow.com/questions/50339501/python-cmd-cmd-exit-on-ctrld
    def do_EOF(self, arg):
        "EOF: Exit on Ctrl-D"
        return True


hyades = HyadesConsole()
if "SSH_ORIGINAL_COMMAND" in os.environ:
    hyades.onecmd(os.environ["SSH_ORIGINAL_COMMAND"])
else:
    try:
        hyades.cmdloop()
    except KeyboardInterrupt:
        readline.write_history_file(histfile)
