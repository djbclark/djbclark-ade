## routing-recalibrate: monthly AI re-rank of routing.toml good_at from calibrate suggestions. No model.
##
## Port of the Python tool (HEAD:bin/routing-recalibrate). bin/routing-recalibrate runs this through
## bin/ade-console-run; the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## Same flags, brief, dispatch command, environment variables and exit codes as the original. The
## launchd job (com.djbclark.routing-recalibrate) runs this unattended, so no operator prompt is shown:
## the run is decided by its inputs, and --dry-run is the only switch.

init -5 python:

    RR_SUMMARY = "Monthly AI re-rank of routing.toml good_at from calibrate suggestions. No model."

    class RrFail(Exception):
        """A step failed with a message for stderr and an exit status."""
        def __init__(self, message, code):
            Exception.__init__(self, message)
            self.code = code

    def rr_paths():
        import os
        from pathlib import Path
        # renpy.config.basedir is the console/ project; the ADE checkout is its parent.
        ade = Path(os.path.dirname(os.path.abspath(renpy.config.basedir)))
        default_state = Path.home() / ".local" / "state" / "bigteam" / "routing-recalibrate"
        default_ping = Path.home() / ".local" / "bin" / "hermes-ping"
        return {
            "ade": ade,
            "route": ade / "bin" / "route_agent.py",
            "state": Path(os.environ.get("ROUTING_RECALIBRATE_STATE", str(default_state))),
            "repo": Path(os.environ.get("ROUTING_RECALIBRATE_REPO", str(ade))),
            "acp": Path(os.environ.get("ACP_DISPATCH", str(ade / "bin" / "acp-dispatch"))),
            "ping": Path(os.environ.get("ROUTING_RECALIBRATE_PING", str(default_ping))),
        }

    def rr_calibrate(paths):
        import json
        import os
        import shutil
        import subprocess
        # sys.executable inside the engine is the Ren'Py binary, so the interpreter is named explicitly.
        py = shutil.which("python3") or "python3"
        proc = subprocess.run(
            [py, str(paths["route"]), "calibrate", "--json", "--since", "30"],
            check=False, capture_output=True, text=True, env=dict(os.environ), timeout=120,
        )
        if proc.returncode != 0:
            raise RrFail(proc.stderr or proc.stdout or "calibrate failed\n", proc.returncode or 1)
        return json.loads(proc.stdout)

    def rr_build_brief(report, date):
        import json
        suggestions = report.get("suggestions") or []
        lines = [
            "# Routing recalibrate %s" % date,
            "",
            "You are re-ranking `good_at` in `config/routing.toml` from the calibrate",
            "report below. Edit **only** the suggested service × kind ranks.",
            "",
            "## Rules",
            "",
            "1. Change `good_at` ranks for the suggested groups only, by the listed delta",
            "   (`+N` means worse / higher number; negative means better / lower number).",
            "2. One commit; message lists each change with its before/after numbers and",
            "   the done_rate vs peer median that justified it.",
            "3. Never change kinds eligibility, gates, reserve floors, frontier rows,",
            "   burn_first flags, pace thresholds, or `[calibrate]` / `[discovery]` /",
            "   `[dispatch]` / `[hermes]`.",
            "4. Never touch any group under the calibrate minimum (`min_n` in the JSON).",
            "5. Run `tests/test_route_agent.py` (and pace/calibrate siblings) via",
            "   `/Users/djbclark/ops/site-private/bin/bg uv run --with pytest python -m pytest -q …`.",
            "6. Push the branch (or master, if that is where you work) when green.",
            "",
            "## Suggestions",
            "",
        ]
        if not suggestions:
            lines.append("(none)")
        else:
            for s in suggestions:
                sign = "+" if s["suggest_rank_delta"] > 0 else ""
                lines.append(
                    "- `%s` × `%s`: rank %s%s (done %s%% vs peer median %s%%, n=%s) — %s"
                    % (s["service"], s["kind"], sign, s["suggest_rank_delta"], s["done_rate"],
                       s["peer_median_done_rate"], s["n"], s["reason"])
                )
        lines += [
            "",
            "## Calibrate JSON",
            "",
            "```json",
            json.dumps(report, indent=2, sort_keys=True),
            "```",
            "",
        ]
        return "\n".join(lines)

    def rr_dispatch_cmd(paths, date, brief):
        return [
            str(paths["acp"]), "claude",
            "--model", "opus",
            "--effort", "high",
            "--kind", "judgment",
            "--name", "recalibrate-%s" % date,
            "--task", "routing-recalibrate",
            "-C", str(paths["repo"]),
            "-f", str(brief),
            "--detach", "--no-wait",
        ]

    def rr_ping(paths, msg):
        import subprocess
        if paths["ping"].is_file():
            subprocess.run([str(paths["ping"]), msg], check=False)
        else:
            print(msg)

    def rr_main(argv):
        import argparse
        import json
        import subprocess
        import sys
        import time
        p = argparse.ArgumentParser(description=RR_SUMMARY)
        p.add_argument("--dry-run", action="store_true",
                       help="print brief and dispatch command; change nothing")
        args = p.parse_args(argv)

        paths = rr_paths()
        state = paths["state"]
        # The state dir is created before any write: launchd opens its log paths before first run.
        state.mkdir(parents=True, exist_ok=True)

        report = rr_calibrate(paths)
        suggestions = report.get("suggestions") or []
        date = time.strftime("%Y-%m-%d", time.localtime())

        if not suggestions:
            print("routing-recalibrate: no suggestions (min_n=%s)" % report.get("min_n"))
            return 0

        brief_text = rr_build_brief(report, date)
        out_dir = state / date
        brief_path = out_dir / "brief.md"
        cmd = rr_dispatch_cmd(paths, date, brief_path)

        if args.dry_run:
            print(brief_text)
            print("# dispatch:", " ".join(cmd))
            return 0

        out_dir.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(brief_text)
        (out_dir / "calibrate.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

        proc = subprocess.run(cmd, check=False)
        if proc.returncode != 0:
            print("routing-recalibrate: dispatch exited %d" % proc.returncode, file=sys.stderr)
            rr_ping(paths, "djbclark-ade: routing recalibrate dispatch failed (rc=%d)" % proc.returncode)
            return proc.returncode

        rr_ping(paths, "djbclark-ade: routing recalibrate dispatched (%d suggestions)" % len(suggestions))
        print("routing-recalibrate: brief %s" % brief_path)
        return 0

    def rr_run(argv):
        """Run the tool on `argv`; returns {"code", "out", "err"} with the streams captured."""
        import contextlib
        import io
        import json
        import sys
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                code = rr_main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            except RrFail as e:
                print(str(e), file=sys.stderr, end="" if str(e).endswith("\n") else "\n")
                code = e.code
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
                print("routing-recalibrate: error: %s" % e, file=sys.stderr)
                code = 1
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def rr_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_routing_recalibrate:
    $ rr_result = rr_run(ade_argv)
    $ rr_show(rr_result)
    $ ade_exit_code = rr_result["code"]
    return
