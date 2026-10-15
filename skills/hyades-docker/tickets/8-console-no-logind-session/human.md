Since about 22:20 EDT on 2026-10-14, every console command that calls `systemctl --user` fails for me, and every login prints a linger error:

```
$ ssh hyades status djbclark-fc-searxng
Could not enable linger: No such device or address
Failed to connect to user scope bus via local transport: $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined (...)
```

`start`, `stop`, `status` and the `daemon-reload` after `setconf` fail; `list`, `getconf`, `df` and `logs` work, and running microVMs keep serving. It worked at 22:09. From `loginctl`, "No such device or address" means logind found the caller outside any `user-UID.slice`: the SSH login was never registered as a session, so it has no `XDG_RUNTIME_DIR` either.

Ideas: check `systemd-logind` and `/run` on the host. In the console, `loginctl enable-linger <user>` plus `XDG_RUNTIME_DIR=/run/user/<uid>` when it is unset would make it independent of the login session.
