"""bin/ade-duel: two agents argue, the transcript is the record, silence fails closed."""

import textwrap
from pathlib import Path

import pytest

DUEL = Path(__file__).resolve().parents[1] / "bin" / "ade-duel"

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, sys
    agent, prompt_file, out_file = sys.argv[1:4]
    text = open(prompt_file).read()
    mode = os.environ.get("FAKE_MODE", "normal")
    if mode == "silent":
        open(out_file, "w").close(); raise SystemExit(0)
    if mode == "crash":
        print("boom", file=sys.stderr); raise SystemExit(7)
    if "You are the JUDGE" in text:
        body = "A survived.\\n" + ("VERDICT: A\\nA named the failure.\\n" if mode != "no-verdict" else "hard call.\\n")
    else:
        role = "PROPOSER" if "You are the PROPOSER" in text else "CHALLENGER"
        body = f"{role}[{agent}] round-ish {text.count('## Round')}\\n"
    open(out_file, "w").write(body)
''')


@pytest.fixture
def runner(tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE)
    script.chmod(0o755)
    return f"{script} {{agent}} {{prompt}} {{output}}"


@pytest.fixture
def artifact(tmp_path):
    a = tmp_path / "artifact.md"
    a.write_text("A one-line design for something contentious.\n")
    return a


def run(duel_run, *args, env=None):
    import os
    import subprocess
    import sys
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(DUEL), *map(str, args)], capture_output=True, text=True, env=e)


def test_rounds_alternate_and_transcript_is_written(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 2, "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    text = (tmp_path / "out" / "transcript.md").read_text()
    assert [l.split(" — ")[0].lstrip("# ") for l in text.splitlines() if l.startswith("## ")] == [
        "proposer", "challenger", "proposer", "challenger", "proposer"]
    assert "round 0" in text and "round 2" in text


def test_silent_agent_fails_closed(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--out", tmp_path / "out",
            env={"FAKE_MODE": "silent"})
    assert r.returncode == 3
    assert "produced no output" in r.stderr
    assert "must not be read as an argument" in r.stderr


def test_runner_crash_is_not_read_as_agreement(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--out", tmp_path / "out",
            env={"FAKE_MODE": "crash"})
    assert r.returncode == 3
    assert "exited 7" in r.stderr and "boom" in r.stderr


def test_missing_runner_is_usage(tmp_path, artifact):
    r = run(None, artifact, "--rounds", 1, "--out", tmp_path / "out", env={"ADE_DUEL_RUNNER": ""})
    assert r.returncode == 2
    assert "no runner" in r.stderr


def test_empty_artifact_is_refused(tmp_path, runner):
    empty = tmp_path / "empty.md"
    empty.write_text("  \n")
    r = run(None, empty, "--runner", runner, "--out", tmp_path / "out")
    assert r.returncode == 2 and "nothing to argue about" in r.stderr


def test_judge_verdict_is_parsed_and_printed(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--judge", "judge-model",
            "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert "VERDICT A" in r.stdout
    assert "verdict: **A**" in (tmp_path / "out" / "transcript.md").read_text()


def test_judge_without_verdict_line_exits_4(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--judge", "judge-model",
            "--out", tmp_path / "out", env={"FAKE_MODE": "no-verdict"})
    assert r.returncode == 4 and "VERDICT" in r.stderr


def test_existing_out_directory_is_not_silently_reused(tmp_path, runner, artifact):
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old\n")
    r = run(None, artifact, "--runner", runner, "--out", out)
    assert r.returncode == 2 and "--force" in r.stderr
    assert (out / "transcript.md").read_text() == "old\n"
