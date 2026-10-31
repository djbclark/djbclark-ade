## Port of claude/hooks/jev_effort_hook.py (UserPromptSubmit effort observation).
## Entry label: hook_jev_effort. The hook JSON arrives on stdin (read in-process via sys.stdin),
## the decision line goes to stdout, and the exit status is left in ade_exit_code.
## Failures never block a prompt: every error path ends at exit 0.
## Deviation: the original armed SIGALRM for its deadline; Ren'Py owns the main thread's signals,
## so the deadline here is subprocess.communicate's timeout alone (same 2.7 s budget).

init python:
    import json, os, re, signal, subprocess, sys, time
    from pathlib import Path

    _jev_started = time.monotonic()
    # console/game is renpy.config.gamedir; the repo root is two levels above console/.
    _JEV_BIN = str(Path(renpy.config.gamedir).resolve().parents[1] / "bin" / "jev")

    def _jev_mode():
        value = os.environ.get("JEV_MODE")
        if value is None:
            try:
                value = (Path.home() / ".config/jev/mode").read_text().split()[0]
            except (OSError, IndexError):
                value = "off"
        return value if value in ("shadow", "act") else "off"

    def _jev_skip(prompt):
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

    def _jev_model_from_tail(path):
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

    def _jev_main(stdin_text):
        selected = _jev_mode()
        if selected == "off":
            return 0
        child = None
        try:
            data = json.loads(stdin_text)
            prompt = data.get("prompt", "")
            if not isinstance(prompt, str) or _jev_skip(prompt):
                return 0
            model = _jev_model_from_tail(data.get("transcript_path"))
            remaining = 2.7 - (time.monotonic() - _jev_started)
            if remaining <= 0:
                return 0
            args = [_JEV_BIN, "decide", "--site", "prompt-effort", "--question",
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
                sys.stdout.write(json.dumps({"systemMessage": f"jev: this looks mechanical (p={result['prob']:.2f}); /model sonnet would cost less"}) + "\n")
        except Exception:
            pass
        finally:
            if child is not None and child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        return 0

label hook_jev_effort:
    $ ade_exit_code = 0
    $ ade_exit_code = _jev_main(sys.stdin.read() if _jev_mode() != "off" else "")
    return
