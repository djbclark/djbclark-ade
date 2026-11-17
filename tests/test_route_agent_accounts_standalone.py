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


def test_codex_prepaid_credits_are_a_separate_pool_from_subscription():
    # The codex provider's subscription window (pool_family default) and its
    # OpenAI API prepaid credits (pool_family openai_api) are separate routing
    # pools: the subscription must not be presented as authority for the
    # prepaid API-only models gpt-6.1-sol / gpt-6-astra (2026-11-17).
    accounts = [
        {
            "provider": "codex",
            "age_seconds": 60,
            "windows": [
                {"label": "Codex weekly quota (2)", "pool_family": "default", "window_id": "secondary",
                 "remaining_percent": 96.0, "headroom_percent": 96.0, "state": "ok"},
                {"label": "OpenAI API credits", "pool_family": "openai_api", "window_id": "codex-api-credits",
                 "remaining_percent": 0.0, "headroom_percent": 0.0, "state": "exhausted"},
            ],
        }
    ]
    pools = r._providers_from_accounts(accounts, 60)
    assert pools["codex-subscription"]["remaining"] == 96.0   # subscription window keeps its headroom
    assert pools["codex"]["remaining"] == 0.0                  # prepaid credits exhausted -> fail closed


def test_codex_prepaid_pool_is_the_openai_api_canary():
    assert r.canary_pool(r.BY_NAME["codex"]) == "openai_api"
    assert r.canary_pool(r.BY_NAME["codex-subscription"]) is None


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


KNOWN = {"provider": "claude", "age_seconds": 60,
         "windows": [_window("weekly", 50), _fable(40, "2026-11-19T00:00:00+00:00")]}
EXPIRED = {"provider": "claude", "age_seconds": 60, "reading_expired": True,
           "windows": [_window("weekly", 90), _fable(10, "2026-11-18T00:00:00+00:00")]}
NO_WINDOW = {"provider": "claude", "age_seconds": 60, "windows": []}


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_a_known_reading_beats_an_unknown_one_for_remaining_and_the_fable_cap_in_either_order(order):
    """Decision pinned: an account whose reading expired adds no number to the pool figure (`remaining`, as in
    `_merge_pool`) and does not blank the other account's Fable cap."""
    pool = r._providers_from_accounts([[KNOWN, EXPIRED][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert pool["sublimits"]["fable"] == 40


@pytest.mark.parametrize("second", [EXPIRED, NO_WINDOW], ids=["expired reading", "no window"])
@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_an_unmeasured_second_account_keeps_the_pool_closed_for_the_plenty_gate(order, second):
    """lw-02 (adversary B1 on #688): the pool figure is the measured account's, but a window an account could not
    measure stays None, so `plenty_remaining` says unknown and the pooled service is not eligible (fail closed on unknown
    quota). Before, the measured account's windows hid the other account's None and opened the gate."""
    pool = r._providers_from_accounts([[KNOWN, second][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert r.plenty_remaining(pool) is None


def test_a_single_account_without_windows_adds_no_marker_a_measured_second_source_can_open_the_pool():
    """The marker is for several accounts of one provider only: one account with no window leaves `windows` empty, so a
    measured Paseo reading folded in by `_merge_pool` still opens the pool (adversary A1 on #698)."""
    into = r._providers_from_accounts([NO_WINDOW], 60)
    assert into["claude"]["windows"] == {} and into["claude"]["remaining"] is None
    r._merge_pool(into, "claude", {"remaining": 60.0, "windows": {"5h": 60.0}, "sublimits": {}})
    assert r.plenty_remaining(into["claude"]) == 60.0


def test_two_measured_accounts_still_open_the_plenty_gate_on_the_tighter_one():
    other = {"provider": "claude", "age_seconds": 60, "windows": [_window("weekly", 80)]}
    pool = r._providers_from_accounts([KNOWN, other], 60)["claude"]
    assert pool["windows"]["weekly"] == 50 and r.plenty_remaining(pool) == 50


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


def _lone_tree(tmp_path, **modules):
    """route_agent.py plus stand-ins for the sibling modules, each with the given source (a repo copy that is broken)."""
    d = tmp_path / "tree"
    d.mkdir()
    shutil.copy(ROOT / "bin" / "route_agent.py", d / "route_agent.py")
    for name, src in modules.items():
        (d / f"{name}.py").write_text(src)
    return d


def _run_script(tmp_path, d):
    return subprocess.run([sys.executable, "-I", str(d / "route_agent.py"), "route", "--kind", "code", "--json"],
                          capture_output=True, text=True, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                          cwd=tmp_path, timeout=60, stdin=subprocess.DEVNULL)


_NAME_ERROR = "raise ImportError(\"cannot import name 'renamed_fn' from 'model_tiers'\", name='model_tiers')\n"


@pytest.mark.parametrize("modules", [
    {"ade_config": "raise ImportError(\"cannot import name 'renamed_fn' from 'ade_gates'\")\n", "ade_gates": "", "model_tiers": ""},
    {"ade_config": "import no_such_third_party_package_lw02\n", "ade_gates": "", "model_tiers": ""},
    {"ade_config": "raise ModuleNotFoundError('x', name='ade_gates')\n", "ade_gates": "", "model_tiers": ""},
    {"ade_config": _NAME_ERROR},
], ids=["renamed name", "missing dependency", "sibling present", "ImportError that names an absent sibling"])
def test_an_import_error_inside_the_repo_copy_surfaces_with_its_traceback(tmp_path, modules):
    """lw-02 (adversary B2 on #688): only "the sibling modules are not beside this file" (a ModuleNotFoundError that names
    one of them, whose file is absent) is the one-line exit 2; any other ImportError is a bug and keeps its traceback.
    The last row is a real `from model_tiers import renamed` error: it carries `name='model_tiers'` too."""
    d = _lone_tree(tmp_path, **modules)
    proc = _run_script(tmp_path, d)
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" in proc.stderr and "cannot route standalone" not in proc.stderr
    assert proc.stdout == ""


def test_imported_by_another_module_a_lone_copy_still_raises_the_import_error(tmp_path):
    d = _lone_tree(tmp_path)
    proc = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(d)!r}); import route_agent"],
                          capture_output=True, text=True, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                          cwd=tmp_path, timeout=60, stdin=subprocess.DEVNULL)
    assert proc.returncode == 1 and "ModuleNotFoundError" in proc.stderr and "cannot route standalone" not in proc.stderr


@pytest.mark.parametrize("modules", [
    {"ade_config": "import ade_gates\n"},
    {"ade_config": "", "ade_gates": "import model_tiers\n"},
    {"ade_config": "import model_tiers\n", "ade_gates": ""},
], ids=["ade_gates absent", "model_tiers absent behind ade_gates", "model_tiers absent behind ade_config"])
def test_a_partial_tree_with_a_sibling_truly_absent_gets_the_one_line(tmp_path, modules):
    proc = _run_script(tmp_path, _lone_tree(tmp_path, **modules))
    assert proc.returncode == 2 and "Traceback" not in proc.stderr and "cannot route standalone" in proc.stderr
    assert len(proc.stderr.splitlines()) == 1 and proc.stdout == ""
