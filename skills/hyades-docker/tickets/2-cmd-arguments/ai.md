## Summary

Hyades console commands that take a trailing command (`tmprun IMAGE CMD?`,
`exec NAME CMD`) build the podman argv incorrectly:

1. `tmprun IMAGE CMD`: the guest is asked to execute the literal string `--`.
2. `exec NAME CMD` (and `tmprun` once 1 is fixed): CMD is passed as a single
   argv element, so any command with arguments fails.

## Environment

SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`, `hyades/console.py`;
podman 5.8.8 rootless with krun; tested 2026-10-14 as `djbclark` over SSH key.

## Reproduction

```
$ ssh -tt djbclark@hyades.mit.edu tmprun docker.io/library/alpine uname
Trying to pull docker.io/library/alpine:latest...
Getting image source signatures
Writing manifest to image destination
Couldn't execute '--': ENOENT: No such file or directory

$ ssh djbclark@hyades.mit.edu tmprun docker.io/library/alpine uname     # no TTY
time="..." level=warning msg="The input device is not a TTY. The --tty and --interactive flags might not work properly"
Couldn't execute '--': ENOENT: No such file or directory

$ printf 'uname -a; ls /mnt; nproc; exit\n' | ssh djbclark@hyades.mit.edu tmprun docker.io/library/alpine
Linux 84a13629850f 6.12.109 #1 SMP PREEMPT_DYNAMIC Mon Sep 21 20:29:27 CEST 2026 x86_64 Linux
4
```

The third form (no CMD, script on stdin) is the working workaround.

`exec NAME CMD` with arguments could not be demonstrated end to end because exec
currently fails earlier for non-root images (separate issue: pty chown), but the
argv is visible in the code.

## Code

```python
def do_exec(self, arg):
    "exec NAME CMD: Execute command inside microVM"
    name, cmd = arg.split(" ", 1)
    check_name(name)
    run(["podman", "exec", "-it", name, "--", cmd])          # cmd is ONE element

def do_tmprun(self, arg):
    "tmprun IMAGE CMD?: Run a temporary microVM with all volumes mounted"
    runcmd = ["podman", "run", "--rm", "-it"]
    ...
    args = arg.split(" ", 1)
    check_image(args[0])
    runcmd.append(args[0])
    if len(args) > 1:
        runcmd.append("--")                                   # after IMAGE: becomes the command
        runcmd.append(args[1])                                # ONE element
    run(runcmd)
```

`podman run [options] IMAGE [COMMAND [ARG...]]`: everything after IMAGE is the
container command, so `--` there is not an option terminator but argv[0]. For
`podman exec [options] CONTAINER [COMMAND [ARG...]]`, `--` after the container
name is accepted by podman's CLI parser (cobra stops flag parsing), so exec only
suffers from the single-element problem.

## Suggested patch

```python
import shlex

def do_exec(self, arg):
    name, cmd = arg.split(" ", 1)
    check_name(name)
    run(["podman", "exec", "-it", name, *shlex.split(cmd)])

def do_tmprun(self, arg):
    ...
    args = arg.split(" ", 1)
    check_image(args[0])
    runcmd += ["--", args[0]]          # terminate podman's options before IMAGE
    if len(args) > 1:
        runcmd += shlex.split(args[1])
    run(runcmd)
```

Note that SSH already joins the client's argv with spaces before the console
sees `SSH_ORIGINAL_COMMAND`, so `shlex.split` gives users normal shell-like
quoting (`exec web sh -c 'ls /data'`). `shlex.split` raises `ValueError` on an
unbalanced quote, which the console's `onecmd` already reports.

## Impact

The inessential guide recommends `tmprun ubuntu` to edit volumes; any
non-interactive or scripted use (`ssh hyades tmprun IMAGE some-command`) fails
today.

## Duplicate search (2026-10-14, after filing)

Searched for existing reports of this and the sibling console bugs:
1. SIPB/hyades and SIPB/hyades-action issues, all states: only SIPB/hyades #1 (closed, unrelated Ctrl+D request) and our own #2-#8.
2. containers/crun GitHub issues for "krun chown", "open_terminal chown", "exec tty krun permission denied": no hits.
3. github.com/sipb/crun has issues disabled. Upstream containers/crun's `handlers/krun.c` has no exec path at all (sipb/crun main is 5 commits ahead of containers/crun main), so the exec/pty bug is SIPB-specific and SIPB/hyades is the right tracker.
