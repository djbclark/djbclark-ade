"""bin/ref and bin/ref-append: global base-36 counter, issued.log, refusal."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv, env, stdin=None):
    return subprocess.run(argv, cwd=ROOT, env=env, input=stdin, capture_output=True,
                          text=True, timeout=30)


def env_with(refs_dir):
    e = dict(os.environ, REFS_DIR=str(refs_dir), PASEO_AGENT_ID="test-agent")
    e["PATH"] = str(ROOT / "bin") + os.pathsep + e["PATH"]
    return e


def test_ref_issues_sequential_ids_and_log(tmp_path):
    d = tmp_path / "refs"
    e = env_with(d)
    r1 = run(["ref", "Chief of Staff"], e)
    assert r1.returncode == 0 and r1.stdout.strip() == "Ref: CHIEFOFSTAFF-1", r1.stdout + r1.stderr
    r2 = run(["ref", "CHIEF"], e)
    assert r2.stdout.strip() == "Ref: CHIEF-2"
    lines = (d / "issued.log").read_text().splitlines()
    assert lines[0].startswith("1\tCHIEFOFSTAFF\t") and lines[0].endswith("\ttest-agent")
    assert lines[1].startswith("2\tCHIEF\t")
    assert (d / "GLOBAL.count").read_text().strip() == "2"


def test_ref_append_appends_then_refuses_double(tmp_path):
    d = tmp_path / "refs"
    e = env_with(d)
    r = run(["ref-append", "TESTBOT"], e, stdin="hello\n")
    assert r.returncode == 0
    assert r.stdout.rstrip().endswith("Ref: TESTBOT-1"), r.stdout
    r2 = run(["ref-append", "TESTBOT"], e, stdin=r.stdout)
    assert r2.returncode == 2 and "already ends with a Ref line" in r2.stderr
