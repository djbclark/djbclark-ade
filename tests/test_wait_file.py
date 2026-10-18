"""bin/wait-file refuses paths that can never appear and waits for real ones."""

import subprocess
import threading
import time
from pathlib import Path

WAIT_FILE = Path(__file__).resolve().parent.parent / "bin" / "wait-file"


def run(*args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(WAIT_FILE), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_refuses_empty_relative_root_and_missing_dir(tmp_path: Path) -> None:
    assert run("").returncode == 2
    assert run("install.log").returncode == 2
    root = run("/install3.log")
    assert root.returncode == 2
    assert "filesystem root" in root.stderr
    assert run(str(tmp_path / "nope" / "x.log")).returncode == 2


def test_bad_timeout_is_usage_error(tmp_path: Path) -> None:
    assert run("--timeout", "soon", str(tmp_path / "x.log")).returncode == 2


def test_times_out(tmp_path: Path) -> None:
    r = run("--timeout", "1", str(tmp_path / "x.log"))
    assert r.returncode == 124


def test_ready_when_non_empty(tmp_path: Path) -> None:
    log = tmp_path / "x.log"

    def write() -> None:
        time.sleep(1)
        log.write_text("hello\n")

    threading.Thread(target=write).start()
    r = run("--timeout", "15", "--nonempty", str(log))
    assert r.returncode == 0
    assert "hello" in r.stdout


def test_match_waits_for_line(tmp_path: Path) -> None:
    log = tmp_path / "x.log"
    log.write_text("progress\n")

    def write() -> None:
        time.sleep(1)
        with log.open("a") as f:
            f.write("rc=0\n")

    threading.Thread(target=write).start()
    r = run("--timeout", "15", "--match", "^rc=", str(log))
    assert r.returncode == 0
    assert "rc=0" in r.stdout


def test_empty_done_marker_is_ready(tmp_path: Path) -> None:
    # a touched .done marker is empty: existence is enough (2026-10-17: a slice waited 6 minutes past it)
    marker = tmp_path / "report.md.done"
    marker.touch()
    assert run("--timeout", "5", str(marker)).returncode == 0
    assert run("--timeout", "1", "--nonempty", str(marker)).returncode == 124
