#!/usr/bin/env python3
"""PreToolUse (Bash): deny a pytest / tox / nox / run_tests*.py / swift build|test|run /
xcodebuild command that is not run through an accepted full-path `bgrun` (or `bg`).

Accepted Stage 0 dual-read wrapper paths (`bin/ade_ops_paths.is_bgrun_path`):
  - `~/.local/bin/bgrun` (and `~/.local/bin/bg`)
  - `<TENDCF_OPS_ROOT>/tendcf-{public,private}-<slug>/bin/bgrun` (default `~/tendcf-ops`, strict slug)
  - legacy `~/ops/site-*/bin/bgrun` (and `~/ops/site-*/bin/bg`)

2026-10-13: a bare `swift test --filter X` ran one swift-frontend per core (8 on 8 cores, up to
3.5 GB each) and took the load to 180 with swap full; bg now slots and caps swift/xcodebuild.

Why (2026-10-08): one session ran a project's full pytest suite directly, with a runner
sized by os.cpu_count() (8 workers, each spawning children). The load average went from
17 to 220 and every other session starved. bgrun caps parallelism (PYTHON_CPU_COUNT and
friends), runs at utility QoS and takes one of two machine-wide test slots.

Allowed without bg: --version/--help/--collect-only, anything already wrapped by an accepted
full-path bgrun/bg, and text that merely mentions pytest inside quotes or a heredoc. Fails open
on any parse error. Escape hatch for the operator: BG_GATE_OFF=1 in the environment.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

BG = "~/.local/bin/bgrun"
LEGACY_BG = "~/ops/site-private/bin/bgrun"

TEST_WORD = (
    r"(?:pytest|py\.test|tox|nox|run_tests\w*\.py|xcodebuild|swift-(?:test|build)"
    r"|swift\s+(?:-\S+\s+)*(?:test|build|run))"
)
# A test command: the word is the command itself, or follows python -m / uv run / env VAR=x /
# a path, at the start of a pipeline segment.
SEGMENT = re.compile(
    r"^\s*"
    r"(?:(?:\w+=\S*\s+)*)"  # VAR=value prefixes
    r"(?:(?:env|time|nice|command|exec)\s+(?:\w+=\S*\s+)*)?"
    r"(?:(?:uv|uvx)\s+(?:run\s+)?(?:--?\S+\s+)*)?"
    r"(?:\S*python[\d.]*\s+(?:-\S+\s+)*(?:-m\s+)?)?"
    r"(?:\S*/)?" + TEST_WORD + r"(?=\s|$)"
)
SAFE = re.compile(r"(?:^|\s)(?:--version|-V|--help|-h|--collect-only|--co)(?:\s|$)")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_KW = frozenset({"if", "elif", "while", "until", "then", "do", "else", "!", "{"})
PRE_WRAPPERS = frozenset({"env", "time", "nice", "nohup", "command", "exec", "timeout", "gtimeout", "caffeinate", "rtk"})
WRAPPER_VALUE_FLAGS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-P"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "time": frozenset({"-o", "-f"}),
    "exec": frozenset({"-a"}),
    "timeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "gtimeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "caffeinate": frozenset({"-w", "-t"}),
}
RTK_RUNNERS = frozenset({"test", "err", "run", "proxy", "bypass", "summary"})
BG_LOOKALIKE_RE = re.compile(r"^(?:bg|bgb|bgrun\w*)\Z")


def _load_ops_paths():
    for cand in (Path(__file__).resolve().parents[2] / "bin", Path.home() / "src" / "djbclark-ade" / "bin"):
        if (cand / "ade_ops_paths.py").is_file():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            import ade_ops_paths  # noqa: PLC0415
            return ade_ops_paths
    return None


_OPS_PATHS = _load_ops_paths()


def _is_valid_bgrun(token: str) -> bool:
    if _OPS_PATHS is not None:
        return _OPS_PATHS.is_bgrun_path(token, allow_bg=True)
    # Minimal standalone fallback anchored strictly to $HOME if bin/ade_ops_paths.py is unavailable.
    if not token or ".." in token.split("/") or "//" in token:
        return False
    home_esc = re.escape(str(Path.home()).rstrip("/"))
    return bool(
        re.match(rf"^(?:~|\$HOME|\$\{{HOME\}}|{home_esc})/\.local/bin/bg(?:run)?\Z", token)
        or re.match(rf"^(?:~|\$HOME|\$\{{HOME\}}|{home_esc})/ops/site-[A-Za-z0-9][A-Za-z0-9._-]*/bin/bg(?:run)?\Z", token)
    ) and not any(part.endswith("-wt") for part in token.split("/"))


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies so words inside heredoc data do not count."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", lines[i])
        if m:
            i += 1
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
        i += 1
    return "\n".join(out)


def _split_segments(text: str) -> list[list[str]]:
    """Split shell text into token lists per command segment, respecting quotes and comments."""
    segments: list[list[str]] = []
    args: list[str] = []
    word: list[str] = []
    quote = ""
    started = False
    i = 0
    n = len(text)

    def finish_word() -> None:
        nonlocal started
        if started:
            args.append("".join(word))
            word.clear()
            started = False

    def finish_segment() -> None:
        finish_word()
        if args:
            segments.append(list(args))
            args.clear()

    while i < n:
        c = text[i]
        if c == "\\" and quote != "'":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            started = True
            if i + 1 < n:
                word.append(text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if quote:
            if c == quote:
                quote = ""
            else:
                word.append(c)
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            started = True
            i += 1
            continue
        if c == "#" and not started:
            while i < n and text[i] != "\n":
                i += 1
            finish_segment()
            i += 1
            continue
        if c in ";|&()\n":
            finish_segment()
            i += 1
            continue
        if c.isspace():
            finish_word()
            i += 1
            continue
        word.append(c)
        started = True
        i += 1

    finish_segment()
    return segments


def _strip_wrappers(tokens: list[str]) -> tuple[bool, list[str]]:
    """Strip shell keywords, assignments, and transparent wrappers.

    Returns `(wrapped_by_valid_bgrun, remaining_tokens)`.
    """
    args = list(tokens)
    while args:
        head = args[0]
        if head in SHELL_KW or ASSIGN_RE.match(head):
            args.pop(0)
            continue
        if _is_valid_bgrun(head):
            return True, []
        base = os.path.basename(head)
        if base in PRE_WRAPPERS:
            args.pop(0)
            if base == "command" and args and args[0] in ("-v", "-V"):
                return True, []
            if base == "rtk":
                while args and args[0].startswith("-"):
                    args.pop(0)
                if args and args[0] in RTK_RUNNERS:
                    args.pop(0)
                    while args and args[0].startswith("-"):
                        opt = args.pop(0)
                        if opt in ("-c", "--command", "--shell") and args:
                            args.pop(0)
            val_flags = WRAPPER_VALUE_FLAGS.get(base, frozenset())
            while args and args[0].startswith("-"):
                opt = args.pop(0)
                if opt in val_flags and args:
                    args.pop(0)
            if base in ("timeout", "gtimeout") and args:
                args.pop(0)
            continue
        # An invalid/lookalike bg/bgrun wrapper (e.g. bare `bg`, `/tmp/bgrun`, `bgrunner`,
        # `tendcf-public-foo-wt/bin/bgrun`): strip it so any wrapped test command is still caught.
        if BG_LOOKALIKE_RE.match(base):
            args.pop(0)
            continue
        break
    return False, args


def should_deny(cmd: str) -> bool:
    """Return True iff `cmd` runs a test/swift/xcodebuild command outside an accepted bgrun path."""
    plain = _strip_heredocs(cmd)
    for tokens in _split_segments(plain):
        wrapped, rest = _strip_wrappers(tokens)
        if wrapped or not rest:
            continue
        joined = " ".join(shlex.quote(t) if any(ch.isspace() for ch in t) else t for t in rest)
        if SAFE.search(joined):
            continue
        if SEGMENT.match(joined):
            return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if data.get("tool_name") != "Bash" or os.environ.get("BG_GATE_OFF"):
        return 0
    cmd = str((data.get("tool_input") or {}).get("command") or "")
    try:
        if should_deny(cmd):
            reason = (
                f"Tests run through bgrun, not bare: {BG} <your command> (or legacy {LEGACY_BG}; "
                "bare `bg` is the shell job-control builtin, so use an accepted full path). bgrun caps "
                "parallelism, runs at utility QoS and takes one of two machine-wide test slots; a bare "
                "run of a full suite sent the load average to 220 on 2026-10-08. Run the changed files "
                "first (--lf -x); run the full suite only when asked."
            )
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }
                )
            )
    except (re.error, TypeError, AttributeError):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
