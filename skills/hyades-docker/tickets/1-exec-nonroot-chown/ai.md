## Summary

Hyades console `exec NAME CMD` (`podman exec -it NAME -- CMD`) fails before the
command runs whenever the target container's process user is non-root:

```
Error: krun: chown `/dev/pts/N`: Operation not permitted: OCI permission denied
```

## Environment (2026-10-14)

1. Hyades console from SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`
   (`hyades/console.py` `do_exec`, line ~314).
2. Runtime: podman 5.8.8 (rootless, `/nix/store/...-podman-5.8.8`), `engine.runtime = "krun"`,
   crun `1.30.1-sipb` from github.com/sipb/crun rev `391b866dd41b2aac93ced07975fb210fa26982af`
   (`overlays.nix`), libkrun "2.0-sipb", guest kernel 6.12.109.
3. User: `djbclark` (uid 93409 on the host), logged in with an SSH key (not `ssh -K`).
4. Target: microVM `djbclark-rustpad`, image `docker.io/ekzhang/rustpad:latest`
   (`f4534d858356`), image config `User: "1000:1000"`, `Cmd: ["./rustpad-server"]`.

## Reproduction (all run by the reporter, 2026-10-14 17:35-17:55 EDT)

| Attempt | Result |
|---|---|
| `ssh djbclark@hyades.mit.edu exec djbclark-rustpad ls /` (no local TTY) | `Error: krun: chown /dev/pts/0: Operation not permitted: OCI permission denied` |
| `printf 'ls /; exit\n' \| ssh -tt djbclark@hyades.mit.edu exec djbclark-rustpad sh` | same error, `/dev/pts/1` |
| interactive console over `ssh -tt`, typing `exec djbclark-rustpad sh` | same error |
| `printf 'uname -a; exit\n' \| ssh ... tmprun docker.io/library/alpine` (uid 0, `podman run --rm -it`) | works: `Linux ... 6.12.109 ... x86_64` |
| `ssh ... tmprun docker.io/ekzhang/rustpad` (uid 1000, `podman run --rm -it`) | works: server starts (container visible in `df`) |

So: `run` with a terminal works for uid 0 and uid 1000; `exec` with a terminal
fails for uid 1000. An `exec` into a uid-0 microVM was not tested (no such
microVM on this account).

## Code reading

1. `console.py` `do_exec`: `run(["podman", "exec", "-it", name, "--", cmd])`. `-t`
   is unconditional.
2. sipb/crun `src/libcrun/linux.c` `open_terminal` (around line 5088 at the rev above):

   ```c
   if (process && process->user)
     uid = process->user->uid;
   fd = libcrun_new_terminal (pty, err);
   ...
   if (uid)
     {
       ret = chown (*pty, uid, -1);
       if (UNLIKELY (ret < 0))
         return crun_make_error (err, errno, "chown `%s`", *pty);
     }
   ```

   The error text matches exactly (`chown` + backticked pty path; podman prefixes
   the runtime name `krun:`). For uid 0 the chown is skipped, which matches the
   alpine success.
3. sipb/crun `src/libcrun/handlers/krun.c` `libkrun_exec_ssh` (line ~657): exec is
   implemented by running `ssh -q -F.../20-systemd-ssh-proxy.conf [-tt] ...` against
   the guest's vsock SSH server; when `process->terminal` it adds `-tt`, so the
   guest side allocates its own pty. The host-side pty that crun chowns is only
   ssh's stdio.

## Hypothesis (not verified)

In rootless podman, crun runs inside the user's user namespace. With the normal
crun runtime the pty comes from a devpts instance mounted inside the container
(owned by that user namespace), so `chown` to the container uid succeeds. With
the krun handler the exec happens on the host side and the pty comes from a
devpts instance the user namespace does not own (or uid 1000 is mapped to a
subuid the namespace cannot assign on that pty), so `chown` returns `EPERM`.
The original uid-1000 container process inside the guest is unaffected.

## Suggested fixes (any one)

1. sipb/crun krun handler: tolerate `EPERM` from that `chown` when the exec
   handler is `libkrun_exec_ssh`, since the pty is only ssh's local stdio
   (smallest, targeted change).
2. Console: `-t` only when the SSH session has a TTY:
   `["podman", "exec", "-i"] + (["-t"] if sys.stdin.isatty() else []) + [name, "--", *shlex.split(cmd)]`.
   This fixes scripted use (`ssh hyades exec NAME CMD`) but not interactive shells.
3. Console: `podman exec -it --user 0 ...` (skips the chown path; changes the
   user commands run as, so probably not desirable).

## Impact

`exec NAME bash` is the documented way to edit a volume or get a root shell in
a bootc/NixOS microVM (inessential guide, "Working with volumes" and "Running a
full Linux distro"). Many Docker Hub images set a non-root `USER`, so this blocks
it for them. Workaround today: `tmprun IMAGE` with a script on stdin (all
volumes are mounted under `/mnt`).

## Related

A separate issue covers `exec NAME CMD` passing CMD as a single argv element.

## Duplicate search (2026-10-14, after filing)

Searched for existing reports of this and the sibling console bugs:
1. SIPB/hyades and SIPB/hyades-action issues, all states: only SIPB/hyades #1 (closed, unrelated Ctrl+D request) and our own #2-#8.
2. containers/crun GitHub issues for "krun chown", "open_terminal chown", "exec tty krun permission denied": no hits.
3. github.com/sipb/crun has issues disabled. Upstream containers/crun's `handlers/krun.c` has no exec path at all (sipb/crun main is 5 commits ahead of containers/crun main), so the exec/pty bug is SIPB-specific and SIPB/hyades is the right tracker.
