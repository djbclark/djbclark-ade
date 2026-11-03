"""drain_common: shared output and subprocess helpers for the D0.2 drain scripts (plan T3).

Every drain script ends in `emit` (a record, exit 1 when it holds anything, else 0) or `cannot` (exit 77: a check that
cannot run counts as "not drained"). Records are one bounded JSON line: {"tool","held","evidence"}. Nothing here writes
anything but stdout; `run` takes an argv list, never a shell string.
"""
import json
import subprocess

MAX_ITEMS = 25     # evidence lines kept in the record; the rest are counted in evidence_truncated
MAX_LEN = 220      # characters per evidence line


def _clip(s):
    s = " ".join(str(s).split())
    return s if len(s) <= MAX_LEN else s[: MAX_LEN - 1] + "…"


def emit(tool, held, evidence, notes=()):
    """Print the record; return the process exit code (1 holds something, 0 empty)."""
    rec = {"tool": tool, "held": held, "evidence": [_clip(e) for e in evidence[:MAX_ITEMS]]}
    if len(evidence) > MAX_ITEMS:
        rec["evidence_truncated"] = len(evidence) - MAX_ITEMS
    if notes:
        rec["notes"] = [_clip(n) for n in notes[:10]]
    print(json.dumps(rec, ensure_ascii=False))
    return 1 if held else 0


def cannot(tool, reason):
    """The check could not run: held is null, exit 77."""
    print(json.dumps({"tool": tool, "held": None, "cannot_run": _clip(reason), "evidence": []}, ensure_ascii=False))
    return 77


def run(argv, timeout=30, env=None):
    """(rc, stdout, stderr) of an argv list; rc is None when it could not start or timed out (stderr says why)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, "", f"timeout after {timeout}s: {argv[0]}"
    except OSError as e:
        return None, "", f"{type(e).__name__}: {e}"
    return r.returncode, r.stdout, r.stderr
