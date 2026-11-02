"""bin/proc-cpu-watch: what is selected per target, what is logged (never a command line), how the log grows. No launchd."""
import importlib.machinery
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "proc-cpu-watch"


@pytest.fixture
def cbw(tmp_path, monkeypatch):
    monkeypatch.setenv("CBW_STATE_DIR", str(tmp_path / "state"))
    loader = importlib.machinery.SourceFileLoader("proc_cpu_watch", str(SCRIPT))
    spec = importlib.util.spec_from_loader("proc_cpu_watch", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.use_target("codexbar")
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
        8: proc(8, 0, "/usr/bin/vim /src/CodexBar/CodexBar.app/Contents/MacOS/CodexBar"),
        9: proc(9, 0, "/usr/bin/codesign -dv /Applications/CodexBar.app/Contents/MacOS/CodexBar"),
        10: proc(10, 0, "/opt/homebrew/bin/omp --prompt /x/CodexBar.app/Contents/Helpers/CodexBarCLI"),
        11: proc(11, 9, "/usr/bin/child-of-codesign"),
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
    assert cbw.label("/opt/Python -I /a/b/s1_agy.py scan") == "Python s1_agy.py"


@pytest.mark.parametrize("cmd", [
    "node --require sk-SECRET server.js",
    "node --token sk-SECRET server.js",
    "python3 --key sk-SECRET script.py",
    "uv --directory sk-SECRET run",
    "env -u sk-SECRET cmd",
    "/opt/Python -I sk-SECRET-acp-run omp",
])
def test_an_option_value_is_never_taken_for_the_script(cbw, cmd):
    assert "SECRET" not in cbw.label(cmd)


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


def test_failed_or_slow_ps_makes_no_record(cbw, monkeypatch, capsys):
    """The real read_ps path: a non-zero rc or a timeout fails the sample, writes no record, says why."""
    import subprocess

    class A:
        verbose = False
    monkeypatch.setattr(cbw.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="1 0 10 0:00.10 x\n", stderr=""))
    assert cbw.cmd_sample(A()) == 1

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 30)
    monkeypatch.setattr(cbw.subprocess, "run", slow)
    assert cbw.cmd_sample(A()) == 1
    assert not cbw.LOG.exists()
    err = capsys.readouterr().err
    assert "ps failed (rc=1)" in err and "timed out" in err


def test_failed_sample_still_caps_launchd_err(cbw, monkeypatch):
    monkeypatch.setattr(cbw, "LAUNCHD_MAX_BYTES", 100)
    cbw.STATE_DIR.mkdir(parents=True)
    err = cbw.STATE_DIR / "launchd.err"
    err.write_text("e" * 500)

    def boom():
        raise RuntimeError("ps failed (rc=1)")
    monkeypatch.setattr(cbw, "read_ps", boom)

    class A:
        verbose = False
    assert cbw.cmd_sample(A()) == 1
    assert err.stat().st_size == 0


def test_report_skips_torn_and_old_shaped_lines(cbw, capsys):
    cbw.STATE_DIR.mkdir(parents=True)
    good = {"ts": "t", "total_pct": 80.0, "procs": 2, "spike": True,
            "top": [{"pid": 1, "pct": 80.0, "name": "CodexBar", "flags": ["--port"]}], "tree": [{"pid": 1, "pct": 80.0, "ppid": 0, "rss_mb": 5, "name": "CodexBar", "flags": []}]}
    old = {"ts": "t0", "total_pct": 1.0, "procs": 1, "top": [{"pid": 2, "pct": 1.0, "cmd": "/old/LEGACYCMD --token x"}]}
    foreign = {"ts": "t1", "total_pct": "lots", "procs": None, "spike": True, "top": [1, "x"], "tree": "nope"}
    cbw.LOG.write_text(json.dumps(old) + "\n" + '{"ts": "torn' + "\n" + "[1,2]\n" + json.dumps(foreign) + "\n" + json.dumps(good) + "\n")

    class A:
        n = 10
    assert cbw.cmd_report(A()) == 0
    out = capsys.readouterr().out
    assert "3 samples scanned, 2 at or above" in out and "CodexBar --port" in out
    assert "LEGACYCMD" not in out


def test_install_refuses_a_linked_worktree(cbw, tmp_path, monkeypatch, capsys):
    wt = tmp_path / "wt"
    (wt / "bin").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere\n")
    (wt / "bin" / "proc-cpu-watch").write_text("")
    monkeypatch.setattr(cbw, "ADE", wt)
    monkeypatch.setattr(cbw.shutil, "which", lambda n: "/bin/true")
    calls = []
    monkeypatch.setattr(cbw.subprocess, "run", lambda *a, **k: calls.append(a))

    class A:
        cmd = "install"
        ade = None
    assert cbw.cmd_install(A()) == 2
    assert not calls and "linked worktree" in capsys.readouterr().err


def test_install_refuses_a_cow_pasture(cbw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cbw, "HOME", tmp_path)
    past = tmp_path / ".cow" / "pastures" / "djbclark-ade" / "p1"
    (past / "bin").mkdir(parents=True)
    (past / ".git").mkdir()
    (past / "bin" / "proc-cpu-watch").write_text("")
    primary = tmp_path / "src" / "djbclark-ade"
    (primary / ".git").mkdir(parents=True)
    assert cbw.disposable_checkout(past) and not cbw.disposable_checkout(primary)
    monkeypatch.setattr(cbw, "ADE", past)
    monkeypatch.setattr(cbw.shutil, "which", lambda n: "/bin/true")
    calls = []
    monkeypatch.setattr(cbw.subprocess, "run", lambda *a, **k: calls.append(a))

    class A:
        cmd = "install"
        ade = None
    assert cbw.cmd_install(A()) == 2
    assert not calls and "cow pasture" in capsys.readouterr().err


def _window(cbw, monkeypatch, first, second):
    snaps = iter([first, second])
    monkeypatch.setattr(cbw, "read_ps", lambda: next(snaps))
    monkeypatch.setattr(cbw, "WINDOW_S", 0)
    monkeypatch.setattr(cbw.time, "monotonic", iter([0.0, 3.0]).__next__)
    return cbw.sample()


def test_an_exec_keeps_the_cpu_baseline_and_a_reused_pid_does_not(cbw, monkeypatch):
    """Same pid + same start time is the same process even after exec changed its command: only the window's CPU counts.
    A reused pid (other start time) has no baseline."""
    root = {"pid": 1, "ppid": 0, "rss_mb": 1, "cpu_s": 0.0, "start": "Sun Nov  1 09:00:00 2026",
            "cmd": "/A/CodexBar.app/Contents/MacOS/CodexBar"}
    before = {1: root, 2: {"pid": 2, "ppid": 1, "rss_mb": 1, "cpu_s": 600.0, "start": "Sun Nov  1 09:00:01 2026", "cmd": "sh -c probe"}}
    execd = {1: root, 2: {"pid": 2, "ppid": 1, "rss_mb": 1, "cpu_s": 600.3, "start": "Sun Nov  1 09:00:01 2026", "cmd": "node probe.js"}}
    rec = _window(cbw, monkeypatch, before, execd)
    assert rec["total_pct"] == pytest.approx(10.0) and not rec["spike"]  # 0.3 s over 3 s, not 600 s
    reused = {1: root, 2: {"pid": 2, "ppid": 1, "rss_mb": 1, "cpu_s": 0.3, "start": "Sun Nov  1 12:00:00 2026", "cmd": "node probe.js"}}
    rec = _window(cbw, monkeypatch, before, reused)
    assert rec["total_pct"] == pytest.approx(10.0)  # no baseline from the old process: its 600 s are not subtracted


def test_read_ps_parses_start_time_and_command(cbw, monkeypatch):
    import subprocess
    out = ("  101     1  2048   1:02.50 Sun Nov  1 10:04:45 2026     /A/CodexBar.app/Contents/MacOS/CodexBar --port 1\n"
           "  102   101  1024   0:00.10 Sun Nov  1 10:05:00 2026     node probe.js\n")
    monkeypatch.setattr(cbw.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    procs = cbw.read_ps()
    assert procs[101]["start"] == "Sun Nov 1 10:04:45 2026" and procs[101]["cpu_s"] == pytest.approx(62.5)
    assert procs[101]["cmd"] == "/A/CodexBar.app/Contents/MacOS/CodexBar --port 1" and procs[102]["ppid"] == 101


def _install(cbw, tmp_path, monkeypatch, ade_name):
    import plistlib
    monkeypatch.setattr(cbw, "HOME", tmp_path / "home")  # no ~/Library/LaunchAgents yet
    ade = tmp_path / ade_name
    (ade / "bin").mkdir(parents=True)
    (ade / ".git").mkdir()
    (ade / "bin" / "proc-cpu-watch").write_text("")
    monkeypatch.setattr(cbw.shutil, "which", lambda n: "/bin/true")
    calls = []

    def run(args, **k):
        import subprocess
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(cbw.subprocess, "run", run)

    class A:
        cmd = "install"
    A.ade = str(ade)
    rc = cbw.cmd_install(A())
    dest = tmp_path / "home" / "Library/LaunchAgents" / f"{cbw.LABEL}.plist"
    return rc, calls, dest, ade, plistlib


def test_install_writes_a_valid_plist_for_special_paths_and_passes_the_state_dir(cbw, tmp_path, monkeypatch):
    rc, calls, dest, ade, plistlib = _install(cbw, tmp_path, monkeypatch, "a&b <c> 'd'")
    assert rc == 0 and dest.exists()  # LaunchAgents created
    doc = plistlib.loads(dest.read_bytes())
    assert doc["ProgramArguments"] == [f"{ade.resolve()}/bin/proc-cpu-watch", "sample", "--target", "codexbar"]
    assert doc["Label"] == "com.djbclark.codexbar-cpu-watch"
    assert doc["EnvironmentVariables"]["CBW_STATE_DIR"] == str(cbw.STATE_DIR)
    assert doc["StandardOutPath"] == f"{cbw.STATE_DIR}/launchd.out"
    assert [c[1] for c in calls] == ["bootout", "bootstrap"]


def test_install_changes_nothing_when_the_plist_cannot_be_built(cbw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cbw, "PLIST", tmp_path / "missing.plist")
    rc, calls, dest, _, _ = _install(cbw, tmp_path, monkeypatch, "ade")
    assert rc == 2 and not calls and not dest.exists()  # the old job was never booted out
    assert "nothing changed" in capsys.readouterr().err


def test_a_reused_pid_outside_the_tree_is_not_counted(cbw, monkeypatch):
    """A CodexBar child exits and an unrelated process takes its pid: its CPU is not CodexBar's (no false spike)."""
    root = {"pid": 1, "ppid": 0, "rss_mb": 1, "cpu_s": 0.0, "start": "Sun Nov  1 09:00:00 2026",
            "cmd": "/A/CodexBar.app/Contents/MacOS/CodexBar"}
    first = {1: root, 7: {"pid": 7, "ppid": 1, "rss_mb": 1, "cpu_s": 1.0, "start": "Sun Nov  1 09:00:05 2026", "cmd": "node probe.js"}}
    second = {1: root, 7: {"pid": 7, "ppid": 300, "rss_mb": 1, "cpu_s": 1.5, "start": "Sun Nov  1 12:00:00 2026", "cmd": "/usr/bin/unrelated"},
              300: {"pid": 300, "ppid": 0, "rss_mb": 1, "cpu_s": 0.0, "start": "Sun Nov  1 08:00:00 2026", "cmd": "/usr/bin/zsh"}}
    rec = _window(cbw, monkeypatch, first, second)
    assert rec["total_pct"] == 0.0 and not rec["spike"] and [t["pid"] for t in rec["top"]] == [1]


def test_a_child_reparented_away_from_the_tree_still_counts(cbw, monkeypatch):
    """The same process (same pid and start) that left the tree because its parent exited is still counted."""
    root = {"pid": 1, "ppid": 0, "rss_mb": 1, "cpu_s": 0.0, "start": "Sun Nov  1 09:00:00 2026",
            "cmd": "/A/CodexBar.app/Contents/MacOS/CodexBar"}
    child = {"pid": 7, "ppid": 1, "rss_mb": 1, "cpu_s": 1.0, "start": "Sun Nov  1 09:00:05 2026", "cmd": "node probe.js"}
    orphan = dict(child, ppid=999, cpu_s=1.6)
    rec = _window(cbw, monkeypatch, {1: root, 7: child}, {1: root, 7: orphan})
    assert rec["total_pct"] == pytest.approx(20.0)


def test_each_target_has_its_own_state_label_and_cbw_state_dir_override(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("proc_cpu_watch_t", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("proc_cpu_watch_t", loader))
    loader.exec_module(mod)
    monkeypatch.setattr(mod, "HOME", tmp_path)
    monkeypatch.delenv("CBW_STATE_DIR", raising=False)
    mod.use_target("opencode")
    assert mod.STATE_DIR == tmp_path / ".local/state/opencode-cpu-watch" and mod.LABEL == "com.djbclark.opencode-cpu-watch"
    monkeypatch.setenv("CBW_STATE_DIR", str(tmp_path / "x"))
    mod.use_target("codexbar")
    assert mod.STATE_DIR == tmp_path / "x" and mod.LABEL == "com.djbclark.codexbar-cpu-watch"


def test_opencode_roots_are_the_serve_executable_not_any_argument(cbw):
    cbw.use_target("opencode")
    procs = {
        1: proc(1, 0, "opencode serve --hostname 127.0.0.1 --port 0"),
        2: proc(2, 0, "/Users/x/.local/lib/node_modules/@opencode/cli/bin/opencode.exe serve --service"),
        3: proc(3, 1, "/opt/homebrew/bin/bash -c gh run watch 1"),
        4: proc(4, 0, "opencode run fix the bug"),
        5: proc(5, 0, "omp --prompt run opencode serve please"),
        6: proc(6, 0, "/opt/homebrew/bin/rg opencode serve /src"),
        7: proc(7, 0, "/usr/bin/vim /x/opencode serve"),
    }
    assert cbw.tree(procs, me=-1) == {1, 2, 3}


def test_install_for_the_opencode_target(cbw, tmp_path, monkeypatch):
    import plistlib
    cbw.use_target("opencode")
    monkeypatch.setattr(cbw, "HOME", tmp_path / "home")
    ade = tmp_path / "ade"
    (ade / "bin").mkdir(parents=True)
    (ade / ".git").mkdir()
    (ade / "bin" / "proc-cpu-watch").write_text("")
    monkeypatch.setattr(cbw.shutil, "which", lambda n: "/bin/true")
    import subprocess
    monkeypatch.setattr(cbw.subprocess, "run", lambda args, **k: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))

    class A:
        cmd = "install"
    A.ade = str(ade)
    assert cbw.cmd_install(A()) == 0
    doc = plistlib.loads((tmp_path / "home/Library/LaunchAgents/com.djbclark.opencode-cpu-watch.plist").read_bytes())
    assert doc["Label"] == "com.djbclark.opencode-cpu-watch"
    assert doc["ProgramArguments"][-2:] == ["--target", "opencode"]
    assert doc["EnvironmentVariables"]["CBW_STATE_DIR"] == str(cbw.STATE_DIR)


@pytest.mark.parametrize("cmd,name", [
    ("env SECRETWORD", "env"),
    ("sh SECRETWORD", "sh"),
    ("bun x SECRETWORD", "bun"),
    ("node /x/server", "node server"),
    ("python3 manage.py runserver", "python3 manage.py"),
])
def test_an_interpreter_names_only_a_script_shaped_argument(cbw, cmd, name):
    """A bare word after an interpreter (opencode sessions run arbitrary commands) is never logged as a name."""
    assert cbw.label(cmd) == name


def test_records_carry_the_target_and_report_shows_only_its_own(cbw, monkeypatch, capsys):
    for target, secret in (("codexbar", "sk-CB"), ("opencode", "sk-OC")):
        cbw.use_target(target)
        root = "/A/CodexBar.app/Contents/MacOS/CodexBar" if target == "codexbar" else "/opt/homebrew/bin/opencode serve"
        snap = {1: {"pid": 1, "ppid": 0, "rss_mb": 1, "cpu_s": 0.0, "start": "s", "cmd": f"{root} --token={secret}"},
                2: {"pid": 2, "ppid": 1, "rss_mb": 1, "cpu_s": 0.0, "start": "t", "cmd": f"sh -c echo {secret}"}}
        rec = _window(cbw, monkeypatch, snap, snap)
        assert rec["target"] == target and secret not in __import__("json").dumps(rec)
        cbw.append(rec)
    cbw.LOG.open("a").write(__import__("json").dumps({"ts": "legacy", "total_pct": 1.0, "procs": 1, "top": []}) + "\n")

    class A:
        n = 10
    cbw.use_target("codexbar")
    assert cbw.cmd_report(A()) == 0
    out = capsys.readouterr().out
    assert "2 samples scanned" in out and "opencode" not in out.split("\n", 1)[1]  # codexbar row + the legacy row


def test_opencode_root_with_a_space_in_its_path_fails_closed(cbw):
    cbw.use_target("opencode")
    procs = {1: proc(1, 0, "/Users/x/My Tools/opencode serve --port 0"), 2: proc(2, 0, "opencode serve")}
    assert cbw.tree(procs, me=-1) == {2}


@pytest.mark.parametrize("args,needle", [(["sample"], "required: --target"), (["sample", "--target", "nope"], "invalid choice")])
def test_every_subcommand_needs_a_known_target(tmp_path, args, needle):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                       env=dict(__import__("os").environ, CBW_STATE_DIR=str(tmp_path / "s")), timeout=30)
    assert r.returncode == 2 and needle in r.stderr and not (tmp_path / "s").exists()
