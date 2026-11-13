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
WIN = "WORKERS repo (Wave 7)"  # the stub runs with --cwd /repo (not a git repo): its repo name is the basename `repo`
LEGACY_WIN = f"workers repo Wave 7 {LEAD}"
LEAD_WKS = "wks_lead01"
FOOTER_LINE = f"Also follow every item of {ROOT}/docs/dispatch-footer.md."
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
        monkeypatch.setenv("PASEO_AGENT_ID", LEAD)
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
    return env.run("--lead", LEAD, "--slice", slice_name, "--window-middle", "Wave 7", "--cwd", "/repo",
                   *extra, "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF TEXT")


def test_first_launch_creates_and_renames(env):
    r = launch(env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"agentId": AGENT, "workspaceId": "wks_abc123", "windowName": WIN,
                                    "tabName": f"worker alpha {LEAD}"}
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert run[run.index("--new-workspace") + 1] == "local" and "--workspace" not in run
    assert run[run.index("--cwd") + 1] == os.path.realpath("/repo")
    assert run[-1] == f"BRIEF TEXT\n\n{FOOTER_LINE}" and "--provider" in run
    assert env.verbs() == [["ls"], ["workspace", "ls"], ["run"], ["workspace", "rename"], ["agent", "update"]]
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
                              {"workspaceId": "wks_b2", "name": f"WORKERS other {OTHER_LEAD}", "cwd": "/repo"}]
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
                                 ["-q"], ["--format", "json"], ["-o", "json"], ["-oyaml"], ["-qd"]])
def test_owned_flags_refused(env, bad):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", *bad, "BRIEF")
    assert r.returncode == 1 and ("set by ade-worker-run" in r.stderr or "bundled" in r.stderr)
    assert not env.calls()


@pytest.mark.parametrize("args", [["--lead", "short", "--slice", "a"], ["--lead", LEAD, "--slice", "bad name"],
                                  ["--lead", LEAD, "--slice", "a", "--window-middle", "x" * 100, "--cwd", "/repo"],
                                  ["--lead", LEAD, "--slice", "a", "--window-middle", " padded", "--cwd", "/repo"],
                                  ["--lead", LEAD, "--slice", "a", "--window-middle", "W", "--repo", "bad repo"]])
def test_bad_names_refused(env, args):
    r = env.run(*args, "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and not env.calls()


def test_run_failure_surfaces(env):
    env.data["run_rc"] = 1
    r = launch(env)
    assert r.returncode == 1 and "paseo run failed" in r.stderr
    assert ["workspace", "rename"] not in env.verbs()


def archive(env, *extra):
    return env.run("archive-window", "--lead", LEAD, "--window-middle", "Wave 7", *extra)


def own(lead, *wks_ids):
    """The helper's window record for `lead` (it is written when the helper mints, migrates or adopts a window)."""
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lead}.windows.json").write_text(json.dumps({"windows": list(wks_ids)}))


def registry(lead):
    p = Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{lead}.windows.json"
    return set(json.loads(p.read_text())["windows"]) if p.exists() else set()


@pytest.fixture
def window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_win1")
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
    assert r.returncode == 1 and ("leading `paseo run`" in r.stderr or "first argument" in r.stderr)
    assert not env.calls()


def test_foreground_run_refused(env):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--provider", "claude/sonnet", "BRIEF")
    assert r.returncode == 1 and "--no-wait" in r.stderr and not env.calls()


def test_non_uuid_agent_id_refused(env):
    env.data["run_out"]["agentId"] = "--evil"
    r = launch(env)
    assert r.returncode == 1 and "unusable agentId" in r.stderr
    assert ["workspace", "rename"] not in env.verbs()


def test_other_leads_window_is_never_picked_without_a_middle(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": "WORKERS repo (Wave 7)", "cwd": "/repo"}]
    env.data["agents"] = [{"id": "o9", "status": "running", "labels": {"ade.lead": OTHER_LEAD}}]
    env.state("o9", "wks_o1", {"ade.lead": OTHER_LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "--window-middle" in r.stderr and ["run"] not in env.verbs()


def test_no_middle_reuses_the_window_holding_the_leads_labelled_agent(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": "WORKERS repo (Other)", "cwd": "/repo"},
                              {"workspaceId": "wks_me", "name": WIN, "cwd": "/repo/lead"}]
    env.data["agents"] = [{"id": "w1", "status": "running", "labels": {"ade.lead": LEAD}}]
    env.state("w1", "wks_me", {"ade.lead": LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = run_argv(env)
    assert run[run.index("--workspace") + 1] == "wks_me"
    assert run[run.index("--cwd") + 1] == "/repo/lead"  # the window's own cwd


def test_changed_middle_refuses_a_second_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_me", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": "w1", "status": "running", "labels": {"ade.lead": LEAD}}]
    env.state("w1", "wks_me", {"ade.lead": LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--window-middle", "Typo", "--cwd", "/repo", "--", "--no-wait", "B")
    assert r.returncode == 1 and "wks_me" in r.stderr and "second window" in r.stderr
    assert ["run"] not in env.verbs()


def test_archive_no_middle_ignores_another_leads_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"WORKERS x {OTHER_LEAD}", "cwd": "/repo"}]
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
    proc = subprocess.Popen([sys.executable, str(SCRIPT), "archive-window", "--lead", LEAD, "--window-middle", "Wave 7"],
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
                             "Wave 7", "--cwd", "/repo", "--", "--no-wait", "BRIEF"],
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


def test_lead_that_is_not_the_caller_refused(env, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", OTHER_LEAD)
    r = launch(env)
    assert r.returncode == 1 and "not this agent" in r.stderr and not env.calls()
    r = archive(env, "--idle-handled")
    assert r.returncode == 1 and "not this agent" in r.stderr and not env.calls()


def test_on_behalf_of_lead_allows_it(env, monkeypatch):
    # the stub renames the minted window, so the archive below finds it
    monkeypatch.setenv("PASEO_AGENT_ID", OTHER_LEAD)
    r = launch(env, "alpha", "--on-behalf-of-lead")  # mints the window
    assert r.returncode == 0
    run = next(c["argv"] for c in env.calls() if c["argv"][0] == "run")
    assert [run[i + 1] for i, x in enumerate(run) if x == "--label"] == [f"ade.lead={LEAD}", "slice=alpha"]
    assert json.loads(r.stdout)["tabName"] == f"worker alpha {LEAD}"
    env.data = json.loads(env.data_path.read_text())  # keep the stub's rename
    assert archive(env, "--on-behalf-of-lead", "--dry-run").returncode == 0


def test_no_caller_agent_id_needs_no_flag(env, monkeypatch):
    monkeypatch.delenv("PASEO_AGENT_ID")
    assert launch(env).returncode == 0


# --- 2026-11-13 naming ruling: `<KIND> <repo> (<work>)`, lead id out of window names, legacy migration, MAIN placement -------

def rename_calls(env):
    return [c["argv"] for c in env.calls() if c["argv"][:2] == ["workspace", "rename"]]


def run_argv(env):
    return next(c["argv"] for c in env.calls() if c["argv"][0] == "run")


def member(env, agent, wks, lead=LEAD, status="running"):
    env.data.setdefault("agents", []).append({"id": agent, "status": status, "labels": {"ade.lead": lead}})
    env.state(agent, wks, {"ade.lead": lead})


def test_new_window_is_minted_in_the_kind_repo_work_form(env):
    assert launch(env).returncode == 0
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", "WORKERS repo (Wave 7)"]]
    assert LEAD not in rename_calls(env)[0][3]  # the lead id lives in the tab name and the label, not the window name


def test_explicit_repo_wins_over_the_cwd(env):
    assert launch(env, "alpha", "--repo", "djbclark-ade").returncode == 0
    assert rename_calls(env)[0][3] == "WORKERS djbclark-ade (Wave 7)"


def test_repo_comes_from_the_main_checkout_even_in_a_linked_worktree(env, tmp_path):
    main = tmp_path / "my-repo"
    main.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(main), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path / "my-repo-feature-wt"
    git("worktree", "add", "-q", "-b", "feature", str(wt))
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", str(wt), "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr
    assert rename_calls(env)[0][3] == "WORKERS my-repo (Wave 7)"


def test_first_launch_without_a_middle_refuses(env):
    r = env.run("--lead", LEAD, "--slice", "a", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "--window-middle" in r.stderr and ["run"] not in env.verbs()


@pytest.mark.parametrize("legacy", [f"workers repo Wave 7 {LEAD}", f"WORKERS repo Wave 7 {LEAD}",
                                    f"workers Wave 7 {LEAD}"])
def test_legacy_window_matched_and_renamed_before_launch(env, legacy):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": legacy, "cwd": "/repo"}]
    r = launch(env, "beta")
    assert r.returncode == 0, r.stderr
    assert env.verbs() == [["ls"], ["workspace", "ls"], ["workspace", "ls"], ["workspace", "rename"], ["run"], ["agent", "update"]]  # rename first (2nd ls: name-free check)
    assert rename_calls(env) == [["workspace", "rename", "wks_old1", WIN]]  # `repo ` prefix of the middle is folded into KIND repo
    run = run_argv(env)
    assert run[run.index("--workspace") + 1] == "wks_old1" and "--new-workspace" not in run
    out = json.loads(r.stdout)
    assert out["windowName"] == WIN and out["workspaceId"] == "wks_old1"


def test_legacy_window_matched_without_a_middle_too(env):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": LEGACY_WIN, "cwd": "/repo"}]
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    assert rename_calls(env) == [["workspace", "rename", "wks_old1", WIN]]


def test_another_leads_legacy_window_is_left_alone(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"workers repo Wave 7 {OTHER_LEAD}", "cwd": "/repo"}]
    assert launch(env).returncode == 0
    assert "--new-workspace" in run_argv(env) and all(a[2] != "wks_o1" for a in rename_calls(env))


def test_current_name_window_is_not_renamed(window):
    member(window, "w1", "wks_win1")
    assert launch(window).returncode == 0
    assert rename_calls(window) == []


def test_legacy_and_current_window_of_the_same_work_refuse(env):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": LEGACY_WIN, "cwd": "/repo"},
                              {"workspaceId": "wks_new1", "name": WIN, "cwd": "/repo"}]
    r = launch(env)
    assert r.returncode == 1 and "wks_old1" in r.stderr and "wks_new1" in r.stderr
    assert ["run"] not in env.verbs() and rename_calls(env) == []


def test_window_holding_another_leads_labelled_agent_is_refused(window):
    member(window, "o9", "wks_win1", lead=OTHER_LEAD)
    r = launch(window)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and "o9" in r.stderr
    assert ["run"] not in window.verbs()


def test_window_holding_only_another_leads_closed_agent_is_refused(env):
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    member(env, "o9", "wks_b1", lead=OTHER_LEAD, status="closed")
    r = launch(env)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and ["run"] not in env.verbs()  # F3
    assert registry(LEAD) == set()


def test_window_registered_to_another_lead_is_refused_for_launch_and_archive(env):
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    own(OTHER_LEAD, "wks_b1")
    for r in (launch(env), archive(env)):
        assert r.returncode == 1 and "registered to lead" in r.stderr
    assert ["run"] not in env.verbs() and ["workspace", "archive"] not in env.verbs()


def test_archive_refuses_a_same_named_window_nothing_shows_is_ours(env):  # F1
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    r = archive(env)
    assert r.returncode == 1 and "never confers ownership" in r.stderr and ["workspace", "archive"] not in env.verbs()
    r = env.run("archive-window", "--lead", LEAD, "--window-middle", "Wave 7", "--repo", "other")
    assert r.returncode == 1 and ["workspace", "archive"] not in env.verbs()
    member(env, "o9", "wks_b1", lead=OTHER_LEAD, status="closed")  # another lead's closed worker: foreign, refused
    r = archive(env)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and ["workspace", "archive"] not in env.verbs()


def test_launch_adopts_an_unclaimed_same_named_window_and_records_it(env):
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    assert launch(env).returncode == 0
    assert registry(LEAD) == {"wks_u1"}
    assert archive(env).returncode == 0  # now provably ours


def test_minting_records_the_window_and_archive_unrecords_it(env):
    assert launch(env).returncode == 0
    assert registry(LEAD) == {"wks_abc123"}
    env.data = json.loads(env.data_path.read_text())
    assert archive(env).returncode == 0
    assert registry(LEAD) == set()


def test_unreadable_window_record_fails_closed(window):
    (Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json").write_text("not json")
    r = launch(window)
    assert r.returncode == 1 and "unreadable" in r.stderr and ["run"] not in window.verbs()


def test_legacy_migration_refuses_when_the_new_name_is_taken(env):  # F2
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": LEGACY_WIN, "cwd": "/repo"},
                              {"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    own(OTHER_LEAD, "wks_b1")
    r = env.run("--lead", LEAD, "--slice", "a", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "wks_old1" not in "".join(a for c in rename_calls(env) for a in c)
    assert ["run"] not in env.verbs()


def test_legacy_migration_records_ownership_even_if_the_launch_then_fails(env):  # F2 / probe S3
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": LEGACY_WIN, "cwd": "/repo"}]
    env.data["run_rc"] = 3
    assert launch(env).returncode == 1
    assert rename_calls(env) == [["workspace", "rename", "wks_old1", WIN]] and registry(LEAD) == {"wks_old1"}
    env.data = json.loads(env.data_path.read_text())
    env.data["run_rc"] = 0
    assert archive(env).returncode == 0  # still ours, found by the record, not by the vanished lead id


def test_an_unbuildable_legacy_name_does_not_block_other_calls(env):  # F8
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": f"workers a  b {LEAD}", "cwd": "/repo"},
                              {"workspaceId": "wks_new1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_new1")
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    assert archive(env).returncode == 0  # the archive path never builds the legacy name


@pytest.mark.parametrize("key", ["ade.lead ", " ade.lead", "ade.lead\t"])
def test_label_keys_with_whitespace_are_refused(env, key):  # F7
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", "--label", f"{key}={OTHER_LEAD}", "BRIEF")
    assert r.returncode == 1 and not env.calls()


@pytest.mark.parametrize("name", ["Workers repo (Wave 7)", "WORKERS repo Wave 7", "WORKERS repo (Wave 7) x",
                                  "MAIN repo (Wave 7)", "USER repo (Wave 7)", "WORKERS  repo (Wave 7)"])
def test_near_miss_names_are_not_matched(env, name):
    env.data["workspaces"] = [{"workspaceId": "wks_nm1", "name": name, "cwd": "/repo"}]
    assert launch(env).returncode == 0
    assert "--new-workspace" in run_argv(env) and all(a[2] != "wks_nm1" for a in rename_calls(env))


def test_archive_accepts_both_spellings_and_never_migrates(env):
    own(LEAD, "wks_w1")
    for name in (WIN, LEGACY_WIN):
        env.data["workspaces"] = [{"workspaceId": "wks_w1", "name": name, "cwd": "/repo"}]
        env.calls_path.unlink(missing_ok=True)
        r = archive(env)
        assert r.returncode == 0, r.stderr
        assert ["workspace", "archive", "wks_w1"] in [c["argv"] for c in env.calls()]
        assert rename_calls(env) == []


def test_archive_never_archives_main_or_user_windows(env):
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": "MAIN repo (Wave 7)"},
                              {"workspaceId": "wks_u1", "name": "USER repo (Wave 7)"}]
    member(env, "w1", LEAD_WKS, status="idle")  # even a window holding the lead's own labelled agent
    r = archive(env, "--idle-handled")
    assert r.returncode == 1 and "no workers window" in r.stderr
    assert ["workspace", "archive"] not in env.verbs()


def test_archive_finds_the_window_by_membership_without_a_middle(window):
    member(window, "w1", "wks_win1", status="idle")
    r = window.run("archive-window", "--lead", LEAD, "--idle-handled")
    assert r.returncode == 0, r.stderr
    assert ["workspace", "archive", "wks_win1"] in [c["argv"] for c in window.calls()]


def test_archive_without_a_middle_finds_an_emptied_window_by_the_record_only(window, env=None):
    r = window.run("archive-window", "--lead", LEAD)  # the window record (written at mint/migrate/adopt) proves it is ours
    assert r.returncode == 0, r.stderr
    (Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json").unlink()
    window.calls_path.unlink()
    r = window.run("archive-window", "--lead", LEAD)  # no record, no labelled agent: nothing to find it by
    assert r.returncode == 1 and "--window-middle" in r.stderr


def test_archive_ignores_a_main_placed_worker_in_the_main_window(window):
    window.data["workspaces"].append({"workspaceId": LEAD_WKS, "name": "MAIN repo (Wave 7)"})
    window.data["agents"] = [{"id": "m1", "status": "running", "labels": {"ade.lead": LEAD, "ade.placement": "main"}}]
    window.state("m1", LEAD_WKS, {"ade.lead": LEAD, "ade.placement": "main"})
    r = archive(window)
    assert r.returncode == 0, r.stderr
    assert ["workspace", "archive", "wks_win1"] in [c["argv"] for c in window.calls()]


def test_archive_still_blocks_on_a_main_labelled_agent_inside_the_workers_window(window):
    window.data["agents"] = [{"id": "m2", "status": "running", "labels": {"ade.lead": LEAD, "ade.placement": "main"}}]
    window.state("m2", "wks_win1", {"ade.lead": LEAD, "ade.placement": "main"})
    r = archive(window)
    assert r.returncode == 1 and "m2" in r.stderr


@pytest.fixture
def main_env(env):
    env.state(LEAD, LEAD_WKS)
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": "MAIN repo (Wave 7)", "cwd": "/repo/lead"}]
    env.data["run_err"] = ""
    return env


def interactive(env, *extra, slice_name="op1"):
    return env.run("--lead", LEAD, "--slice", slice_name, *extra, "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF")


@pytest.mark.parametrize("flag", [["--placement", "main"], ["--interactive"]])
def test_main_placement_launches_into_the_leads_window(main_env, flag):
    r = interactive(main_env, *flag)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"agentId": AGENT, "workspaceId": LEAD_WKS, "windowName": "MAIN repo (Wave 7)",
                                    "tabName": f"worker op1 {LEAD}"}
    run = run_argv(main_env)
    assert run[run.index("--workspace") + 1] == LEAD_WKS and "--new-workspace" not in run
    assert run[run.index("--cwd") + 1] == "/repo/lead"
    assert [run[i + 1] for i, x in enumerate(run) if x == "--label"] == [f"ade.lead={LEAD}", "slice=op1", "ade.placement=main"]
    assert rename_calls(main_env) == []  # an already-MAIN window is not renamed by a launch
    assert all(c["env"]["PASEO_WORKSPACE_ID"] is None for c in main_env.calls())
    assert ["agent", "update", AGENT, "--name", f"worker op1 {LEAD}"] in [c["argv"] for c in main_env.calls()]


def test_main_placement_uses_the_agent_record_not_the_ambient_workspace_id(main_env, monkeypatch):
    monkeypatch.delenv("PASEO_WORKSPACE_ID")
    r = interactive(main_env, "--interactive")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["workspaceId"] == LEAD_WKS  # not the ambient wks_ambient


def test_main_placement_migrates_a_legacy_main_name_first(main_env):
    main_env.data["workspaces"][0]["name"] = "MAIN repo Wave 7"
    main_env.data["workspaces"][0]["cwd"] = "/repo"
    r = interactive(main_env, "--interactive", "--cwd", "/repo")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "MAIN repo (Wave 7)"]]
    assert main_env.verbs().index(["workspace", "rename"]) < main_env.verbs().index(["run"])
    assert json.loads(r.stdout)["windowName"] == "MAIN repo (Wave 7)"


@pytest.mark.parametrize("name", ["djbclark-ade Wave 7", "master", "MAINTAIN x", "Main x", "WORKERS repo (Wave 7)",
                                  "USER repo (Wave 7)", f"workers repo Wave 7 {LEAD}"])
def test_main_placement_refuses_a_window_that_is_not_main(main_env, name):
    main_env.data["workspaces"][0]["name"] = name
    r = interactive(main_env, "--interactive")
    assert r.returncode == 1 and ("rename-main" in r.stderr or "rename it by hand" in r.stderr)
    assert ["run"] not in main_env.verbs() and rename_calls(main_env) == []


def test_main_placement_needs_the_lead_to_be_the_caller(main_env, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", OTHER_LEAD)
    r = interactive(main_env, "--interactive", "--on-behalf-of-lead")
    assert r.returncode == 1 and "run it as the lead itself" in r.stderr and not main_env.calls()
    monkeypatch.delenv("PASEO_AGENT_ID")
    r = interactive(main_env, "--interactive")
    assert r.returncode == 1 and "run it as the lead itself" in r.stderr and not main_env.calls()


def test_main_placement_without_a_state_file_workspace_refuses(env):
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": "MAIN repo (x)", "cwd": "/repo"}]
    r = interactive(env, "--interactive")
    assert r.returncode == 1 and "own window is unknown" in r.stderr and ["run"] not in env.verbs()


def test_main_placement_window_missing_from_the_listing_refuses(main_env):
    main_env.data["workspaces"] = []
    r = interactive(main_env, "--interactive")
    assert r.returncode == 1 and "not in `paseo workspace ls" in r.stderr and ["run"] not in main_env.verbs()


def test_main_placement_refuses_window_middle(main_env):
    r = interactive(main_env, "--interactive", "--window-middle", "x")
    assert r.returncode == 1 and "--window-middle" in r.stderr and not main_env.calls()


def test_default_placement_still_uses_the_workers_window(main_env):
    main_env.data["run_err"] = "Created workspace wks_abc123 - master (master)\n"
    assert launch(main_env).returncode == 0
    assert "--new-workspace" in run_argv(main_env)


def test_ade_placement_label_is_owned(env):
    r = env.run("--lead", LEAD, "--slice", "alpha", "--", "--no-wait", "--label", "ade.placement=other", "BRIEF")
    assert r.returncode == 1 and "set by ade-worker-run" in r.stderr and not env.calls()


@pytest.mark.parametrize("old,new", [("djbclark-ade Wave 7", "MAIN repo (djbclark-ade Wave 7)"), ("repo Wave 7", "MAIN repo (Wave 7)"),
                                     ("master", "MAIN repo (master)"), ("MAIN repo Wave 7", "MAIN repo (Wave 7)")])
def test_rename_main_converts_the_name(main_env, old, new):
    main_env.data["workspaces"][0]["name"] = old
    r = main_env.run("rename-main", "--lead", LEAD, "--repo", "repo")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, new]] and json.loads(r.stdout)["renamed"] is True


def test_rename_main_is_a_noop_on_a_main_name_and_takes_an_explicit_work(main_env):
    r = main_env.run("rename-main", "--lead", LEAD)
    assert r.returncode == 0 and json.loads(r.stdout)["renamed"] is False and rename_calls(main_env) == []
    main_env.data["workspaces"][0]["name"] = "master"
    r = main_env.run("rename-main", "--lead", LEAD, "--window-middle", "Wave 8")  # repo from the window's cwd: lead
    assert r.returncode == 0 and rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "MAIN lead (Wave 8)"]]


@pytest.mark.parametrize("name", ["WORKERS repo (Wave 7)", "USER repo (Wave 7)", f"workers repo Wave 7 {LEAD}"])
def test_rename_main_refuses_a_workers_or_user_window(main_env, name):
    main_env.data["workspaces"][0]["name"] = name
    r = main_env.run("rename-main", "--lead", LEAD)
    assert r.returncode == 1 and rename_calls(main_env) == []


def test_rename_main_needs_the_lead_to_be_the_caller_and_a_short_name(main_env, monkeypatch):
    main_env.data["workspaces"][0]["name"] = "master"
    r = main_env.run("rename-main", "--lead", LEAD, "--window-middle", "x" * 100)
    assert r.returncode == 1 and "exceeds" in r.stderr and rename_calls(main_env) == []
    monkeypatch.setenv("PASEO_AGENT_ID", OTHER_LEAD)
    r = main_env.run("rename-main", "--lead", LEAD)
    assert r.returncode == 1 and "run it as the lead itself" in r.stderr


# --- delivery footer line (lead add-on, 2026-11-13) ----------------------------------------------------------------------

def test_footer_line_is_appended_to_the_brief_once(env):
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    assert run_argv(env)[-1] == f"BRIEF\n\n{FOOTER_LINE}"
    assert (ROOT / "docs/dispatch-footer.md").is_file() and str(ROOT) in FOOTER_LINE  # an absolute path from the repo root


def test_footer_not_doubled_when_the_brief_already_names_it(env):
    brief = f"BRIEF {ROOT}/docs/dispatch-footer.md"
    env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", "--no-wait", brief)
    assert run_argv(env)[-1] == brief


def test_no_footer_leaves_the_brief_alone(env):
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--no-footer", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0 and run_argv(env)[-1] == "BRIEF"


@pytest.mark.parametrize("rest", [["--no-wait"], ["--no-wait", "--provider", "claude/sonnet"], ["--no-wait", "-m", "x"]])
def test_footer_refuses_when_the_last_argument_is_not_the_brief(env, rest):
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", *rest)
    assert r.returncode == 1 and "brief" in r.stderr and not env.calls()


def test_interactive_legacy_main_migration_uses_the_windows_own_repo_not_the_callers_cwd(main_env):  # F4
    main_env.data["workspaces"][0].update(name="MAIN Wave 7", cwd="/somewhere/djbclark-ade")
    r = interactive(main_env, "--interactive", "--cwd", "/elsewhere/other-repo")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "MAIN djbclark-ade (Wave 7)"]]


@pytest.mark.parametrize("rest", [["--no-wait", "BRIEF", "--image", "/tmp/x.png"], ["--no-wait", "BRIEF", "--base", "main"],
                                  ["--no-wait", "--wait-timeout", "5"], ["BRIEF", "--no-wait"]])
def test_footer_refuses_a_trailing_value_flag_instead_of_corrupting_it(env, rest):  # F5
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", *rest)
    assert r.returncode == 1 and not env.calls()


@pytest.mark.parametrize("rest", [["--provider", "x", "--no-wait", "BRIEF"], ["--no-wait", "--provider", "x", "BRIEF"],
                                  ["--no-wait", "--mode=full-access", "BRIEF"], ["--json", "--no-wait", "BRIEF"]])
def test_footer_accepts_the_brief_after_flags_and_their_values(env, rest):
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", *rest)
    assert r.returncode == 0, r.stderr
    assert run_argv(env)[-1] == f"BRIEF\n\n{FOOTER_LINE}"
