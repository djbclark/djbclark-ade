"""Savings, suggestions and the always-freeze list (docs/gui-hog-dialog.md Q1 and Q3, operator ruling 2026-11-21).

Linux CI runs all of it on a fake process table and a temp state directory; nothing signals a real process and no live state file is read.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
import gui_hog_freeze as gf  # noqa: E402
import gui_hog_savings as sv  # noqa: E402
from test_gui_hog_auto import BEEPER, GROK, OTHER, World, auto_cfg, held  # noqa: E402
from test_gui_hog_freeze import T0, world  # noqa: E402,F401,F811 (a fixture imported by name)

REPO = Path(__file__).resolve().parent.parent
NOLOCAL = Path("/nonexistent")


def shipped():
    return gh.load_config(local=NOLOCAL)


@pytest.fixture(autouse=True)
def _sampler_is_loaded(monkeypatch):
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: True)


# ---- the ring of system readings -------------------------------------------------------------------------------------------------------------
def ring_of(rows):
    ring = []
    for t, load, comp, pi, sw in rows:
        sv.hist_add(ring, t, load, {"compress": comp, "pageins": pi, "swapins": sw})
    return ring


def test_the_ring_keeps_the_last_180_readings_and_ignores_a_clock_that_goes_back():
    ring = []
    for i in range(200):
        sv.hist_add(ring, 1000.0 + i * 20, 1.0, {})
    assert len(ring) == sv.HIST_MAX and ring[0][0] == 1000.0 + 20 * 20
    n = len(ring)
    sv.hist_add(ring, 1000.0, 9.0, {})
    sv.hist_add(ring, float("nan"), 9.0, {})
    assert len(ring) == n and all(r[1] == 1.0 for r in ring)


def test_clean_hist_drops_every_malformed_row():
    good = [100.0, 1.0, 5.0, None, 2.0]
    raw = [good, "x", [1, 2], [float("inf"), 1, 1, 1, 1], [100.0, 1, 1, 1, 1], [90.0, 1, 1, 1, 1], [200.0, True, 1, 1, 1][:4] + ["s"], [300.0, 2.0, 1, 1, 1]]
    assert sv.clean_hist(raw) == [good, [300.0, 2.0, 1.0, 1.0, 1.0]]
    assert sv.clean_hist("junk") == [] and sv.clean_hist(None) == []


def test_window_metrics_are_means_and_rates_over_the_window_only():
    ring = ring_of([(0, 2.0, 0, 0, 0), (20, 4.0, 2000, 100, 0), (40, 6.0, 6000, 100, 40), (200, 9.0, 99999, 9999, 9999)])   # the last pair is a 160 s gap: no rate
    m = sv.window_metrics(ring, 0, 40)
    assert m == {"n": 3, "span_s": 40, "load": 4.0, "compress_s": 150.0, "pageins_s": 2.5, "swapins_s": 1.0}
    assert sv.window_metrics(ring, 500, 600) is None
    assert sv.window_metrics(ring, 200, 200)["compress_s"] is None   # one reading is no rate
    back = ring_of([(0, 1.0, 100, 0, 0), (20, 1.0, 50, 0, 0)])   # a counter that went back (a reboot) is no rate
    assert sv.window_metrics(back, 0, 20)["compress_s"] is None
    unread = ring_of([(0, None, None, None, None), (20, None, None, None, None)])
    assert sv.window_metrics(unread, 0, 20) == {"n": 2, "span_s": 20, "load": None, "compress_s": None, "pageins_s": None, "swapins_s": None}


def test_a_pair_of_readings_across_a_sleep_counts_toward_no_rate():
    ring = ring_of([(0, 1.0, 0, 0, 0), (20, 1.0, 2000, 0, 0), (400, 1.0, 10 ** 9, 0, 0)])   # 380 s with no reading: a sleep or a stall, inside the window
    m = sv.window_metrics(ring, 0, 400)
    assert m["n"] == 3 and m["compress_s"] == 100.0   # only the 20 s pair counts, never the jump over the gap


def test_the_window_before_a_freeze_is_its_own_length_within_two_to_thirty_minutes():
    assert sv.window_for(600) == 600 and sv.window_for(30) == 120 and sv.window_for(86400) == 1800 and sv.window_for(None) == 600 and sv.window_for(float("nan")) == 600


# ---- a freeze records what it takes off the CPU, its resume writes the result ----------------------------------------------------------------
def test_a_freeze_and_its_resume_write_a_freeze_result_with_the_before_and_during_windows(world):
    before = [(T0 - 600 + i * 20, 4.0, 1000 + 100 * i, 50 * i, 0) for i in range(30)]   # 10 minutes of load 4: compressor 5 pages/s, pageins 2.5/s
    sv.write_hist(world.state, ring_of(before))
    e = world.freeze(minutes=10, by="dialog")
    assert e["measure"]["cores"] == 1.5 and e["measure"]["rss_mb"] == 300 and e["measure"]["w"] == 600   # root + 2 helpers, 0.5 cores and 100 MB each (FakeOps)
    assert e["measure"]["sys"]["load"] == 4.0 and e["measure"]["sys"]["compress_s"] == 5.0 and e["measure"]["sys"]["n"] == 30
    assert world.entries()[0]["measure"]["cores"] == 1.5   # persisted: a resume from another process can still judge it
    during = [(T0 + i * 20, 2.0, 3900 + 20 * (i + 1), 1450 + 10 * (i + 1), 0) for i in range(32)]   # compressor 1 pages/s, pageins 0.5/s, load 2
    sv.write_hist(world.state, ring_of(before + during))
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 640, by="sampler")
    assert r["resumed"] == [e["id"]]
    res = [x for x in world.events() if x["event"] == "freeze-result"]
    assert len(res) == 1
    x = res[0]
    assert (x["entry"], x["by"], x["froze_by"], x["mode"], x["held_s"], x["window_s"]) == (e["id"], "sampler", "dialog", "timed", 640, 600)
    assert (x["cores_before"], x["cores_freed_est"], x["rss_mb"], x["rss_freed_mb"], x["bundle_id"]) == (1.5, 1.5, 300, 0, "com.example.fake")   # SIGSTOP frees CPU, never RSS
    assert x["before"]["load"] == 4.0 and x["during"]["load"] == 2.0
    assert x["delta"] == {"load": -2.0, "compress_s": -4.0, "pageins_s": -2.0, "swapins_s": 0.0}


def test_a_freeze_without_any_history_still_records_cores_and_a_result_without_pressure_numbers(world):
    e = world.freeze(minutes=5)
    assert e["measure"]["sys"] is None and e["measure"]["cores"] == 1.5
    gf.thaw_all(world.state, ops=world.ops, now=T0 + 400)
    x = [y for y in world.events() if y["event"] == "freeze-result"][0]
    assert x["before"] is None and x["during"] is None and x["delta"] == {} and x["cores_before"] == 1.5


def test_a_failure_to_measure_never_undoes_a_freeze_or_fails_a_resume(world, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(sv, "before_measure", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        e = world.freeze(minutes=5)
        assert "measure" not in e and e["state"] == "frozen" and world.ops.sent
        assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 400) == ([e["id"]], [])
        assert not [y for y in world.events() if y["event"] == "freeze-result"]   # an entry without a measure resumes silently
    e = world.freeze(minutes=5)
    assert "measure" in e
    with monkeypatch.context() as m:
        m.setattr(sv, "result", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 400) == ([e["id"]], [])   # the resume went through, the result did not
    assert world.entries() == [] and world.ops.procs[5000]["state"] == "S"


def test_a_hand_edited_measure_is_dropped_but_the_entry_survives(world):
    e = world.freeze(minutes=5)
    for bad in ({"w": float("nan"), "cores": 1, "rss_mb": 1}, {"w": 60, "cores": "1", "rss_mb": 1}, {"w": 60}, "x", [1]):
        n = gf.norm_entry(dict(e, measure=bad))
        assert n and "measure" not in n
    ok = gf.norm_entry(dict(e, measure={"w": 99999, "cores": 1.234, "rss_mb": 7, "sys": {"n": 3, "load": float("inf"), "compress_s": 4, "junk": 1}}))["measure"]
    assert ok["w"] == 1800 and ok["cores"] == 1.23 and ok["sys"]["load"] is None and ok["sys"]["compress_s"] == 4 and "junk" not in ok["sys"]


def test_the_history_file_is_read_through_the_directory_fd_and_a_symlink_is_no_history(world):
    gdir = world.state / "gui-hog"
    gdir.mkdir(mode=0o700, exist_ok=True)
    real = world.tmp / "elsewhere.json"
    real.write_text(json.dumps({"v": 1, "rows": [[T0 - 10, 99.0, 1, 1, 1], [T0 - 5, 99.0, 2, 2, 2]]}))
    os.symlink(real, gdir / sv.HIST_FILE)
    assert sv.read_hist(world.state) == []
    e = world.freeze(minutes=5)
    assert e["measure"]["sys"] is None   # the freeze did not follow the link either


# ---- suggest ----------------------------------------------------------------------------------------------------------------------------------
def fr(bid, cores, held_s=600, rss=500, load=None, name=None):
    return {"event": "freeze-result", "bundle_id": bid, "app": {"name": name or bid}, "cores_before": cores, "held_s": held_s, "rss_mb": rss,
            "delta": {} if load is None else {"load": load}}


def show(bid, cores, hb=False, name=None):
    return {"event": "would-show", "apps": [{"name": name or bid, "bundle_id": bid, "cores_5m": cores, "rss_mb": 300, "hosts_build": hb}]}


def test_suggest_proposes_large_savings_for_always_and_negligible_savings_for_never_auto():
    c = shipped()
    results = [fr("com.example.big", x, load=-0.3) for x in (1.2, 0.9, 1.6)] + [fr("com.example.tiny", 0.01) for _ in range(3)] + [fr("com.example.few", 2.0)] * 2
    s = sv.suggest(c, results, [])
    assert [p["bundle_id"] for p in s["always"]] == ["com.example.big"] and [p["bundle_id"] for p in s["never_auto"]] == ["com.example.tiny"]
    ev = " ".join(s["always"][0]["evidence"])
    assert "3 freezes" in ev and "median 1.20" in ev and "a freeze frees none of it" in ev and "load during minus before: median -0.30" in ev
    assert "negligible" in s["never_auto"][0]["why"] and "com.example.few" not in json.dumps([s["always"], s["never_auto"]])   # two events are not enough


def test_suggest_uses_dialog_sightings_for_an_app_that_was_never_frozen_and_ignores_short_freezes():
    c = shipped()
    s = sv.suggest(c, [fr("com.example.q", 5.0, held_s=20)] * 5, [show("com.example.chat", 0.02)] * 4 + [show("com.example.heavy", 2.0)] * 3)
    assert [p["bundle_id"] for p in s["never_auto"]] == ["com.example.chat"] and "dialog sightings" in s["never_auto"][0]["why"]
    assert [p["bundle_id"] for p in s["always"]] == ["com.example.heavy"]
    assert "com.example.q" not in s["apps"]   # a freeze held under a minute says nothing


def test_suggest_never_proposes_a_dependency_a_protected_app_or_a_build_host_for_always():
    c = shipped()
    big = [fr(b, 2.0) for _ in range(4) for b in (BEEPER, "com.mitchellh.ghostty", "com.example.ide")]
    s = sv.suggest(c, big, [show("com.example.ide", 2.0, hb=True)] * 3)
    assert s["always"] == []   # Beeper depends, Ghostty is protected, the IDE hosted a build
    assert "com.mitchellh.ghostty" not in json.dumps(s["never_auto"])
    c["freeze"]["depends"]["com.example.ide"] = ["its language server answers the agents"]
    s = sv.suggest(c, [], [])
    assert [p["bundle_id"] for p in s["never_auto"]] == ["com.example.ide"] and s["never_auto"][0]["evidence"] == ["its language server answers the agents"]


def test_suggest_never_proposes_always_for_an_app_with_a_dependency_note_that_is_not_on_skip():
    c = shipped()
    c["freeze"]["depends"]["com.example.dep"] = ["its server answers the agents"]
    s = sv.suggest(c, [fr("com.example.dep", 3.0) for _ in range(4)], [])
    assert s["always"] == []   # large savings, but something depends on it
    assert [p["bundle_id"] for p in s["never_auto"]] == ["com.example.dep"]


def test_suggest_reports_conflicts_and_keeps_listed_apps_quiet():
    c = shipped()
    c["freeze"]["auto"]["always"] = [BEEPER, "com.mitchellh.ghostty", "com.example.x"]
    c["freeze"]["depends"]["com.example.x"] = ["a thing"]
    s = sv.suggest(c, [], [])
    notes = " ".join(s["notes"])
    assert "com.automattic.beeper.desktop is on the always-freeze list but also on the never-auto list" in notes
    assert "com.mitchellh.ghostty is protected" in notes and "com.example.x is on the always-freeze list but something depends on it (a thing)" in notes
    assert [p["bundle_id"] for p in s["never_auto"]] == ["com.example.x"]   # Beeper and CodexBar are on skip already: not proposed again


def test_suggest_lines_say_the_source_and_that_nothing_was_edited():
    text = "\n".join(sv.suggest_lines(sv.suggest(shipped(), [fr("com.example.big", 1.0)] * 3, []), 30))
    assert "to adopt, add \"com.example.big\" to always in config/gui-hog.toml" in text and "Nothing was edited" in text and "frees CPU, not memory" in text


def test_the_suggest_command_prints_and_edits_nothing(tmp_path):
    state = tmp_path / "state"
    gdir = state / "gui-hog"
    gdir.mkdir(parents=True, mode=0o700)
    with open(gdir / "events.jsonl", "w") as f:
        for _ in range(3):
            f.write(json.dumps({"t": gh._iso(__import__("time").time() - 3600), "event": "freeze-result", "bundle_id": "com.example.big", "app": {"name": "Big"},
                                "cores_before": 1.4, "held_s": 600, "rss_mb": 900, "delta": {}}) + "\n")
    def snap():
        return sorted((p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in list(state.rglob("*")) + [REPO / "config" / "gui-hog.toml"] if p.is_file())
    before = snap()
    env = dict(os.environ, LW_STATE_DIR=str(state), LW_GUI_HOG_LOCAL=str(NOLOCAL))
    r = subprocess.run([sys.executable, str(REPO / "bin" / "gui-hog"), "suggest", "--json"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert [p["bundle_id"] for p in json.loads(r.stdout)["always"]] == ["com.example.big"]
    r = subprocess.run([sys.executable, str(REPO / "bin" / "gui-hog"), "suggest", "--days", "1"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "Nothing was edited" in r.stdout and "com.example.big" in r.stdout
    assert snap() == before


# ---- the always-freeze list (Q3) ----------------------------------------------------------------------------------------------------------------
def test_the_shipped_always_list_has_no_protected_or_never_auto_entry_and_every_skip_entry_has_a_dependency_note():
    c = shipped()
    assert c["freeze"]["auto"]["always"] == [] and gh.always_problems(c) == []
    assert all(b in c["freeze"]["depends"] for b in c["freeze"]["auto"]["skip"])   # the two known cases are written down: Beeper's MCP port, the quota feeder
    assert c["suggest"] == {"min_events": 3, "negligible_cores": 0.10, "large_cores": 0.50, "days": 30}


def test_skip_wins_and_a_protected_app_is_ignored_on_the_always_list():
    c = shipped()   # the shipped file carries the protected list (auto_cfg reads none)
    c["freeze"]["auto"].update(order=[], skip=[BEEPER], always=[BEEPER, "com.mitchellh.ghostty", "com.jetbrains.intellij", OTHER])
    assert gh.always_apps(c) == frozenset({OTHER.casefold()})
    assert sorted(gh.always_problems(c)) == [(BEEPER, "on the never-auto list (skip wins)"), ("com.jetbrains.intellij", "protected"),
                                             ("com.mitchellh.ghostty", "protected")]


def test_the_always_list_is_off_when_the_auto_freeze_or_freeze_is_off(monkeypatch):
    c = auto_cfg(order=())
    c["freeze"]["auto"]["always"] = [OTHER]
    assert gh.always_apps(c) == frozenset({OTHER.casefold()})
    monkeypatch.setenv("LW_GUI_HOG_AUTO", "0")
    assert gh.always_apps(c) == frozenset()
    monkeypatch.delenv("LW_GUI_HOG_AUTO")
    c["freeze"]["auto"]["enabled"] = False
    assert gh.always_apps(c) == frozenset()
    c["freeze"]["auto"]["enabled"], c["freeze"]["enabled"] = True, False
    assert gh.always_apps(c) == frozenset()   # the apps become ordinary dialog rows again: switching auto-freeze off never hides one


def test_the_overlay_adds_to_the_always_list_and_to_depends_but_never_removes(tmp_path):
    base = tmp_path / "shipped.toml"
    base.write_text('[freeze.auto]\nalways = ["com.example.a"]\n[freeze.depends]\n"com.example.a" = ["one"]\n')
    over = tmp_path / "gui-hog.toml"
    over.write_text('[freeze.auto]\nalways = ["com.example.b", "com.EXAMPLE.a", 7, ""]\n[freeze.depends]\n"com.example.a" = ["two", "one", 3]\n')
    c = gh.load_config(path=base, local=over)
    assert c["freeze"]["auto"]["always"] == ["com.example.a", "com.example.b"] and c["freeze"]["depends"]["com.example.a"] == ["one", "two"]


def test_an_always_app_gets_no_dialog_and_no_row_but_an_app_hosting_a_build_does():
    c = auto_cfg(order=())
    c["freeze"]["auto"]["always"] = [OTHER]
    apps = [{"id": "400", "name": "Other", "bundle_id": OTHER, "cores_5m": 3.0, "rss_mb": 500, "protected": None, "hosts_build": False, "excluded": None,
             "present": True, "cpu_now": 3.0, "bundle_path": "/x"}]
    hold = held()
    d = gh.should_show(hold, apps, T0, None, None, c)
    assert not d["show"] and d["reason"] == "below-threshold" and d["sum_cores"] == 0.0
    c["freeze"]["auto"]["enabled"] = False
    assert gh.should_show(hold, apps, T0, None, None, c)["show"]   # auto-freeze off: an ordinary row again
    c["freeze"]["auto"]["enabled"] = True
    apps[0]["hosts_build"] = True
    assert gh.should_show(hold, apps, T0, None, None, c)["show"]   # it cannot be frozen, so the operator is asked
    snap = gh.build_snapshot(apps, hold, T0, c)
    assert [r["name"] for r in snap["rows"]] == ["Other"]
    apps[0]["hosts_build"] = False
    assert gh.build_snapshot(apps, hold, T0, c)["rows"] == []
    assert gh.would_show_line({"reason": "show", "holds": [], "sum_cores": 0, "sum_rss_mb": 0}, apps, T0, 1.0, c, 1)["apps"] == []


def test_the_sampler_freezes_an_always_app_before_the_order(w):
    c = auto_cfg(order=(GROK,), always=[OTHER])
    r = w.step(c)
    assert r["bundle_id"] == OTHER and r.get("entry") and w.stopped() == [400]   # the always list first, one app per tick
    assert w.step(c, now=T0 + 20)["bundle_id"] == GROK


def test_never_auto_wins_over_the_always_list_in_the_sampler(w):
    c = auto_cfg(order=(), skip=(OTHER,), always=[OTHER])
    assert w.step(c) is None and w.stopped() == []


def test_an_always_only_config_still_runs_the_auto_step(w):
    assert w.step(auto_cfg(order=(), always=[OTHER]))["bundle_id"] == OTHER


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)
