`exec NAME CMD` fails for any microVM whose image runs as a non-root `USER`:

```
(djbclark@hyades) exec djbclark-rustpad sh
Error: krun: chown `/dev/pts/1`: Operation not permitted: OCI permission denied
```

`docker.io/ekzhang/rustpad` has `User: 1000:1000`. Same result over `ssh hyades exec ...` with or without `-tt`. `tmprun` with a root image (alpine) gets a terminal fine, and `tmprun docker.io/ekzhang/rustpad` (uid 1000, `run` path) also starts, so it looks specific to exec + terminal + non-root.

Looks like crun's `open_terminal` (`linux.c`) does `chown(pty, process->user->uid)`, which fails here; with krun the pty isn't even used inside the guest (exec goes through `ssh -tt`). Possible fixes: ignore that `EPERM` in the krun handler, or have the console pass `-t` only when stdin is a TTY.

The same `-t`-only-with-a-TTY change would also help `tmprun` with a script piped on stdin. Today that goes through a pty, so lines over 4095 bytes are cut, a command that reads stdin (apt's debconf prompt) eats the rest of the script, and the output carries terminal escapes.

---
Full technical detail (long, written for AI agents): https://forgejo.mit.edu/djbclark/hyades/issues/1
_Prepared with an AI coding assistant; results reviewed by me._
