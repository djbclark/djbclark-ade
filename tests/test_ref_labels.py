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


def test_ref_lookup_prints_bot_time_and_agent(tmp_path):
    e = env_with(tmp_path / "refs")
    run(["ref", "CLAUDE"], e)
    run(["ref", "ADE"], e)
    for query in ("CLAUDE-1", "claude-1", "1", "Ref: CLAUDE-1"):
        r = run(["ref", "lookup", query], e)
        assert r.returncode == 0, (query, r.stderr)
        out = r.stdout.splitlines()
        assert out[0] == "Ref: CLAUDE-1" and out[1] == "bot: CLAUDE"
        assert out[2].startswith("issued: 20") and out[3] == "agent: test-agent"
    assert run(["ref", "lookup", "2"], e).stdout.splitlines()[1] == "bot: ADE"


def test_ref_lookup_exit_1_when_never_issued_or_wrong_bot(tmp_path):
    d = tmp_path / "refs"
    e = env_with(d)
    run(["ref", "CLAUDE"], e)
    r = run(["ref", "lookup", "zz"], e)
    assert r.returncode == 1 and "never issued" in r.stderr and r.stdout == ""
    r = run(["ref", "lookup", "ADE-1"], e)
    assert r.returncode == 1 and "issued to CLAUDE, not ADE" in r.stderr
    assert run(["ref", "lookup", "82118f5 x"], e).returncode == 2  # not an id at all
    assert run(["ref", "lookup"], e).returncode != 0


def test_ref_lookup_is_read_only_and_survives_a_missing_dir(tmp_path):
    d = tmp_path / "never-created"
    r = run(["ref", "lookup", "1"], env_with(d))
    assert r.returncode == 1 and not d.exists()
    # an old 2-column log line and the counter are left alone
    d2 = tmp_path / "old"
    d2.mkdir()
    (d2 / "issued.log").write_text("7\tOLDBOT\n")
    before = sorted(p.name for p in d2.iterdir())
    r = run(["ref", "lookup", "OLDBOT-7"], env_with(d2))
    assert r.returncode == 0 and "unknown" in r.stdout and "none recorded" in r.stdout
    assert sorted(p.name for p in d2.iterdir()) == before
