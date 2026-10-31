## Entry point: bin/ade-console-run sets ADE_CONSOLE_LABEL and ADE_CONSOLE_ARGV (NUL-separated, base64).

init -10 python:
    import base64, os

    def _ade_argv():
        raw = os.environ.get("ADE_CONSOLE_ARGV", "")
        if not raw:
            return []
        parts = base64.b64decode(raw).split(b"\0")
        return [p.decode("utf-8", "surrogateescape") for p in parts[:-1]]

    ade_argv = _ade_argv()
    ade_exit_code = 0

label start:
    $ _target = os.environ.get("ADE_CONSOLE_LABEL", "")
    if not _target or not renpy.has_label(_target):
        "No console flow named [_target!q]."
        $ renpy.quit(status=2)
    call expression _target
    $ renpy.quit(status=ade_exit_code)
