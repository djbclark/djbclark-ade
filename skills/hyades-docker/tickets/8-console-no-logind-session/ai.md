## Summary

From about 22:20 EDT on 2026-10-14, every SSH login to the Hyades console for user
`djbclark` arrives without a systemd-logind session. The console's start-up
`loginctl enable-linger` fails with "No such device or address" (ENXIO), the login has
no `XDG_RUNTIME_DIR`, and every console command that runs `systemctl --user` fails
with "Failed to connect to user scope bus via local transport: $DBUS_SESSION_BUS_ADDRESS
and $XDG_RUNTIME_DIR not defined". Commands that do not use the user bus still work.
The user's systemd manager is still running (its units keep running and log to the
user journal), so running microVMs are unaffected; only control is lost.

No SIPB/hyades commit landed in the window (the newest on `main` is `f9f5f503` from
2026-10-12), so the change is on the host, not in the console code. Whether other
users are affected is unknown: I can only test my own account.

## Environment (2026-10-14)

1. Hyades console from SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`
   (`hyades/console.py`).
2. User `djbclark`, SSH key login, `ssh -o BatchMode=yes djbclark@hyades.mit.edu <cmd>`.
   Each command is a fresh SSH connection (no `ControlMaster` multiplexing), so a
   stale client-side connection cannot explain it.
3. Eight microVMs configured; seven `djbclark-fc-*` units form a Firecrawl stack that
   keeps serving `https://djbclark-firecrawl.sipb.cloud` throughout.

## Timeline (EDT; each line is one SSH login; times are when the command finished)

1. 22:09:05 `setconf` x7 (a scripted `deploy apply`): no linger error, each
   `daemon-reload` succeeded.
2. 22:09:14 `stop` + `start djbclark-fc-searxng`: no linger error, both succeeded
   (user journal: `Stopped` 22:09:16, `Started` 22:09:22).
3. About 22:09:30 `status djbclark-fc-searxng`: succeeded (`Active: active (running)`).
4. 22:10:03 `logs djbclark-fc-searxng`: **`Could not enable linger: No such process`**
   (ESRCH, a different errno from what followed), journal output fine.
5. 22:20:37 `setconf` x7: `Could not enable linger: No such device or address` and six
   `Failed to connect to user scope bus` (the `daemon-reload`s).
6. 22:20:44 `stop`, `start`: the same two errors each.
7. 22:21-22:36 `status` three times: the same, every time.
8. 22:32 `list`, `getconf`, `df`: linger error printed, command output correct.
9. 22:37 `logs`: linger error printed, journal output correct (the user journal is
   read from files, not over the user bus).

So the first anomaly is between 22:09:30 and 22:10:03, and full failure is in place by
22:20:37.

## Exact output

```
$ ssh hyades status djbclark-fc-searxng; echo "rc=$?"
Could not enable linger: No such device or address
Failed to connect to user scope bus via local transport: $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined (consider using --machine=<user>@.host --user to connect to bus of other user)
rc=1
```

## What the errors mean (code reading, systemd `main` at `7f073ff56f14e9b6ff7052998b640df88a359358`)

1. The console runs `loginctl enable-linger` with no user at start-up
   (`hyades/console.py` line 84 at `f9f5f503`).
2. With no argument, `loginctl` sends `SetUserLinger` with `UID_INVALID`, meaning "the
   caller's own user" (`src/login/loginctl.c` lines 1239-1267; the error text "Could not
   enable linger: %s" is line 1267).
3. logind resolves `UID_INVALID` with `sd_bus_creds_get_owner_uid()`
   (`src/login/logind-dbus.c`, `method_set_user_linger` from line 1608, call at 1628).
4. That calls `cg_path_get_owner_uid()` (`src/libsystemd/sd-bus/bus-creds.c` line 572),
   which returns `-ENXIO` when the caller's cgroup is not under a `user-<uid>.slice`
   (`src/basic/cgroup-util.c` lines 1111-1128).
5. So ENXIO means the console process is not inside any user session's cgroup: the
   SSH login was not registered by `pam_systemd`/logind. The same missing session
   explains the absent `XDG_RUNTIME_DIR`, which `pam_systemd` sets.
6. `systemctl --user` requires `XDG_RUNTIME_DIR` or `DBUS_SESSION_BUS_ADDRESS`; since
   the fix for systemd/systemd#34849 (closed 2024-10-22) it fails with exactly
   the "not defined (consider using --machine=...)" message seen here.
7. The 22:10:03 ESRCH ("No such process") is unexplained. Hypothesis: logind was already
   losing track of sessions (a creds/PID lookup failing) before it stopped registering
   new ones entirely.

## Console commands affected (`hyades/console.py` at `f9f5f503`)

1. Fail: `start`, `stop`, `restart`, `kill`, `status` (lines 321-337) and every command
   that ends in `regenerate`'s `systemctl --user daemon-reload` (line 244): `setconf`,
   `create`, `edit`, `delete`, `wordpress` (line 411 too).
2. Work: `list`, `getconf`, `df`, `lsvol`, `logs` (line 341; `journalctl --user` reads
   journal files directly).
3. Side effect: `setconf` saves `hyades.json` and rewrites the Quadlet files before the
   `daemon-reload` fails, so the saved config and the loaded units now differ. A later
   successful `daemon-reload` (by the user, or anything else that triggers one) applies
   the saved config. The console reports the failure but the write is not rolled back.

## Hypotheses for the host (unverified; I cannot see the host)

1. `systemd-logind` crashed, restarted, or is wedged, so `pam_systemd`'s
   `CreateSession` fails and sshd continues without a session (`pam_systemd` failures
   are non-fatal in the usual PAM stack).
2. `/run` is full, so logind cannot create session state.
3. A change to sshd or the PAM stack skipped `pam_systemd` for these logins.
4. Something specific to this account's `user-<uid>.slice` or `user@<uid>.service`.
   Less likely: the user manager is alive and logging.

Ruled out:

1. Client-side SSH multiplexing (none configured; every call is a new connection).
2. A console code change (no commits since 2026-10-12).
3. The systemd 257 user-bus bug where `daemon-reload` breaks `systemctl --user` with
   "Connection refused" (Arch forum thread 302556, fixed in 258). That bug leaves
   `XDG_RUNTIME_DIR` set; here it is not set and logind has no session, which
   `daemon-reload` cannot cause. Note for completeness: the last good logins (22:09)
   ran seven user `daemon-reload`s.

Useful checks on the host: `systemctl status systemd-logind`,
`journalctl -u systemd-logind -u sshd --since "2026-10-14 22:05"`, `df -h /run`,
`loginctl list-sessions`, and `cat /proc/<console pid>/cgroup` for a fresh login.

## Possible console hardening (untested sketch)

Make the console independent of the login session. `os` and `getuser` are already
imported in `console.py`:

```python
# Allow running microVMs even when not logged in
run(["loginctl", "enable-linger", getuser()])
runtime_dir = f"/run/user/{os.getuid()}"
if "XDG_RUNTIME_DIR" not in os.environ and os.path.isdir(runtime_dir):
    # No logind session (e.g. pam_systemd failed); the lingering user manager's
    # bus is still at the usual place.
    os.environ["XDG_RUNTIME_DIR"] = runtime_dir
```

Caveats: with a named user, logind authorizes via polkit's
`org.freedesktop.login1.set-self-linger` rather than the session, which may need a
policy check on the host; and the fallback only helps while `user@<uid>.service` is
running (linger keeps it running). It hides the symptom; the session failure still
needs fixing on the host.

## Impact

Users cannot start, stop, restart or reconfigure microVMs from the console while this
lasts. Already-running microVMs keep serving. `setconf` half-applies (see above).
