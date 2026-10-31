#!/usr/bin/env python3
"""A queued rumination line must not outlive the condition it describes (2026-10-29).

At 21:41 the Tier 1 pointer really did record 067a9868 while the repo was at 58a1a774, so the watcher
queued `stale chain log: ...` (the seat was mid-turn). The pointer was corrected at 21:47, but the
passes at 21:47, 21:52 and 21:58 kept logging that same sentence: the queue replayed TEXT, it never
re-derived it. A state-like line (stale chain log, finished-but-open jobs) now carries a key, and a
queued copy whose key the pass no longer produces is dropped. Event lines (new mail, new jobs, the
new-PR announcement) stay keyless on purpose: they are diffs against `state["last"]`, the pass cannot
recompute them, and dropping one would lose an announcement the seat never heard. Delivery stays
AT-LEAST-ONCE: a keyless or still-true entry is retried, a bare-string queue from the previous version
still loads.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LIVE = "d2a505dd-8c93-4ba5-8684-e98a3865a1ae"
QUIET = {"mail": [], "jobs": [], "prs": [], "stale": None}


def load(monkeypatch, tmp_path):
    loader = importlib.machinery.SourceFileLoader("rumination_watch", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    repo = tmp_path / "techno-euphora"
    (repo / "agents" / "comm").mkdir(parents=True)
    monkeypatch.setattr(rw, "REPO", repo)
    monkeypatch.setattr(rw, "HOME", tmp_path)
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    monkeypatch.setattr(rw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "LOG", tmp_path / "state" / "rumination.log")
    monkeypatch.setattr(rw, "DEPLOY_OFF", True)          # the real deploy would fetch and fast-forward
    monkeypatch.setattr(rw, "owner_session", lambda: (LIVE, "test"))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("working", "mid-turn"))
    monkeypatch.setattr(rw, "escalate_dark", lambda *args, **kw: ("", ""))
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    return rw


class Seat:
    """A stand-in for `to_session`: returns WORD and records every summary it was handed."""

    def __init__(self, rw, monkeypatch, word="working"):
        self.word = word
        self.sent: list[str] = []
        monkeypatch.setattr(rw, "to_session", self._send)

    def _send(self, text):
        self.sent.append(text)
        return self.word


def run_pass(rw, survey):
    rw.survey = lambda: survey
    return rw._pass(rw.argparse.Namespace(dry_run=False, quiet=True))


def write_state(rw, pending, last=QUIET):
    rw.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rw.STATE.write_text(json.dumps({"last": last, "pending": pending}))


def pending_on_disk(rw):
    return json.loads(rw.STATE.read_text())["pending"]


STALE = "stale chain log: Tier 1 log records 067a9868b010, repo is at 58a1a7743130"


def test_a_resolved_stale_line_is_dropped_not_replayed(monkeypatch, tmp_path):
    """The live case: queued while busy, condition fixed, seat STILL busy next pass."""
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "working")
    stale = dict(QUIET, stale="Tier 1 log records 067a9868b010, repo is at 58a1a7743130")
    run_pass(rw, stale)
    assert [e["key"] for e in pending_on_disk(rw)] == ["stale chain log"]
    assert seat.sent == ["rumination: " + STALE]

    seat.sent.clear()
    assert run_pass(rw, QUIET) == 0                    # pointer corrected; seat is still mid-turn
    assert seat.sent == [], "a fixed condition must not be sent again"
    assert pending_on_disk(rw) == []
    log = rw.LOG.read_text()
    assert log.count("pending: dropping resolved stale chain log") == 1
    assert log.count("067a9868b010") == 1, "only the first, true, pass may print the sentence"


def test_a_still_true_keyed_line_is_retried_as_a_labelled_retry_with_its_age(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "working")
    write_state(rw, [{"key": "stale chain log", "text": "stale chain log: records OLD, repo is at X",
                      "queued_at": time.time() - 6 * 60}])
    assert run_pass(rw, dict(QUIET, stale="records NEW, repo is at Y")) == 10
    assert seat.sent == ["rumination: stale chain log: records NEW, repo is at Y"], \
        "the retry is this pass's recomputation, never the old sentence"
    (entry,) = pending_on_disk(rw)
    assert entry["key"] == "stale chain log" and entry["text"].endswith("records NEW, repo is at Y")
    assert abs(time.time() - 6 * 60 - entry["queued_at"]) < 30, "the original queue time is kept"
    spoke = [ln for ln in rw.LOG.read_text().splitlines() if " spoke session=" in ln]
    assert len(spoke) == 1
    assert "pending=1 (retry, oldest 6m): rumination: stale chain log: records NEW" in spoke[0]


def test_a_first_time_line_is_not_marked_as_a_retry(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    Seat(rw, monkeypatch, "working")
    run_pass(rw, dict(QUIET, stale="x"))
    (spoke,) = [ln for ln in rw.LOG.read_text().splitlines() if " spoke session=" in ln]
    assert "pending=1: rumination: stale chain log: x" in spoke and "retry" not in spoke


def test_the_old_bare_string_queue_still_loads_and_is_delivered(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "delivered")
    write_state(rw, ["2 unread peer message(s): a, b", STALE])
    state = rw.load_state()
    assert [(e["key"], e["text"], e["queued_at"]) for e in state["pending"]] == [
        (None, "2 unread peer message(s): a, b", None), (None, STALE, None)]
    # An old bare line has no key, so it is retried even though nothing now matches it: at-least-once.
    assert run_pass(rw, QUIET) == 10
    assert seat.sent == ["rumination: 2 unread peer message(s): a, b; " + STALE]
    assert pending_on_disk(rw) == []
    (spoke,) = [ln for ln in rw.LOG.read_text().splitlines() if " spoke session=" in ln]
    assert "pending=0 (retry): rumination:" in spoke, "unknown age: still marked as a retry"


def test_a_keyless_event_line_is_retried_though_no_current_item_matches_it(monkeypatch, tmp_path):
    """The regression guard against over-eager dropping: new mail cannot be recomputed after it has
    been consumed, so a keyless entry survives every pass until a real send."""
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "working")
    write_state(rw, [{"key": None, "text": "1 unread peer message(s): m1", "queued_at": time.time() - 3600}])
    for _ in range(3):
        run_pass(rw, QUIET)                            # nothing new, seat busy
    assert seat.sent == ["rumination: 1 unread peer message(s): m1"] * 3
    assert [e["text"] for e in pending_on_disk(rw)] == ["1 unread peer message(s): m1"]
    assert "dropping resolved" not in rw.LOG.read_text()
    seat.word = "delivered"
    run_pass(rw, QUIET)
    assert pending_on_disk(rw) == []


def test_a_new_mail_line_is_queued_keyless(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    Seat(rw, monkeypatch, "working")
    run_pass(rw, dict(QUIET, mail=["peer-1"]))
    (entry,) = pending_on_disk(rw)
    assert entry["key"] is None and "unread peer message" in entry["text"]


def test_a_stuck_job_line_is_keyed_by_label_and_refreshed_to_the_jobs_stuck_now(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "working")
    jobs = [{"name": "A", "done_exists": False}, {"name": "B", "done_exists": True}]
    write_state(rw, [{"key": "job(s) finished but not closed",
                      "text": "job(s) finished but not closed: A", "queued_at": time.time() - 60}],
                last=dict(QUIET, jobs=jobs))          # both jobs already announced: no event line
    run_pass(rw, dict(QUIET, jobs=jobs))
    # B still satisfies the finding, so it is kept, but the sentence names B, not the closed A.
    assert seat.sent[-1].endswith("job(s) finished but not closed: B")
    assert "A" not in seat.sent[-1].split("closed:")[1]
    run_pass(rw, dict(QUIET, jobs=[{"name": "B", "done_exists": False}]))
    assert pending_on_disk(rw) == []
    assert "pending: dropping resolved job(s) finished but not closed" in rw.LOG.read_text()


def test_the_cap_still_evicts_the_oldest_and_says_so(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    Seat(rw, monkeypatch, "working")
    monkeypatch.setattr(rw, "PENDING_MAX", 2)
    write_state(rw, [{"key": None, "text": f"mail {n}", "queued_at": 1.0} for n in range(4)])
    run_pass(rw, QUIET)
    assert [e["text"] for e in pending_on_disk(rw)] == ["mail 2", "mail 3"]
    assert "dropping 2 oldest line(s) over the cap of 2: mail 0" in rw.LOG.read_text()


def test_an_unverified_send_still_clears_the_queue_and_admits_the_loss(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    Seat(rw, monkeypatch, "unverified")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or False)
    write_state(rw, [{"key": None, "text": "1 unread peer message(s): m", "queued_at": 1.0}])
    run_pass(rw, QUIET)
    assert pending_on_disk(rw) == []
    assert any("could not be PROVEN delivered" in t for t in told)
    assert "could not be PROVEN" in json.loads(rw.STATE.read_text())["undisclosed"]


def test_unreadable_pending_entries_do_not_crash_the_pass(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    seat = Seat(rw, monkeypatch, "working")
    write_state(rw, [5, {"key": "stale chain log"}, None, ["x"], {"text": ""},
                     {"key": 7, "text": "1 unread peer message(s): ok", "queued_at": "soon"}])
    assert run_pass(rw, QUIET) == 10
    assert seat.sent == ["rumination: 1 unread peer message(s): ok"], "readable entries survive"
    (entry,) = pending_on_disk(rw)
    assert entry["key"] is None and entry["queued_at"] is None
    assert "pending: ignoring 5 unreadable entries" in rw.LOG.read_text()
    assert "pending_unreadable" not in json.loads(rw.STATE.read_text())


def test_a_pending_that_is_not_a_list_is_discarded(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    write_state(rw, "stale chain log")
    assert rw.load_state()["pending"] == []
    write_state(rw, {"key": "k", "text": "t"})
    assert rw.load_state()["pending"] == []

import pytest


@pytest.fixture(autouse=True)
def isolated_watcher_environment(monkeypatch, tmp_path):
    import os
    import subprocess
    for key in list(os.environ):
        if key.startswith("RW_") or key == "PASEO_AGENT_ID":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RW_NO_DEPLOY", "1")
    real = subprocess.run
    def guarded(argv, *args, **kwargs):
        command = list(argv) if not isinstance(argv, str) else [argv]
        if command[:3] == ["env", "-u", "PASEO_AGENT_ID"]:
            command = command[3:]
        git_read = {"rev-parse", "cat-file", "merge-base", "log", "status"}
        git_cwd = Path(command[command.index("-C") + 1]).resolve() if "-C" in command else Path.cwd()
        fixture_git = git_cwd.is_relative_to(tmp_path)
        allowed = command and ((command[0] == "git" and
                    (fixture_git or (command[3] if command[1:2] == ["-C"] else command[1]) in git_read)) or
                  (Path(command[0]).name.startswith("python") and "-c" in command))
        import shutil
        executable = shutil.which(command[0]) if command else None
        local_fixture = executable and Path(executable).resolve().is_relative_to(tmp_path)
        python_fixture = (command and Path(command[0]).name.startswith("python") and
                          any(Path(arg).is_absolute() and Path(arg).resolve().is_relative_to(tmp_path)
                              for arg in command[1:]))
        allowed = allowed or local_fixture or python_fixture
        if not allowed:
            raise AssertionError(f"unexpected external launcher: {command}")
        return real(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", guarded)
