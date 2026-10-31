## opencode-self-compact: ask the native Go plugin's single admission guard to compact this session.
##
## Port of the Python tool (HEAD:bin/opencode-self-compact). bin/opencode-self-compact runs this through
## bin/ade-console-run; the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## Same usage, scope checks, messages and exit codes as the original (2 invalid scope or options,
## 7 guard refusal, 11 RPC failure). There is no direct compact POST, no cooldown store, no parent
## target and no retry, as before. The tool is driven by the OpenCode plugin, so it shows no prompt.

init -5 python:

    OSC_ID_RE = r"ses_[A-Za-z0-9]+"

    def osc_main(argv):
        import json
        import os
        import re
        import subprocess
        import sys
        from pathlib import Path
        from urllib.parse import urlencode

        sid = os.environ.get("ADE_OPENCODE_SESSION_ID", "")
        directory = os.environ.get("ADE_OPENCODE_DIRECTORY", "")
        if (argv not in ([], ["--dry-run"]) or not re.fullmatch(OSC_ID_RE, sid)
                or not directory or not Path(directory).is_absolute()):
            print("self-slash: native compact needs tool-scoped session and directory", file=sys.stderr)
            return 2
        if argv == ["--dry-run"]:
            print("self-slash: would ask native Go guard to compact %s; no API call made" % sid)
            return 0

        route = "/api/rpc/ade.go-context/compact?" + urlencode({"location[directory]": directory})
        try:
            result = subprocess.run(
                ["opencode", "api", "post", route, "--data", json.dumps({"input": {"sessionID": sid}})],
                capture_output=True, text=True, timeout=45, check=False)
            if result.returncode:
                print("self-slash: native Go guard unavailable or request uncertain; do not retry blindly",
                      file=sys.stderr)
                return 11
            value = json.loads(result.stdout)
            # Native RPC returns {output: ...}; the guard's boolean is not HTTP acceptance.
            data = value.get("output") if isinstance(value, dict) else None
            if not isinstance(data, dict) or data.get("accepted") is not True:
                print("self-slash: native guard refused compaction; inspect pending state, cooldown or baseline",
                      file=sys.stderr)
                return 7
            print("self-slash: native compaction accepted for %s; completion is not yet verified" % sid)
            return 0
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print("self-slash: native Go guard call failed or is uncertain (%s); no automatic retry"
                  % type(error).__name__, file=sys.stderr)
            return 11

    def osc_run(argv):
        """Run the tool on `argv`; returns {"code", "out", "err"} with the streams captured."""
        import contextlib
        import io
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            code = osc_main(list(argv))
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def osc_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_opencode_self_compact:
    $ osc_result = osc_run(ade_argv)
    $ osc_show(osc_result)
    $ ade_exit_code = osc_result["code"]
    return
