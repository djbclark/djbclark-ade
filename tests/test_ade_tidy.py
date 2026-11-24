"""Offline tests for bin/ade-tidy: a fake `paseo` binary serves canned JSON and records every argv; nothing contacts a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402 - the claims registry the tidy script reads (ADE_STATE_DIR)
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
                     "ADE_TIDY_STATE": str(tmp_path / "tidy-state.json"), "ADE_WORKER_RUN_STATE": str(tmp_path / "wr"),
                     "ADE_STATE_DIR": str(tmp_path / "ade-state"), "ADE_SELF_SESSION_STATE": str(tmp_path / "self-session")}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("PASEO_AGENT_ID", LEAD)
        self.window(W_MAIN, "LEAD myrepo (Wave 7)", str(self.repo))
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

    def run(self, *args, apply=False, as_json=True):
        self.data_path.write_text(json.dumps(self.data))
        cmd = [sys.executable, str(SCRIPT), "--repo", str(self.repo), *(["--json"] if as_json else []), "--reports-dir", str(self.reports), *args]
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
    env.window(W_OTHER, "LEAD myrepo (other)")
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
    assert ids["00000003"]["wantKind"] == "OTHER" and ids["00000003"]["windowKind"] == "LEAD"
    assert env.mutating() == []
    # the plan never calls an agent-move command: only reads
    assert all(c[0] in ("ls", "workspace", "permit", "terminal", "logs") for c in env.calls())


def test_windows_renamed_lead_kept_empty_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo Wave 7", "running")
    env.worker(1, "running")
    env.window(W_EMPTY, "master")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)           # only this lead's archived worker ever lived there
    p = env.plan()
    ren = {r["windowId"]: r["to"] for r in p["renames"]}
    assert ren[W_WORK] == "WORKER myrepo (Wave 7)" and W_MAIN not in ren   # LEAD already conforms
    assert {w["windowId"] for w in p["archive_windows"]} == {W_EMPTY}
    assert {w["windowId"] for w in p["empty_not_ours"]} == {W_USER}          # owner unknown: listed, not archived
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert ["workspace", "rename", W_WORK, "WORKER myrepo (Wave 7)"] in env.calls()
    archived = {c[2] for c in env.calls() if c[:2] == ["workspace", "archive"]}
    assert archived == {W_EMPTY} and W_MAIN not in archived and W_WORK not in archived


def test_worktree_isolated_window_other_leads_window_and_background_agent_kept(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window("wks_wt", "slice", isolation="worktree")
    env.record("0000000c-0000-0000-0000-000000000000", "wks_wt")           # ours, but a worktree: archive would delete it
    env.window("wks_olead", "WORKER myrepo (theirs)")
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
    env.window(W_EMPTY, "WORKER myrepo (Wave 6)")
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
    assert names[W_WORK].startswith("WORKER myrepo (")


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
    env.window(W_EMPTY, "WORKER myrepo (Wave 6)")
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
    env.data["agents"].clear()
    after = [NOTICE, "[Shell] bin/pytest -x &", "[Edit] bin/ade-tidy", *receipt]                  # notice, then more work, then the ack
    assert late_ack_worker(env, after)["archive_agents"] == []
    env.data["agents"].clear()
    grep = ['[Shell] rg -n "paseo send --no-wait lead done: x" bin/ tests/']                  # a command that only mentions the notice
    assert late_ack_worker(env, grep + receipt)["archive_agents"] == []
    env.data["agents"].clear()
    assert late_ack_worker(env, [NOTICE, "[Message received] 8cd86203", f"ack {W1}"])["archive_agents"] == []   # one-token ack: no receipt


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


# ---- wb-01 (operator ruling 2026-11-14): three boxes LEAD / WORKER / OTHER per lead and repo ---------------------------------

PRED = "22222222-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
W2, W3 = ("0000000%d-0000-0000-0000-000000000000" % n for n in (2, 3))


def rename_window(env, wid, name):
    next(w for w in env.data["workspaces"] if w["workspaceId"] == wid)["name"] = name


def archived_windows(env):
    return {c[2] for c in env.calls() if c[:2] == ["workspace", "archive"]}


def archived_agents(env):
    return {c[2] for c in env.calls() if c[:2] == ["agent", "archive"]}


def link_handoff(pred, nxt, status="archived"):
    d = Path(os.environ["ADE_SELF_SESSION_STATE"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"handoff-{pred}.json").write_text(json.dumps(
        {"kind": "handoff", "predecessor": pred, "successor": nxt, "status": status, "ack": {"agent_id": nxt},
         "home": str(Path(os.environ["PASEO_HOME"]).resolve())}))


def write_claim(env, cid="c1", state="active", expires_at=None, **owner):
    c = ade_claims.make_claim(id=cid, path=env.wt, branch="fix", base_sha="0" * 40, **owner)
    c["state"] = state
    if expires_at:
        c["expires_at"] = expires_at
    ade_claims.write_claim(c)


def test_old_kind_window_names_are_renamed_to_the_current_kinds(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.worker(1, "running")
    rename_window(env, W_MAIN, "MAIN myrepo (Wave 7)")
    rename_window(env, W_WORK, "WORKERS myrepo (Wave 8)")
    p = env.plan()
    assert {r["windowId"]: r["to"] for r in p["renames"]} == {W_MAIN: "LEAD myrepo (Wave 7)", W_WORK: "WORKER myrepo (Wave 8)"}
    assert env.run(apply=True).returncode == 0
    assert ["workspace", "rename", W_MAIN, "LEAD myrepo (Wave 7)"] in env.calls()
    assert ["workspace", "rename", W_WORK, "WORKER myrepo (Wave 8)"] in env.calls()
    assert not archived_windows(env) & {W_MAIN, W_WORK}


def test_old_main_window_is_never_archived_even_with_no_agents(env):
    env.window(W_EMPTY, "MAIN myrepo (Wave 5)")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)
    p = env.plan()
    assert W_EMPTY not in [w["windowId"] for w in p["archive_windows"]]
    assert env.run(apply=True).returncode == 0
    assert W_EMPTY not in archived_windows(env)


def test_second_worker_window_is_extra_and_archived_when_empty(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")
    env.worker(2, "running")                                                    # the keeper: most live agents
    env.window(W_EMPTY, "WORKER myrepo (Wave 8)")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)                 # only this lead's archived worker ever lived there
    p = env.plan()
    ex = {e["windowId"]: e for e in p["extra_windows"]}
    assert set(ex) == {W_EMPTY}
    assert ex[W_EMPTY]["box"] == "WORKER" and ex[W_EMPTY]["live"] == 0 and ex[W_EMPTY]["archive"] is True
    assert ex[W_EMPTY]["why"].startswith("second WORKER window") and W_WORK in ex[W_EMPTY]["why"]
    assert env.run(apply=True).returncode == 0
    assert archived_windows(env) == {W_EMPTY}                                   # the keeper stays


def test_keeper_is_the_window_with_more_live_agents_whatever_the_id(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")                                                    # W_WORK: one live agent
    env.window(W_EMPTY, "WORKER myrepo (Wave 8)")
    env.worker(2, "running", wks=W_EMPTY)
    env.worker(3, "running", wks=W_EMPTY)                                       # W_EMPTY: two, so it keeps its place
    ex = {e["windowId"]: e for e in env.plan()["extra_windows"]}
    assert set(ex) == {W_WORK} and ex[W_WORK]["archive"] is False and ex[W_WORK]["live"] == 1


def test_dry_run_archives_nothing_and_lists_section_h(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")
    env.window(W_EMPTY, "WORKER myrepo (Wave 8)")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)
    r = env.run(as_json=False)
    assert r.returncode == 0, r.stderr
    assert "H. Windows beyond the three boxes" in r.stdout and f"H1. {W_EMPTY}" in r.stdout and "second WORKER window" in r.stdout
    assert "--apply archives it" in r.stdout
    assert env.mutating() == []
    env.data["workspaces"] = [w for w in env.data["workspaces"] if w["workspaceId"] != W_EMPTY]    # nothing extra: H still shown
    r = env.run(as_json=False)
    assert "H. Windows beyond the three boxes" in r.stdout and "H-. none" in r.stdout


def test_other_leads_worker_windows_are_never_extra_or_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")
    env.window(W_OTHER, "WORKER myrepo (Wave 9)")                               # registered to the other lead, empty
    env.record("0000000f-0000-0000-0000-000000000000", W_OTHER, lead=OTHER_LEAD)
    registry(env, OTHER_LEAD, [W_OTHER])
    env.window(W_FOREIGN, "WORKER myrepo (theirs)")                             # holds the other lead's live worker
    env.worker(5, "idle", wks=W_FOREIGN, lead=OTHER_LEAD)
    p = env.plan()
    assert not {e["windowId"] for e in p["extra_windows"]} & {W_OTHER, W_FOREIGN}
    assert not {w["windowId"] for w in p["archive_windows"]} & {W_OTHER, W_FOREIGN}
    assert env.run(apply=True).returncode == 0
    assert not archived_windows(env) & {W_OTHER, W_FOREIGN} and not archived_agents(env)


def test_predecessor_chain_window_is_ours_and_archivable(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "WORKER myrepo (old wave)")
    registry(env, PRED, [W_EMPTY])                                              # registered under the predecessor lead
    env.window(W_OTHER, "WORKER myrepo (older)")
    env.record("0000000f-0000-0000-0000-000000000000", W_OTHER, lead=PRED)      # only the predecessor's archived worker lived there
    p = env.plan()                                                              # no completed handoff yet: another lead's, not ours
    assert not {W_EMPTY, W_OTHER} & {w["windowId"] for w in p["archive_windows"]}
    assert W_EMPTY not in {e["windowId"] for e in p["extra_windows"]}
    link_handoff(PRED, LEAD)
    p = env.plan()
    assert {W_EMPTY, W_OTHER} <= {w["windowId"] for w in p["archive_windows"]}
    # three WORKER windows of the chain (the Env's own W_WORK too): the current-form name with the lowest id (W_EMPTY) is the keeper
    assert [e["windowId"] for e in p["extra_windows"]] == [W_OTHER, W_WORK]
    assert env.run(apply=True).returncode == 0
    assert {W_EMPTY, W_OTHER} <= archived_windows(env) and W_MAIN not in archived_windows(env)
    link_handoff(PRED, LEAD, status="pending")                                  # a handoff that did not complete is no succession
    assert W_EMPTY not in {w["windowId"] for w in env.plan()["archive_windows"]}


def test_predecessor_labelled_worker_is_own_worker_and_archivable(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished", lead=PRED)
    assert by_id(env.plan())["00000001"]["class"] == "other-worker"             # no ledger: someone else's
    assert env.plan()["archive_agents"] == []
    link_handoff(PRED, LEAD)
    p = env.plan()
    assert by_id(p)["00000001"]["class"] == "own-worker"
    assert [x["agent"][:8] for x in p["archive_agents"]] == ["00000001"]
    assert env.run(apply=True).returncode == 0
    assert archived_agents(env) == {W1}


def test_running_agent_keeps_its_window_and_extra_is_not_archived(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")
    env.worker(2, "running")
    env.window(W_EMPTY, "WORKER myrepo (Wave 8)")
    env.worker(3, "running", wks=W_EMPTY)
    p = env.plan()
    ex = {e["windowId"]: e for e in p["extra_windows"]}
    assert set(ex) == {W_EMPTY} and ex[W_EMPTY]["archive"] is False and ex[W_EMPTY]["live"] == 1
    assert W_EMPTY not in {w["windowId"] for w in p["archive_windows"]}
    assert env.run(apply=True).returncode == 0
    assert archived_windows(env) == set() and archived_agents(env) == set()


def test_finished_worker_alone_in_an_extra_window_archives_agent_then_window(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "WORKER myrepo (Wave 7)")
    env.worker(1, "running")
    env.worker(2, "running")
    env.window(W_EMPTY, "WORKER myrepo (Wave 8)")
    env.report("s3", ack=True)
    env.worker(3, "idle", wks=W_EMPTY, text="finished")
    p = env.plan()
    ex = {e["windowId"]: e for e in p["extra_windows"]}
    assert ex[W_EMPTY]["archive"] is True                                       # its only occupant is archiving this run
    assert [x["agent"] for x in p["archive_agents"]] == [W3]


@pytest.mark.parametrize("owner_key", ["owner_agent", "owner_record", "owner_session"])
def test_done_worker_holding_an_active_claim_is_not_archived(env, owner_key):
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    write_claim(env, **{owner_key: W1})
    p = env.plan()
    assert p["archive_agents"] == [] and [x["agent"] for x in p["claim_held"]] == [W1]
    assert W_WORK not in {w["windowId"] for w in p["archive_windows"]}
    assert "G1c." in subprocess.run([sys.executable, str(SCRIPT), "--repo", str(env.repo), "--reports-dir", str(env.reports)],
                                    capture_output=True, text=True).stdout
    assert env.run(apply=True).returncode == 0
    assert archived_agents(env) == set() and archived_windows(env) == set()


@pytest.mark.parametrize("state, expires_at", [("released", None), ("merged", None), ("active", "2020-01-01T00:00:00Z")])
def test_done_worker_with_a_released_or_expired_claim_is_archived(env, state, expires_at):
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    write_claim(env, state=state, expires_at=expires_at, owner_agent=W1)
    p = env.plan()
    assert [x["agent"] for x in p["archive_agents"]] == [W1] and p["claim_held"] == []
    assert env.run(apply=True).returncode == 0
    assert archived_agents(env) == {W1}


def test_done_worker_with_no_claim_is_archived_and_another_agents_claim_is_irrelevant(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    write_claim(env, owner_agent=W2)                                            # an active claim, but another agent's
    p = env.plan()
    assert [x["agent"] for x in p["archive_agents"]] == [W1] and p["claim_held"] == []


def test_window_named_outside_the_scheme_is_extra_with_no_box_but_the_leads_own_window_never(env):
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_MAIN, "my-lead-window")                                # the lead's own window, off-scheme
    registry(env, LEAD, [W_MAIN])                                               # provably ours, so only its LEAD kind exempts it
    env.window(W_EMPTY, "master")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)                 # ours (labelled), empty
    p = env.plan()
    ex = {e["windowId"]: e for e in p["extra_windows"]}
    assert set(ex) == {W_EMPTY} and ex[W_EMPTY]["box"] is None and ex[W_EMPTY]["why"] == "named outside the scheme"
    assert ex[W_EMPTY]["archive"] is True
    assert env.run(apply=True).returncode == 0
    assert W_EMPTY in archived_windows(env) and W_MAIN not in archived_windows(env)


def test_off_scheme_window_of_unknown_owner_is_not_extra(env):
    env.window(W_EMPTY, "master")                                               # no record, no registry: owner unknown
    p = env.plan()
    assert W_EMPTY not in {e["windowId"] for e in p["extra_windows"]}
    assert W_EMPTY in {w["windowId"] for w in p["empty_not_ours"]}


def test_work_option_accepts_the_new_kinds_and_refuses_the_old(env):
    rename_window(env, W_MAIN, "scratch lead")
    rename_window(env, W_WORK, "scratch worker")
    rename_window(env, W_USER, "scratch other")
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.worker(1, "running")
    env.agent("00000003-0000-0000-0000-000000000000", W_USER, "operator session")
    p = env.plan("--work", "LEAD=Wave 9", "--work", "WORKER=Hotfix", "--work", "OTHER=Probe")
    assert {r["windowId"]: r["to"] for r in p["renames"]} == {
        W_MAIN: "LEAD myrepo (Wave 9)", W_WORK: "WORKER myrepo (Hotfix)", W_USER: "OTHER myrepo (Probe)"}
    r = env.run("--work", "MAIN=Wave 9")
    assert r.returncode == 1 and "--work wants KIND=TEXT" in r.stderr
    assert env.mutating() == []


def test_claim_taken_between_plan_and_apply_stops_the_agent_archive(env):
    """The apply re-reads the claim registry right before `agent archive` (the stub writes the claim at the 3rd `ls -g`)."""
    env.report("s1", ack=True)
    env.worker(1, text="finished")
    claim_path = Path(os.environ["ADE_STATE_DIR"]) / "claims" / "late.json"
    claim = ade_claims.make_claim(id="late", path=env.wt, branch="fix", base_sha="0" * 40, owner_agent=W1)
    env.data.update(claim_at=3, claim_path=str(claim_path), claim_json=json.dumps(claim))
    stub = env.tmp / "bin/paseo"
    stub.write_text(STUB.replace('if a[:2] == ["ls", "-g"]:\n', 'if a[:2] == ["ls", "-g"]:\n'
                    '    d["ls_n"] = d.get("ls_n", 0) + 1\n    save()\n'
                    '    if d["ls_n"] >= d.get("claim_at", 99):\n        Path(d["claim_path"]).parent.mkdir(parents=True, exist_ok=True)\n'
                    '        Path(d["claim_path"]).write_text(d["claim_json"])\n', 1))
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert "holds an active claim: skipped" in r.stdout and archived_agents(env) == set()


# ---- adversary round 1 of PR 732 (wb-01): fail-closed claims, chain-aware renames and unregistering ----------------

def done_worker(env):
    env.report("s1", ack=True)
    env.worker(1, text="finished")


def test_corrupt_claim_file_stops_the_apply_and_archives_nothing(env):
    """A2: a claim file that does not parse leaves ownership of a worktree unknown: no agent and no window is archived."""
    done_worker(env)
    d = Path(os.environ["ADE_STATE_DIR"]) / "claims"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{nope")
    r = env.run(apply=True)
    assert r.returncode == 1 and "claim" in r.stderr and "nothing is archived" in r.stderr and "Traceback" not in r.stderr
    assert env.mutating() == []


def test_corrupt_claim_file_is_a_listed_warning_in_a_dry_run_not_a_refusal(env):
    """am-02 (wb-01 review B3): the read-only plan still prints sections A to H; it lists no archive it cannot clear and says why."""
    done_worker(env)
    env.window(W_EMPTY, "master")
    env.record("0000000b-0000-0000-0000-000000000000", W_EMPTY)           # an empty window of this lead's: archivable with a good registry
    assert {w["windowId"] for w in env.plan()["archive_windows"]} == {W_WORK, W_EMPTY}     # the done worker's too, once it is archived
    d = Path(os.environ["ADE_STATE_DIR"]) / "claims"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{nope")
    r = env.run(as_json=False)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    assert "A. Inventory" in r.stdout and "H. Windows" in r.stdout
    assert "WARNING: claims unknown" in r.stdout and "bad.json" in r.stdout and "--apply refuses the whole run" in r.stdout
    assert "archive agent" not in r.stdout and "archive window" not in r.stdout
    p = env.plan()
    assert [w for w in p["archive_windows"]] == []
    assert p["archive_agents"] == [] and p["archive_windows"] == [] and p["claim_held"] == []
    assert any(n.startswith("WARNING: claims unknown") for n in p["notes"])
    assert env.mutating() == []
    r = env.run(apply=True)                                                     # --apply still fails closed, before any change
    assert r.returncode == 1 and "bad.json" in r.stderr and "nothing is archived" in r.stderr and "Traceback" not in r.stderr
    assert env.mutating() == []
    (d / "bad.json").unlink()                                                   # a good registry: the same plan archives again
    p = env.plan()
    assert [x["agent"] for x in p["archive_agents"]] == [W1] and {w["windowId"] for w in p["archive_windows"]} == {W_WORK, W_EMPTY}


def test_unreadable_claims_dir_stops_the_apply_and_archives_nothing(env):
    """A2: a claims directory that cannot be listed is not "no claims"."""
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 directory")
    done_worker(env)
    d = Path(os.environ["ADE_STATE_DIR"]) / "claims"
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        r = env.run(apply=True)
    finally:
        d.chmod(0o700)
    assert r.returncode == 1 and "claims directory" in r.stderr and "cannot be read" in r.stderr and "Traceback" not in r.stderr
    assert env.mutating() == []


def test_missing_claims_dir_is_no_claims_and_the_apply_archives_as_before(env):
    done_worker(env)
    assert not (Path(os.environ["ADE_STATE_DIR"]) / "claims").exists()
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert archived_agents(env) == {W1}


def test_legacy_window_of_a_predecessor_is_registered_then_renamed(env):
    """A3: `workers <middle> <predecessor id>` of a completed self-handoff chain: ownership is recorded under the successor
    before the predecessor's id leaves the name."""
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    rename_window(env, W_WORK, "workers myrepo Wave 7 " + PRED)
    env.worker(1, text="BLOCKED: x")                                            # this lead's worker keeps the window occupied
    p = env.plan()                                                              # no completed handoff yet: another lead's window
    assert not any(r["windowId"] == W_WORK for r in p["renames"])
    link_handoff(PRED, LEAD)
    assert [r["to"] for r in env.plan()["renames"] if r["windowId"] == W_WORK] == ["WORKER myrepo (Wave 7)"]
    r = env.run(apply=True)
    assert r.returncode == 0, r.stderr
    assert ["workspace", "rename", W_WORK, "WORKER myrepo (Wave 7)"] in env.calls()
    reg = json.loads((Path(os.environ["ADE_WORKER_RUN_STATE"]) / f"{LEAD}.windows.json").read_text())
    assert W_WORK in reg["windows"]


@pytest.mark.parametrize("also_current_leads", [False, True])
def test_archiving_a_predecessors_empty_box_unregisters_it_from_the_predecessors_record(env, also_current_leads):
    """A4: the window id leaves every chain member's `<lead>.windows.json`, as ade-worker-run archive-window does."""
    env.agent(LEAD, W_MAIN, "LEAD myrepo", "running")
    env.window(W_EMPTY, "WORKER myrepo (old wave)")
    registry(env, PRED, [W_EMPTY, "wks_kept"])
    if also_current_leads:
        registry(env, LEAD, [W_EMPTY])
    link_handoff(PRED, LEAD)
    assert W_EMPTY in {w["windowId"] for w in env.plan()["archive_windows"]}
    assert env.run(apply=True).returncode == 0
    assert W_EMPTY in archived_windows(env)
    wr = Path(os.environ["ADE_WORKER_RUN_STATE"])
    assert json.loads((wr / f"{PRED}.windows.json").read_text())["windows"] == ["wks_kept"]
    if also_current_leads:
        assert W_EMPTY not in json.loads((wr / f"{LEAD}.windows.json").read_text())["windows"]


# ----------------------------------------------------------------------------------------------- idle-hours (Queue #91 & #96)

IDLE_PS_STUB = '''#!/usr/bin/env python3
import json, os
from pathlib import Path
d = json.loads(Path(os.environ["FAKE_DATA"]).read_text())
print("\\n".join(d.get("ps", [])))
'''


class NoPathIdleEnv:
    """Offline test harness for `--idle-hours` that injects fake `paseo` and `ps` via explicit env vars
    (`ADE_TIDY_PASEO`, `ADE_TIDY_PS` + `ADE_TIDY_TEST=1`) with NO `PATH` modification (code-review rule 2)."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.repo = tmp_path / "myrepo"
        for cmd in (["git", "init", "-q", str(self.repo)],
                    ["git", "-C", str(self.repo), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, check=True, capture_output=True)
        self.data_path = tmp_path / "data.json"
        self.calls_path = tmp_path / "calls.jsonl"
        self.home = tmp_path / "paseo-home"
        self.reports = tmp_path / "reports"
        self.lw_dir = tmp_path / "load-watch"
        self.reports.mkdir()
        self.lw_dir.mkdir()
        self.data = {"agents": [], "workspaces": [], "logs": {}, "permits": [], "terminals": {}, "ps": []}
        self.paseo_stub = tmp_path / "fake-paseo"
        self.paseo_stub.write_text(STUB)
        self.paseo_stub.chmod(0o755)
        self.ps_stub = tmp_path / "fake-ps"
        self.ps_stub.write_text(IDLE_PS_STUB)
        self.ps_stub.chmod(0o755)
        for k, v in {
            "ADE_TIDY_PASEO": str(self.paseo_stub),
            "ADE_TIDY_PS": str(self.ps_stub),
            "ADE_TIDY_TEST": "1",
            "FAKE_DATA": str(self.data_path),
            "FAKE_CALLS": str(self.calls_path),
            "PASEO_HOME": str(self.home),
            "LW_STATE_DIR": str(self.lw_dir),
            "ADE_TIDY_STATE": str(tmp_path / "tidy-state.json"),
            "ADE_WORKER_RUN_STATE": str(tmp_path / "wr"),
            "ADE_STATE_DIR": str(tmp_path / "ade-state"),
            "ADE_SELF_SESSION_STATE": str(tmp_path / "self-session"),
            "PASEO_AGENT_ID": LEAD,
        }.items():
            monkeypatch.setenv(k, v)
        self.window(W_MAIN, "LEAD myrepo (Wave 7)")
        self.window(W_WORK, "WORKER myrepo (Wave 7)")
        self.agent(LEAD, W_MAIN, "LEAD myrepo", status="running", hours_ago=0.1)

    @staticmethod
    def iso_ago(hours: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - hours * 3600.0))

    def window(self, wid: str, name: str, isolation: str = "local") -> None:
        self.data["workspaces"].append({"workspaceId": wid, "project": "myrepo", "name": name,
                                        "isolation": isolation, "cwd": str(self.repo)})

    def agent(self, aid: str, wks: str, name: str, status: str = "idle", labels: dict | None = None,
              hours_ago: float = 5.0, text: str = "finished task", tags: list[str] | None = None,
              session_id: str | None = None) -> str:
        self.data["agents"].append({"id": aid, "name": name, "status": status, "cwd": str(self.repo)})
        p = self.home / "agents/proj" / f"{aid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec: dict = {"id": aid, "workspaceId": wks, "labels": labels or {}, "lastActivityAt": self.iso_ago(hours_ago)}
        if session_id:
            rec["persistence"] = {"sessionId": session_id}
        p.write_text(json.dumps(rec))
        self.data["logs"][aid] = "\n".join([*(tags or ["[Shell] ls"]), text])
        return aid

    def run(self, *args: str, apply: bool = False, as_json: bool = True) -> subprocess.CompletedProcess[str]:
        self.data_path.write_text(json.dumps(self.data))
        cmd = [sys.executable, str(SCRIPT), "--repo", str(self.repo), *(["--json"] if as_json else []),
               "--reports-dir", str(self.reports), *args]
        if apply:
            cmd += ["--lead", LEAD, "--apply"]
        return subprocess.run(cmd, capture_output=True, text=True)

    def calls(self) -> list[list[str]]:
        return [json.loads(x) for x in self.calls_path.read_text().splitlines()] if self.calls_path.exists() else []

    def archived_agents(self) -> set[str]:
        return {c[2] for c in self.calls() if c[:2] == ["agent", "archive"]}


def test_idle_hours_off_by_default_and_rejects_nonpositive(tmp_path: Path, monkeypatch) -> None:
    e = NoPathIdleEnv(tmp_path, monkeypatch)
    e.agent("10000001-0000-0000-0000-000000000000", W_WORK, "adhoc probe", labels={"ade.lead": LEAD}, hours_ago=8.0)
    r_off = e.run(as_json=False)
    assert r_off.returncode == 0 and "I. Idle hibernation" not in r_off.stdout
    p_off = json.loads(e.run(as_json=True).stdout)
    assert p_off["idle_hours"] is None and p_off["idle_hibernate"] == []

    for bad in ("0", "-2", "nan", "inf"):
        r_bad = e.run("--idle-hours", bad)
        assert r_bad.returncode == 2


def test_idle_hours_observe_reports_safe_own_workers_with_rss_and_revive_note(tmp_path: Path, monkeypatch) -> None:
    e = NoPathIdleEnv(tmp_path, monkeypatch)
    adhoc = e.agent("10000001-0000-0000-0000-000000000000", W_WORK, "adhoc worker", labels={"ade.lead": LEAD},
                    hours_ago=5.5, session_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    sliced = e.agent("10000002-0000-0000-0000-000000000000", W_WORK, "worker sdone",
                     labels={"ade.lead": LEAD, "slice": "sdone"}, status="closed", hours_ago=6.0)
    recent = e.agent("10000003-0000-0000-0000-000000000000", W_WORK, "recent worker", labels={"ade.lead": LEAD}, hours_ago=1.0)
    rep = e.reports / "sdone-report.md"
    rep.write_text("summary\nDONE\n")
    Path(f"{rep}.done").write_text("")
    Path(f"{rep}.done.ack").write_text("")
    old_t = time.time() - 6 * 3600
    for q in (rep, Path(f"{rep}.done"), Path(f"{rep}.done.ack")):
        os.utime(q, (old_t, old_t))
    e.data["ps"] = [
        f"5001 40000 Mon Nov 24 01:00:00 2026 204800 /usr/local/bin/claude --resume aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa --mcp-config {{\"url\":\"http://127.0.0.1/?callerAgentId={adhoc}\"}}",
        "5002 5001 Mon Nov 24 01:00:01 2026 51200 node /opt/homebrew/bin/graft mcp",
    ]
    r_json = e.run("--idle-hours", "4", as_json=True)
    assert r_json.returncode == 0, r_json.stderr
    p = json.loads(r_json.stdout)
    by_id = {x["agent"]: x for x in p["idle_hibernate"]}
    assert set(by_id) == {adhoc, sliced}
    assert recent not in by_id
    assert by_id[adhoc]["rss_mb"] == 250.0
    assert by_id[adhoc]["revive_cmd"] == f"bin/ade-revive {adhoc}"
    assert by_id[sliced]["rss_mb"] is None
    assert by_id[sliced]["revive_cmd"] == f"bin/ade-revive {sliced}"
    assert e.archived_agents() == set()  # observe-only: zero mutations

    r_txt = e.run("--idle-hours", "4", as_json=False)
    assert r_txt.returncode == 0
    assert "I. Idle hibernation (--idle-hours 4; observe-only unless --apply)" in r_txt.stdout
    assert "rss 250.0 MB" in r_txt.stdout
    assert f"reversible via: bin/ade-revive {adhoc}" in r_txt.stdout


def test_idle_hours_excludes_all_unsafe_and_non_own_agents_and_apply_archives_only_safe(tmp_path: Path, monkeypatch) -> None:
    e = NoPathIdleEnv(tmp_path, monkeypatch)
    # 1. Running own-worker -> excluded
    running_id = e.agent("20000001-0000-0000-0000-000000000000", W_WORK, "running worker", status="running",
                         labels={"ade.lead": LEAD}, hours_ago=6.0)
    # 2. Pending permission card -> excluded
    permit_id = e.agent("20000002-0000-0000-0000-000000000000", W_WORK, "permit worker", status="idle",
                        labels={"ade.lead": LEAD}, hours_ago=6.0)
    e.data["permits"] = [{"agentId": permit_id, "name": "Bash"}]
    # 3. Standing watchers (all 3 mechanisms) -> excluded
    lw_watcher = e.agent("20000003-0000-0000-0000-000000000000", W_WORK, "worker plain", status="idle",
                         labels={"ade.lead": LEAD}, hours_ago=8.0)
    (e.lw_dir / "watcher.json").write_text(json.dumps({
        "channel": "paseo", "target": lw_watcher, "paseo_home": str(e.home),
    }))
    role_watcher = e.agent("20000004-0000-0000-0000-000000000000", W_WORK, "worker role", status="idle",
                           labels={"ade.lead": LEAD, "ade.role": "load-watcher"}, hours_ago=8.0)
    title_watcher = e.agent("20000005-0000-0000-0000-000000000000", W_WORK, "Standing Load Watcher", status="idle",
                            labels={"ade.lead": LEAD}, hours_ago=8.0)
    # 4. Unreported / unacked paid work (~/CLAUDE.md item 9) -> excluded
    working_stub = e.agent("20000006-0000-0000-0000-000000000000", W_WORK, "worker stub", status="idle",
                           labels={"ade.lead": LEAD, "slice": "stub1"}, hours_ago=6.0)
    (e.reports / "stub1-report.md").write_text("STATUS: working\n")
    missing_rep = e.agent("20000007-0000-0000-0000-000000000000", W_WORK, "worker norep", status="idle",
                          labels={"ade.lead": LEAD, "slice": "norep"}, hours_ago=6.0)
    unacked_rep = e.agent("20000008-0000-0000-0000-000000000000", W_WORK, "worker unacked", status="idle",
                          labels={"ade.lead": LEAD, "slice": "unacked"}, hours_ago=6.0)
    ur = e.reports / "unacked-report.md"
    ur.write_text("all good\nDONE\n")
    Path(f"{ur}.done").write_text("")
    # 5. Operator-owned & other-lead sessions -> operator-call candidates ONLY, never archived by --apply
    op_id = e.agent("20000009-0000-0000-0000-000000000000", W_USER, "operator session", status="idle",
                    labels={}, hours_ago=8.0)
    other_id = e.agent("20000010-0000-0000-0000-000000000000", W_WORK, "other lead worker", status="idle",
                       labels={"ade.lead": OTHER_LEAD}, hours_ago=8.0)
    # 6. Proven-safe own-chain idle workers -> eligible & archived under --apply
    safe_adhoc = e.agent("20000011-0000-0000-0000-000000000000", W_WORK, "safe adhoc worker", status="idle",
                         labels={"ade.lead": LEAD}, hours_ago=5.0)
    safe_slice = e.agent("20000012-0000-0000-0000-000000000000", W_WORK, "safe slice worker", status="closed",
                         labels={"ade.lead": LEAD, "slice": "safeslice"}, hours_ago=5.0)
    sr = e.reports / "safeslice-report.md"
    sr.write_text("shipped\nDONE\n")
    Path(f"{sr}.done").write_text("")
    Path(f"{sr}.done.ack").write_text("")
    old_t = time.time() - 5 * 3600
    for q in (sr, Path(f"{sr}.done"), Path(f"{sr}.done.ack")):
        os.utime(q, (old_t, old_t))

    p = json.loads(e.run("--idle-hours", "4", as_json=True).stdout)
    assert {x["agent"] for x in p["idle_hibernate"]} == {safe_adhoc, safe_slice}
    assert {x["agent"] for x in p["idle_operator_candidates"]} == {op_id, other_id}
    skipped = {x["agent"]: x["reason"] for x in p["idle_skipped"]}
    assert skipped[running_id] == "running"
    assert skipped[permit_id] == "permission-pending"
    assert skipped[lw_watcher] == "standing-watcher"
    assert skipped[role_watcher] == "standing-watcher"
    assert skipped[title_watcher] == "standing-watcher"
    assert skipped[working_stub] == "unreported-work"
    assert skipped[missing_rep] == "missing-report"
    assert skipped[unacked_rep] == "unacked-work"

    r_apply = e.run("--idle-hours", "4", apply=True, as_json=False)
    assert r_apply.returncode == 0, r_apply.stderr
    assert e.archived_agents() == {safe_adhoc, safe_slice}
    # Never passes --force to `paseo agent archive`
    assert all("--force" not in c for c in e.calls() if c[:2] == ["agent", "archive"])
    assert f"idle-hibernate {safe_adhoc} archived" in r_apply.stdout
    assert f"bin/ade-revive {safe_adhoc}" in r_apply.stdout


def test_idle_hours_active_claim_live_child_and_corrupt_watcher_fail_closed(tmp_path: Path, monkeypatch) -> None:
    e = NoPathIdleEnv(tmp_path, monkeypatch)
    claimed = e.agent("30000001-0000-0000-0000-000000000000", W_WORK, "claimed worker", labels={"ade.lead": LEAD}, hours_ago=6.0)
    parent = e.agent("30000002-0000-0000-0000-000000000000", W_WORK, "parent worker", labels={"ade.lead": LEAD}, hours_ago=6.0)
    # Write active claim for `claimed`
    cdir = Path(os.environ["ADE_STATE_DIR"]) / "claims"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "c1.json").write_text(json.dumps({
        "id": "c1", "state": "active", "owner": {"agent": claimed},
        "expires_at": "2999-01-01T00:00:00Z", "workspace": str(e.repo),
    }))
    # Write unarchived child record pointing to `parent`
    cp = e.home / "agents/proj" / "30000003-0000-0000-0000-000000000000.json"
    cp.write_text(json.dumps({"id": "30000003-0000-0000-0000-000000000000", "workspaceId": W_WORK,
                              "labels": {"paseo.parent-agent-id": parent}}))
    p = json.loads(e.run("--idle-hours", "4", as_json=True).stdout)
    assert p["idle_hibernate"] == []
    skipped = {x["agent"]: x["reason"] for x in p["idle_skipped"]}
    assert skipped[claimed] == "active-claim"
    assert skipped[parent] == "has-live-children"

    # Corrupt watcher.json fails closed: observe warns, --apply refuses (exit 1) and archives nothing
    safe = e.agent("30000004-0000-0000-0000-000000000000", W_WORK, "safe worker", labels={"ade.lead": LEAD}, hours_ago=6.0)
    (e.lw_dir / "watcher.json").write_text("{corrupt")
    p_bad = json.loads(e.run("--idle-hours", "4", as_json=True).stdout)
    assert p_bad["idle_hibernate"] == []
    assert any("standing watcher registry unreadable" in n for n in p_bad["notes"])
    r_apply = e.run("--idle-hours", "4", apply=True, as_json=False)
    assert r_apply.returncode == 1 and "standing watcher registry unreadable" in r_apply.stderr
    assert safe not in e.archived_agents() and e.archived_agents() == set()


def test_idle_hours_apply_rechecks_live_status_before_archiving(tmp_path: Path, monkeypatch) -> None:
    e = NoPathIdleEnv(tmp_path, monkeypatch)
    w = e.agent("40000001-0000-0000-0000-000000000000", W_WORK, "flips running", labels={"ade.lead": LEAD}, hours_ago=6.0)
    # First 3 `ls -g` calls (inventory, plan live_ids, apply nowrows) see idle; 4th (live re-read right before archive) sees running
    idle_rows = list(e.data["agents"])
    running_rows = [{**r, "status": "running"} if r["id"] == w else r for r in idle_rows]
    e.data["ls_seq"] = [idle_rows, idle_rows, idle_rows, running_rows]
    r = e.run("--idle-hours", "4", apply=True, as_json=False)
    assert r.returncode == 0, r.stderr
    assert e.archived_agents() == set()
    assert f"SKIP idle-hibernate {w}" in r.stdout
