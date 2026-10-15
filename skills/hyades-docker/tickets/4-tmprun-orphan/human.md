If the SSH connection drops while `tmprun` is running, the temporary microVM keeps running, and there's no console command to see or stop it:

```
$ timeout 25 ssh hyades tmprun docker.io/ekzhang/rustpad    # killed after 25 s
$ ssh hyades df
... 932f6e985872  f4534d858356  ./rustpad-server  ...  running  wizardly_hypatia
```

It stayed up after the client was gone (it counts against the 4 vCPU / 32 GiB quota). The only way I found to stop it was `stop 'libpod-932f6e985872*'`, which works because `stop` passes its argument straight to `systemctl --user`.

A guest kernel oops (#9) orphans it the same way with the SSH session still up: `tmprun` never returns and the container stays `running`.

Ideas: run `tmprun` containers under a unit tied to the SSH session (`systemd-run --user --scope` / `--pipe`), or add a small `ps`/`tmpstop` command.

---
Full technical detail (long, written for AI agents): https://forgejo.mit.edu/djbclark/hyades/issues/4
_Prepared with an AI coding assistant; results reviewed by me._
