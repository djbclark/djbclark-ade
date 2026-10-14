`exec NAME CMD` fails for any microVM whose image runs as a non-root `USER`:

```
(djbclark@hyades) exec djbclark-rustpad sh
Error: krun: chown `/dev/pts/1`: Operation not permitted: OCI permission denied
```

`docker.io/ekzhang/rustpad` has `User: 1000:1000`. Same result over `ssh hyades exec ...` with or without `-tt`. `tmprun` with a root image (alpine) gets a terminal fine, and `tmprun docker.io/ekzhang/rustpad` (uid 1000, `run` path) also starts, so it looks specific to exec + terminal + non-root.

Looks like crun's `open_terminal` (`linux.c`) does `chown(pty, process->user->uid)`, which fails here; with krun the pty isn't even used inside the guest (exec goes through `ssh -tt`). Possible fixes: ignore that `EPERM` in the krun handler, or have the console pass `-t` only when stdin is a TTY.
