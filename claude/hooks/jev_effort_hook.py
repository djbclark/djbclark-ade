#!/usr/bin/env python3
"""Optional UserPromptSubmit effort observation; failures never block a prompt."""
import os
import sys
import time
from pathlib import Path

STARTED = time.monotonic()


def mode():
    value = os.environ.get("JEV_MODE")
    if value is None:
        try:
            value = (Path.home() / ".config/jev/mode").read_text().split()[0]
        except (OSError, IndexError):
            value = "off"
    return value if value in ("shadow", "act") else "off"


if __name__ == "__main__" and mode() == "off":
    sys.exit(0)

import json
import re
import signal
import subprocess

JEV = Path(__file__).resolve().parents[2] / "bin/jev"


def skip(prompt):
    text = prompt.strip()
    # Claude may wrap pasted material; strip that wrapper only for skip detection.
    text = re.sub(r'^<pasted_content\b[^>]*>\s*|\s*</pasted_content[^>]*>$', '', text).strip()
    if len(text) < 20 or text.startswith("/"):
        return True
    if re.fullmatch(r"<(task-notification|tool_result|tool-result)\b[^>]*>.*</\1>", text, re.S):
        return True
    try:
        data = json.loads(text)
        blocks = data if isinstance(data, list) else [data]
        return bool(blocks) and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
    except ValueError:
        return False


def model_from_tail(path):
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            start = max(0, stream.tell() - 65536)
            stream.seek(start)
            data = stream.read(65536)
        lines = data.splitlines()
        if start:
            lines = lines[1:]
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "assistant":
                return (entry.get("message") or {}).get("model") or entry.get("model") or "unknown"
    except (OSError, TypeError):
        pass
    return "unknown"


def deadline(_sig, _frame):
    raise TimeoutError()


def main():
    selected = mode()
    if selected == "off":
        return 0
    child = None
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, max(.001, 2.9 - (time.monotonic() - STARTED)))
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or skip(prompt):
            return 0
        model = model_from_tail(data.get("transcript_path"))
        remaining = 2.7 - (time.monotonic() - STARTED)
        if remaining <= 0:
            return 0
        args = [str(JEV), "decide", "--site", "prompt-effort", "--question",
                "How much reasoning does the next stretch of work this prompt asks for need?",
                "--option", "mechanical", "--option", "normal", "--option", "hard",
                "--meta", "model=" + model, "--meta", "session=" + str(data.get("session_id", "")),
                "--timeout", str(max(.001, remaining - .1))]
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, start_new_session=True,
                                 env=dict(os.environ, JEV_MODE=selected))
        output, _ = child.communicate(prompt[:4000], timeout=remaining)
        if child.returncode != 0:
            return 0
        result = json.loads(output)
        if (selected == "act" and result.get("answer") == "mechanical" and
                result.get("confident") and any(m in model.lower() for m in ("opus", "fable"))):
            print(json.dumps({"systemMessage": f"jev: this looks mechanical (p={result['prob']:.2f}); /model sonnet would cost less"}))
    except Exception:
        pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
