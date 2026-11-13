"""Offline tests for bin/ade-worker-run: a stub `paseo` records argv and env; nothing contacts a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/ade-worker-run"
LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61"
OTHER_LEAD = "11111111-2222-3333-4444-555555555555"
AGENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
WIN = f"workers djbclark-ade Wave 7 {LEAD}"
STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
data_path = Path(os.environ["FAKE_DATA"])
d = json.loads(data_path.read_text())
a = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"argv": a, "env": {k: os.environ.get(k) for k in ("PASEO_AGENT_ID", "PASEO_AGENT_CWD", "PASEO_WORKSPACE_ID")}}) + "\\n")
def save():
    data_path.write_text(json.dumps(d))
if a[:3] == ["workspace", "ls", "--json"]:
    print(json.dumps(d["workspaces"]))
elif a[:2] == ["workspace", "rename"]:
    for w in d["workspaces"]:
        if w["workspaceId"] == a[2]:
            w["name"] = a[3]
    save()
elif a[:2] == ["workspace", "archive"]:
    pass
elif a[:2] == ["agent", "update"]:
    pass
elif a[0] == "run":
    if "--new-workspace" in a:
        d["workspaces"].append({"workspaceId": d["created_id"], "name": "master", "cwd": a[a.index("--cwd") + 1]})
        save()
    sys.stderr.write(d.get("run_err", ""))
    print(json.dumps(d["run_out"]))
    sys.exit(d.get("run_rc", 0))
elif a[0] == "ls":
    rows = d["agents"]
    if "-a" not in a:
        rows = [r for r in rows if not r.get("archived")]
    if "--label" in a:
        k, v = a[a.index("--label") + 1].split("=", 1)
        rows = [r for r in rows if r.get("labels", {}).get(k) == v]
    print(json.dumps([{"id": r["id"], "status": r["status"]} for r in rows]))
else:
    sys.exit(9)
'''


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.data_path = tmp_path / "data.json"
        self.calls_path = tmp_path / "calls.jsonl"
        self.home = tmp_path / "paseo-home"
        self.data = {"workspaces": [], "created_id": "wks_abc123", "agents": [],
                     "run_out": {"agentId": AGENT, "status": "running"},
                     "run_err": "Created workspace wks_abc123 - master (master)\nTip: pass --workspace <id>\n"}
        stub = tmp_path / "bin/paseo"
        stub.parent.mkdir()
        stub.write_text(STUB)
        stub.chmod(0o755)
        monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_DATA", str(self.data_path))
        monkeypatch.setenv("FAKE_CALLS", str(self.calls_path))
        monkeypatch.setenv("PASEO_HOME", str(self.home))
        monkeypatch.setenv("ADE_WORKER_RUN_STATE", str(tmp_path / "state"))
        monkeypatch.setenv("PASEO_AGENT_ID", "ambient-agent")
        monkeypatch.setenv("PASEO_AGENT_CWD", "/ambient/cwd")
        monkeypatch.setenv("PASEO_WORKSPACE_ID", "wks_ambient")
        self.flush()

    def flush(self):
        self.data_path.write_text(json.dumps(self.data))

    def state(self, agent_id, workspace_id, labels=None):
        p = self.home / "agents/proj" / f"{agent_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"id": agent_id, "workspaceId": workspace_id, "labels": labels or {}}))

    def run(self, *args):
        self.flush()
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def calls(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(x) for x in self.calls_path.read_text().splitlines()]

    def verbs(self):
        return [c["argv"][:2] if c["argv"][0] in ("workspace", "agent") else c["argv"][:1] for c in self.calls()]


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def launch(env, slice_name="alpha", *extra):
    return env.run("--lead", LEAD, "--slice", slice_name, "--window-middle", "djbclark-ade Wave 7", "--cwd", "/repo",
                   *extra, "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF TEXT")


def test_first_launch_creates_and_renames(env):
    r = launch(env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"agentId": AGENT, "workspaceId": "wks_abc123", "windowName": WIN,
                                    "tabName": f"worker alpha {LEAD}"}
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert run[run.index("--new-workspace") + 1] == "local" and "--workspace" not in run
    assert run[run.index("--cwd") + 1] == os.path.realpath("/repo")
    assert run[-1] == "BRIEF TEXT" and "--provider" in run
    assert env.verbs() == [["workspace", "ls"], ["run"], ["workspace", "rename"], ["agent", "update"]]
    rename = next(c["argv"] for c in env.calls() if c["argv"][:2] == ["workspace", "rename"])
    assert rename == ["workspace", "rename", "wks_abc123", WIN]
    update = next(c["argv"] for c in env.calls() if c["argv"][:2] == ["agent", "update"])
    assert update == ["agent", "update", AGENT, "--name", f"worker alpha {LEAD}"]


def test_second_launch_reuses_the_window(env):
    assert launch(env).returncode == 0
    env.calls_path.unlink()
    env.data = json.loads(env.data_path.read_text())  # the stub renamed the window
    r = launch(env, "beta")
    assert r.returncode == 0, r.stderr
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert run[run.index("--workspace") + 1] == "wks_abc123" and "--new-workspace" not in run
    assert ["workspace", "rename"] not in env.verbs()
    assert json.loads(r.stdout)["tabName"] == f"worker beta {LEAD}"


def test_two_matching_windows_refuse(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a1", "name": WIN, "cwd": "/repo"},
                              {"workspaceId": "wks_b2", "name": WIN, "cwd": "/repo"}]
    r = launch(env)
    assert r.returncode == 1 and "wks_a1" in r.stderr and "wks_b2" in r.stderr
    assert ["run"] not in env.verbs()


def test_window_match_is_exact_not_substring(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a1", "name": f"old {WIN} extra", "cwd": "/repo"},
                              {"workspaceId": "wks_b2", "name": f"workers other {OTHER_LEAD}", "cwd": "/repo"}]
    assert launch(env).returncode == 0
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert "--new-workspace" in run  # neither row is this lead's window


def test_missing_created_line_fails_closed(env):
    env.data["run_err"] = "Tip: pass --workspace <id>\n"
    r = launch(env)
    assert r.returncode == 1 and AGENT in r.stderr and "no created workspace" in r.stderr
    assert ["workspace", "rename"] not in env.verbs() and ["agent", "update"] not in env.verbs()


def test_ambiguous_created_lines_fail_closed(env):
    env.data["run_err"] += "Created workspace wks_zzz999 - other\n"
    r = launch(env)
    assert r.returncode == 1 and "ambiguous" in r.stderr
    assert ["workspace", "rename"] not in env.verbs()


def test_json_workspace_id_conflicting_with_the_line_fails(env):
    env.data["run_out"]["workspaceId"] = "wks_other77"
    r = launch(env)
    assert r.returncode == 1 and "ambiguous" in r.stderr


def test_state_file_conflict_fails(env):
    env.state(AGENT, "wks_different")
    r = launch(env)
    assert r.returncode == 1 and "ambiguous" in r.stderr


def test_state_file_agreeing_passes(env):
    env.state(AGENT, "wks_abc123")
    assert launch(env).returncode == 0


def test_env_stripped_on_every_call(env):
    assert launch(env).returncode == 0
    assert env.calls()
    for c in env.calls():
        assert c["env"] == {"PASEO_AGENT_ID": None, "PASEO_AGENT_CWD": None, "PASEO_WORKSPACE_ID": None}


def test_labels_present(env):
    assert launch(env).returncode == 0
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    labels = [run[i + 1] for i, x in enumerate(run) if x == "--label"]
    assert labels == [f"ade.lead={LEAD}", "slice=alpha"]


@pytest.mark.parametrize("bad", [["--workspace", "wks_x"], ["--new-workspace", "local"], ["--cwd", "/x"],
                                 ["--label", "ade.lead=other"], ["--label=slice=zzz"], ["-C", "/x"],
                                 ["--dir", "/x"], ["--new-workspace=local"], ["--host", "h:1"], ["--home", "/h"],
                                 ["-q"], ["--format", "json"], ["-o", "json"]])
def test_owned_flags_refused(env, bad):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", *bad, "BRIEF")
    assert r.returncode == 1 and "set by ade-worker-run" in r.stderr
    assert not env.calls()


@pytest.mark.parametrize("args", [["--lead", "short", "--slice", "a"], ["--lead", LEAD, "--slice", "bad name"],
                                  ["--lead", LEAD, "--slice", "a", "--window-middle", "x" * 60]])
def test_bad_names_refused(env, args):
    r = env.run(*args, "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and not env.calls()


def test_run_failure_surfaces(env):
    env.data["run_rc"] = 1
    r = launch(env)
    assert r.returncode == 1 and "paseo run failed" in r.stderr
    assert ["workspace", "rename"] not in env.verbs()


def archive(env, *extra):
    return env.run("archive-window", "--lead", LEAD, *extra)


@pytest.fixture
def window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    return env


def test_archive_refuses_with_running_labelled_agent(window):
    window.data["agents"] = [{"id": "w1", "status": "running", "labels": {"ade.lead": LEAD}}]
    window.state("w1", "wks_win1", {"ade.lead": LEAD})
    r = archive(window)
    assert r.returncode == 1 and "w1" in r.stderr
    assert json.loads(r.stdout)["archived"] is False
    assert ["workspace", "archive"] not in window.verbs()


def test_archive_refuses_other_live_agent_in_window_even_when_idle_handled(window):
    window.data["agents"] = [{"id": "x1", "status": "idle", "labels": {}}]
    window.state("x1", "wks_win1")
    r = archive(window, "--idle-handled")
    assert r.returncode == 1 and "other live agent" in r.stderr
    assert ["workspace", "archive"] not in window.verbs()


def test_archive_idle_labelled_needs_the_flag(window):
    window.data["agents"] = [{"id": "w1", "status": "idle", "labels": {"ade.lead": LEAD}}]
    window.state("w1", "wks_win1", {"ade.lead": LEAD})
    assert archive(window).returncode == 1
    assert ["workspace", "archive"] not in window.verbs()
    r = archive(window, "--idle-handled")
    assert r.returncode == 0, r.stderr
    archived = next(c["argv"] for c in window.calls() if c["argv"][:2] == ["workspace", "archive"])
    assert archived == ["workspace", "archive", "wks_win1"]


def test_archive_ignores_agents_in_other_windows_and_closed_ones(window):
    window.data["agents"] = [{"id": "c1", "status": "closed", "labels": {"ade.lead": LEAD}},
                             {"id": "o1", "status": "running", "labels": {}},
                             {"id": "o2", "status": "idle", "labels": {"ade.lead": OTHER_LEAD}}]
    window.state("c1", "wks_win1", {"ade.lead": LEAD})
    window.state("o1", "wks_elsewhere")
    window.state("o2", "wks_win1", {"ade.lead": OTHER_LEAD})  # another lead's agent inside this window
    r = archive(window)
    assert r.returncode == 1 and "o2" in r.stderr and "o1" not in r.stderr
    window.data["agents"] = window.data["agents"][:2]
    r = archive(window)
    assert r.returncode == 0, r.stderr
    assert ["workspace", "archive"] in window.verbs()


def test_archive_unplaceable_live_agent_blocks(window):
    window.data["agents"] = [{"id": "ghost", "status": "running", "labels": {}}]
    r = archive(window)
    assert r.returncode == 1 and "no usable workspaceId" in r.stderr


def test_archive_refuses_ambiguous_and_missing_window(env):
    assert archive(env).returncode == 1 and "no workers window" in archive(env).stderr
    env.data["workspaces"] = [{"workspaceId": "wks_a1", "name": WIN}, {"workspaceId": "wks_b2", "name": WIN}]
    r = archive(env)
    assert r.returncode == 1 and "wks_a1" in r.stderr
    assert ["workspace", "archive"] not in env.verbs()


def test_archive_dry_run_archives_nothing(window):
    r = archive(window, "--dry-run")
    assert r.returncode == 0 and json.loads(r.stdout)["archived"] is False
    assert ["workspace", "archive"] not in window.verbs()


@pytest.mark.parametrize("rest", [["paseo", "run", "--no-wait", "BRIEF"], ["run", "--no-wait", "BRIEF"],
                                  ["paseo run --provider x --no-wait", "--no-wait", "BRIEF"]])
def test_leading_paseo_run_refused(env, rest):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", *rest)
    assert r.returncode == 1 and "leading `paseo run`" in r.stderr and not env.calls()


def test_foreground_run_refused(env):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--provider", "claude/sonnet", "BRIEF")
    assert r.returncode == 1 and "--no-wait" in r.stderr and not env.calls()


def test_non_uuid_agent_id_refused(env):
    env.data["run_out"]["agentId"] = "--evil"
    r = launch(env)
    assert r.returncode == 1 and "unusable agentId" in r.stderr
    assert ["workspace", "rename"] not in env.verbs()


def test_no_middle_never_picks_another_leads_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"workers x {OTHER_LEAD}", "cwd": "/repo"}]
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert "--new-workspace" in run and "wks_o1" not in run
    assert json.loads(r.stdout)["windowName"] == f"workers repo {LEAD}"


def test_no_middle_reuses_own_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"workers x {OTHER_LEAD}", "cwd": "/repo"},
                              {"workspaceId": "wks_me", "name": WIN, "cwd": "/repo"}]
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert run[run.index("--workspace") + 1] == "wks_me"
    assert run[run.index("--cwd") + 1] == "/repo"  # the window's own cwd, and no middle validation on reuse


def test_changed_middle_refuses_a_second_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_me", "name": WIN, "cwd": "/repo"}]
    r = env.run("--lead", LEAD, "--slice", "alpha", "--window-middle", "Typo", "--cwd", "/repo", "--", "--no-wait", "B")
    assert r.returncode == 1 and "wks_me" in r.stderr and "second window" in r.stderr
    assert ["run"] not in env.verbs()


def test_archive_no_middle_ignores_another_leads_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"workers x {OTHER_LEAD}", "cwd": "/repo"}]
    r = archive(env)
    assert r.returncode == 1 and "no workers window" in r.stderr
    assert ["workspace", "archive"] not in env.verbs()


def test_archive_ignores_archived_agents(window):
    window.data["agents"] = [{"id": "z1", "status": "idle", "archived": True, "labels": {"ade.lead": LEAD}}]
    window.state("z1", "wks_win1", {"ade.lead": LEAD})
    r = archive(window)
    assert r.returncode == 0, r.stderr


def test_archive_state_file_without_workspace_id_blocks(window):
    window.data["agents"] = [{"id": "n1", "status": "idle", "labels": {}}]
    p = window.home / "agents/proj/n1.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": "n1"}))
    r = archive(window)
    assert r.returncode == 1 and "n1" in r.stderr


def test_archive_waits_for_the_lead_lock(window):
    import fcntl
    import threading
    lock_dir = Path(os.environ["ADE_WORKER_RUN_STATE"])
    lock_dir.mkdir(parents=True, exist_ok=True)
    fh = (lock_dir / f"{LEAD}.lock").open("a")
    fcntl.flock(fh, fcntl.LOCK_EX)
    window.flush()
    proc = subprocess.Popen([sys.executable, str(SCRIPT), "archive-window", "--lead", LEAD],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t = threading.Timer(1.5, fh.close)
    t.start()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=1.0)
        assert not window.calls()  # no paseo call before the lock is free
        assert proc.wait(timeout=20) == 0
    finally:
        t.cancel()
        proc.kill()
        proc.communicate()


@pytest.mark.parametrize("existing", [False, True])
def test_launch_waits_for_the_lead_lock(env, existing):
    import fcntl
    import threading
    if existing:
        env.data["workspaces"] = [{"workspaceId": "wks_me", "name": WIN, "cwd": "/repo"}]
    lock_dir = Path(os.environ["ADE_WORKER_RUN_STATE"])
    lock_dir.mkdir(parents=True, exist_ok=True)
    fh = (lock_dir / f"{LEAD}.lock").open("a")
    fcntl.flock(fh, fcntl.LOCK_EX)
    env.flush()
    proc = subprocess.Popen([sys.executable, str(SCRIPT), "--lead", LEAD, "--slice", "alpha", "--window-middle",
                             "djbclark-ade Wave 7", "--cwd", "/repo", "--", "--no-wait", "BRIEF"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t = threading.Timer(1.5, fh.close)
    t.start()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=1.0)
        assert not env.calls()
        assert proc.wait(timeout=20) == 0
    finally:
        t.cancel()
        proc.kill()
        proc.communicate()
