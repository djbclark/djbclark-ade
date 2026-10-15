**Upstream issue:** https://forgejo.mit.edu/SIPB/hyades/issues/8

> This is the full technical report, written for AI coding agents (verbose by design). The short human-readable version lives upstream. Prepared with an AI coding assistant; results reviewed by @djbclark.

## Summary

A `tmprun` microVM (`podman run --rm -it ...`) outlives the SSH session that
started it when the client disconnects. The console has no command to list or
stop such containers, so they keep consuming the user's quota until the server
restarts or the user discovers the systemd scope trick below.

## Environment

SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`; podman 5.8.8 rootless,
krun runtime; tested 2026-10-14 ~17:54 EDT as `djbclark` with an SSH key.

## Reproduction

```
$ timeout 25 ssh -o BatchMode=yes djbclark@hyades.mit.edu tmprun docker.io/ekzhang/rustpad < /dev/null
time="2026-10-14T17:53:57-04:00" level=warning msg="The input device is not a TTY. ..."
# exit 124 (timeout killed the local ssh client)

$ ssh djbclark@hyades.mit.edu df          # 25 s later, and again 15 s after that
Containers space usage:
CONTAINER ID  IMAGE         COMMAND           LOCAL VOLUMES  SIZE     CREATED     STATUS   NAMES
bd4dd8c1c8a2  f4534d858356  ./rustpad-server  0              28.32kB  3 hours     running  djbclark-rustpad
932f6e985872  f4534d858356  ./rustpad-server  0              26.59kB  45 seconds  running  wizardly_hypatia
```

`stop wizardly_hypatia` / `kill wizardly_hypatia` do nothing useful (they map to
`systemctl --user stop|kill wizardly_hypatia`, and there is no such unit). This
worked:

```
$ ssh djbclark@hyades.mit.edu status 'libpod-932f6e985872*'
● libpod-932f6e985872277af185bedea879f770cc1582786e28c64fd9b9f87d716da53b.scope - libcrun container
     Loaded: loaded (/run/user/93409/systemd/transient/libpod-....scope; transient)
     Active: active (running) since Wed 2026-10-14 17:53:57 EDT; 52s ago
$ ssh djbclark@hyades.mit.edu stop 'libpod-932f6e985872*'
$ ssh djbclark@hyades.mit.edu df          # container gone (--rm removed it)
```

It works because `do_stop` passes its argument unvalidated to
`systemctl --user stop`, which accepts glob patterns for loaded units. (That
lack of `check_name` in start/stop/restart/kill/status/logs is probably fine
security-wise, since it is the user's own systemd instance, but worth knowing.)

## Update 2026-10-14 (evening): a guest kernel oops orphans it too

Second trigger, with the SSH client alive: the guest kernel oops of SIPB/hyades#9
(`getsockopt(SOL_IP, IP_TOS)` on a TSI UDP socket; libkrunfw#140). In
`tmprun docker.io/library/python:3-alpine` the oops killed `python3`
("note: python3[496] exited with irqs disabled"), but the microVM never exited:
`tmprun` did not return, and after the local client was stopped by `timeout`
the container stayed `running` in `df`. Three such orphans were stopped with
`stop libpod-<id>*` during that investigation (in stdin mode the console takes
quotes literally, so the argument goes unquoted). A unit tied to the SSH session
would not help this case; a `ps`/`tmpstop` command (or a run-time limit for
`tmprun`) would.

## Probable cause

With no TTY (or after the TTY's controlling process dies), sshd closes the
session, the `podman run` client process exits or is killed by SIGHUP, but the
container itself is supervised by conmon in its own transient scope
(`libpod-<id>.scope`, `libpod-conmon-<id>.scope`), so it is not in the SSH
session's cgroup and receives no signal. `--rm` only acts when the container
exits. Not verified which signal path applies here.

## Suggestions

1. Tie the container to the console process: give it a known
   `--name tmprun-<random>` and stop it in a `finally` in `do_tmprun`. Smallest
   change (untested sketch):
   ```python
   name = f"tmprun-{token_hex(4)}"
   runcmd = ["podman", "run", "--rm", "-it", "--name", name, ...]
   try:
       run(runcmd)
   finally:
       run(["podman", "stop", "--ignore", "-t", "5", name])
   ```
   (SIGHUP would need a handler that raises, e.g. `signal.signal(SIGHUP, lambda *_: sys.exit(129))`,
   for the `finally` to run.)
2. Or add read-only `ps` (`podman ps --filter ...`) and a `tmpstop NAME`
   restricted to non-Quadlet containers.
3. Document the `stop 'libpod-<id>*'` workaround meanwhile.

## Impact

Easy to hit with scripted use (`ssh hyades tmprun IMAGE < script` with a
timeout, or a dropped Wi-Fi connection during an interactive `tmprun ubuntu`).
Orphans consume vCPU/RAM quota and keep volumes mounted read-write.


## Duplicate search (2026-10-14, after filing)

Searched for existing reports of this and the sibling console bugs:
1. SIPB/hyades and SIPB/hyades-action issues, all states: only SIPB/hyades #1 (closed, unrelated Ctrl+D request) and our own #2-#8.
2. containers/crun GitHub issues for "krun chown", "open_terminal chown", "exec tty krun permission denied": no hits.
3. github.com/sipb/crun has issues disabled. Upstream containers/crun's `handlers/krun.c` has no exec path at all (sipb/crun main is 5 commits ahead of containers/crun main), so the exec/pty bug is SIPB-specific and SIPB/hyades is the right tracker.

