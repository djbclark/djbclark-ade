Two small argument bugs in the console:

1. `tmprun IMAGE CMD` always fails: `do_tmprun` appends `--` after the image, so podman runs `--` as the command.
   ```
   $ ssh hyades tmprun docker.io/library/alpine uname
   Couldn't execute '--': ENOENT: No such file or directory
   ```
   (`tmprun IMAGE` without CMD works.)
2. `exec NAME CMD` passes CMD as one argv element (`["podman", "exec", "-it", name, "--", cmd]`), so `exec NAME ls -la /` would look for a program literally named `ls -la /`.

Suggested fix: `shlex.split()` the command, and for `tmprun` drop the `--` (or put it before the image).
