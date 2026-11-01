"""bin/codexbar-cpu-watch: what is selected, what is logged (never a command line), how the log grows. No launchd."""
import importlib.machinery
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "codexbar-cpu-watch"


@pytest.fixture
def cbw(tmp_path, monkeypatch):
    monkeypatch.setenv("CBW_STATE_DIR", str(tmp_path / "state"))
    loader = importlib.machinery.SourceFileLoader("codexbar_cpu_watch", str(SCRIPT))
    spec = importlib.util.spec_from_loader("codexbar_cpu_watch", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def proc(pid, ppid, cmd, cpu=0.0):
    return {"pid": pid, "ppid": ppid, "rss_mb": 10, "cpu_s": cpu, "cmd": cmd}


def test_cputime_formats(cbw):
    assert cbw.cputime_s("0:00.12") == pytest.approx(0.12)
    assert cbw.cputime_s("1-02:03:04") == 86400 + 2 * 3600 + 3 * 60 + 4
    assert cbw.cputime_s("12:34.50") == pytest.approx(12 * 60 + 34.5)


def test_tree_roots_are_the_executable_not_any_argument(cbw):
    procs = {
        1: proc(1, 0, "/Applications/CodexBar.app/Contents/MacOS/CodexBar"),
        2: proc(2, 1, "/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI serve --port 10546"),
        3: proc(3, 2, "node /x/codex-probe.js"),
        4: proc(4, 0, "omp --prompt look at CodexBar please"),
        5: proc(5, 4, "node /x/child-of-agent.js"),
        6: proc(6, 0, "vim /src/CodexBar/CodexBar.app/Contents/MacOS/CodexBar"),
        7: proc(7, 0, "/Users/x/src/CodexBar/CodexBar.app/Contents/MacOS/CodexBar"),
    }
    assert cbw.tree(procs, me=-1) == {1, 2, 3, 7}


def test_tree_excludes_itself(cbw):
    procs = {1: proc(1, 0, "/A/CodexBar.app/Contents/MacOS/CodexBar"), 2: proc(2, 1, "python codexbar-cpu-watch sample")}
    assert cbw.tree(procs, me=2) == {1}


def test_no_secret_reaches_the_record(cbw):
    cmd = ("/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI serve --token=sk-SECRET1 --api-key sk-SECRET2 "
           "-H Authorization:BearerSECRET3 -pSECRET4 --port 10546")
    assert cbw.label(cmd) == "CodexBarCLI"
    flags = cbw.flag_names(cmd)
    assert "--token" in flags and "--api-key" in flags and "--port" in flags and "-H" in flags
    assert not any("SECRET" in f for f in flags)
    assert cbw.label("node /home/u/tool/server.js --x") == "node server.js"
    assert cbw.label("bash -c TOKEN=abc123 run") == "bash"
    assert cbw.label("/opt/Python -I /a/b/acp-run omp --k v") == "Python acp-run"


def test_sample_record_holds_no_command_line(cbw, monkeypatch):
    secret = "sk-SECRETVALUE"
    snaps = iter([
        {1: proc(1, 0, f"/A/CodexBar.app/Contents/MacOS/CodexBar --token={secret}", 10.0)},
        {1: proc(1, 0, f"/A/CodexBar.app/Contents/MacOS/CodexBar --token={secret}", 11.5)},
    ])
    monkeypatch.setattr(cbw, "read_ps", lambda: next(snaps))
    monkeypatch.setattr(cbw, "WINDOW_S", 0)
    monkeypatch.setattr(cbw, "SPIKE_PCT", 1)
    rec = cbw.sample()
    assert rec["spike"] and rec["total_pct"] > 1
    assert secret not in json.dumps(rec)
    assert rec["tree"][0]["name"] == "CodexBar" and rec["tree"][0]["flags"] == ["--token"]


def test_log_is_private_appended_and_rotated(cbw, monkeypatch):
    monkeypatch.setattr(cbw, "MAX_BYTES", 400)
    for i in range(30):
        cbw.append({"i": i, "pad": "x" * 40})
    d = cbw.STATE_DIR
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    for f in d.iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert (d / "samples.jsonl.1").exists()
    lines = [json.loads(x) for p in (d / "samples.jsonl.1", d / "samples.jsonl") for x in p.read_text().splitlines()]
    assert [r["i"] for r in lines] == sorted(r["i"] for r in lines) and lines[-1]["i"] == 29


def test_oversized_launchd_log_is_emptied_and_made_private(cbw, monkeypatch):
    monkeypatch.setattr(cbw, "LAUNCHD_MAX_BYTES", 100)
    cbw.STATE_DIR.mkdir(parents=True)
    out = cbw.STATE_DIR / "launchd.out"
    out.write_text("y" * 500)
    os.chmod(out, 0o644)
    cbw.append({"i": 1})
    assert out.stat().st_size == 0 and stat.S_IMODE(out.stat().st_mode) == 0o600


def test_failed_ps_makes_no_record(cbw, monkeypatch, capsys):
    def boom():
        raise RuntimeError("ps failed (rc=1)")
    monkeypatch.setattr(cbw, "read_ps", boom)

    class A:
        verbose = False
    assert cbw.cmd_sample(A()) == 1
    assert not cbw.LOG.exists()


def test_report_skips_torn_and_old_shaped_lines(cbw, capsys):
    cbw.STATE_DIR.mkdir(parents=True)
    good = {"ts": "t", "total_pct": 80.0, "procs": 2, "spike": True,
            "top": [{"pid": 1, "pct": 80.0, "name": "CodexBar", "flags": ["--port"]}], "tree": [{"pid": 1, "pct": 80.0, "ppid": 0, "rss_mb": 5, "name": "CodexBar", "flags": []}]}
    old = {"ts": "t0", "total_pct": 1.0, "procs": 1, "top": [{"pid": 2, "pct": 1.0, "cmd": "/old/CodexBar"}]}
    cbw.LOG.write_text(json.dumps(old) + "\n" + '{"ts": "torn' + "\n" + "[1,2]\n" + json.dumps(good) + "\n")

    class A:
        n = 10
    assert cbw.cmd_report(A()) == 0
    out = capsys.readouterr().out
    assert "2 samples scanned, 1 at or above" in out and "SPIKE" in out and "CodexBar --port" in out


def test_install_refuses_a_linked_worktree(cbw, tmp_path, monkeypatch, capsys):
    wt = tmp_path / "wt"
    (wt / "bin").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere\n")
    (wt / "bin" / "codexbar-cpu-watch").write_text("")
    monkeypatch.setattr(cbw, "ADE", wt)
    monkeypatch.setattr(cbw.shutil, "which", lambda n: "/bin/true")
    calls = []
    monkeypatch.setattr(cbw.subprocess, "run", lambda *a, **k: calls.append(a))

    class A:
        cmd = "install"
        ade = None
    assert cbw.cmd_install(A()) == 2
    assert not calls and "linked worktree" in capsys.readouterr().err
