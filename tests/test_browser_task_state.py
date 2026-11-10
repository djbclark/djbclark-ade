"""S7 completion is API proof, never a send receipt or a deadline registration."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_browser_task as tasks
import ade_browser_task_state as state


def result(data=None, rc=0):
    return subprocess.CompletedProcess([], rc, json.dumps(data) if data is not None else "", "")


def registration(argv):
    assert argv[:4] == [sys.executable, "-I", str(state.DEADLINE), "start"]
    return result({"name": argv[4], "owner": argv[argv.index("--owner") + 1],
                   "state": "running", "on_expire": "notify",
                   "reg_id": "a" * 32,
                   "checkpoint": argv[argv.index("--checkpoint") + 1],
                   "budget_s": int(argv[argv.index("--budget") + 1])})


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "repo with spaces"
    (root / "prompts/browser").mkdir(parents=True)
    shutil.copyfile(REPO / "prompts/browser/pr-access.md", root / "prompts/browser/pr-access.md")
    return root, tmp_path / "state"


def tracked(layout, **kwargs):
    root, directory = layout
    params = dict(root=root, task_id="pr-access", name="restrict-prs", seconds=60,
                  notify_owner="agent-123", owner="alice", repo="project",
                  directory=directory, yes=True, runner=registration, clock=lambda: 1000)
    params.update(kwargs)
    return state.track(**params)


def proof(**updates):
    return {"full_name": "alice/project", "has_pull_requests": True,
            "pull_request_creation_policy": "collaborators_only", **updates}


def test_track_default_is_no_effect_plan(layout):
    forbidden = Mock(side_effect=AssertionError("plan executed subprocess"))
    payload, rc = tracked(layout, yes=False, runner=forbidden)
    assert rc == 0 and payload["status"] == "dry-run" and payload["completed"] is False
    assert payload["send"] is False
    assert "--on-expire" in payload["deadline_argv"]
    assert not layout[1].exists()
    forbidden.assert_not_called()


def test_track_binds_target_and_registers_existing_notify_deadline(layout):
    calls = []
    def runner(argv):
        calls.append(argv)
        return registration(argv)
    payload, rc = tracked(layout, runner=runner)
    assert rc == 0 and payload["state"] == "pending" and payload["monitoring"] == "registered"
    assert payload["completed"] is False and payload["deadline_at"] == 1060
    assert calls[0] == [sys.executable, "-I", str(state.DEADLINE), "start", payload["deadline_name"],
                        "--budget", "60", "--owner", "agent-123", "--on-expire", "notify",
                        "--checkpoint", str(layout[1] / "restrict-prs.json"), "--json"]
    saved = (layout[1] / "restrict-prs.json").read_text()
    assert "prompt" not in json.loads(saved) and "Bot" not in saved
    before = saved
    with pytest.raises(tasks.BrowserTaskError, match="already exists"):
        tracked(layout, owner="different-owner", runner=Mock(side_effect=AssertionError()))
    assert (layout[1] / "restrict-prs.json").read_text() == before


@pytest.mark.parametrize("response,monitoring", [
    (result(rc=2), "registration-failed"), (result({"status": "sent"}), "registration-unknown"),
    (OSError("missing deadline"), "registration-unknown"),
    (subprocess.TimeoutExpired([], 30), "registration-unknown"),
])
def test_partial_registration_is_visible_never_retried_or_completed(layout, response, monitoring):
    runner = Mock(side_effect=[response])
    payload, rc = tracked(layout, runner=runner)
    assert rc == 1 and payload["state"] == "pending" and payload["monitoring"] == monitoring
    assert not payload["completed"] and runner.call_count == 1
    # Even uncertain registration is durable and cannot be silently retried.
    with pytest.raises(tasks.BrowserTaskError, match="already exists"):
        tracked(layout, runner=runner)
    assert runner.call_count == 1


@pytest.mark.parametrize("change", [
    {"name": "../escape"}, {"name": "UPPER"}, {"seconds": 0}, {"seconds": 86401},
    {"notify_owner": "-"}, {"notify_owner": "agent with spaces"},
    {"task_id": "issue-access"}, {"task_id": "github-app-create"},
    {"owner": "other/repo"}, {"repo": "../escape"},
])
def test_invalid_identifiers_fail_before_files_or_processes(layout, change, monkeypatch):
    render = Mock(side_effect=AssertionError("read template before validation"))
    monkeypatch.setattr(tasks, "render_task", render)
    with pytest.raises(tasks.BrowserTaskError):
        tracked(layout, **change, runner=Mock(side_effect=AssertionError("subprocess")))
    assert not layout[1].exists()
    render.assert_not_called()


def test_completed_requires_exact_authoritative_get_and_cleanup(layout):
    tracked(layout)
    runner = Mock(side_effect=[result(proof(full_name="ALICE/Project")), result()])
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"] and payload["state"] == "completed"
    assert runner.call_args_list[0].args[0] == ["gh", "api", "--method", "GET", "-H",
        "X-GitHub-Api-Version: 2026-03-10", "repos/alice/project"]
    assert runner.call_args_list[1].args[0] == [sys.executable, "-I", str(state.DEADLINE),
                                              "done", payload["deadline_name"]]
    assert payload["deadline_cleanup"] == "done"
    # Once completed this historical result is stable; no replay/send/network.
    again, rc = state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError()), clock=lambda: 2000)
    assert again["completed"] and rc == 0


@pytest.mark.parametrize("response", [
    result({"status": "sent"}), result({"status": "completed"}), result(proof(), rc=1),
    result(proof(full_name="alice/elsewhere")), result(proof(full_name=None)),
    result(proof(pull_request_creation_policy="all")), result(proof(has_pull_requests=False)),
    result(proof(pull_request_creation_policy=None)), result([proof()]),
    result(proof(has_pull_requests="true")), OSError("no gh"), subprocess.TimeoutExpired([], 30),
    subprocess.CompletedProcess([], 0, "bad json", "arbitrary API/bot error text"),
])
def test_nonproof_never_completes_and_does_not_store_payload(layout, response):
    tracked(layout)
    runner = Mock(side_effect=[response])
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 1 and payload["state"] == "pending" and payload["completed"] is False
    assert runner.call_count == 1
    assert "arbitrary API/bot" not in (layout[1] / "restrict-prs.json").read_text()


def test_expiry_before_and_during_get_cannot_be_reanimated(layout):
    tracked(layout)
    before = (layout[1] / "restrict-prs.json").read_bytes()
    assert state.status("restrict-prs", directory=layout[1], clock=lambda: 1060)["status"] == "expired"
    assert (layout[1] / "restrict-prs.json").read_bytes() == before  # status is pure
    clock = iter([1059, 1060])
    runner = Mock(side_effect=[result(proof())])
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: next(clock))
    assert rc == 1 and payload["state"] == "expired" and not payload["completed"]
    # Do not deregister an expired deadline: its notification may still be pending.
    assert runner.call_count == 1
    again, rc = state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError()), clock=lambda: 1050)
    assert rc == 1 and again["state"] == "expired"


def test_expired_record_does_not_execute_api(layout):
    tracked(layout)
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError()), clock=lambda: 1061)
    assert rc == 1 and payload["status"] == "expired"


@pytest.mark.parametrize("observed_at", [999, 1019, float("nan"), float("inf"), True])
def test_invalid_or_backwards_clock_never_writes_unreadable_completion(layout, observed_at):
    tracked(layout)
    clock = iter([1020, observed_at])
    runner = Mock(side_effect=[result(proof())])
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: next(clock))
    assert rc == 1 and not payload["completed"] and payload["state"] == "pending"
    assert payload["observation"]["reason"] == "clock-anomaly" and runner.call_count == 1
    assert state.status("restrict-prs", directory=layout[1], clock=lambda: 1020)["state"] == "pending"


def test_changed_template_or_config_does_not_retarget_record(layout):
    tracked(layout)
    root, directory = layout
    (root / "config").mkdir()
    (root / "config/github.toml").write_text('[github]\nowner="someone"\nrepository="other"\n')
    # Explicit recorded target wins over changed defaults.
    plan, rc = state.verify("restrict-prs", directory=directory, dry_run=True, runner=Mock(side_effect=AssertionError()))
    assert rc == 0 and plan["verify_argv"][-1] == "repos/alice/project"
    template = root / "prompts/browser/pr-access.md"
    template.write_text(template.read_text() + "\nChanged request.\n")
    payload, rc = state.verify("restrict-prs", directory=directory, runner=Mock(side_effect=AssertionError()), clock=lambda: 1020)
    assert rc == 1 and payload["observation"]["reason"] == "template-binding-changed"


def test_verify_dry_run_preserves_state_and_does_not_lock(layout):
    tracked(layout)
    lock = layout[1] / "restrict-prs.lock"
    lock.unlink()
    before = (layout[1] / "restrict-prs.json").read_bytes()
    payload, rc = state.verify("restrict-prs", directory=layout[1], dry_run=True,
                               runner=Mock(side_effect=AssertionError()))
    assert rc == 0 and payload["status"] == "dry-run" and not payload["completed"]
    assert not lock.exists() and (layout[1] / "restrict-prs.json").read_bytes() == before


@pytest.mark.parametrize("corrupt", [
    {"observation": None}, {"completed_at": None}, {"completed_at": float("nan")},
    {"completed_at": 1060}, {"completed_at": 999},
    {"observation": {"status": "sent"}},
    {"observation.policy": "all"}, {"observation.pull_requests_enabled": False},
    {"observation.source": "bot-reply"}, {"observation.observed_at": 1019},
    {"observation.target": "someone/other"}, {"observation.template_sha256": "0" * 64},
])
def test_malformed_completed_records_never_infer_success(layout, corrupt):
    tracked(layout)
    state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=[result(proof()), result()]), clock=lambda: 1020)
    path = layout[1] / "restrict-prs.json"
    record = json.loads(path.read_text())
    for key, value in corrupt.items():
        if key.startswith("observation."):
            record["observation"][key.split(".")[1]] = value
        else:
            record[key] = value
    path.write_text(json.dumps(record))
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.status("restrict-prs", directory=layout[1])
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError()))


def test_concurrent_failure_cannot_overwrite_completed(layout):
    tracked(layout)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def first_runner(argv):
        calls.append(argv)
        if argv[0] == "gh":
            entered.set()
            assert release.wait(5)
            return result(proof())
        return result()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(state.verify, "restrict-prs", directory=layout[1], runner=first_runner, clock=lambda: 1020)
        assert entered.wait(5)
        second = pool.submit(state.verify, "restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError("stale verifier called API")), clock=lambda: 1021)
        release.set()
        assert first.result(timeout=5)[1] == 0 and second.result(timeout=5)[1] == 0
    assert state.status("restrict-prs", directory=layout[1])["completed"]
    assert len(calls) == 2


@pytest.mark.parametrize("cleanup", [result(rc=1), OSError("deadline absent"), subprocess.TimeoutExpired([], 30)])
def test_completion_proof_independent_of_notice_cleanup(layout, cleanup):
    tracked(layout)
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=[result(proof()), cleanup]), clock=lambda: 1020)
    assert rc == 0 and payload["completed"] and payload["monitoring"] == "registered"
    assert payload["deadline_cleanup"] in ("failed", "unknown")


def test_unconfirmed_registration_never_deregisters_other_work(layout):
    tracked(layout, runner=Mock(side_effect=[OSError("registration uncertain")]))
    runner = Mock(side_effect=[result(proof())])
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"] and runner.call_count == 1
    assert payload["deadline_cleanup"] == "not-attempted-unconfirmed-registration"


def test_cold_cli_default_track_creates_no_bytecode_or_state(layout, tmp_path):
    root, directory = layout
    (root / "bin").mkdir()
    for name in ("ade-browser-task", "ade_browser_task.py", "ade_browser_task_state.py"):
        shutil.copyfile(REPO / "bin" / name, root / "bin" / name)
    home = tmp_path / "home"
    home.mkdir()
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    proc = subprocess.run([sys.executable, "-I", str(root / "bin/ade-browser-task"), "track", "pr-access",
                           "--name", "restrict-prs", "--deadline-seconds", "60", "--notify-owner", "agent-123",
                           "--owner", "alice", "--repo", "project", "--state-dir", str(directory), "--json"],
                          env={**os.environ, "HOME": str(home), "PATH": ""}, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "dry-run"
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not directory.exists() and list(home.iterdir()) == []
