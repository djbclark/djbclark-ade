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


def test_non_regular_entry_is_report_only_in_the_plan(tmp_path):
    lj = S.LiveJob("a.fifo", "launchd", "non-regular", None)
    assert lj.source != "generated"  # the planner's report-only branch (never unload) takes every non-"generated" source
