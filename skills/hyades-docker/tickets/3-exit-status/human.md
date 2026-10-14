When the console runs a single command over SSH (`ssh hyades CMD`), it always exits 0, even when the command fails:

```
$ ssh hyades status nosuchvm; echo $?
Unit nosuchvm.service could not be found.
0
$ ssh hyades bogus; echo $?
*** Unknown syntax: bogus
0
```

Same for tracebacks (`getconf nosuchvm` → `KeyError`) and podman errors. That makes `ssh hyades ...` hard to script (CI deploy steps, `set -e`). Suggest: in the `SSH_ORIGINAL_COMMAND` branch, exit non-zero if `onecmd` hit an exception, an unknown command, or a subprocess returned non-zero.
