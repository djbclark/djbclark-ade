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
    for template in ("pr-access.md", "issue-access.md", "github-app-create.md"):
        shutil.copyfile(REPO / "prompts/browser" / template, root / "prompts/browser" / template)
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
    {"task_id": "add-collaborator"}, {"task_id": "no-such-task"},
    {"task_id": "github-app-create", "app_name": "../escape"},
    {"task_id": "github-app-create", "app_name": "has_underscore"},
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
    assert runner.call_args_list[0].args[0] == ["gh", "api", "--hostname", "github.com", "--method", "GET", "-H",
        "X-GitHub-Api-Version: 2026-03-10", "repos/alice/project"]
    assert runner.call_args_list[1].args[0] == [sys.executable, "-I", str(state.DEADLINE),
                                              "done", payload["deadline_name"]]
    assert payload["deadline_cleanup"] == "done"
    # Once completed this historical result is stable; no replay/send/network.
    again, rc = state.verify("restrict-prs", directory=layout[1], runner=Mock(side_effect=AssertionError()), clock=lambda: 2000)
    assert again["completed"] and rc == 0


def test_github_host_override_cannot_retarget_bound_template(layout, monkeypatch):
    monkeypatch.setenv("GH_HOST", "enterprise.example")
    tracked(layout)
    runner = Mock(side_effect=[result(proof()), result()])
    plan, rc = state.verify("restrict-prs", directory=layout[1], dry_run=True, runner=runner)
    assert rc == 0 and runner.call_count == 0
    payload, rc = state.verify("restrict-prs", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"]
    get = runner.call_args_list[0].args[0]
    assert get == plan["verify_argv"]
    assert get[get.index("--hostname") + 1] == "github.com"
    assert get[-1] == "repos/alice/project"
    assert os.environ["GH_HOST"] == "enterprise.example"


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
    {"observation.hostname": None}, {"observation.hostname": "enterprise.example"},
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


# --- W22 (2026-11-12): issue-access / github-app-create readbacks, poll ---


def issue_tracked(layout, **kwargs):
    root, directory = layout
    params = dict(root=root, task_id="issue-access", name="restrict-issues", seconds=60,
                  notify_owner="agent-123", owner="alice", repo="project",
                  directory=directory, yes=True, runner=registration, clock=lambda: 1000)
    params.update(kwargs)
    return state.track(**params)


def issue_proof(**updates):
    return {"full_name": "alice/project", "has_issues": True,
            "issue_creation_policy": "collaborators_only", **updates}


def test_issue_access_completes_from_repository_readback(layout):
    issue_tracked(layout)
    runner = Mock(side_effect=[result(issue_proof(full_name="ALICE/Project")), result()])
    payload, rc = state.verify("restrict-issues", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"] and payload["state"] == "completed"
    assert runner.call_args_list[0].args[0] == ["gh", "api", "--hostname", "github.com", "--method", "GET", "-H",
        "X-GitHub-Api-Version: 2026-03-10", "repos/alice/project"]
    obs = payload["observation"]
    assert obs["issue_creation_policy"] == "collaborators_only" and obs["issues_enabled"] is True
    assert obs["source"] == "github-rest-repository" and obs["hostname"] == "github.com"
    assert payload["deadline_cleanup"] == "done"
    again, rc = state.verify("restrict-issues", directory=layout[1],
                             runner=Mock(side_effect=AssertionError()), clock=lambda: 2000)
    assert again["completed"] and rc == 0


@pytest.mark.parametrize("response,reason", [
    (result({"full_name": "alice/project", "has_issues": True}), "field-missing"),
    (result(issue_proof(issue_creation_policy=None)), None),
    (result(issue_proof(issue_creation_policy="all")), None),
    (result(issue_proof(issue_creation_policy="everyone")), None),
    (result(issue_proof(has_issues=False)), None),
    (result(issue_proof(has_issues="true")), None),
    (result(issue_proof(full_name="alice/elsewhere")), "repository-identity-mismatch"),
    (result(issue_proof(), rc=1), "api-unreadable"),
    (OSError("no gh"), "api-unreadable"),
    (subprocess.TimeoutExpired([], 30), "api-unreadable"),
    (subprocess.CompletedProcess([], 0, "bad json", "arbitrary API/bot error text"), "api-unreadable"),
])
def test_issue_access_nonproof_never_completes_or_stores_payload(layout, response, reason):
    issue_tracked(layout)
    runner = Mock(side_effect=[response])
    payload, rc = state.verify("restrict-issues", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 1 and payload["state"] == "pending" and payload["completed"] is False
    if reason:
        assert payload["observation"]["reason"] == reason
    assert payload["observation"]["status"] == "not-matched"
    assert runner.call_count == 1
    assert "arbitrary API/bot" not in (layout[1] / "restrict-issues.json").read_text()


@pytest.mark.parametrize("corrupt", [
    {"observation": None}, {"completed_at": 1060},
    {"observation.issue_creation_policy": "all"},
    {"observation.issue_creation_policy": "unknown"},
    {"observation.issues_enabled": False},
    {"observation.source": "bot-reply"},
    {"observation.observed_at": 1019},
    {"observation.target": "someone/other"},
])
def test_issue_completed_records_never_infer_success(layout, corrupt):
    issue_tracked(layout)
    state.verify("restrict-issues", directory=layout[1],
                 runner=Mock(side_effect=[result(issue_proof()), result()]), clock=lambda: 1020)
    path = layout[1] / "restrict-issues.json"
    record = json.loads(path.read_text())
    for key, value in corrupt.items():
        if key.startswith("observation."):
            record["observation"][key.split(".")[1]] = value
        else:
            record[key] = value
    path.write_text(json.dumps(record))
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.status("restrict-issues", directory=layout[1])
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.verify("restrict-issues", directory=layout[1], runner=Mock(side_effect=AssertionError()))


def app_tracked(layout, **kwargs):
    root, directory = layout
    params = dict(root=root, task_id="github-app-create", name="create-app", seconds=60,
                  notify_owner="agent-123", owner="alice", repo="project",
                  directory=directory, yes=True, runner=registration, clock=lambda: 1000)
    params.update(kwargs)
    return state.track(**params)


def app_payload(**updates):
    payload = {"slug": "ade-merge-gate", "id": 123,
               "permissions": {"statuses": "write", "checks": "write", "pull_requests": "read"}}
    payload.update(updates)
    return payload


def installations_payload(**updates):
    row = {"id": 7, "app_id": 123, "app_slug": "ade-merge-gate",
           "account": "alice", "repository_selection": "selected"}
    row.update(updates)
    return [row]


def app_proof_responses():
    return [result(app_payload()), result(installations_payload()),
            result(["alice/project"]), result()]


def test_app_create_completes_from_app_and_installation_readback(layout):
    payload_track, _ = app_tracked(layout)
    assert payload_track["app_name"] == "ade-merge-gate"
    runner = Mock(side_effect=app_proof_responses())
    payload, rc = state.verify("create-app", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"] and payload["state"] == "completed"
    argvs = [call.args[0] for call in runner.call_args_list]
    assert argvs[0][:-1] == ["gh", "api", "--hostname", "github.com", "--method", "GET",
                             "-H", "X-GitHub-Api-Version: 2026-03-10"]
    assert argvs[0][-1] == "apps/ade-merge-gate"
    assert argvs[1][-3] == "user/installations?per_page=100"
    assert "account: .account.login" in argvs[1][-1]
    assert argvs[2][-3] == "user/installations/7/repositories?per_page=100"
    assert argvs[2][-1] == "[.repositories[].full_name]"
    assert argvs[3][:4] == [sys.executable, "-I", str(state.DEADLINE), "done"]
    obs = payload["observation"]
    assert obs["source"] == "github-rest-app-and-installations"
    assert obs["app_slug"] == "ade-merge-gate" and obs["app_found"] is True and obs["app_id"] == 123
    assert (obs["perm_statuses"], obs["perm_checks"], obs["perm_pull_requests"]) == ("write", "write", "read")
    assert obs["installation_found"] is True and obs["installation_id"] == 7
    assert obs["installation_account_match"] is True and obs["install_repos_exact"] is True
    assert obs["repository_selection"] == "selected" and obs["install_repos_count"] == 1
    again, rc = state.verify("create-app", directory=layout[1],
                             runner=Mock(side_effect=AssertionError()), clock=lambda: 2000)
    assert again["completed"] and rc == 0


def test_app_verify_dry_run_lists_readback_argv_without_executing(layout):
    app_tracked(layout)
    runner = Mock(side_effect=AssertionError("dry run executed a readback"))
    plan, rc = state.verify("create-app", directory=layout[1], dry_run=True, runner=runner)
    assert rc == 0 and plan["status"] == "dry-run"
    assert plan["verify_argv"][-1] == "apps/ade-merge-gate"
    assert len(plan["verify_argv_all"]) == 2
    runner.assert_not_called()


@pytest.mark.parametrize("responses,reason", [
    (None, None),  # full proof via app_proof_responses()
    ([result(rc=1)], "app-unreadable"),
    ([result({"slug": "other-app", "id": 5})], "app-unreadable"),
    ([result("bad json")], "app-unreadable"),
    ([result(app_payload(permissions={"statuses": "read", "checks": "write", "pull_requests": "read"})),
      result(installations_payload()), result(["alice/project"])], "permissions-mismatch"),
    ([result(app_payload()), result(installations_payload()), result(["alice/other"])],
     "installation-repos-extra"),
    ([result(app_payload()), result(installations_payload()),
      result(["alice/project", "alice/other"])], "installation-repos-extra"),
    ([result(app_payload()), result(installations_payload()), result([])],
     "installation-repos-missing"),
    ([result(app_payload()), result(installations_payload(account="someone")),
      result(["alice/project"])], "installation-account-mismatch"),
    ([result(app_payload()), result(installations_payload(app_slug="other"))],
     "installation-missing"),
    ([result(app_payload()), result(rc=1)], "installations-unreadable"),
    ([result(app_payload()), result(installations_payload()), result(rc=1)],
     "installation-repos-unreadable"),
    ([result(app_payload()), result(installations_payload(id="x"))],
     "installation-repos-unreadable"),
])
def test_app_nonproof_never_completes(layout, responses, reason):
    app_tracked(layout)
    runner = Mock(side_effect=responses if responses is not None else app_proof_responses())
    if responses is None:
        payload, rc = state.verify("create-app", directory=layout[1], runner=runner, clock=lambda: 1020)
        assert rc == 0 and payload["completed"]
        return
    payload, rc = state.verify("create-app", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 1 and payload["state"] == "pending" and payload["completed"] is False
    if reason:
        assert payload["observation"]["reason"] == reason
    assert payload["observation"]["status"] == "not-matched"


@pytest.mark.parametrize("corrupt", [
    {"observation": {"status": "matched"}},
    {"observation.app_slug": "other-app"},
    {"observation.app_found": False},
    {"observation.app_id": None},
    {"observation.perm_checks": "unknown"},
    {"observation.install_repos_exact": False},
    {"observation.installation_account_match": False},
    {"observation.source": "github-rest-repository"},
    {"app_name": "other-app"},
])
def test_app_completed_records_never_infer_success(layout, corrupt):
    app_tracked(layout)
    state.verify("create-app", directory=layout[1],
                 runner=Mock(side_effect=app_proof_responses()), clock=lambda: 1020)
    path = layout[1] / "create-app.json"
    record = json.loads(path.read_text())
    for key, value in corrupt.items():
        if key.startswith("observation."):
            record["observation"][key.split(".")[1]] = value
        else:
            record[key] = value
    path.write_text(json.dumps(record))
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.status("create-app", directory=layout[1])
    with pytest.raises(tasks.BrowserTaskError, match="proof"):
        state.verify("create-app", directory=layout[1], runner=Mock(side_effect=AssertionError()))


def not_matched_response():
    return result({"full_name": "alice/project", "has_pull_requests": True,
                   "pull_request_creation_policy": "all"})


def test_app_completion_driven_by_exact_repo_list_not_selection_flag(layout):
    # A selection of "all" with a single-repo visible list is the same end
    # state; the proof is the exact user-visible repository list, and the
    # selection flag is recorded but never required.
    app_tracked(layout)
    runner = Mock(side_effect=[result(app_payload()),
                               result(installations_payload(repository_selection="all")),
                               result(["alice/project"]), result()])
    payload, rc = state.verify("create-app", directory=layout[1], runner=runner, clock=lambda: 1020)
    assert rc == 0 and payload["completed"]
    assert payload["observation"]["repository_selection"] == "all"
    assert payload["observation"]["install_repos_exact"] is True


def test_poll_dry_run_is_a_pure_plan(layout):
    tracked(layout)
    root, directory = layout
    before = (directory / "restrict-prs.json").read_bytes()
    runner = Mock(side_effect=AssertionError("plan executed a readback"))
    payload, rc = state.poll("restrict-prs", directory=directory, interval_seconds=30,
                             max_wait_seconds=120, dry_run=True, runner=runner, clock=lambda: 1000)
    assert rc == 0 and payload["status"] == "dry-run" and payload["completed"] is False
    assert payload["record_state"] == "pending" and payload["deadline_in_seconds"] == 60
    assert payload["planned_polls_upper_bound"] == 4
    assert payload["verify_argv"][-1] == "repos/alice/project"
    runner.assert_not_called()
    assert (directory / "restrict-prs.json").read_bytes() == before
    assert not list(directory.glob("*.lock"))


def test_poll_stops_on_first_completion_without_sleeping(layout):
    tracked(layout)
    sleeps: list[float] = []
    runner = Mock(side_effect=[result(proof()), result()])
    payload, rc = state.poll("restrict-prs", directory=layout[1], runner=runner,
                             clock=lambda: 1005, sleeper=sleeps.append)
    assert rc == 0 and payload["completed"] and payload["state"] == "completed"
    assert payload["polls"] == 1 and payload["poll_stopped"] == "completed" and sleeps == []


def test_poll_repeats_verify_on_interval_until_completed(layout):
    tracked(layout)
    sleeps: list[float] = []
    runner = Mock(side_effect=[not_matched_response(), result(proof()), result()])
    payload, rc = state.poll("restrict-prs", directory=layout[1], interval_seconds=15,
                             max_wait_seconds=600, runner=runner,
                             clock=lambda: 1000 + 10 * len(sleeps), sleeper=sleeps.append)
    assert rc == 0 and payload["completed"] and payload["polls"] == 2
    assert payload["poll_stopped"] == "completed" and sleeps == [15]


def test_poll_respects_max_wait_and_reports_pending(layout):
    tracked(layout)
    sleeps: list[float] = []
    ticks = iter([1000, 1000, 1000, 1000, 1030, 1030, 1030, 1030])
    runner = Mock(side_effect=[not_matched_response(), not_matched_response(), not_matched_response()])
    payload, rc = state.poll("restrict-prs", directory=layout[1], interval_seconds=60,
                             max_wait_seconds=30, runner=runner,
                             clock=lambda: next(ticks), sleeper=sleeps.append)
    assert rc == 1 and payload["state"] == "pending" and not payload["completed"]
    assert payload["polls"] == 3 and payload["poll_stopped"] == "pending" and sleeps == [30]


def test_poll_stops_at_record_deadline_and_reports_expired(layout):
    tracked(layout)
    sleeps: list[float] = []
    ticks = iter([1000, 1000, 1000, 1000, 1060])
    runner = Mock(side_effect=[not_matched_response()])
    payload, rc = state.poll("restrict-prs", directory=layout[1], interval_seconds=60,
                             max_wait_seconds=600, runner=runner,
                             clock=lambda: next(ticks), sleeper=sleeps.append)
    assert rc == 1 and payload["state"] == "expired" and not payload["completed"]
    assert payload["polls"] == 2 and payload["poll_stopped"] == "expired" and sleeps == [60]
    runner.assert_called_once()  # the expiry pass never reaches the API


@pytest.mark.parametrize("kwargs", [
    {"interval_seconds": 4}, {"interval_seconds": 3601}, {"interval_seconds": True},
    {"max_wait_seconds": 0}, {"max_wait_seconds": 86401}, {"max_wait_seconds": False},
])
def test_poll_bounds_validated_before_any_read(layout, kwargs, monkeypatch):
    tracked(layout)
    read = Mock(side_effect=AssertionError("bounds checked after record read"))
    monkeypatch.setattr(state, "_read", read)
    with pytest.raises(tasks.BrowserTaskError):
        state.poll("restrict-prs", directory=layout[1], dry_run=True, **kwargs)
    read.assert_not_called()


def test_cold_cli_poll_dry_run_creates_no_bytecode_or_changes(layout, tmp_path):
    root, directory = layout
    (root / "bin").mkdir()
    for name in ("ade-browser-task", "ade_browser_task.py", "ade_browser_task_state.py"):
        shutil.copyfile(REPO / "bin" / name, root / "bin" / name)
    home = tmp_path / "home"
    home.mkdir()
    cli = [sys.executable, "-I", str(root / "bin/ade-browser-task")]
    env = {**os.environ, "HOME": str(home), "PATH": ""}

    def run(*args):
        return subprocess.run(cli + list(args) + ["--state-dir", str(directory), "--json"],
                              env=env, capture_output=True, text=True, timeout=10)

    proc = run("track", "pr-access", "--name", "restrict-prs", "--deadline-seconds", "60",
               "--notify-owner", "agent-123", "--owner", "alice", "--repo", "project", "--yes")
    assert proc.returncode == 1, proc.stderr  # deadline binary missing: registration unknown
    assert json.loads(proc.stdout)["monitoring"] == "registration-unknown"
    after_track = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    proc = run("poll", "restrict-prs", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "dry-run" and payload["record_state"] == "pending"
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == after_track
    assert list(home.iterdir()) == []
