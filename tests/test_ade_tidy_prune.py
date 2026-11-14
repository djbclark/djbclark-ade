"""Offline tests for `bin/ade-tidy prune` (2026-11-14): a fake `paseo` serves canned JSON and records every argv; the agent
state records, Baton's state file and the prune log live under tmp_path. Nothing contacts a daemon."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("ADE_TIDY_UNDER_TEST") or ROOT / "bin/ade-tidy")  # mutation checks point this at a mutated copy
ME = "99999999-0000-0000-0000-000000000000"
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
elif a[:2] == ["permit", "ls"]:
    if d.get("permit_fail"):
        sys.exit(1)
    print(json.dumps(d.get("permits", [])))
elif a[:2] == ["agent", "archive"]:
    rc = d.get("archive_rc", {}).get(a[2], 0)
    if rc == 0:
        d["agents"] = [x for x in d["agents"] if x["id"] != a[2]]
        d.pop("ls_seq", None)
        save()
    sys.exit(rc)
else:
    sys.exit(9)
'''


def uid(n: int) -> str:
    return f"{n:08d}-0000-0000-0000-000000000000"


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.home = tmp_path / "paseo-home"
        self.data_path, self.calls_path = tmp_path / "data.json", tmp_path / "calls.jsonl"
        self.log = tmp_path / "state/helper-prune.log"
        self.data = {"agents": [], "permits": [], "archive_rc": {}}
        self.baton: dict = {}
        stub = tmp_path / "bin/paseo"
        stub.parent.mkdir()
        stub.write_text(STUB)
        stub.chmod(0o755)
        for k, v in {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}", "FAKE_DATA": str(self.data_path),
                     "FAKE_CALLS": str(self.calls_path), "PASEO_HOME": str(self.home),
                     "ADE_HELPER_PRUNE_LOG": str(self.log)}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
        self.monkeypatch = monkeypatch
        self.now = time.time()

    @staticmethod
    def stamp(epoch: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))

    def record(self, aid, labels=None, archived=False, last_activity=None, created=None, ws="wks_a"):
        p = self.home / "agents/proj" / f"{aid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"id": aid, "workspaceId": ws, "labels": labels if labels is not None else {}, "title": "x",
               "createdAt": self.stamp(created or self.now - 3600),
               "lastActivityAt": self.stamp(last_activity or self.now - 1800)}
        if archived:
            rec["archivedAt"] = self.stamp(self.now - 60)
        p.write_text(json.dumps(rec))

    def agent(self, aid, name, status="idle", labels=None, **kw):
        """A live agent (listed by `paseo ls -g`) plus its state record."""
        self.data["agents"].append({"id": aid, "name": name, "status": status, "cwd": "/x"})
        self.record(aid, labels, **kw)

    def parent(self, n, status="idle", archived=False, live=True):
        pid = uid(n)
        if archived or not live:
            self.record(pid, {}, archived=archived)
        else:
            self.agent(pid, f"parent {n}", status)
        return pid

    def handoff(self, parent, saved=None, status="done", content="# handoff\n", exists=True):
        path = self.tmp / "handoffs" / f"{parent}.md"
        path.parent.mkdir(exist_ok=True)
        if exists:
            path.write_text(content)
        self.baton[parent] = {"agentId": parent, "status": status, "path": str(path),
                              "savedAt": int((saved or self.now - 900) * 1000)}

    def helper(self, n, parent, status="idle", name="[Handoff writer]", labels="both", **kw):
        lab = {}
        if labels in ("both", "label"):
            lab["baton-writer"] = "1"
        if parent is not None:
            lab["paseo.parent-agent-id"] = parent
        self.agent(uid(n), name, status, lab, **kw)
        return uid(n)

    def run(self, *args, apply=False):
        self.data_path.write_text(json.dumps(self.data))
        bs = self.home / "plugin-data/baton/baton-state.json"
        bs.parent.mkdir(parents=True, exist_ok=True)
        bs.write_text(json.dumps(self.baton))
        r = subprocess.run([sys.executable, str(SCRIPT), "prune", "--json", *args, *(["--apply"] if apply else [])],
                           capture_output=True, text=True)
        self.data = json.loads(self.data_path.read_text())   # the fake's own changes (an archived agent is gone) carry to the next run
        return r

    def go(self, *args, apply=False):
        r = self.run(*args, apply=apply)
        assert r.returncode == 0, (r.stdout, r.stderr)
        return json.loads(r.stdout)

    def calls(self):
        return [json.loads(x) for x in self.calls_path.read_text().splitlines()] if self.calls_path.exists() else []

    def archives(self):
        return [c[2] for c in self.calls() if c[:2] == ["agent", "archive"]]

    def log_lines(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def reasons(s, key="skipped"):
    return {r["id"]: r["reason"] for r in s[key]}


def test_observe_selects_and_changes_nothing(env):
    p = env.parent(1)
    env.handoff(p)
    h = env.helper(10, p)
    s = env.go()
    assert s["mode"] == "observe" and reasons(s, "selected") == {h: "handoff-written"}
    assert s["archived"] == [] and s["locked"] is False
    assert env.archives() == [] and not env.log.exists()   # the --apply gate: observe never archives, never logs


def test_json_shape_and_counts(env):
    p = env.parent(1)
    env.handoff(p)
    env.helper(10, p)
    env.helper(11, p, status="running")
    env.agent(uid(50), "ordinary worker")
    s = env.go()
    assert set(s) == {"mode", "at", "min_idle_s", "agents_seen", "helpers", "selected", "skipped", "archived", "errors", "locked", "counts"}
    assert s["counts"] == {"agents_seen": 4, "helpers": 2, "selected": 1, "archived": 0, "skipped": 1, "errors": 0}
    row = s["selected"][0]
    assert set(row) >= {"id", "parent", "status", "workspace", "reason", "idle_s"} and row["parent"] == p
    assert set(s["skipped"][0]) >= {"id", "parent", "status", "workspace", "reason", "detail"}


def test_apply_archives_handoff_written_and_logs(env):
    p = env.parent(1)
    env.handoff(p)
    h = env.helper(10, p)
    s = env.go(apply=True)
    assert [r["id"] for r in s["archived"]] == [h] and s["counts"]["archived"] == 1 and s["errors"] == []
    assert env.archives() == [h]
    (line,) = env.log_lines()
    assert line["helper"] == h and line["parent"] == p and line["reason"] == "handoff-written" and line["rc"] == 0
    assert line["ts"].endswith("Z") and len(line["ts"]) == 20


def test_apply_is_idempotent(env):
    p = env.parent(1)
    env.handoff(p)
    env.helper(10, p)
    assert env.go(apply=True)["counts"]["archived"] == 1
    again = env.go(apply=True)
    assert again["archived"] == [] and again["selected"] == [] and len(env.archives()) == 1 and len(env.log_lines()) == 1


@pytest.mark.parametrize("kind,code", [("archived", "parent-archived"), ("gone", "parent-gone"), ("closed", "parent-closed")])
def test_parent_finished_archives_without_handoff(env, kind, code):
    env.agent(uid(2), "bystander")  # a record exists, so an absent parent is provably gone, not an unreadable store
    p = {"archived": lambda: env.parent(1, archived=True), "gone": lambda: uid(1),
         "closed": lambda: env.parent(1, status="closed")}[kind]()
    h = env.helper(10, p)
    s = env.go(apply=True)
    assert [r["id"] for r in s["archived"]] == [h] and s["archived"][0]["reason"] == code
    assert env.log_lines()[0]["reason"] == code


def test_skip_not_idle(env):
    p = env.parent(1, archived=True)
    ids = [env.helper(10 + i, p, status=st) for i, st in enumerate(("running", "closed", "error"))]
    s = env.go(apply=True)
    assert [reasons(s)[i] for i in ids] == ["not-idle"] * 3 and env.archives() == []


def test_skip_permission_pending(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    env.data["permits"] = [{"id": "11111111-1111-1111-1111-111111111111", "agentId": h, "name": "Bash"}]
    s = env.go(apply=True)
    assert reasons(s) == {h: "permission-pending"} and env.archives() == []


def test_permit_list_unreadable_selects_nothing(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    env.data["permit_fail"] = True
    r = env.run(apply=True)
    s = json.loads(r.stdout)
    assert r.returncode == 1 and reasons(s) == {h: "permits-unreadable"} and s["errors"] and env.archives() == []


def test_skip_recently_active_and_min_idle_option(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p, last_activity=time.time() - 30)
    assert reasons(env.go(apply=True)) == {h: "recently-active"} and env.archives() == []
    s = env.go("--min-idle", "5", apply=True)   # a smaller floor accepts the same helper
    assert [r["id"] for r in s["archived"]] == [h]


@pytest.mark.parametrize("case,detail", [("none", "no Baton entry"), ("pending", "status pending"), ("missing", "file missing"),
                                         ("empty", "empty"), ("old", "predates")])
def test_skip_handoff_unproven(env, case, detail):
    p = env.parent(1)
    h = env.helper(10, p)
    if case == "pending":
        env.handoff(p, status="pending")
    elif case == "missing":
        env.handoff(p, exists=False)
    elif case == "empty":
        env.handoff(p, content="")
    elif case == "old":
        env.handoff(p, saved=env.now - 7200)   # written before the helper was created (3600 s ago)
    s = env.go(apply=True)
    assert reasons(s) == {h: "handoff-unproven"} and detail in s["skipped"][0]["detail"] and env.archives() == []


def test_skip_no_parent_title_only_label_only_and_record_missing(env):
    p = env.parent(1, archived=True)
    a = env.helper(10, None)                                  # no parent label
    b = env.helper(11, p, labels="title")                    # title but no baton-writer label
    c = env.helper(12, p, name="some other title")           # label but another title
    d = uid(13)
    env.data["agents"].append({"id": d, "name": "[Handoff writer]", "status": "idle", "cwd": "/x"})   # no state record at all
    s = env.go(apply=True)
    assert reasons(s) == {a: "no-parent", b: "no-baton-label", c: "title-mismatch", d: "no-baton-label"}
    assert env.archives() == []


def test_never_touches_non_helpers_or_main(env):
    p = env.parent(1, archived=True)
    env.agent(uid(60), "LEAD myrepo Wave 7", labels={"ade.lead": uid(61)})
    env.agent(uid(62), "MAIN agent")
    env.agent(uid(63), "worker s1", labels={"ade.lead": uid(60), "slice": "s1"})
    env.agent(uid(64), "[handoff writer] lowercase")           # not the title Baton sets
    h = env.helper(10, p)
    s = env.go(apply=True)
    assert env.archives() == [h]
    touched = {uid(60), uid(62), uid(63), uid(64)}
    assert not touched & {r["id"] for r in s["selected"] + s["skipped"] + s["archived"]}


def test_main_kind_helper_titled_agent_is_skipped(env):
    p = env.parent(1, archived=True)
    lead = env.helper(10, p)                       # titled and labelled like a helper, but another agent's lead
    env.agent(uid(20), "worker s1", labels={"ade.lead": lead})
    s = env.go(apply=True)
    assert reasons(s) == {lead: "main-kind"} and env.archives() == []


def test_self_is_never_archived(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    env.monkeypatch.setenv("PASEO_AGENT_ID", h)
    s = env.go(apply=True)
    assert reasons(s) == {h: "self"} and env.archives() == []


def test_archive_failure_is_an_error_and_logged(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    env.data["archive_rc"] = {h: 3}
    r = env.run(apply=True)
    s = json.loads(r.stdout)
    assert r.returncode == 1 and s["archived"] == [] and s["counts"]["errors"] == 1 and h in s["errors"][0]["id"]
    assert env.log_lines()[0]["rc"] == 3 and "error" in env.log_lines()[0]


def test_changed_between_plan_and_apply_is_not_archived(env):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    idle, busy = list(env.data["agents"]), [dict(x, status="running") if x["id"] == h else x for x in env.data["agents"]]
    env.data["ls_seq"] = [idle, busy]            # the first read sees idle, the re-read right before acting sees running
    s = env.go(apply=True)
    assert env.archives() == [] and reasons(s) == {h: "changed-before-archive"} and s["archived"] == []


def test_apply_while_another_prune_holds_the_lock(env):
    p = env.parent(1, archived=True)
    env.helper(10, p)
    env.log.parent.mkdir(parents=True, exist_ok=True)
    with open(env.log.with_name("helper-prune.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        s = env.go(apply=True)
    assert s["locked"] is True and env.archives() == []


def test_usage_error(env):
    r = subprocess.run([sys.executable, str(SCRIPT), "prune", "--nope"], capture_output=True, text=True)
    assert r.returncode == 2
