## paseo-set-model: switch a live Paseo agent's model in place, or list the daemon's agents.
## Port of the original bin/paseo-set-model (Python). Entry label: tool_paseo_set_model; arguments in ade_argv.
##
##   paseo-set-model set <agent> <model> [--dry-run]
##   paseo-set-model list --json
##   paseo-set-model autoaccept <agent> [--dry-run]
##
## The work runs in Paseo's bundled Electron node through bin/paseo-set-model.mjs (argv list, no shell),
## with the helper's own lines and exit status as the answer. Exit codes: 0 ok, 1 other error,
## 2 usage, 3 no such agent, 4 model not applied. Output is written to the process stdout/stderr;
## narrator is reserved for operator choices.

init python:
    import os
    import subprocess
    import sys
    from pathlib import Path

    PSM_APP = "/Applications/Paseo.app/Contents"
    PSM_DEFAULT_HELPER = f"{PSM_APP}/Frameworks/Paseo Helper.app/Contents/MacOS/Paseo Helper"
    PSM_DEFAULT_CLI_DIST = f"{PSM_APP}/Resources/app.asar/node_modules/@getpaseo/cli/dist"
    # renpy.config.basedir is console/; the helper .mjs sits in bin/ beside the original tool.
    PSM_MJS = Path(renpy.config.basedir).resolve().parent / "bin" / "paseo-set-model.mjs"

    PSM_USAGE = (
        "usage: paseo-set-model set <agent> <model> [--dry-run]\n"
        "       paseo-set-model list --json\n"
        "       paseo-set-model autoaccept <agent> [--dry-run]\n"
        "\n"
        "exit codes: 0 ok, 1 error, 2 usage, 3 no such agent, 4 model not applied\n"
    )

    PSM_DOC = (
        "paseo-set-model: switch a live Paseo agent's model in place, or list the daemon's agents.\n"
        "Agents are matched by full id or unique prefix. A provider other than the agent's is refused.\n"
        "`autoaccept` turns the agent's auto_accept feature on and re-fetches it to verify (exit 4 if off).\n"
    )

    def psm_parse(argv):
        """Return (args_for_helper, None) or (None, exit_code) for a usage error."""
        cmd, rest = argv[0], argv[1:]
        if cmd in ("set", "autoaccept"):
            flags = [a for a in rest if a.startswith("--")]
            pos = [a for a in rest if not a.startswith("--")]
            want_pos = 2 if cmd == "set" else 1
            if len(pos) != want_pos or any(f != "--dry-run" for f in flags):
                return None, 2
            return [cmd, *pos, *flags], None
        if cmd == "list":
            if rest != ["--json"]:
                return None, 2
            return ["list"], None
        return None, 2

    def psm_run(argv):
        """Return (exit_code, message_for_stderr_or_None). Help goes to stderr like the usage does."""
        if not argv:
            return 2, PSM_USAGE
        if argv[0] in ("-h", "--help"):
            return 0, PSM_DOC
        args, code = psm_parse(argv)
        if args is None:
            return code, PSM_USAGE
        helper = os.environ.get("PASEO_SET_MODEL_HELPER") or PSM_DEFAULT_HELPER
        env = dict(os.environ)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        env["PASEO_NODE_ENV"] = "production"
        env["PASEO_SET_MODEL_CLI_DIST"] = os.environ.get("PASEO_SET_MODEL_CLI_DIST") or PSM_DEFAULT_CLI_DIST
        try:
            # Argv list, inherited stdio: the helper's own lines and exit status are the answer.
            p = subprocess.run([helper, "--disable-warning=DEP0040", str(PSM_MJS), *args], env=env, check=False)
            return p.returncode, None
        except OSError as e:
            return 1, f"paseo-set-model: cannot run {helper}: {e}"

label tool_paseo_set_model:
    python:
        _psm_code, _psm_msg = psm_run(ade_argv)
        if _psm_msg:
            # -h prints the summary on stdout; usage and errors go to stderr.
            print(_psm_msg, file=sys.__stdout__ if _psm_code == 0 else sys.__stderr__)
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        ade_exit_code = _psm_code
    return
