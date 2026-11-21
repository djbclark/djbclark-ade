"""The three lows of the PR 859 adversary re-review (round 2, head 1b767598), fixed in the stacked follow-up:
(1) a keep-running rule is ONE executable, matched exactly; (2) the auto-freeze's start times come from one batch read, only while a build is held, and an app
whose process started after the table was read is left out of that tick; (3) the config comments and the `load_config` docstring match the rulings."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
import gui_hog_freeze as gf  # noqa: E402
from test_gui_hog_auto import CHROME, CODEXBAR, OTHER, World, auto_cfg, held  # noqa: E402
from test_gui_hog_freeze import ME, T0  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: True)
    monkeypatch.delenv("LW_GUI_HOG_AUTO", raising=False)
    monkeypatch.delenv("LW_GUI_HOG", raising=False)


def lstart(epoch):
    return time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(epoch))


# ---- low 1: a keep-running rule names one executable ------------------------------------------------------------------------------------------
def test_low1_an_absolute_rule_that_is_a_directory_is_refused_and_a_file_is_not(tmp_path):
    tool = tmp_path / "Xcode.app" / "Contents" / "Developer"
    (tool / "usr" / "bin").mkdir(parents=True)
    clang = tool / "usr" / "bin" / "clang"
    clang.write_text("")
    assert gh.rule_ok(str(tool)) is False and gh.rule_ok(str(tool / "usr")) is False   # a toolchain directory would lift the build stop for all of it
    assert gh.rule_ok(str(clang)) is True


def test_low1_a_relative_rule_that_names_a_directory_keeps_nothing(w):
    cfg = auto_cfg(keep=False)
    cfg["freeze"]["keep_running"] = {CODEXBAR: ["Contents/Helpers"]}   # the directory that holds CodexBarCLI: the old prefix match kept every helper in it
    a = w.group(cfg)[CODEXBAR]
    assert a["kept_pids"] == [] and a["member_pids"] == [100, 101]
    cfg["freeze"]["keep_running"] = {CODEXBAR: ["Contents/Helpers/CodexBarCLI"]}
    assert w.group(cfg)[CODEXBAR]["kept_pids"] == [101]   # the exact executable still works


def test_low1_the_out_of_bundle_exemption_is_exact_too(w, monkeypatch):
    """Even a rule that got past `rule_ok` (a directory that did not exist when the config was read) lifts the build stop for that one path only."""
    monkeypatch.setattr(gh, "rule_ok", lambda r: True)
    cfg = auto_cfg(keep=False)
    cfg["freeze"]["keep_running"] = {CHROME: [str(w.nm.parent)]}   # the directory holding the out-of-bundle host, not the host
    assert w.group(cfg)[CHROME]["hosts_build"] is True
    cfg["freeze"]["keep_running"] = {CHROME: [str(w.nm)]}
    a = w.group(cfg)[CHROME]
    assert a["hosts_build"] is False and a["kept_pids"] == [501]


def test_low1_same_path_is_exact_and_case_blind():
    assert gh._same_path("/A/B.app/Contents/Helpers/X", "/a/b.app/contents/helpers/x")
    assert not gh._same_path("/A/B.app/Contents/Helpers/X/deeper", "/A/B.app/Contents/Helpers/X")
    assert not gh._same_path("/A/B.app/Contents/Helpers", "/A/B.app/Contents/Helpers/X")


# ---- low 2: the start times -------------------------------------------------------------------------------------------------------------------
def test_low2_starts_are_read_once_and_only_while_a_build_is_held(monkeypatch):
    calls = []
    monkeypatch.setattr(gh, "proc_starts", lambda pids: calls.append(sorted(pids)) or {p: lstart(T0 - 500) for p in pids})
    monkeypatch.setattr(gh, "proc_start", lambda p: (_ for _ in ()).throw(AssertionError("one ps per app")))
    assert gh.auto_starts([100, 400], [], T0) == ({}, set()) and calls == []   # no hold: the step does nothing, so no ps at all
    starts, late = gh.auto_starts([100, 400], held(), T0)
    assert calls == [[100, 400]] and starts == {100: lstart(T0 - 500), 400: lstart(T0 - 500)} and late == set()


def test_low2_a_process_started_after_the_table_was_read_is_late_and_not_handed_on():
    starts = {100: lstart(T0 - 500), 400: lstart(T0 + 60), 500: "proc:123"}
    got, late = gh.auto_starts([100, 400, 500], held(), T0, start_of=starts.get)
    assert late == {"400"} and got == {100: lstart(T0 - 500), 500: "proc:123"}   # an unparsable form is accepted: freeze() re-checks all four fields
    got, late = gh.auto_starts([400], held(), T0, start_of={400: lstart(T0 + gh.START_SLACK_S)}.get)
    assert late == set() and 400 in got   # the one-second resolution of lstart is allowed for


def test_low2_the_tick_leaves_a_relaunched_app_out_of_the_step(w, monkeypatch):
    seen = []
    monkeypatch.setattr(gf, "auto_freeze_step", lambda *a, **k: seen.append((a, k)) or None)
    monkeypatch.setattr(gh, "read_holds", lambda *a, **k: held())
    late = {400: lstart(T0 + 90)}   # OTHER (pid 400) was started after the table was read: a relaunch in the gap
    table, rss, ttys, _s = w.ops.table()
    cfg = auto_cfg(order=(CODEXBAR, OTHER))
    gh.tick({}, T0, table, rss, ttys, state_dir=w.state, my_uid=ME, cfg=cfg, lsapps=w.lsapps(), exe_of=w.ops.exe, out=lambda x: None, auto_freeze=True,
            start_of=lambda p: late.get(p, lstart(T0 - 500)), gui_ok=False, load_avg=(1, 2, 3), ncpu=10)
    (args, kw), = seen
    roots = {a["root_pid"] for a in args[2]}
    assert 400 not in roots and 100 in roots and 400 not in kw["starts"] and 100 in kw["starts"]


def test_low2_the_tick_reads_no_start_without_a_hold(w, monkeypatch):
    seen = []
    monkeypatch.setattr(gf, "auto_freeze_step", lambda *a, **k: seen.append(k) or None)
    monkeypatch.setattr(gh, "read_holds", lambda *a, **k: [])
    table, rss, ttys, _s = w.ops.table()
    gh.tick({}, T0, table, rss, ttys, state_dir=w.state, my_uid=ME, cfg=auto_cfg(), lsapps=w.lsapps(), exe_of=w.ops.exe, out=lambda x: None, auto_freeze=True,
            start_of=lambda p: (_ for _ in ()).throw(AssertionError("a ps with no hold")), gui_ok=False, load_avg=(1, 2, 3), ncpu=10)
    assert seen and seen[0]["starts"] == {}


# ---- low 3: the comments say what was ruled ---------------------------------------------------------------------------------------------------
def test_low3_the_config_comments_and_the_docstring_match_the_rulings():
    text = (REPO / "config" / "gui-hog.toml").read_text()
    assert "CodexBar is first in the auto list" not in text and "Costs while frozen" not in text and "unproven for a full freeze" not in text
    assert "ADD to `skip` and `always`" in text and "ONE executable" in text and "never as a prefix" in text
    doc = gh.load_config.__doc__
    assert "`[freeze.auto] skip`" in doc and "`always`" in doc and "`[freeze.depends]`" in doc
    assert "EXACTLY" in (gh.rule_ok.__doc__ or "") and "existing directory" in gh.rule_ok.__doc__
