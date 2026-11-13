"""Offline tests for bin/ade-tidy: a fake `paseo` binary serves canned JSON and records every argv; nothing contacts a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("ADE_TIDY_UNDER_TEST") or ROOT / "bin/ade-tidy")  # mutation checks point this at a mutated copy
LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61"
OTHER_LEAD = "11111111-2222-3333-4444-555555555555"
W_MAIN, W_WORK, W_USER, W_EMPTY, W_OTHER, W_FOREIGN = (f"wks_{n}" for n in ("main", "work", "user", "empty", "other", "foreign"))
STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_DATA"])
d = json.loads(path.read_text())
a = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\\n")
def save():
    path.write_text(json.dumps(d))
if a[:2] == ["ls", "-g"]:
    seq = d.get("ls_seq")
    rows = seq.pop(0) if seq and len(seq) > 1 else (seq[0] if seq else d["agents"])
    if seq is not None:
        save()
    print(json.dumps(rows))
elif a[:2] == ["workspace", "ls"]:
    print(json.dumps(d["workspaces"]))
elif a[:2] == ["permit", "ls"]:
    print(json.dumps(d.get("permits", [])))
elif a[:2] == ["terminal", "ls"]:
    if d.get("terminal_fail"):
        sys.exit(1)
    print(json.dumps(d.get("terminals", {}).get(a[a.index("--workspace") + 1], [])))
elif a[0] == "logs":
    print(d.get("logs", {}).get(a[1], ""))
elif a[0] == "send":
    print(json.dumps({"status": "sent"}))
elif a[:2] == ["workspace", "rename"]:
    for w in d["workspaces"]:
        if w["workspaceId"] == a[2]:
            w["name"] = a[3]
    save()
elif a[:2] in (["workspace", "archive"], ["agent", "archive"]):
    sys.exit(d.get("archive_rc", 0))
else:
    sys.exit(9)
'''


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.repo = tmp_path / "myrepo"
        self.wt = tmp_path / "myrepo-fix-wt"
        for cmd in (["git", "init", "-q", str(self.repo)],
                    ["git", "-C", str(self.repo), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x"],
                    ["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "fix", str(self.wt)]):
            subprocess.run(cmd, check=True, capture_output=True)
        self.data_path, self.calls_path = tmp_path / "data.json", tmp_path / "calls.jsonl"
        self.home = tmp_path / "paseo-home"
        self.reports = tmp_path / "reports"
        self.reports.mkdir()
        self.data = {"agents": [], "workspaces": [], "logs": {}, "permits": [], "terminals": {}}
        stub = tmp_path / "bin/paseo"
        stub.parent.mkdir()
        stub.write_text(STUB)
        stub.chmod(0o755)
        for k, v in {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}", "FAKE_DATA": str(self.data_path),
                     "FAKE_CALLS": str(self.calls_path), "PASEO_HOME": str(self.home),
                     "ADE_TIDY_STATE": str(tmp_path / "tidy-state.json"), "ADE_WORKER_RUN_STATE": str(tmp_path / "wr")}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("PASEO_AGENT_ID", LEAD)
        self.window(W_MAIN, "MAIN myrepo (Wave 7)", str(self.repo))
        self.window(W_WORK, "workers myrepo Wave 7 " + LEAD, str(self.repo))
        self.window(W_USER, "scratch", str(self.repo))

    def window(self, wid, name, cwd=None, project="myrepo", isolation="local"):
        self.data["workspaces"].append({"workspaceId": wid, "project": project, "name": name, "isolation": isolation,
                                        "cwd": cwd or str(self.tmp / "elsewhere" if project != "myrepo" else self.repo)})

    def record(self, aid, wks, lead=LEAD, archived=True):
        """A state record that is not in `paseo ls -g` (an archived agent, or a background one when archived=False)."""
        p = self.home / "agents/proj" / f"{aid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"id": aid, "workspaceId": wks, "labels": {"ade.lead": lead} if lead else {},
                                 **({"archivedAt": "2026-11-13T00:00:00Z"} if archived else {})}))

    def agent(self, aid, wks, name, status="idle", cwd=None, labels=None, text="", tags=None):
        self.data["agents"].append({"id": aid, "name": name, "status": status, "cwd": str(cwd or self.repo)})
        p = self.home / "agents/proj" / f"{aid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"id": aid, "workspaceId": wks, "labels": labels or {}}))
        self.data["logs"][aid] = "\n".join([*(tags or ["[Shell] ls"]), text])

    def worker(self, n, status="idle", wks=W_WORK, lead=LEAD, **kw):
        return self.agent(f"0000000{n}-0000-0000-0000-000000000000", wks, f"worker s{n} {lead}", status,
                          labels={"ade.lead": lead, "slice": f"s{n}"}, **kw)

    def run(self, *args, apply=False):
        self.data_path.write_text(json.dumps(self.data))
        cmd = [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--json", "--reports-dir", str(self.reports), *args]
        if apply:
            cmd += ["--lead", LEAD, "--apply"]
        return subprocess.run(cmd, capture_output=True, text=True)

    def calls(self):
        return [json.loads(x) for x in self.calls_path.read_text().splitlines()] if self.calls_path.exists() else []

    def mutating(self):
        return [c for c in self.calls() if c[:2] in (["workspace", "rename"], ["workspace", "archive"], ["agent", "archive"])
                or c[0] == "send"]

    def plan(self, *args):
        r = self.run(*args)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def report(self, slice_name, last="DONE", done=True, ack=False):
        rp = self.reports / f"unit-{slice_name}.md"
        rp.write_text(f"STATUS: x\n{last}\n")
        if done:
            Path(f"{rp}.done").write_text("")
        if ack:
            Path(f"{rp}.done.ack").write_text("")
        return rp


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def by_id(p):
    return {r["id"][:8]: r for r in p["agents"]}


def test_observe_changes_nothing_and_classifies(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo Wave 7", "running")
    env.worker(1, text="BLOCKED: which branch?")
    env.worker(2, lead=OTHER_LEAD)
    env.agent("00000003-0000-0000-0000-000000000000", W_USER, "my own session")
    env.agent("00000004-0000-0000-0000-000000000000", W_USER, "[Handoff writer]")
    env.window("wks_elsewhere", "other project", project="other")
    env.agent("00000005-0000-0000-0000-000000000000", "wks_elsewhere", "elsewhere", cwd=env.tmp)  # outside the repo: not listed
    p = env.plan()
    a = by_id(p)
    assert (a["8cd86203"]["class"], a["00000001"]["class"], a["00000002"]["class"]) == ("self", "own-worker", "other-worker")
    assert (a["00000003"]["class"], a["00000004"]["class"]) == ("operator", "helper")
    assert "00000005" not in a
    assert env.mutating() == []
    assert [w["id"][:8] for w in p["waiting_on_lead"]] == ["00000001"]
    assert "which branch" in p["waiting_on_lead"][0]["reason"]


def test_worktree_agent_and_window_project_count(env):
    env.agent("00000006-0000-0000-0000-000000000000", W_USER, "in worktree", cwd=env.wt / "sub")
    env.agent("00000007-0000-0000-0000-000000000000", W_USER, "by project", cwd=env.tmp)  # cwd elsewhere, window project is the repo
    assert {"00000006", "00000007"} <= set(by_id(env.plan()))


def test_verdicts(env):
    env.worker(1, "running")
    env.worker(2, text="Should I merge this?")
    env.agent("00000003-0000-0000-0000-000000000000", W_USER, "op asks", text="Do you want X or Y?")
    env.agent("00000004-0000-0000-0000-000000000000", W_USER, "op card", tags=["[Tool] AskUserQuestion"], text="")
    env.worker(5, text="done: Please reply: ack 00000005-0000-0000-0000-000000000000")
    env.worker(6, text="working on it, nothing to say")
    env.data["permits"] = [{"id": "11111111-1111-1111-1111-111111111111", "agentId": "00000007-0000-0000-0000-000000000000",
                            "name": "Bash", "description": "rm -rf secrets"}]
    env.worker(7, "running")
    a = by_id(env.plan())
    assert a["00000001"]["verdict"] == "working"
    assert a["00000002"]["verdict"] == "waiting-on-lead"  # an own worker's question goes to the lead
    assert a["00000003"]["verdict"] == "waiting-on-operator"
    assert a["00000004"]["verdict"] == "waiting-on-operator"
    assert a["00000005"]["verdict"] == "waiting-on-lead"  # asks for an ack
    assert a["00000006"]["verdict"] == "unknown"
    assert a["00000007"]["verdict"] == "waiting-on-operator" and "permission" in a["00000007"]["reason"]
    assert "rm -rf" not in a["00000007"]["reason"]   # only the tool name is shown


def test_done_needs_ack_before_archive(env):
    env.report("s1")
    env.worker(1, text="written: x")
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "waiting-on-lead" and p["archive_agents"] == []
    Path(f"{env.reports}/unit-s1.md.done.ack").write_text("")
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "done"
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]
    # handled by flag instead of an ack file
    Path(f"{env.reports}/unit-s1.md.done.ack").unlink()
    p = env.plan("--handled", "00000001-0000-0000-0000-000000000000")
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]


def test_unverified_done_is_never_archived(env):
    env.report("s2", last="not finished", done=True, ack=True)
    env.report("s3", done=False, ack=True)                                # DONE line, ack, but no .done marker
    env.worker(1, text="all done!")                                       # says done, no report
    env.worker(2, text="x")
    env.worker(3, text="x")
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "done" and "not verified" in by_id(p)["00000001"]["reason"]
    assert p["archive_agents"] == []
    # the lead passes --handled for an ack-without-.done case: that archives s3 (report ends DONE), never s2 (not DONE)
    p = env.plan("--handled", ",".join(f"0000000{n}-0000-0000-0000-000000000000" for n in (1, 2, 3)))
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000003"]


def test_question_or_blocked_beats_a_finished_report(env):
    env.report("s1", ack=True)
    env.worker(1, text="done, but should I merge now?")
    env.report("s2", ack=True)
    env.worker(2, text="BLOCKED: need a decision")
    p = env.plan()
    assert [by_id(p)[k]["verdict"] for k in ("00000001", "00000002")] == ["waiting-on-lead", "waiting-on-lead"]
    assert p["archive_agents"] == []


def test_closed_worker_is_archived_only_with_verified_done(env):
    env.worker(1, "closed", text="BLOCKED: waiting")             # interrupted by a daemon restart
    env.worker(2, "closed", text="")                             # closed, nothing known
    env.report("s3", ack=True)
    env.worker(3, "closed", text="finished")
    p = env.plan()
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000003"]
    assert {u[:8] for u in p["unreached"]} >= {"00000002"}
    assert by_id(p)["00000002"]["verdict"] == "unknown" and "closed" in by_id(p)["00000002"]["reason"]


def test_operator_agents_listed_never_archived(env):
    env.agent("00000003-0000-0000-0000-000000000000", W_USER, "mine", "closed")
    p = env.plan()
    assert p["archive_agents"] == [] and p["list_only"][0]["agent"].startswith("00000003")
    r = env.run(apply=True)
    assert r.returncode == 0 and not [c for c in env.calls() if c[:2] == ["agent", "archive"]]


def test_other_leads_workers_and_leads_untouched(env):
    env.worker(2, lead=OTHER_LEAD)
    env.agent(OTHER_LEAD, W_OTHER, "LEAD other", "idle")
    env.window(W_OTHER, "MAIN myrepo (other)")
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    sent = [c for c in env.calls() if c[0] == "send"]
    assert not any(c[3].startswith(("00000002", OTHER_LEAD[:8])) for c in sent)
    assert not [c for c in env.calls() if c[:2] == ["agent", "archive"]]


def test_send_idle_only_once_per_hour_never_steer(env):
    env.worker(1)                        # idle, unknown: gets a send
    env.worker(2, "running")             # working: nothing
    env.agent("00000003-0000-0000-0000-000000000000", W_USER, "asks", text="Which one?")  # waits on the operator: nothing
    assert env.run(apply=True).returncode == 0
    sends = [c for c in env.calls() if c[0] == "send"]
    assert len(sends) == 1 and sends[0][:3] == ["send", "--json", "--no-wait"] and "--behavior" not in sends[0]
    assert sends[0][3] == "00000001-0000-0000-0000-000000000000"
    text = sends[0][sends[0].index("--prompt") + 1]
    assert f"ack {LEAD}" in text and "ack 0000" not in text
    env.calls_path.unlink()
    assert env.run(apply=True).returncode == 0
    assert [c for c in env.calls() if c[0] == "send"] == []   # not again within the hour


def test_ack_subcommand_suppresses_send(env):
    env.worker(1)
    r = subprocess.run([sys.executable, str(SCRIPT), "ack", "00000001-0000-0000-0000-000000000000"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert env.plan()["send"] == []


def test_send_skipped_when_agent_no_longer_idle(env):
    env.worker(1)
    env.data["ls_seq"] = [list(env.data["agents"]), [{**x, "status": "running"} for x in env.data["agents"]]]
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[0] == "send"] == []
    assert "not idle now" in r.stdout


def test_apply_archives_done_worker_not_a_running_one(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    env.data["ls_seq"] = [list(env.data["agents"]), [{**x, "status": "running"} for x in env.data["agents"]]]
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[:2] == ["agent", "archive"]] == []   # went running between plan and apply
    env.data["ls_seq"] = None
    env.data["ls_seq"] = [list(env.data["agents"])]
    env.data["agents"][0]["status"] = "idle"
    r = env.run(apply=True)
    assert [c for c in env.calls() if c[:2] == ["agent", "archive"]] == [["agent", "archive", "00000001-0000-0000-0000-000000000000"]]
    assert all("--force" not in c for c in env.calls())


def test_misplaced_tab_is_reported_never_moved(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo Wave 7", "running")
    env.agent("00000003-0000-0000-0000-000000000000", W_MAIN, "operator session in MAIN")
    env.agent("00000004-0000-0000-0000-000000000000", W_MAIN, "other op")
    env.agent("00000005-0000-0000-0000-000000000000", W_USER, "lead-ish in user", labels={})
    p = env.plan()
    ids = {m["agent"][:8]: m for m in p["misplaced"]}
    assert ids["00000003"]["wantKind"] == "USER" and ids["00000003"]["windowKind"] == "MAIN"
    assert env.mutating() == []
    # the plan never calls an agent-move command: only reads
    assert all(c[0] in ("ls", "workspace", "permit", "terminal", "logs") for c in env.calls())


def test_windows_renamed_main_kept_empty_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo Wave 7", "running")
    env.worker(1, "running")
    env.window(W_EMPTY, "master")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)           # only this lead's archived worker ever lived there
    p = env.plan()
    ren = {r["windowId"]: r["to"] for r in p["renames"]}
    assert ren[W_WORK] == "WORKERS myrepo (Wave 7)" and W_MAIN not in ren   # MAIN already conforms
    assert {w["windowId"] for w in p["archive_windows"]} == {W_EMPTY}
    assert {w["windowId"] for w in p["empty_not_ours"]} == {W_USER}          # owner unknown: listed, not archived
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert ["workspace", "rename", W_WORK, "WORKERS myrepo (Wave 7)"] in env.calls()
    archived = {c[2] for c in env.calls() if c[:2] == ["workspace", "archive"]}
    assert archived == {W_EMPTY} and W_MAIN not in archived and W_WORK not in archived


def test_worktree_isolated_window_other_leads_window_and_background_agent_kept(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window("wks_wt", "slice", isolation="worktree")
    env.record("0000000c-0000-0000-0000-000000000000", "wks_wt")           # ours, but a worktree: archive would delete it
    env.window("wks_olead", "WORKERS myrepo (theirs)")
    env.record("0000000d-0000-0000-0000-000000000000", "wks_olead", lead=OTHER_LEAD)
    env.window("wks_bg", "background only")
    env.record("0000000e-0000-0000-0000-000000000000", "wks_bg", archived=False)   # background agent: not in `paseo ls -g`
    p = env.plan()
    assert not {w["windowId"] for w in p["archive_windows"]} & {"wks_wt", "wks_olead", "wks_bg", W_MAIN}
    assert {w["windowId"] for w in p["empty_not_ours"]} >= {"wks_wt", "wks_olead"}
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert not {c[2] for c in env.calls() if c[:2] == ["workspace", "archive"]} & {"wks_wt", "wks_olead", "wks_bg", W_MAIN}


def test_apply_needs_explicit_lead(env):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(env.repo), "--apply"], capture_output=True, text=True)
    assert r.returncode == 1 and "explicit --lead" in r.stderr and env.mutating() == []


def test_window_with_terminal_or_foreign_agent_not_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "master")
    env.record("0000000f-0000-0000-0000-000000000000", W_EMPTY)
    env.data["terminals"] = {W_EMPTY: [{"id": "t1"}]}
    env.agent("00000009-0000-0000-0000-000000000000", W_USER, "another repo's agent", cwd=env.tmp,
              labels={})  # in W_USER (project=myrepo) so it is in scope; also keeps W_USER occupied
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[:2] == ["workspace", "archive"]] == [["workspace", "archive", W_WORK]] or \
        {c[2] for c in env.calls() if c[:2] == ["workspace", "archive"]} == {W_WORK}
    assert "has a terminal" in r.stdout


def test_unplaced_live_agent_blocks_window_archive(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.data["agents"].append({"id": "0000000a-0000-0000-0000-000000000000", "name": "ghost", "status": "idle", "cwd": str(env.tmp)})
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[:2] == ["workspace", "archive"]] == []


def test_refuses_wrong_lead_and_non_repo(env, monkeypatch):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(env.repo), "--lead", OTHER_LEAD], capture_output=True, text=True)
    assert r.returncode == 1 and "not this agent" in r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(env.tmp)], capture_output=True, text=True)
    assert r.returncode == 1 and "not inside a git repository" in r.stderr


def test_agent_text_is_bounded_and_stripped(env):
    env.worker(1, text="BLOCKED: " + "x\x1b[31m" * 500)
    reason = env.plan()["waiting_on_lead"][0]["reason"]
    assert len(reason) <= 300 and "\x1b" not in reason


def test_report_path_outside_reports_dir_is_ignored(env):
    outside = env.tmp / "elsewhere"
    outside.mkdir()
    rp = outside / "unit-x.md"
    rp.write_text("DONE\n")
    Path(f"{rp}.done").write_text("")
    Path(f"{rp}.done.ack").write_text("")
    env.worker(1, text=f"written: {rp}")                        # path named by agent text: never used
    (env.reports / "unit-s2.md").symlink_to(rp)                 # symlink out of the reports folder
    env.worker(2, text="nothing")
    p = env.plan()
    assert not by_id(p)["00000001"]["verified_done"] and not by_id(p)["00000002"]["verified_done"]
    assert p["archive_agents"] == []


def test_terminal_list_failure_blocks_window_archive(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "master")
    env.record("0000000f-0000-0000-0000-000000000000", W_EMPTY)
    env.data["terminal_fail"] = True
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[:2] == ["workspace", "archive"]] == []
