#!/usr/bin/env python3
"""The "advanced" battery: harder, multi-step, tool-use-heavy coding and sysadmin
tasks, to probe a coding agent beyond the essentials floor.

Same shape as essentials.py: each task is
    {"name", "prompt", "seed" (files or "GIT"), "verify"(project_dir) -> (ok, detail)}
scored from the artifact, never the agent's report. Run with the same harness
(`bench.py advanced`, or a module-parameterised runner). Scope (2026-10-13):
rename a symbol across files, parse a log into a required report, a CLI with an
error exit code, CSV->JSON, a git branch + commit, an edge-case fix, a cross-file
dependency fix, and a SQLite query.
"""
import json
import os
import re
import subprocess

ACCESS_LOG = "GET /a 200\nGET /b 404\nGET /a 200\nPOST /c 500\n"


def sh(cmd, cwd, timeout=60):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


# --- verifiers ------------------------------------------------------------

def _v_rename_cross_file(p):
    for fn in os.listdir(p):
        if fn.endswith(".py") and "area_circle" in _read(os.path.join(p, fn)):
            return False, f"'area_circle' still in {fn}"
    rc1, out1 = sh("python3 report.py 2>&1", p)
    rc2, _ = sh("python3 -m unittest discover 2>&1", p)
    rc3, _ = sh("python3 -m pytest -q 2>&1", p)
    tests = rc2 == 0 or (rc3 == 0 and "passed" in sh("python3 -m pytest -q 2>&1", p)[1])
    return (rc1 == 0 and out1.strip() == "12.57" and tests), f"report={out1.strip()[:20]} unittest_rc={rc2}"


def _v_parse_access_log(p):
    txt = _read(f"{p}/summary.txt")
    kv = dict(re.findall(r"(\w+)\s*=\s*(\S+)", txt))
    ok = kv.get("total") == "4" and kv.get("4xx") == "1" and kv.get("5xx") == "1" and kv.get("top") == "/a"
    return ok, txt.strip()[:80]


def _v_cli(p):
    rc1, out1 = sh("python3 wc.py sample.txt 2>&1", p)
    rc2, _ = sh("python3 wc.py does_not_exist.txt 2>&1", p)
    ok = rc1 == 0 and "3" in out1 and rc2 == 2
    return ok, f"count_rc={rc1} out={out1.strip()[:10]} missing_rc={rc2}"


def _v_csv_to_json(p):
    try:
        d = json.loads(_read(f"{p}/people.json"))
    except ValueError as e:
        return False, f"invalid json: {e}"
    try:
        ok = (isinstance(d, list) and len(d) == 2 and d[0].get("name") == "ann"
              and str(d[0].get("age")) == "30" and d[1].get("name") == "bob" and str(d[1].get("age")) == "25")
    except (AttributeError, TypeError):
        ok = False
    return ok, json.dumps(d)[:90]


def _v_git_branch(p):
    br = sh("git rev-parse --abbrev-ref HEAD 2>&1", p)[1].strip()
    n = len([l for l in sh("git log --oneline 2>&1", p)[1].splitlines() if l.strip()])
    clean = sh("git status --porcelain 2>&1", p)[1].strip() == ""
    ok = br == "feature" and os.path.exists(f"{p}/feature.txt") and n >= 2 and clean
    return ok, f"branch={br} commits={n} clean={clean}"


def _v_fix_edge_case(p):
    rc1, out1 = sh("python3 stats.py nums.txt 2>&1", p)
    rc2, out2 = sh("python3 stats.py empty.txt 2>&1", p)

    def is4(s):
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return bool(m) and float(m.group()) == 4.0

    def is0(s):
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return bool(m) and float(m.group()) == 0.0

    ok = rc1 == 0 and is4(out1) and rc2 == 0 and is0(out2)
    return ok, f"mean_rc={rc1} out={out1.strip()[:10]} empty_rc={rc2} out={out2.strip()[:10]}"


def _v_dependency_chain(p):
    rc, out = sh("python3 a.py 2>&1", p)
    return (rc == 0 and out.strip() == "43"), f"rc={rc} out={out.strip()[:30]}"


def _v_sqlite(p):
    try:
        import sqlite3
        con = sqlite3.connect(f"{p}/reports.db")
        rows = con.execute("select region, amount from sales").fetchall()
        con.close()
    except Exception as e:  # noqa: BLE001
        return False, f"db error: {e}"
    east = sum(a for r, a in rows if r == "east")
    tot = _read(f"{p}/total_east.txt").strip()
    ok = east == 150 and tot == "150" and len(rows) == 3
    return ok, f"rows={rows} total_east={tot}"


TASKS = [
    {"name": "rename_cross_file", "verify": _v_rename_cross_file,
     "seed": {
         "mathlib.py": "def area_circle(r):\n    return 3.14159 * r * r\n",
         "report.py": "from mathlib import area_circle\n\nprint(round(area_circle(2), 2))\n",
         "test_report.py": "import unittest\nfrom mathlib import area_circle\n\n\nclass T(unittest.TestCase):\n    def test_area(self):\n        self.assertAlmostEqual(area_circle(1), 3.14159, places=4)\n",
     },
     "prompt": "Rename the function area_circle to circle_area everywhere in this directory (mathlib.py and every file that imports or calls it), keeping report.py printing 12.57 and the tests passing. Run the tests."},

    {"name": "parse_access_log", "verify": _v_parse_access_log, "seed": {"access.log": ACCESS_LOG},
     "prompt": 'Parse access.log and write summary.txt with exactly: the total request count, the number of 4xx responses, the number of 5xx responses, and the most frequent path, in the form "total=<n> 4xx=<n> 5xx=<n> top=<path>" (spaces between the pairs).'},

    {"name": "cli_error_code", "verify": _v_cli, "seed": {"sample.txt": "a\nb\nc\n"},
     "prompt": "Write wc.py: running 'python3 wc.py FILE' prints the number of lines in FILE and exits 0; if FILE does not exist it prints an error and exits with status 2. Do not use the shell wc command to read the file; read it in Python."},

    {"name": "csv_to_json", "verify": _v_csv_to_json, "seed": {"people.csv": "name,age\nann,30\nbob,25\n"},
     "prompt": "Convert people.csv into people.json: a JSON array of objects using the header row as the keys (one object per data row). Keep it valid JSON."},

    {"name": "git_branch_commit", "verify": _v_git_branch, "seed": "GIT",
     "prompt": "Create and switch to a new git branch named feature, add a file feature.txt containing the word done, and commit it on that branch. Leave the working tree clean."},

    {"name": "fix_edge_case", "verify": _v_fix_edge_case,
     "seed": {
         "stats.py": "import sys\n\nnums = [int(x) for x in open(sys.argv[1]).read().split()]\nprint(sum(nums) / len(nums))\n",
         "nums.txt": "2 4 6\n", "empty.txt": "",
     },
     "prompt": "stats.py reads whitespace-separated integers from the file named on the command line and prints their mean. It currently crashes on an empty file. Fix it so it prints the mean, and prints 0 for an empty file. Do not change the file names."},

    {"name": "fix_dependency_chain", "verify": _v_dependency_chain,
     "seed": {
         "c.py": "def base():\n    return 42\n",
         "b.py": "from c import base\n\n\ndef value():\n    return base() - 2\n",
         "a.py": "from b import value\n\nprint(value() + 1)\n",
     },
     "prompt": "This is a three-file program: a.py imports b.py, which imports c.py. Running 'python3 a.py' should print 43 but prints 41. There is exactly one bug; find it and fix it so a.py prints 43."},

    {"name": "sqlite_query", "verify": _v_sqlite, "seed": {},
     "prompt": "Using Python, create a SQLite database reports.db with a table sales(region TEXT, amount INTEGER) and insert exactly these rows: ('east', 100), ('west', 200), ('east', 50). Then write total_east.txt containing the total amount for the east region (just the number)."},
]


def seed_project(proj, task):
    if task.get("seed") == "GIT":
        sh("git init -q && git config user.email t@t && git config user.name t", proj)
        with open(os.path.join(proj, "README.md"), "w") as f:
            f.write("demo\n")
        sh("git add -A && git commit -qm init", proj)
        return
    for fn, content in (task.get("seed") or {}).items():
        path = os.path.join(proj, fn)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
