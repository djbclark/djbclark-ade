"""W17: Python acquisition (uv only, explicit, ledger-serialized, never root) and the sh cold-start bridge."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai


def done(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class Fake:
    """Scripted runner/which: records argv, answers probes and uv."""

    def __init__(self, state, *, path_python=None, uv="/fake/uv", managed=None, install_rc=0, install_raises=None):
        self.state, self.calls = state, []
        self.path_python, self.uv, self.managed = path_python, uv, managed
        self.install_rc, self.install_raises = install_rc, install_raises
        self.installed = False
        self.sentinel_during_install = None
        self.ledger_during_install = None

    def which(self, name):
        return {"python3": self.path_python, "uv": self.uv}.get(name)

    def run(self, argv):
        self.calls.append(list(argv))
        if argv[1:3] == ["-I", "-c"]:
            ok = argv[0] == self.managed and self.installed or argv[0] == self.path_python
            return done(0, "3.13.1\n") if ok else done(1, "3.9.6\n")
        if argv[1:3] == ["python", "install"]:
            self.sentinel_during_install = (self.state / ai.PYTHON_PENDING).is_file()
            self.ledger_during_install = ai.load_ledger(self.state)["entries"].get("python")
            if self.install_raises:
                raise self.install_raises
            self.installed = self.install_rc == 0
            return done(self.install_rc, "", "boom" if self.install_rc else "")
        if argv[1:3] == ["python", "find"]:
            return done(0, self.managed + "\n") if self.installed and self.managed else done(1)
        raise AssertionError(f"unexpected argv {argv}")

    def acquire(self, **kw):
        return ai.acquire_python(state_dir=self.state, runner=self.run, which=self.which, euid=1000, **kw)


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def test_dry_run_plans_without_subprocess_or_writes(state, monkeypatch):
    monkeypatch.setattr(ai.subprocess, "run", Mock(side_effect=AssertionError("dry run ran a command")))
    fake = Fake(state)
    report, rc = fake.acquire()
    assert rc == 0 and report["mode"] == "dry-run" and report["python_status"] == "missing"
    assert report["install_argv"] == ["/fake/uv", "python", "install", "3.13"]
    assert fake.calls == [] and not state.exists()


def test_dry_run_without_uv_or_python_names_the_manual_step(state):
    report, rc = Fake(state, uv=None).acquire()
    assert rc == 1 and report["status"] == "uv-missing" and "install uv yourself" in report["reason"]
    assert not state.exists()


def test_refuses_as_root_before_anything_runs(state):
    fake = Fake(state)
    report, rc = ai.acquire_python(state_dir=state, yes=True, runner=fake.run, which=fake.which, euid=0)
    assert rc == 1 and report["status"] == "refused-root"
    assert fake.calls == [] and not state.exists()


def test_yes_records_an_existing_supported_python_without_downloading(state):
    fake = Fake(state, path_python="/usr/local/bin/python3")
    report, rc = fake.acquire(yes=True)
    assert rc == 0 and report["status"] == "ready" and report["python"] == "/usr/local/bin/python3"
    assert not any(c[1:3] == ["python", "install"] for c in fake.calls)
    entry = ai.load_ledger(state)["entries"]["python"]
    assert entry["status"] == "installed" and entry["version"] == "3.13.1"
    assert not (state / ai.PYTHON_PENDING).exists()


def test_cold_acquisition_is_pending_before_download_then_verified(state):
    ai.save_ledger(state, {"entries": {"just": {"status": "installed"}}})
    fake = Fake(state, managed="/uv/py/bin/python3.13")
    report, rc = fake.acquire(yes=True)
    assert rc == 0 and report["python"] == "/uv/py/bin/python3.13"
    assert fake.sentinel_during_install is True
    assert fake.ledger_during_install["status"] == "pending"
    entries = ai.load_ledger(state)["entries"]
    assert entries["python"]["status"] == "installed" and entries["python"]["path"] == "/uv/py/bin/python3.13"
    assert entries["just"] == {"status": "installed"}, "other components' evidence is preserved"
    assert not (state / ai.PYTHON_PENDING).exists()
    # only uv and the interpreter probe: never pip, sudo or a package manager
    assert {c[0] for c in fake.calls} <= {"/fake/uv", "/uv/py/bin/python3.13", "/usr/bin/python3"}
    assert not any(part in ("pip", "sudo", "brew") for c in fake.calls for part in c)


def test_uv_missing_starts_nothing(state):
    fake = Fake(state, uv=None)
    report, rc = fake.acquire(yes=True)
    assert rc == 1 and report["status"] == "uv-missing" and fake.calls == []
    assert not (state / ai.PYTHON_PENDING).exists()


def test_uv_failure_is_recorded_failed_and_sentinel_cleared(state):
    fake = Fake(state, managed="/uv/py", install_rc=2)
    report, rc = fake.acquire(yes=True)
    assert rc == 1 and report["status"] == "acquisition-failed"
    entry = ai.load_ledger(state)["entries"]["python"]
    assert entry["status"] == "failed" and entry["returncode"] == 2 and entry["detail"] == "boom"
    assert not (state / ai.PYTHON_PENDING).exists()


def test_unknown_outcome_blocks_until_explicit_recovery_which_never_downloads(state):
    fake = Fake(state, managed="/uv/py", install_raises=subprocess.TimeoutExpired(["uv"], 900))
    report, rc = fake.acquire(yes=True)
    assert rc == 1 and report["status"] == "unknown-pending"
    assert ai.load_ledger(state)["entries"]["python"]["status"] == "pending"
    assert (state / ai.PYTHON_PENDING).is_file()
    # the owner (a crashed process) is dead; dry-run and plain --yes both refuse and name recovery
    (state / ai.PYTHON_PENDING).write_text("pid=999999999\nstarted=x\nargv=[]\n")
    for yes in (False, True):
        refused = Fake(state, managed="/uv/py")
        r, code = refused.acquire(yes=yes)
        assert code == 1 and r["status"] == "pending-recovery" and "--recover" in r["reason"]
        assert refused.calls == []
    # explicit recovery: dry-run describes, --yes verifies (uv already finished) and clears
    describe, code = Fake(state, managed="/uv/py").acquire(recover=True)
    assert code == 0 and describe["pending"]["pid"] == "999999999"
    recovered = Fake(state, managed="/uv/py")
    recovered.installed = True
    r, code = recovered.acquire(yes=True, recover=True)
    assert code == 0 and r["status"] == "ready"
    assert not any(c[1:3] == ["python", "install"] for c in recovered.calls)
    entry = ai.load_ledger(state)["entries"]["python"]
    assert entry["status"] == "installed" and entry["recovered"] is True
    assert not (state / ai.PYTHON_PENDING).exists()


def test_recovery_with_nothing_usable_records_failure_and_clears(state):
    state.mkdir()
    (state / ai.PYTHON_PENDING).write_text("pid=999999999\n")
    fake = Fake(state, managed="/uv/py")  # never installed: probes fail
    r, rc = fake.acquire(yes=True, recover=True)
    assert rc == 1 and r["status"] == "unverified"
    assert ai.load_ledger(state)["entries"]["python"]["status"] == "failed"
    assert not (state / ai.PYTHON_PENDING).exists()


def test_recover_without_pending_is_refused(state):
    r, rc = Fake(state).acquire(yes=True, recover=True)
    assert rc == 1 and r["status"] == "nothing-to-recover"


def test_live_other_owner_blocks(state):
    state.mkdir()
    (state / ai.PYTHON_PENDING).write_text(f"pid={os.getppid()}\n")
    fake = Fake(state, managed="/uv/py")
    r, rc = fake.acquire(yes=True)
    assert rc == 1 and r["status"] == "owner-active" and fake.calls == []


def test_bridge_handoff_adopts_its_own_pending_sentinel(state):
    state.mkdir()
    (state / ai.PYTHON_PENDING).write_text(f"pid={os.getpid()}\nstarted=x\nargv=[]\n")
    fake = Fake(state, path_python="/uv/py/bin/python3.13")
    r, rc = fake.acquire(yes=True)
    assert rc == 0 and r["status"] == "ready"
    assert not (state / ai.PYTHON_PENDING).exists()


def test_acquisition_waits_for_the_ledger_lock(state):
    fake = Fake(state, path_python="/usr/local/bin/python3")
    out = {}
    entered, release = threading.Event(), threading.Event()

    def holder():
        with ai.install_ledger_lock(state):
            entered.set()
            release.wait(10)

    def worker():
        out["r"] = fake.acquire(yes=True)

    h = threading.Thread(target=holder); h.start(); assert entered.wait(5)
    w = threading.Thread(target=worker); w.start()
    time.sleep(0.4)
    assert "r" not in out and fake.calls == [], "must wait for the shared ledger lock"
    release.set(); h.join(5); w.join(5)
    assert out["r"][1] == 0


# ---- sh cold-start bridge, with fake uv/python on a PATH holding nothing else ----

TOOLS = ["sh", "uname", "date", "sed", "dirname", "mkdir", "rm", "cat", "test", "[", "kill", "touch", "cut"]


@pytest.fixture
def cold(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    log = tmp_path / "log"
    state = tmp_path / "state"
    (bindir / "id").write_text('#!/bin/sh\necho "${FAKE_UID:-1000}"\n')
    (bindir / "id").chmod(0o755)

    def python(name, supported=True):
        p = bindir / name
        p.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = -I ] && [ "$2" = -c ]; then exit {0 if supported else 1}; fi\n'
            f'echo "HANDOFF pid=$$ args=$*" >> "{log}"\n'
            f'if [ -f "{state}/python-acquire.pending" ]; then echo "SENTINEL $(cat "{state}/python-acquire.pending" | sed -n 1p)" >> "{log}"; fi\n'
            "exit 0\n"
        )
        p.chmod(0o755)
        return p

    def uv(install_rc=0, managed=None):
        u = bindir / "uv"
        flag = tmp_path / "uv-installed"
        u.write_text(
            "#!/bin/sh\n"
            f'echo "uv $*" >> "{log}"\n'
            'if [ "$1 $2" = "python install" ]; then '
            f'[ {install_rc} = 0 ] && touch "{flag}"; exit {install_rc}; fi\n'
            f'if [ "$1 $2" = "python find" ]; then [ -f "{flag}" ] && echo "{managed}" && exit 0; exit 1; fi\n'
            "exit 9\n"
        )
        u.chmod(0o755)

    def run(*args, env=None):
        full = {"PATH": str(bindir), "HOME": str(tmp_path / "home"), "ADE_INSTALL_STATE_DIR": str(state), **(env or {})}
        return subprocess.run(["/bin/sh", str(REPO / "bin/ade-bootstrap"), *args], env=full,
                              capture_output=True, text=True, timeout=30)

    class C: pass
    c = C(); c.bindir, c.log, c.state, c.python, c.uv, c.run = bindir, log, state, python, uv, run
    c.text = lambda: log.read_text() if log.exists() else ""
    return c


def test_bridge_preview_runs_nothing(cold):
    cold.uv(); cold.python("python3", supported=False)
    r = cold.run()
    assert r.returncode == 0 and "preview" in r.stdout and "uv python install 3.13" in r.stdout
    assert cold.text() == "" and not cold.state.exists()


def test_bridge_refuses_root(cold):
    cold.uv()
    r = cold.run("--yes", env={"FAKE_UID": "0"})
    assert r.returncode == 77 and cold.text() == "" and not cold.state.exists()


def test_bridge_hands_off_without_downloading_when_python_exists(cold):
    cold.uv(); cold.python("python3")
    r = cold.run("--yes")
    assert r.returncode == 0, r.stderr
    assert "python install" not in cold.text()
    assert f"args=-I {REPO}/bin/ade-install python --yes --state-dir {cold.state}" in cold.text()


def test_bridge_cold_path_installs_with_uv_then_hands_off_with_adoptable_sentinel(cold, tmp_path):
    managed = cold.python("managed-python")
    cold.uv(managed=str(managed))
    r = cold.run("--yes")
    assert r.returncode == 0, r.stderr
    text = cold.text()
    assert "uv python install 3.13" in text and "HANDOFF" in text
    pid = text.split("HANDOFF pid=")[1].split()[0]
    assert f"SENTINEL pid={pid}" in text, "the exec'd interpreter owns the sentinel (the Python side adopts it)"
    assert "args=-I" in text and "python --yes --state-dir" in text


def test_bridge_without_uv_or_python_names_the_step_and_changes_nothing(cold):
    cold.python("python3", supported=False)
    r = cold.run("--yes")
    assert r.returncode == 69 and "Install uv yourself" in r.stderr
    assert not cold.state.exists() or not (cold.state / "python-acquire.pending").exists()


def test_bridge_uv_failure_clears_sentinel_and_never_hands_off(cold):
    cold.uv(install_rc=3)
    r = cold.run("--yes")
    assert r.returncode == 1 and "HANDOFF" not in cold.text()
    assert not (cold.state / "python-acquire.pending").exists()


def test_bridge_pending_and_live_owner_and_explicit_recovery(cold):
    cold.state.mkdir()
    sentinel = cold.state / "python-acquire.pending"
    sentinel.write_text(f"pid={os.getppid()}\n")
    cold.uv(); cold.python("python3")
    live = cold.run("--yes")
    assert live.returncode == 75 and "still acquiring" in live.stderr and cold.text() == ""
    sentinel.write_text("pid=999999999\n")
    for flags in ((), ("--yes",)):
        blocked = cold.run(*flags)
        assert blocked.returncode == 75 and "--recover --yes" in (blocked.stdout + blocked.stderr)
    assert sentinel.exists() and cold.text() == ""
    ok = cold.run("--recover", "--yes")
    assert ok.returncode == 0 and "python --yes --state-dir" in cold.text() and "--recover" in cold.text()
    assert "python install" not in cold.text(), "recovery never re-downloads"


def test_bridge_recovery_with_no_python_clears_and_says_retry(cold):
    cold.state.mkdir()
    sentinel = cold.state / "python-acquire.pending"
    sentinel.write_text("pid=999999999\n")
    r = cold.run("--recover", "--yes")
    assert r.returncode == 0 and "Retry" in r.stdout and not sentinel.exists()
    assert cold.text() == ""


def test_bridge_rejects_unknown_arguments_and_shows_help(cold):
    assert cold.run("--bogus").returncode == 2
    h = cold.run("--help")
    assert h.returncode == 0 and "cold-start bridge" in h.stdout and "Exit:" in h.stdout
