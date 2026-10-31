## heavy-shim: PATH shim for `swift` and `xcodebuild`, linked as ~/.local/bin/swift and
## ~/.local/bin/xcodebuild ahead of /usr/bin on PATH.
##
## Port of the bash shim (HEAD:bin/heavy-shim). bin/heavy-shim runs this through bin/ade-console-run.
## The shim's behaviour depends on the name it was invoked by, which the engine cannot see, so the
## invoked name is passed first and the real arguments follow; `ade_argv[0]` is the name and
## `ade_argv[1:]` are the tool's own arguments.
##
## Classification is the original's: `swift build|test|run` and any `xcodebuild` other than the
## informational flags run through the machine-wide slot (~/ops/site-private/bin/bg) with BG_SHIM=1
## set so the re-exec does not loop; everything else goes straight to /usr/bin. Output is not
## captured: the child's stdout and stderr pass through unchanged, because a build log written to
## narrator lines would wait for one click per line.

init -5 python:

    HS_SWIFT_HEAVY = ("build", "test", "run")
    HS_SWIFT_INFO = ("--version", "-version", "--help", "-h", "-help")
    HS_XCODE_LIGHT = ("-version", "-help", "-usage", "-showsdks", "-list",
                      "-showBuildSettings", "-showdestinations")

    def hs_is_heavy(name, args):
        """True when this invocation should take a test slot. Mirrors the original case statements."""
        if name == "swift":
            for a in args:
                if a in HS_SWIFT_INFO:
                    return False
                if a.startswith("-"):
                    continue
                return a in HS_SWIFT_HEAVY
            return False
        if name == "xcodebuild":
            return not any(a in HS_XCODE_LIGHT for a in args)
        return False

    def hs_run(argv):
        """Run the wrapped tool; returns its exit status, or 127 when the real binary is absent."""
        import os
        import subprocess
        import sys
        if not argv or not argv[0]:
            print("heavy-shim: no tool name was passed", file=sys.stderr)
            return 2
        name = argv[0]
        args = list(argv[1:])
        real = "/usr/bin/%s" % name
        bg = os.path.join(os.path.expanduser("~"), "ops", "site-private", "bin", "bg")
        sys.stdout.flush()
        sys.stderr.flush()
        if not os.environ.get("BG_SHIM") and os.access(bg, os.X_OK) and hs_is_heavy(name, args):
            env = dict(os.environ, BG_SHIM="1")
            cmd = [bg, real] + args
        else:
            env = os.environ
            cmd = [real] + args
        try:
            return subprocess.call(cmd, env=env)
        except FileNotFoundError:
            print("heavy-shim: %s: No such file or directory" % cmd[0], file=sys.stderr)
            return 127


label tool_heavy_shim:
    $ hs_rc = hs_run(ade_argv)
    $ ade_exit_code = hs_rc
    return
