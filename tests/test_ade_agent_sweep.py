"""Exercise the sweep with local fake monitors and a rendered LaunchAgent."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "ade-agent-sweep"
LABEL = "com.djbclark.ade-agent-sweep"
PLIST = ROOT / "launchd" / f"{LABEL}.plist"
TTL = "ADE_PASEO_CACHE_TTL"
EXPECTED = [
    ["ade-supervisor-scan"],
    ["ade-progress", "scan", "--yes"],
    ["ade-subagent-stalls", "--notify"],
]
FAKE_STEP = """\
#!/usr/bin/env python3
import json
import os
import pathlib
import sys

name = pathlib.Path(sys.argv[0]).name
with open(os.environ["SWEEP_CALL_LOG"], "a") as log:
    log.write(json.dumps({
        "argv": [name, *sys.argv[1:]],
        "ttl": os.environ["ADE_PASEO_CACHE_TTL"],
        "state": [os.environ[key] for key in (
            "ADE_SUPERVISOR_STATE_DIR", "ADE_PROGRESS_STATE", "XDG_STATE_HOME",
        )],
    }) + "\\n")
print(f"{name} stdout")
if name == os.environ.get("SWEEP_FAIL_STEP"):
    print("fake monitor stderr", file=sys.stderr)
    sys.exit(7)
"""


@pytest.fixture
def harness(tmp_path):
    script = tmp_path / SCRIPT.name
    shutil.copy2(SCRIPT, script)
    for name, *_ in EXPECTED:
        stub = tmp_path / name
        stub.write_text(FAKE_STEP)
        stub.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    state = [str(tmp_path / name) for name in ("supervisor", "progress", "stalls")]
    env = dict(os.environ, SWEEP_CALL_LOG=str(log), ADE_SUPERVISOR_STATE_DIR=state[0],
               ADE_PROGRESS_STATE=state[1], XDG_STATE_HOME=state[2])
    env.pop(TTL, None)
    env.pop("SWEEP_FAIL_STEP", None)

    def invoke(*args, extra_env=None):
        proc = subprocess.run([str(script), *args], env={**env, **(extra_env or {})},
                              capture_output=True, text=True, timeout=10)
        rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        assert all(row["state"] == state for row in rows)
        return proc, rows

    return invoke


@pytest.mark.parametrize(("overrides", "ttl"), [({}, "10"), ({TTL: "0"}, "0"), ({TTL: ""}, "")])
def test_children_run_in_order_with_shared_ttl(harness, overrides, ttl):
    proc, rows = harness("--json", extra_env=overrides)
    assert proc.returncode == 0, proc.stderr
    assert [row["argv"] for row in rows] == EXPECTED
    assert [row["ttl"] for row in rows] == [ttl] * 3
    summary = json.loads(proc.stdout)
    assert summary["paseo_cache_ttl"] == ttl
    assert [step["status"] for step in summary["steps"]] == ["ok"] * 3
    assert all(f"{name} stdout" in proc.stderr for name, *_ in EXPECTED)


def test_nonzero_exit_is_logged_and_later_steps_run(harness):
    proc, rows = harness("--json", extra_env={"SWEEP_FAIL_STEP": "ade-supervisor-scan"})
    assert proc.returncode == 1
    assert [row["argv"] for row in rows] == EXPECTED
    steps = json.loads(proc.stdout)["steps"]
    assert [row["returncode"] for row in steps] == [7, 0, 0]
    assert [row["status"] for row in steps] == ["failed", "ok", "ok"]
    assert "ade-supervisor-scan: exit status 7" in proc.stderr
    assert "fake monitor stderr" in proc.stderr


@pytest.mark.parametrize("dry_run", [False, True])
def test_only_keeps_order_and_deduplicates(harness, dry_run):
    args = ["--dry-run"] if dry_run else []
    proc, rows = harness("--json", "--only", "ade-subagent-stalls", "--only", "ade-progress",
                         "--only", "ade-progress", *args)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["dry_run"] is dry_run
    assert [row["step"] for row in summary["steps"]] == ["ade-progress", "ade-subagent-stalls"]
    assert [row["argv"] for row in rows] == ([] if dry_run else EXPECTED[1:])
    if dry_run:
        assert all(row["status"] == "planned" and row["returncode"] is None for row in summary["steps"])
        assert proc.stderr == ""


def test_plain_dry_run_and_invalid_selection(harness):
    proc, rows = harness("--dry-run")
    assert proc.returncode == 0 and rows == []
    assert len(proc.stdout.splitlines()) == 3
    assert proc.stdout.count(f"{TTL}=10") == 3
    proc, rows = harness("--only", "unknown")
    assert proc.returncode == 2 and rows == []
    assert "invalid choice" in proc.stderr


@pytest.fixture
def sweep():
    loader = importlib.machinery.SourceFileLoader("agent_sweep", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("error", "status", "diagnostic"),
    [(FileNotFoundError("missing executable"), "error", "FileNotFoundError: missing executable"),
     (subprocess.TimeoutExpired("fake", 180), "timeout", "timed out after 180s")],
)
def test_launch_error_and_timeout_are_isolated(sweep, monkeypatch, capsys, error, status, diagnostic):
    seen = []

    def run_step(command, env, json_output):
        seen.append([Path(command[0]).name, *command[1:]])
        if len(seen) == 1:
            raise error
        return 0

    monkeypatch.setattr(sweep, "run_step", run_step)
    assert sweep.main(["--json"]) == 1
    out, err = capsys.readouterr()
    assert seen == EXPECTED
    assert [row["status"] for row in json.loads(out)["steps"]] == [status, "ok", "ok"]
    assert f"ade-supervisor-scan: {diagnostic}" in err


def test_timeout_kills_step_process_group_and_reaps_child(sweep, monkeypatch):
    events = []

    class Child:
        pid = 1234
        returncode = None

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = -signal.SIGKILL
            return self.returncode

    def spawn(command, **kwargs):
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        return Child()

    monkeypatch.setattr(sweep.subprocess, "Popen", spawn)
    monkeypatch.setattr(sweep.os, "killpg", lambda pid, sig: events.append(("killpg", pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        sweep.run_step(["fake"], {}, False)
    assert events == [("wait", sweep.STEP_TIMEOUT), ("killpg", Child.pid, signal.SIGKILL), ("wait", None)]


def test_launchd_template_and_rendered_catalog_job(tmp_path):
    with PLIST.open("rb") as source:
        template = plistlib.load(source)
    assert template["Label"] == LABEL
    assert template["StartInterval"] == 300
    assert template["ProgramArguments"] == [
        "__ADE__/bin/ade-job-run", "--lock-dir", "__ADMISSION__", LABEL, "--",
        "__ADE__/bin/ade-agent-sweep",
    ]
    inventory = tomllib.loads((ROOT / "config" / "ade.toml").read_text())["install"]
    row = next(job for job in inventory["jobs"] if job["name"] == "ade-agent-sweep")
    assert row["label"] == LABEL and ROOT / row["plist"] == PLIST
    assert row["chosen"] and row["platforms"] == ["mac"]
    assert any(job["label"] == "com.djbclark.ade-supervisor-scan" for job in inventory["retired_jobs"])
    env = dict(os.environ, HOME=str(tmp_path))
    set_arg = row["set"][0].format(home=tmp_path)
    proc = subprocess.run([sys.executable, str(ROOT / "bin" / "ade-sched"),
                           "--backend", "launchd", "--set", set_arg, "render", str(PLIST)],
                          env=env, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    rendered = plistlib.loads(proc.stdout[proc.stdout.index("<?xml"):].encode())
    assert rendered["StartInterval"] == 300
    assert rendered["ProgramArguments"][:2] == [str(ROOT / "bin" / "ade-job-run"), "--lock-dir"]
    assert Path(rendered["ProgramArguments"][2]).is_absolute()
    assert rendered["ProgramArguments"][3:] == [LABEL, "--", str(SCRIPT)]
    assert rendered["StandardErrorPath"] == str(tmp_path / ".local/state/djbclark-ade/agent-sweep/sweep.err")
    assert not list(tmp_path.iterdir())
