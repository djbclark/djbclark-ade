#!/usr/bin/env python3
"""load-watch's find-and-tell hot path (slim-down E5, 2026-11-06): `cmd_sample` on a synthetic sustained spike, through
attribution, with a fake `paseo` on PATH (canned `paseo ls -a -g --json`, a `paseo send` that logs its argv and prints a
`.status`) and a fake process table. It pins the cwd join, the `paseo send` call, the operator notice for a cwd several
agents share, and that a missing `paseo` (or a crash inside attribution) degrades to the operator notice, never to an
exception: `cmd_sample` is the threat model's runaway-load response. Replaces tests/test_relay_watchers_no_ack.py (its
two other watchers, session-load-watch and rumination-watch, were deleted in the same slice)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch_fat", str(LW))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return path


class Spike:
    """One machine: a fake bin dir (paseo, hermes-ping), a process table, cwds, and the agents `paseo ls` lists."""

    def __init__(self, tmp_path, monkeypatch, with_paseo=True, send_status="sent"):
        self.tmp = tmp_path
        self.home = Path(os.path.realpath(tmp_path)) / "home"
        (self.home / "wt-a").mkdir(parents=True)
        (self.home / "shared").mkdir()
        self.bin = tmp_path / "fakebin"
        self.bin.mkdir()
        self.sends = tmp_path / "sends.jsonl"
        self.pings = tmp_path / "pings.txt"
        self.agents = tmp_path / "agents.json"
        # `paseo ls` prints the cwd with `~` for the home directory (ls.ts shortenPath): load-watch must expand it
        self.agents.write_text(json.dumps([
            {"id": "aaaaaaaa-1111", "shortId": "aaaaaaa", "name": "ade-build", "provider": "claude/opus-5.5",
             "thinking": None, "status": "running", "cwd": "~/wt-a", "created": "5m ago", "background": False},
            {"id": "bbbbbbbb-2222", "shortId": "bbbbbbb", "name": "shared-one", "provider": "codex/gpt-5.5",
             "status": "idle", "cwd": "~/shared", "created": "1h ago", "background": False},
            {"id": "cccccccc-3333", "shortId": "ccccccc", "name": "shared-two", "provider": "claude/opus-5.5",
             "status": "running", "cwd": "~/shared", "created": "2h ago", "background": True},
            {"id": "wwwwwwww-9999", "shortId": "wwwwwww", "name": "load-watcher", "provider": "claude/opus-5.5",
             "status": "idle", "cwd": "/elsewhere", "created": "1d ago", "background": False},
            {"id": "no-cwd", "name": "broken"}, "not a row",
        ]))
        if with_paseo:
            script(self.bin / "paseo", f"""import json, sys
a = sys.argv[1:]
if a[:1] == ["ls"]:
    assert a == ["ls", "-a", "-g", "--json"], a
    sys.stdout.write(open({str(self.agents)!r}).read())
elif a[:1] == ["send"]:
    open({str(self.sends)!r}, "a").write(json.dumps(a) + "\\n")
    print(json.dumps({{"agentId": a[-2], "status": {send_status!r}}}))
else:
    sys.exit(2)
""")
        script(self.bin / "hermes-ping", f"import sys\nopen({str(self.pings)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
        monkeypatch.setenv("PATH", str(self.bin) + os.pathsep + "/usr/bin:/bin")
        monkeypatch.delenv("PASEO_CLI", raising=False)
        monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
        lw = self.lw = load_module()
        self.clock = {"t": 1000.0}
        monkeypatch.setattr(lw, "HOME", self.home)
        monkeypatch.setattr(lw, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(lw, "REGISTRY", tmp_path / "ci-only.tsv")
        monkeypatch.setattr(lw, "HERMES_PING", self.bin / "hermes-ping")
        monkeypatch.setattr(lw, "now", lambda: self.clock["t"])
        monkeypatch.setattr(lw.os, "getloadavg", lambda: (40.0, 40.0, 40.0))
        monkeypatch.setattr(lw.os, "cpu_count", lambda: 8)
        monkeypatch.setattr(lw, "guard", lambda *a: None)
        monkeypatch.setattr(lw, "churn_read", lambda st, t: None)
        monkeypatch.setattr(lw, "forgejo_remote", lambda top: "")
        uid = lw.MY_UID
        wt, shared = str(self.home / "wt-a"), str(self.home / "shared")
        # pid -> (ppid, uid, cores, command)
        self.table = {
            "400": (1, uid, 0.1, "/opt/paseo/daemon"),
            "500": (400, uid, 0.6, "claude --resume"),                # agent A's own CLI: not build work
            "510": (500, uid, 0.2, "/bin/bash -c cargo build"),
            "600": (510, uid, 3.0, "rustc --crate-name big"),         # runs in a temp dir: the ancestor's cwd decides
            "700": (1, uid, 2.0, "python3 -m pytest tests/"),         # cwd shared by agents B and C: not guessed
            "800": (1, uid, 0.3, "/usr/libexec/mds"),                  # no agent's cwd: loose
        }
        self.cwds = {"400": "/", "500": wt, "510": wt, "600": "/tmp/cargo-xyz", "700": shared, "800": "/"}
        monkeypatch.setattr(lw, "ps_table", lambda: dict(self.table))
        monkeypatch.setattr(lw, "proc_cwds", lambda pids: {str(p): self.cwds[str(p)] for p in pids if str(p) in self.cwds})
        monkeypatch.setattr(lw, "git_top", lambda path: "")
        lw.save_watcher({"channel": "paseo", "target": "wwwwwwww-9999"})

    def sample(self, t):
        self.clock["t"] = t

        class A:
            dry_run = False
            verbose = False
        return self.lw.cmd_sample(A())

    def spike(self):
        assert self.sample(1000) == 0
        assert self.sample(1200) == 0
        assert self.sample(1400) == 0   # 400 s hot: past LW_SUSTAIN_S (300)

    def sent(self):
        return [json.loads(ln) for ln in self.sends.read_text().splitlines()] if self.sends.exists() else []

    def pinged(self):
        return self.pings.read_text() if self.pings.exists() else ""

    def incidents(self):
        p = self.tmp / "state" / "incidents.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def test_a_sustained_spike_is_attributed_by_cwd_and_told_by_paseo_send(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch)
    m.spike()
    inc = m.incidents()
    assert len(inc) == 1
    r = inc[0]
    assert (r["agent_id"], r["session"], r["agent"], r["delivery"], r["relayed"]) == \
        ("aaaaaaaa-1111", "ade-build", "claude/opus-5.5", "sent", True)
    assert r["cwd"] == str(m.home / "wt-a")                            # `~/wt-a` expanded
    assert [p["pid"] for p in r["procs"]] == [600, 510]                # the agent's own `claude` (500) is not counted
    assert r["cores"] == pytest.approx(3.2)
    to_a = [s for s in m.sent() if s[-2] == "aaaaaaaa-1111"]
    assert len(to_a) == 1
    assert to_a[0][:6] == ["send", "--no-wait", "--json", "--behavior", "steer", "--"]
    assert r["id"] in to_a[0][-1] and r["brief"] in to_a[0][-1]
    assert Path(r["brief"]).exists() and "ade-build" in Path(r["brief"]).read_text()
    assert "told it" in m.pinged()
    # the agents that share ~/shared are never guessed: the operator hears the process and both candidates
    assert not any(s[-2] in ("bbbbbbbb-2222", "cccccccc-3333") for s in m.sent())
    ping = [ln for ln in m.pinged().splitlines() if "did not guess" in ln]
    assert len(ping) == 1
    assert "pid 700" in ping[0] and "python3 -m pytest" in ping[0] and str(m.home / "shared") in ping[0]
    assert "bbbbbbb shared-one (codex/gpt-5.5, idle)" in ping[0] and "ccccccc shared-two (claude/opus-5.5, running)" in ping[0]
    to_w = [s[-1] for s in m.sent() if s[-2] == "wwwwwwww-9999"]
    assert any("did not guess" in t for t in to_w)                      # the watcher hears it too
    assert any("load-watch " + r["id"] in t for t in to_w)              # and the incident
    assert all("As the load watcher" in t for t in to_w)                # with the instruction itself (R2-11)


def test_a_queued_send_is_logged_not_delivered_and_offers_the_fixer(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch, send_status="queued")
    m.spike()
    r = m.incidents()[0]
    assert r["delivery"] == "queued" and r["relayed"] is False
    log = (tmp_path / "state" / "sample.log").read_text()
    assert "delivery=queued, not delivered" in log
    assert "queued it, not delivered" in m.pinged() and "acp-dispatch cursor" in m.pinged()


def test_without_paseo_the_spike_reaches_the_operator_and_nothing_raises(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch, with_paseo=False)
    m.spike()                          # returns 0 each time: no exception escapes
    assert m.incidents() == []
    ping = m.pinged()
    assert "could not name the agent behind it: no `paseo` on PATH" in ping
    assert "3.0 rustc --crate-name big" in ping and "2.0 python3 -m pytest" in ping  # the process lines
    assert "no agent attribution (no `paseo` on PATH)" in (tmp_path / "state" / "sample.log").read_text()
    assert m.sample(1420) == 0 and m.pinged() == ping   # once per episode, as before


def test_a_crash_inside_attribution_is_an_operator_notice_too(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch)

    def boom():
        raise RuntimeError("synthetic")
    monkeypatch.setattr(m.lw, "paseo_agents", boom)
    m.spike()
    assert "could not name the agent behind it: attribution failed (RuntimeError)" in m.pinged()
    assert "attribution error: RuntimeError('synthetic')" in (tmp_path / "state" / "sample.log").read_text()


def test_paseo_ls_failures_and_shapes_are_reasons_not_exceptions(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch)
    lw = m.lw
    agents, why = lw.paseo_agents()
    assert why is None and [a["id"] for a in agents] == ["aaaaaaaa-1111", "bbbbbbbb-2222", "cccccccc-3333", "wwwwwwww-9999"]
    assert agents[0]["cwd"] == str(m.home / "wt-a") and agents[3]["cwd"] == "/elsewhere"
    for body, reason in (("print('{}')", "no list of agents"), ("print('nope')", "printed no JSON"),
                         ("import sys; sys.stderr.write('DAEMON_NOT_RUNNING'); sys.exit(1)", "exited 1: DAEMON_NOT_RUNNING")):
        script(m.bin / "paseo", body + "\n")
        agents, why = lw.paseo_agents()
        assert agents is None and reason in why, why
    monkeypatch.setenv("PASEO_CLI", str(tmp_path / "missing" / "paseo"))
    assert lw.paseo_agents() == (None, f"no `{tmp_path / 'missing' / 'paseo'}` on PATH")


def test_a_repo_with_one_agent_takes_a_daemon_in_a_subdirectory(tmp_path, monkeypatch):
    """No cwd on the chain matches, but the process's own cwd is in the git repo of exactly one agent (a Gradle daemon)."""
    m = Spike(tmp_path, monkeypatch)
    lw = m.lw
    wt = str(m.home / "wt-a")
    m.table = {"900": (1, lw.MY_UID, 2.5, "java GradleDaemon")}
    m.cwds = {"900": wt + "/app"}
    monkeypatch.setattr(lw, "git_top", lambda path: wt if path.startswith(wt) else "")
    groups, loose, unsure, why = lw.attribute({"900": [2.5, lw.MY_UID, "java GradleDaemon"]}, 1, {"900": 1})
    assert why is None and not loose and not unsure and list(groups) == ["aaaaaaaa-1111"]
    assert groups["aaaaaaaa-1111"]["procs"][0]["pid"] == 900


def test_an_agent_in_the_home_directory_or_root_owns_nothing_by_cwd(tmp_path, monkeypatch):
    m = Spike(tmp_path, monkeypatch)
    lw = m.lw
    m.agents.write_text(json.dumps([{"id": "home-agent", "provider": "claude/x", "cwd": "~"},
                                    {"id": "root-agent", "provider": "claude/x", "cwd": "/"}]))
    monkeypatch.setattr(lw, "proc_cwds", lambda pids: {str(p): ("/" if str(p) == "1" else str(m.home)) for p in pids})
    groups, loose, unsure, why = lw.attribute({"900": [2.0, lw.MY_UID, "make"], "901": [2.0, lw.MY_UID, "mds"]}, 1,
                                              {"900": 1, "901": 1})
    assert why is None and not groups and not unsure and [r["pid"] for r in loose] == [900, 901]
