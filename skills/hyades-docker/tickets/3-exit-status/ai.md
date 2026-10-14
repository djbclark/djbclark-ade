## Summary

`ssh USER@hyades.mit.edu CMD ARGS` (the console's `SSH_ORIGINAL_COMMAND` mode)
returns exit status 0 for every command, including unknown commands, Python
exceptions, and failing `podman`/`systemctl`/`journalctl` subprocesses. Scripts
and CI steps cannot detect failure without scraping output.

## Environment

SIPB/hyades `f9f5f503560c9b952c989358d24fa30e719a59d8`; tested 2026-10-14 as
`djbclark` with an SSH key, OpenSSH client on macOS, `BatchMode=yes`.

## Reproduction (all exit 0)

| Command | Output |
|---|---|
| `ssh hyades status nosuchvm` | `Unit nosuchvm.service could not be found.` (systemctl exits 4) |
| `ssh hyades bogus` | `*** Unknown syntax: bogus` |
| `ssh hyades getconf nosuchvm` | traceback ending `KeyError: 'nosuchvm'` |
| `ssh hyades exec djbclark-rustpad ls /` | `Error: krun: chown /dev/pts/0: ...` (podman exits non-zero; code not captured) |
| `ssh hyades tmprun docker.io/library/alpine uname` | `Couldn't execute '--': ENOENT ...` |

## Code

```python
def run(...)  # subprocess.run, return codes ignored everywhere (ruff PLW1510 disabled at top)

class HyadesConsole(Cmd):
    def onecmd(self, line):
        try:
            ...
            return super().onecmd(line)
        except KeyboardInterrupt:
            pass
        except Exception:
            print(format_exc())
            return False

hyades = HyadesConsole()
if "SSH_ORIGINAL_COMMAND" in os.environ:
    hyades.onecmd(os.environ["SSH_ORIGINAL_COMMAND"])   # result discarded; script ends -> exit 0
else:
    ...
```

`Cmd.default()` prints `*** Unknown syntax` and returns None, so unknown commands
are indistinguishable from success too.

## Suggested patch (minimal, keeps interactive behaviour)

```python
import subprocess, sys

failed = False

def run(cmd, *a, **kw):
    global failed
    r = subprocess.run(cmd, *a, **kw)
    if r.returncode != 0:
        failed = True
    return r

class HyadesConsole(Cmd):
    def default(self, line):
        global failed
        failed = True
        return super().default(line)

    def onecmd(self, line):
        global failed
        try:
            ...
        except Exception:
            failed = True
            print(format_exc())
            return False

if "SSH_ORIGINAL_COMMAND" in os.environ:
    hyades.onecmd(os.environ["SSH_ORIGINAL_COMMAND"])
    sys.exit(1 if failed else 0)
```

(`from subprocess import run` at the top would become `import subprocess` plus
this wrapper; `check=True` is not an option because some failures, such as
`systemctl status` of a stopped unit returning 3, are informational.) Passing
the subprocess's own code through (`sys.exit(r.returncode)`) would be even more
useful for `status` (systemd's 0/3/4 semantics), if preferred.

`entergp GROUP CMD` runs the group's console via `systemd-run --pipe` (which
implies `--wait` and should return the inner exit status; not tested), so it
would likely inherit the fix.

## Impact

Any automation (a deploy step that runs `ssh hyades restart app`, a health check
with `status`) silently succeeds on failure. The reporter's client-side wrapper
currently greps the output for `Traceback`, `Error:`, `*** Unknown syntax`,
`Unit ... could not be found`, `Couldn't execute`, which is fragile.

## Duplicate search (2026-10-14, after filing)

Searched for existing reports of this and the sibling console bugs:
1. SIPB/hyades and SIPB/hyades-action issues, all states: only SIPB/hyades #1 (closed, unrelated Ctrl+D request) and our own #2-#8.
2. containers/crun GitHub issues for "krun chown", "open_terminal chown", "exec tty krun permission denied": no hits.
3. github.com/sipb/crun has issues disabled. Upstream containers/crun's `handlers/krun.c` has no exec path at all (sipb/crun main is 5 commits ahead of containers/crun main), so the exec/pty bug is SIPB-specific and SIPB/hyades is the right tracker.
