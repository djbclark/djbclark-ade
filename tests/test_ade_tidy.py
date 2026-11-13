"""Offline tests for bin/ade-tidy: a fake `paseo` binary serves canned JSON and records every argv; nothing contacts a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

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
    n = d.get("log_calls", 0)
    d["log_calls"] = n + 1
    save()
    if d.get("flip_after") is not None and n >= d["flip_after"]:
        Path(d["flip_file"]).write_text("BLOCKED: x\\nDONE\\n")
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

    def agent(self, aid, wks, name, status="idle", cwd=None, labels=None, text="", tags=None, last_user=None):
        self.data["agents"].append({"id": aid, "name": name, "status": status, "cwd": str(cwd or self.repo)})
        p = self.home / "agents/proj" / f"{aid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"id": aid, "workspaceId": wks, "labels": labels or {}, **({"lastUserMessageAt": last_user} if last_user else {})}))
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
        self.age(rp)
        return rp

    @staticmethod
    def age(rp, epoch=None):
        """Set the report and its markers to one old time (the --handled path wants a report quiet for two minutes)."""
        t = epoch or time.time() - 600
        for q in (rp, Path(f"{rp}.done"), Path(f"{rp}.done.ack")):
            if q.exists():
                os.utime(q, (t, t))


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


def test_worktree_agent_counts_but_window_project_does_not(env):
    env.agent("00000006-0000-0000-0000-000000000000", W_USER, "in worktree", cwd=env.wt / "sub")
    env.agent("00000007-0000-0000-0000-000000000000", W_USER, "by project", cwd=env.tmp)  # cwd elsewhere, window project is the repo
    ids = set(by_id(env.plan()))
    assert "00000006" in ids and "00000007" not in ids   # scope is the agent's own cwd, not its window's directory


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


def test_blocked_report_with_done_and_ack_is_not_finished(env):
    rp = env.reports / "unit-s1.md"
    rp.write_text("BLOCKED: need an answer\nbody\nDONE\n")
    Path(f"{rp}.done").write_text("")
    Path(f"{rp}.done.ack").write_text("")
    env.worker(1, text="written: x")
    assert env.plan()["archive_agents"] == []


def test_retasked_worker_is_not_archived(env):
    rp = env.report("s1", ack=True)
    env.worker(1, text="finished", last_user="2099-01-01T00:00:00.000Z")   # a message newer than .done
    env.worker(2, text="finished")
    env.report("s2", ack=True)
    Path(f"{env.reports}/unit-s2.md.done.r1").write_text("")               # re-task marker
    assert env.plan()["archive_agents"] == []
    # --handled does not override a re-task either
    p = env.plan("--handled", "00000001-0000-0000-0000-000000000000,00000002-0000-0000-0000-000000000000")
    assert p["archive_agents"] == []


def test_inbound_message_or_unreadable_log_blocks_archive(env):
    env.report("s1", ack=True)
    env.worker(1, text="please also fix X", tags=["[Message received] 8cd86203"])   # untagged body of an inbound message
    env.report("s2", ack=True)
    env.worker(2, text="finished")
    env.data["logs"].pop("00000002-0000-0000-0000-000000000000")                  # fake prints an empty log
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "unknown" and "00000001" not in [x["agent"][:8] for x in p["archive_agents"]]


def test_handled_with_report_done_but_no_done_marker_archives(env):
    rp = env.reports / "unit-s1.md"
    rp.write_text("x\nDONE\n")
    env.age(rp)
    env.worker(1, text="finished")
    assert env.plan()["archive_agents"] == []
    p = env.plan("--handled", "00000001-0000-0000-0000-000000000000")
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]


def test_one_unacked_send_then_no_more(env):
    env.worker(1)
    assert env.run(apply=True).returncode == 0 and len([c for c in env.calls() if c[0] == "send"]) == 1
    st = json.loads(Path(os.environ["ADE_TIDY_STATE"]).read_text())
    st["sends"]["00000001-0000-0000-0000-000000000000"]["ts"] -= 10 * 3600      # long ago, still no ack
    Path(os.environ["ADE_TIDY_STATE"]).write_text(json.dumps(st))
    env.calls_path.unlink()
    p = env.plan()
    assert p["send"] == [] and p["unreached"] == ["00000001-0000-0000-0000-000000000000"]


def test_operator_requested_main_worker_needs_handled(env):
    env.report("s1", ack=True)
    env.agent("00000001-0000-0000-0000-000000000000", W_MAIN, f"worker s1 {LEAD}", labels={"ade.lead": LEAD, "slice": "s1", "ade.placement": "main"}, text="finished")
    assert env.plan()["archive_agents"] == []
    assert len(env.plan("--handled", "00000001-0000-0000-0000-000000000000")["archive_agents"]) == 1


def test_unreadable_state_record_blocks_window_archive(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "master")
    env.record("0000000f-0000-0000-0000-000000000000", W_EMPTY)
    (env.home / "agents/proj/broken.json").write_text("{not json")
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[:2] == ["workspace", "archive"]] == []


# ---- adversary round 3 -------------------------------------------------------------------------------------------

W1 = "00000001-0000-0000-0000-000000000000"


def test_agent_sourced_retask_in_log_blocks_archive_idle_and_closed(env):
    """The lead's `paseo send` re-task is a `[Message received]` entry and leaves lastUserMessageAt unchanged."""
    env.report("s1", ack=True)
    env.worker(1, text="started the build, waiting for it", tags=["[Shell] ls", "[Message received] 8cd86203", "please also fix X"])
    env.report("s2", ack=True)
    env.worker(2, "closed", text="", tags=["[Message received] 8cd86203", "round 2: add tests", "[Shell] pytest"])
    p = env.plan()
    assert p["archive_agents"] == []
    assert env.plan("--handled", f"{W1},00000002-0000-0000-0000-000000000000")["archive_agents"] == []


def test_bare_ack_message_is_not_a_retask(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished", tags=["[Shell] ls", "[Message received] 8cd86203", "ack 00000001-0000-0000-0000-000000000000 m1"])
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]


def test_human_retask_within_the_hour_under_dst(env, monkeypatch):
    """lastUserMessageAt is UTC with Z: parse it as UTC, whatever TZ and DST say (an old mktime - timezone read it an hour early)."""
    monkeypatch.setenv("TZ", "America/New_York")
    rp = env.report("s1", ack=True)
    july = 1782907200.0                                                  # 2026-07-01T12:00:00Z
    env.age(rp, july)
    env.worker(1, text="finished", last_user="2026-07-01T12:30:00.000Z")   # 30 minutes after .done
    assert env.plan()["archive_agents"] == []
    env.data["agents"].clear()
    env.worker(1, text="finished", last_user="2026-07-01T11:00:00.000Z")   # an hour before .done: not a re-task
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]


def test_unparsable_last_user_message_counts_as_retask(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished", last_user="not-a-time")
    assert env.plan()["archive_agents"] == []


def test_long_blocked_report_and_blocked_with_handled_are_never_archived(env):
    rp = env.reports / "unit-s1.md"
    rp.write_text("BLOCKED: need an answer\n" + "line of partial work\n" * 600 + "DONE\n")        # well over 4 KB
    Path(f"{rp}.done").write_text("")
    Path(f"{rp}.done.ack").write_text("")
    env.age(rp)
    env.worker(1, text="written: x")
    assert env.plan()["archive_agents"] == []
    assert env.plan("--handled", W1)["archive_agents"] == []
    rp2 = env.reports / "unit-s2.md"
    rp2.write_text("BLOCKED: q\nDONE\n")                                                          # no .done: the --handled branch
    env.age(rp2)
    env.worker(2, text="written: x")
    assert env.plan("--handled", "00000002-0000-0000-0000-000000000000")["archive_agents"] == []


def test_handled_refuses_a_report_rewritten_after_done_or_still_warm(env):
    rp = env.report("s1")                                                # .done, no ack
    time.sleep(0)
    os.utime(rp, (time.time() - 100, time.time() - 100))                 # report newer than .done (which is 600 s old)
    env.worker(1, text="finished")
    assert env.plan("--handled", W1)["archive_agents"] == []
    rp2 = env.reports / "unit-s2.md"
    rp2.write_text("x\nDONE\n")                                         # written just now: still warm
    env.worker(2, text="finished")
    assert env.plan("--handled", "00000002-0000-0000-0000-000000000000")["archive_agents"] == []


def test_empty_log_or_no_activity_is_unreadable_and_not_archived(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    env.data["logs"][W1] = ""
    env.report("s2", ack=True)
    env.worker(2, text="finished")
    env.data["logs"]["00000002-0000-0000-0000-000000000000"] = "No activity to display."
    p = env.plan()
    assert p["archive_agents"] == []
    assert by_id(p)["00000001"]["verdict"] == "unknown" and by_id(p)["00000002"]["verdict"] == "unknown"


def test_plain_reply_after_inbound_message_still_shows_blocked(env):
    env.worker(1, text="BLOCKED: which branch?", tags=["[Shell] ls", "[Message received] 8cd86203", "status please"])
    p = env.plan()
    assert [r["id"][:8] for r in p["waiting_on_lead"]] == ["00000001"]


def test_child_agent_notice_is_not_the_workers_own_words(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished child", tags=["[Shell] ls", "[Agent finished] child"])
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "unknown" and p["archive_agents"] == []


def test_archive_reruns_the_whole_verdict_at_apply(env):
    """The report turns BLOCKED between the plan and the archive call: apply re-reads it and archives nothing."""
    rp = env.report("s1", ack=True)
    env.worker(1, text="finished")
    env.data.update(flip_after=1, flip_file=str(rp))                  # the 2nd `paseo logs` call (apply's) rewrites the report
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert "no longer verified done" in r.stdout
    assert [c for c in env.calls() if c[:2] == ["agent", "archive"]] == []


def test_send_refused_without_a_session(env, monkeypatch):
    env.worker(1)
    monkeypatch.delenv("PASEO_AGENT_ID")
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[0] == "send"] == [] and "sourceless" in r.stdout


def test_send_rechecks_status_under_the_lock(env):
    env.worker(1)
    # ls calls: inventory, plan, apply start (idle) ... then the re-read inside the lock (running)
    idle, running = list(env.data["agents"]), [{**x, "status": "running"} for x in env.data["agents"]]
    env.data["ls_seq"] = [idle, idle, idle, running]
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert [c for c in env.calls() if c[0] == "send"] == []


def test_report_symlink_inside_the_reports_folder_is_refused(env):
    env.report("s1", ack=True)
    (env.reports / "unit-s2.md").symlink_to(env.reports / "unit-s1.md")
    env.worker(2, text="finished")
    p = env.plan()
    assert not by_id(p)["00000002"]["verified_done"] and p["archive_agents"] == []


# ---- after the ws-naming rebase: ade-worker-run's registry and lock order ----------------------------------------

def registry(env, lead, wids):
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lead}.windows.json").write_text(json.dumps({"windows": wids}))


def test_registered_empty_window_is_ours_and_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "WORKERS myrepo (Wave 6)")
    env.record("0000000f-0000-0000-0000-000000000000", W_EMPTY, lead=None)      # unlabelled record: ownership only via the registry
    assert [c for c in env.calls() if c[:2] == ["workspace", "archive"]] == []
    p = env.plan()
    assert W_EMPTY not in [w["windowId"] for w in p["archive_windows"]] and any(w["windowId"] == W_EMPTY for w in p["empty_not_ours"])
    registry(env, LEAD, [W_EMPTY])
    assert W_EMPTY in [w["windowId"] for w in env.plan()["archive_windows"]]


def test_other_leads_registered_window_is_never_renamed_or_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_OTHER, "workers myrepo Wave 9 " + OTHER_LEAD)
    env.record("0000000f-0000-0000-0000-000000000000", W_OTHER)                  # labelled for THIS lead, registered to the other
    registry(env, OTHER_LEAD, [W_OTHER])
    p = env.plan()
    assert W_OTHER not in [w["windowId"] for w in p["archive_windows"]] and not any(r["windowId"] == W_OTHER for r in p["renames"])
    assert env.run(apply=True).returncode == 0
    assert not [c for c in env.calls() if c[:2] in (["workspace", "archive"], ["workspace", "rename"]) and W_OTHER in c]


def test_unreadable_registry_stops_the_run(env):
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{LEAD}.windows.json").write_text("{nope")
    r = env.run()
    assert r.returncode == 1 and "unreadable" in r.stderr
    assert env.mutating() == []


def test_renaming_my_legacy_window_records_it_in_the_registry(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.worker(1, text="BLOCKED: x")                                           # keeps W_WORK occupied by this lead's worker
    assert env.run(apply=True).returncode == 0
    reg = json.loads((Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json").read_text())
    assert W_WORK in reg["windows"]
    names = {w["workspaceId"]: w["name"] for w in json.loads(env.data_path.read_text())["workspaces"]}
    assert names[W_WORK].startswith("WORKERS myrepo (")


def test_apply_takes_the_lead_lock_then_the_global_lock(env):
    env.worker(1)
    assert env.run(apply=True).returncode == 0
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    assert (d / f"{LEAD}.lock").exists() and (d / "_global.lock").exists()


# ---- adversary round 4 -------------------------------------------------------------------------------------------

def set_state(env, aid, **kw):
    p = env.home / "agents/proj" / f"{aid}.json"
    d = json.loads(p.read_text())
    d.update(kw)
    p.write_text(json.dumps(d))


def test_ack_first_retask_message_is_a_retask(env):
    env.report("s1", ack=True)
    env.worker(1, text="started the build", tags=["[Message received] 8cd86203", f"ack {W1} m1", "Round 2: add the tests", "[Shell] pytest"])
    assert env.plan()["archive_agents"] == []


def test_activity_long_after_the_ack_blocks_archive(env):
    """A re-task by `paseo send` that scrolled out of the 40-item tail still shows in lastActivityAt."""
    rp = env.report("s1", ack=True)
    ack_epoch = os.stat(f"{rp}.done.ack").st_mtime
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
    env.worker(1, text="finished")
    set_state(env, W1, lastActivityAt=iso(ack_epoch + 30))                 # replied to the ack
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]
    set_state(env, W1, lastActivityAt=iso(ack_epoch + 3600))               # worked for an hour afterwards
    assert env.plan()["archive_agents"] == []
    set_state(env, W1, lastActivityAt="garbage")
    assert env.plan()["archive_agents"] == []


def test_handled_without_done_refuses_a_later_human_prompt(env):
    rp = env.reports / "unit-s1.md"
    rp.write_text("x\nDONE\n")
    env.age(rp)
    old = os.stat(rp).st_mtime
    env.worker(1, text="finished", last_user=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(old + 60)))
    assert env.plan("--handled", W1)["archive_agents"] == []


def test_plain_reply_to_the_ack_does_not_block_archive_or_trigger_a_ping(env):
    env.report("s1", ack=True)
    env.worker(1, text="Acknowledged.", tags=["[Shell] ls", "[Message received] 8cd86203", f"ack {W1} m1"])
    p = env.plan()
    assert by_id(p)["00000001"]["verdict"] == "done" and [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]
    assert p["send"] == []


def test_legacy_rename_registers_before_renaming(env):
    d = Path(os.environ["ADE_WORKER_RUN_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    for n in (f"{LEAD}.lock", "_global.lock"):
        (d / n).write_text("")
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.worker(1, text="BLOCKED: x")                                           # W_WORK is this lead's legacy-named window
    d.chmod(0o500)                                                             # the registry cannot be written
    try:
        r = env.run(apply=True)
    finally:
        d.chmod(0o700)
    assert r.returncode == 0, r.stderr
    assert not [c for c in env.calls() if c[:2] == ["workspace", "rename"] and c[2] == W_WORK]


def test_registry_is_pruned_after_a_window_archive(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "WORKERS myrepo (Wave 6)")
    env.record("0000000f-0000-0000-0000-000000000000", W_EMPTY, lead=None)
    registry(env, LEAD, [W_EMPTY, "wks_gone"])
    assert env.run(apply=True).returncode == 0
    assert ["workspace", "archive", W_EMPTY] in env.calls()
    reg = json.loads((Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json").read_text())
    assert reg["windows"] == ["wks_gone"]


def test_tool_call_after_the_receipt_is_a_retask(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished", tags=["[Shell] ls", "[Message received] 8cd86203", f"ack {W1} m1", "[Shell] true"])
    assert env.plan()["archive_agents"] == []


# ---- adversary round 5 -------------------------------------------------------------------------------------------

def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def aged_report(env, slice_name, done_ago, ack_ago):
    rp = env.report(slice_name, ack=True)
    now = time.time()
    os.utime(rp, (now - done_ago - 5, now - done_ago - 5))
    os.utime(f"{rp}.done", (now - done_ago, now - done_ago))
    os.utime(f"{rp}.done.ack", (now - ack_ago, now - ack_ago))
    return now - done_ago, now - ack_ago


def test_human_prompt_between_done_and_a_late_ack_is_a_retask(env):
    t0, ack = aged_report(env, "s1", 6000, 600)                        # .done 100 min ago, lead acked 10 min ago
    env.worker(1, text="Acknowledged.", last_user=iso(t0 + 600),       # the operator prompted it 90 min ago
               tags=["[User] also rerun the suite", "[Shell] bg pytest", "[Message received] 8cd86203", f"ack {W1} m1"])
    set_state(env, W1, lastActivityAt=iso(ack + 20))
    assert env.plan()["archive_agents"] == []


def test_off_tail_retask_with_a_late_disk_ack_is_caught_by_activity(env):
    t0, ack = aged_report(env, "s1", 3000, 1000)                       # .done 50 min ago; ack written mid-round-2
    env.worker(1, text="suite running in the background", tags=["[Shell] ls"] * 38)    # no receipt in the tail
    set_state(env, W1, lastActivityAt=iso(ack + 200))
    assert env.plan()["archive_agents"] == []
    set_state(env, W1, lastActivityAt=iso(ack + 30))                   # idled shortly after the late ack, no receipt visible
    assert env.plan()["archive_agents"] == []
    set_state(env, W1, lastActivityAt=iso(t0 + 10))                    # idle right after its completion notice: fine
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]


def test_thought_or_longer_or_tool_reply_to_the_ack_is_still_a_finished_worker(env):
    t0, ack = aged_report(env, "s1", 600, 300)
    env.worker(1, text="Acknowledged.", tags=["[Shell] paseo send --json --no-wait lead --prompt done: x", "[Message received] 8cd86203", f"ack {W1} m1", "[Thought] they acked"])
    aged_report(env, "s2", 600, 300)
    env.worker(2, text="Nothing further.\nAll done.", tags=["[Shell] paseo send --json --no-wait lead --prompt done: x", "[Message received] 8cd86203", "ack 00000002-0000-0000-0000-000000000000 m1"])
    aged_report(env, "s3", 600, 300)
    env.worker(3, text="checked", tags=["[Shell] paseo send --json --no-wait lead --prompt done: x", "[Message received] 8cd86203", "ack 00000003-0000-0000-0000-000000000000 m1",
                                        "[Shell] completion-notice --check-ack unit-s3"])
    for n in (1, 2, 3):
        set_state(env, f"0000000{n}-0000-0000-0000-000000000000", lastActivityAt=iso(ack + 10))
    p = env.plan()
    assert sorted(x["agent"][:8] for x in p["archive_agents"]) == ["00000001", "00000002", "00000003"]
    assert p["send"] == []
    set_state(env, "00000003-0000-0000-0000-000000000000", lastActivityAt=iso(ack + 3600))        # same tail, an hour later
    assert "00000003" not in [x["agent"][:8] for x in env.plan()["archive_agents"]]


def test_failed_rename_drops_the_registry_entry_it_added(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.worker(1, text="BLOCKED: x")
    stub = env.tmp / "bin/paseo"
    stub.write_text(STUB.replace('elif a[:2] == ["workspace", "rename"]:', 'elif a[:2] == ["workspace", "rename"]:\n    sys.exit(3)'))
    assert env.run(apply=True).returncode == 0
    reg = Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json"
    assert W_WORK not in (json.loads(reg.read_text())["windows"] if reg.exists() else [])


# ---- adversary round 6 -------------------------------------------------------------------------------------------

NOTICE = "[Shell] paseo send --json --no-wait lead --prompt done: x"


def test_late_ack_explains_activity_only_when_this_rounds_notice_precedes_it(env):
    t0, ack = aged_report(env, "s1", 3000, 1000)
    env.worker(1, text="suite running", tags=["[Message received] 8cd86203", f"ack {W1} m1"])        # a receipt, but no notice before it
    set_state(env, W1, lastActivityAt=iso(ack + 30))
    assert env.plan()["archive_agents"] == []
    env.data["logs"][W1] = "\n".join([NOTICE, "[Message received] 8cd86203", f"ack {W1} m1", "suite running"])
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]


def test_newer_done_after_a_rename_is_the_next_rounds_completion(env):
    rp = env.report("s1", ack=True)
    renamed = Path(f"{rp}.done.r1")
    renamed.write_text("")
    now = time.time()
    os.utime(renamed, (now - 3000, now - 3000))                          # the round-1 marker, renamed
    for q in (rp, Path(f"{rp}.done"), Path(f"{rp}.done.ack")):
        os.utime(q, (now - 600, now - 600))                              # round 2's own completion, acked
    env.worker(1, text="finished", tags=[NOTICE])
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]
    os.utime(renamed, (now - 100, now - 100))                            # a rename newer than .done: re-tasked since
    assert env.plan()["archive_agents"] == []


def test_reply_tools_are_shell_commands_or_the_send_tool_not_edits(env):
    aged_report(env, "s1", 600, 300)
    env.worker(1, text="ok", tags=[NOTICE, "[Message received] 8cd86203", f"ack {W1} m1", "[Send message] lead"])
    aged_report(env, "s2", 600, 300)
    env.worker(2, text="ok", tags=[NOTICE, "[Message received] 8cd86203", "ack 00000002-0000-0000-0000-000000000000 m1",
                                   "[Edit] bin/completion-notice"])
    p = env.plan()
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]


def test_a_peers_earlier_ack_does_not_make_later_ordinary_work_a_retask(env):
    aged_report(env, "s1", 600, 300)
    env.worker(1, text="finished", tags=[NOTICE, "[Message received] peer", f"ack {W1} m0", "[Shell] ls", "[Shell] git status",
                                         "[Message received] 8cd86203", f"ack {W1} m1"])
    assert [x["agent"][:8] for x in env.plan()["archive_agents"]] == ["00000001"]


# ---- adversary round 7 -------------------------------------------------------------------------------------------

def late_ack_worker(env, tags, reply="Acknowledged."):
    """A worker whose round-1 report is acked late (ack 60 s ago, .done 1 h ago) and idled 40 s after the ack."""
    t0, ack = aged_report(env, "s1", 3600, 60)
    env.worker(1, text=reply, tags=tags)
    set_state(env, W1, lastActivityAt=iso(ack + 40))
    return env.plan()


def test_a_notice_must_be_the_last_tool_call_before_the_ack_and_the_command_itself(env):
    receipt = ["[Message received] 8cd86203", f"ack {W1} m1"]
    mention = ['[Shell] rg -n "paseo send" bin/', "[Edit] bin/completion-notice", "[Shell] nohup make test &"]
    assert late_ack_worker(env, mention + receipt)["archive_agents"] == []                        # B1: a mention, then work
    env.data["agents"].clear()
    assert late_ack_worker(env, ["[Shell] git diff bin/completion-notice", "[Shell] bin/pytest -x &"] + receipt)["archive_agents"] == []   # B3
    env.data["agents"].clear()
    peer = ["[Shell] paseo send --no-wait peer --prompt 'started suite. Please reply: ack W'", "[Message received] peer", f"ack {W1}"]
    assert late_ack_worker(env, peer)["archive_agents"] == []                                    # B2: a peer's ack, one token
    env.data["agents"].clear()
    assert late_ack_worker(env, [NOTICE, *receipt])["archive_agents"][0]["agent"] == W1         # control: the real flow


def test_ack_plus_task_with_edits_of_the_notice_tool_is_a_retask(env):
    p = late_ack_worker(env, [NOTICE, "[Message received] 8cd86203", f"ack {W1} m1", "also fix the bug",
                              "[Shell] gsed -i s/a/b/ bin/completion-notice", "[Shell] git commit -am fix bin/completion-notice"], "fixed.")
    assert p["archive_agents"] == []


def test_peer_ack_before_the_notice_does_not_void_the_leads_later_receipt(env):
    tags = ["[Message received] peer", f"ack {W1} m0", "[Shell] make test", "[Shell] bin/completion-notice --send --requester x --title t",
            "[Message received] 8cd86203", f"ack {W1} m1"]
    assert [x["agent"] for x in late_ack_worker(env, tags)["archive_agents"]] == [W1]


def test_other_notice_forms_count_as_the_notice(env):
    receipt = ["[Message received] 8cd86203", f"ack {W1} m1"]
    for notice in ("[Send message] lead done: x", "[Shell] python3 ~/src/session-finder/relay.py send lead done: x",
                   "[Shell] bin/completion-notice --send --requester x --title t"):
        env.data["agents"].clear()
        assert [x["agent"] for x in late_ack_worker(env, [notice, *receipt])["archive_agents"]] == [W1], notice
