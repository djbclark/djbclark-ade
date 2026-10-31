## opencode-plugin-guard: keep the tool-managed OpenCode plugin (rtk) at the v2 module shape
## that OpenCode 2 requires.
##
## Port of the bash guard (HEAD:bin/opencode-plugin-guard). bin/opencode-plugin-guard runs this through
## bin/ade-console-run; the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## Same checks, restore rules, log lines and state files as the original. The GNU-tool calls
## (ggrep, gdate, ghead) are replaced by Python's re, datetime and the same logic, so the guard no
## longer depends on the g* tools. Exit 0 when nothing needed doing; 1 when something was restored
## or needs attention. Non-destructive: a live file that is already v2 and differs from the canonical
## copy is left alone, and unknown RTK copies are flagged for review.

init -5 python:

    OPG_UNSAFE_RTK_SHA256 = "8e46510ecdc95d4268838e435d33752d179675a6005b8de2483c7355b5d7da44"

    def opg_lines(path):
        """The file's lines, read leniently (grep semantics)."""
        from pathlib import Path
        return Path(path).read_text(errors="replace").splitlines()

    def opg_has_v2(path):
        """OpenCode 2 accepts a default export object with an id plus an effect or setup function."""
        import os
        import re
        if not os.path.isfile(path):
            return False
        lines = opg_lines(path)
        if not any(re.search(r"export default \{\s*id:", ln) for ln in lines):
            return False
        return any(re.search(r"(^|[^A-Za-z0-9_])(setup|effect)([^A-Za-z0-9_]|$)", ln) for ln in lines)

    def opg_sha(path, digits=12):
        import hashlib
        from pathlib import Path
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:digits]

    def opg_is_unsafe_rtk(path):
        import hashlib
        from pathlib import Path
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest() == OPG_UNSAFE_RTK_SHA256
        except OSError:
            return False

    def opg_now():
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def opg_upstream_or_drift(ctx, name, live, canonical):
        """v2 present but not our bytes: identical is fine, a stale canonical is flagged, else left alone."""
        import filecmp
        import re
        from pathlib import Path
        if filecmp.cmp(live, canonical, shallow=False):
            print("  %s: v2 present, identical to the canonical copy" % name)
            return
        print("  %s: v2 shape present but differs from the canonical copy" % name)
        # A newer still-v1 template rewritten by us would look like drift only in the version comment.
        pat = re.compile(r"opencode-integration-version: [0-9.]*")

        def version(path):
            for ln in opg_lines(path):
                m = pat.search(ln)
                if m:
                    return m.group(0)
            return None

        live_ver = version(live)
        canon_ver = version(canonical)
        if live_ver and canon_ver and live_ver != canon_ver:
            print("    WARNING: canonical drift — live says '%s', canonical '%s'." % (live_ver, canon_ver))
            print("    Refresh %s/%s and re-run." % (ctx["canon"], Path(canonical).name))
            ctx["rc"] = 1
            return
        print("    -> treating as upstream v2 (or a local edit); not touching it")
        with open(ctx["state"] / ("upstream-v2-%s" % name), "a") as fh:
            fh.write(opg_now() + "\n")

    def opg_handle(ctx, name, live_file, canonical):
        import os
        import shutil
        from pathlib import Path
        if not os.path.isfile(canonical):
            print("  %s: no canonical copy at %s — skipping" % (name, canonical))
            return
        if name == "rtk" and opg_is_unsafe_rtk(canonical):
            print("  rtk: canonical %s is the known unsafe shim; refresh it; no write" % canonical)
            ctx["rc"] = 1
            return
        if os.path.islink(live_file) and not os.path.exists(live_file):
            print("  %s: dangling or cyclic plugin symlink preserved; review its target; no write" % name)
            ctx["rc"] = 1
            return
        if os.path.exists(live_file) and not os.path.isfile(live_file):
            print("  %s: non-regular plugin entry preserved; review it; no write" % name)
            ctx["rc"] = 1
            return

        # Only our exact former managed copy is migrated automatically; anything else is preserved.
        unsafe_rtk = name == "rtk" and os.path.isfile(live_file) and opg_is_unsafe_rtk(live_file)
        if unsafe_rtk:
            print("  rtk: known unsafe automatic rewrite shim; migrate to disabled entrypoints")
        elif opg_has_v2(live_file):
            if name == "rtk" and not filecmp_same(live_file, canonical):
                print("  rtk: unknown v2 copy preserved; permission safety needs review")
                ctx["rc"] = 1
            else:
                opg_upstream_or_drift(ctx, name, live_file, canonical)
            return
        else:
            print("  %s: v2 shape MISSING in %s" % (name, live_file))

        if ctx["check"]:
            print("    would restore from %s" % canonical)
            ctx["rc"] = 1
            return
        target = Path(os.path.realpath(live_file))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path("%s.new.%d" % (target, os.getpid()))
        shutil.copyfile(canonical, tmp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)  # atomic replace; OpenCode's watcher reloads it
        print("    restored %s from canonical (sha %s)" % (target.name, opg_sha(target)))
        ctx["rc"] = 1

    def filecmp_same(a, b):
        import filecmp
        return filecmp.cmp(a, b, shallow=False)

    def opg_main(argv):
        import os
        from pathlib import Path
        home = os.path.expanduser("~")
        canon = Path(os.environ.get("OPENCODE_PLUGIN_GUARD_CANONICAL",
                                    os.path.join(home, "src", "djbclark-ade", "opencode-plugins")))
        config = Path(os.environ.get("OPENCODE_CONFIG_DIR", os.path.join(home, ".config", "opencode")))
        state = Path(home) / ".local" / "state" / "opencode-plugin-guard"
        check = bool(argv) and argv[0] == "--check"
        state.mkdir(parents=True, exist_ok=True)

        ctx = {"rc": 0, "check": check, "canon": canon, "state": state}
        print("opencode-plugin-guard %s — %s" % ("(check)" if check else "(enforce)", opg_now()))

        # An old obsolescence sentinel is not evidence of permission safety: the managed file is always
        # inspected, and `rtk hook opencode` is never run as a probe.
        opg_handle(ctx, "rtk", str(config / "plugins" / "rtk.ts"), str(canon / "rtk.ts"))
        return ctx["rc"]

    def opg_run(argv):
        """Run the guard on `argv`; returns {"code", "out", "err"} with the streams captured."""
        import contextlib
        import io
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            code = opg_main(list(argv))
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def opg_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_opencode_plugin_guard:
    $ opg_result = opg_run(ade_argv)
    $ opg_show(opg_result)
    $ ade_exit_code = opg_result["code"]
    return
