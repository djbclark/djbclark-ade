## claude-settings-env: keep required and default `env` keys in ~/.claude/settings.json (2026-10-16).
##
## Port of the Python tool (HEAD:bin/claude-settings-env). bin/claude-settings-env runs this through
## bin/ade-console-run; the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## Same REQUIRED and DEFAULTS tables, same --check and --settings flags, same messages and exit codes.
## A REQUIRED key is corrected; a DEFAULTS key is added when absent and an operator's own value is left
## alone and reported. The file is replaced atomically on its realpath, keeping its mode and key order.
## Nothing runs this automatically, so no prompt is shown.

init -5 python:

    CSE_SUMMARY = "Keep required and default `env` keys in ~/.claude/settings.json (2026-10-16)."

    # graft: never write graft/ into the repo's tracked .gitignore
    # (trailhq/Graft#582; honoured by `graft build`, workspace-cli, `--no-gitignore`).
    CSE_REQUIRED = {
        "GRAFT_NO_GITIGNORE": "1",
    }

    # Agent-tool sub-agents and teammates with no `model` default to Sonnet instead of inheriting an
    # Opus or Fable lead's model (djbclark, 2026-10-23; docs/queue.md "Follow-ups from PRs 29 and 30"
    # item 2). A definition's `model:` or a model passed in the call still wins (Claude Code 2.1.251+);
    # Explore and Plan ignore it.
    CSE_DEFAULTS = {
        "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet",
    }

    def cse_missing(settings, required, defaults=None):
        env = settings.get("env") or {}
        pending = {k: v for k, v in required.items() if env.get(k) != v}
        pending.update({k: v for k, v in (defaults or {}).items() if k not in env})
        return pending

    def cse_apply(path, required, check, defaults=None):
        import json
        import os
        import tempfile
        from pathlib import Path
        real = path.resolve()
        settings = json.loads(real.read_text())
        env = settings.get("env") or {}
        for k, v in (defaults or {}).items():
            if k in env and env[k] != v:
                print("left alone in %s: %s=%s (default %s)" % (path, k, env[k], v))
        pending = cse_missing(settings, required, defaults)
        if not pending:
            print("ok: %s already set in %s" % (", ".join(list(required) + list(defaults or {})), path))
            return 0
        if check:
            print("missing in %s: %s" % (path, ", ".join("%s=%s" % (k, v) for k, v in pending.items())))
            return 1
        settings.setdefault("env", {}).update(pending)
        fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=real.name + ".")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
            os.chmod(tmp, real.stat().st_mode & 0o7777)
            os.replace(tmp, real)
        except BaseException:
            os.unlink(tmp)
            raise
        print("set in %s: %s" % (path, ", ".join("%s=%s" % (k, v) for k, v in pending.items())))
        return 0

    def cse_main(argv):
        import argparse
        from pathlib import Path
        ap = argparse.ArgumentParser(prog="claude-settings-env", description=CSE_SUMMARY)
        ap.add_argument("--check", action="store_true",
                        help="report only; exit 1 if a key is missing or a REQUIRED one differs")
        ap.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
        args = ap.parse_args(argv)
        return cse_apply(args.settings, CSE_REQUIRED, args.check, CSE_DEFAULTS)

    def cse_run(argv):
        """Run the tool on `argv`; returns {"code", "out", "err"}. argparse's usage errors arrive as
        SystemExit and keep their status 2."""
        import contextlib
        import io
        import sys
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                code = cse_main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            except (OSError, ValueError) as e:
                # An unreadable or unparsable settings file is an error with status 1, not a crash
                # of the engine.
                print("claude-settings-env: error: %s" % e, file=sys.stderr)
                code = 1
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def cse_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_claude_settings_env:
    $ cse_result = cse_run(ade_argv)
    $ cse_show(cse_result)
    $ ade_exit_code = cse_result["code"]
    return
