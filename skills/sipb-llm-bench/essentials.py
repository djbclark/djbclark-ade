#!/usr/bin/env python3
"""The "essentials" battery: small, objectively-scored coding and sysadmin tasks.

Each task is a dict:

    {"name": str, "prompt": str,
     "seed":  {relative_path: content, ...} or "GIT",
     "verify": callable(project_dir) -> (ok: bool, detail: str)}

The prompt is handed to the agent with the project dir as cwd; `verify` checks
the artifact on disk (or runs the tests) — never the agent's own report. This is
the set behind `bench.py essentials`; keep it stdlib-only and deterministic.

Scope (2026-10-13): file create/append/edit, config edits (TOML, JSON, nginx),
a bug fix, a new function + test, rename/move, read-a-value-and-write-it,
mkdir -p, find/replace, a git commit, and a shell pipeline. The aim is a floor:
a model that cannot do these should not be offered to a coding agent.
"""
import json
import os
import re
import subprocess

CALC_BUGGY = """def add(a, b):
    return a + b


def count_up(n):
    # intended: return 1..n inclusive
    return list(range(n))
"""

TEST_CALC = """import unittest
from calc import add, count_up


class T(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_count_up(self):
        self.assertEqual(count_up(3), [1, 2, 3])
"""


def sh(cmd, cwd, timeout=60):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def _v_write_file(p):
    return _read(f"{p}/hello.txt") == "hello world\n", repr(_read(f"{p}/hello.txt")[:40])


def _v_append_line(p):
    txt = _read(f"{p}/app.conf")
    ok = txt.rstrip().endswith("DEBUG=1") and "PORT=8080" in txt
    return ok, txt.replace("\n", " | ")[:80]


def _v_edit_toml(p):
    txt = _read(f"{p}/config.toml")
    ok = re.search(r"enabled\s*=\s*true\b", txt) and "8080" in txt
    return bool(ok), txt.replace("\n", " | ")[:80]


def _v_fix_bug(p):
    return sh("python3 -m unittest 2>&1", p)[0] == 0, ""


def _v_add_function(p):
    rc1, _ = sh("python3 -c 'import math_utils; assert math_utils.add(2,3)==5' 2>&1", p)
    rc2, out = sh("python3 -m unittest discover 2>&1", p)
    m = re.search(r"Ran (\d+) test", out)
    n = int(m.group(1)) if m else 0
    return rc1 == 0 and rc2 == 0 and n >= 1, f"import_rc={rc1} unittest_rc={rc2} ntests={n}"


def _v_rename_move(p):
    ok = (os.path.exists(f"{p}/new_name.txt") and not os.path.exists(f"{p}/old_name.txt")
          and _read(f"{p}/new_name.txt") == "keep me\n")
    return ok, ""


def _v_read_and_write(p):
    return _read(f"{p}/port.txt").strip() == "5432", _read(f"{p}/port.txt") or "<none>"


def _v_mkdir_tree(p):
    return os.path.exists(f"{p}/a/b/c/marker.txt") and _read(f"{p}/a/b/c/marker.txt").strip() == "ok", ""


def _v_grep_replace(p):
    txt = _read(f"{p}/data.txt")
    return ("foo" not in txt and txt.count("bar") == 3), txt.replace("\n", " | ")[:80]


def _v_git_commit(p):
    rc, out = sh("git log --oneline 2>&1; echo ---; git status --porcelain 2>&1", p)
    ok = "add feature" in out and out.split("---")[-1].strip() == ""
    return ok, out.replace("\n", " | ")[:100]


def _v_shell_pipeline(p):
    return _read(f"{p}/sorted.txt") == "1\n2\n3\n", _read(f"{p}/sorted.txt") or "<none>"


def _v_update_json(p):
    try:
        d = json.loads(_read(f"{p}/package.json"))
    except ValueError as e:
        return False, f"invalid json: {e}"
    return (d.get("version") == "2.0.0" and d.get("name") == "demo" and d.get("private") is True), json.dumps(d)


def _v_nginx(p):
    txt = _read(f"{p}/nginx.conf")
    return ("worker_processes 4;" in txt and "user nginx;" in txt), txt.replace("\n", " | ")[:80]


def _v_script_exec(p):
    f = f"{p}/deploy.sh"
    if not os.path.exists(f):
        return False, "missing deploy.sh"
    try:
        exe = bool(os.stat(f).st_mode & 0o111)
    except OSError:
        exe = False
    out = sh("bash deploy.sh 2>&1", p)[1]
    return exe and "deployed" in out, f"exec={exe} out={out.strip()[:40]}"


def _first_num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _v_multistep_csv(p):
    if not os.path.exists(f"{p}/sumcol.py"):
        return False, "<no sumcol.py>"
    rc, out = sh("python3 sumcol.py 2>&1", p)
    res = _read(f"{p}/result.txt")
    ok = rc == 0 and _first_num(out) == 6.0 and _first_num(res) == 6.0
    return ok, f"rc={rc} stdout={out.strip()[:20]} result={res.strip()[:10]}"


def _v_fix_runtime(p):
    rc, out = sh("python3 run.py 2>&1", p)
    return (rc == 0 and "42" in out), f"rc={rc} out={out.strip()[:60]}"


def _v_file_mode(p):
    f = f"{p}/secret.txt"
    if not os.path.exists(f):
        return False, "missing secret.txt"
    mode = os.stat(f).st_mode & 0o777
    return (_read(f).strip() == "topsecret" and mode == 0o600), f"mode={oct(mode)}"


def _v_yaml(p):
    txt = _read(f"{p}/service.yaml")
    return bool(re.search(r"replicas:\s*3\b", txt)) and "myapp" in txt, txt.replace("\n", " | ")[:80]


def _v_env(p):
    txt = _read(f"{p}/.env")
    ok = bool(re.search(r"^LOG_LEVEL=debug$", txt, re.M) and re.search(r"^APP=1$", txt, re.M))
    return ok, txt.replace("\n", " | ")[:80]


def _v_systemd(p):
    txt = _read(f"{p}/app.service")
    return ("Restart=always" in txt and "Restart=no" not in txt), txt.replace("\n", " | ")[:80]


TASKS = [
    {"name": "write_file", "verify": _v_write_file, "seed": {},
     "prompt": 'Create a file named hello.txt in the current directory containing exactly the text "hello world" (without the quotes) and a trailing newline. Then stop.'},
    {"name": "append_line", "verify": _v_append_line, "seed": {"app.conf": "PORT=8080\nHOST=localhost\n"},
     "prompt": 'The file app.conf already exists. Append a line containing exactly "DEBUG=1" at the end of it, keeping every existing line.'},
    {"name": "edit_toml", "verify": _v_edit_toml, "seed": {"config.toml": "[server]\nenabled = false\nport = 8080\n"},
     "prompt": "In config.toml (already present) set the key enabled to true. Change nothing else."},
    {"name": "fix_bug", "verify": _v_fix_bug, "seed": {"calc.py": CALC_BUGGY, "test_calc.py": TEST_CALC},
     "prompt": 'calc.py and test_calc.py are in the current directory. Running "python3 -m unittest" fails. Fix calc.py so the tests pass. Do not modify test_calc.py.'},
    {"name": "add_function_and_test", "verify": _v_add_function, "seed": {"math_utils.py": "def unused():\n    return 0\n"},
     "prompt": "In math_utils.py add a function add(a, b) that returns a + b. Add a test file test_math_utils.py that imports add and tests it, then run the tests."},
    {"name": "rename_move", "verify": _v_rename_move, "seed": {"old_name.txt": "keep me\n"},
     "prompt": "Rename the file old_name.txt to new_name.txt."},
    {"name": "read_and_write", "verify": _v_read_and_write, "seed": {"notes.md": "# Notes\nHOST=localhost\nPORT=5432\nDEBUG=yes\n"},
     "prompt": 'notes.md contains a line "PORT=<number>". Write only that number to a new file port.txt.'},
    {"name": "mkdir_tree", "verify": _v_mkdir_tree, "seed": {},
     "prompt": "In the current directory, create the directory path a/b/c and put a file named marker.txt inside it containing the text ok."},
    {"name": "grep_replace", "verify": _v_grep_replace, "seed": {"data.txt": "foo one\nfoo two\nbaz foo\n"},
     "prompt": "In data.txt replace every occurrence of foo with bar."},
    {"name": "git_commit", "verify": _v_git_commit, "seed": "GIT",
     "prompt": "This is a git repository with an uncommitted new file. Stage all changes and commit them with the message 'add feature'."},
    {"name": "shell_pipeline", "verify": _v_shell_pipeline, "seed": {},
     "prompt": "In the current directory, create a file numbers.txt containing the numbers 3, 1, 2 and 2 (one per line). Then create sorted.txt containing those numbers unique and sorted ascending, one per line."},
    {"name": "update_json", "verify": _v_update_json, "seed": {"package.json": '{\n  "name": "demo",\n  "version": "1.0.0",\n  "private": true\n}\n'},
     "prompt": 'In package.json set the value of the key "version" to "2.0.0". Keep it valid JSON and change nothing else.'},
    {"name": "nginx_config", "verify": _v_nginx, "seed": {"nginx.conf": "user nginx;\nworker_processes 1;\nerror_log /var/log/nginx/error.log;\n"},
     "prompt": "In nginx.conf change the worker_processes directive from 1 to 4, leaving the rest of the file unchanged."},
    {"name": "script_exec", "verify": _v_script_exec, "seed": {},
     "prompt": "In the current directory, create a shell script named deploy.sh that prints the single word 'deployed', make it executable (chmod +x), and run it once."},
    {"name": "multistep_csv", "verify": _v_multistep_csv, "seed": {"data.csv": "name,value\na,1\nb,2\nc,3\n"},
     "prompt": "data.csv is present (a header row name,value then rows). Write a Python script sumcol.py that reads data.csv and prints the sum of the numbers in the second column. Run it and write just that sum to result.txt."},
    {"name": "fix_runtime", "verify": _v_fix_runtime,
     "seed": {"run.py": "def total():\n    return 40 + 2\n\n\nprint(totl())\n"},
     "prompt": "run.py in the current directory crashes when run with python3. Fix it so that 'python3 run.py' prints 42 and exits successfully."},
    {"name": "file_mode", "verify": _v_file_mode, "seed": {},
     "prompt": "In the current directory, create a file named secret.txt containing the text topsecret, then set its permissions to 600 (owner read/write only)."},
    {"name": "yaml_edit", "verify": _v_yaml, "seed": {"service.yaml": "app: myapp\nreplicas: 1\nimage: myapp:1.0\n"},
     "prompt": "In service.yaml set replicas to 3. Change nothing else."},
    {"name": "env_file", "verify": _v_env, "seed": {".env": "APP=1\nLOG_LEVEL=info\n"},
     "prompt": "In the .env file set the value of LOG_LEVEL to debug, keeping the other lines."},
    {"name": "systemd_unit", "verify": _v_systemd, "seed": {"app.service": "[Service]\nExecStart=/usr/bin/app\nRestart=no\n"},
     "prompt": "In app.service change Restart=no to Restart=always. Change nothing else."},
]


def seed_project(proj, task):
    """Create the task's starting files (or a git repo) in proj."""
    if task.get("seed") == "GIT":
        sh("git init -q && git config user.email t@t && git config user.name t", proj)
        with open(os.path.join(proj, "README.md"), "w") as f:
            f.write("demo\n")
        sh("git add -A && git commit -qm init", proj)
        with open(os.path.join(proj, "feature.py"), "w") as f:
            f.write("x = 1\n")
        return
    for fn, content in (task.get("seed") or {}).items():
        path = os.path.join(proj, fn)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
