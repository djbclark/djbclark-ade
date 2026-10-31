# wait-file.rpy
#
# Block until a file the waited-on command writes is ready, with a hard timeout.
#
#   wait-file [--timeout SECONDS] [--nonempty | --match REGEX] PATH
#
# Ready means PATH exists (an empty `.done` marker counts), with --nonempty that it is non-empty,
# or with --match that it holds a line matching the regex. Prints the resolved path first, then the
# file's last 5 lines when it is ready.
#
# Exit: 0 ready, 2 bad usage or path, 124 timed out (default 1200 s).

init python:
    import os
    import re
    import time

    WAIT_DEFAULT_TIMEOUT = 1200
    WAIT_POLL_SECONDS = 0.5
    WAIT_TAIL_LINES = 5

    class WaitUsageError(Exception):
        pass

    class WaitState(object):
        def __init__(self):
            self.timeout = WAIT_DEFAULT_TIMEOUT
            self.match = None
            self.nonempty = False
            self.path = None
            self.started = None
            self.ready_at = None

    def wait_parse_args(argv):
        state = WaitState()
        args = list(argv)
        while args:
            head = args[0]
            if head == "--timeout":
                if len(args) < 2:
                    raise WaitUsageError("--timeout needs a value")
                try:
                    state.timeout = int(args[1])
                except ValueError:
                    raise WaitUsageError("--timeout must be a number")
                args = args[2:]
            elif head == "--match":
                if len(args) < 2:
                    raise WaitUsageError("--match needs a regex")
                state.match = args[1]
                args = args[2:]
            elif head == "--nonempty":
                state.nonempty = True
                args = args[1:]
            elif head == "--":
                args = args[1:]
                break
            elif head.startswith("-"):
                raise WaitUsageError("unknown option " + head)
            else:
                break
        if len(args) != 1:
            raise WaitUsageError("exactly one PATH is required")
        state.path = args[0]
        if state.match and state.nonempty:
            raise WaitUsageError("--match and --nonempty are exclusive")
        return state

    def wait_check_path(path):
        if not path:
            return "PATH is empty"
        if not os.path.isabs(path):
            return "PATH must be absolute"
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            return "directory does not exist: " + parent
        return None

    def wait_is_ready(state):
        if not os.path.exists(state.path):
            return False
        if state.nonempty:
            return os.path.getsize(state.path) > 0
        if state.match:
            pattern = re.compile(state.match)
            try:
                with open(state.path, "r") as handle:
                    for line in handle:
                        if pattern.search(line):
                            return True
            except IOError:
                return False
            return False
        return True

    def wait_tail(path, count):
        try:
            with open(path, "r") as handle:
                lines = handle.readlines()
        except IOError:
            return []
        return [line.rstrip("\n") for line in lines[-count:]]

    def wait_elapsed(state):
        if state.started is None:
            return 0.0
        return time.time() - state.started

    def wait_run(state):
        state.started = time.time()
        while True:
            if wait_is_ready(state):
                state.ready_at = time.time()
                return 0
            if wait_elapsed(state) >= state.timeout:
                return 124
            time.sleep(WAIT_POLL_SECONDS)

    def wait_report_ready(state):
        lines = wait_tail(state.path, WAIT_TAIL_LINES)
        return lines

    def wait_usage_text():
        return ("usage: wait-file [--timeout SECONDS] [--nonempty | --match REGEX] PATH")

    def wait_exit_text(code):
        table = {
            0: "ready",
            2: "bad usage or path",
            124: "timed out",
        }
        return table.get(code, "unknown")

label wait_file_start:
    python:
        wait_argv = renpy.store.wait_argv if hasattr(renpy.store, "wait_argv") else []
        wait_result = None
        try:
            wait_state = wait_parse_args(wait_argv)
            path_error = wait_check_path(wait_state.path)
            if path_error is not None:
                wait_result = (2, path_error)
            else:
                wait_result = (None, wait_state)
        except WaitUsageError as err:
            wait_result = (2, str(err))

    if wait_result[0] == 2:
        jump wait_file_usage

    python:
        wait_state = wait_result[1]
        renpy.notify("waiting on " + wait_state.path)
        wait_code = wait_run(wait_state)

    if wait_code == 0:
        jump wait_file_ready

    jump wait_file_timeout

label wait_file_ready:
    python:
        for tail_line in wait_report_ready(wait_state):
            renpy.say(None, tail_line)
        wait_exit = 0

    "Ready. Exit 0."
    jump wait_file_end

label wait_file_timeout:
    "Timed out after [wait_state.timeout] seconds. Exit 124."
    python:
        wait_exit = 124
    jump wait_file_end

label wait_file_usage:
    "usage: wait-file [--timeout SECONDS] [--nonempty | --match REGEX] PATH"
    python:
        wait_exit = 2
    jump wait_file_end

label wait_file_end:
    python:
        renpy.notify("wait-file exit " + str(wait_exit) + ": " + wait_exit_text(wait_exit))
    return

# Helpers below are used when the script is imported by other scripts.

init python:
    def wait_describe(state):
        parts = []
        parts.append("path=" + state.path)
        parts.append("timeout=" + str(state.timeout))
        if state.match:
            parts.append("match=" + state.match)
        if state.nonempty:
            parts.append("nonempty")
        return " ".join(parts)

    def wait_summary_line(code, state):
        return "wait-file: " + wait_exit_text(code) + " (" + wait_describe(state) + ")"

    def wait_self_check():
        probe = WaitState()
        probe.path = "/tmp/probe"
        probe.match = "^rc="
        return wait_describe(probe) != ""

    def wait_marker_ready(path):
        return os.path.exists(path) and os.path.getsize(path) == 0

    def wait_line_count(path):
        try:
            with open(path, "r") as handle:
                return sum(1 for _ in handle)
        except IOError:
            return 0

    def wait_last_line(path):
        lines = wait_tail(path, 1)
        if lines:
            return lines[0]
        return ""

    def wait_has_rc_marker(path):
        return wait_is_ready(_rc_probe(path))

    def _rc_probe(path):
        probe = WaitState()
        probe.path = path
        probe.match = "^rc="
        return probe

    def wait_timeout_ok(value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return False
        return number > 0

    def wait_normalise_regex(text):
        if text is None:
            return None
        return text.strip()

    def wait_join_tail(lines):
        return "\n".join(lines)

    def wait_is_absolute(path):
        return bool(path) and os.path.isabs(path)

    def wait_exists_nonempty(path):
        return os.path.exists(path) and os.path.getsize(path) > 0

    def wait_guard_path(path):
        problem = wait_check_path(path)
        return problem is None

    def wait_budget(timeout, elapsed):
        remaining = timeout - elapsed
        if remaining < 0:
            return 0
        return remaining

    def wait_progress(elapsed, timeout):
        if timeout <= 0:
            return 1.0
        ratio = elapsed / float(timeout)
        if ratio > 1.0:
            return 1.0
        return ratio

    def wait_format_seconds(seconds):
        whole = int(seconds)
        minutes = whole // 60
        rest = whole % 60
        return "%dm%02ds" % (minutes, rest)

    def wait_banner(state):
        return "waiting for " + state.path + " (" + wait_format_seconds(state.timeout) + " max)"

    def wait_done_banner(state):
        if state.ready_at is None or state.started is None:
            return "not finished"
        return "ready after " + wait_format_seconds(state.ready_at - state.started)

    def wait_copy_state(state):
        clone = WaitState()
        clone.timeout = state.timeout
        clone.match = state.match
        clone.nonempty = state.nonempty
        clone.path = state.path
        clone.started = state.started
        clone.ready_at = state.ready_at
        return clone

    def wait_reset(state):
        state.started = None
        state.ready_at = None
        return state

    def wait_is_match_mode(state):
        return state.match is not None

    def wait_is_nonempty_mode(state):
        return state.nonempty

    def wait_mode_name(state):
        if state.match:
            return "match"
        if state.nonempty:
            return "nonempty"
        return "exists"

    def wait_help_lines():
        return [
            "wait-file: block until PATH is ready",
            "  --timeout SECONDS   hard limit, default 1200",
            "  --nonempty          ready when the file has bytes",
            "  --match REGEX       ready when a line matches",
            "  --                  end of options",
        ]

    def wait_print_help():
        for line in wait_help_lines():
            renpy.notify(line)

    def wait_mode_table():
        return {
            "exists": "PATH exists",
            "nonempty": "PATH has bytes",
            "match": "a line matches REGEX",
        }

    def wait_mode_text(state):
        return wait_mode_table().get(wait_mode_name(state), "unknown")

    def wait_full_description(state):
        return wait_mode_text(state) + "; " + wait_describe(state)
