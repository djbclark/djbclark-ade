"""Offline tests for `bin/ade-tidy prune` (2026-11-14): a fake `paseo` serves canned JSON and records every argv; the agent
state records, Baton's state file and the prune log live under tmp_path. Nothing contacts a daemon."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import signal

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
elif a[:2] == ["agent", "inspect"]:
    row = d.get("inspect", {}).get(a[2])
    if row is None:
        sys.exit(1)
    print(json.dumps(row))
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
PS_STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_DATA"])
d = json.loads(path.read_text())
a = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["ps", *a]) + "\\n")
if "-p" in a:
    pid = a[a.index("-p") + 1]
    over = d.get("ps_recheck", {})
    lines = [over[pid]] if pid in over and over[pid] else ([] if pid in over else [l for l in d.get("ps", []) if l.split()[0] == pid])
    print("\\n".join(lines))
    sys.exit(0 if lines else 1)
seq = d.get("ps_seq")
rows = seq.pop(0) if seq and len(seq) > 1 else (seq[0] if seq else d.get("ps", []))
if seq is not None:
    path.write_text(json.dumps(d))
print("\\n".join(rows))
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
        ps = tmp_path / "bin/ps"
        ps.write_text(PS_STUB)
        ps.chmod(0o755)
        self.data["ps"] = []
        for k, v in {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}", "FAKE_DATA": str(self.data_path),
                     "FAKE_CALLS": str(self.calls_path), "PASEO_HOME": str(self.home),
                     "ADE_HELPER_PRUNE_LOG": str(self.log), "ADE_HELPER_PRUNE_PS": str(ps),
                     "ADE_HELPER_PRUNE_EXCLUDE": str(tmp_path / "state/helper-prune.exclude")}.items():
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
        self.data.setdefault("inspect", {})[aid] = {"Id": aid, "Archived": False, "Status": status, "PendingPermissions": []}
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
    assert set(s) == {"mode", "at", "min_idle_s", "agents_seen", "helpers", "selected", "skipped", "archived", "errors", "locked", "counts",
                      "orphans", "orphan_skipped", "unmapped", "killed", "provider_live", "deferred", "kill_plan"}
    assert s["counts"] == {"agents_seen": 4, "helpers": 2, "selected": 1, "archived": 0, "skipped": 1, "errors": 0,
                           "orphans": 0, "orphan_skipped": 0, "unmapped": 0, "killed": 0, "deferred": 0}
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
    assert line["kind"] == "helper-archive" and line["helper"] == h and line["parent"] == p and line["reason"] == "handoff-written" and line["rc"] == 0
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


# ----------------------------------------------------------------------------------------------- round 2: exclude list

def test_exclude_file_and_option_skip_the_helper(env):
    p = env.parent(1, archived=True)
    a, b, c = (env.helper(10 + i, p) for i in range(3))
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text(f"# keep these\n\n{a}  # the operator's\n")
    s = env.go("--exclude", b, apply=True)
    assert reasons(s) == {a: "excluded", b: "excluded"} and env.archives() == [c]


def test_exclude_file_is_read_on_every_run(env):
    p = env.parent(1, archived=True)
    a = env.helper(10, p)
    assert reasons(env.go()) == {} and [r["id"] for r in env.go()["selected"]] == [a]
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text(a + "\n")
    obs = env.go()                                     # observe: the plan itself must not select it
    assert obs["selected"] == [] and reasons(obs) == {a: "excluded"}
    s = env.go(apply=True)
    assert reasons(s) == {a: "excluded"} and env.archives() == []


def test_exclude_bad_line_refuses_the_run(env):
    p = env.parent(1, archived=True)
    env.helper(10, p)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text("00000010\n")   # a short id could protect the wrong agent: refuse
    r = env.run(apply=True)
    assert r.returncode == 1 and "not a full agent id" in r.stderr and env.archives() == []


def test_exclude_option_needs_a_full_id(env):
    assert env.run("--exclude", "0000001").returncode == 2


@pytest.fixture
def mod(env):
    loader = importlib.machinery.SourceFileLoader("ade_tidy_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_tidy_under_test", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def test_exclude_added_between_plan_and_archive_is_honoured(env, mod, monkeypatch):
    p = env.parent(1, archived=True)
    a = env.helper(10, p)
    env.data_path.write_text(json.dumps(env.data))
    real, n = mod.prune_plan, []

    def late(*args, **kw):
        out = real(*args, **kw)
        n.append(1)
        if len(n) == 2:   # after the re-read plan, before the archive
            Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
            Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text(a + "\n")
        return out

    monkeypatch.setattr(mod, "prune_plan", late)
    s = mod.prune(True, 300)
    assert env.archives() == [] and [(r["id"], r["reason"]) for r in s["skipped"]] == [(a, "excluded")]


# ----------------------------------------------------------------------------------------------- round 2: orphan provider processes

SESS = "0c7d97fa-06a1-4694-a660-eff3aa173b1f"
FLAGS = "--output-format stream-json --verbose --input-format stream-json --thinking adaptive --model opus"
T0 = "Fri Nov 13 05:39:40 2026"
PROV, KID = 4000101, 4000102


def psl(pid, ppid, cmd, lstart=T0, rss=129200):
    return f"{pid:>7} {ppid:>7} {lstart} {rss:>8} {cmd}"


def provider_cmd(sid=SESS):
    return f"/Users/x/.local/bin/claude {FLAGS} --resume={sid}"


def orphan_world(env, archived=True, last_status="closed", inspect=True, n=70, sess=SESS, prov=PROV, kid=KID, age=7200, active_ago=None):
    """An agent record plus a provider process (and a graft child) for its session. Archived `age` seconds ago; its record's
    last activity is `active_ago` (default: the same moment) seconds ago."""
    aid = uid(n)
    p = env.home / "agents/proj" / f"{aid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"id": aid, "workspaceId": "wks_a", "labels": {}, "lastStatus": last_status,
           "runtimeInfo": {"sessionId": sess}, "persistence": {"sessionId": sess, "nativeHandle": sess},
           "lastActivityAt": env.stamp(env.now - (age if active_ago is None else active_ago))}
    if archived:
        rec["archivedAt"] = env.stamp(env.now - age)
    p.write_text(json.dumps(rec))
    inspects = env.data.setdefault("inspect", {})
    if inspect:
        inspects[aid] = {"Id": aid, "Archived": archived, "Status": last_status, "PendingPermissions": []}
    if not env.data["ps"]:
        env.data["ps"] = [psl(1, 0, "/sbin/launchd", rss=100), psl(40000, 1, "/Applications/Paseo daemon", rss=500)]
    env.data["ps"] += [psl(prov, 40000, provider_cmd(sess)), psl(kid, prov, "node /Users/x/.local/bin/graft mcp", T0, 3904)]
    return aid


@pytest.fixture
def kills(mod, monkeypatch):
    sent = []
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    return sent


def test_observe_reports_the_orphan_and_never_kills(env):
    aid = orphan_world(env)
    s = env.go()
    (o,) = s["orphans"]
    assert (o["pid"], o["ppid"], o["agent"], o["session"], o["rss_kb"]) == (PROV, 40000, aid, SESS, 129200)
    assert [c["pid"] for c in o["children"]] == [KID] and s["killed"] == [] and s["counts"]["orphans"] == 1
    assert not env.log.exists()   # observe writes no log line


def test_apply_sigterms_child_then_provider_and_logs(env, mod, kills):
    aid = orphan_world(env)
    env.data["ps"].append(psl(4000103, PROV, "sleep 1000"))                 # a direct child that is not graft mcp
    env.data["ps"].append(psl(4000104, KID, "node /Users/x/.local/bin/graft mcp"))   # a grandchild: not direct
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [(KID, signal.SIGTERM), (PROV, signal.SIGTERM)]
    assert [k["pid"] for k in s["killed"]] == [KID, PROV] and s["errors"] == []
    lines = [x for x in env.log_lines() if x["kind"] == "process-kill"]
    assert [(x["pid"], x["ppid"], x["agent"], x["session"], x["rc"], x["role"]) for x in lines] == [
        (KID, PROV, aid, SESS, 0, "graft-child"), (PROV, 40000, aid, SESS, 0, "provider")]
    assert lines[0]["rss_kb"] == 3904 and lines[0]["ts"].endswith("Z")


def test_apply_via_cli_with_nothing_to_kill_is_quiet(env):
    s = env.go(apply=True)
    assert s["killed"] == [] and s["orphans"] == []


def test_live_agents_process_is_never_an_orphan(env, mod, kills):
    orphan_world(env, archived=False, last_status="idle")
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and s["orphans"] == [] and s["provider_live"] == 1


def test_archived_but_not_closed_is_skipped(env, mod, kills):
    aid = orphan_world(env, last_status="idle")                              # the record says idle ...
    env.data["inspect"][aid]["Status"] = "closed"                            # ... though inspect says closed: both must say closed
    env.data_path.write_text(json.dumps(env.data))
    assert [o["reason"] for o in mod.prune(True, 300)["orphan_skipped"]] == ["not-closed"] and kills == []


def test_inspect_must_agree_with_the_record(env, mod, kills):
    aid = orphan_world(env)
    env.data["inspect"][aid]["Status"] = "idle"                              # the record says closed, inspect says idle
    env.data_path.write_text(json.dumps(env.data))
    assert [o["reason"] for o in mod.prune(True, 300)["orphan_skipped"]] == ["not-closed"] and kills == []


def test_unprovable_mappings_are_unmapped_and_untouched(env, mod, kills):
    orphan_world(env)
    other = "11111111-2222-3333-4444-555555555555"
    env.data["ps"] += [psl(4000201, 40000, provider_cmd(other)),                                        # session with no record
                       psl(4000202, 777, f"/Users/x/.local/bin/claude --resume={SESS}"),                 # a terminal session: not launched by Paseo
                       psl(4000203, 40000, f"/Users/x/.local/bin/claude {FLAGS}")]                      # no session in argv: not listed at all
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert {u["pid"]: u["reason"] for u in s["unmapped"]} == {4000201: "no-agent-record", 4000202: "not-paseo-launched"}
    assert [k[0] for k in kills] == [KID, PROV]


def test_two_records_for_one_session_is_ambiguous(env, mod, kills):
    orphan_world(env)
    twin = env.home / "agents/proj" / f"{uid(71)}.json"
    twin.write_text(json.dumps({"id": uid(71), "workspaceId": "wks_a", "labels": {}, "runtimeInfo": {"sessionId": SESS}}))   # a live twin
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and s["orphans"] == [] and [u["reason"] for u in s["unmapped"]] == ["ambiguous-session"]


def test_reused_pid_is_not_killed(env, mod, kills):
    orphan_world(env)
    env.data["ps_recheck"] = {str(PROV): psl(PROV, 40000, provider_cmd(), lstart="Sat Nov 14 09:00:00 2026"),   # another process, same pid
                              str(KID): psl(KID, PROV, "node /Users/x/.local/bin/graft mcp", lstart=T0)}
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [(KID, signal.SIGTERM)] and [k["pid"] for k in s["killed"]] == [KID]
    skipped = [x for x in env.log_lines() if x.get("skipped")]
    assert [(x["pid"], x["skipped"], x["rc"]) for x in skipped] == [(PROV, "start-time-changed", None)]


def test_same_start_time_but_another_session_is_not_killed(env, mod, kills):
    orphan_world(env)
    env.data["ps_recheck"] = {str(PROV): psl(PROV, 40000, provider_cmd("99999999-0000-0000-0000-000000000009"))}
    env.data_path.write_text(json.dumps(env.data))
    mod.prune(True, 300)
    assert PROV not in [k[0] for k in kills] and [x["skipped"] for x in env.log_lines() if x.get("skipped")] == ["session-changed"]


def test_child_that_changed_parent_or_command_is_not_killed(env, mod, kills):
    orphan_world(env)
    env.data["ps_recheck"] = {str(KID): psl(KID, 1, "node /Users/x/.local/bin/graft mcp")}      # reparented to launchd
    env.data_path.write_text(json.dumps(env.data))
    mod.prune(True, 300)
    assert KID not in [k[0] for k in kills] and "not-the-same-child" in [x.get("skipped") for x in env.log_lines()]
    kills.clear()
    env.data["ps_recheck"] = {str(KID): psl(KID, PROV, "node /Users/x/bin/other mcp")}
    env.data_path.write_text(json.dumps(env.data))
    mod.prune(True, 300)
    assert KID not in [k[0] for k in kills]


def test_pid_one_and_gone_pids_are_never_signalled(env, mod, kills):
    orphan_world(env)
    env.data_path.write_text(json.dumps(env.data))
    e = mod.kill_guarded(1, 0, T0, None, uid(70), 100, "provider")           # the fake table's launchd row (pid 1, same start time) matches
    e2 = mod.kill_guarded(1, 0, T0, None, uid(70), 100, "graft-child")
    e3 = mod.kill_guarded(999999, 1, T0, None, uid(70), 100, "provider")
    assert kills == [] and e["skipped"] == "gone" and e2["skipped"] == "gone" and e3["skipped"] == "gone"


def test_callers_own_process_tree_is_never_killed(env, mod, kills):
    orphan_world(env)
    mine = os.getpid()
    env.data["ps"] += [psl(mine, 4000301, "python pytest"), psl(4000301, 40000, provider_cmd())]   # my parent IS the archived agent's process
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert 4000301 not in [k[0] for k in kills] and {o["pid"] for o in s["orphan_skipped"]} >= {4000301}
    assert {o["reason"] for o in s["orphan_skipped"] if o["pid"] == 4000301} == {"own-tree"}


def test_excluded_and_own_agent_orphans_are_skipped(env, mod, kills, monkeypatch):
    aid = orphan_world(env)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text(aid + "\n")
    env.data_path.write_text(json.dumps(env.data))
    assert [o["reason"] for o in mod.prune(True, 300)["orphan_skipped"]] == ["excluded"] and kills == []
    Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).unlink()
    monkeypatch.setenv("PASEO_AGENT_ID", aid)
    assert [o["reason"] for o in mod.prune(True, 300)["orphan_skipped"]] == ["self"] and kills == []


def test_orphan_that_vanishes_between_plan_and_kill_is_not_killed(env, mod, kills):
    orphan_world(env)
    full = list(env.data["ps"])
    env.data["ps_seq"] = [full, [l for l in full if l.split()[0] not in (str(PROV), str(KID))]]   # the re-read no longer has it
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and [o["reason"] for o in s["orphan_skipped"]] == ["changed-before-kill"]


def test_kill_failure_is_an_error_with_its_errno(env, mod, monkeypatch):
    orphan_world(env)
    env.data_path.write_text(json.dumps(env.data))

    def boom(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(mod.os, "kill", boom)
    s = mod.prune(True, 300)
    assert s["killed"] == [] and len(s["errors"]) == 2 and {x["rc"] for x in env.log_lines() if x["kind"] == "process-kill"} == {1}


def test_ps_output_is_parsed_robustly(mod):
    rows = mod.PS_RE.match(psl(12, 3, "/a b/claude --x  y"))
    assert rows and rows[5] == "/a b/claude --x  y"
    assert mod.PS_RE.match("garbage") is None


def test_exclusion_added_between_orphan_plan_and_kill_is_honoured(env, mod, kills, monkeypatch):
    aid = orphan_world(env)
    env.data_path.write_text(json.dumps(env.data))
    real, n = mod.orphan_plan, []

    def late(*args, **kw):
        out = real(*args, **kw)
        n.append(1)
        if len(n) == 2:   # after the re-read plan, before the first kill
            Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).parent.mkdir(parents=True, exist_ok=True)
            Path(os.environ["ADE_HELPER_PRUNE_EXCLUDE"]).write_text(aid + "\n")
        return out

    monkeypatch.setattr(mod, "orphan_plan", late)
    s = mod.prune(True, 300)
    assert kills == [] and [o["reason"] for o in s["orphan_skipped"]] == ["changed-before-kill"]


# ----------------------------------------------------------------------------------------------- round 3: kill budget, grace, re-checks

def sess_n(n):
    return f"0c7d97fa-06a1-4694-a660-eff3aa17{n:04d}"


def three_orphans(env, **kw):
    return [orphan_world(env, n=70 + i, sess=sess_n(i), prov=PROV + 10 * i, kid=KID + 10 * i, **kw) for i in range(3)]


def test_grace_defers_a_recently_archived_orphan(env, mod, kills):
    orphan_world(env, age=600)                                   # archived 10 minutes ago, default grace 30
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and s["orphans"] == [] and [(d["pid"], d["reason"]) for d in s["deferred"]] == [(PROV, "grace")]
    assert s["kill_plan"]["deferred_grace"] == 1 and s["kill_plan"]["actionable"] == 0
    assert [k[0] for k in (kills if mod.prune(True, 300, (), 10, 300) else [])] == [KID, PROV]   # a shorter grace admits it


def test_quiet_gate_defers_an_orphan_with_recent_activity(env, mod, kills):
    orphan_world(env, age=7200, active_ago=60)                   # archived 2 h ago but the record shows activity a minute ago
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and [(d["pid"], d["reason"]) for d in s["deferred"]] == [(PROV, "grace")]


def test_unreadable_activity_time_fails_closed(env, mod, kills):
    aid = orphan_world(env)
    rp = env.home / "agents/proj" / f"{aid}.json"
    rec = json.loads(rp.read_text())
    rec["lastActivityAt"] = "yesterday-ish"
    rp.write_text(json.dumps(rec))
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300)
    assert kills == [] and [d["reason"] for d in s["deferred"]] == ["grace"]


def test_kill_cap_defers_the_rest_and_the_next_run_picks_them_up(env, mod, kills):
    three_orphans(env)
    env.data_path.write_text(json.dumps(env.data))
    s = mod.prune(True, 300, (), 2, 1800)
    assert [k[0] for k in kills] == [KID, PROV, KID + 10, PROV + 10]       # two providers, each child first
    assert [(d["pid"], d["reason"]) for d in s["deferred"]] == [(PROV + 20, "kill-cap")]
    assert s["kill_plan"] == {"found": 3, "actionable": 2, "deferred_grace": 0, "deferred_cap": 1, "max_kills": 2, "orphan_grace_s": 1800}
    assert s["counts"]["killed"] == 4 and s["counts"]["deferred"] == 1     # providers and graft children are both counted as signalled
    kills.clear()
    env.data["ps"] = [x for x in env.data["ps"] if x.split()[0] not in map(str, (PROV, KID, PROV + 10, KID + 10))]   # they exited
    env.data_path.write_text(json.dumps(env.data))
    s2 = mod.prune(True, 300, (), 2, 1800)
    assert [k[0] for k in kills] == [KID + 20, PROV + 20] and s2["deferred"] == []


def test_max_kills_zero_reports_only_and_cli_flags_validate(env):
    three_orphans(env)
    s = env.go("--max-kills", "0")
    assert s["orphans"] == [] and len(s["deferred"]) == 3 and s["kill_plan"]["max_kills"] == 0
    assert env.run("--max-kills", "-1").returncode == 2 and env.run("--orphan-grace", "x").returncode == 2


def test_kill_plan_is_in_the_observe_summary_and_the_json_line(env):
    three_orphans(env)
    s = env.go("--max-kills", "1")
    assert s["kill_plan"]["actionable"] == 1 and s["kill_plan"]["deferred_cap"] == 2 and s["killed"] == []
    r = env.run("--json-line")
    (line,) = r.stdout.splitlines()
    j = json.loads(line)
    assert j["kill_plan"]["found"] == 3 and j["counts"]["orphans"] == 3 and "orphans" not in j and len(line) < 600


def test_pre_kill_inspect_recheck(env, mod, kills, monkeypatch):
    orphan_world(env)
    env.data_path.write_text(json.dumps(env.data))
    real, calls = mod.agent_archived_closed, []

    def flaky(aid):
        calls.append(aid)
        return real(aid) and len(calls) < 3        # plan, re-read plan: true; the check right before the kill: the agent was un-archived

    monkeypatch.setattr(mod, "agent_archived_closed", flaky)
    s = mod.prune(True, 300)
    assert len(calls) == 3 and kills == [] and [o["reason"] for o in s["orphan_skipped"]] == ["changed-before-kill"]


def test_kill_time_replan_reads_fresh_agent_records(env, mod, kills, monkeypatch):
    orphan_world(env)
    env.data_path.write_text(json.dumps(env.data))
    real, n = mod.orphan_plan, []

    def twin_appears(*args, **kw):
        n.append(1)
        if len(n) == 2:   # between the first plan and the kill-time re-plan another record claims the same session
            (env.home / "agents/proj" / f"{uid(71)}.json").write_text(json.dumps({"id": uid(71), "labels": {}, "runtimeInfo": {"sessionId": SESS}}))
        return real(*args, **kw)

    monkeypatch.setattr(mod, "orphan_plan", twin_appears)
    s = mod.prune(True, 300)
    assert kills == [] and [o["reason"] for o in s["orphan_skipped"]] == ["changed-before-kill"]


def flip_after_second_plan(mod, monkeypatch, env, change):
    real, n = mod.prune_plan, []

    def late(*args, **kw):
        out = real(*args, **kw)
        n.append(1)
        if len(n) == 2:
            change()
            env.data_path.write_text(json.dumps(env.data))
        return out

    monkeypatch.setattr(mod, "prune_plan", late)


@pytest.mark.parametrize("what", ["running", "permission", "archived"])
def test_helper_is_rechecked_right_before_its_archive(env, mod, monkeypatch, what):
    p = env.parent(1, archived=True)
    h = env.helper(10, p)
    env.data_path.write_text(json.dumps(env.data))

    def change():
        ins = env.data["inspect"][h]
        if what == "running":
            ins["Status"] = "running"
        elif what == "permission":
            ins["PendingPermissions"] = [{"id": "x"}]
        else:
            ins["Archived"] = True

    flip_after_second_plan(mod, monkeypatch, env, change)
    s = mod.prune(True, 300)
    assert env.archives() == [] and [(r["id"], r["reason"]) for r in s["skipped"]] == [(h, "changed-before-archive")]


def test_main_agent_with_a_baton_label_is_never_selected(env):
    p = env.parent(1, archived=True)
    env.agent(uid(80), "MAIN myrepo (Wave 7)", labels={"baton-writer": "1", "paseo.parent-agent-id": p})
    s = env.go(apply=True)
    assert reasons(s) == {uid(80): "title-mismatch"} and env.archives() == []


def test_human_output_strips_control_characters(env):
    p = env.parent(1, archived=True)
    env.agent(uid(10), "[Handoff writer]", labels={"baton-writer": "1", "paseo.parent-agent-id": "\x1b[2J\x1b[Hevil"})
    env.data_path.write_text(json.dumps(env.data))
    r = subprocess.run([sys.executable, str(SCRIPT), "prune"], capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "no-parent" in r.stdout and "\x1b" not in r.stdout and "\x07" not in r.stdout


def test_ps_is_called_by_absolute_path(env, monkeypatch):
    monkeypatch.delenv("ADE_HELPER_PRUNE_PS")
    loader = importlib.machinery.SourceFileLoader("ade_tidy_ps_default", str(SCRIPT))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("ade_tidy_ps_default", loader))
    loader.exec_module(m)
    assert m.PS_BIN == "/bin/ps"
    seen = []
    monkeypatch.setattr(m.subprocess, "run", lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    m.ps_rows()
    m.ps_rows(123)
    assert [a[0] for a in seen] == ["/bin/ps", "/bin/ps"]
