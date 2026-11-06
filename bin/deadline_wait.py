"""deadline_wait: how a long WAITER registers its own deadline (docs/deadline.md, "Waiters register themselves").

Used by `bin/load-watch admit --wait` (the PR waiter that also used it was removed 2026-11-06, slim-down E8);
`bin/acp-dispatch-wait` does the same in bash. A waiter holds no work (it only
polls), so the action on expiry is `kill` of its own process group: nothing is lost, and the caller just sees exit 124.

Shape. `deadline start --pid` refuses the registrar's own parent (a top-level session must never register itself for a kill), so a process cannot
register itself. The waiter therefore runs as a SUPERVISOR: it starts `deadline run --name NAME --budget B --heartbeat H --on-expire kill -- SELF ARGV`
(one fresh process group, the record written before the wait starts, `done` on every exit path, signals included, exit 124 when the enforcer
stopped it) and returns that exit code. The re-run copy of the waiter sees `DEADLINE_NAME` (exported by `deadline run`) and so does not register
again: that is also the rule for a waiter started under a caller's own `deadline run` (no double registration). The inner copy touches
$DEADLINE_WAIT_MARK on its way in: if the supervised run never reached it (the deadline tool is missing, crashed, or refused the name) the
supervisor warns once on stderr and waits in-process, unregistered. A deadline problem never costs the wait.

Lifecycle. `done` on every CATCHABLE exit (normal end, failure, SIGTERM/INT/HUP to the supervisor). A SIGKILLed supervisor cannot stop its child: the
supervised copy checks the supervisor's pid on every poll/beat (ENV_SUP) and ends itself (exit 143), so an uncatchable kill leaves no orphaned wait
The supervised copy removes ENV_NAME/ENV_MARK/ENV_SUP from its environment on entry: its descendants
can neither beat this record nor mistake themselves for the supervised copy. Names carry the supervisor's pid, so two waiters for one PR/record
(another repo, a new head, a re-arm) never refuse each other's registration.

Budget. The class budget of docs/paseo-only-rearchitecture.md B9 (admission wait at most 30 min) or the waiter's own timeout,
whichever is shorter, plus MARGIN_S: the waiter's own timeout path (it writes its result files) must finish before the enforcer can fire.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARGIN_S = 60.0
ENV_NAME = "DEADLINE_WAIT_NAME"     # the name this waiter chose for its own registration
ENV_MARK = "DEADLINE_WAIT_MARK"     # file (inside a private directory) the supervised copy creates once it is running
ENV_SUP = "DEADLINE_WAIT_SUPERVISOR"  # pid of the supervisor: the supervised copy ends when it is gone (a SIGKILLed supervisor leaves no orphan)
BEAT_EVERY_S = float(os.environ.get("DEADLINE_WAIT_BEAT_EVERY") or 10.0)   # a Python start per beat: at most one per 10 s (the env is a test seam)
BEAT_GIVE_UP = 3                    # consecutive failed beats before one warning and no more tries

_warned: set[str] = set()
_beat = {"last": 0.0, "fails": 0, "off": False}
_inner: dict = {}   # set in the supervised copy only: {"name", "sup"}. Module state, NOT environment: its descendants must not inherit it


def warn(tool: str, msg: str) -> None:
    """One stderr line per distinct message and process."""
    if msg not in _warned:
        _warned.add(msg)
        print(f"{tool}: warning: {msg}", file=sys.stderr, flush=True)


def deadline_bin() -> str | None:
    path = os.environ.get("DEADLINE_BIN") or str(HERE / "deadline")
    return path if os.access(path, os.X_OK) else None


def safe_name(prefix: str, ident: object) -> str:
    """`prefix-ident` as a deadline name ([A-Za-z0-9_][A-Za-z0-9._-]{0,99})."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", f"{prefix}-{ident}")[:100]


def budget_for(own_timeout_s: float, class_budget_s: float) -> float:
    return min(own_timeout_s, class_budget_s) + MARGIN_S


def supervised(tool: str, name: str, budget_s: float, heartbeat_s: float, script: str, argv: list[str],
               opt_out: bool = False) -> int | None:
    """None: wait in this process (opted out, nested under another `deadline run`, this IS the supervised copy, or the deadline tool did not
    run it). An int: the supervised run's exit code, which the caller returns (124 = the enforcer stopped it)."""
    if opt_out:
        return None
    if "DEADLINE_NAME" in os.environ:   # set (even empty): under `deadline run`, or already supervised, or a failed registration
        mark = os.environ.pop(ENV_MARK, None)
        mine = os.environ.pop(ENV_NAME, None)
        sup = os.environ.pop(ENV_SUP, None)
        if mark and mine and os.environ["DEADLINE_NAME"] == mine:
            # this is the supervised copy. The three variables were just removed from the environment: a descendant started by this waiter
            # inherits only DEADLINE_NAME (which makes ITS waiters skip registration) and can never beat this record or touch this mark
            _inner.update(name=mine, sup=int(sup) if sup and sup.isdigit() else 0)
            try:
                Path(mark).touch()
            except OSError:
                pass
        return None
    path = deadline_bin()
    if path is None:
        warn(tool, "no usable deadline tool (bin/deadline or $DEADLINE_BIN): waiting without a deadline")
        return None
    try:
        mark_dir = tempfile.mkdtemp(prefix="deadline-wait-")   # 0700: nobody else can pre-create or symlink the mark
    except OSError as e:
        warn(tool, f"cannot make a private directory ({e}): waiting without a deadline")
        return None
    mark = os.path.join(mark_dir, "started")   # absent until the supervised copy creates it
    exe = [script] if os.access(script, os.X_OK) else [sys.executable, script]
    cmd = [path, "run", "--name", name, "--budget", str(max(1, math.ceil(budget_s))), "--heartbeat", str(max(1, math.ceil(heartbeat_s))),
           "--on-expire", "kill", "--", *exe, *argv]
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        # its own session: a terminal or group signal reaches only this supervisor, which forwards it ONCE (no double signal)
        child = subprocess.Popen(cmd, env={**os.environ, ENV_NAME: name, ENV_MARK: mark, ENV_SUP: str(os.getpid())},
                                 start_new_session=True)
    except OSError as e:
        shutil.rmtree(mark_dir, ignore_errors=True)
        warn(tool, f"cannot start {path} ({e}): waiting without a deadline")
        return None

    got: list[int] = []

    def forward(sg, _frame):
        got.append(sg)
        try:
            child.send_signal(sg)
        except OSError:
            pass

    old = {s: signal.signal(s, forward) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        rc = child.wait()
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    started = os.path.exists(mark)
    shutil.rmtree(mark_dir, ignore_errors=True)
    if got and not started:   # cancelled before the wait began: the caller asked it to stop, so it must not wait in this process
        return 128 + got[0]
    if not started:   # `deadline run` ended without ever starting the wait: nothing waited, so wait here
        warn(tool, f"the deadline tool did not run the wait (exit {rc}): waiting without a deadline")
        return None
    return 128 - rc if rc < 0 else rc


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def beat() -> None:
    """Heartbeat of this waiter's own record, from its poll loop. Only when this process is the supervised copy of a registration it made
    (`_inner`): a waiter nested under someone else's `deadline run`, or a descendant of the supervised copy, does not beat that record. Also the
    liveness check of the supervisor (every call, unthrottled). Throttled, bounded,
    and a failing tool is one warning, never a stop."""
    name = _inner.get("name")
    if not name:
        return
    sup = _inner.get("sup")
    if sup and not pid_alive(sup):   # the supervisor was killed without a chance to stop us: end the wait, do not run on orphaned
        print(f"{os.path.basename(sys.argv[0])}: supervisor pid {sup} is gone; stopping the wait", file=sys.stderr, flush=True)
        raise SystemExit(143)
    if _beat["off"]:
        return
    t = time.monotonic()
    if t - _beat["last"] < BEAT_EVERY_S:
        return
    _beat["last"] = t
    path = deadline_bin()
    ok = False
    if path:
        try:
            ok = subprocess.run([path, "beat", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=10, check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _beat["fails"] = 0 if ok else _beat["fails"] + 1
    if _beat["fails"] >= BEAT_GIVE_UP:   # the first beat can land before `deadline run` has saved the record: a few misses are normal
        _beat["off"] = True
        warn(os.path.basename(sys.argv[0]) or "deadline_wait", f"heartbeat to deadline {name} keeps failing: waiting on without it")
