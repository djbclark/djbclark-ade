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


# ---------------------------------------------------------------- code mode

CODE_FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, sys
    from pathlib import Path
    agent, prompt_file, out_file = sys.argv[1:4]
    Path("solution.txt").write_text(f"by {agent}\\n")
    if agent == "good":
        Path("ok.txt").write_text("1\\n")
    if agent == "noisy":
        Path("noise.txt").write_text("x" * 500 + "\\n")
    open(out_file, "w").write(f"{agent} worked in {os.getcwd()}\\nchanged solution.txt\\n")
''')


@pytest.fixture
def code_runner(tmp_path):
    script = tmp_path / "code_agent.py"
    script.write_text(CODE_FAKE)
    script.chmod(0o755)
    return f"{script} {{agent}} {{prompt}} {{output}}"


@pytest.fixture
def srcdir(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "original.txt").write_text("before\n")
    return d


def test_code_mode_picks_the_side_that_passes_the_check(tmp_path, code_runner, srcdir):
    r = run(None, "make the check pass", "--code", srcdir, "--runner", code_runner, "--rounds", 0,
            "--a", "good", "--b", "sloppy", "--check", "test -f ok.txt", "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert "WINNER proposer" in r.stdout
    out = tmp_path / "out"
    assert (out / "a" / "solution.txt").exists() and (out / "b" / "solution.txt").exists()
    assert (out / "a" / "ok.txt").exists() and not (out / "b" / "ok.txt").exists()
    text = (out / "transcript.md").read_text()
    assert "changed: 2 files" in text and "solution.txt" in text


def test_code_mode_reports_toe_stepping(tmp_path, code_runner, srcdir):
    r = run(None, "make the check pass", "--code", srcdir, "--runner", code_runner, "--rounds", 0,
            "--a", "good", "--b", "sloppy", "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    text = (tmp_path / "out" / "transcript.md").read_text()
    assert "## toe-stepping" in text and "solution.txt" in text.split("## toe-stepping")[1]


def test_code_mode_with_no_passing_side_fails_closed(tmp_path, code_runner, srcdir):
    r = run(None, "make the check pass", "--code", srcdir, "--runner", code_runner, "--rounds", 0,
            "--a", "sloppy", "--b", "sloppy", "--check", "test -f ok.txt", "--out", tmp_path / "out")
    assert r.returncode == 5
    assert "neither side passes --check" in r.stderr


def test_code_mode_falls_back_to_the_smaller_change(tmp_path, code_runner, srcdir):
    r = run(None, "make the check pass", "--code", srcdir, "--runner", code_runner, "--rounds", 0,
            "--a", "noisy", "--b", "sloppy", "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert "WINNER challenger" in r.stdout, r.stdout
    assert "touched 1 files instead of 2" in r.stdout


def test_code_mode_refuses_a_missing_directory(tmp_path, code_runner):
    r = run(None, "task", "--code", tmp_path / "nope", "--runner", code_runner, "--out", tmp_path / "out")
    assert r.returncode == 2 and "not a directory" in r.stderr


# ---------------------------------------------------------------- trash talk

ECHO = textwrap.dedent('''\
    #!/usr/bin/env python3
    import sys
    agent, prompt_file, out_file = sys.argv[1:4]
    open(out_file, "w").write("ECHO " + open(prompt_file).read())
''')


@pytest.fixture
def echo_runner(tmp_path):
    script = tmp_path / "echo_agent.py"
    script.write_text(ECHO)
    script.chmod(0o755)
    return f"{script} {{agent}} {{prompt}} {{output}}"


def test_insults_are_on_by_default_and_bound_to_a_claim(tmp_path, echo_runner, artifact):
    r = run(None, artifact, "--runner", echo_runner, "--rounds", 1, "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    text = (tmp_path / "out" / "transcript.md").read_text()
    assert "TRASH TALK" in text
    assert "every insult must be attached to a concrete technical claim" in text
    assert "the operator is never the\\n    target" in text or "operator is never the" in text


def test_insults_off_is_the_polite_committee(tmp_path, echo_runner, artifact):
    r = run(None, artifact, "--runner", echo_runner, "--rounds", 1, "--insults", "off",
            "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert "TRASH TALK" not in (tmp_path / "out" / "transcript.md").read_text()


def test_failed_run_does_not_truncate_an_existing_transcript(tmp_path, runner, artifact):
    """Atomic write: a duel that dies mid-way must leave the previous transcript intact, not half-written."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("previous run\n")
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--out", out, "--force",
            env={"FAKE_MODE": "silent"})
    assert r.returncode == 3
    assert (out / "transcript.md").read_text() == "previous run\n"
    assert not list(out.glob(".*.tmp")), "a temp file was left behind"


def test_output_directory_is_reserved_against_a_second_duel(tmp_path, runner, artifact):
    out = tmp_path / "out"
    out.mkdir()
    (out / "duel.lock").write_text("1234 running\n")
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--out", out, "--force")
    assert r.returncode == 2 and "in use by another duel" in r.stderr
    assert not (out / "transcript.md").exists()


def test_the_artifact_evaluated_is_kept_beside_the_transcript(tmp_path, runner, artifact):
    r = run(None, artifact, "--runner", runner, "--rounds", 1, "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out" / "artifact.md").read_text() == artifact.read_text()
    assert "artifact.md" in (tmp_path / "out" / "transcript.md").read_text()
    assert not (tmp_path / "out" / "duel.lock").exists(), "the reservation must be released"
