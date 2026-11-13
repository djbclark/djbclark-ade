"""B1 (W21c-a): the live backend scan never opens a non-regular `*.plist` / `*.service` entry (a FIFO hung `reconcile`).

Real FIFOs in a tmp dir, a fake launchctl (always "not loaded"), and every scan runs in a child process under a timeout, so a
regression fails the test instead of hanging the suite."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_sched as S  # noqa: E402

CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import ade_sched as S
backend, d, tool = sys.argv[2], sys.argv[3], sys.argv[4]
kw = {"agents_dir": d, "launchctl": tool} if backend == "launchd" else {"unit_dir": d, "systemctl": tool}
jobs = S.list_backend_labels(backend, env={"HOME": d}, **kw)
print(json.dumps([[j.id, j.source, j.active] for j in jobs]))
"""


@pytest.fixture
def fake_tool(tmp_path):
    t = tmp_path / "fakectl"
    t.write_text("#!/bin/sh\nexit 1\n")
    t.chmod(0o755)
    return str(t)


def scan(backend: str, d: Path, tool: str, timeout: float = 20.0) -> list[list]:
    r = subprocess.run([sys.executable, "-c", CHILD, str(BIN), backend, str(d), tool], capture_output=True, text=True,
                       timeout=timeout)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_helper_classifies_without_blocking(tmp_path):
    fifo = tmp_path / "x.plist"
    os.mkfifo(fifo)
    reg = tmp_path / "r.plist"
    reg.write_text(f"<!-- {S.GENERATED} -->" + "x" * 9000)
    link = tmp_path / "l.plist"
    link.symlink_to(reg)
    fifo_link = tmp_path / "fl.plist"
    fifo_link.symlink_to(fifo)
    assert S._unit_head(fifo) is S._NON_REGULAR
    assert S._unit_head(fifo_link) is S._NON_REGULAR
    assert S._unit_head(tmp_path) is S._NON_REGULAR
    assert S._unit_head(tmp_path / "missing.plist") is S._UNREADABLE
    assert S._unit_head(tmp_path / "dangling.plist") is S._UNREADABLE
    head = S._unit_head(reg)
    assert isinstance(head, str) and len(head) == 4096 and S.GENERATED in head
    assert S._unit_head(link) == head


@pytest.mark.parametrize("make", ["fifo", "fifo-symlink"])
def test_launchd_scan_reports_a_fifo_and_does_not_hang(tmp_path, fake_tool, make):
    d = tmp_path / "agents"
    d.mkdir()
    fifo = tmp_path / "elsewhere.fifo"
    os.mkfifo(fifo)
    if make == "fifo":
        os.mkfifo(d / "a.fifo.plist")
    else:
        (d / "a.fifo.plist").symlink_to(fifo)
    (d / "b.ok.plist").write_text(f"<!-- {S.GENERATED} -->")
    (d / "c.hand.plist").write_text("<plist/>")
    got = scan("launchd", d, fake_tool)
    assert got == [["a.fifo", "non-regular", None], ["b.ok", "generated", False], ["c.hand", "file", False]]
    # the FIFO survives untouched and no writer was ever needed
    assert stat.S_ISFIFO(os.lstat(d / "a.fifo.plist").st_mode) or (d / "a.fifo.plist").is_symlink()


def test_systemd_scan_reports_a_fifo_and_does_not_hang(tmp_path, fake_tool):
    d = tmp_path / "units"
    d.mkdir()
    os.mkfifo(d / "a.fifo.service")
    (d / "b.ok.service").write_text(f"# {S.GENERATED}\n")
    got = scan("systemd", d, fake_tool)
    assert [g[:2] for g in got] == [["a.fifo", "non-regular"], ["b.ok", "generated"]]


def test_status_listing_skips_a_fifo_without_hanging(tmp_path, fake_tool):
    d = tmp_path / "agents"
    d.mkdir()
    os.mkfifo(d / "a.fifo.plist")
    (d / "b.ok.plist").write_text(f"<!-- {S.GENERATED} -->")
    child = ("import sys; sys.path.insert(0, sys.argv[1]); import ade_sched as S; "
             "print(S.installed_labels('launchd', env={'HOME': sys.argv[2]}, agents_dir=sys.argv[2], launchctl=sys.argv[3]))")
    r = subprocess.run([sys.executable, "-c", child, str(BIN), str(d), fake_tool], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "['b.ok']"


def test_a_fifo_is_no_live_identity_and_is_reported_in_the_scan_notes(tmp_path, fake_tool):
    d = tmp_path / "agents"
    d.mkdir()
    os.mkfifo(d / "com.djbclark.x.plist")
    child = ("import sys, json; sys.path.insert(0, sys.argv[1]); import ade_sched as S; "
             "b = S.detect('launchd', {'HOME': sys.argv[2]}); "
             "sc = S.scan_live(b, env={'HOME': sys.argv[2]}, skip_paseo=True, agents_dir=sys.argv[2], launchctl=sys.argv[3]); "
             "print(json.dumps([sorted(sc.ids), list(sc.notes), [j.source for j in sc.jobs]]))")
    r = subprocess.run([sys.executable, "-c", child, str(BIN), str(d), fake_tool], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    ids, notes, sources = json.loads(r.stdout)
    assert ids == [] and sources == ["non-regular"]
    assert len(notes) == 1 and "com.djbclark.x" in notes[0] and "not a regular file" in notes[0]


def test_planner_reports_the_note_and_never_removes_a_fifo_entry(tmp_path):
    live = S.LiveScan("launchd", (S.LiveJob("com.djbclark.x", "launchd", "non-regular", None),),
                      ("launchd entry com.djbclark.x: not a regular file; never opened, not a live identity",))
    steps = S.plan_reconcile([], [], ledger=S.empty_jobs_ledger(), live=live, backend_name="launchd", root=tmp_path)
    assert steps and all(s.action == "report" and not s.touch for s in steps)
    assert any("not a regular file" in s.detail for s in steps)


def test_whole_file_reads_refuse_a_fifo_without_hanging(tmp_path):
    child = ("import sys; sys.path.insert(0, sys.argv[1]); import ade_sched as S; from pathlib import Path\n"
             "for n in ('f', 'l'):\n"
             "    try: S.read_regular_bytes(Path(sys.argv[2]) / n)\n"
             "    except OSError as e: print('refused', n)\n"
             "print(S._on_disk_files_match is not None)")
    os.mkfifo(tmp_path / "f")
    (tmp_path / "l").symlink_to(tmp_path / "f")
    r = subprocess.run([sys.executable, "-c", child, str(BIN), str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["refused", "f", "refused", "l", "True"]
    reg = tmp_path / "ok"
    reg.write_bytes(b"x" * 10)
    assert S.read_regular_bytes(reg) == b"x" * 10
    with pytest.raises(OSError):
        S.read_regular_bytes(reg, limit=5)
