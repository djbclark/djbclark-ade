"""The auto-freeze list and the keep-running rule (docs/gui-hog-dialog.md O6, operator ruling 2026-11-21, B6 amended).

Linux CI runs all of it: a fake process table (`FakeOps`, as test_gui_hog_freeze.py) and a temp state directory; nothing signals a real process.
"""
import json
import os
import plistlib
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
import gui_hog_freeze as gf  # noqa: E402
from test_gui_hog_freeze import ME, T0, FakeOps, proc  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NOLOCAL = Path("/nonexistent")
CODEXBAR, BEEPER, GROK, OTHER, CHROME = ("com.steipete.codexbar", "com.automattic.beeper.desktop", "com.anysphere.sand", "com.example.other",
                                         "com.google.Chrome")


def shipped():
    return gh.load_config(local=NOLOCAL)


def make_app(root, name, bid):
    app = root / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Helpers").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bid}))
    return app


def held(age=400, refused=("pageins",)):
    return [{"pid": 4242, "start": "s", "caller": "bg", "refused_since": T0 - age, "refused": list(refused), "updated": T0}]


class World:
    """CodexBar (root 100 + CodexBarCLI 101), Beeper (200), Grok Bot (300), an unlisted app (400) and a Chrome-like app (500) with an
    out-of-bundle native-messaging host (501) under launchd (pid 1)."""

    def __init__(self, tmp):
        self.tmp, self.state = tmp, tmp / "state"
        self.state.mkdir()
        self.apps = {}
        procs = {1: proc(0, "/sbin/launchd", uid=0, pid=1)}
        for pid, name, bid in ((100, "CodexBar", CODEXBAR), (200, "Beeper", BEEPER), (300, "Grok Bot", GROK), (400, "Other", OTHER), (500, "Chrome", CHROME)):
            app = make_app(tmp / "Apps", name, bid)
            self.apps[bid] = app
            procs[pid] = proc(1, app / "Contents" / "MacOS" / name.replace(" ", ""), pid=pid)
        self.cli = self.apps[CODEXBAR] / "Contents" / "Helpers" / "CodexBarCLI"
        procs[101] = proc(100, self.cli, pid=101)
        self.nm = tmp / "outside" / "Host.app" / "Contents" / "MacOS" / "nm-host"   # a rule must name an executable inside an .app bundle (L4)
        self.nm.parent.mkdir(parents=True)
        procs[501] = proc(500, self.nm, pid=501)
        self.ops = FakeOps(procs)

    def lsapps(self):
        out = []
        for pid in (100, 200, 300, 400, 500):
            exe = Path(self.ops.procs[pid]["exe"])
            app = exe.parents[2]
            out.append({"name": app.stem, "bundle_id": plistlib.loads((app / "Contents" / "Info.plist").read_bytes())["CFBundleIdentifier"],
                        "bundle_path": str(app), "exe": str(exe), "pid": pid, "type": "Foreground"})
        return out

    def group(self, cfg):
        table, rss, ttys, _s = self.ops.table()
        return {a["bundle_id"]: a for a in gh.group_apps(table, rss, ttys, self.lsapps(), exe_of=self.ops.exe, my_uid=ME, agent_clis=(), cfg=cfg)}

    def step(self, cfg, now=T0, held_=None, gh_state=None, dry=False, st=None):
        gh_state = st if st is not None else gh_state
        self.gh_state = gh_state if gh_state is not None else getattr(self, "gh_state", {})
        apps = list(self.group(cfg).values())
        return gf.auto_freeze_step(self.gh_state, self.state, apps, held() if held_ is None else held_, now, cfg, my_uid=ME, ops=self.ops, dry=dry)

    def stopped(self):
        return sorted(p for p, d in self.ops.procs.items() if d["state"] == "T")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.fixture(autouse=True)
def _sampler_is_loaded(monkeypatch):
    """The auto step now checks launchd's job (M1); the tests that need it unloaded say so."""
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: True)


def auto_cfg(order=(CODEXBAR, BEEPER, GROK), keep=True, skip=(), **auto):
    c = gh.load_config(path=NOLOCAL, local=NOLOCAL)
    c["freeze"]["auto"].update(enabled=True, order=list(order), skip=list(skip), **auto)
    if keep:
        c["freeze"]["keep_running"] = {CODEXBAR: ["Contents/Helpers/CodexBarCLI"]}
    return c


# ---- the shipped config and the overlay (1) -------------------------------------------------------------------------------------------------
def test_the_shipped_config_lists_grok_bot_and_skips_beeper_and_codexbar():
    c = shipped()
    assert c["freeze"]["auto"]["order"] == [GROK] and c["freeze"]["auto"]["enabled"] is True
    assert c["freeze"]["auto"]["skip"] == [BEEPER, CODEXBAR]   # operator rulings M3 and M2, 2026-11-21 (P7)
    assert c["freeze"]["keep_running"][CODEXBAR] == ["Contents/Helpers/CodexBarCLI"]
    assert c["freeze"]["enabled"] is True and c["freeze"]["default_minutes"] == 10   # the nested tables did not wipe the plain keys


def test_chrome_is_not_auto_frozen_but_its_native_messaging_hosts_are_kept_running():
    c = shipped()
    assert CHROME not in c["freeze"]["auto"]["order"]
    rules = c["freeze"]["keep_running"][CHROME]
    assert any(r.endswith("1Password-BrowserSupport") for r in rules) and any(r.endswith("/chrome-use") for r in rules)


def test_the_user_overlay_overrides_the_order_and_adds_keep_rules(tmp_path):
    over = tmp_path / "gui-hog.toml"
    over.write_text('[freeze.auto]\norder = ["com.example.x", "", 5]\nmin_cores = 0.2\n[freeze.keep_running]\n"com.steipete.codexbar" = ["Contents/Helpers/Extra"]\n'
                    '"com.example.x" = ["Contents/Helpers/H"]\n')
    c = gh.load_config(local=over)
    assert c["freeze"]["auto"]["order"] == ["com.example.x"] and c["freeze"]["auto"]["min_cores"] == 0.2
    assert c["freeze"]["keep_running"][CODEXBAR] == ["Contents/Helpers/CodexBarCLI", "Contents/Helpers/Extra"]   # added to, never replaced
    assert c["freeze"]["keep_running"]["com.example.x"] == ["Contents/Helpers/H"]


def test_the_overlay_cannot_turn_freeze_off_or_change_its_limits_and_a_broken_one_is_ignored(tmp_path):
    over = tmp_path / "gui-hog.toml"
    over.write_text("[freeze]\nenabled = false\nmax_minutes = 99999\npasses = 99\n[freeze.auto]\nenabled = false\n")
    c = gh.load_config(local=over)
    assert c["freeze"]["enabled"] is True and c["freeze"]["max_minutes"] == 1440 and c["freeze"]["passes"] == 3
    assert c["freeze"]["auto"]["enabled"] is False   # the operator may switch the auto list off (the overlay is theirs)
    over.write_text("this is [not toml")
    assert gh.load_config(local=over)["freeze"]["auto"]["order"] == [GROK]


def test_the_overlay_cannot_remove_a_protected_entry(tmp_path):
    over = tmp_path / "gui-hog.toml"
    over.write_text('[protected]\nbundle_ids = ["com.example.extra"]\n')
    c = gh.load_config(local=over)
    assert "sh.paseo.desktop" in c["protected"]["bundle_ids"] and "com.example.extra" in c["protected"]["bundle_ids"]


# ---- the keep-running rule (2) ----------------------------------------------------------------------------------------------------------------
def test_group_apps_leaves_the_kept_helper_out_of_the_members_a_freeze_stops(w):
    a = w.group(auto_cfg())[CODEXBAR]
    assert a["member_pids"] == [100] and a["kept_pids"] == [101] and a["kept_names"] == ["CodexBarCLI"] and a["members"] == 2
    assert a["kept_cores"] == pytest.approx(0.5) and not a["hosts_build"]
    b = w.group(auto_cfg(keep=False))[CODEXBAR]
    assert b["member_pids"] == [100, 101] and b["kept_pids"] == [] and b["kept_names"] == []   # without the rule both would be stopped (today's bug)


def test_a_descendant_of_a_kept_process_is_kept_too_and_the_root_never_is(w):
    w.ops.procs[102] = proc(101, w.cli.parent / "Sub", pid=102)
    cfg = auto_cfg()
    a = w.group(cfg)[CODEXBAR]
    assert a["kept_pids"] == [101, 102] and a["member_pids"] == [100]
    cfg["freeze"]["keep_running"][CODEXBAR].append("Contents/MacOS/CodexBar")   # a rule that matches the main binary keeps nothing: the root stays frozen
    assert 100 in w.group(cfg)[CODEXBAR]["member_pids"] and 100 not in w.group(cfg)[CODEXBAR]["kept_pids"]


def test_the_rule_matches_the_kernel_executable_never_argv_and_ignores_dotdot(w):
    w.ops.procs[101]["exe"] = str(w.tmp / "elsewhere" / "CodexBarCLI")   # same name, outside the bundle; its argv still claims the helper path
    w.ops.procs[101]["cmd"] = str(w.cli)
    a = w.group(auto_cfg())[CODEXBAR]
    assert a["kept_pids"] == [] and a["hosts_build"]   # not kept (the kernel path is outside the bundle: that is a build)
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"][CODEXBAR] = ["../CodexBar.app/Contents/Helpers/CodexBarCLI", "Contents/Helpers/../MacOS/CodexBar"]
    assert gh.keep_rules(cfg, CODEXBAR) == []


def test_the_rule_matches_the_bundle_id_case_insensitively(w):
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"] = {CODEXBAR.upper(): ["Contents/Helpers/CodexBarCLI"]}
    assert w.group(cfg)[CODEXBAR]["kept_pids"] == [101]


def test_a_freeze_never_signals_the_kept_helper_and_the_entry_records_it(w):
    cfg = auto_cfg()
    e = gf.freeze(w.state, 100, start="start-100", ops=w.ops, cfg=cfg, now=T0, check_sampler=False, agent_clis=(), minutes=10, by="dialog")
    assert e["kept"] == ["CodexBarCLI"] and w.stopped() == [100] and w.ops.sent_to(101) == []   # manual (dialog) freezes keep it too
    assert json.loads((w.state / "gui-hog" / "frozen.json").read_text())["entries"][0]["kept"] == ["CodexBarCLI"]
    ev = [json.loads(x) for x in (w.state / "gui-hog" / "events.jsonl").read_text().splitlines()]
    assert ev[0]["event"] == "freeze" and ev[0]["kept"] == ["CodexBarCLI"]
    view = gf.frozen_view(w.state, ops=w.ops, now=T0)["entries"][0]
    assert view["kept"] == ["CodexBarCLI"] and view["members"] == 1   # the dialog reads `kept` from here
    assert gf.thaw_due(w.state, ops=w.ops, now=T0 + 601)["resumed"] == [e["id"]]
    assert w.ops.sent_to(101) == [] and w.stopped() == []


def test_without_the_rule_the_helper_is_stopped_with_the_app(w):
    gf.freeze(w.state, 100, start="start-100", ops=w.ops, cfg=auto_cfg(keep=False), now=T0, check_sampler=False, agent_clis=(), minutes=10)
    assert w.stopped() == [100, 101]


def test_a_kept_entry_field_is_validated_data_and_never_signals(w):
    e = {"id": "f-1", "state": "frozen", "app": {}, "root": {"pid": 100, "start": "s", "uid": ME, "exe": "/x"}, "members": [], "mode": "indefinite",
         "frozen_at": T0, "kept": ["ok", 7, "x‮y", *["n"] * 40]}
    n = gf.norm_entry(e)
    assert n["kept"][0] == "ok" and "xy" in n["kept"] and len(n["kept"]) <= 20
    assert "kept" not in gf.norm_entry({**e, "kept": "not-a-list"}) and "kept" not in gf.norm_entry({**e, "kept": [1, 2]})


# ---- Chrome (3) ---------------------------------------------------------------------------------------------------------------------------------
def test_an_out_of_bundle_native_messaging_host_makes_chrome_host_a_build_unless_a_rule_keeps_it(w):
    cfg = auto_cfg()
    assert w.group(cfg)[CHROME]["hosts_build"] is True   # today's `no actions`
    cfg["freeze"]["keep_running"][CHROME] = [str(w.nm)]
    a = w.group(cfg)[CHROME]
    assert not a["hosts_build"] and a["kept_pids"] == [501] and a["member_pids"] == [500]
    cfg["freeze"]["keep_running"][CHROME] = [str(w.nm.parent / "other-host")]   # another path does not exempt it
    assert w.group(cfg)[CHROME]["hosts_build"] is True


def test_the_home_directory_form_of_a_rule_expands(w, monkeypatch):
    monkeypatch.setenv("HOME", str(w.tmp))
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"][CHROME] = ["~/outside/Host.app/Contents/MacOS/nm-host"]
    assert not w.group(cfg)[CHROME]["hosts_build"]


@pytest.mark.parametrize("how", ["tty", "shell-child", "held"])
def test_a_kept_path_does_not_hide_a_real_build(w, how):
    """The exemption lifts only the out-of-bundle rule: a pty, a shell or a held caller on that very process is still a build."""
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"][CHROME] = [str(w.nm)]
    table, rss, ttys, _s = w.ops.table()
    held_pids = ()
    if how == "tty":
        ttys = set(ttys) | {"501"}
    elif how == "held":
        held_pids = [501]
    else:
        w.ops.procs[502] = proc(501, "/bin/zsh", pid=502)
        table, rss, ttys, _s = w.ops.table()
    a = {x["bundle_id"]: x for x in gh.group_apps(table, rss, ttys, w.lsapps(), exe_of=w.ops.exe, my_uid=ME, held_pids=held_pids, agent_clis=(), cfg=cfg)}[CHROME]
    assert a["hosts_build"] is True


def test_chrome_is_freezable_once_its_hosts_are_kept_and_the_hosts_keep_running(w):
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"][CHROME] = [str(w.nm)]
    e = gf.freeze(w.state, 500, start="start-500", ops=w.ops, cfg=cfg, now=T0, check_sampler=False, agent_clis=(), minutes=10, by="dialog")
    assert w.stopped() == [500] and w.ops.sent_to(501) == [] and e["kept"] == ["nm-host"]
    with pytest.raises(gf.Refusal) as r:   # and without the rule the vet still refuses with exit 5 (the old behaviour)
        gf.freeze(w.state, 500, start="start-500", ops=FakeOps({**w.ops.procs, 500: {**w.ops.procs[500], "state": "S"}}), cfg=auto_cfg(), now=T0,
                  check_sampler=False, agent_clis=(), minutes=10)
    assert r.value.code in (gf.HOSTS_BUILD, gf.REFUSED)


# ---- the auto-freeze step (1) ---------------------------------------------------------------------------------------------------------------
def test_a_held_build_freezes_the_first_listed_app_by_auto_one_per_tick(w):
    cfg = auto_cfg()
    r = w.step(cfg)
    assert r["bundle_id"] == CODEXBAR and r["entry"] and r["kept"] == ["CodexBarCLI"] and w.stopped() == [100] and w.ops.sent_to(101) == []
    r2 = w.step(cfg, now=T0 + 20)
    assert r2["bundle_id"] == BEEPER and w.stopped() == [100, 200]   # the next listed app, one per tick
    r3 = w.step(cfg, now=T0 + 40)
    assert r3["bundle_id"] == GROK
    assert w.step(cfg, now=T0 + 60) is None   # list exhausted: nothing else is touched (the unlisted app and Chrome stay running)
    assert w.stopped() == [100, 200, 300]
    ev = [json.loads(x) for x in (w.state / "gui-hog" / "events.jsonl").read_text().splitlines()]
    assert [(x["event"], x["by"], x["app"]["bundle_id"]) for x in ev] == [("freeze", "auto", CODEXBAR), ("freeze", "auto", BEEPER), ("freeze", "auto", GROK)]
    assert all(e["mode"] == "timed" and e["by"] == "auto" for e in json.loads((w.state / "gui-hog" / "frozen.json").read_text())["entries"])


def test_the_order_is_preferred_first_to_last(w):
    cfg = auto_cfg(order=(GROK, CODEXBAR))
    assert w.step(cfg)["bundle_id"] == GROK and w.step(cfg, now=T0 + 20)["bundle_id"] == CODEXBAR


def test_the_freeze_is_timed_with_the_configured_minutes(w):
    r = w.step(auto_cfg(minutes=3))
    assert r["thaw_at"] == T0 + 180
    (w.tmp / "second").mkdir()
    w2 = World(w.tmp / "second")
    assert w2.step(auto_cfg(), now=T0 + 5, gh_state={})["thaw_at"] == T0 + 5 + 600   # default: [freeze] default_minutes


def test_nothing_is_frozen_without_a_hold_that_desktop_apps_can_relieve(w):
    cfg = auto_cfg()
    assert w.step(cfg, held_=[]) is None   # no build is waiting
    assert w.step(cfg, held_=held(age=60)) is None   # under hold_s (180)
    assert w.step(cfg, held_=held(refused=("agent_cap",))) is None   # a gate quitting an app cannot relieve
    assert w.stopped() == [] and not (w.state / "gui-hog" / "frozen.json").exists()
    assert w.step(cfg, held_=held(refused=("agent_cap", "load")))["bundle_id"] == CODEXBAR


def test_the_list_stops_when_the_hold_clears(w):
    cfg = auto_cfg()
    assert w.step(cfg)["bundle_id"] == CODEXBAR
    assert w.step(cfg, now=T0 + 20, held_=[]) is None and w.stopped() == [100]   # the build was admitted: Beeper is left alone


def test_a_protected_app_on_the_list_is_never_auto_frozen(w):
    cfg = auto_cfg()
    cfg["protected"]["bundle_ids"].append(CODEXBAR)
    r = w.step(cfg)
    assert r["bundle_id"] == BEEPER and w.stopped() == [200]
    for why in [why for _a, why in gf.auto_candidates(list(w.group(cfg).values()), cfg, {}, T0)]:
        assert why in ("", "protected")


def test_the_hard_floor_beats_the_list(w):
    cfg = auto_cfg(order=("com.apple.finder",))
    w.apps["com.apple.finder"] = make_app(w.tmp / "Apps", "Finder", "com.apple.finder")
    exe = w.apps["com.apple.finder"] / "Contents" / "MacOS" / "Finder"
    w.ops.procs[600] = proc(1, exe, pid=600)
    apps = [{"name": "Finder", "bundle_id": "com.apple.finder", "bundle_path": str(w.apps["com.apple.finder"]), "exe": str(exe), "pid": 600, "type": "Foreground"}]
    table, rss, ttys, _s = w.ops.table()
    found = gh.group_apps(table, rss, ttys, apps, exe_of=w.ops.exe, my_uid=ME, agent_clis=(), cfg=cfg)
    assert found[0]["protected"]
    assert gf.auto_freeze_step({}, w.state, found, held(), T0, cfg, my_uid=ME, ops=w.ops) is None and w.stopped() == []


def test_an_app_that_hosts_a_build_or_belongs_to_one_is_skipped(w):
    cfg = auto_cfg()
    w.ops.procs[102] = proc(100, "/bin/zsh", pid=102)   # a shell inside CodexBar: it hosts a terminal
    r = w.step(cfg)
    assert r["bundle_id"] == BEEPER and 100 not in w.stopped()
    assert gf.auto_candidates(list(w.group(cfg).values()), cfg, {}, T0)[0][1] == "hosts-build"


def test_an_idle_app_is_skipped_because_a_freeze_would_free_nothing(w):
    cfg = auto_cfg(min_cores=0.6)   # every fake process uses 0.5 cores: CodexBar's freeable cores are 0.5 (its server's 0.5 are kept), the others 0.5
    assert w.step(cfg) is None and w.stopped() == []
    cfg2 = auto_cfg(min_cores=0.5)
    assert w.step(cfg2)["bundle_id"] == CODEXBAR


def test_an_app_that_is_not_running_is_skipped(w):
    w.ops.procs[100]["state"] = "gone"
    w.ops.procs[101]["state"] = "gone"
    assert w.step(auto_cfg())["bundle_id"] == BEEPER


def test_an_operators_resume_sticks_for_refreeze_s(w):
    cfg = auto_cfg(order=(CODEXBAR,), refreeze_s=3600)
    e = w.step(cfg)
    assert gf.thaw_all(w.state, ops=w.ops, by="dialog", entry_id=e["entry"])   # the operator pressed Resume
    assert w.step(cfg, now=T0 + 300) is None and w.stopped() == []   # still held, but not frozen again
    assert w.step(cfg, now=T0 + 3601)["bundle_id"] == CODEXBAR and w.stopped() == [100]


def test_a_refused_auto_freeze_waits_before_the_retry_and_never_raises(w):
    cfg = auto_cfg(order=(CODEXBAR, BEEPER))

    def boom(*a, **k):
        raise gf.Refusal(gf.HOSTS_BUILD, "a terminal appeared")
    st = {}
    apps = list(w.group(cfg).values())
    r = gf.auto_freeze_step(st, w.state, apps, held(), T0, cfg, my_uid=ME, ops=w.ops, freeze_fn=boom)
    assert r["bundle_id"] == CODEXBAR and r["refused"].startswith("5:") and w.stopped() == []
    cand = dict((a.get("bundle_id"), why) for a, why in gf.auto_candidates(apps, cfg, st["auto"], T0 + 30))
    assert cand[CODEXBAR] == "retry-wait" and cand[BEEPER] == ""
    assert dict((a.get("bundle_id"), why) for a, why in gf.auto_candidates(apps, cfg, st["auto"], T0 + gf.AUTO_RETRY_S + 1))[CODEXBAR] == ""


def test_the_auto_list_can_be_switched_off(w):
    for mutate in (lambda c: c["freeze"]["auto"].update(enabled=False), lambda c: c["freeze"].update(enabled=False), lambda c: c["freeze"]["auto"].update(order=[])):
        c = auto_cfg()
        mutate(c)
        assert w.step(c) is None
    assert w.stopped() == []


def test_a_dry_run_names_the_app_and_signals_nothing(w):
    r = w.step(auto_cfg(), dry=True)
    assert r == {"app": "CodexBar", "bundle_id": CODEXBAR, "dry": True} and w.ops.sent == [] and not (w.state / "gui-hog" / "frozen.json").exists()


def test_the_unlisted_app_is_never_auto_frozen_whatever_it_uses(w):
    cfg = auto_cfg(order=(CODEXBAR,))
    w.ops.procs[400]["cmd"] = "busy"
    assert w.step(cfg)["bundle_id"] == CODEXBAR
    assert w.step(cfg, now=T0 + 20) is None and 400 not in w.stopped()


# ---- the sampler's tick (1) -----------------------------------------------------------------------------------------------------------------------
def _tick(w, monkeypatch, **kw):
    calls = []
    monkeypatch.setattr(gf, "auto_freeze_step", lambda *a, **k: calls.append((a, k)) or {"app": "X", "dry": k.get("dry")})
    table, rss, ttys, _s = w.ops.table()
    out = []
    gh.tick({}, T0, table, rss, ttys, state_dir=w.state, my_uid=ME, cfg=auto_cfg(), lsapps=w.lsapps(), exe_of=w.ops.exe, out=out.append,
            start_of=lambda p: "S", gui_ok=False, load_avg=(1, 2, 3), ncpu=10, **kw)
    return calls, out


def test_only_the_sampler_with_auto_freeze_true_runs_the_step(w, monkeypatch):
    monkeypatch.delenv("LW_GUI_HOG_AUTO", raising=False)
    monkeypatch.delenv("LW_GUI_HOG", raising=False)
    calls, out = _tick(w, monkeypatch)
    assert calls == []   # a test or any other caller of tick() never freezes anything
    calls, out = _tick(w, monkeypatch, auto_freeze=True)
    assert len(calls) == 1 and calls[0][1]["dry"] is False and any("auto-freeze" in x for x in out)
    calls, out = _tick(w, monkeypatch, dry=True)
    assert len(calls) == 1 and calls[0][1]["dry"] is True and any("would auto-freeze" in x for x in out)   # `load-watch sample --dry-run` prints what it would do


def test_the_kill_switches_stop_the_step(w, monkeypatch):
    monkeypatch.setenv("LW_GUI_HOG_AUTO", "0")
    assert _tick(w, monkeypatch, auto_freeze=True)[0] == []
    monkeypatch.delenv("LW_GUI_HOG_AUTO")
    monkeypatch.setenv("LW_GUI_HOG", "0")
    assert _tick(w, monkeypatch, auto_freeze=True)[0] == []


def test_a_failing_step_never_stops_the_tick(w, monkeypatch):
    monkeypatch.delenv("LW_GUI_HOG_AUTO", raising=False)
    monkeypatch.delenv("LW_GUI_HOG", raising=False)
    monkeypatch.setattr(gf, "auto_freeze_step", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    table, rss, ttys, _s = w.ops.table()
    out = []
    d = gh.tick({}, T0, table, rss, ttys, state_dir=w.state, my_uid=ME, cfg=auto_cfg(), lsapps=w.lsapps(), exe_of=w.ops.exe, out=out.append, auto_freeze=True,
                gui_ok=False, load_avg=(1, 2, 3), ncpu=10)
    assert d is not None and any("auto-freeze" in x and "boom" in x for x in out)


def test_the_sampler_passes_auto_freeze_and_the_cli_accepts_by_auto():
    src = (REPO / "bin" / "load-watch").read_text()
    assert "launch=True, auto_freeze=True" in src
    assert "auto" in gf.BY and gf.norm_entry({"id": "f-1", "state": "frozen", "app": {}, "root": {"pid": 100, "start": "s", "uid": ME, "exe": "/x"}, "members": [],
                                              "mode": "indefinite", "frozen_at": T0, "by": "auto"})["by"] == "auto"
    assert signal.SIGSTOP and os.getuid() == ME


# ---- adversary round 1 (PR 859, head a0bedcf6): M1, L1-L5 -----------------------------------------------------------------------------------
def test_m1_an_auto_freeze_needs_the_sampler_job_loaded(w, monkeypatch):
    """A `load-watch sample` that launchd's job does not follow (uninstalled or unloaded) must not stop an app on a timer nothing would ever thaw."""
    seen = []
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: seen.append(uid) or False)
    cfg = auto_cfg(order=(CODEXBAR, BEEPER))
    st = {}
    r = w.step(cfg, st=st)
    assert r["bundle_id"] == CODEXBAR and r["refused"].startswith(f"{gf.SAMPLER}:") and w.stopped() == [] and seen == [ME]
    assert st["auto"][CODEXBAR]["ok"] is False   # retry-wait: the next app is tried, this one after AUTO_RETRY_S
    assert w.step(cfg, st=st, now=T0 + 20)["bundle_id"] == BEEPER and w.stopped() == []
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: True)
    assert w.step(cfg, st=st, now=T0 + gf.AUTO_RETRY_S + 1)["entry"] and w.stopped() == [100]


def test_l1_ignore_one_hour_pauses_the_auto_freeze_too(w):
    cfg = auto_cfg()
    assert gf.auto_freeze_step({}, w.state, list(w.group(cfg).values()), held(), T0, cfg, my_uid=ME, ops=w.ops, snoozed=True) is None and w.stopped() == []
    assert w.step(cfg)["bundle_id"] == CODEXBAR   # not snoozed: it runs


def test_l1_the_tick_passes_the_snooze(w, monkeypatch):
    monkeypatch.delenv("LW_GUI_HOG_AUTO", raising=False)
    monkeypatch.delenv("LW_GUI_HOG", raising=False)
    calls = []
    monkeypatch.setattr(gf, "auto_freeze_step", lambda *a, **k: calls.append(k) or None)
    (w.state / "gui-hog").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gh, "read_snooze", lambda sd: T0 + 1800)
    table, rss, ttys, _s = w.ops.table()
    gh.tick({}, T0, table, rss, ttys, state_dir=w.state, my_uid=ME, cfg=auto_cfg(), lsapps=w.lsapps(), exe_of=w.ops.exe, out=lambda x: None, auto_freeze=True,
            gui_ok=False, load_avg=(1, 2, 3), ncpu=10)
    assert calls and calls[0]["snoozed"] is True


@pytest.mark.parametrize("body", ['enabled = "false"', "enabled = 0", 'refreeze_s = 0', "refreeze_s = -5", 'min_cores = "x"', "min_cores = -1", "minutes = 0",
                                  'minutes = "10"', "refreeze_s = 1e999", "minutes = 99999"])
def test_l2_wrong_typed_or_out_of_range_auto_values_keep_the_shipped_value(tmp_path, body):
    over = tmp_path / "gui-hog.toml"
    over.write_text("[freeze.auto]\n" + body + "\n")
    base = shipped()["freeze"]["auto"]
    assert gh.load_config(local=over)["freeze"]["auto"] == base


def test_l2_the_overlay_can_switch_auto_off_but_never_back_on(tmp_path):
    shipped_off = tmp_path / "shipped.toml"
    shipped_off.write_text('[freeze]\nenabled = true\n[freeze.auto]\nenabled = false\norder = ["a.b"]\n')
    over = tmp_path / "gui-hog.toml"
    over.write_text("[freeze.auto]\nenabled = true\n")
    assert gh.load_config(path=shipped_off, local=over)["freeze"]["auto"]["enabled"] is False   # the repo's rollback wins
    over.write_text("[freeze.auto]\nenabled = false\n")
    assert gh.load_config(local=over)["freeze"]["auto"]["enabled"] is False
    over.write_text("[freeze.auto]\nrefreeze_s = 7200\nmin_cores = 0.5\nminutes = 15\n")
    a = gh.load_config(local=over)["freeze"]["auto"]
    assert (a["refreeze_s"], a["min_cores"], a["minutes"]) == (7200, 0.5, 15)


def test_l3_the_start_comes_from_the_tick_so_a_relaunched_app_is_refused(w):
    cfg = auto_cfg(order=(CODEXBAR,))
    apps = list(w.group(cfg).values())
    st = {}
    r = gf.auto_freeze_step(st, w.state, apps, held(), T0, cfg, my_uid=ME, ops=w.ops, starts={100: "start-OTHER-INSTANCE"})
    assert r["refused"].startswith(f"{gf.IDENTITY}:") and w.stopped() == []   # the pid now belongs to another process than the one that was decided on
    r = gf.auto_freeze_step({}, w.state, apps, held(), T0, cfg, my_uid=ME, ops=w.ops, starts={100: "start-100"})
    assert r["entry"] and w.stopped() == [100]


@pytest.mark.parametrize("rule", ["/", "/opt/homebrew", "/Applications", "Contents", "", "/usr/local/bin/cargo", "../x/y", "/Applications/A.app", "/Applications/A.app/Contents"])
def test_l4_broad_or_inexact_keep_rules_are_refused(rule, tmp_path):
    assert gh.rule_ok(rule) is False
    over = tmp_path / "gui-hog.toml"
    over.write_text('[freeze.keep_running]\n"com.jetbrains.intellij" = [' + json.dumps(rule) + "]\n")
    assert "com.jetbrains.intellij" not in gh.load_config(local=over)["freeze"]["keep_running"] or gh.load_config(local=over)["freeze"]["keep_running"]["com.jetbrains.intellij"] == []
    cfg = auto_cfg()
    cfg["freeze"]["keep_running"]["com.jetbrains.intellij"] = [rule]
    assert gh.keep_rules(cfg, "com.jetbrains.intellij") == []


@pytest.mark.parametrize("rule", ["Contents/Helpers/CodexBarCLI", "/Applications/1Password.app/Contents/Library/LoginItems/H.app/Contents/MacOS/x",
                                  "~/.local/share/chrome-use/ChromeUse.app/Contents/MacOS/chrome-use"])
def test_l4_an_exact_executable_inside_a_bundle_is_accepted(rule):
    assert gh.rule_ok(rule) is True


def test_l5_an_os_error_is_recorded_as_a_refusal_and_retried_later_not_every_tick(w):
    cfg = auto_cfg(order=(CODEXBAR, BEEPER))
    w.ops.info_error = True   # ps timed out
    st = {}
    r = w.step(cfg, st=st)
    assert r["bundle_id"] == CODEXBAR and r["refused"].startswith("error: OSError") and w.stopped() == []
    assert st["auto"][CODEXBAR]["ok"] is False
    assert w.step(cfg, st=st, now=T0 + 20)["bundle_id"] == BEEPER   # CodexBar waits AUTO_RETRY_S; no repeated attempt (and log line) per tick


# ---- operator rulings 2026-11-21 (M3, M2): the never-auto `skip` list ------------------------------------------------------------------------
def test_an_app_on_skip_is_never_auto_frozen_even_when_listed_in_order(w):
    cfg = shipped()
    cfg["freeze"]["auto"]["order"] = [CODEXBAR, BEEPER, GROK]
    assert dict((a.get("bundle_id"), why) for a, why in gf.auto_candidates(list(w.group(cfg).values()), cfg, {}, T0)) == {CODEXBAR: "never-auto", BEEPER: "never-auto", GROK: ""}
    assert w.step(cfg)["bundle_id"] == GROK and w.stopped() == [300]
    assert w.step(cfg, now=T0 + 20) is None and w.stopped() == [300]   # Beeper and CodexBar are never touched, however long the hold


def test_skip_matches_the_bundle_id_case_insensitively_and_wins_over_a_running_busy_app(w):
    cfg = auto_cfg(order=(CODEXBAR,), skip=(CODEXBAR.upper(),))
    assert w.step(cfg) is None and w.stopped() == []


def test_a_manual_freeze_of_a_skipped_app_stays_possible(w):
    cfg = shipped()
    e = gf.freeze(w.state, 100, start="start-100", ops=w.ops, cfg=cfg, now=T0, check_sampler=False, agent_clis=(), minutes=10, by="cli")
    assert e["by"] == "cli" and w.stopped() == [100] and w.ops.sent_to(101) == []   # the dialog's own Freeze, with CodexBarCLI still kept running


def test_the_overlay_adds_to_skip_and_can_never_remove_from_it(tmp_path):
    over = tmp_path / "gui-hog.toml"
    over.write_text('[freeze.auto]\nskip = ["com.example.y", "", 5, "COM.EXAMPLE.Y"]\n')
    assert gh.load_config(local=over)["freeze"]["auto"]["skip"][:3] == [BEEPER, CODEXBAR, "com.example.y"]
    over.write_text("[freeze.auto]\nskip = []\n")
    assert gh.load_config(local=over)["freeze"]["auto"]["skip"] == [BEEPER, CODEXBAR]
    over.write_text('[freeze.auto]\nskip = "x"\n')
    assert gh.load_config(local=over)["freeze"]["auto"]["skip"] == [BEEPER, CODEXBAR]


def test_the_shipped_file_replaces_skip(tmp_path):
    f = tmp_path / "shipped.toml"
    f.write_text('[freeze.auto]\nskip = ["a.b"]\norder = ["c.d"]\n')
    assert gh.load_config(path=f, local=NOLOCAL)["freeze"]["auto"]["skip"] == ["a.b"]


def test_the_overlay_skip_never_duplicates_a_shipped_entry(tmp_path):
    over = tmp_path / "gui-hog.toml"
    over.write_text('[freeze.auto]\nskip = ["COM.AUTOMATTIC.BEEPER.DESKTOP", "com.example.z"]\n')
    assert gh.load_config(local=over)["freeze"]["auto"]["skip"] == [BEEPER, CODEXBAR, "com.example.z"]


def test_skip_matches_when_the_order_entry_has_another_case(w):
    cfg = auto_cfg(order=(CODEXBAR.upper(),), skip=(CODEXBAR,))
    assert w.step(cfg) is None and w.stopped() == []
