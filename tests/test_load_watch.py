"""bin/load-watch: the ci-only registry `bg` reads, the sample window, incident acks and the watcher's `paseo send`. No launchd.
The find-and-tell hot path (attribution through a fake `paseo`) is tests/test_load_watch_find_and_tell.py."""
import importlib.machinery
import importlib.util
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"


def lw_env(tmp_path, **extra_env):
    # HOME is a scratch directory: a `local` decision asks `$HOME/.local/bin/sudo-ask` (djbclark's Touch ID dialog), never the real one
    return dict(os.environ, HOME=str(tmp_path / "home"), LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"), **extra_env)


def run(tmp_path, *args, **extra_env):
    return subprocess.run([sys.executable, str(LW), *args], capture_output=True, text=True, env=lw_env(tmp_path, **extra_env), timeout=30)


def stub_sudo_ask(tmp_path, rc):
    """A fake `sudo-ask` that records its argv (one line per call) and exits `rc`: 0 = Allow + Touch ID, anything else = Deny/cancel."""
    path = tmp_path / "home" / ".local" / "bin" / "sudo-ask"
    path.parent.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "sudo-ask-calls"
    path.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{calls}"\nexit {rc}\n')
    path.chmod(0o755)
    return calls


def rows(tmp_path):
    f = tmp_path / "ci-only.tsv"
    return [ln.split("\t") for ln in f.read_text().splitlines() if not ln.startswith("#")] if f.exists() else []


def approvals_log(tmp_path):
    f = tmp_path / "home" / ".local" / "state" / "bg" / "approvals.log"
    return [ln.split("\t") for ln in f.read_text().splitlines()] if f.exists() else []


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_ci_only_add_check_rm(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    top = os.path.realpath(repo)
    assert run(tmp_path, "ci-only", "add", str(repo / "."), "scripts/ci-run test").returncode == 0
    r = run(tmp_path, "ci-only", "check", str(repo))
    assert (r.returncode, r.stdout.strip()) == (0, "scripts/ci-run test")
    line = [ln for ln in (tmp_path / "ci-only.tsv").read_text().splitlines() if not ln.startswith("#")][0]
    assert line.split("\t")[:3] == [top, "ci", "scripts/ci-run test"]  # repo, mode, CI command, date
    assert run(tmp_path, "ci-only", "check", str(tmp_path)).returncode == 1
    assert run(tmp_path, "ci-only", "rm", str(repo)).returncode == 0
    assert run(tmp_path, "ci-only", "check", str(repo)).returncode == 1


def test_ci_only_add_needs_command(tmp_path):
    assert run(tmp_path, "ci-only", "add", str(tmp_path)).returncode == 2


def test_window_means_and_exited_parents():
    lw = load_module()
    st = {"samples": [{"t": 1, "d": {"10": [2.0, 501, "cc1", 5]}},
                      {"t": 2, "d": {"10": [1.0, 501, "cc1", 5], "11": [0.5, 501, "ld", 5]}}]}
    use, n = lw.window(st)
    assert n == 2 and use["10"][0] == 3.0 and use["11"][0] == 0.5
    parent = lw.ppids(st, {"12": (7, 501, 0.0, "make")})
    assert parent == {"10": 5, "11": 5, "12": 7}  # exited pids keep their ppid for attribution


def test_ack_records_and_unknown_id(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "incidents.jsonl").write_text(json.dumps({"id": "x1", "t": "", "load1": 20, "agent": "claude",
                                                       "session": "s", "cores": 3, "relayed": True}) + "\n")
    assert run(tmp_path, "ack", "x1", "moved to CI").returncode == 0
    assert "moved to CI" in json.loads((state / "incidents.jsonl").read_text())["ack"]
    assert run(tmp_path, "ack", "nope", "x").returncode == 1


def _sampler(tmp_path, monkeypatch):
    lw = load_module()
    clock = {"t": 1000.0}
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "HERMES_PING", tmp_path / "no-such-ping")
    monkeypatch.setattr(lw, "now", lambda: clock["t"])
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (40.0, 40.0, 40.0))
    monkeypatch.setattr(lw.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    monkeypatch.setattr(lw, "attribute", lambda use, span, parent, cmds=None: ({}, [], [], None))
    monkeypatch.setattr(lw, "guard", lambda *args: None)

    class A:
        dry_run = False
        verbose = False

    def at(t):
        clock["t"] = t
        lw.cmd_sample(A())
        return (tmp_path / "sample.log").read_text() if (tmp_path / "sample.log").exists() else ""
    at.lw = lw
    return at


def test_sustain_is_time_based_and_tolerates_slow_samples(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    assert at(1000) == ""
    assert at(1200) == ""            # 200 s hot: not yet
    assert "sustained load" in at(1400)  # 400 s hot, samples 200 s apart (a stalled launchd)



def test_unexplained_load_reaches_the_watcher_hourly(tmp_path, monkeypatch):
    """Hermes hears an unexplained sustained load every 6 h; the watcher every hour (djbclark, 2026-10-20)."""
    at = _sampler(tmp_path, monkeypatch)
    lw = at.lw
    load = {"v": 40.0}
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (load["v"],) * 3)
    sent = []
    monkeypatch.setattr(lw, "paseo_send", lambda w, text: sent.append(text) or "sent")
    lw.save_watcher({"channel": "paseo", "target": "agent-a"})

    def episode(start):
        load["v"] = 40.0
        at(start)
        at(start + 400)
        load["v"] = 1.0
        at(start + 500)  # cools off: the next spike is a new episode

    episode(1000)
    assert len(sent) == 1 and "no agent's build and no single process above 1.5 cores explains it" in sent[0]
    episode(2000)                      # 1000 s later: inside the hour
    assert len(sent) == 1
    episode(1000 + lw.WATCHER_NOCPU_S + 100)
    assert len(sent) == 2

def test_long_gap_restarts_the_clock(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    at(1000)
    assert at(2000) == ""            # 1000 s gap is a sleep: hot clock restarts at 2000
    assert at(2200) == ""
    assert "sustained load" in at(2400)


def test_ci_decide_check_modes_and_legacy_rows(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    top = os.path.realpath(repo)
    (tmp_path / "ci-only.tsv").write_text(f"{top}\tscripts/ci-run\t2026-10-18\n")  # pre-decide 3-column row
    stub_sudo_ask(tmp_path, 0)
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["ci", "scripts/ci-run"]
    assert run(tmp_path, "ci-only", "check", str(repo)).stdout.strip() == "scripts/ci-run"
    assert run(tmp_path, "ci", "decide", str(repo), "local", "needs Xcode").returncode == 0
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["local", "needs Xcode"]
    assert run(tmp_path, "ci-only", "check", str(repo)).returncode == 1  # bg's old reader: only ci refuses
    assert run(tmp_path, "ci", "decide", str(repo), "local").returncode == 2  # a reason is required
    assert run(tmp_path, "ci", "check", str(tmp_path)).returncode == 1  # undecided


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_local_decision_approved_is_recorded_and_logged(tmp_path):
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 0)
    r = run(tmp_path, "ci", "decide", str(repo), "local", "needs Xcode")
    assert r.returncode == 0, r.stderr
    assert [x[:3] for x in rows(tmp_path)] == [[os.path.realpath(repo), "local", "needs Xcode"]]
    ask = calls.read_text().splitlines()
    assert len(ask) == 1 and ask[0].startswith("-k /usr/bin/printf")  # fresh auth (-k), not a cached sudo ticket
    assert os.path.realpath(repo) in ask[0] and "needs Xcode" in ask[0]  # djbclark sees the directory and the reason
    (log,) = approvals_log(tmp_path)
    assert log[1:2] == ["lw-local-approved"] and log[3] == os.path.realpath(repo) and log[4] == "load-watch"
    assert "needs Xcode" not in "\t".join(log)  # the reason is not logged


def test_local_decision_denied_cancelled_or_unaskable_writes_nothing(tmp_path):
    repo = _repo(tmp_path)
    run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run")
    before = (tmp_path / "ci-only.tsv").read_text()
    assert rows(tmp_path)[0][1] == "ci"
    # no sudo-ask at all (missing helper, no GUI): refused
    r = run(tmp_path, "ci", "decide", str(repo), "local", "why")
    assert r.returncode == 1 and "djbclark" in r.stderr and "nothing was recorded" in r.stderr
    assert "pending" not in r.stderr  # a denial must not steer the agent to a decision that also runs here
    assert (tmp_path / "ci-only.tsv").read_text() == before
    assert [x[1] for x in approvals_log(tmp_path)] == ["lw-local-unavailable"]
    # Deny (rc 1) and cancel/timeout (rc 124, 143): refused
    for rc in (1, 124, 143):
        stub_sudo_ask(tmp_path, rc)
        r = run(tmp_path, "ci", "decide", str(repo), "local", "why")
        assert r.returncode == 1 and "did not approve" in r.stderr, rc
        assert "pending" not in r.stderr, rc
        assert (tmp_path / "ci-only.tsv").read_text() == before, rc
    assert [x[1] for x in approvals_log(tmp_path)][1:] == ["lw-local-denied"] * 3
    # a non-executable helper is as good as none
    (tmp_path / "home" / ".local" / "bin" / "sudo-ask").chmod(0o644)
    assert run(tmp_path, "ci", "decide", str(repo), "local", "why").returncode == 1
    assert (tmp_path / "ci-only.tsv").read_text() == before


def test_local_and_pending_decisions_are_gated_and_ci_is_not(tmp_path):
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 1)  # every ask is denied
    asked = lambda: len(calls.read_text().splitlines()) if calls.exists() else 0
    assert run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run").returncode == 0  # ci is never gated
    assert asked() == 0
    # ci -> pending downgrades CI-first to running here: gated like local (lead adversary, PR 744 B2a)
    r = run(tmp_path, "ci", "decide", str(repo), "pending", "seeded")
    assert r.returncode == 1 and "did not approve a `pending` decision" in r.stderr
    assert rows(tmp_path)[0][1] == "ci" and asked() == 1
    assert run(tmp_path, "ci", "decide", str(repo), "local", "why").returncode == 1  # ci -> local too
    assert rows(tmp_path)[0][1] == "ci" and asked() == 2
    # a pending row (approved once) <-> local is gated both ways; back to ci is not
    stub_sudo_ask(tmp_path, 0)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "seeded").returncode == 0
    assert rows(tmp_path)[0][1] == "pending"
    stub_sudo_ask(tmp_path, 1)
    assert run(tmp_path, "ci", "decide", str(repo), "local", "why").returncode == 1  # pending -> local
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "seeded, still").returncode == 0  # same mode: note only, no dialog
    assert rows(tmp_path)[0][1:3] == ["pending", "seeded, still"]
    assert run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run").returncode == 0
    assert rows(tmp_path)[0][1] == "ci"
    assert run(tmp_path, "ci", "check", str(repo)).returncode == 0  # reads are ungated
    assert run(tmp_path, "ci", "list").returncode == 0
    assert run(tmp_path, "ci", "rm", str(repo)).returncode == 0


def test_pending_decision_approved_is_recorded_and_logged_as_pending(tmp_path):
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 0)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "seeded").returncode == 0
    assert rows(tmp_path)[0][1:3] == ["pending", "seeded"]
    (ask,) = calls.read_text().splitlines()
    assert "PENDING" in ask and os.path.realpath(repo) in ask
    (log,) = approvals_log(tmp_path)
    assert log[1] == "lw-pending-approved" and log[3] == os.path.realpath(repo)  # the event names the mode (rv-758 B1), not `local`


def test_pending_decision_denied_or_unaskable_is_logged_as_pending(tmp_path):
    repo = _repo(tmp_path)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "why").returncode == 1  # no sudo-ask at all
    stub_sudo_ask(tmp_path, 1)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "why").returncode == 1  # Deny
    assert [x[1] for x in approvals_log(tmp_path)] == ["lw-pending-unavailable", "lw-pending-denied"]


def test_pending_glob_key_is_gated(tmp_path):
    """PR 744 B2b: an ungated `pending` glob such as `DIR/*` made every undecided repo under it run here."""
    repo = _repo(tmp_path)
    glob = os.path.realpath(tmp_path) + "/*"
    calls = stub_sudo_ask(tmp_path, 1)
    r = run(tmp_path, "ci", "decide", glob, "pending", "everything")
    assert r.returncode == 1 and not (tmp_path / "ci-only.tsv").exists() and calls.exists()
    assert run(tmp_path, "ci", "check", str(repo)).returncode == 1  # still undecided, so bg still refuses
    stub_sudo_ask(tmp_path, 0)
    assert run(tmp_path, "ci", "decide", glob, "pending", "everything").returncode == 0
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["pending", "everything"]


def test_existing_local_row_keeps_working_and_edits_its_reason_without_a_dialog(tmp_path):
    repo = _repo(tmp_path)
    top = os.path.realpath(repo)
    (tmp_path / "ci-only.tsv").write_text(f"{top}\tlocal\tmacOS only\t2026-10-18\n")  # recorded before the gate
    calls = stub_sudo_ask(tmp_path, 1)  # a denying helper: it must not even be asked
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["local", "macOS only"]
    assert run(tmp_path, "ci", "decide", str(repo), "local", "macOS only, still").returncode == 0
    assert rows(tmp_path)[0][1:3] == ["local", "macOS only, still"]
    assert not calls.exists()


def test_control_characters_cannot_plant_a_local_row_past_the_gate(tmp_path):
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 1)  # every ask is denied
    glob = os.path.realpath(tmp_path) + "/*"
    evil = f"note\n{glob}\tlocal\tx"  # a second, `local` registry row smuggled into an ungated pending/ci decision
    for mode in ("pending", "ci"):
        r = run(tmp_path, "ci", "decide", str(repo), mode, evil)
        assert r.returncode == 2 and "control character" in r.stderr, mode
    assert run(tmp_path, "ci-only", "add", str(repo), evil).returncode == 2
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "a\tb").returncode == 2
    for sep in ("\x0b", "\x0c", "\x1c", "\x7f", "\x85", "\u2028", "\u2029"):  # what str.splitlines() splits on, and DEL/C1
        assert run(tmp_path, "ci", "decide", str(repo), "pending", f"a{sep}b").returncode == 2, repr(sep)
    assert not (tmp_path / "ci-only.tsv").exists() and not calls.exists()
    # the same through a hostile directory name, and a hand-built row set reaching write_registry
    odd = tmp_path / "x\ny"
    odd.mkdir()
    assert run(tmp_path, "ci", "decide", str(odd), "pending", "ok").returncode == 2
    assert not (tmp_path / "ci-only.tsv").exists()


def test_write_registry_refuses_control_characters(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "REGISTRY", tmp_path / "ci-only.tsv")
    try:
        lw.write_registry({"/r": ["pending", "n\n/x\tlocal\ty", "2026-11-15"]})
    except SystemExit as e:
        assert "control character" in str(e)
    else:
        raise AssertionError("write_registry accepted a control character")
    assert not (tmp_path / "ci-only.tsv").exists()


def test_caller_environment_cannot_make_the_helper_approve(tmp_path):
    repo = _repo(tmp_path)
    path = tmp_path / "home" / ".local" / "bin" / "sudo-ask"
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/bash\nexit 1\n")  # a bash helper that denies, like the real sudo-ask
    path.chmod(0o755)
    hook = tmp_path / "hook.sh"
    hook.write_text("exit 0\n")  # BASH_ENV runs this first in a non-interactive bash: it would approve before the helper's own code
    assert run(tmp_path, "ci", "decide", str(repo), "local", "why", BASH_ENV=str(hook)).returncode == 1
    assert run(tmp_path, "ci", "decide", str(repo), "local", "why", ENV=str(hook), SHELLOPTS="xtrace").returncode == 1
    assert not (tmp_path / "ci-only.tsv").exists()


def _slow_approver(tmp_path):
    """A sudo-ask that waits for a flag file, then approves: the dialog is 'open' until the test creates the flag."""
    flag, started = tmp_path / "flag", tmp_path / "started"
    path = tmp_path / "home" / ".local" / "bin" / "sudo-ask"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n: > {started}\nwhile [ ! -e {flag} ]; do sleep 0.05; done\nexit 0\n")
    path.chmod(0o755)
    return flag, started


def _wait_for(path):
    for _ in range(200):
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def test_changes_made_during_the_approval_wait_survive(tmp_path):
    """PR 744 B1: the registry snapshot must not be held across the dialog (a stale write-back restored an unapproved `local` row)."""
    repo, j, k = _repo(tmp_path), tmp_path / "j", tmp_path / "k"
    for d in (j, k):
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
    jt, kt = os.path.realpath(j), os.path.realpath(k)
    (tmp_path / "ci-only.tsv").write_text(f"{jt}\tlocal\tgrandfathered\t2026-10-18\n")
    flag, started = _slow_approver(tmp_path)
    p = subprocess.Popen([sys.executable, str(LW), "ci", "decide", str(repo), "local", "needs Xcode"], env=lw_env(tmp_path),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for(started)  # the dialog is open and the first process has read the registry
        assert run(tmp_path, "ci", "decide", str(j), "ci", "scripts/ci-run").returncode == 0  # the operator moves J to CI meanwhile
        assert run(tmp_path, "ci", "decide", str(k), "ci", "scripts/ci-run").returncode == 0
        flag.write_text("")
        assert p.wait(timeout=30) == 0
    finally:
        p.kill()
    got = {r[0]: r[1] for r in rows(tmp_path)}
    assert got == {os.path.realpath(repo): "local", jt: "ci", kt: "ci"}, got


def test_concurrent_registry_writers_lose_no_update(tmp_path):
    dirs = []
    for i in range(10):
        d = tmp_path / f"r{i}"
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        dirs.append(d)
    procs = [subprocess.Popen([sys.executable, str(LW), "ci-only", "add", str(d), "scripts/ci-run"], env=lw_env(tmp_path),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for d in dirs]
    assert [p.wait(timeout=60) for p in procs] == [0] * 10
    assert sorted(r[0] for r in rows(tmp_path)) == sorted(os.path.realpath(d) for d in dirs)


def test_helper_gets_no_tmpdir(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "HOME", tmp_path)
    monkeypatch.setenv("TMPDIR", "/somewhere/evil")
    monkeypatch.setenv("BASH_ENV", "/x")
    env = lw.helper_env()
    assert "TMPDIR" not in env and "BASH_ENV" not in env and env["HOME"] == str(tmp_path)


def test_damaged_row_is_named_in_the_refusal(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "ci-only.tsv").write_text("/damaged\x01repo\tci\tcmd\t2026-10-18\n")
    r = run(tmp_path, "ci-only", "add", str(repo), "scripts/ci-run")
    assert r.returncode == 1 and "damaged" in r.stderr and "nothing was written" in r.stderr


def test_glob_local_decision_is_gated(tmp_path):
    stub_sudo_ask(tmp_path, 1)
    glob = os.path.realpath(tmp_path) + "/*"
    assert run(tmp_path, "ci", "decide", glob, "local", "all of it").returncode == 1
    assert not (tmp_path / "ci-only.tsv").exists()


def test_approval_log_escapes_the_directory_and_uses_bgs_timestamp(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "HOME", tmp_path / "home")
    lw.local_approval_log("lw-local-approved", "/r\n2026-01-01T00:00:00-05:00\tlw-local-approved\tdeadbeef\t/etc\tbg", "why")
    (line,) = (tmp_path / "home/.local/state/bg/approvals.log").read_text().splitlines()
    cols = line.split("\t")
    assert len(cols) == 5 and cols[1] == "lw-local-approved" and cols[4] == "load-watch" and "\\n" in cols[3]
    assert cols[0][-6] in "+-" and cols[0][-3] == ":"  # 2026-11-15T19:35:00-05:00, as `gdate -Is`


def test_local_decision_helper_timeout_or_crash_is_a_refusal(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "HOME", tmp_path / "home")
    monkeypatch.setattr(lw, "BGRUN_BIN", tmp_path / "no-bgrun")  # never the real bgrun (and so never a real ticket)
    slow = tmp_path / "sudo-ask"
    slow.write_text("#!/bin/sh\nsleep 30\nexit 0\n")  # would approve, but only after the outer bound
    slow.chmod(0o755)
    monkeypatch.setattr(lw, "SUDO_ASK", slow)
    monkeypatch.setattr(lw, "SUDO_ASK_TIMEOUT_S", 0.5)
    assert lw.approve_local_decision("/some/repo", "why") is False
    bad = tmp_path / "bad-ask"
    bad.write_text("not an executable script\n")  # exec format error: OSError
    bad.chmod(0o755)
    monkeypatch.setattr(lw, "SUDO_ASK", bad)
    assert lw.approve_local_decision("/some/repo", "why") is False


def stub_bgrun(path, rc, out="", sleep=0):
    """A fake `bgrun`: records its argv (one line per call) next to itself, prints `out`, exits `rc`. Never the real one, so no real ticket is read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    calls = path.parent / (path.name + "-calls")
    path.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{calls}"\nsleep {sleep}\nprintf \'%s\\n\' "{out}"\nexit {rc}\n')
    path.chmod(0o755)
    return calls


def ticket_module(tmp_path, monkeypatch, bgrun_rc=None, ask_rc=0, **kw):
    """load-watch with HOME, SUDO_ASK and BGRUN_BIN all in tmp_path; returns (module, bgrun calls file, sudo-ask calls file)."""
    lw = load_module()
    monkeypatch.setattr(lw, "HOME", tmp_path / "home")
    monkeypatch.setattr(lw, "REGISTRY", tmp_path / "ci-only.tsv")  # never the real registry
    ask_calls = stub_sudo_ask(tmp_path, ask_rc)
    monkeypatch.setattr(lw, "SUDO_ASK", tmp_path / "home" / ".local" / "bin" / "sudo-ask")
    bg = tmp_path / "bin" / "bgrun"
    monkeypatch.setattr(lw, "BGRUN_BIN", bg)
    bg_calls = stub_bgrun(bg, bgrun_rc, **kw) if bgrun_rc is not None else bg.parent / "bgrun-calls"
    return lw, bg_calls, ask_calls


def test_live_ticket_covers_a_local_decision_without_the_dialog(tmp_path, monkeypatch, capsys):
    lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, 0, out="7f3a9c01 until 2026-11-22 02:10 EST")
    assert lw.approve_local_decision("/some/repo", "why") == "7f3a9c01"  # the ticket id, not just True
    assert bg_calls.read_text().splitlines() == ["approve-local check /some/repo"]
    assert not ask_calls.exists()
    err = capsys.readouterr().err
    assert "7f3a9c01 until 2026-11-22 02:10 EST" in err and "no dialog" in err
    assert [row[1] for row in approvals_log(tmp_path)] == ["lw-local-ticket"]
    assert approvals_log(tmp_path)[0][-1] == "ticket=7f3a9c01"  # the audit trail names the ticket


def test_no_live_ticket_falls_through_to_the_dialog(tmp_path, monkeypatch):
    for rc in (1, 2, 127):  # no ticket / narrowed to one command, missing directory, anything else
        lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, rc)
        assert lw.approve_local_decision("/some/repo", "why") is True  # the stub sudo-ask allows
        assert ask_calls.read_text().count("\n") == 1
        ask_calls.unlink()
    assert {row[1] for row in approvals_log(tmp_path)} == {"lw-local-approved"}
    lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, 1, ask_rc=1)
    assert lw.approve_local_decision("/some/repo", "why") is False  # a refused dialog is still a refusal
    ask_calls.unlink(missing_ok=True)
    lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, 1, out="7f3a9c01 until later")  # an id-shaped line with a non-zero exit: not a ticket
    assert lw.approve_local_decision("/some/repo", "why") is True and ask_calls.read_text().count("\n") == 1
    ask_calls.unlink(missing_ok=True)
    lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, 0, out="tk-7f3a until later")  # exit 0 but no 8-hex id to name: not trusted
    assert lw.approve_local_decision("/some/repo", "why") is True and ask_calls.read_text().count("\n") == 1


def test_ticket_check_missing_broken_or_slow_falls_through(tmp_path, monkeypatch):
    lw, _, ask_calls = ticket_module(tmp_path, monkeypatch)  # no bgrun file at all
    assert lw.approve_local_decision("/some/repo", "why") is True and ask_calls.read_text().count("\n") == 1
    ask_calls.unlink()
    bad = tmp_path / "bin" / "bgrun"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not an executable script\n")  # exec format error: OSError
    bad.chmod(0o755)
    assert lw.approve_local_decision("/some/repo", "why") is True and ask_calls.read_text().count("\n") == 1
    ask_calls.unlink()
    stub_bgrun(bad, 0, out="7f3a9c01 until later", sleep=30)  # would cover, but only after the bound
    monkeypatch.setattr(lw, "TICKET_CHECK_TIMEOUT_S", 0.5)
    assert lw.approve_local_decision("/some/repo", "why") is True and ask_calls.read_text().count("\n") == 1
    assert {row[1] for row in approvals_log(tmp_path)} == {"lw-local-approved"}


def test_ticket_never_covers_other_modes(tmp_path, monkeypatch):
    lw, bg_calls, ask_calls = ticket_module(tmp_path, monkeypatch, 0, out="7f3a9c01 until 2026-11-22 02:10 EST")
    assert lw.approve_local_decision("/some/repo", "why", "pending") is True  # asked (the stub allows), not covered
    assert lw.approve_local_decision("/some/repo", "why", "ci") is True
    assert not bg_calls.exists()  # bgrun never even consulted
    assert ask_calls.read_text().count("\n") == 2
    assert {row[1] for row in approvals_log(tmp_path)} == {"lw-pending-approved", "lw-ci-approved"}


def test_ci_decide_local_is_recorded_under_a_live_ticket_with_no_dialog(tmp_path):
    repo = _repo(tmp_path)
    ask_calls = stub_sudo_ask(tmp_path, 1)  # a dialog would be denied
    bgrun = tmp_path / "home" / "ops" / "site-private-djbclark" / "bin" / "bgrun"
    bg_calls = stub_bgrun(bgrun, 0, out="0badc0de until 2026-11-22 02:10 EST")
    r = run(tmp_path, "ci", "decide", str(repo), "local", "offline focused tests")
    assert r.returncode == 0 and rows(tmp_path)[0][:2] == [os.path.realpath(repo), "local"]
    assert rows(tmp_path)[0][2] == "[ticket 0badc0de] offline focused tests"  # recorded as ticket-bound
    assert not ask_calls.exists() and bg_calls.read_text().splitlines() == [f"approve-local check {os.path.realpath(repo)}"]
    assert "0badc0de until" in r.stderr
    top = os.path.realpath(repo)
    assert run(tmp_path, "ci", "check", str(repo)).stdout.startswith("local\t[ticket 0badc0de] ")  # live: honoured
    stub_bgrun(bgrun, 1)  # ticket expired or revoked: the row no longer counts
    r = run(tmp_path, "ci", "check", str(repo))
    assert r.returncode == 1 and r.stdout == "" and "no live ticket covers" in r.stderr
    r = run(tmp_path, "ci", "decide", str(repo), "local", "new note")  # a ticket row's note cannot be changed into a permanent row without the dialog
    assert r.returncode == 1 and rows(tmp_path)[0][2].startswith("[ticket ")
    stub_bgrun(bgrun, 0, out="0badc0de until 2026-11-22 02:10 EST")
    r = run(tmp_path, "ci", "decide", str(repo), "pending", "note")  # a ticket is not a pending approval: the (denying) dialog decides
    assert r.returncode == 1


def test_a_ticket_never_overwrites_a_ci_decision_or_records_a_glob(tmp_path):
    repo = _repo(tmp_path)
    ask_calls = stub_sudo_ask(tmp_path, 1)  # a dialog would be denied
    bg_calls = stub_bgrun(tmp_path / "home" / "ops" / "site-private-djbclark" / "bin" / "bgrun", 0, out="0badc0de until 2026-11-22 02:10 EST")
    assert run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run").returncode == 0
    r = run(tmp_path, "ci", "decide", str(repo), "local", "flip")  # live ticket, but a recorded `ci` decision: asks (and is denied)
    assert r.returncode == 1 and rows(tmp_path)[0][1] == "ci" and ask_calls.exists() and not bg_calls.exists()
    g = run(tmp_path, "ci", "decide", str(tmp_path) + "/*", "local", "everywhere")  # a glob row: asks too, ticket or no ticket
    assert g.returncode == 1 and all(r[0] != str(tmp_path) + "/*" for r in rows(tmp_path))
    assert not bg_calls.exists()


def test_a_ci_row_recorded_during_the_ticket_check_is_not_overwritten(tmp_path):
    repo = _repo(tmp_path)
    top = os.path.realpath(repo)
    ask_calls = stub_sudo_ask(tmp_path, 1)  # the dialog is denied
    bgrun = tmp_path / "home" / "ops" / "site-private-djbclark" / "bin" / "bgrun"
    bgrun.parent.mkdir(parents=True, exist_ok=True)
    reg = tmp_path / "ci-only.tsv"
    # the stub covers the directory, but writes a `ci` row for it first (another agent deciding at the same moment)
    bgrun.write_text(f"#!/bin/sh\nmkdir -p '{reg.parent}'\nprintf '%s\\t%s\\t%s\\t%s\\n' '{top}' ci scripts/ci-run 2026-11-21 > '{reg}'\necho '0badc0de until x'\nexit 0\n")
    bgrun.chmod(0o755)
    r = run(tmp_path, "ci", "decide", str(repo), "local", "race")
    assert r.returncode == 1 and ask_calls.exists()  # the dialog decided (and denied), the ticket did not
    assert rows(tmp_path)[0][1] == "ci"


def test_a_ci_row_at_the_main_checkout_or_a_glob_recorded_during_the_ticket_check_is_not_shadowed(tmp_path):
    # the race guard must use decision() (main worktree, pasture source, covering glob), not only the row at the directory itself
    repo = _repo(tmp_path)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(git + ["worktree", "add", "-q", str(wt)], check=True)
    top = os.path.realpath(repo)
    for key in (top, os.path.dirname(top) + "/*"):  # the main checkout, then a glob over its parent
        (tmp_path / "ci-only.tsv").unlink(missing_ok=True)
        ask_calls = stub_sudo_ask(tmp_path, 1)  # the dialog is denied
        ask_calls.unlink(missing_ok=True)
        bgrun = tmp_path / "home" / "ops" / "site-private-djbclark" / "bin" / "bgrun"
        bgrun.parent.mkdir(parents=True, exist_ok=True)
        reg = tmp_path / "ci-only.tsv"
        bgrun.write_text(f"#!/bin/sh\nprintf '%s\\t%s\\t%s\\t%s\\n' '{key}' ci scripts/ci-run 2026-11-21 > '{reg}'\necho '0badc0de until x'\nexit 0\n")
        bgrun.chmod(0o755)
        r = run(tmp_path, "ci", "decide", str(wt), "local", "race")
        assert r.returncode == 1 and ask_calls.exists(), key  # the dialog decided (and denied), not the ticket
        assert [row[0] for row in rows(tmp_path)] == [key]  # no row was written at the worktree


def test_a_ticket_row_needs_a_live_ticket_over_the_directory_being_run(tmp_path):
    repo = _repo(tmp_path)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(git + ["worktree", "add", "-q", str(wt)], check=True)
    bgrun = tmp_path / "home" / "ops" / "site-private-djbclark" / "bin" / "bgrun"
    stub_sudo_ask(tmp_path, 1)
    stub_bgrun(bgrun, 0, out="0badc0de until 2026-11-22 02:10 EST")
    assert run(tmp_path, "ci", "decide", str(repo), "local", "tests").returncode == 0
    assert run(tmp_path, "ci", "check", str(wt)).returncode == 0  # the ticket covers the worktree too
    # a ticket scoped to the repo only: bgrun's check fails for the worktree path, so the inherited row does not apply there
    bgrun.write_text(f"#!/bin/sh\ncase \"$3\" in '{os.path.realpath(wt)}') exit 1 ;; esac\necho '0badc0de until x'\nexit 0\n")
    r = run(tmp_path, "ci", "check", str(wt))
    assert r.returncode == 1 and "no live ticket covers" in r.stderr
    assert run(tmp_path, "ci", "check", str(repo)).returncode == 0
    # and the other way round: covered at the worktree but not at the row's own directory
    bgrun.write_text(f"#!/bin/sh\ncase \"$3\" in '{os.path.realpath(repo)}') exit 1 ;; esac\necho '0badc0de until x'\nexit 0\n")
    assert run(tmp_path, "ci", "check", str(wt)).returncode == 1


def test_ci_only_add_still_records_ci_without_a_dialog(tmp_path):
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 1)
    assert run(tmp_path, "ci-only", "add", str(repo), "scripts/ci-run test").returncode == 0
    assert rows(tmp_path)[0][1] == "ci" and not calls.exists()


def test_ci_worktree_and_glob_take_a_decision(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(git + ["worktree", "add", "-q", str(tmp_path / "wt")], check=True)
    stub_sudo_ask(tmp_path, 0)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "seeded").returncode == 0
    out = run(tmp_path, "ci", "check", str(tmp_path / "wt")).stdout.strip().split("\t")
    assert out == ["pending", "seeded", os.path.realpath(repo)]
    other = tmp_path / "pastures" / "p1"
    other.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    assert run(tmp_path, "ci", "check", str(other)).returncode == 1
    glob = os.path.realpath(tmp_path / "pastures") + "/*"
    assert run(tmp_path, "ci", "decide", glob, "local", "queue in flight").returncode == 0
    assert run(tmp_path, "ci", "check", str(other)).stdout.split("\t")[0] == "local"


def _guard(tmp_path, monkeypatch, jobs, runs=None):
    lw = load_module()
    calls = []
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "GUARD", tmp_path / "guard.tsv")
    monkeypatch.setattr(lw, "HERMES_PING", tmp_path / "no-such-ping")
    monkeypatch.setattr(lw, "launchd_jobs", lambda: dict(jobs))
    monkeypatch.setattr(lw, "job_info", lambda label: (runs["n"] if runs else None, str(tmp_path / "j.plist")))
    monkeypatch.setattr(lw.time, "sleep", lambda s: None)
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: calls.append(argv) or
                        subprocess.CompletedProcess(argv, 0, "", ""))
    (tmp_path / "j.plist").write_text("x")
    return lw, calls


def test_guard_hang_cools_down_retests_and_passes(tmp_path, monkeypatch):
    jobs = {"com.x.job": (100, "0")}
    lw, calls = _guard(tmp_path, monkeypatch, jobs)
    (tmp_path / "guard.tsv").write_text("com.x.job\thang_s=120\tAFS\n")
    table = {"100": (1, 501, 0.0, "python lockers"), "101": (100, 501, 0.0, "aklog -path /afs/x")}
    lw.PSTATE.clear()
    lw.PSTATE.update({"100": ("S", 1000), "101": ("U", 1000)})
    st = {}
    lw.guard(st, table, 1000.0, False)
    assert st["guard"]["com.x.job"].get("state") is None      # stuck, but not for 120 s yet
    lw.guard(st, table, 1130.0, False)
    s = st["guard"]["com.x.job"]
    assert s["state"] == "cooldown" and "hung" in s["trip"]
    assert ["launchctl", "bootout", f"gui/{lw.MY_UID}/com.x.job"] in calls
    assert any(c[:2] == ["kill", "-TERM"] and "101" in c for c in calls)
    jobs.clear()                                              # booted out
    lw.guard(st, {}, 1130.0 + lw.GUARD_COOLDOWN_S, False)
    assert s["state"] == "testing"
    assert ["launchctl", "bootstrap", f"gui/{lw.MY_UID}", str(tmp_path / "j.plist")] in calls
    lw.guard(st, {}, 1130.0 + lw.GUARD_COOLDOWN_S + lw.GUARD_TEST_S, False)
    assert s["state"] == "ok"


def test_guard_fifth_round_in_a_day_stops_for_good(tmp_path, monkeypatch):
    lw, calls = _guard(tmp_path, monkeypatch, {"com.x.job": (100, "0")})
    (tmp_path / "guard.tsv").write_text("com.x.job\tmax_rss_mb=10\t\n")
    lw.PSTATE.clear()
    lw.PSTATE["100"] = ("S", 50 * 1024)
    t = 10000.0
    st = {"guard": {"com.x.job": {"rounds": [t - 4000, t - 3000, t - 2000, t - 1000]}}}
    lw.guard(st, {"100": (1, 501, 0.0, "hog")}, t, False)
    assert st["guard"]["com.x.job"]["state"] == "permanent"
    assert ["launchctl", "disable", f"gui/{lw.MY_UID}/com.x.job"] in calls


def test_guard_catches_a_crash_loop_on_any_job(tmp_path, monkeypatch):
    runs = {"n": 100}
    lw, calls = _guard(tmp_path, monkeypatch, {"com.y.loop": (None, "1")}, runs)
    lw.PSTATE.clear()
    st = {}
    lw.guard(st, {}, 1000.0, False)
    runs["n"] = 130
    lw.guard(st, {}, 1000.0 + lw.LOOP_CHECK_S, False)
    s = st["guard"]["com.y.loop"]
    assert s["state"] == "cooldown" and "crash loop: 30 restarts" in s["trip"]



def test_guard_catches_a_slow_crash_loop(tmp_path, monkeypatch):
    """litellm, 2026-10-20: a restart every ~32 s stays under the fast rule (20 per 10 min) for ever; the slow
    rule (60 in 2 h) must trip it."""
    runs = {"n": 100}
    lw, calls = _guard(tmp_path, monkeypatch, {"com.y.slow": (None, "1")}, runs)
    lw.PSTATE.clear()
    st, t, checks = {}, 1000.0, 0
    while st.get("guard", {}).get("com.y.slow", {}).get("state") != "cooldown":
        assert checks < 60, "slow loop never tripped"
        lw.guard(st, {}, t, False)
        t += lw.LOOP_CHECK_S
        runs["n"] += 3  # 15 per 10 min: under the fast rule
        checks += 1
    s = st["guard"]["com.y.slow"]
    assert "crash loop: 60 restarts in 40 min" in s["trip"]
    assert ["launchctl", "bootout", f"gui/{lw.MY_UID}/com.y.slow"] in calls

# ---- brief attribution: the work's repo, and whether it ran under bg (incident 20261018-2056-82c4844a) -----------
BG = str(Path.home() / "ops/site-private/bin/bgrun")


def _work(monkeypatch, procs, parent, cmds, cwds, tops, rows=None, session_top="/r/ade"):
    lw = load_module()
    monkeypatch.setattr(lw, "proc_cwds", lambda pids: {str(p): cwds[str(p)] for p in pids if str(p) in cwds})
    monkeypatch.setattr(lw, "git_top", lambda path: tops.get(path, ""))
    monkeypatch.setattr(lw, "forgejo_remote", lambda top: "")
    monkeypatch.setattr(lw, "main_worktree", lambda top: "")
    monkeypatch.setattr(lw, "pasture_source", lambda top: "")
    monkeypatch.setattr(lw, "registry", lambda: rows or {})
    session = {"id": "s1", "agent": "claude/opus", "name": "ade-87", "cwd": "/r/ade"}
    g = {"session": session, "cores": sum(c for _, c in procs),
         "procs": [{"pid": pid, "cores": c, "cmd": "rustc x"} for pid, c in procs]}
    return lw, g, lw.work_repos(g, session_top, parent, cmds)


def test_work_repo_is_the_process_cwd_not_the_sessions(monkeypatch):
    _, _, w = _work(monkeypatch, [(100, 1.0)], {"100": 1000}, {"100": "rustc"}, {"100": "/r/sudo"},
                    {"/r/sudo": "/r/sudo"})
    assert not w["guess"] and [r["top"] for r in w["repos"]] == ["/r/sudo"]


def test_brew_child_in_a_temp_dir_takes_its_ancestors_repo(monkeypatch):
    parent = {"300": 250, "250": 200, "200": 150, "150": 1000}
    cwds = {"300": "/tmp/build", "250": "/tmp", "200": "/r/sudo", "150": "/r/ade"}
    _, _, w = _work(monkeypatch, [(300, 0.8)], parent, {}, cwds, {"/r/sudo": "/r/sudo", "/r/ade": "/r/ade"})
    assert [r["top"] for r in w["repos"]] == ["/r/sudo"]  # nearest ancestor inside a repo, not the farther one


def test_under_bg_and_outside_bg(monkeypatch):
    parent = {"300": 200, "200": 150, "150": 1000, "400": 1000}
    cmds = {"150": f"/bin/bash {BG} just release", "200": "just release"}
    cwds = {"300": "/r/sudo", "400": "/r/sudo"}
    _, _, w = _work(monkeypatch, [(300, 1.0), (400, 0.5)], parent, cmds, cwds, {"/r/sudo": "/r/sudo"})
    r = w["repos"][0]
    assert r["cores"] == 1.5 and r["bg_cores"] == 1.0 and r["rule"] == "release"
    _, _, w = _work(monkeypatch, [(400, 0.5)], parent, cmds, cwds, {"/r/sudo": "/r/sudo"})
    assert w["repos"][0]["bg_cores"] == 0.0


def test_bg_rules_and_lookalikes():
    lw = load_module()
    assert lw.bg_args(f"/bin/bash {BG} pytest tests/test_x.py") == ["pytest", "tests/test_x.py"]
    assert lw.bg_args(f"{BG} just release") == ["just", "release"]
    assert lw.bg_args("cat /Users/x/ops/site-private/bin/bgrun") is None  # reading it is not running it
    assert lw.bg_args("python other/bin/bgrun") is None
    for name in ("bg", "bgrun"):
        path = f"/Users/x/ops/site-private-djbclark/bin/{name}"
        assert lw.bg_args(f"{path} pytest t.py") == ["pytest", "t.py"]
        assert lw.bg_args(f"/bin/bash {path} pytest t.py") == ["pytest", "t.py"]
        assert lw.bg_args(f"cat {path}") is None
        assert lw.bg_args(f"python other/bin/{name}") is None
    assert lw.bg_args("/Users/x/ops/site-private/bin/bgrunner pytest t.py") is None
    assert lw.bg_rule(["just", "release-all"]) == "release"
    assert lw.bg_rule(["just", "build"]) == ""
    assert lw.bg_rule(["just", "release", "--local-tests"]) == ""
    assert lw.bg_rule(["uv", "run", "pytest", "tests/test_x.py"]) == "targeted test"
    assert lw.bg_rule(["pytest", "tests/", "-k", "foo"]) == "targeted test"
    assert lw.bg_rule(["pytest", "tests/"]) == ""


def test_nothing_maps_falls_back_to_the_session_and_says_guess(monkeypatch):
    lw, g, w = _work(monkeypatch, [(100, 1.0)], {"100": 1000}, {}, {"100": "/tmp/x"}, {})
    assert w["guess"] and [r["top"] for r in w["repos"]] == ["/r/ade"]
    text = lw.brief("inc1", g, w, 30.0, 8)
    assert "a guess" in text and "`/r/ade`" in text


def test_two_repos_are_listed_with_their_shares(monkeypatch):
    cwds = {"100": "/r/a", "101": "/r/b", "102": "/tmp/x"}
    lw, g, w = _work(monkeypatch, [(100, 1.2), (101, 0.6), (102, 0.2)], {}, {}, cwds,
                     {"/r/a": "/r/a", "/r/b": "/r/b"})
    assert [(r["top"], round(r["cores"], 1)) for r in w["repos"]] == [("/r/a", 1.2), ("/r/b", 0.6)]
    assert w["unmapped"] == 0.2
    text = lw.brief("inc2", g, w, 30.0, 8)
    assert "a. `/r/a`, 1.2 of those cores" in text and "b. `/r/b`, 0.6" in text
    assert "0.2 cores ran in no git repo" in text and "ci-only add /r/a" in text and "ci-only add /r/b" in text
    assert "ci-only add /r/ade" not in text


def test_brief_for_the_2056_incident(monkeypatch):
    rows = {"/r/sudo": ["ci", "scripts/github-test-ref", "2026-10-18"]}
    parent = {"35811": 35000, "35000": 34000, "34000": 1000}
    cmds = {"34000": f"/bin/bash {BG} just release"}
    cwds = {"35811": "/private/tmp/secretspec-x", "35000": "/private/tmp", "34000": "/r/sudo"}
    lw, g, w = _work(monkeypatch, [(35811, 0.61)], parent, cmds, cwds, {"/r/sudo": "/r/sudo", "/r/ade": "/r/ade"},
                     rows)
    text = lw.brief("20261018-2056-82c4844a", g, w, 39.9, 8)
    assert "`/r/sudo`" in text and "It ran under `bg` (through bg's release rule)." in text
    assert "Your session's cwd (`/r/ade`) is outside it." in text
    assert "ci-only add" not in text and "Nothing to register" in text
    assert "no Forgejo remote" in text and "outside `bg`" not in text


def test_proc_cwds_parses_one_lsof_call(monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "PROC_CWD", False)  # the macOS path (no /proc)
    calls = []
    out = "p100\nn/r/a\np101\nn/tmp/x y\n"
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: calls.append(argv) or
                        subprocess.CompletedProcess(argv, 1, out, ""))
    assert lw.proc_cwds([101, 100, 100, 0]) == {"100": "/r/a", "101": "/tmp/x y"}
    assert len(calls) == 1 and calls[0][-1] == "100,101"
    assert lw.proc_cwds([]) == {} and len(calls) == 1


def test_proc_cwds_reads_proc_on_linux_without_lsof(monkeypatch, tmp_path):
    """Review rule 5: Linux reads /proc/PID/cwd (no lsof needed); a pid that exited is left out."""
    lw = load_module()
    monkeypatch.setattr(lw, "PROC_CWD", True)
    links = {"/proc/100/cwd": "/r/a", "/proc/101/cwd": "/tmp/x y"}

    def readlink(path):
        if path in links:
            return links[path]
        raise FileNotFoundError(path)
    monkeypatch.setattr(lw.os, "readlink", readlink)
    monkeypatch.setattr(lw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no lsof on Linux")))
    assert lw.proc_cwds([101, 100, 102]) == {"100": "/r/a", "101": "/tmp/x y"}


def fake_paseo(tmp_path, rc=0, status="sent"):
    """A `paseo` stand-in that appends its argv (one JSON list per line) to sent.jsonl and prints `{"status": STATUS}`."""
    log = tmp_path / "sent.jsonl"
    cli = tmp_path / "paseo"
    cli.write_text(f"#!{sys.executable}\nimport json, sys\nopen({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                   f"print(json.dumps({{'agentId': sys.argv[-2], 'status': {status!r}}}))\nsys.exit({rc})\n")
    cli.chmod(0o755)
    return cli, log


def run_env(tmp_path, env, *args):
    base = {k: v for k, v in os.environ.items() if k not in ("PASEO_AGENT_ID", "PASEO_CLI", "CLAUDE_CODE_SESSION_ID")}
    base.update(LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"), **env)
    return subprocess.run([sys.executable, str(LW), *args], capture_output=True, text=True, env=base, timeout=30)


def test_watcher_set_from_paseo_env_show_clear(tmp_path):
    cli, log = fake_paseo(tmp_path)
    env = {"PASEO_AGENT_ID": "agent-a", "PASEO_CLI": str(cli)}
    assert run_env(tmp_path, {}, "watcher", "show").returncode == 1
    r = run_env(tmp_path, env, "watcher", "set", "--name", "lw", "--chain", "load-spike-monitor-t")
    assert r.returncode == 0 and "paseo agent-a" in r.stdout
    w = json.loads(run_env(tmp_path, {}, "watcher", "show", "--json").stdout)
    assert (w["channel"], w["target"], w["paseo_cli"], w["chain"]) == ("paseo", "agent-a", str(cli), "load-spike-monitor-t")
    assert "sid" not in w
    assert not log.exists()  # nobody to tell on a first set
    assert run_env(tmp_path, {}, "watcher", "clear", "someone-else").returncode == 1
    assert run_env(tmp_path, {}, "watcher", "clear", "agent-a").returncode == 0
    assert run_env(tmp_path, {}, "watcher", "show").returncode == 1


def test_watcher_set_replaces_and_tells_the_old_one(tmp_path):
    cli, log = fake_paseo(tmp_path)
    assert run_env(tmp_path, {"PASEO_AGENT_ID": "old", "PASEO_CLI": str(cli)}, "watcher", "set").returncode == 0
    r = run_env(tmp_path, {"PASEO_AGENT_ID": "new", "PASEO_CLI": str(cli)}, "watcher", "set", "--name", "B")
    assert r.returncode == 0 and "replaced paseo old" in r.stdout and "told the old watcher" in r.stdout
    sent = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert len(sent) == 1 and sent[0][:7] == ["send", "--no-wait", "--json", "--behavior", "steer", "--", "old"]
    assert "no longer the load watcher" in sent[0][-1] and "B took over" in sent[0][-1]
    assert json.loads((tmp_path / "state" / "watcher.json").read_text())["target"] == "new"


def fake_send(monkeypatch, lw, results, clock=None):
    """Fake subprocess.run and time.sleep for send_to: `results` is a list of (rc, stderr) (or (rc, stderr, stdout)),
    the last one repeats; `paseo send --json` writes its error to stderr. Returns (argvs, pauses, timeouts)."""
    argvs, pauses, timeouts = [], [], []

    def run(argv, **kw):
        argvs.append(argv)
        timeouts.append(kw.get("timeout"))
        res = results[min(len(argvs), len(results)) - 1]
        out = res[2] if len(res) > 2 else (SENT if res[0] == 0 else "")
        return subprocess.CompletedProcess(argv, res[0], out, res[1])

    monkeypatch.setattr(lw.subprocess, "run", run)
    monkeypatch.setattr(lw.time, "sleep", lambda s: pauses.append(s))
    if clock is not None:
        monkeypatch.setattr(lw.time, "monotonic", clock)
    return argvs, pauses, timeouts


def err(code, message="x"):
    return json.dumps({"error": {"code": code, "message": message}})


PASEO_W = {"channel": "paseo", "target": "agent-a", "paseo_cli": "paseo-fake"}
SENT = json.dumps({"agentId": "agent-a", "status": "sent", "message": "Message sent, not waiting for completion"})
QUEUED = json.dumps({"agentId": "agent-a", "status": "queued", "message": "Message queued for delivery after two quiet seconds"})
UNREACHABLE = err("DAEMON_UNREACHABLE", "Cannot connect to daemon")


def test_send_to_first_attempt_succeeds_without_retry(monkeypatch):
    lw = load_module()
    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "hi") is True
    assert len(argvs) == 1 and not pauses and timeouts == [60]
    assert argvs[0] == ["paseo-fake", "send", "--no-wait", "--json", "--behavior", "steer", "--", "agent-a", "hi"]


def test_send_to_text_starting_with_a_dash_stays_after_the_separator(monkeypatch):
    lw = load_module()
    argvs, _, _ = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "--prompt-file=/x") is True
    argv = argvs[0]
    assert argv.index("--") < argv.index("agent-a") < argv.index("--prompt-file=/x") == len(argv) - 1


def test_send_to_retries_each_real_restart_code_then_succeeds(monkeypatch):
    lw = load_module()
    assert set(lw.SEND_TRANSIENT) == {"DAEMON_UNREACHABLE", "DAEMON_CONNECTION_LOST", "DAEMON_NOT_READY",
                                      "DAEMON_NOT_RUNNING"}
    for code in ("DAEMON_UNREACHABLE", "DAEMON_CONNECTION_LOST", "DAEMON_NOT_READY", "DAEMON_NOT_RUNNING"):
        argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, err(code)), (0, "")])
        assert lw.send_to(PASEO_W, "hi") is True, code
        assert len(argvs) == 2 and pauses == [lw.SEND_RETRY_PAUSE_S], code


def test_send_to_reads_the_code_from_stdout_too(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, "", err("DAEMON_NOT_RUNNING")), (0, "")])
    assert lw.send_to(PASEO_W, "hi") is True and len(argvs) == 2 and len(pauses) == 1


def test_send_to_gives_up_after_two_retries(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)])
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 + lw.SEND_RETRIES == 3 and len(pauses) == 2
    assert lw.SEND_RETRIES * lw.SEND_RETRY_PAUSE_S < lw.SEND_RETRY_BUDGET_S <= 30


def test_send_to_does_not_retry_other_failures(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, err("SEND_FAILED", "Agent not found"))])
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 and not pauses


def test_send_transient_is_an_exact_code_match():
    lw = load_module()
    run = lambda err_, out="": subprocess.CompletedProcess([], 1, out, err_)  # noqa: E731
    # the four real codes, on stderr or stdout
    for code in lw.SEND_TRANSIENT:
        assert lw.send_transient(run(err(code))) and lw.send_transient(run("", err(code)))
    # another code that merely contains the text of a real one
    for code in ("AGENT_NOT_READY", "PROVIDER_NOT_READY", "DAEMON_NOT_READY_YET", "XDAEMON_NOT_RUNNING", "CONNECTION_LOST",
                 "NOT_READY", "SEND_FAILED"):
        assert not lw.send_transient(run(err(code))), code
    # the text inside prose, in the message, in details or in an unrelated field
    assert not lw.send_transient(run(err("SEND_FAILED", "Failed to send: DAEMON_NOT_READY DAEMON_UNREACHABLE")))
    assert not lw.send_transient(run(json.dumps({"error": {"code": "SEND_FAILED", "details": "DAEMON_NOT_RUNNING"}})))
    assert not lw.send_transient(run("Error: DAEMON_NOT_RUNNING: Cannot connect to daemon"))
    # non-JSON, empty, None and wrongly shaped output
    for bad in ("", "not json DAEMON_UNREACHABLE", "[1, 2]", '"DAEMON_UNREACHABLE"', "null", "42",
                '{"error": "DAEMON_UNREACHABLE"}', '{"error": {"code": ["DAEMON_UNREACHABLE"]}}', '{"error": null}'):
        assert not lw.send_transient(run(bad)), bad
        assert not lw.send_transient(run("", bad)), bad
    assert not lw.send_transient(subprocess.CompletedProcess([], 1, None, None))


def test_send_to_a_code_named_only_in_prose_is_not_retried(monkeypatch):
    lw = load_module()
    for e in (err("AGENT_NOT_READY"), "DAEMON_NOT_READY: still starting", err("SEND_FAILED", "DAEMON_UNREACHABLE")):
        argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, e)])
        assert lw.send_to(PASEO_W, "hi") is False
        assert len(argvs) == 1 and not pauses, e
    assert lw._paseo_down is False


def test_send_to_timeouts_stay_inside_the_budget(monkeypatch):
    lw = load_module()
    now = [0.0]
    pauses_seen = []

    def clock():
        return now[0]

    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=clock)
    monkeypatch.setattr(lw.time, "sleep", lambda s: (pauses_seen.append(s), now.__setitem__(0, now[0] + s + 7.0)))
    assert lw.send_to(PASEO_W, "hi") is False
    assert timeouts[0] == 60
    assert len(timeouts) >= 2
    for t in timeouts[1:]:
        assert 1.0 <= t <= lw.SEND_RETRY_BUDGET_S - lw.SEND_RETRY_PAUSE_S, timeouts
    # each pause here advances the clock 12 s: the retries start at 12 s and 24 s, so their timeouts are 18 and 6
    assert timeouts == [60, lw.SEND_RETRY_BUDGET_S - 12.0, lw.SEND_RETRY_BUDGET_S - 24.0]


def test_send_to_retry_timeout_never_drops_below_one_second(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0, 24.5], itertools.repeat(29.5))  # start, check before the pause, then 0.5 s of budget left
    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "hi") is False
    assert timeouts == [60, 1.0] and len(pauses) == 1


def test_send_to_retry_stays_inside_the_budget(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0], itertools.repeat(28.0))  # the first attempt took 28 s: no pause fits in 30 s
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 and not pauses


def test_send_to_after_giving_up_later_sends_make_one_attempt(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)])
    assert lw._paseo_down is False
    assert lw.send_to(PASEO_W, "a") is False
    assert len(argvs) == 3 and len(pauses) == 2 and lw._paseo_down is True
    for n in (4, 5):
        assert lw.send_to(PASEO_W, "b") is False
        assert len(argvs) == n and len(pauses) == 2   # one attempt each, no pause
    # a success proves the daemon is back: retries return
    argvs2, pauses2, _ = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "c") is True and lw._paseo_down is False
    argvs3, pauses3, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE), (0, "")])
    assert lw.send_to(PASEO_W, "d") is True and len(argvs3) == 2 and len(pauses3) == 1


def test_send_to_running_out_of_budget_on_a_restart_code_also_gives_up_for_the_process(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0], itertools.repeat(28.0))
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "a") is False and lw._paseo_down is True
    assert len(argvs) == 1 and not pauses


def test_send_to_a_non_restart_failure_does_not_set_the_process_flag(monkeypatch):
    lw = load_module()
    fake_send(monkeypatch, lw, [(1, err("SEND_FAILED", "Agent not found"))])
    assert lw.send_to(PASEO_W, "a") is False and lw._paseo_down is False


def test_send_reads_status_never_the_exit_code(monkeypatch):
    """`paseo send` exits 0 for a queued line too (research 2026-11-06 item 1): only `.status` decides."""
    lw = load_module()
    fake_send(monkeypatch, lw, [(0, "", QUEUED)])
    assert lw.paseo_send(PASEO_W, "hi") == "queued"
    assert lw.send_to(PASEO_W, "hi") is False            # queued is not delivered
    for out in ("", "not json", "[]", '{"status": ""}', '{"status": 3}'):
        fake_send(monkeypatch, lw, [(0, "", out)])
        assert lw.paseo_send(PASEO_W, "hi") == "unknown" and lw.send_to(PASEO_W, "hi") is False, out
    fake_send(monkeypatch, lw, [(0, "", json.dumps({"type": "single", "data": {"status": "sent"}}))])
    assert lw.paseo_send(PASEO_W, "hi") == "sent"


def test_send_without_a_paseo_binary_is_failed_not_an_exception(monkeypatch):
    lw = load_module()
    assert lw.paseo_send({"channel": "paseo", "target": "a", "paseo_cli": "/nonexistent/paseo"}, "hi") == "failed"


def test_send_to_timeout_and_oserror_do_not_escape(monkeypatch):
    lw = load_module()
    pauses = []
    monkeypatch.setattr(lw.time, "sleep", lambda s: pauses.append(s))
    for exc in (subprocess.TimeoutExpired("paseo", 60), OSError("gone")):
        def run(argv, exc=exc, **kw):
            raise exc
        monkeypatch.setattr(lw.subprocess, "run", run)
        assert lw.send_to(PASEO_W, "hi") is False
    assert not pauses


def test_notify_reads_queued_as_not_delivered_and_offers_the_fixer(monkeypatch):
    lw = load_module()
    argvs = []

    def run(argv, **kw):
        argvs.append(argv)
        return subprocess.CompletedProcess(argv, 0, QUEUED, "")
    monkeypatch.setattr(lw.subprocess, "run", run)
    monkeypatch.setattr(lw, "HERMES_PING", Path("/nonexistent/hermes-ping"))
    g = {"session": {"id": "abcd1234-0000", "agent": "claude/opus", "name": "n", "cwd": "/r/a"},
         "procs": [{"cmd": "cargo build", "cores": 3.0}], "cores": 3.0}
    status, ping = lw.notify("inc1", g, "/tmp/top", "/tmp/brief.md", 12.0, 8, False)
    assert status == "queued" and "queued it, not delivered" in ping
    assert "paseo run --provider cursor/default" in ping and "ade.kind=code" in ping
    assert "--prompt-file" not in ping
    assert "Read and act on the load-watch brief at" in ping
    assert "acp-dispatch" not in ping and "acp-run" not in ping
    send = argvs[0]
    assert send[1:5] == ["send", "--no-wait", "--json", "--behavior"] and send[-2] == "abcd1234-0000"
    assert "relay.py" not in " ".join(send)


def test_watcher_set_needs_a_session(tmp_path):
    assert run_env(tmp_path, {}, "watcher", "set").returncode == 2


def test_tell_watcher_skips_the_told_offender_and_stamps(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(lw, "paseo_send", lambda w, text: sent.append((w["target"], text)) or "sent")
    assert lw.tell_watcher("x.", False) is None  # no watcher registered
    lw.save_watcher({"channel": "paseo", "target": "agent-a"})
    assert lw.tell_watcher("x.", False, skip={"agent-a"}) is None and not sent
    assert lw.tell_watcher("load 30.", False) is True
    assert sent[0][0] == "agent-a" and "load 30." in sent[0][1] and lw.WATCHER_HOWTO in sent[0][1]
    assert "loadwatch" not in sent[0][1] and "load-watch ack ID" in sent[0][1]  # the instruction itself (R2-11)
    assert "last_ok" in json.loads((tmp_path / "watcher.json").read_text())
    for st in ("failed", "queued"):
        monkeypatch.setattr(lw, "paseo_send", lambda w, text, st=st: st)
        assert lw.tell_watcher("y.", False) is False
        assert "last_fail" in json.loads((tmp_path / "watcher.json").read_text())
    assert "queued, not delivered" in (tmp_path / "sample.log").read_text()


def test_watcher_record_must_be_well_formed(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    for bad in ("[]", "{}", '{"channel": "smoke", "target": "x"}', "not json"):
        (tmp_path / "watcher.json").write_text(bad)
        assert lw.watcher() is None


def test_a_relay_channel_watcher_reaches_nobody_and_show_says_so(tmp_path, monkeypatch):
    """The relay.py channel is gone (slim-down E5, 2026-11-06): an older record is no watcher, and `show` names the fix."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "watcher.json").write_text(json.dumps({"channel": "relay", "target": "sess-1"}))
    r = run_env(tmp_path, {}, "watcher", "show")
    assert r.returncode == 1 and "relay channel" in r.stderr and "--paseo ID" in r.stderr
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", state)
    assert lw.watcher() is None
    assert run_env(tmp_path, {}, "watcher", "set", "--relay", "x").returncode == 2  # the flag is gone


def test_watcher_test_names_a_queued_line(tmp_path):
    for status, rc, word in (("sent", 0, "sent to paseo agent-a"), ("queued", 0, "queued, not delivered, for paseo agent-a"),
                             ("error", 1, "could not reach (error) paseo agent-a")):
        cli, _log = fake_paseo(tmp_path, status=status)
        env = {"PASEO_AGENT_ID": "agent-a", "PASEO_CLI": str(cli)}
        assert run_env(tmp_path, env, "watcher", "set").returncode == 0
        r = run_env(tmp_path, {}, "watcher", "test")
        assert (r.returncode, r.stdout.strip()) == (rc, word), status


def test_ci_macos_retry_route(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "main_worktree", lambda top: "/repo")
    monkeypatch.setattr(lw, "pasture_source", lambda top: "")
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (16, 0, 0))
    route = lambda platform="macos", job="build": lw.ci_job_route("/wt", platform, job)
    record = lambda attempt, result: lw.record_ci_attempt("/wt", "macos", "build", attempt, result)
    assert route() == ("ci", "-", 0)
    record("run1", "cancelled")
    record("run1", "cancelled")  # same run reported twice must not bypass the gate
    assert route() == ("local", "16", 1)
    assert route("linux") == ("ci", "-", 0)
    assert route(job="other") == ("ci", "-", 0)
    assert lw.ci_job_route("/wt", "linux", "build", True) == ("ci", "-", 0)
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (16.01, 0, 0))
    assert route() == ("wait", "16", 1)
    record("run2", "failure")
    assert route() == ("local", "bypass", 2)
    record("run3", "success")
    record("run1", "cancelled")  # old event keeps its position before success
    assert route() == ("ci", "-", 0)
    assert lw.ci_job_route("/wt", "macos", "build", True) == ("wait", "16", 0)
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (15.9, 0, 0))
    record("slow-run", "slow")
    assert route() == ("local", "16", 0)
    assert lw.ci_job_route("/other-wt", "macos", "build") == route()


def test_ci_attempt_cli(tmp_path):
    args = ("--job", "xcode", "--platform", "macos")
    assert run(tmp_path, "ci", "record", str(tmp_path), *args).returncode == 2
    for attempt in ("1", "2"):
        r = run(tmp_path, "ci", "record", str(tmp_path), *args,
                "--attempt", attempt, "--result", "failure")
        assert r.returncode == 0, r.stderr
    r = run(tmp_path, "ci", "route", str(tmp_path), *args)
    assert (r.returncode, r.stdout.strip()) == (0, "local\tbypass\t2")


def test_damaged_row_refuses_before_any_dialog(tmp_path):
    """rv-744 Low (c): a registry row with a control character must refuse before sudo-ask is shown, not after djbclark approved."""
    repo = _repo(tmp_path)
    calls = stub_sudo_ask(tmp_path, 0)
    (tmp_path / "ci-only.tsv").write_text("/x/y\tlocal\tbad\x01reason\t2026-10-18\n")
    r = run(tmp_path, "ci", "decide", str(repo), "local", "needs Xcode")
    assert r.returncode != 0 and "control character" in r.stderr and "nothing was written" in r.stderr
    assert not calls.exists() or calls.read_text() == ""  # no dialog was invoked


def test_registry_lock_wait_is_bounded(tmp_path):
    """rv-744 Low (a): a held lock yields a clear refusal after the timeout, not an endless wait."""
    import fcntl
    repo = _repo(tmp_path)
    (tmp_path / "ci-only.tsv").write_text("")
    with open(str(tmp_path / "ci-only.tsv") + ".lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        t0 = time.monotonic()
        r = run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run", LW_REGISTRY_LOCK_TIMEOUT_S="0.5")
        assert time.monotonic() - t0 < 10
    assert r.returncode != 0 and "registry lock" in r.stderr and "nothing was changed" in r.stderr
    assert rows(tmp_path) == []


def test_registry_lock_waits_for_a_release_and_ignores_a_bad_timeout(tmp_path):
    """The bound must still WAIT (a lock released after 1 s is acquired), and a typo'd or nan timeout falls back to the default."""
    import fcntl
    import threading
    repo = _repo(tmp_path)
    (tmp_path / "ci-only.tsv").write_text("")
    held = open(str(tmp_path / "ci-only.tsv") + ".lock", "a")
    fcntl.flock(held, fcntl.LOCK_EX)
    threading.Timer(1.0, lambda: (fcntl.flock(held, fcntl.LOCK_UN), held.close())).start()
    r = run(tmp_path, "ci", "decide", str(repo), "ci", "scripts/ci-run", LW_REGISTRY_LOCK_TIMEOUT_S="nan")
    assert r.returncode == 0, r.stderr
    assert [x[1] for x in rows(tmp_path)] == ["ci"]
    assert run(tmp_path, "ci", "list", LW_REGISTRY_LOCK_TIMEOUT_S="abc").returncode == 0


SKILL = Path(__file__).resolve().parent.parent / "skills" / "watch" / "SKILL.md"


def _step4():
    text = SKILL.read_text()
    return text[text.index("### Step 4"):text.index("## 3. Standing Watcher Mode")]


def test_watch_step4_sends_only_sourced_idle_plain_and_rate_limited():
    """PR 888 round 2: a sourceless `paseo send` interrupts a running turn, so every send Step 4 adds needs a Paseo session,
    an idle lead, no --behavior flag, a once-per-hour cap and a label source that exists (inspect has no labels)."""
    s4 = _step4()
    assert "$PASEO_AGENT_ID" in s4 and "sourceless" in s4 and "sends nothing" in s4
    assert "never a `--behavior` flag" in s4 and "--behavior steer" not in s4
    assert "paseo send --no-wait --json" in s4
    assert 'Status == "idle"' in s4
    assert "one such message per lead per hour" in s4 and "archive-asks.jsonl" in s4
    assert "SuccessionError" in s4 and "Archived: true" in s4 and "No current holder" in s4
    assert "carry no role or label" in s4 and 'labels["ade.lead"]' in s4 and "--label ade.lead=" in s4
    # every `paseo send` in Step 4 is the plain no-wait form: no steer, no other behavior
    assert s4.count("--behavior") == 1


def test_watch_step4_item1_sends_only_to_an_idle_blamed_agent():
    """PR 888 round 3 MED 1: a sourced send is not safe to a running agent (steer falls back to replacing the turn, and every
    sourced message clears pending permissions), so item 1 carries the same idle/no-card gate as item 3."""
    s4 = _step4()
    item1 = s4[s4.index("1. **Steer future heavy runs"):s4.index("2. **Guard a misbehaving")]
    assert 'Status == "idle"' in item1 and "Archived: false" in item1 and "PendingPermissions == []" in item1
    assert "A blamed agent that is running is not messaged" in item1
    rules = s4[s4.index("**Send rules"):s4.index("1. **Steer future")]
    assert "steer falls back to interrupt" in rules and "every sourced agent-message clears pending permissions" in rules
    assert "defaults to interrupt and clears pending permissions" not in rules
    assert "send only to an idle agent with no card" in rules


def test_watch_step4_describes_prune_orphan_stop_and_unlocked_rate_record():
    """PR 888 round 3 LOW 1 and LOW 2."""
    s4 = _step4()
    assert "stops orphan provider processes of already-archived agents" in s4 and "--max-kills" in s4
    assert "not locked" in s4 and "only one session at a time sends these messages" in s4


def test_watcher_howto_carries_the_send_rules():
    lw = load_module()
    h = lw.WATCHER_HOWTO
    assert "$PASEO_AGENT_ID" in h and "never `--behavior`" in h and "sourceless send interrupts" in h
    assert "`Status` idle" in h and "at most one message per lead per hour" in h
    assert "never run `paseo agent archive` yourself" in h
    # round 3 MED 1: a running blamed agent is listed, not messaged; any send to a running agent can replace its turn
    assert "any send to a running agent can replace its turn" in h and "clears pending permissions" in h
    assert "a running blamed agent is listed for djbclark, not messaged" in h
    assert "reads `Status` idle, `Archived: false` and no pending permissions" in h


def test_watch_step4_pins_the_round1_archive_safety_rules():
    """PR 888 round 4 MED 1: the round-1 HIGH fix (the watcher never archives leads or operator agents, never archives by
    itself, and only a memory refusal starts item 3) lived in prose no test read, so seven of eight mutants survived."""
    s4 = _step4()
    # the one trigger, and what is not a trigger
    assert "refuses on a memory reason (`free_mem`, `swapins` or `compressor`)" in s4
    assert "never starts item 3" in s4 and "reports anything" not in s4
    # the watcher has no archive authority of its own
    assert "The watcher never runs `paseo agent archive` itself." in s4
    assert "may run `paseo agent archive`" not in s4
    assert "`~/src/djbclark-ade/bin/ade-tidy prune`" in s4
    # an agent with no ade.lead label (every LEAD, operator agents) is only listed
    assert "**No `ade.lead` label**" in s4
    assert "list it for djbclark in one line; never archive it and never message it about archiving" in s4
    # `closed` is not proof of finished work
    assert "`closed` alone proves nothing finished" in s4
    assert "is finished and may be archived" not in s4
    # the hard boundaries
    assert "never archive a `running` agent, a LEAD, an agent with a pending permission or question" in s4
    assert "archive any agent" not in s4
    assert "when in doubt, do not archive" in s4


def test_watch_step4_item3_lead_gate_and_consistent_scope():
    """PR 888 round 4 MED 1 (item 3 lead gate) and LOW 2 (item 1 reason; closed workers not named)."""
    s4 = _step4()
    gate = s4[s4.index("**Has `ade.lead=<L>`"):s4.index("**Rate limit:**")]
    assert "the owning lead decides, never the watcher" in gate
    assert "`Archived: false`" in gate and 'Status == "idle"' in gate and "PendingPermissions == []" in gate
    assert "`paseo permit ls`" in gate and "never message an agent waiting on a card or an archived one" in gate
    # LOW 2: item 3 targets live idle processes only, and the lead message names idle workers only
    assert "targets live idle provider processes only" in s4
    assert "its idle workers (closed ones hold little RAM and are not named)" in gate
    assert "idle or closed workers" not in s4
    # LOW 2: the item 1 reason no longer claims the incident brief always reached the agent
    item1 = s4[s4.index("1. **Steer future heavy runs"):s4.index("2. **Guard a misbehaving")]
    assert "has already reached it" not in item1
    assert "that send can queue or fail" in item1


def test_watch_step4_and_howto_pin_each_send_gate_with_its_condition():
    """PR 888 round 5 LOW 1: the send gates were pinned by the presence of words, so inverting one (`idle` to `running`,
    `only when` to `even when`) left the suite green. Pin each gate phrase whole, condition included."""
    s4 = _step4()
    item1 = s4[s4.index("1. **Steer future heavy runs"):s4.index("2. **Guard a misbehaving")]
    assert "only when a fresh `paseo agent inspect ID --json` reads `Status == \"idle\"`, `Archived: false` and `PendingPermissions == []`" in item1
    assert "Never ask it to stop its current step." in item1
    rules = s4[s4.index("**Send rules"):s4.index("1. **Steer future")]
    assert "a fresh `paseo agent inspect ID --json` must read `Status == \"idle\"`, `Archived: false` and `PendingPermissions == []` right before the send" in rules
    assert "otherwise list the agent for djbclark and retry at the next incident" in rules
    assert "and none while an earlier one is unacked and under 6 hours old" in s4
    assert "(observe first; `--apply` only from the watcher's own top-level session, never from a sub-agent)" in s4
    assert "An agent whose report was never read is paid work and is never a target." in s4
    assert "only one session at a time sends these messages (the standing watcher when one runs; any other `/watch load` session lists the lead for djbclark and sends nothing)" in s4
    h = load_module().WATCHER_HOWTO
    assert "so send only when a fresh `paseo agent inspect ID --json` reads `Status` idle, `Archived: false` and no pending permissions" in h
    assert "(succession ledger; `paseo agent inspect ID --json` reads `Archived: false`, `Status` idle, no pending card;" in h


def test_watcher_howto_pins_the_round1_rules_and_has_no_unconditional_send():
    """PR 888 round 4 MED 1 (HOWTO side) and LOW 1: every send in the prompt is idle-gated, including the older 'send it one line'."""
    h = load_module().WATCHER_HOWTO
    assert "Only when `admit --json` refuses on memory (`free_mem`, `swapins`, `compressor`)" in h
    assert "never archive, or ask about archiving, an agent with no `ade.lead` label (list it)" in h
    assert "never touch an agent with no" not in h  # #888 r5 LOW 2: wider than Step 4 (item 1 may message an idle LEAD)
    assert "never run `paseo agent archive` yourself (only `bin/ade-tidy prune`)" in h
    assert "following skills/watch/SKILL.md Step 4 exactly" in h
    # LOW 1: the "send it one line" clause carries the idle gate right in front of it
    assert "if it was not told, send it one line" not in h
    pos = h.index("send it one line")
    assert "reads `Status` idle, `Archived: false` and no pending permissions" in h[max(0, pos - 160):pos]
    assert "a running one is listed for djbclark, not messaged" in h
