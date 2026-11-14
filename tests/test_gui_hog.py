"""bin/gui_hog.py and its load-watch wiring, GUI-hog dialog PR 3a (docs/gui-hog-dialog.md H1 a, b, c, f): the trigger decision table, app
grouping (helpers, build subtrees), the protected list, the hold registry in `admit`, the dry-run log, `gui-hog status`, the
admit-log summary count and LW_GUI_HOG=0. No window, no signals: stdlib and fixtures only, so it runs on Linux CI."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
from test_load_watch_pr2 import CORES, LW, SOFT, Run, load_module  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gui_hog" / "lsappinfo.txt"
ME = 502
NOW = 2_000_000.0
BIN = Path(__file__).resolve().parent.parent / "bin"


def cfg(**trigger):
    c = gh.load_config(path=Path("/nonexistent"), local=Path("/nonexistent"))
    c["trigger"].update(trigger)
    return c


def shipped():
    return gh.load_config(local=Path("/nonexistent"))


def app(name, cores, rss=100, bid="com.example.a", protected=None, excluded=None, hosts_build=False):
    return {"id": name, "name": name, "bundle_id": bid, "bundle_path": f"/Applications/{name}.app", "cores_5m": cores, "rss_mb": rss,
            "protected": protected, "excluded": excluded, "hosts_build": hosts_build}


def hold(age, refused=("load",), pid=11, caller="bg"):
    return {"pid": pid, "start": "s", "caller": caller, "refused_since": NOW - age, "refused": list(refused), "updated": NOW}


# ---- untrusted text (J3) -------------------------------------------------------------------------------------------------------------------

def test_clean_strips_controls_bidi_zero_width_and_separators():
    dirty = "a\x00b\x1b[31mc\u202ed\u200be\u2028f\u2029g\x9bh\u2066i\ufeffj\n\t"
    assert gh.clean(dirty) == "ab[31mcdefghij"


@pytest.mark.parametrize("ch", ["\U000e0049", "\u2060", "\u00ad", "\u180e", "\ufff9", "\u034f", "\u115f", "\u1160", "\u3164", "\uffa0",
                                "\u200f", "\u061c", "\ue000", "\x7f", "\x85", "\ufe0f", "\ufe01", "\U000e0100", "\u17b4", "\u180b", "\u2800"])
def test_clean_strips_invisible_and_filler_characters(ch):
    assert gh.clean(f"ab{ch}cd") == "abcd" and gh.clean(ch * 5) == ""


def test_clean_clips_without_splitting_a_combining_cluster():
    s = "x" * 59 + "é" + "yy"   # the 60th character is the base of a cluster whose mark is character 61
    out = gh.clean(s, 60)
    assert out == "x" * 59 + "…" and "́" not in out
    assert gh.clean("short") == "short"
    assert len(gh.clean("y" * 500)) <= 61


# ---- lsappinfo parsing against the fixture (H1b) --------------------------------------------------------------------------------------------

def test_parse_lsappinfo_fixture():
    ents = gh.parse_lsappinfo(FIXTURE.read_text())
    by = {e["pid"]: e for e in ents}
    assert set(by) == {100, 101, 200, 300, 301, 400, 500, 600}   # the entry with no pid line is skipped
    assert by[200]["bundle_id"] == "com.mitchellh.ghostty" and by[200]["type"] == "Foreground"
    assert by[101]["bundle_id"] is None and by[101]["type"] == "BackgroundOnly"        # bundleID=[ NULL ]
    assert by[300]["bundle_path"] == "/Applications/Slack.app"
    assert by[400]["exe"].endswith("/Contents/MacOS/Electron")
    assert by[500]["name"] == 'Evil "quoted" \u202eapp'   # quotes and a bidi mark survive parsing; `clean` is what strips them


@pytest.mark.parametrize("text", ["", "garbage\nmore garbage", "1) no asn line\n pid = 4 type=\"Foreground\"", "\x00\x01"])
def test_parse_lsappinfo_never_raises_on_nonsense(text):
    assert gh.parse_lsappinfo(text) == []


def test_collect_lsappinfo_failure_is_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("no lsappinfo")
    monkeypatch.setattr(gh.subprocess, "run", boom)
    assert gh.collect_lsappinfo() == []


# ---- grouping (H1b) ----------------------------------------------------------------------------------------------------------------------

def tbl(*rows):
    """rows: (pid, ppid, uid, cores, cmd) -> (table, rss_kb)."""
    return {str(p): (pp, u, c, cmd) for p, pp, u, c, cmd in rows}


def group(table, exe, lsapps=None, rss=None, ttys=(), held=(), config=None):
    ls = gh.parse_lsappinfo(FIXTURE.read_text()) if lsapps is None else lsapps
    return {a["id"]: a for a in gh.group_apps(table, rss or {}, set(ttys), ls, exe_of=lambda p: exe.get(str(p)), my_uid=ME,
                                              held_pids=held, agent_clis={"claude", "codex"}, cfg=config or shipped())}


SLACK = "/Applications/Slack.app/Contents"


def test_helpers_group_into_one_app_by_tree_and_by_bundle_exe():
    table = tbl((300, 1, ME, 0.5, f"{SLACK}/MacOS/Slack"), (310, 300, ME, 0.7, f"{SLACK}/Frameworks/Slack Helper (Renderer).app/x"),
                (311, 310, ME, 0.2, f"{SLACK}/Frameworks/Slack Helper (GPU).app/x"),
                (320, 1, ME, 0.3, f"{SLACK}/Frameworks/Slack Helper.app/Contents/MacOS/Slack Helper"),   # started by launchd: ppid 1
                (900, 1, ME, 9.0, "/usr/bin/other"))
    exe = {"300": f"{SLACK}/MacOS/Slack", "310": f"{SLACK}/Frameworks/Slack Helper (Renderer).app/x",
           "311": f"{SLACK}/Frameworks/Slack Helper (GPU).app/x", "320": f"{SLACK}/Frameworks/Slack Helper.app/Contents/MacOS/Slack Helper",
           "900": "/usr/bin/other"}
    apps = group(table, exe, rss={"300": 100 * 1024, "310": 300 * 1024, "311": 50 * 1024, "320": 50 * 1024, "900": 10 ** 6})
    slack = apps["300"]
    assert slack["members"] == 4 and slack["cores"] == pytest.approx(1.7) and slack["rss_mb"] == pytest.approx(500)
    assert not slack["hosts_build"] and slack["excluded"] is None and slack["protected"] is None
    assert "301" not in apps   # Slack Helper's own lsappinfo entry (nested in the bundle) is folded into Slack, not a second row
    assert "900" not in apps


CODE = "/Applications/Visual Studio Code.app/Contents"


def test_ide_terminal_running_make_is_a_build_not_a_hog():
    table = tbl((400, 1, ME, 0.4, f"{CODE}/MacOS/Electron"), (410, 400, ME, 0.2, f"{CODE}/Frameworks/Code Helper.app/x"),
                (420, 410, ME, 0.0, "/bin/zsh -l"), (421, 420, ME, 3.5, "make -j8"), (422, 421, ME, 4.0, "cc1plus"))
    exe = {"400": f"{CODE}/MacOS/Electron", "410": f"{CODE}/Frameworks/Code Helper.app/x", "420": "/bin/zsh", "421": "/usr/bin/make",
           "422": "/usr/bin/cc1plus"}
    a = group(table, exe)["400"]
    assert a["hosts_build"] and a["build_cores"] == pytest.approx(7.5)
    assert a["cores"] == pytest.approx(0.6) and a["members"] == 2   # the shell and everything under it never count


def test_ide_started_gradle_daemon_outside_the_bundle_is_a_build():
    """No shell above the java: the out-of-bundle executable alone stops the walk (C4b stop 5)."""
    table = tbl((400, 1, ME, 0.1, f"{CODE}/MacOS/Electron"), (430, 400, ME, 6.0, "java -jar gradle-daemon.jar"))
    a = group(table, {"400": f"{CODE}/MacOS/Electron", "430": "/Library/Java/JavaVirtualMachines/jdk/bin/java"})["400"]
    assert a["hosts_build"] and a["cores"] == pytest.approx(0.1) and a["build_cores"] == pytest.approx(6.0)


def test_xcode_with_in_bundle_toolchain_is_protected_by_bundle_id():
    xc = "/Applications/Xcode.app/Contents"
    ls = [{"name": "Xcode", "bundle_id": "com.apple.dt.Xcode", "bundle_path": "/Applications/Xcode.app", "exe": f"{xc}/MacOS/Xcode",
           "pid": 700, "type": "Foreground"}]
    table = tbl((700, 1, ME, 0.3, f"{xc}/MacOS/Xcode"), (701, 700, ME, 5.0, f"{xc}/Developer/usr/bin/swift-frontend"))
    a = group(table, {"700": f"{xc}/MacOS/Xcode", "701": f"{xc}/Developer/usr/bin/swift-frontend"}, lsapps=ls)["700"]
    assert a["protected"] == "cfg:bundle-id" and a["members"] == 2 and not a["hosts_build"]


def test_pty_attached_child_and_agent_cli_child_stop_the_walk():
    table = tbl((400, 1, ME, 0.1, "x"), (440, 400, ME, 2.0, "tool"), (441, 400, ME, 3.0, "node agent"), (442, 400, ME, 0.3, "helper"))
    exe = {"400": f"{CODE}/MacOS/Electron", "440": f"{CODE}/Frameworks/t", "441": "/usr/local/bin/claude", "442": f"{CODE}/Frameworks/h"}
    a = group(table, exe, ttys={"440"})["400"]
    assert a["hosts_build"] and a["build_cores"] == pytest.approx(5.0) and a["cores"] == pytest.approx(0.4)


def test_an_app_started_under_a_held_caller_or_an_agent_cli_is_excluded():
    """Playwright's Chrome for Testing: the app's ancestry reaches the agent (or the held `bg`)."""
    exe = {"500": "/Applications/Evil.app/Contents/MacOS/evil", "50": "/usr/local/bin/claude", "51": "/bin/bg", "40": "/usr/bin/node"}
    under_agent = tbl((50, 1, ME, 0.1, "claude"), (40, 50, ME, 0.1, "node"), (500, 40, ME, 2.0, "evil"))
    assert group(under_agent, exe)["500"]["excluded"] == "agent-ancestor"
    under_bg = tbl((51, 1, ME, 0.1, "bg"), (500, 51, ME, 2.0, "evil"))
    assert group(under_bg, exe, held=[51])["500"]["excluded"] == "held-ancestor"
    plain = tbl((500, 1, ME, 2.0, "evil"))
    assert group(plain, exe)["500"]["excluded"] is None


def test_an_agent_cli_is_recognised_by_its_argv_not_only_by_the_kernel_exe():
    """Claude's own binary is named for its version, and a node script's kernel exe is `node`: the argv heads decide (load-watch's cli_heads)."""
    exe = {"400": f"{CODE}/MacOS/Electron", "441": "/Users/x/.local/share/claude/versions/2.1.325", "442": "/usr/local/bin/node",
           "443": "/bin/zsh", "444": f"{CODE}/Frameworks/h"}
    table = tbl((400, 1, ME, 0.1, "x"), (441, 400, ME, 3.0, "claude --dangerously-skip-permissions"),
                (442, 400, ME, 4.0, "node /opt/homebrew/bin/codex exec"), (443, 400, ME, 0.0, "-zsh"), (444, 400, ME, 0.2, "h"))
    a = group(table, exe)["400"]
    assert a["hosts_build"] and a["build_cores"] == pytest.approx(7.0) and a["cores"] == pytest.approx(0.3) and a["members"] == 2
    under = tbl((50, 1, ME, 0.1, "claude"), (500, 50, ME, 2.0, "evil"))
    assert group(under, {"500": "/Applications/Evil.app/Contents/MacOS/evil", "50": "/x/2.1.325"})["500"]["excluded"] == "agent-ancestor"


def test_a_build_running_the_apps_own_binary_is_not_the_app():
    """Headless Chrome for a test run: its executable lies in Chrome's bundle, but a shell/agent stands between it and the app."""
    ch = "/Applications/Google Chrome.app/Contents"
    ls = [{"name": "Chrome", "bundle_id": "com.google.Chrome", "bundle_path": "/Applications/Google Chrome.app", "exe": f"{ch}/MacOS/Google Chrome",
           "pid": 600, "type": "Foreground"}]
    exe = {"600": f"{ch}/MacOS/Google Chrome", "50": "/x/2.1.325", "51": "/usr/local/bin/node", "610": f"{ch}/MacOS/Google Chrome",
           "611": f"{ch}/Frameworks/Helper.app/Contents/MacOS/Helper", "620": f"{ch}/Frameworks/Helper.app/Contents/MacOS/Helper"}
    table = tbl((600, 1, ME, 0.5, f"{ch}/MacOS/Google Chrome"), (620, 600, ME, 0.3, f"{ch}/Frameworks/Helper.app/x"),
                (50, 1, ME, 0.1, "claude"), (51, 50, ME, 0.1, "node run-tests.js"),
                (610, 51, ME, 6.0, f"{ch}/MacOS/Google Chrome --headless"), (611, 610, ME, 2.0, f"{ch}/Frameworks/Helper.app/x --type=renderer"))
    a = group(table, exe, lsapps=ls)["600"]
    assert a["members"] == 2 and a["cores"] == pytest.approx(0.8)      # the real Chrome and its helper, nothing of the test run
    assert not a["hosts_build"]


def test_other_users_apps_are_not_apps_of_ours():
    table = tbl((100, 1, 0, 0.5, "loginwindow"), (300, 1, ME, 0.5, "x"))
    apps = group(table, {})
    assert "100" not in apps


def test_fallback_groups_by_the_kernel_exe_path_when_lsappinfo_is_empty(tmp_path):
    bundle = tmp_path / "Foo.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    exe_path = str(bundle / "Contents" / "MacOS" / "Foo")
    table = tbl((800, 1, ME, 1.0, exe_path), (801, 800, ME, 0.5, exe_path + " helper"))
    apps = group(table, {"800": exe_path, "801": exe_path}, lsapps=[])
    assert list(apps) == ["800"] and apps["800"]["members"] == 2 and apps["800"]["name"] == "Foo"
    assert apps["800"]["bundle_path"] == str(bundle)


# ---- the protected list (H1c) ------------------------------------------------------------------------------------------------------------

def reason(bid=None, bundle="/Applications/Foo.app", exe=None, uid=ME, config=None):
    return gh.protect_reason(bid, bundle, exe or bundle + "/Contents/MacOS/foo", uid, ME, config or shipped())


@pytest.mark.parametrize("bid,expected", [("com.mitchellh.ghostty", "cfg:bundle-id"), ("COM.MITCHELLH.GHOSTTY", "cfg:bundle-id"),
                                          ("com.jetbrains.intellij", "cfg:bundle-id-prefix"), ("sh.paseo.desktop.helper", "cfg:bundle-id"),
                                          ("com.apple.dt.Xcode", "cfg:bundle-id"), ("io.tailscale.ipn.macsys", "cfg:bundle-id"),
                                          ("com.tinyspeck.slackmacgap", None), ("com.example.ghostty", None)])
def test_protected_by_bundle_id(bid, expected):
    assert reason(bid) == expected


def test_protected_by_bundle_path_matches_components_not_text_prefixes():
    assert reason(None, "/Applications/Ghostty.app") == "cfg:bundle-path"
    assert reason(None, "/applications/ghostty.app") == "cfg:bundle-path"          # case-insensitive file system
    assert reason(None, "/Applications/Ghostty.app.x") is None                      # not a path prefix of it
    assert reason(None, "/Applications/Foo.app", exe="/Applications/Ghostty.app/Contents/MacOS/ghostty") == "cfg:bundle-path"
    assert reason(None, "/Applications/Foo.app", exe="/Applications/WezTerm.app/Contents/MacOS/wezterm-gui") == "cfg:bundle-path"


def test_the_bundle_path_alone_protects_when_the_executable_is_unknown_or_elsewhere():
    """The bundle check and the executable check are separate: an app whose exe cannot be read, or lies outside its bundle, is still protected by the bundle."""
    for exe in (None, "/opt/elsewhere/helper"):
        assert gh.protect_reason(None, "/Applications/Ghostty.app", exe, ME, ME, shipped()) == "cfg:bundle-path"
        assert gh.protect_reason(None, "/Applications/Foo.app", exe, ME, ME, shipped()) is None


def test_a_display_name_never_protects_and_never_unprotects():
    """Protection looks at the live bundle id, path and exe only: `group_apps` never reads the name."""
    ls = gh.parse_lsappinfo(FIXTURE.read_text())
    table = tbl((200, 1, ME, 1.0, "g"), (300, 1, ME, 1.0, "s"))
    exe = {"200": "/Applications/Ghostty.app/Contents/MacOS/ghostty", "300": "/Applications/Slack.app/Contents/MacOS/Slack"}
    spoof = [dict(e, name="Ghostty") if e["pid"] == 300 else dict(e, name="Totally Normal App") if e["pid"] == 200 else e for e in ls]
    apps = group(table, exe, lsapps=spoof)
    assert apps["300"]["protected"] is None       # called "Ghostty", is not
    assert apps["200"]["protected"] is not None   # called anything, is


def test_an_app_that_claims_a_protected_bundle_id_is_protected():
    table = tbl((600, 1, ME, 3.0, "/Users/x/Downloads/Impostor.app/Contents/MacOS/impostor"))
    a = group(table, {"600": "/Users/x/Downloads/Impostor.app/Contents/MacOS/impostor"})["600"]
    assert a["bundle_id"] == "com.mitchellh.ghostty" and a["protected"] == "cfg:bundle-id"   # the safe direction


@pytest.mark.parametrize("bid,bundle,exe,uid,why", [
    ("com.apple.dock", "/Applications/Dock.app", None, ME, "hard:bundle-id"), ("com.apple.finder", "/x/F.app", None, ME, "hard:bundle-id"),
    ("com.apple.loginwindow", "/x/L.app", None, ME, "hard:bundle-id"), ("com.apple.controlcenter", "/x/C.app", None, ME, "hard:bundle-id"),
    ("com.apple.WindowManager", "/x/W.app", None, ME, "hard:bundle-id"), ("com.djbclark.ade.gui-hog", "/x/G.app", None, ME, "hard:bundle-id"),
    ("com.example.x", "/System/Library/CoreServices/X.app", None, ME, "hard:system-path"),
    ("com.example.x", "/Applications/X.app", "/usr/libexec/x", ME, "hard:system-path"),
    ("com.example.x", "/Applications/X.app", "/Applications/X.app/Contents/MacOS/WindowServer", ME, "hard:exe"),
    ("com.example.x", "/Applications/X.app", None, 0, "hard:uid"), ("com.example.x", "/Applications/X.app", None, ME + 1, "hard:uid")])
def test_the_hard_floor(bid, bundle, exe, uid, why):
    assert reason(bid, bundle, exe, uid) == why


def test_config_can_add_to_the_protected_list_but_never_lift_the_hard_floor(tmp_path):
    local = tmp_path / "gui-hog.toml"
    local.write_text('[protected]\nbundle_ids = ["com.example.mine"]\nbundle_paths = ["/Opt/Mine.app"]\n'
                     '[trigger]\nmin_cores = 0\n\n[hard]\nbundle_ids = []\n')
    c = gh.load_config(local=local)
    assert c["trigger"]["min_cores"] == 0.75                                  # the local file cannot touch the trigger
    assert "com.example.mine" in c["protected"]["bundle_ids"] and "com.mitchellh.ghostty" in c["protected"]["bundle_ids"]
    assert reason("com.example.mine", config=c) == "cfg:bundle-id" and reason(None, "/Opt/Mine.app", config=c) == "cfg:bundle-path"
    empty = tmp_path / "empty.toml"
    empty.write_text("[protected]\nbundle_ids = []\nbundle_id_prefixes = []\nbundle_paths = []\n")
    c2 = gh.load_config(path=empty, local=Path("/nonexistent"))
    assert reason("com.apple.dock", config=c2) == "hard:bundle-id"            # even an empty config keeps the floor
    assert reason("com.apple.finder", config=c2) == "hard:bundle-id"
    bad = tmp_path / "bad.toml"
    bad.write_text("this is [not toml")
    assert "com.mitchellh.ghostty" in gh.load_config(local=bad)["protected"]["bundle_ids"]   # a broken local file is ignored


def test_the_shipped_config_names_what_the_design_protects():
    c = shipped()
    for must in ("sh.paseo.desktop", "com.mitchellh.ghostty", "com.apple.Terminal", "io.tailscale.ipn.macsys",
                 "com.apple.CoreSimulator.CoreSimulatorService", "com.apple.dt.Xcode", "com.google.android.studio", "com.1password.1password"):
        assert must in c["protected"]["bundle_ids"], must
    assert c["trigger"]["hold_s"] == 180 and c["trigger"]["min_cores"] == 0.75 and c["trigger"]["min_rss_mb"] == 2048
    assert c["trigger"]["rate_s"] == 1800 and c["trigger"]["snooze_s"] == 3600


# ---- should_show: the decision table (H1a) -------------------------------------------------------------------------------------------------

BUSY = [app("A", 0.5, 300), app("B", 0.3, 300)]   # 0.8 cores, 600 MB: over the cores line only
HEAVY = [app("A", 0.2, 1500), app("B", 0.1, 700)]  # 0.3 cores, 2200 MB: over the RSS line only


def show(held, apps, snooze=None, last=None, config=None):
    return gh.should_show(held, apps, NOW, snooze, last, config or cfg())


@pytest.mark.parametrize("held,apps,snooze,last,want,why", [
    ([], BUSY, None, None, False, "no-hold"),
    ([hold(179)], BUSY, None, None, False, "hold-too-short"),
    ([hold(180)], BUSY, None, None, True, "show"),                     # exactly the 3-minute wait
    ([hold(600, ("agents",))], BUSY, None, None, False, "not-relievable"),
    ([hold(600, ("agents", "pageins"))], BUSY, None, None, True, "show"),
    ([hold(600, ("memory_unreadable",))], BUSY, None, None, False, "not-relievable"),
    ([hold(10), hold(500, ("swapins",), pid=12)], BUSY, None, None, True, "show"),   # any one old, relievable hold
    ([hold(600)], [app("A", 0.749, 1000)], None, None, False, "below-threshold"),
    ([hold(600)], [app("A", 0.75, 1000)], None, None, True, "show"),
    ([hold(600)], [app("A", 0.1, 2047)], None, None, False, "below-threshold"),
    ([hold(600)], [app("A", 0.1, 2048)], None, None, True, "show"),
    ([hold(600)], HEAVY, None, None, True, "show"),
    ([hold(600)], [app("A", 0.5, 100), app("B", 0.25, 100)], None, None, True, "show"),        # K2: a SUM, no single app reaches 0.75
    ([hold(600)], BUSY, None, NOW - 1799, False, "rate-limited"),
    ([hold(600)], BUSY, None, NOW - 1800, True, "show"),
    ([hold(600)], BUSY, NOW + 1, None, False, "snoozed"),                                          # Ignore: 60 min
    ([hold(600)], BUSY, NOW, None, True, "show"),
    ([hold(600)], BUSY, NOW + 3599, NOW - 100, False, "snoozed"),
    ([hold(600)], [app("A", 5.0, 5000, protected="cfg:bundle-id")], None, None, False, "below-threshold"),   # protected apps never count
    ([hold(600)], [app("A", 5.0, 5000, excluded="agent-ancestor")], None, None, False, "below-threshold"),   # nor a build's own tree
    ([hold(600)], [app("A", 0.1, 100, hosts_build=True), app("B", 0.7, 100)], None, None, True, "show"),     # an IDE counts without its build
])
def test_should_show_decision_table(held, apps, snooze, last, want, why):
    d = show(held, apps, snooze, last)
    assert (d["show"], d["reason"]) == (want, why)


def test_should_show_reports_the_sums_and_the_holds():
    d = show([hold(300, ("load", "pageins"))], BUSY)
    assert d["sum_cores"] == pytest.approx(0.8) and d["sum_rss_mb"] == 600 and [h["pid"] for h in d["holds"]] == [11]


def test_thresholds_come_from_the_config():
    tight = cfg(min_cores=5.0, min_rss_mb=10 ** 6)
    assert show([hold(600)], BUSY, config=tight)["reason"] == "below-threshold"
    assert show([hold(60)], BUSY, config=cfg(hold_s=30))["show"]


# ---- the 5-minute window ----------------------------------------------------------------------------------------------------------------

def feed(st, rows, t0=NOW - 200, dt=20, config=None):
    """Feed window_update one sample per element of `rows` (a list of app lists), return the means at the last sample."""
    c = config or cfg()
    t = t0
    for r in rows:
        gh.window_update(st, t, r, 5.0, c)
        t += dt
    return gh.window_means(st, t - dt, c)


def test_window_mean_counts_a_missing_sample_as_zero_and_rss_is_the_latest():
    a1 = {"id": "9", "name": "A", "bundle_id": "b", "bundle_path": "/p", "cores": 1.0, "rss_mb": 500, "protected": None, "excluded": None, "hosts_build": False}
    a2 = dict(a1, cores=3.0, rss_mb=900)
    means = feed({}, [[a1], [], [a1], [a2]])
    assert len(means) == 1 and means[0]["cores_5m"] == pytest.approx((1.0 + 0 + 1.0 + 3.0) / 4) and means[0]["rss_mb"] == 900


def test_window_trims_to_window_s_and_drops_unused_meta():
    a = {"id": "9", "name": "A", "bundle_id": "b", "bundle_path": "/p", "cores": 1.0, "rss_mb": 500, "protected": None, "excluded": None, "hosts_build": False}
    st = {}
    gh.window_update(st, NOW - 1000, [a], 4.0, cfg())
    gh.window_update(st, NOW, [], 4.0, cfg())
    assert len(st["apps"]) == 1 and st["app_meta"] == {}


def test_window_stores_flags_and_skips_excluded_and_tiny_apps():
    base = {"bundle_id": "b", "bundle_path": "/p", "protected": None, "excluded": None, "hosts_build": False}
    apps = [dict(base, id="1", name="prot", cores=0.5, rss_mb=100, protected="cfg:bundle-id"),
            dict(base, id="2", name="ex", cores=2.0, rss_mb=500, excluded="agent-ancestor"),
            dict(base, id="3", name="tiny", cores=0.0, rss_mb=10),
            dict(base, id="4", name="ide", cores=0.3, rss_mb=300, hosts_build=True)]
    st = {}
    gh.window_update(st, NOW, apps, 3.0, cfg())
    assert st["apps"][0]["a"] == {"1": [0.5, 100, 1], "4": [0.3, 300, 2]}
    means = {m["id"]: m for m in gh.window_means(st, NOW, cfg())}
    assert means["1"]["protected"] and means["4"]["hosts_build"] and not means["4"]["protected"]


def test_window_means_survive_a_corrupt_state_file():
    st = {"apps": [None, {"t": "x"}, {"t": NOW, "a": [1]}, {"t": NOW, "a": {"1": "oops", "2": [float("nan"), 1], "3": [1.0, 2]}}],
          "app_meta": {"3": "not a dict"}}
    means = gh.window_means(st, NOW, cfg())
    assert [m["id"] for m in means] == ["3"] and means[0]["name"] == "3"


# ---- the hold registry (H1f, gui_hog side) --------------------------------------------------------------------------------------------------

def put(state, pid, start="S1", upd=NOW, since=NOW - 300, refused=("load",), poll=15, caller="bg"):
    return gh.hold_write(state, pid, start, caller, since, list(refused), upd, poll)


def mine(start_of=lambda pid: "S1"):
    return start_of


def test_hold_write_is_atomic_private_and_readable(tmp_path):
    p = put(tmp_path, 4242, since=NOW - 200)
    assert p.parent == tmp_path / "held" and p.name == "4242-S1.json" and (p.stat().st_mode & 0o777) == 0o600
    assert not [x for x in p.parent.iterdir() if x.name.startswith(".hold-")]
    rec = json.loads(p.read_text())
    assert rec["v"] == 1 and rec["pid"] == 4242 and rec["refused"] == ["load"] and rec["refused_since"] == int(NOW - 200)
    [h] = gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")
    assert h["pid"] == 4242 and h["caller"] == "bg" and h["refused"] == ["load"] and h["refused_since"] == int(NOW - 200)


def test_a_hold_not_refreshed_for_60_seconds_is_stale_and_swept(tmp_path):
    p = put(tmp_path, 1, upd=NOW - 61)
    assert gh.read_holds(tmp_path, NOW, sweep=False, start_of=lambda pid: "S1") == [] and p.exists()   # read-only status never sweeps
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1") == [] and not p.exists()
    fresh = put(tmp_path, 2, upd=NOW - 59)
    assert len(gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")) == 1 and fresh.exists()


def test_a_slow_poller_widens_its_own_staleness_window(tmp_path):
    put(tmp_path, 1, upd=NOW - 100, poll=60)   # 2 * 60 + 15 = 135 s
    assert len(gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")) == 1


def test_a_hold_whose_pid_start_changed_or_is_gone_is_stale(tmp_path):
    reused = put(tmp_path, 7, start="OLD")
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "NEW") == [] and not reused.exists()
    gone = put(tmp_path, 2 ** 22 + 8)
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: None) == [] and not gone.exists()      # no start and no process: gone
    nostart = put(tmp_path, os.getpid(), start="")   # no start recorded: alive is checked instead
    assert len(gh.read_holds(tmp_path, NOW, start_of=lambda pid: "x")) == 1 and nostart.exists()
    dead = put(tmp_path, 2 ** 22 + 12345, start="")
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "x")[0]["pid"] == os.getpid() and not dead.exists()


def test_a_fifo_a_symlink_a_huge_pid_and_nan_in_the_held_directory_never_hang_or_crash(tmp_path):
    d = tmp_path / "held"
    d.mkdir()
    os.mkfifo(d / "7-S1.json")
    secret = tmp_path / "secret"
    secret.write_text("keep me")
    (d / "8-S1.json").symlink_to(secret)
    real = d / "real-hold.txt"                                                    # a valid, fresh hold of a live pid, reached only through a symlink
    real.write_text(json.dumps({"v": 1, "pid": os.getpid(), "start": "S1", "updated": NOW, "refused_since": NOW, "refused": ["load"]}))
    (d / f"{os.getpid()}-S1.json").symlink_to(real)
    (d / "9-S1.json").write_text(json.dumps({"v": 1, "pid": 10 ** 30, "start": "S1", "updated": NOW, "refused_since": NOW, "refused": ["load"]}))
    (d / "10-S1.json").write_text('{"v": 1, "pid": 10, "start": "S1", "updated": NaN, "refused_since": NaN, "refused": ["load"]}')
    (d / "11-S1.json").write_text(json.dumps({"v": 1, "pid": 11, "start": "S1", "updated": NOW + 10 ** 6, "refused_since": NOW, "refused": ["load"]}))
    (d / "12-S1.json").write_text("x" * 10 ** 6)                                  # far beyond the size cap
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1") == []
    assert secret.read_text() == "keep me"


def test_a_symlinked_held_directory_is_neither_read_nor_swept(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    victim = real / "1-S1.json"
    victim.write_text(json.dumps({"v": 1, "pid": 1, "start": "S1", "updated": NOW - 10 ** 5, "refused_since": NOW, "refused": ["load"]}))
    (tmp_path / "held").symlink_to(real)
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1") == [] and victim.exists()
    with pytest.raises(OSError):
        gh.hold_write(tmp_path, os.getpid(), "S1", "bg", NOW, ["load"], NOW)


def test_a_failed_start_read_is_not_pid_reuse_unless_the_process_is_gone(tmp_path):
    alive = put(tmp_path, os.getpid(), start="OLD")
    assert len(gh.read_holds(tmp_path, NOW, start_of=lambda pid: None)) == 1 and alive.exists()   # `ps` timed out: keep the hold
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "NEW") == [] and not alive.exists()   # a different start: reused


def test_the_first_sweep_of_an_admit_does_not_compare_start_times(tmp_path):
    put(tmp_path, os.getpid(), start="OLD")
    calls = []
    assert len(gh.read_holds(tmp_path, NOW, check_start=False, start_of=lambda pid: calls.append(pid) or "NEW")) == 1 and calls == []


def test_refused_since_is_clamped_never_trusted(tmp_path):
    put(tmp_path, 1, since=NOW - 10 ** 7)
    put(tmp_path, 2, since=NOW + 10 ** 6)
    by = {h["pid"]: h for h in gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")}
    assert by[1]["refused_since"] == NOW - 3600           # the age is capped at STARVE_REFUSED_SINCE_MAX_S
    assert by[2]["refused_since"] == NOW                   # a future value counts as now
    (tmp_path / "held" / "3-S1.json").write_text(json.dumps({"v": 1, "pid": 3, "start": "S1", "updated": NOW, "refused_since": "soon", "refused": ["load"]}))
    assert {h["pid"]: h for h in gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")}[3]["refused_since"] == NOW


@pytest.mark.parametrize("body", ["not json", "[]", "{}", '{"v": 2, "pid": 1, "updated": 1}', '{"v": 1, "pid": "x", "updated": 1}',
                                  '{"v": 1, "pid": 1, "updated": null}', '{"v": 1, "pid": true, "updated": 1}', "\x00" * 10,
                                  '{"v":1,"pid":1,"start":"S1","updated":' + str(2_000_000) + ',"refused":"load"}'])
def test_garbage_in_the_held_directory_is_skipped(tmp_path, body):
    d = tmp_path / "held"
    d.mkdir()
    (d / "bad.json").write_text(body)
    (d / "notes.txt").write_text("x")
    assert gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1") == []


def test_hold_text_is_cleaned_on_write_and_on_read(tmp_path):
    put(tmp_path, 5, caller="b\x1bg\u202e", refused=["load\x00", "pageins"])
    d = tmp_path / "held"
    rec = json.loads(next(d.iterdir()).read_text())
    rec["caller"] = "ev\u202eil\x07"
    next(d.iterdir()).write_text(json.dumps(rec))
    [h] = gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")
    assert h["caller"] == "evil" and h["refused"] == ["load", "pageins"]


def test_a_missing_held_directory_is_no_holds(tmp_path):
    assert gh.read_holds(tmp_path / "nope", NOW) == []


# ---- the hold registry inside `admit` (H1f) ---------------------------------------------------------------------------------------------------

def held_files(state):
    d = Path(state) / "held"
    return sorted(d.iterdir()) if d.exists() else []


def spy(run):
    """Record the held directory at every nap (a poll boundary of the waiting admit)."""
    seen = []
    orig = run.lw.nap

    def nap(s):
        seen.append([json.loads(p.read_text()) for p in held_files(run.state)])
        orig(s)
    run.lw.nap = nap
    return seen


def test_a_waiting_admit_keeps_a_hold_file_and_removes_it_on_return(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen = spy(run)
    rc, rec, _ = run(capsys, wait=100.0)
    assert rc == 75 and rec["status"] == "hot"
    assert len(seen) >= 3 and all(len(s) == 1 for s in seen)
    first, last = seen[0][0], seen[-1][0]
    assert first["pid"] == os.getpid() and first["v"] == 1 and first["caller"] == "pytest"
    assert set(first["refused"]) == {"load", "compressor"}
    assert first["refused_since"] == int(NOW)                      # the run began at the first poll
    assert last["updated"] > first["updated"] and last["refused_since"] == first["refused_since"]   # refreshed, same run
    assert held_files(run.state) == []                             # removed on return
    assert rec["refused"] == ["load", "compressor"]                # the verdict is untouched


def test_the_hold_start_credits_a_refused_since_through_parse_refused_since(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen = spy(run)
    rc, _rec, _ = run(capsys, wait=30.0, refused_since=str(int(NOW - 100)))
    assert rc == 75 and seen and seen[0][0]["refused_since"] == int(NOW - 100)       # a cross-chunk start is legitimately older than this admit
    big = Run(monkeypatch, tmp_path / "big", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen_big = spy(big)
    assert big(capsys, wait=30.0, refused_since=str(int(NOW - 500)))[0] == 0 and seen_big == []   # the valve spends a 500 s credit at once: no wait, no hold file
    run2 = Run(monkeypatch, tmp_path / "b", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen2 = spy(run2)
    monkeypatch.setattr(run2.lw, "STARVE_SOFT_S", 0.0)                      # valve off: the capped 3600 s credit would admit at once
    run2(capsys, wait=30.0, refused_since=str(int(NOW - 10 ** 6)))
    assert seen2[0][0]["refused_since"] == int(NOW - 3600)                  # capped at STARVE_REFUSED_SINCE_MAX_S
    run3 = Run(monkeypatch, tmp_path / "c", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen3 = spy(run3)
    run3(capsys, wait=30.0, refused_since=str(int(NOW + 5000)))             # a future value is ignored: the run starts at this call
    assert seen3[0][0]["refused_since"] == int(NOW)


def test_no_hold_file_for_a_bare_check_or_a_clean_admit(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **SOFT)
    seen = spy(run)
    rc, _rec, _ = run(capsys, wait=0.0)
    assert rc == 75 and held_files(run.state) == [] and seen == []
    calm = Run(monkeypatch, tmp_path / "calm", wall0=NOW, LW_FAKE_LOAD1="0.1")
    rc, rec, _ = calm(capsys, wait=60.0)
    assert rc == 0 and rec["status"] == "ok" and held_files(calm.state) == []


def test_a_clean_reading_ends_the_run_and_removes_the_file(monkeypatch, tmp_path, capsys):
    loads = ",".join([str(CORES * 3.0)] * 2 + ["0.1"] * 4)
    run = Run(monkeypatch, tmp_path, wall0=NOW, LW_FAKE_LOAD1=loads, LW_FAKE_CHURN="40000")
    seen = spy(run)
    rc, rec, _ = run(capsys, wait=400.0)
    assert rc == 0 and rec["status"] == "ok"
    assert seen and seen[0] and held_files(run.state) == []


def test_a_bare_check_never_touches_the_registry(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    calls = []
    for name in ("hold_write", "proc_start", "read_holds"):
        monkeypatch.setattr(gh, name, lambda *a, _n=name, **k: calls.append(_n))
    rc, _rec, _ = run(capsys, wait=0.0)
    assert rc == 75 and calls == [] and held_files(run.state) == []


def test_the_first_refused_poll_sweeps_stale_files_of_dead_waiters(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    stale = put(run.state, 2 ** 22 + 77, upd=NOW - 5000)
    seen = spy(run)
    run(capsys, wait=30.0)
    assert not stale.exists() and len(seen[0]) == 1


def test_the_hold_names_the_caller_pid_and_a_supervising_parent_can_override_it(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen = spy(run)
    monkeypatch.delenv("LW_ADMIT_CALLER_PID", raising=False)
    run(capsys, wait=30.0)
    assert seen[0][0]["caller_pid"] == os.getppid() and run.lw.admit_caller_pid() == os.getppid()
    monkeypatch.setenv("LW_ADMIT_CALLER_PID", "4242")
    run2 = Run(monkeypatch, tmp_path / "b", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    seen2 = spy(run2)
    run2(capsys, wait=30.0)
    assert seen2[0][0]["caller_pid"] == 4242
    monkeypatch.setenv("LW_ADMIT_CALLER_PID", "not-a-pid")
    assert run2.lw.admit_caller_pid() == os.getppid()


def test_the_supervised_copy_inherits_the_callers_pid_and_a_bad_value_never_raises(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, LW_FAKE_LOAD1="0.1")
    monkeypatch.setenv("LW_ADMIT_CALLER_PID", "1")
    monkeypatch.delenv("LW_ADMIT_CALLER_PID")                 # absent now, and removed again at teardown whatever admit sets
    got = []
    monkeypatch.setattr(run.lw, "self_deadline", lambda a, poll: got.append(os.environ.get("LW_ADMIT_CALLER_PID")) or 0)
    rc, _rec, _ = run.lw.cmd_admit(__import__("argparse").Namespace(wait=60.0, max_per_core=2.0, json=True, supervise=True)), None, None
    capsys.readouterr()
    assert rc == 0 and got == [str(os.getppid())]
    for bad in ("\u00b2", "\u0661\u0662", "x", "9" * 40, "-3"):
        monkeypatch.setenv("LW_ADMIT_CALLER_PID", bad)
        assert run.lw.admit_caller_pid() == os.getppid()


def test_a_broken_gui_hog_module_changes_neither_the_verdict_nor_the_exit_code(monkeypatch, tmp_path, capsys):
    base = Run(monkeypatch, tmp_path / "a", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    rc0, rec0, _ = base(capsys, wait=60.0)

    def boom():
        raise ImportError("gui_hog is broken")
    run = Run(monkeypatch, tmp_path / "b", wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    monkeypatch.setattr(run.lw, "gui_hog_mod", boom)
    rc, rec, _ = run(capsys, wait=60.0)
    assert (rc, rec["status"], rec["refused"]) == (rc0, rec0["status"], rec0["refused"]) and held_files(run.state) == []
    ok = Run(monkeypatch, tmp_path / "c", wall0=NOW, LW_FAKE_LOAD1="0.1")
    monkeypatch.setattr(ok.lw, "gui_hog_mod", boom)
    assert ok(capsys, wait=60.0)[0] == 0


def test_a_failing_registry_write_changes_neither_the_verdict_nor_the_exit_code(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    run.state.mkdir(parents=True, exist_ok=True)
    (run.state / "held").write_text("a file where the directory should be")   # mkdir and every write fail
    rc, rec, err = run(capsys, wait=60.0)
    assert rc == 75 and rec["status"] == "hot" and "Traceback" not in err
    forced = Run(monkeypatch, tmp_path / "f", wall0=NOW, **SOFT)               # the starvation valve is untouched too
    forced.state.mkdir(parents=True, exist_ok=True)
    (forced.state / "held").write_text("x")
    rc, rec, _ = forced(capsys, wait=600.0)
    assert rc == 0 and rec["forced"] == "starved" and rec["waited_s"] == 300


def test_a_hold_registry_exception_is_swallowed_even_from_hold_write(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))

    def raising(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(gh, "hold_write", raising)
    rc, rec, _ = run(capsys, wait=40.0)
    assert rc == 75 and rec["refused"] == ["load", "compressor"]


def test_hold_file_is_removed_even_when_admit_raises(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=NOW, **dict(SOFT, LW_STARVE_SOFT_S="0"))
    calls = []

    def nap(s):
        calls.append(held_files(run.state))
        if len(calls) == 2:
            raise KeyboardInterrupt
        run.clock[0] += s
    monkeypatch.setattr(run.lw, "nap", nap)
    with pytest.raises(KeyboardInterrupt):
        run(capsys, wait=100.0)
    assert calls[0] and held_files(run.state) == []


# ---- ps_table's tty column --------------------------------------------------------------------------------------------------------------

def test_ps_table_records_pty_attached_pids(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    out = ("  10     1   502   1.5 S    31  1000 ??       /Applications/X.app/Contents/MacOS/X --flag\n"
           "  11    10   502  20.0 R    31  2000 ttys003  make -j8\n"
           "  12    10   502   0.0 S     4   500 -        helper with  spaces   in args\n"
           "  13    10   502   0.0 S     4   500 ?        linux style no tty\n"
           "  bad line\n")
    monkeypatch.setattr(lw.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    lw.PTTY.clear()
    t = lw.ps_table()
    assert set(t) == {"10", "11", "12", "13"} and lw.PTTY == {"11"}
    assert t["10"][3] == "/Applications/X.app/Contents/MacOS/X --flag" and t["12"][3] == "helper with  spaces   in args"
    assert t["11"][2] == pytest.approx(0.2) and lw.PSTATE["11"] == ("R", 2000)


# ---- the sampler's tick, the dry-run log (H1a, I1) -----------------------------------------------------------------------------------------

class World:
    """One sampler in a temp state directory: fake processes (an app using `cores` cores and `rss_mb` MB) and a hold file."""

    def __init__(self, tmp_path, cores=1.0, rss_mb=300, protected=False):
        self.state = tmp_path / "state"
        self.state.mkdir(parents=True)
        self.st = {}
        bid = "com.mitchellh.ghostty" if protected else "com.example.hog"
        self.ls = [{"name": "Hog", "bundle_id": bid, "bundle_path": "/Applications/Hog.app", "exe": "/Applications/Hog.app/Contents/MacOS/hog",
                    "pid": 800, "type": "Foreground"}]
        self.table = {"800": (1, ME, cores, "/Applications/Hog.app/Contents/MacOS/hog")}
        self.rss = {"800": rss_mb * 1024}
        self.exe = {"800": "/Applications/Hog.app/Contents/MacOS/hog"}
        self.lines = []

    def hold(self, t, age=400, refused=("pageins",), pid=None):
        gh.hold_write(self.state, pid or os.getpid(), "S1", "bg", t - age, list(refused), t, 15)

    def tick(self, t, dry=False, **kw):
        return gh.tick(self.st, t, self.table, self.rss, set(), state_dir=self.state, my_uid=ME, agent_clis={"claude"}, load1=7.5, dry=dry,
                       start_of=lambda pid: "S1", cfg=shipped(), lsapps=self.ls, exe_of=lambda p: self.exe.get(str(p)), out=self.lines.append, **kw)

    def log(self):
        p = gh.dry_run_path(self.state)
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_tick_logs_a_would_show_line_once_per_30_minutes(tmp_path):
    w = World(tmp_path)
    t = NOW
    w.hold(t)
    d = w.tick(t)
    assert d["show"] and d["reason"] == "show"
    [line] = w.log()
    assert line["event"] == "would-show" and line["held"][0]["caller"] == "bg" and line["held"][0]["held_s"] == 400
    assert line["held"][0]["refused"] == ["pageins"] and line["cores_hit"] and not line["rss_hit"]
    assert line["apps"][0]["name"] == "Hog" and line["apps"][0]["bundle_id"] == "com.example.hog" and line["load1"] == 7.5
    assert w.st["gui_hog"]["last_shown"] == t
    for later in (t + 20, t + 900, t + 1799):
        w.hold(later)
        assert w.tick(later)["reason"] == "rate-limited"
    assert len(w.log()) == 1
    w.hold(t + 1800)
    assert w.tick(t + 1800)["show"] and len(w.log()) == 2


def test_tick_honours_the_ignore_snooze_file(tmp_path):
    w = World(tmp_path)
    w.hold(NOW)
    (w.state / "gui-hog").mkdir()
    (w.state / "gui-hog" / "snooze.json").write_text(json.dumps({"snooze_until": NOW + 3600}))
    assert w.tick(NOW)["reason"] == "snoozed" and w.log() == []
    w.hold(NOW + 3600)
    assert w.tick(NOW + 3600)["show"] and len(w.log()) == 1


@pytest.mark.parametrize("body", ["garbage", '{"snooze_until": "never"}', '{"snooze_until": null}', "[]"])
def test_a_corrupt_snooze_file_does_not_snooze(tmp_path, body):
    w = World(tmp_path)
    w.hold(NOW)
    (w.state / "gui-hog").mkdir()
    (w.state / "gui-hog" / "snooze.json").write_text(body)
    assert w.tick(NOW)["show"]


def test_tick_needs_a_hold_of_three_minutes_a_relievable_gate_and_enough_app_use(tmp_path):
    w = World(tmp_path)
    assert w.tick(NOW)["reason"] == "no-hold"
    w.hold(NOW + 20, age=100)
    assert w.tick(NOW + 20)["reason"] == "hold-too-short"
    w.hold(NOW + 40, age=400, refused=("agents",))
    assert w.tick(NOW + 40)["reason"] == "not-relievable"
    low = World(tmp_path / "low", cores=0.2, rss_mb=300)
    low.hold(NOW)
    assert low.tick(NOW)["reason"] == "below-threshold" and low.log() == []
    prot = World(tmp_path / "prot", cores=9.0, rss_mb=9000, protected=True)
    prot.hold(NOW)
    assert prot.tick(NOW)["reason"] == "below-threshold"          # Ghostty's bundle id: protected apps never count


def test_apps_under_the_callers_of_a_waiting_admit_are_excluded(tmp_path):
    w = World(tmp_path)
    w.table["700"] = (1, ME, 0.5, "make -j8")     # a caller no argv rule would recognise: only the hold's caller_pid names it
    w.table["800"] = (700, ME, 3.0, "/Applications/Hog.app/Contents/MacOS/hog")
    w.exe["700"] = "/usr/bin/make"
    gh.hold_write(w.state, os.getpid(), "S1", "bg", NOW - 400, ["pageins"], NOW, 15, caller_pid=700)   # the admit's pid is not the caller's
    d = w.tick(NOW)
    assert not d["show"] and d["reason"] == "below-threshold"
    other = World(tmp_path / "other")
    other.table["700"], other.table["800"], other.exe["700"] = w.table["700"], w.table["800"], "/usr/bin/make"
    gh.hold_write(other.state, os.getpid(), "S1", "bg", NOW - 400, ["pageins"], NOW, 15)                  # no caller_pid: the app counts
    assert other.tick(NOW)["show"]


def test_a_caller_pid_of_one_or_out_of_range_is_dropped(tmp_path):
    for cp in (1, 0, 2 ** 31, -5):
        gh.hold_write(tmp_path, os.getpid(), "S1", "bg", NOW - 400, ["load"], NOW, 15, caller_pid=cp)
        [h] = gh.read_holds(tmp_path, NOW, start_of=lambda pid: "S1")
        assert "caller_pid" not in h or h["caller_pid"] is None


@pytest.mark.parametrize("key,bad", [("apps", {"x": 1}), ("apps", "text"), ("app_meta", []), ("gui_hog", []), ("gui_hog", "x"), ("apps", [None, 3, "a"])])
def test_corrupt_state_heals_instead_of_killing_every_tick(tmp_path, key, bad):
    w = World(tmp_path)
    w.hold(NOW)
    w.st[key] = bad
    assert w.tick(NOW)["show"]
    assert isinstance(w.st["apps"], list) and isinstance(w.st["gui_hog"], dict) and isinstance(w.st["app_meta"], dict)


def test_window_entries_without_a_sample_dict_are_dropped_not_fatal(tmp_path):
    w = World(tmp_path)
    w.hold(NOW)
    w.st["apps"] = [{"t": NOW - 10, "a": 5}, {"t": NOW - 10}, {"t": NOW - 10, "a": None, "cpu": 1}]
    assert w.tick(NOW)["show"] and all(isinstance(x["a"], dict) for x in w.st["apps"])


def test_a_huge_snooze_is_clamped_and_a_future_last_shown_is_ignored(tmp_path):
    w = World(tmp_path)
    w.hold(NOW)
    (w.state / "gui-hog").mkdir()
    (w.state / "gui-hog" / "snooze.json").write_text(json.dumps({"snooze_until": NOW + 10 ** 12}))
    assert w.tick(NOW)["reason"] == "snoozed"
    w.hold(NOW + 3601)
    assert w.tick(NOW + 3601)["show"]                              # the snooze never outlasts snooze_s
    w2 = World(tmp_path / "w2")
    w2.hold(NOW)
    w2.st["gui_hog"] = {"last_shown": NOW + 10 ** 9}                # a clock that was set forward once
    assert w2.tick(NOW)["show"]
    assert gh._iso(float("inf")) == "?" and gh._iso(10 ** 30) == "?"


def test_hostile_files_in_the_gui_hog_directory_are_ignored(tmp_path):
    w = World(tmp_path)
    w.hold(NOW)
    g = w.state / "gui-hog"
    g.mkdir()
    os.mkfifo(g / "snooze.json")
    outside = tmp_path / "outside.log"
    outside.write_text("keep")
    (g / "dry-run.jsonl").symlink_to(outside)
    assert gh.read_snooze(w.state) is None
    with pytest.raises(OSError):
        gh.dry_run_append(w.state, {"t": gh._iso(NOW), "event": "would-show"})
    assert outside.read_text() == "keep" and gh.count_dry_run(w.state, 7, NOW) == 0


def test_the_trigger_fires_on_the_rss_sum_alone(tmp_path):
    w = World(tmp_path, cores=0.01, rss_mb=2100)
    w.hold(NOW)
    d = w.tick(NOW)
    assert d["show"] and w.log()[0]["rss_hit"] and not w.log()[0]["cores_hit"]


def test_the_window_accumulates_every_tick_whatever_the_load(tmp_path):
    w = World(tmp_path)
    for i in range(20):
        w.tick(NOW + 20 * i)
    ts = [x["t"] for x in w.st["apps"]]
    assert len(ts) == 16 and ts[0] >= NOW + 380 - 300 and ts == sorted(ts)    # trimmed to 300 s
    assert w.st["app_meta"]["800"]["n"] == "Hog" and w.log() == []            # no hold, no line


def test_dry_flag_prints_and_records_nothing_but_the_window(tmp_path):
    w = World(tmp_path)
    w.hold(NOW)
    d = w.tick(NOW, dry=True)
    assert d["show"] and w.log() == [] and "last_shown" not in w.st["gui_hog"]
    assert len(w.lines) == 1 and w.lines[0].startswith("gui-hog would show dialog: ") and "would-show" in w.lines[0]
    assert (w.state / "held").exists() and len(list((w.state / "held").iterdir())) == 1      # dry-run sweeps nothing


def test_lw_gui_hog_0_switches_the_trigger_and_the_window_off(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.hold(NOW)
    w.st.update({"apps": [{"t": NOW, "cpu": 1, "a": {}}], "app_meta": {"1": {}}})
    monkeypatch.setenv("LW_GUI_HOG", "0")
    assert w.tick(NOW) is None
    assert w.log() == [] and "apps" not in w.st and "app_meta" not in w.st
    monkeypatch.setenv("LW_GUI_HOG", "1")
    assert w.tick(NOW)["show"]


def test_lw_gui_hog_0_in_the_sampler_wrapper(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    monkeypatch.setenv("LW_GUI_HOG", "0")
    boom = []
    monkeypatch.setattr(lw, "gui_hog_mod", lambda: boom.append(1) or (_ for _ in ()).throw(AssertionError("must not import")))
    st = {"apps": [1], "app_meta": {}}
    lw.gui_hog_tick(st, NOW, {}, 1.0, False)
    assert boom == [] and st == {}


def test_names_in_the_log_are_cleaned_and_clipped(tmp_path):
    w = World(tmp_path)
    w.ls[0]["name"] = "Hog\u202e\x1b[2Jevil" + "z" * 200
    w.ls[0]["bundle_id"] = "com.example.hog\u200b\x07"
    w.hold(NOW)
    w.tick(NOW)
    raw = gh.dry_run_path(w.state).read_text()
    assert "\u202e" not in raw and "\\u202e" not in raw and "\\u001b" not in raw and "\\u0007" not in raw and "\\u200b" not in raw
    assert len(w.log()[0]["apps"][0]["name"]) <= 61 and w.log()[0]["apps"][0]["bundle_id"] == "com.example.hog"
    assert (gh.dry_run_path(w.state).stat().st_mode & 0o777) == 0o600


def test_the_dry_run_log_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "DRY_RUN_MAX_BYTES", 200)
    for i in range(10):
        gh.dry_run_append(tmp_path, {"t": gh._iso(NOW), "event": "would-show", "i": i, "pad": "x" * 60})
    p = gh.dry_run_path(tmp_path)
    assert p.with_name(p.name + ".1").exists() and p.stat().st_size < 400
    assert gh.count_dry_run(tmp_path, 1, NOW + 5) >= 4


def test_count_dry_run_counts_would_show_lines_in_the_window_only(tmp_path):
    p = gh.dry_run_path(tmp_path)
    p.parent.mkdir(parents=True)
    old, new = gh._iso(NOW - 10 * 86400), gh._iso(NOW - 3600)
    p.write_text("\n".join([json.dumps({"t": new, "event": "would-show"}), json.dumps({"t": old, "event": "would-show"}),
                            json.dumps({"t": new, "event": "other"}), "not json", json.dumps({"t": "yesterday", "event": "would-show"}),
                            json.dumps({"event": "would-show"}), json.dumps([1])]) + "\n")
    assert gh.count_dry_run(tmp_path, 7, NOW) == 1 and gh.count_dry_run(tmp_path, 30, NOW) == 2
    assert gh.count_dry_run(tmp_path / "none", 7, NOW) == 0


def test_the_sampler_survives_a_failing_gui_hog_step(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    monkeypatch.setattr(lw, "gui_hog_mod", lambda: (_ for _ in ()).throw(RuntimeError("module broke")))
    import argparse
    rc = lw.cmd_sample(argparse.Namespace(dry_run=False, verbose=False))
    assert rc == 0 and "gui-hog error" in (lw.STATE_DIR / "sample.log").read_text()


# ---- admit-log summary (H1) -----------------------------------------------------------------------------------------------------------------

def test_admit_log_summary_gains_the_dry_run_count(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    entry = {"t": gh._iso(__import__("time").time()), "verdict": "ok", "refused": [], "free_mb": 4000, "wait_s": 0}
    (state / "admit-log.jsonl").write_text(json.dumps(entry) + "\n")
    env = dict(os.environ, LW_STATE_DIR=str(state), LW_ADMIT_LOG="")
    for k in ("LW_ADMIT_LOG",):
        env.pop(k)
    r = subprocess.run([sys.executable, str(LW), "admit-log", "summary"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0 and "gui-hog dry-run: 0 would-show lines in the last 7 days" in r.stdout, r
    for _ in range(3):
        gh.dry_run_append(state / "", {"t": gh._iso(__import__("time").time()), "event": "would-show"})
    r = subprocess.run([sys.executable, str(LW), "admit-log", "summary", "--days", "2"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0 and "gui-hog dry-run: 3 would-show lines in the last 2 days" in r.stdout, r
    (state / "admit-log.jsonl").write_text("")
    r = subprocess.run([sys.executable, str(LW), "admit-log", "summary"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 1 and "no admit calls" in r.stdout and "3 would-show lines" in r.stdout


def test_admit_log_summary_is_unchanged_when_the_module_is_broken(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    monkeypatch.setattr(lw, "gui_hog_mod", lambda: (_ for _ in ()).throw(ImportError("x")))
    assert lw.gui_hog_dry_count(7) == ""


# ---- `gui-hog status` (H1) -------------------------------------------------------------------------------------------------------------------

def run_status(state, *args):
    env = dict(os.environ, LW_STATE_DIR=str(state), LW_GUI_HOG_LOCAL="/nonexistent")
    env.pop("LW_GUI_HOG", None)
    return subprocess.run([sys.executable, str(BIN / "gui-hog"), "status", *args], capture_output=True, text=True, env=env, timeout=30)


def test_gui_hog_status_on_an_empty_state_directory(tmp_path):
    r = run_status(tmp_path)
    assert r.returncode == 0, r
    assert "ENABLED" in r.stdout and "decision now: no (no-hold)" in r.stdout and "holds: 0" in r.stdout
    assert "0 would-show lines in the last 7 days" in r.stdout and "0 protected apps hidden" in r.stdout


def test_gui_hog_status_shows_holds_apps_and_the_decision(tmp_path):
    import time
    now = time.time()
    st = {"apps": [{"t": now - 20, "cpu": 4.0, "a": {"800": [0.9, 1200], "801": [0.4, 300, 1], "802": [0.1, 50, 2]}}],
          "app_meta": {"800": {"n": "Hog", "b": "com.example.hog", "p": "/Applications/Hog.app"},
                       "801": {"n": "Ghostty", "b": "com.mitchellh.ghostty", "p": "/Applications/Ghostty.app"},
                       "802": {"n": "Code", "b": "com.microsoft.VSCode", "p": "/Applications/Code.app"}}}
    (tmp_path / "state.json").write_text(json.dumps(st))
    gh.hold_write(tmp_path, os.getpid(), gh.proc_start(os.getpid()) or "", "bg", now - 400, ["pageins", "swapins"], now, 15)
    r = run_status(tmp_path)
    assert r.returncode == 0, r
    assert "decision now: WOULD SHOW (show)" in r.stdout and "bg pid" in r.stdout and "pageins, swapins" in r.stdout
    assert "0.90 cores" in r.stdout and "Hog" in r.stdout and "has a build or terminal inside" in r.stdout and "1 protected apps hidden" in r.stdout
    assert "Ghostty" not in r.stdout     # protected apps are counted, never listed
    j = json.loads(run_status(tmp_path, "--json").stdout)
    assert j["enabled"] and j["decision"]["show"] and [a["name"] for a in j["apps"]][0] == "Hog"


def test_gui_hog_status_reports_the_off_switch(tmp_path):
    env = dict(os.environ, LW_STATE_DIR=str(tmp_path), LW_GUI_HOG="0", LW_GUI_HOG_LOCAL="/nonexistent")
    r = subprocess.run([sys.executable, str(BIN / "gui-hog"), "status"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0 and "OFF (LW_GUI_HOG=0)" in r.stdout


# ---- macOS only (H2): the real lsappinfo and kernel paths -----------------------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="lsappinfo and proc_pidpath are macOS tools")
def test_macos_smoke_lsappinfo_and_kernel_exe():
    ents = gh.collect_lsappinfo()
    assert ents and all(isinstance(e["pid"], int) and e["type"] for e in ents)
    exe = gh.kernel_exe(os.getpid())
    assert exe and os.path.exists(exe)
    start = gh.proc_start(os.getpid())
    assert start and start == gh.proc_start(os.getpid())


def test_kernel_exe_and_proc_start_of_this_process_and_of_a_missing_one():
    if os.path.isdir("/proc/self") or sys.platform == "darwin":
        assert gh.kernel_exe(os.getpid()) and gh.proc_start(os.getpid())
    assert gh.kernel_exe(2 ** 22 + 99991) is None and gh.proc_start(2 ** 22 + 99991) is None
