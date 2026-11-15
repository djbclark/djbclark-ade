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
WIN = "WORKER repo (Wave 7)"  # the stub runs with --cwd /repo (not a git repo): its repo name is the basename `repo`
LEGACY_WIN = f"workers repo Wave 7 {LEAD}"
OTHER_WIN = "OTHER repo (other)"
LEAD_NAME = "LEAD repo (Wave 7)"  # the lead's own window in `main_env`
# bin/ade-worker-run bug (wb-01 report): a launch calls find_window with middle=None, which returns the lead's ONLY owned box
# even when it belongs to ANOTHER repo, so a launch for a second repo reuses (or, by the cwd check, is refused by) the first
# repo's window instead of opening its own, as the 2026-11-14 ruling says. These tests assert the ruling; remove the marker with the fix.
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
elif a[:2] == ["agent", "stop"]:
    sys.exit(d.get("stop_rc", 0))
elif a[:2] == ["agent", "inspect"]:
    if "inspect_cwd" not in d or d.get("inspect_rc"):
        sys.exit(d.get("inspect_rc") or 1)
    print(json.dumps({"Id": a[2], "Cwd": d["inspect_cwd"]}))
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
        monkeypatch.setenv("ADE_SELF_SESSION_STATE", str(tmp_path / "self-session"))
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

    def run(self, *args, cwd=None):
        self.flush()
        # a non-repo default directory: the suite may itself run from a linked worktree, where an implicit cwd is checked
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd or self.tmp)

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
    assert env.verbs() == [["ls"], ["workspace", "ls"], ["run"], ["workspace", "rename"], ["agent", "update"], ["agent", "inspect"]]
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
    own(LEAD, "wks_a1", "wks_b2")  # both are the lead's boxes: the pick (--window-middle Wave 7) cannot tell them apart
    r = launch(env)
    assert r.returncode == 1 and "wks_a1" in r.stderr and "wks_b2" in r.stderr and "2 windows match the lead's WORKER box" in r.stderr
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
    assert archive(env).returncode == 1 and "no WORKER box for lead" in archive(env).stderr
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
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": "o9", "status": "running", "labels": {"ade.lead": OTHER_LEAD}}]
    env.state("o9", "wks_o1", {"ade.lead": OTHER_LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr  # the stranger's window is not this lead's box: the lead opens its own
    run = run_argv(env)
    assert run[run.index("--new-workspace") + 1] == "local" and "--workspace" not in run
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", "WORKER repo (workers)"]]


def test_no_middle_reuses_the_window_holding_the_leads_labelled_agent(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": "WORKER repo (Other)", "cwd": "/repo"},
                              {"workspaceId": "wks_me", "name": WIN, "cwd": "/repo/lead"}]
    env.data["agents"] = [{"id": "w1", "status": "running", "labels": {"ade.lead": LEAD}}]
    env.state("w1", "wks_me", {"ade.lead": LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--repo", "repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = run_argv(env)
    assert run[run.index("--workspace") + 1] == "wks_me"
    assert run[run.index("--cwd") + 1] == "/repo/lead"  # the window's own cwd


def test_a_different_middle_reuses_the_owned_box_not_a_second_window(env):
    """The old typo guard is gone (operator ruling 2026-11-14): --window-middle never opens a second box beside an owned one."""
    env.data["workspaces"] = [{"workspaceId": "wks_me", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": "w1", "status": "running", "labels": {"ade.lead": LEAD}}]
    env.state("w1", "wks_me", {"ade.lead": LEAD})
    r = env.run("--lead", LEAD, "--slice", "alpha", "--window-middle", "Typo", "--cwd", "/repo", "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr
    run = run_argv(env)
    assert run[run.index("--workspace") + 1] == "wks_me" and "--new-workspace" not in run
    assert rename_calls(env) == [] and json.loads(r.stdout)["windowName"] == WIN


def test_archive_no_middle_ignores_another_leads_window(env):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": f"WORKERS x {OTHER_LEAD}", "cwd": "/repo"}]
    r = archive(env)
    assert r.returncode == 1 and "no WORKER box for lead" in r.stderr
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
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", "WORKER repo (Wave 7)"]]
    assert LEAD not in rename_calls(env)[0][3]  # the lead id lives in the tab name and the label, not the window name


def test_explicit_repo_wins_over_the_cwd(env):
    assert launch(env, "alpha", "--repo", "djbclark-ade").returncode == 0
    assert rename_calls(env)[0][3] == "WORKER djbclark-ade (Wave 7)"


def test_repo_comes_from_the_main_checkout_even_in_a_linked_worktree(env, tmp_path):
    main = tmp_path / "my-repo"
    main.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(main), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path / "my-repo-feature-wt"
    git("worktree", "add", "-q", "-b", "feature", str(wt))
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", str(wt), "--", "--no-wait", f"work in {wt}")
    assert r.returncode == 0, r.stderr
    assert rename_calls(env)[0][3] == "WORKER my-repo (Wave 7)"
    assert json.loads(r.stdout)["tabName"] == f"worker a {LEAD} [wt: my-repo-feature-wt]"  # a --cwd that is a linked worktree is named


def test_first_launch_without_a_middle_opens_the_default_work_box(env):
    r = env.run("--lead", LEAD, "--slice", "a", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["windowName"] == "WORKER repo (workers)"
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", "WORKER repo (workers)"]]
    assert registry(LEAD) == {"wks_abc123"}


@pytest.mark.parametrize("legacy", [f"workers repo Wave 7 {LEAD}", f"WORKERS repo Wave 7 {LEAD}",
                                    f"workers Wave 7 {LEAD}"])
def test_legacy_window_matched_and_renamed_before_launch(env, legacy):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": legacy, "cwd": "/repo"}]
    r = launch(env, "beta")
    assert r.returncode == 0, r.stderr
    assert env.verbs() == [["ls"], ["workspace", "ls"], ["workspace", "ls"], ["workspace", "rename"], ["run"], ["agent", "update"], ["agent", "inspect"]]  # rename first (2nd ls: name-free check)
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
    r = launch(env)  # the owned legacy window wins the match, then its rename onto the taken name is refused
    assert r.returncode == 1 and "already has that name" in r.stderr
    assert ["run"] not in env.verbs() and rename_calls(env) == []


def test_window_holding_another_leads_labelled_agent_is_refused(window):
    member(window, "o9", "wks_win1", lead=OTHER_LEAD)
    r = launch(window)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and "o9" in r.stderr
    assert ["run"] not in window.verbs()


def test_window_holding_only_another_leads_closed_agent_is_refused(env):
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_b1")  # the lead's box (by its record) that once held another lead's worker
    member(env, "o9", "wks_b1", lead=OTHER_LEAD, status="closed")
    r = launch(env)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and ["run"] not in env.verbs()  # F3


def test_window_registered_to_another_lead_is_never_taken_by_launch_and_refused_by_archive(env):
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    own(OTHER_LEAD, "wks_b1")
    r = launch(env)  # a launch looks for the lead's own boxes only: the other lead's window is not one, so it opens its own
    assert r.returncode == 0, r.stderr
    run = run_argv(env)
    assert "--new-workspace" in run and all(a[2] != "wks_b1" for a in rename_calls(env)) and registry(OTHER_LEAD) == {"wks_b1"}
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]  # only the stranger's window by that name
    r = archive(env)
    assert r.returncode == 1 and "registered to lead" in r.stderr
    assert ["workspace", "archive"] not in env.verbs()


def test_archive_refuses_a_same_named_window_nothing_shows_is_ours(env):  # F1
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    r = archive(env)
    assert r.returncode == 1 and "never confers ownership" in r.stderr and ["workspace", "archive"] not in env.verbs()
    r = env.run("archive-window", "--lead", LEAD, "--window-middle", "Wave 7", "--repo", "other")
    assert r.returncode == 1 and ["workspace", "archive"] not in env.verbs()
    member(env, "o9", "wks_b1", lead=OTHER_LEAD, status="closed")  # another lead's closed worker: foreign, refused
    r = archive(env)
    assert r.returncode == 1 and "another lead's agents" in r.stderr and ["workspace", "archive"] not in env.verbs()


def test_launch_never_adopts_an_unclaimed_same_named_window(env):
    """A launch finds boxes by ownership only (find_window middle=None): a window of the right name nothing shows is the lead's
    is left alone and the lead opens (and records) its own, so a name alone still never confers ownership."""
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    assert launch(env).returncode == 0
    assert "--new-workspace" in run_argv(env) and registry(LEAD) == {"wks_abc123"}
    env.data = json.loads(env.data_path.read_text())  # the stub's rename of the minted window
    r = env.run("archive-window", "--lead", LEAD, "--dry-run", "--repo", "repo")  # the record finds its own window, not the namesake
    assert r.returncode == 0 and json.loads(r.stdout)["workspaceId"] == "wks_abc123", r.stderr


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


@pytest.mark.parametrize("name", ["Workers repo (Wave 7)", "WORKERS repo Wave 7", "WORKER repo (Wave 7) x", "worker repo (Wave 7)",
                                  "WORKER  repo (Wave 7)", "MAIN repo (Wave 7)", "LEAD repo (Wave 7)", "USER repo (Wave 7)",
                                  "OTHER repo (Wave 7)", "WORKERS  repo (Wave 7)"])
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


def test_archive_never_archives_lead_windows_or_the_other_box_by_default(env):
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": LEAD_NAME},
                              {"workspaceId": "wks_u1", "name": "OTHER repo (Wave 7)"},
                              {"workspaceId": "wks_m1", "name": "MAIN repo (Wave 9)"}]  # a 2026-11-13 name is still a LEAD window
    member(env, "w1", LEAD_WKS, status="idle")  # even a window holding the lead's own labelled agent
    own(LEAD, "wks_u1")
    for extra in ([], ["--placement", "worker"]):
        r = archive(env, "--idle-handled", *extra)
        assert r.returncode == 1 and "no WORKER box for lead" in r.stderr
    r = archive(env, "--idle-handled", "--placement", "other")  # the OTHER box is archivable, but only when asked for
    assert r.returncode == 0, r.stderr
    assert [c["argv"] for c in env.calls() if c["argv"][:2] == ["workspace", "archive"]] == [["workspace", "archive", "wks_u1"]]


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


def test_archive_ignores_a_main_placed_worker_in_the_lead_window(window):
    window.data["workspaces"].append({"workspaceId": LEAD_WKS, "name": LEAD_NAME})
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
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": LEAD_NAME, "cwd": "/repo/lead"}]
    env.data["run_err"] = ""
    return env


def interactive(env, *extra, slice_name="op1", cwd=None):
    return env.run("--lead", LEAD, "--slice", slice_name, *extra, "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF", cwd=cwd)


@pytest.mark.parametrize("flag", [["--placement", "main"], ["--placement", "lead"], ["--interactive"]])
def test_main_placement_launches_into_the_leads_window(main_env, flag):
    r = interactive(main_env, *flag)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"agentId": AGENT, "workspaceId": LEAD_WKS, "windowName": LEAD_NAME,
                                    "tabName": f"worker op1 {LEAD}"}
    run = run_argv(main_env)
    assert run[run.index("--workspace") + 1] == LEAD_WKS and "--new-workspace" not in run
    assert run[run.index("--cwd") + 1] == "/repo/lead"
    assert [run[i + 1] for i, x in enumerate(run) if x == "--label"] == [f"ade.lead={LEAD}", "slice=op1", "ade.placement=main"]
    assert rename_calls(main_env) == []  # an already-LEAD window is not renamed by a launch
    assert LEAD_WKS not in registry(LEAD)  # the record means "WORKER windows": a LEAD launch never writes it
    assert all(c["env"]["PASEO_WORKSPACE_ID"] is None for c in main_env.calls())
    assert ["agent", "update", AGENT, "--name", f"worker op1 {LEAD}"] in [c["argv"] for c in main_env.calls()]


def test_main_placement_uses_the_agent_record_not_the_ambient_workspace_id(main_env, monkeypatch):
    monkeypatch.delenv("PASEO_WORKSPACE_ID")
    r = interactive(main_env, "--interactive")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["workspaceId"] == LEAD_WKS  # not the ambient wks_ambient


@pytest.mark.parametrize("old", ["MAIN repo Wave 7", "MAIN repo (Wave 7)"])
def test_main_placement_migrates_a_2026_11_13_main_name_to_lead_first(main_env, old):
    main_env.data["workspaces"][0]["name"] = old
    main_env.data["workspaces"][0]["cwd"] = "/repo"
    r = interactive(main_env, "--interactive", "--cwd", "/repo")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, LEAD_NAME]]
    assert main_env.verbs().index(["workspace", "rename"]) < main_env.verbs().index(["run"])
    assert json.loads(r.stdout)["windowName"] == LEAD_NAME


@pytest.mark.parametrize("name", ["djbclark-ade Wave 7", "master", "MAINTAIN x", "Main x", "WORKER repo (Wave 7)",
                                  "OTHER repo (Wave 7)", "WORKERS repo (Wave 7)", "USER repo (Wave 7)", f"workers repo Wave 7 {LEAD}"])
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
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": "LEAD repo (x)", "cwd": "/repo"}]
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


@pytest.mark.parametrize("old,new", [("djbclark-ade Wave 7", "LEAD repo (djbclark-ade Wave 7)"), ("repo Wave 7", "LEAD repo (Wave 7)"),
                                     ("master", "LEAD repo (master)"), ("MAIN repo Wave 7", "LEAD repo (Wave 7)"),
                                     ("MAIN repo (Wave 7)", "LEAD repo (Wave 7)")])
@pytest.mark.parametrize("verb", ["rename-main", "rename-lead"])
def test_rename_main_converts_the_name(main_env, old, new, verb):
    main_env.data["workspaces"][0]["name"] = old
    r = main_env.run(verb, "--lead", LEAD, "--repo", "repo")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, new]] and json.loads(r.stdout)["renamed"] is True


def test_rename_main_is_a_noop_on_a_lead_name_and_takes_an_explicit_work(main_env):
    r = main_env.run("rename-main", "--lead", LEAD)
    assert r.returncode == 0 and json.loads(r.stdout)["renamed"] is False and rename_calls(main_env) == []
    main_env.data["workspaces"][0]["name"] = "master"
    r = main_env.run("rename-lead", "--lead", LEAD, "--window-middle", "Wave 8")  # repo from the window's cwd: lead
    assert r.returncode == 0 and rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "LEAD lead (Wave 8)"]]


@pytest.mark.parametrize("name", ["WORKER repo (Wave 7)", "OTHER repo (Wave 7)", "WORKERS repo (Wave 7)", "USER repo (Wave 7)",
                                  f"workers repo Wave 7 {LEAD}"])
def test_rename_main_refuses_a_worker_or_other_window(main_env, name):
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


def test_interactive_legacy_main_migration_uses_the_windows_own_repo(main_env):  # F4
    main_env.data["workspaces"][0].update(name="MAIN Wave 7", cwd="/somewhere/djbclark-ade")
    r = interactive(main_env, "--interactive", "--cwd", "/somewhere/djbclark-ade")
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "LEAD djbclark-ade (Wave 7)"]]


def test_interactive_legacy_main_migration_without_cwd_takes_the_windows_repo_not_the_callers(main_env, tmp_path):  # F4, kept
    """No --cwd: the caller's own directory (here a repo named other-repo) is not checked against the window, so the rename must
    still use the window's repo. Kills `repo or wsn.repo_of(row["cwd"])` in main_target (the caller's repo winning)."""
    main_env.data["workspaces"][0].update(name="MAIN Wave 7", cwd="/somewhere/djbclark-ade")
    elsewhere = tmp_path / "other-repo"
    elsewhere.mkdir()
    r = interactive(main_env, "--interactive", cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    assert rename_calls(main_env) == [["workspace", "rename", LEAD_WKS, "LEAD djbclark-ade (Wave 7)"]]


def test_interactive_with_a_cwd_other_than_the_windows_is_refused_before_any_rename(main_env):  # ls-05 (was F4's other repo)
    main_env.data["workspaces"][0].update(name="MAIN Wave 7", cwd="/somewhere/djbclark-ade")
    r = interactive(main_env, "--interactive", "--cwd", "/elsewhere/other-repo")
    assert r.returncode == 1 and "runs in /somewhere/djbclark-ade" in r.stderr
    assert not rename_calls(main_env)


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


# --- round 2 adversary findings (B1-B6) ---------------------------------------------------------------------------------

def test_failed_launch_does_not_record_an_adopted_window(env):  # B1
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    env.data["run_rc"] = 2
    assert launch(env).returncode == 1
    assert registry(LEAD) == set()
    env.data["run_rc"] = 0
    r = archive(env)
    assert r.returncode == 1 and "never confers ownership" in r.stderr and ["workspace", "archive"] not in env.verbs()


@pytest.mark.parametrize("status", ["running", "idle", "closed"])
def test_a_window_holding_an_unlabelled_agent_is_left_alone_and_never_adopted(env, status):  # B2
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": "op1", "status": status, "labels": {}}]
    env.state("op1", "wks_u1")
    r = launch(env)  # not the lead's box (nothing shows it): the lead opens its own and never touches the operator's window
    assert r.returncode == 0, r.stderr
    assert "--new-workspace" in run_argv(env) and registry(LEAD) == {"wks_abc123"}
    assert all(a[2] != "wks_u1" for a in rename_calls(env))


def test_a_stray_or_foreign_named_record_file_does_not_block_other_leads(window):  # B3
    (Path(os.environ["ADE_WORKER_RUN_STATE"]) / "junk.windows.json").write_text("{")
    assert launch(window).returncode == 0


def test_an_unclaimed_duplicate_name_does_not_lock_the_owner_out(window):  # B4
    window.data["workspaces"].append({"workspaceId": "wks_dup", "name": WIN, "cwd": "/repo"})
    r = launch(window)
    assert r.returncode == 0, r.stderr
    assert run_argv(window)[run_argv(window).index("--workspace") + 1] == "wks_win1"


def test_legacy_window_in_another_leads_record_is_refused(env):  # B5
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": LEGACY_WIN, "cwd": "/repo"}]
    own(OTHER_LEAD, "wks_old1")
    r = launch(env)
    assert r.returncode == 1 and "registered to lead" in r.stderr and rename_calls(env) == [] and registry(LEAD) == set()


def test_no_wait_taken_as_a_flag_value_is_not_a_brief_position(env):  # B6d
    r = env.run("--lead", LEAD, "--slice", "a", "--window-middle", "Wave 7", "--cwd", "/repo", "--", "--provider", "--no-wait", "BRIEF")
    assert r.returncode == 1 and not env.calls()


def test_a_window_beside_a_live_agent_that_cannot_be_placed_is_left_alone(env):  # round 3 B1
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": "ghost", "status": "running", "labels": {}}]  # no state file
    r = launch(env)
    assert r.returncode == 0, r.stderr
    assert "--new-workspace" in run_argv(env) and registry(LEAD) == {"wks_abc123"}


def test_a_record_write_failure_after_launch_names_the_launched_agent(env, monkeypatch):  # round 3 B2
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": WIN, "cwd": "/repo"}]
    env.data["run_err"] = ""
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{LEAD}.windows.json").mkdir()  # a directory where the record file belongs: reading it raises, not a clean refusal
    r = launch(env)
    assert r.returncode == 1 and "Traceback" not in r.stderr


# --- lead succession (2026-11-14): windows and labelled workers of an archived predecessor are the successor's ---

PRED1 = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
PRED2 = "22222222-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
WORKER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def handoff(pred, nxt, status="archived"):
    d = Path(os.environ["ADE_SELF_SESSION_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"handoff-{pred}.json").write_text(json.dumps(
        {"kind": "handoff", "predecessor": pred, "successor": nxt, "status": status, "ack": {"agent_id": nxt},
         "home": str(Path(os.environ["PASEO_HOME"]).resolve())}))


def chain(*ids, status="archived"):
    for pred, nxt in zip(ids, ids[1:]):
        handoff(pred, nxt, status)


def placed(env):
    return [c["argv"] for c in env.calls() if c["argv"][0] == "run"]


def test_window_registered_to_a_replaced_lead_is_adopted_by_the_successor(env):
    """The 2026-11-14 failure: `window ... is registered to lead 8cd86203, not 994234ba` after two self-handoffs."""
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(PRED1, "wks_win1")
    chain(PRED1, PRED2, LEAD)  # three steps: PRED1 -> PRED2 -> LEAD
    r = launch(env)
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_win1" and f"ade.lead={LEAD}" in run
    assert "--new-workspace" not in run


def test_workers_labelled_for_a_replaced_lead_do_not_make_the_window_foreign(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": WORKER, "status": "idle", "labels": {"ade.lead": PRED2}}]
    env.state(WORKER, "wks_win1", {"ade.lead": PRED2})  # no registry record at all: the label alone proves it
    chain(PRED1, PRED2, LEAD)
    r = launch(env)
    assert r.returncode == 0, r.stderr
    assert placed(env)


def test_without_a_completed_handoff_the_old_refusals_stand(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(PRED1, "wks_win1")
    for status in ("awaiting-ack", "acknowledged", "archive-unknown"):  # a broken chain: the last hop never finished
        chain(PRED1, PRED2, status=status)
        handoff(PRED2, LEAD)
        r = archive(env)
        assert r.returncode == 1 and f"registered to lead {PRED1}" in r.stderr, status
    r = launch(env)  # a launch never takes it either: it is not a box of this lead, so the lead opens its own
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert "--new-workspace" in run and registry(PRED1) == {"wks_win1"}
    assert ["workspace", "archive"] not in env.verbs()


def test_a_different_live_lead_is_still_refused_even_beside_a_chain(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"},
                              {"workspaceId": "wks_win2", "name": "WORKER repo (Wave 9)", "cwd": "/repo"}]
    chain(PRED1, LEAD)
    own(OTHER_LEAD, "wks_win1")
    own(PRED1, "wks_win2")
    r = archive(env)  # Wave 7 is the stranger's
    assert r.returncode == 1 and f"registered to lead {OTHER_LEAD}" in r.stderr
    env.data["agents"] = [{"id": WORKER, "status": "idle", "labels": {"ade.lead": OTHER_LEAD}}]
    env.state(WORKER, "wks_win2", {"ade.lead": OTHER_LEAD})
    r = env.run("--lead", LEAD, "--slice", "beta", "--window-middle", "Wave 9", "--cwd", "/repo", "--",
                "--provider", "claude/sonnet", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "another lead's agents" in r.stderr
    assert not placed(env)
    env.data["agents"] = []
    r = launch(env)  # the stranger's window is never a box of this lead's; the one its predecessor placed is
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_win2"


def test_a_successors_registry_never_makes_a_predecessor_foreign_to_itself(env):
    """The predecessor's lineage is itself only: a record under the successor is the predecessor's `other lead`."""
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_win1")
    chain(PRED1, LEAD)
    r = env.run("archive-window", "--lead", PRED1, "--on-behalf-of-lead", "--window-middle", "Wave 7")
    assert r.returncode == 1 and f"registered to lead {LEAD}" in r.stderr
    r = env.run("--lead", PRED1, "--on-behalf-of-lead", "--slice", "alpha", "--window-middle", "Wave 7", "--cwd", "/repo",
                "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr  # not the predecessor's box: it opens its own and leaves the successor's alone
    assert "--new-workspace" in placed(env)[0] and registry(LEAD) == {"wks_win1"}


def test_a_cyclic_ledger_adopts_nothing(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(PRED1, "wks_win1")
    handoff(PRED1, LEAD)
    handoff(LEAD, PRED1)
    r = launch(env)
    assert r.returncode == 1 and "cyclic" in r.stderr and not placed(env)  # loud, never "no predecessors"


def test_label_queries_stay_bounded_on_a_long_chain(env):
    ids = [f"{i:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa" for i in range(1, 41)]
    chain(*ids, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(ids[0], "wks_win1")  # the OLDEST predecessor's record is still honoured: registries are file reads
    # an unlabelled agent in the window: an unclaimed name match would be refused (never adopted), an owned window is not
    env.data["agents"] = [{"id": "x1", "status": "idle", "labels": {}}]
    env.state("x1", "wks_win1")
    r = launch(env)
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_win1"
    # owned through the oldest predecessor's record, not adopted by name (a mutant reading registries of the bounded ids alone
    # would refuse: the unlabelled agent makes an unclaimed window unadoptable); the launch records it under LEAD
    assert registry(LEAD) == {"wks_win1"}
    label_calls = [c["argv"] for c in env.calls() if c["argv"][0] == "ls" and "--label" in c["argv"]]
    assert 1 <= len(label_calls) <= 9  # the lead plus the 8 nearest predecessors, however long the chain
    # archive-window refuses a window nothing shows is the lead's: it must find this one owned (through the oldest record)
    env.data["agents"] = []
    r = archive(env, "--dry-run")
    assert r.returncode == 0, r.stderr


def test_archive_blockers_name_the_matching_label_and_the_bound_is_documented_behaviour(env):
    ids = [f"{i:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa" for i in range(1, 41)]
    chain(*ids, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_win1")
    near, far = WORKER, "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    env.data["agents"] = [{"id": near, "status": "running", "labels": {"ade.lead": ids[-2]}},
                          {"id": far, "status": "running", "labels": {"ade.lead": ids[0]}}]
    env.state(near, "wks_win1", {"ade.lead": ids[-2]})
    env.state(far, "wks_other", {"ade.lead": ids[0]})  # 40 handoffs back, in another window: beyond the label bound
    r = archive(env)
    assert r.returncode == 1 and "Traceback" not in r.stderr and f"{near}: labelled ade.lead={ids[-2]}, status running" in r.stderr
    assert far not in r.stderr  # documented bound (docs/self-session.md C0a): not asked about, so not a blocker
    env.state(far, "wks_win1", {"ade.lead": ids[0]})  # in the window itself it still blocks, whatever its label
    assert f"blocker: {far}: other live agent in the window" in archive(env).stderr




def test_archive_window_covers_a_replaced_leads_window_and_clears_its_record(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    env.data["agents"] = [{"id": WORKER, "status": "idle", "labels": {"ade.lead": PRED1}}]
    env.state(WORKER, "wks_win1", {"ade.lead": PRED1})
    own(PRED1, "wks_win1")
    chain(PRED1, LEAD)
    assert archive(env).returncode == 1  # the predecessor's idle worker blocks, exactly as the lead's own would
    r = archive(env, "--idle-handled")
    assert r.returncode == 0, r.stderr
    assert ["workspace", "archive"] in env.verbs()
    assert registry(PRED1) == set()  # the stale id is gone from the replaced lead's record too


# --- ls-03: a successor lead that inherited several predecessor windows is not stuck (2026-11-14) ---------------------------

def inherited_windows(env, *names):
    """PRED1 -> LEAD handoff; PRED1 owns one window per name; LEAD owns none of its own."""
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": f"wks_old{i}", "name": n, "cwd": "/repo"} for i, n in enumerate(names)]
    own(PRED1, *[f"wks_old{i}" for i in range(len(names))])


def test_a_successor_reuses_the_inherited_box_of_its_repo_and_leaves_the_others(env):
    inherited_windows(env, "WORKER repo (Old A)", "WORKERS other (Old C)")
    r = launch(env)  # --window-middle "Wave 7" is not new work for a new window any more: one box per lead and repo
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_old0" and "--new-workspace" not in run
    assert json.loads(r.stdout)["windowName"] == "WORKER repo (Old A)" and rename_calls(env) == []
    assert registry(LEAD) == {"wks_old0"} and registry(PRED1) == {"wks_old0", "wks_old1"}


def test_a_successor_with_an_own_and_an_inherited_box_of_the_repo_must_pick_one(env):
    inherited_windows(env, "WORKER repo (Old A)")
    env.data["workspaces"].append({"workspaceId": "wks_mine", "name": "WORKER repo (Mine)", "cwd": "/repo"})
    own(LEAD, "wks_mine")  # the lead placed this one itself: two boxes of the repo, whoever placed them
    r = launch(env)  # --window-middle "Wave 7" picks neither
    assert r.returncode == 1 and "2 windows match the lead's WORKER box" in r.stderr
    assert "wks_mine" in r.stderr and "wks_old0" in r.stderr and not placed(env)
    r = env.run("--lead", LEAD, "--slice", "alpha", "--window-middle", "Mine", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_mine"


def test_without_a_middle_the_window_of_this_repo_is_picked_when_exactly_one_matches(env):
    inherited_windows(env, "WORKER repo (Old A)", "WORKER other (Old B)", "WORKER third (Old C)")
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_old0"


def test_without_a_middle_two_windows_of_the_same_repo_are_still_ambiguous(env):
    inherited_windows(env, "WORKER repo (Old A)", "WORKER repo (Old B)", "WORKERS other (Old C)")
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "2 windows match" in r.stderr and "--window-middle" in r.stderr
    assert not placed(env)


def test_a_wrong_repo_never_picks_an_inherited_legacy_window(env):
    """The repo of a legacy window is its cwd's, never the --repo argument: archive-window refuses two matches; a launch takes the window whose gone directory names no repo."""
    chain(PRED1, LEAD)
    env.data["workspaces"] = [
        {"workspaceId": "wks_mine", "name": "WORKER bar (X)", "cwd": "/bar"},
        {"workspaceId": "wks_leg", "name": f"workers Wave 6 {PRED1}", "cwd": "/elsewhere/foo"}]
    own(LEAD, "wks_mine")
    r = env.run("archive-window", "--lead", LEAD, "--repo", "baz", "--dry-run")
    assert r.returncode == 1 and "2 windows match" in r.stderr, r.stderr
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "baz", "--", "--no-wait", "B")  # `bar` is another repo's; the legacy window's
    assert r.returncode == 0, r.stderr                                                    # directory is gone, so it names no repo: it is the box
    assert placed(env)[0][placed(env)[0].index("--workspace") + 1] == "wks_leg"


def test_a_legacy_window_is_picked_by_its_cwds_repo(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [
        {"workspaceId": "wks_mine", "name": "WORKER bar (X)", "cwd": "/bar"},
        {"workspaceId": "wks_leg", "name": f"workers Wave 6 {PRED1}", "cwd": "/elsewhere/foo"}]
    own(LEAD, "wks_mine")
    r = env.run("archive-window", "--lead", LEAD, "--repo", "foo", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "wks_leg" in r.stdout and "wks_mine" not in r.stdout


def test_archive_window_narrows_by_repo_and_refuses_when_ambiguous(env):
    inherited_windows(env, "WORKER repo (Old A)", "WORKER other (Old B)")
    r = env.run("archive-window", "--lead", LEAD, "--repo", "other", "--dry-run")
    assert r.returncode == 0 and "wks_old1" in r.stdout, r.stderr
    r = env.run("archive-window", "--lead", LEAD, "--repo", "nothere", "--dry-run")
    assert r.returncode == 1 and "2 windows match" in r.stderr


def test_with_a_middle_the_repo_narrowing_never_promotes_an_unowned_name_match(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [
        {"workspaceId": "wks_u", "name": "WORKER repo (M)", "cwd": "/repo"},  # no record, no label: not this lead's box
        {"workspaceId": "wks_l1", "name": f"workers M {PRED1}", "cwd": "/x/one"},
        {"workspaceId": "wks_l2", "name": f"workers M {PRED1}", "cwd": "/x/two"}]
    r = env.run("--lead", LEAD, "--slice", "s", "--window-middle", "M", "--cwd", "/repo", "--", "--no-wait", "B")
    assert r.returncode == 1 and "2 windows match" in r.stderr and not placed(env)
    assert "wks_l1" in r.stderr and "wks_l2" in r.stderr and "wks_u" not in r.stderr  # the unowned name match is not even counted


def test_a_lead_whose_own_window_has_a_legacy_name_reuses_it_for_any_middle(env):
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}", "cwd": "/repo"}]
    r = launch(env)  # --window-middle "Wave 7": the lead's own (legacy) window is Wave 6, and it is the box
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_leg" and "--new-workspace" not in run
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER repo (Wave 6)"]] and registry(LEAD) == {"wks_leg"}


def test_a_successor_with_only_an_inherited_legacy_window_reuses_it_and_renames_it(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {PRED1}", "cwd": "/repo"}]
    r = launch(env)  # --window-middle "Wave 7": the predecessor's legacy window is the successor's box now
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_leg" and "--new-workspace" not in run
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER repo (Wave 6)"]] and registry(LEAD) == {"wks_leg"}


def test_a_launch_into_an_inherited_window_makes_it_the_successors_own(env):
    """The record keeps covering a window the successor used, after its worker is archived (archive-window finds it by it)."""
    inherited_windows(env, "WORKER repo (Wave 7)")
    r = launch(env)
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_old0" and "--new-workspace" not in run
    assert registry(LEAD) == {"wks_old0"} and registry(PRED1) == {"wks_old0"}
    env.data["agents"] = []  # the worker is archived: only the registry says the window is the lead's
    r = env.run("--lead", LEAD, "--slice", "beta", "--window-middle", "Wave 7x", "--cwd", "/repo", "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr  # a different middle is the same box, never a second window
    run = placed(env)[1]
    assert run[run.index("--workspace") + 1] == "wks_old0" and "--new-workspace" not in run


def test_archive_window_without_a_repo_never_picks_a_cwd_less_legacy_window(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [
        {"workspaceId": "wks_cur", "name": "WORKER bar (X)", "cwd": "/bar"},
        {"workspaceId": "wks_leg", "name": f"workers Wave 6 {PRED1}"}]  # no cwd: its repo is unknown
    own(LEAD, "wks_cur")
    own(PRED1, "wks_leg")
    r = env.run("archive-window", "--lead", LEAD, "--dry-run")
    assert r.returncode == 1 and "2 windows match" in r.stderr, r.stderr


def test_an_unbuildable_predecessor_window_for_the_same_work_still_refuses_a_new_one(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 7 {PRED1}", "cwd": "/x/bad repo"}]
    own(PRED1, "wks_leg")
    r = launch(env)  # --window-middle "Wave 7": the same work, but the window cannot be renamed (repo name invalid)
    assert r.returncode == 1 and "cannot be renamed" in r.stderr and not placed(env)


def test_an_unbuildable_predecessor_window_in_the_repo_work_form_still_refuses_a_new_one(env):
    """Legacy middles were usually `<repo> <work>`: `workers repo Wave 7 <PRED1>` is the work "Wave 7" once the repo is peeled
    off (wsn.normalize_work), so asking for the middle "Wave 7" must not open a second window beside it."""
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers repo Wave 7 {PRED1}", "cwd": "/x/bad repo"}]
    own(PRED1, "wks_leg")
    r = launch(env)
    assert r.returncode == 1 and "cannot be renamed" in r.stderr and not placed(env)


def test_a_buildable_predecessor_window_of_another_repo_is_not_taken_by_normalising_with_the_launch_repo(env, tmp_path):
    """`workers repo Wave 7 <PRED1>` in cwd /other migrates to `repo Wave 7` in repo `other`; a launch from repo `repo` is not
    that repo's box (one box per lead and repo): it opens its own, the predecessor's window stays the predecessor's."""
    chain(PRED1, LEAD)
    (tmp_path / "other").mkdir()
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers repo Wave 7 {PRED1}", "cwd": str(tmp_path / "other")}]
    own(PRED1, "wks_leg")
    r = launch(env)
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--new-workspace") + 1] == "local" and "--workspace" not in run
    assert "wks_leg" not in registry(LEAD)
    assert not [c for c in env.calls() if c["argv"][:2] == ["workspace", "rename"] and "wks_leg" in c["argv"]]


def test_a_buildable_predecessor_window_for_other_work_is_reused_whatever_the_middle(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Big Wave 7 {PRED1}", "cwd": "/repo"}]
    own(PRED1, "wks_leg")
    r = launch(env)  # --window-middle "Wave 7" is not the work "Big Wave 7", and does not have to be
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_leg" and "--new-workspace" not in run
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER repo (Big Wave 7)"]] and "wks_leg" in registry(LEAD)


def test_an_unbuildable_predecessor_window_is_the_box_and_needs_an_explicit_repo(env):
    chain(PRED1, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Big Wave 7 {PRED1}", "cwd": "/x/bad repo"}]
    own(PRED1, "wks_leg")
    r = launch(env)  # the only box of the lead cannot be renamed (its repo `bad repo` is no valid name): refused, nothing placed
    assert r.returncode == 1 and "cannot be renamed" in r.stderr and not placed(env)
    r = env.run("--lead", LEAD, "--slice", "alpha", "--repo", "repo", "--", "--no-wait", "BRIEF")  # --repo names the window's repo
    assert r.returncode == 0, r.stderr
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER repo (Big Wave 7)"]]


def test_a_cwd_other_than_the_windows_is_refused_not_silently_dropped(env):
    """`paseo run --workspace` ignores --cwd (getpaseo/paseo#9699): the worker would start in the window's directory."""
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_win1")
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 1 and "runs in /repo" in r.stderr and "/repo-claimed-wt" in r.stderr
    assert not placed(env)


def test_the_windows_own_directory_as_cwd_still_launches(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_win1")
    r = launch(env)  # --cwd /repo
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--cwd") + 1] == "/repo"


def test_a_new_window_takes_the_callers_cwd(env):
    r = env.run("--lead", LEAD, "--slice", "s", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--new-workspace") + 1] == "local" and run[run.index("--cwd") + 1] == "/repo-claimed-wt"


def test_a_window_without_a_known_directory_is_checked_after_the_launch(env):
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN}]
    own(LEAD, "wks_win1")
    env.data["inspect_cwd"] = "/repo-main"
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 1 and "started in /repo-main" in r.stderr and "was launched" in r.stderr
    assert "stopped (interrupted" in r.stderr and ["agent", "stop", AGENT] in [c["argv"] for c in env.calls()]  # not left running
    env.data["stop_rc"] = 1  # the stop itself failed: say so, the worker is still running
    r = env.run("--lead", LEAD, "--slice", "s1", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 1 and "NOT stopped" in r.stderr
    del env.data["stop_rc"]
    env.data["inspect_cwd"] = "/repo-claimed-wt"
    r = env.run("--lead", LEAD, "--slice", "s2", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr
    del env.data["inspect_cwd"]  # paseo cannot say: the launch stands
    r = env.run("--lead", LEAD, "--slice", "s3", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr


def test_a_new_window_is_verified_too_and_a_dropped_cwd_is_reported(env):
    env.data["inspect_cwd"] = "/Users/someone"  # what paseo did with --cwd /repo
    r = launch(env)
    assert r.returncode == 1 and "started in /Users/someone" in r.stderr and "was launched" in r.stderr
    assert "stopped (interrupted" in r.stderr and "dropped --cwd for the new window" in r.stderr


def test_a_symlinked_window_cwd_with_a_trailing_slash_matches_the_real_directory(env, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": WIN, "cwd": f"{link}/"}]
    env.data["inspect_cwd"] = str(link)  # paseo reports the symlink path
    own(LEAD, "wks_win1")
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", str(real), "--", "--no-wait", "B")
    assert r.returncode == 0, r.stderr


def test_an_unreadable_inspect_never_fails_a_good_launch(env):
    env.data["inspect_rc"] = 1
    r = launch(env)
    assert r.returncode == 0, r.stderr


# --- wr-01: one WORKER window per (lead, repo); a minted window sits in the repo's primary checkout (2026-11-14) -------------

def other_repo_launch(env, middle="tendcf PR41 fork fixes", repo_cwd="/libntech-wt", *extra):
    return env.run("--lead", LEAD, "--slice", "s", "--window-middle", middle, "--cwd", repo_cwd, *extra, "--", "--no-wait", "B")


def test_a_launch_for_another_repo_mints_its_own_window_not_a_refusal(env):
    """The reported case: the lead owns a WORKER box for repo A; a launch for repo B opens its own box beside it."""
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"}]
    own(LEAD, "wks_a")
    r = other_repo_launch(env, "tendcf PR41 fork fixes", "/libntech-wt", "--repo", "libntech")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--new-workspace") + 1] == "local" and "--workspace" not in run
    assert json.loads(r.stdout)["windowName"] == "WORKER libntech (tendcf PR41 fork fixes)"
    assert registry(LEAD) == {"wks_a", "wks_abc123"}  # the new window is the lead's own beside the first


def test_a_mistyped_middle_reuses_the_same_repos_box_never_the_other_repos(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"},
                              {"workspaceId": "wks_l", "name": "WORKER libntech (strictjson)", "cwd": "/libntech"}]
    own(LEAD, "wks_a", "wks_l")
    r = other_repo_launch(env, "strictjsno", "/libntech", "--repo", "libntech")
    assert r.returncode == 0, r.stderr  # no typo guard: the middle never opens a box and never picks the other repo's
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_l" and rename_calls(env) == []
    assert json.loads(r.stdout)["windowName"] == "WORKER libntech (strictjson)"


def test_the_repo_comes_from_the_cwd_when_no_repo_is_given(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"}]
    own(LEAD, "wks_a")
    r = other_repo_launch(env, repo_cwd="/libntech")  # repo_of(/libntech) = libntech: not cfengine-core's box
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["windowName"] == "WORKER libntech (tendcf PR41 fork fixes)"


def test_a_second_middle_of_the_derived_repo_reuses_its_box(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"},
                              {"workspaceId": "wks_abc123", "name": "WORKER libntech (tendcf PR41 fork fixes)", "cwd": "/libntech"}]
    own(LEAD, "wks_a", "wks_abc123")
    r = other_repo_launch(env, "tendcf PR41 fork fixs", "/libntech")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_abc123" and rename_calls(env) == []


def test_a_legacy_window_of_another_repo_is_not_taken(env, tmp_path):
    core, lib = tmp_path / "cfengine-core", tmp_path / "libntech"
    core.mkdir()
    lib.mkdir()
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}", "cwd": str(core)}]
    r = other_repo_launch(env, repo_cwd=str(lib))  # the legacy window is cfengine-core's: a libntech launch mints its own
    assert r.returncode == 0, r.stderr
    assert placed(env)[0][placed(env)[0].index("--new-workspace") + 1] == "local"


def test_a_legacy_window_of_the_repo_of_its_cwd_is_reused_and_renamed(env, tmp_path):
    lib = tmp_path / "libntech"
    lib.mkdir()
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}", "cwd": str(lib)}]
    r = other_repo_launch(env, "Typo", str(lib))  # the same repo: its box, whatever the middle
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_leg" and "--new-workspace" not in run
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER libntech (Wave 6)"]]


def test_a_legacy_window_with_no_cwd_is_the_launch_repos_box(env):
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}"}]  # a legacy window with no cwd
    r = other_repo_launch(env, repo_cwd="/libntech")
    assert r.returncode == 0, r.stderr  # nothing says it is another repo's: it is taken and named for the launch's repo
    assert rename_calls(env) == [["workspace", "rename", "wks_leg", "WORKER libntech (Wave 6)"]]


def test_no_repo_keeps_every_owned_window_in_the_archive_typo_guard(env, monkeypatch):
    """find_window with a `middle` (only archive-window passes one now; a launch passes none) still refuses a middle that
    matches nothing while the lead owns a box: with repo None every owned window counts."""
    import importlib.machinery, importlib.util
    loader = importlib.machinery.SourceFileLoader("ade_worker_run_t", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_worker_run_t", loader)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.syspath_prepend(str(ROOT / "bin"))
    loader.exec_module(mod)
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"}]
    own(LEAD, "wks_a")
    env.flush()
    with pytest.raises(mod.Refused, match="second window"):
        mod.find_window(LEAD, None, "Whatever")
    with pytest.raises(mod.Refused, match="second window"):
        mod.find_window(LEAD, "cfengine-core", "Whatever")
    assert mod.find_window(LEAD, "libntech", "Whatever") is None
    # a launch's call shape (middle None) finds the box whatever its work; `pick` only chooses among several
    found = mod.find_window(LEAD, "cfengine-core", None, pick="Whatever")
    assert found.row["workspaceId"] == "wks_a" and found.owned and found.rename_to is None


def git(*args, cwd):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"})


def make_repo(tmp_path, name="libntech"):
    main = tmp_path / name
    main.mkdir()
    git("init", "-q", "-b", "master", cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "i", cwd=main)
    wt = tmp_path / f"{name}-strictjson-wt"
    git("worktree", "add", "-q", "-b", "sj", str(wt), cwd=main)
    return main, wt


def mint(env, wt, brief=None, slice_name="s", middle="strictjson"):
    return env.run("--lead", LEAD, "--slice", slice_name, "--window-middle", middle, "--cwd", str(wt), "--", "--no-wait",
                   brief if brief is not None else f"work in {wt}")


def test_a_minted_window_sits_in_the_primary_checkout_not_the_claimed_worktree(env, tmp_path):
    main, wt = make_repo(tmp_path)
    r = mint(env, wt)
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--cwd") + 1] == os.path.realpath(main)
    out = json.loads(r.stdout)
    assert out["windowName"] == "WORKER libntech (strictjson)"
    assert out["tabName"] == f"worker s {LEAD} [wt: libntech-strictjson-wt]"  # the claimed worktree is named in the tab
    assert out["cwd"] == os.path.realpath(main) and out["requestedCwd"] == os.path.realpath(wt)  # said, not silent
    assert "primary checkout" in r.stderr
    # the placement check compares with the primary checkout: a worker that started there passes, one elsewhere is stopped
    env.data["workspaces"] = []
    env.data["inspect_cwd"] = os.path.realpath(main)
    own(LEAD)
    assert mint(env, wt, slice_name="s2").returncode == 0
    env.data["workspaces"] = []
    env.data["inspect_cwd"] = str(wt)
    r = mint(env, wt, slice_name="s3")
    assert r.returncode == 1 and "started in" in r.stderr and "primary checkout" in r.stderr


def test_a_minted_window_needs_the_worktree_named_in_the_brief(env, tmp_path):
    """The worker starts in the shared primary checkout: a brief that never names the worktree is refused before any launch."""
    main, wt = make_repo(tmp_path)
    r = mint(env, wt, brief="just do the work")
    assert r.returncode == 1 and str(os.path.realpath(wt)) in r.stderr and "brief" in r.stderr
    assert not placed(env)


def test_the_same_launch_again_goes_to_the_window_just_minted(env, tmp_path):
    """The identical command line works twice: the second finds the window by name and places the worker at its cwd."""
    main, wt = make_repo(tmp_path)
    r = mint(env, wt)
    assert r.returncode == 0, r.stderr
    wid = json.loads(r.stdout)["workspaceId"]
    env.data["workspaces"] = [{"workspaceId": wid, "name": "WORKER libntech (strictjson)", "cwd": os.path.realpath(main)}]
    r = mint(env, wt, slice_name="s2")
    assert r.returncode == 0, r.stderr
    run = placed(env)[1]
    assert run[run.index("--workspace") + 1] == wid and run[run.index("--cwd") + 1] == os.path.realpath(main)
    assert json.loads(r.stdout)["cwd"] == os.path.realpath(main)
    assert mint(env, wt, brief="no worktree here", slice_name="s3").returncode == 1  # still needs the worktree in the brief


def test_a_submodule_inside_a_claimed_worktree_resolves_to_the_superprojects_primary_checkout(tmp_path):
    sys.path.insert(0, str(ROOT / "bin"))
    import ade_ws_names as wsn
    sub = tmp_path / "sub"
    sub.mkdir()
    git("init", "-q", "-b", "master", cwd=sub)
    git("commit", "-q", "--allow-empty", "-m", "i", cwd=sub)
    main = tmp_path / "super"
    main.mkdir()
    git("init", "-q", "-b", "master", cwd=main)
    git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "libs/sub", cwd=main)
    git("commit", "-q", "-m", "s", cwd=main)
    wt = tmp_path / "super-wt"
    git("worktree", "add", "-q", "-b", "w", str(wt), cwd=main)
    git("-c", "protocol.file.allow=always", "submodule", "update", "-q", "--init", cwd=wt)
    assert wsn.primary_checkout_of(str(wt / "libs/sub")) == os.path.realpath(main / "libs/sub")
    assert wsn.primary_checkout_of(str(wt)) == os.path.realpath(main)


def test_a_worktree_of_a_separate_git_dir_or_bare_repo_has_no_primary_checkout_and_says_so(tmp_path):
    sys.path.insert(0, str(ROOT / "bin"))
    import ade_ws_names as wsn
    main = tmp_path / "plain"
    main.mkdir()
    git("init", "-q", "-b", "master", cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "i", cwd=main)
    sep = tmp_path / "sep.git"  # a separate git dir: the common dir is not named `.git`
    subprocess.run(["git", "init", "-q", "-b", "master", "--separate-git-dir", str(sep), str(tmp_path / "sepwork")], check=True,
                   capture_output=True)
    git("commit", "-q", "--allow-empty", "-m", "i", cwd=tmp_path / "sepwork")
    wt = tmp_path / "sepwork-wt"
    git("worktree", "add", "-q", "-b", "w", str(wt), cwd=tmp_path / "sepwork")
    # git records no path to a --separate-git-dir repo's main work tree: nothing better than the worktree itself, said by linked_worktree
    assert wsn.primary_checkout_of(str(wt)) == os.path.realpath(wt) and wsn.linked_worktree(str(wt))
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(main), str(bare)], check=True, capture_output=True)
    git("worktree", "add", "-q", "-b", "w", str(tmp_path / "barewt"), cwd=bare)
    assert wsn.primary_checkout_of(str(tmp_path / "barewt")) == os.path.realpath(tmp_path / "barewt")  # no main worktree: itself
    assert wsn.linked_worktree(str(tmp_path / "barewt"))


def test_a_repo_name_in_another_case_reuses_the_only_box(env):
    env.data["workspaces"] = [{"workspaceId": "wks_l", "name": "WORKER libntech (strictjson)", "cwd": "/libntech"}]
    own(LEAD, "wks_l")
    r = other_repo_launch(env, "strictjsno", "/libntech", "--repo", "LibNTech")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_l" and rename_calls(env) == []


def test_the_repo_narrowing_ignores_the_case_of_the_repo_name(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER cfengine-core (cmdbfc a1)", "cwd": "/cfengine-core"},
                              {"workspaceId": "wks_l", "name": "WORKER libntech (strictjson)", "cwd": "/libntech"}]
    own(LEAD, "wks_a", "wks_l")
    r = other_repo_launch(env, "strictjsno", "/libntech", "--repo", "LibNTech")
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_l"


def test_a_legacy_row_without_a_workspace_id_is_a_refusal_not_a_traceback(env):
    env.data["workspaces"] = [{"name": f"workers Wave 6 {LEAD}", "cwd": "/libntech"}]
    r = other_repo_launch(env, "x", "/libntech")
    assert "Traceback" not in r.stderr


def test_a_relative_cwd_or_a_longer_name_does_not_satisfy_the_brief_check(env, tmp_path):
    main, wt = make_repo(tmp_path)
    env.flush()
    # `--cwd .` run from the worktree: the brief must still carry the absolute path ("." is in almost any text)
    r = subprocess.run([sys.executable, str(SCRIPT), "--lead", LEAD, "--slice", "s", "--window-middle", "strictjson", "--cwd", ".",
                        "--", "--no-wait", "Fix the parser."], capture_output=True, text=True, cwd=wt)
    assert r.returncode == 1 and "brief" in r.stderr and not placed(env)
    r = subprocess.run([sys.executable, str(SCRIPT), "--lead", LEAD, "--slice", "s", "--window-middle", "strictjson", "--cwd", ".",
                        "--", "--no-wait", "Fix . the parser"], capture_output=True, text=True, cwd=wt)  # a lone "." in the text
    assert r.returncode == 1 and "brief" in r.stderr and not placed(env)
    r = mint(env, wt, brief=f"work in {wt}2/x and {wt}-other")  # a longer name is not the worktree
    assert r.returncode == 1 and "brief" in r.stderr and not placed(env)
    assert mint(env, wt, brief=f"work in {wt}/src, then {wt}.").returncode == 0  # a path under it, a trailing full stop


def test_main_placement_keeps_refusing_a_cwd_other_than_its_windows(env, tmp_path):
    main, wt = make_repo(tmp_path)
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": "LEAD libntech (lead)", "cwd": str(os.path.realpath(main))}]
    env.state(LEAD, LEAD_WKS, {})
    r = env.run("--lead", LEAD, "--slice", "s", "--placement", "lead", "--cwd", str(wt), "--", "--no-wait", "no worktree named")
    assert r.returncode == 1 and "paseo ignores --cwd" in r.stderr and not placed(env)


def test_a_refused_brief_check_renames_nothing(env, tmp_path):
    main, wt = make_repo(tmp_path)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}", "cwd": str(os.path.realpath(main))}]
    r = env.run("--lead", LEAD, "--slice", "s", "--window-middle", "Wave 6", "--cwd", str(wt), "--", "--no-wait", "no worktree named")
    assert r.returncode == 1 and "brief" in r.stderr
    assert ["workspace", "rename"] not in env.verbs() and not placed(env) and registry(LEAD) == set()


def test_an_uninitialised_submodule_directory_is_not_a_primary_checkout(tmp_path):
    sys.path.insert(0, str(ROOT / "bin"))
    import ade_ws_names as wsn
    sub = tmp_path / "sub"
    sub.mkdir()
    git("init", "-q", "-b", "master", cwd=sub)
    git("commit", "-q", "--allow-empty", "-m", "i", cwd=sub)
    main = tmp_path / "super"
    main.mkdir()
    git("init", "-q", "-b", "master", cwd=main)
    git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "libs/sub", cwd=main)
    git("commit", "-q", "-m", "s", cwd=main)
    wt = tmp_path / "super-wt"
    git("worktree", "add", "-q", "-b", "w", str(wt), cwd=main)
    git("-c", "protocol.file.allow=always", "submodule", "update", "-q", "--init", cwd=wt)
    subprocess.run(["rm", "-rf", str(main / "libs/sub")], check=True)
    (main / "libs/sub").mkdir()  # the primary checkout never initialised its submodule: an empty directory
    assert wsn.primary_checkout_of(str(wt / "libs/sub")) == os.path.realpath(wt / "libs/sub")
    assert wsn.linked_worktree(str(wt / "libs/sub"))  # the superproject is a linked worktree: the launch warns


def run_in(env, wt, *args):
    return env.run("--lead", LEAD, "--slice", "s", *args, cwd=str(wt))


def test_no_cwd_from_a_linked_worktree_is_checked_like_an_explicit_cwd(env, tmp_path):
    """Lead review of #709, B1: standing in a worktree and giving no --cwd must not silently start the worker in the primary checkout."""
    main, wt = make_repo(tmp_path)
    r = run_in(env, wt, "--window-middle", "strictjson", "--", "--no-wait", "just do it")
    assert r.returncode == 1 and "brief" in r.stderr and not placed(env)
    # round 4, D1: the remedy must never tell the lead to hand over the worktree it stands in
    assert "--cwd" in r.stderr and "put that worktree" not in r.stderr and "Never hand a worker the worktree you" in r.stderr
    r = run_in(env, wt, "--window-middle", "strictjson", "--", "--no-wait", f"work in {wt}")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["cwd"] == os.path.realpath(main) and out["requestedCwd"] == os.path.realpath(wt) and "primary checkout" in r.stderr
    # inside the primary checkout itself nothing is substituted and nothing is checked
    env.data["workspaces"] = []
    own(LEAD)
    r = run_in(env, main, "--window-middle", "strictjson", "--", "--no-wait", "no path needed")
    assert r.returncode == 0, r.stderr
    assert "cwd" not in json.loads(r.stdout)
    # the post-launch check covers the implicit case too: a worker that started in the worktree is stopped
    env.data["workspaces"] = []
    env.data["inspect_cwd"] = str(wt)
    own(LEAD)
    r = run_in(env, wt, "--window-middle", "strictjson", "--", "--no-wait", f"work in {wt}")
    assert r.returncode == 1 and "started in" in r.stderr and "stopped (interrupted" in r.stderr


def test_the_explicit_cwd_refusal_still_says_to_put_the_worktree_in_the_brief(env, tmp_path):
    main, wt = make_repo(tmp_path)
    r = mint(env, wt, brief="no path")
    assert r.returncode == 1 and "put that worktree in the brief" in r.stderr and "you gave no --cwd" not in r.stderr


def test_a_subdirectory_of_the_worktree_accepts_a_brief_naming_the_worktree(env, tmp_path):
    """Round 4, E1: --cwd <wt>/sub, brief names <wt>: the worktree is named."""
    main, wt = make_repo(tmp_path)
    (wt / "sub").mkdir()
    r = env.run("--lead", LEAD, "--slice", "s", "--window-middle", "strictjson", "--cwd", str(wt / "sub"), "--", "--no-wait", f"work in {wt}")
    assert r.returncode == 0, r.stderr


def test_a_directory_that_is_no_git_checkout_never_aliases_two_repos(env, tmp_path):
    """Round 4, E2a: two --repo names minted from one scratch directory are two repos, each with its own box."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER alpha (Wave 1)", "cwd": str(scratch)}]
    own(LEAD, "wks_a")
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "beta", "--window-middle", "Wave 1", "--cwd", str(scratch), "--", "--no-wait", "go")
    assert r.returncode == 0, r.stderr
    assert "--new-workspace" in placed(env)[0] and json.loads(r.stdout)["windowName"] == "WORKER beta (Wave 1)"


def test_a_launch_for_another_repo_name_from_the_checkout_of_a_box_opens_its_own_box(env, tmp_path):
    """--repo libntech from inside the cfengine-core checkout: the box of cfengine-core is another repo's, so libntech gets its own."""
    core, _ = make_repo(tmp_path, "cfengine-core")
    env.data["workspaces"] = [{"workspaceId": "wks_core", "name": "WORKER cfengine-core (Wave 1)", "cwd": os.path.realpath(core)}]
    own(LEAD, "wks_core")
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "libntech", "--window-middle", "Wave 2", "--cwd", str(core), "--", "--no-wait", "go")
    assert r.returncode == 0, r.stderr
    assert "--new-workspace" in placed(env)[0] and json.loads(r.stdout)["windowName"] == "WORKER libntech (Wave 2)"


def test_a_window_named_with_a_repo_alias_is_reused_for_the_same_checkout(env, tmp_path):
    main, wt = make_repo(tmp_path)
    env.data["workspaces"] = [{"workspaceId": "wks_alias", "name": "WORKER ade (Wave 7)", "cwd": os.path.realpath(main)}]
    own(LEAD, "wks_alias")
    r = mint(env, wt, middle="Wave 8")  # repo derived: libntech, not `ade`; the same checkout: the same box, placed at its cwd
    assert r.returncode == 0, r.stderr
    run = placed(env)[0]
    assert run[run.index("--workspace") + 1] == "wks_alias" and run[run.index("--cwd") + 1] == os.path.realpath(main)
    assert rename_calls(env) == [] and "--new-workspace" not in run


def test_a_window_of_another_checkout_is_another_repos_box(env, tmp_path):
    main, wt = make_repo(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    env.data["workspaces"] = [{"workspaceId": "wks_alias", "name": "WORKER ade (Wave 7)", "cwd": str(tmp_path / "elsewhere")}]
    own(LEAD, "wks_alias")
    r = mint(env, wt, middle="Wave 8")
    assert r.returncode == 0, r.stderr  # another checkout: another repo, so its own box
    assert "--new-workspace" in placed(env)[0]


def test_a_legacy_window_whose_directory_is_gone_is_the_box_and_the_cwd_check_refuses(env, tmp_path):
    main, wt = make_repo(tmp_path)
    env.data["workspaces"] = [{"workspaceId": "wks_leg", "name": f"workers Wave 6 {LEAD}", "cwd": str(tmp_path / "libntech-old-wt")}]
    r = mint(env, wt, middle="Typo")
    assert r.returncode == 1 and "wks_leg" in r.stderr and "runs in" in r.stderr  # taken as the box, then refused for its cwd
    assert not placed(env) and rename_calls(env) == []


def test_a_prefix_or_a_dotted_sibling_does_not_name_the_worktree(env, tmp_path):
    main, wt = make_repo(tmp_path)
    for brief in (f"copy at /mnt/backup{wt}", f"copy at /mnt/backup-{wt}", f"see {wt}.old and {wt}.bak/x"):
        r = mint(env, wt, brief=brief)
        assert r.returncode == 1 and "brief" in r.stderr, brief
    assert not placed(env)


def test_the_footer_path_never_names_the_worktree(env, tmp_path):
    """The footer carries <the script's checkout>/docs/dispatch-footer.md: a worktree that IS that checkout is not named by it."""
    main, wt = make_repo(tmp_path)
    for rel in ("bin", "docs"):
        (wt / rel).mkdir(exist_ok=True)
    for f in ("ade-worker-run", "ade_ws_names.py", "ade_lead_succession.py"):
        (wt / "bin" / f).write_text((ROOT / "bin" / f).read_text())
    (wt / "bin/ade-worker-run").chmod(0o755)
    (wt / "docs/dispatch-footer.md").write_text("footer\n")
    env.flush()
    r = subprocess.run([sys.executable, str(wt / "bin/ade-worker-run"), "--lead", LEAD, "--slice", "s", "--window-middle", "strictjson",
                        "--cwd", str(wt), "--", "--no-wait", "do the work"], capture_output=True, text=True, cwd=env.tmp)
    assert r.returncode == 1 and "brief" in r.stderr and not placed(env), r.stderr


# --- wb-01: three boxes per lead and repo, LEAD / WORKER / OTHER (operator ruling 2026-11-14) -------------------------------

def mw(env, slice_name, *args, middle=None):
    """A default (WORKER box) launch from /repo; `args` are extra ade-worker-run options before `--`."""
    mid = ["--window-middle", middle] if middle else []
    return env.run("--lead", LEAD, "--slice", slice_name, *mid, "--cwd", "/repo", *args, "--", "--no-wait", "BRIEF")


def reload(env):
    env.data = json.loads(env.data_path.read_text())  # keep what the stub renamed or created


def run_places(env):
    """(`--workspace` id or None, whether it asked for a new workspace) for every `paseo run` the stub saw."""
    out = []
    for a in placed(env):
        out.append((a[a.index("--workspace") + 1] if "--workspace" in a else None, "--new-workspace" in a))
    return out


def test_one_box_is_reused_across_slices_and_window_middles(env):
    r1 = mw(env, "a", middle="Wave 7")
    assert r1.returncode == 0, r1.stderr
    reload(env)
    r2 = mw(env, "b", middle="Something else entirely")
    r3 = mw(env, "c")
    assert r2.returncode == 0 and r3.returncode == 0, (r2.stderr, r3.stderr)
    outs = [json.loads(r.stdout) for r in (r1, r2, r3)]
    assert {o["workspaceId"] for o in outs} == {"wks_abc123"} and {o["windowName"] for o in outs} == {WIN}
    assert [o["tabName"] for o in outs] == [f"worker {x} {LEAD}" for x in "abc"]
    assert run_places(env) == [(None, True), ("wks_abc123", False), ("wks_abc123", False)]  # one workspace create
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", WIN]]  # named once, when it was opened
    assert registry(LEAD) == {"wks_abc123"}


def test_a_successor_reuses_its_predecessors_box_whatever_the_slice_and_middle(env):
    chain(PRED1, PRED2, LEAD)
    env.data["workspaces"] = [{"workspaceId": "wks_win1", "name": "WORKER repo (Old work)", "cwd": "/repo"}]
    own(PRED1, "wks_win1")
    r = mw(env, "fresh-slice", middle="Brand new work")
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [("wks_win1", False)] and rename_calls(env) == []
    assert json.loads(r.stdout)["windowName"] == "WORKER repo (Old work)"
    assert registry(LEAD) == {"wks_win1"} and registry(PRED1) == {"wks_win1"}
    assert mw(env, "again").returncode == 0 and run_places(env) == [("wks_win1", False)] * 2


@pytest.mark.parametrize("old", ["WORKERS repo (Wave 7)", f"workers repo Wave 7 {LEAD}"])
@pytest.mark.parametrize("middle", [None, "Wave 7", "Other work"])
def test_an_owned_2026_11_13_window_is_reused_and_renamed_to_the_current_kind(env, old, middle):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": old, "cwd": "/repo"}]
    own(LEAD, "wks_old1")
    r = mw(env, "beta", middle=middle)
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [("wks_old1", False)]  # no second window
    assert rename_calls(env) == [["workspace", "rename", "wks_old1", WIN]] and json.loads(r.stdout)["windowName"] == WIN
    assert env.verbs().index(["workspace", "rename"]) < env.verbs().index(["run"])
    reload(env)
    env.calls_path.unlink()
    assert mw(env, "gamma", middle=middle).returncode == 0 and rename_calls(env) == []  # renamed once, not again


@pytest.mark.parametrize("old", ["WORKERS repo (Wave 7)", f"workers repo Wave 7 {OTHER_LEAD}", "USER repo (Wave 7)"])
def test_a_2026_11_13_window_another_lead_owns_is_not_taken(env, old):
    env.data["workspaces"] = [{"workspaceId": "wks_o1", "name": old, "cwd": "/repo"}]
    own(OTHER_LEAD, "wks_o1")
    r = mw(env, "beta", middle="Wave 7")
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [(None, True)]  # the lead opens its own box
    assert all(a[2] != "wks_o1" for a in rename_calls(env)) and registry(OTHER_LEAD) == {"wks_o1"} and registry(LEAD) == {"wks_abc123"}


def test_renaming_a_2026_11_13_box_onto_a_taken_current_name_is_refused(env):
    env.data["workspaces"] = [{"workspaceId": "wks_old1", "name": "WORKERS repo (Wave 7)", "cwd": "/repo"},
                              {"workspaceId": "wks_b1", "name": WIN, "cwd": "/repo"}]
    own(LEAD, "wks_old1")
    own(OTHER_LEAD, "wks_b1")
    r = mw(env, "beta", middle="Wave 7")
    assert r.returncode == 1 and "already has that name" in r.stderr
    assert not placed(env) and rename_calls(env) == []


@pytest.mark.parametrize("flag", [["--placement", "workers"], ["--placement", "worker"], []])
def test_worker_placement_spellings_all_land_in_the_worker_box(env, flag):
    r = mw(env, "a", *flag, middle="Wave 7")
    assert r.returncode == 0, r.stderr
    run = run_argv(env)
    assert [run[i + 1] for i, x in enumerate(run) if x == "--label"] == [f"ade.lead={LEAD}", "slice=a"]  # no placement label
    assert json.loads(r.stdout)["windowName"] == WIN and json.loads(r.stdout)["tabName"] == f"worker a {LEAD}"


@pytest.mark.parametrize("flag", [["--placement", "other"], ["--other"]])
def test_other_placement_opens_the_other_box_and_reuses_it(env, flag):
    r = mw(env, "p1", *flag)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["windowName"] == OTHER_WIN and out["tabName"] == f"other p1 {LEAD}" and out["workspaceId"] == "wks_abc123"
    run = run_argv(env)
    assert [run[i + 1] for i, x in enumerate(run) if x == "--label"] == [f"ade.lead={LEAD}", "slice=p1", "ade.placement=other"]
    assert rename_calls(env) == [["workspace", "rename", "wks_abc123", OTHER_WIN]]
    assert ["agent", "update", AGENT, "--name", f"other p1 {LEAD}"] in [c["argv"] for c in env.calls()]
    assert registry(LEAD) == {"wks_abc123"}
    reload(env)
    r = mw(env, "p2", *flag, middle="probe")  # a second OTHER launch reuses it: --window-middle never opens another
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [(None, True), ("wks_abc123", False)] and json.loads(r.stdout)["tabName"] == f"other p2 {LEAD}"


def test_worker_and_other_launches_never_land_in_each_others_box(env):
    assert mw(env, "p1", "--other").returncode == 0  # OTHER repo (other) = wks_abc123
    reload(env)
    env.data["created_id"] = "wks_def456"
    env.data["run_err"] = "Created workspace wks_def456 - master (master)\n"
    r = mw(env, "w1", middle="Wave 7")  # a WORKER launch: the OTHER box is not its box
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["workspaceId"] == "wks_def456" and json.loads(r.stdout)["windowName"] == WIN
    reload(env)
    names = {w["workspaceId"]: w["name"] for w in env.data["workspaces"]}
    assert names == {"wks_abc123": OTHER_WIN, "wks_def456": WIN}
    r = mw(env, "p2", "--other")  # and an OTHER launch finds its own box again, not the WORKER one
    assert json.loads(r.stdout)["workspaceId"] == "wks_abc123" and json.loads(r.stdout)["tabName"] == f"other p2 {LEAD}"
    r = mw(env, "w2")
    assert json.loads(r.stdout)["workspaceId"] == "wks_def456" and json.loads(r.stdout)["tabName"] == f"worker w2 {LEAD}"
    assert run_places(env) == [(None, True), (None, True), ("wks_abc123", False), ("wks_def456", False)]


def test_other_box_work_text_comes_from_window_middle_when_it_is_opened(env):
    r = mw(env, "p1", "--other", middle="probe")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["windowName"] == "OTHER repo (probe)"


@pytest.mark.parametrize("old,new", [("USER repo (probe)", "OTHER repo (probe)")])
def test_an_owned_user_window_is_the_other_box_and_renamed(env, old, new):
    env.data["workspaces"] = [{"workspaceId": "wks_u1", "name": old, "cwd": "/repo"}]
    own(LEAD, "wks_u1")
    r = mw(env, "p1", "--other")
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [("wks_u1", False)] and rename_calls(env) == [["workspace", "rename", "wks_u1", new]]
    r = mw(env, "w1", middle="Wave 7")  # a WORKER launch never takes the USER/OTHER window
    assert run_places(env)[-1] == (None, True)


def test_a_lead_placement_launch_leaves_the_worker_and_other_boxes_alone(main_env):
    main_env.data["workspaces"] += [{"workspaceId": "wks_w", "name": WIN, "cwd": "/repo"}, {"workspaceId": "wks_o", "name": OTHER_WIN, "cwd": "/repo"}]
    own(LEAD, "wks_w", "wks_o")
    r = interactive(main_env, "--interactive")
    assert r.returncode == 0, r.stderr
    assert run_places(main_env) == [(LEAD_WKS, False)] and rename_calls(main_env) == []


def test_tab_name_names_the_worktree_given_with_dash_dash_worktree(env):
    r = launch(env, "s", "--worktree", "/x/djbclark-ade-foo-wt")
    assert r.returncode == 0, r.stderr
    tab = f"worker s {LEAD} [wt: djbclark-ade-foo-wt]"
    assert json.loads(r.stdout)["tabName"] == tab
    assert ["agent", "update", AGENT, "--name", tab] in [c["argv"] for c in env.calls()]
    assert "--worktree" not in run_argv(env) and "djbclark-ade-foo-wt" not in " ".join(run_argv(env)[:-1])  # a name only, not passed on


def test_tab_name_has_no_worktree_part_without_one(env):
    r = launch(env, "s")  # --cwd /repo is not a git checkout at all
    assert json.loads(r.stdout)["tabName"] == f"worker s {LEAD}"


def test_tab_name_names_a_linked_worktree_given_as_cwd_but_not_a_primary_checkout(env, tmp_path):
    main, wt = make_repo(tmp_path)
    r = mint(env, wt, slice_name="s")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tabName"] == f"worker s {LEAD} [wt: libntech-strictjson-wt]"
    reload(env)
    r = env.run("--lead", LEAD, "--slice", "s2", "--window-middle", "strictjson", "--cwd", str(main), "--", "--no-wait", "go")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tabName"] == f"worker s2 {LEAD}"  # the primary checkout is no worktree: unchanged name


def test_an_explicit_worktree_wins_over_the_cwd_and_names_the_other_box_tab(env, tmp_path):
    main, wt = make_repo(tmp_path)
    r = env.run("--lead", LEAD, "--slice", "p", "--other", "--worktree", "/x/mine-wt", "--cwd", str(wt), "--", "--no-wait", f"in {wt}")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tabName"] == f"other p {LEAD} [wt: mine-wt]"


def test_an_overlong_worktree_name_is_shortened_with_a_tilde_to_fit_the_tab_name(env):
    long_dir = "w" * 200
    r = launch(env, "s", "--worktree", f"/x/{long_dir}")
    assert r.returncode == 0, r.stderr
    tab = json.loads(r.stdout)["tabName"]
    assert len(tab) == 100 and tab.startswith(f"worker s {LEAD} [wt: www") and tab.endswith("~]")
    assert ["agent", "update", AGENT, "--name", tab] in [c["argv"] for c in env.calls()]


def test_a_slice_too_long_for_the_tab_prefix_is_refused_before_anything_runs(env):
    r = env.run("--lead", LEAD, "--slice", "s" * 60, "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "exceeds 100 characters" in r.stderr and not env.calls()


def test_several_owned_boxes_need_a_pick_by_work_text(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER repo (Alpha)", "cwd": "/repo"},
                              {"workspaceId": "wks_b", "name": "WORKER repo (Beta)", "cwd": "/repo"}]
    own(LEAD, "wks_a", "wks_b")
    r = mw(env, "s")  # no --window-middle
    assert r.returncode == 1 and "2 windows match the lead's WORKER box" in r.stderr and "wks_a" in r.stderr and "wks_b" in r.stderr
    r = mw(env, "s", middle="Gamma")  # a pick that names neither
    assert r.returncode == 1 and "2 windows match the lead's WORKER box" in r.stderr
    assert not placed(env)
    r = mw(env, "s", middle="Beta")
    assert r.returncode == 0, r.stderr
    r = mw(env, "s2", middle="Alpha")
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [("wks_b", False), ("wks_a", False)] and rename_calls(env) == []


def test_several_owned_boxes_are_picked_per_box_not_across_boxes(env):
    env.data["workspaces"] = [{"workspaceId": "wks_a", "name": "WORKER repo (Alpha)", "cwd": "/repo"},
                              {"workspaceId": "wks_b", "name": "WORKER repo (Beta)", "cwd": "/repo"},
                              {"workspaceId": "wks_o", "name": "OTHER repo (Alpha)", "cwd": "/repo"}]
    own(LEAD, "wks_a", "wks_b", "wks_o")
    r = mw(env, "s", "--other")  # the OTHER box has one window: no pick needed, and the WORKER ones do not count
    assert r.returncode == 0, r.stderr
    assert run_places(env) == [("wks_o", False)]


def test_archive_other_box_needs_the_placement_and_blocks_on_its_own_agents(window):
    window.data["workspaces"].append({"workspaceId": "wks_o1", "name": OTHER_WIN, "cwd": "/repo"})
    own(LEAD, "wks_win1", "wks_o1")
    window.data["agents"] = [{"id": "p1", "status": "running", "labels": {"ade.lead": LEAD, "ade.placement": "other"}}]
    window.state("p1", "wks_o1", {"ade.lead": LEAD, "ade.placement": "other"})
    r = window.run("archive-window", "--lead", LEAD, "--repo", "repo", "--placement", "other")
    assert r.returncode == 1 and "p1" in r.stderr and ["workspace", "archive"] not in window.verbs()
    r = window.run("archive-window", "--lead", LEAD, "--repo", "repo")  # the WORKER box does not wait for an OTHER-box tab
    assert r.returncode == 0, r.stderr
    assert [c["argv"] for c in window.calls() if c["argv"][:2] == ["workspace", "archive"]] == [["workspace", "archive", "wks_win1"]]


def test_archive_never_takes_the_lead_placement(window):
    r = window.run("archive-window", "--lead", LEAD, "--placement", "lead")
    assert r.returncode == 2 and not window.calls()  # not a choice: a LEAD window is never archived here


def test_archive_placement_workers_alias_still_works(window):
    r = window.run("archive-window", "--lead", LEAD, "--placement", "workers", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["workspaceId"] == "wks_win1"


def test_archive_refuses_a_lead_named_window_even_when_it_is_the_one_found(env):
    env.data["workspaces"] = [{"workspaceId": LEAD_WKS, "name": LEAD_NAME}]
    own(LEAD, LEAD_WKS)
    for extra in ([], ["--placement", "other"]):
        r = archive(env, *extra)
        assert r.returncode == 1 and "no " in r.stderr and ["workspace", "archive"] not in env.verbs()


def test_archive_typo_guard_still_refuses_a_middle_naming_no_box(window):
    r = window.run("archive-window", "--lead", LEAD, "--window-middle", "Typo")
    assert r.returncode == 1 and "second window" in r.stderr and "wks_win1" in r.stderr
    assert ["workspace", "archive"] not in window.verbs()


def test_rename_lead_is_the_same_command_as_rename_main(main_env):
    main_env.data["workspaces"][0]["name"] = "MAIN repo (Wave 7)"
    r = main_env.run("rename-lead", "--lead", LEAD)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["renamed"] is True and out["windowName"] == LEAD_NAME and out["previousName"] == "MAIN repo (Wave 7)"


# --- adversary round 1 of PR 732 (wb-01): closed strangers block an archive; unrenamable names are refused, not tracebacks ----

@pytest.fixture
def two_boxes(window):
    window.data["workspaces"].append({"workspaceId": "wks_o1", "name": OTHER_WIN, "cwd": "/repo"})
    own(LEAD, "wks_win1", "wks_o1")
    return window


def archive_calls(env):
    return [c["argv"] for c in env.calls() if c["argv"][:2] == ["workspace", "archive"]]


@pytest.mark.parametrize("box, wks, extra", [("other", "wks_o1", ["--placement", "other", "--repo", "repo"]),
                                             ("worker", "wks_win1", [])])
def test_a_closed_agent_nobody_here_launched_blocks_the_archive(two_boxes, box, wks, extra):
    """A1: a closed agent that is not labelled for the lead (the operator's interrupted session) would be archived with the window."""
    two_boxes.data["agents"] = [{"id": "op1", "status": "closed", "labels": {}}]
    two_boxes.state("op1", wks)
    r = two_boxes.run("archive-window", "--lead", LEAD, *extra)
    assert r.returncode == 1 and "blocker: op1: closed, but not labelled for this lead" in r.stderr
    assert json.loads(r.stdout)["archived"] is False and json.loads(r.stdout)["blockers"]
    assert archive_calls(two_boxes) == []
    two_boxes.data["agents"][0]["labels"] = {"ade.lead": OTHER_LEAD}                  # another lead's closed agent: still not ours
    two_boxes.flush()
    r = two_boxes.run("archive-window", "--lead", LEAD, *extra)
    assert r.returncode == 1 and archive_calls(two_boxes) == []


def test_a_closed_agent_labelled_for_the_lead_does_not_block_the_archive(two_boxes):
    two_boxes.data["agents"] = [{"id": "c1", "status": "closed", "labels": {"ade.lead": LEAD}}]
    two_boxes.state("c1", "wks_o1", {"ade.lead": LEAD})
    r = two_boxes.run("archive-window", "--lead", LEAD, "--placement", "other", "--repo", "repo")
    assert r.returncode == 0, r.stderr
    assert archive_calls(two_boxes) == [["workspace", "archive", "wks_o1"]]


def test_a_closed_unlabelled_agent_in_another_window_does_not_block(two_boxes):
    two_boxes.data["agents"] = [{"id": "op1", "status": "closed", "labels": {}}]
    two_boxes.state("op1", "wks_elsewhere")
    r = two_boxes.run("archive-window", "--lead", LEAD, "--placement", "other", "--repo", "repo")
    assert r.returncode == 0, r.stderr


def test_dry_run_with_a_closed_stranger_reports_the_blocker_and_archives_nothing(two_boxes):
    two_boxes.data["agents"] = [{"id": "op1", "status": "closed", "labels": {}}]
    two_boxes.state("op1", "wks_o1")
    r = two_boxes.run("archive-window", "--lead", LEAD, "--placement", "other", "--repo", "repo", "--dry-run")
    assert r.returncode == 1 and "op1" in r.stderr and "closed, but not labelled" in r.stderr
    assert archive_calls(two_boxes) == []
    assert registry(LEAD) == {"wks_win1", "wks_o1"}                                    # nothing was unregistered either


def test_a_workers_window_with_an_untrimmed_work_text_is_refused_not_a_traceback(env):
    """A5: `WORKERS repo ( x)` parses (the old kind) but its current-kind name cannot be built: refuse, launch nothing."""
    env.data["workspaces"] = [{"workspaceId": "wks_bad", "name": "WORKERS repo ( x)", "cwd": "/repo"}]
    own(LEAD, "wks_bad")
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo", "--", "--no-wait", "BRIEF")
    assert r.returncode == 1 and "Traceback" not in r.stderr and "rename it by hand" in r.stderr and "wks_bad" in r.stderr
    assert ["run"] not in env.verbs() and rename_calls(env) == []


def test_rename_main_of_a_window_with_an_untrimmed_work_text_is_refused_not_a_traceback(main_env):
    main_env.data["workspaces"][0]["name"] = "MAIN repo ( x)"
    r = main_env.run("rename-main", "--lead", LEAD)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "rename it by hand" in r.stderr and LEAD_WKS in r.stderr
    assert rename_calls(main_env) == [] and ["run"] not in main_env.verbs()


# --- am-02 (reviews of PR 732 B1, B2): a closed agent with no state file blocks; names reach stderr escaped ----

@pytest.mark.parametrize("box, wks, extra", [("other", "wks_o1", ["--placement", "other", "--repo", "repo"]),
                                             ("worker", "wks_win1", [])])
def test_a_closed_unlabelled_agent_with_no_readable_state_file_blocks_the_archive(two_boxes, box, wks, extra):
    """B1: its window is unknown, so it may be the operator's session in this window: fail closed."""
    two_boxes.data["agents"] = [{"id": "op1", "status": "closed", "labels": {}}]       # no state file written for it
    r = two_boxes.run("archive-window", "--lead", LEAD, *extra)
    assert r.returncode == 1 and "blocker: op1: closed, not labelled for this lead, and no readable state file" in r.stderr
    assert archive_calls(two_boxes) == []
    (two_boxes.home / "agents/proj").mkdir(parents=True, exist_ok=True)
    (two_boxes.home / "agents/proj" / "op1.json").write_text("{not json")               # an unparsable one is the same
    r = two_boxes.run("archive-window", "--lead", LEAD, *extra)
    assert r.returncode == 1 and "no readable state file" in r.stderr and archive_calls(two_boxes) == []
    two_boxes.state("op1", "")                                                          # a state file without a usable workspaceId
    r = two_boxes.run("archive-window", "--lead", LEAD, *extra)
    assert r.returncode == 1 and "no readable state file" in r.stderr and archive_calls(two_boxes) == []
    two_boxes.state("op1", "wks_elsewhere")                                             # its window is known and is not this one
    assert two_boxes.run("archive-window", "--lead", LEAD, *extra).returncode == 0


def test_a_closed_agent_labelled_for_the_lead_with_no_state_file_still_does_not_block(two_boxes):
    two_boxes.data["agents"] = [{"id": "c1", "status": "closed", "labels": {"ade.lead": LEAD}}]
    r = two_boxes.run("archive-window", "--lead", LEAD, "--placement", "other", "--repo", "repo")
    assert r.returncode == 0, r.stderr


def test_a_window_name_with_control_characters_is_escaped_in_a_refusal(env):
    """B2: refusal texts show the name with `!r`, so an escape sequence cannot reach the terminal."""
    weird = "WORKER repo (Wave 7\x1b[31m\x07)"
    env.data["workspaces"] = [{"workspaceId": "wks_b1", "name": weird, "cwd": "/repo"}]
    own(LEAD, "wks_b1")
    member(env, "o9", "wks_b1", lead=OTHER_LEAD)
    r = env.run("--lead", LEAD, "--slice", "alpha", "--cwd", "/repo",
                "--", "--provider", "claude/sonnet", "--no-wait", "BRIEF TEXT")
    assert r.returncode == 1, r.stderr
    assert "another lead's agents" in r.stderr and "\x1b" not in r.stderr and "\x07" not in r.stderr, r.stderr
    assert "\\x1b[31m" in r.stderr


def test_a_window_cwd_with_control_characters_is_escaped_in_the_cwd_refusal(env):
    """am-02 round 1 L4a: the window's cwd comes from Paseo too."""
    env.data["workspaces"] = [{"workspaceId": "wks_c1", "name": WIN, "cwd": "/repo\x1b[31m"}]
    own(LEAD, "wks_c1")
    r = env.run("--lead", LEAD, "--slice", "s", "--repo", "repo", "--window-middle", "Wave 7", "--cwd", "/repo-claimed-wt", "--",
                "--no-wait", "B")
    assert r.returncode == 1 and "runs in /repo" in r.stderr and "\x1b" not in r.stderr and "\\x1b[31m" in r.stderr, r.stderr
