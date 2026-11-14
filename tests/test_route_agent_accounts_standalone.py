"""route_agent.py: several accounts of one pool keep every window and model sublimit; a copy of the file alone fails cleanly.

(2026-11-14, pr-radar-route follow-ups: CodeRabbit comments on omercnet/paseo-plugins#618, verified against the code.)
"""
from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import route_agent as r  # noqa: E402


def _window(label, left, resets_at=None):
    return {"label": label, "pool_family": "default", "remaining_percent": left, "headroom_percent": left,
            "state": "ok" if left > 1 else "exhausted", "resets_at": resets_at}


def _fable(left, resets_at):
    return {"label": "Fable", "pool_family": "fable", "quota_scope": "model_sublimit", "shared_pool_family": "default",
            "max_share_of_parent_percent": 50, "headroom_percent": left, "remaining_percent": left,
            "state": "ok" if left > 1 else "exhausted", "resets_at": resets_at}


ACCOUNT_A = {"provider": "claude", "age_seconds": 60,
             "windows": [_window("weekly", 20, "2026-11-20T00:00:00+00:00"), _fable(0, "2026-11-18T00:00:00+00:00")]}
ACCOUNT_B = {"provider": "claude", "age_seconds": 60,
             "windows": [_window("weekly", 70, "2026-11-21T00:00:00+00:00"), _window("session", 60),
                         _fable(30, "2026-11-19T00:00:00+00:00")]}


@pytest.mark.parametrize("order", list(itertools.permutations([ACCOUNT_A, ACCOUNT_B])))
def test_several_accounts_keep_every_window_sublimit_and_reset(order):
    pool = r._providers_from_accounts(list(order), 60)["claude"]
    assert pool["remaining"] == 20                                   # the tightest account wins, in either order
    assert pool["windows"]["weekly"] == 20                           # per window the tighter reading, not the last account's
    assert pool["windows"]["session"] == 60                          # a window only the other account reports survives
    assert pool["sublimits"]["fable"] == 0                           # a cap never loosens by account order
    assert pool["sublimit_resets"]["fable"] == "2026-11-19T00:00:00+00:00"   # the later reset, for the wait message


def test_one_account_is_unchanged_by_the_merge():
    pool = r._providers_from_accounts([ACCOUNT_B], 60)["claude"]
    assert pool["remaining"] == 60 and pool["windows"]["weekly"] == 70 and pool["windows"]["session"] == 60
    assert pool["sublimits"] == {"fable": 30}
    assert pool["sublimit_resets"] == {"fable": "2026-11-19T00:00:00+00:00"}


def test_a_later_account_without_sublimits_does_not_drop_the_earlier_ones():
    bare = {"provider": "claude", "age_seconds": 60, "windows": [_window("weekly", 90)]}
    pool = r._providers_from_accounts([ACCOUNT_A, bare], 60)["claude"]
    assert pool["sublimits"] == {"fable": 0}
    assert pool["sublimit_resets"] == {"fable": "2026-11-18T00:00:00+00:00"}


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_a_known_reading_beats_an_unknown_one_in_either_order(order):
    """Decision pinned (the same as `remaining` and `_merge_pool`): an account whose reading expired adds no number, and
    does not blank the other account's windows or Fable cap either."""
    known = {"provider": "claude", "age_seconds": 60,
             "windows": [_window("weekly", 50), _fable(40, "2026-11-19T00:00:00+00:00")]}
    unknown = {"provider": "claude", "age_seconds": 60, "reading_expired": True,
               "windows": [_window("weekly", 90), _fable(10, "2026-11-18T00:00:00+00:00")]}
    pool = r._providers_from_accounts([[known, unknown][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert pool["windows"]["weekly"] == 50
    assert pool["sublimits"]["fable"] == 40


def _standalone(tmp_path, *args):
    """bin/route_agent.py copied alone into an empty directory: no ade_config, ade_gates, model_tiers or config/."""
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(ROOT / "bin" / "route_agent.py", lone / "route_agent.py")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-I", str(lone / "route_agent.py"), *args], capture_output=True, text=True,
                          env=env, cwd=tmp_path, timeout=60, stdin=subprocess.DEVNULL)


def test_a_lone_copy_fails_with_one_line_not_a_traceback(tmp_path):
    proc = _standalone(tmp_path, "route", "--kind", "code", "--json")
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "Traceback" not in proc.stderr
    assert len(proc.stderr.splitlines()) == 1
    assert "cannot route standalone" in proc.stderr and "ade_config" in proc.stderr


def test_the_repo_copy_still_runs(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("ROUTING_POLICY", "AIUSE_SNAPSHOT")} | {"HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(ROOT / "bin" / "route_agent.py"), "--help"], capture_output=True, text=True,
                          cwd=tmp_path, timeout=60, stdin=subprocess.DEVNULL, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "route" in proc.stdout
