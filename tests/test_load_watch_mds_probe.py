"""bin/load-watch mds probe (2026-11-01): one log line per episode when mds stays busy, naming Finder and the top
other processes by program name only. No ps, no launchd: mds_probe is fed a fake process table."""
import importlib.machinery
import importlib.util
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
MDS = "/System/Library/Frameworks/CoreServices.framework/Frameworks/Metadata.framework/Support/mds"
FINDER = "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"
STEP = 20


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def table(mds, finder=0.0, extra=None):
    rows = {
        "388": (1, 0, mds, MDS),
        "389": (1, 0, 9.0, "/usr/libexec/mds_stores"),  # not mds: must not count as it, shows in "others"
        "725": (1, 501, finder, FINDER),
        "900": (1, 501, 0.4, "/usr/bin/python3 worker.py"),
    }
    rows.update(extra or {})
    return rows


def run(feed, peers=None):
    lw = load_module()
    lines = []
    lw.log = lines.append
    lw.mds_peers = (lambda: peers) if callable(peers) is False else peers
    st = {"cooldown": {}}
    for t, tab in feed:
        lw.mds_probe(st, t, tab, False)
    return st, lines


def steady(n, tab, start=0):
    return [(start + i * STEP, tab) for i in range(n)]


def test_quiet_mds_records_nothing():
    st, lines = run(steady(20, table(0.1)))
    assert lines == [] and "mds_hot" not in st


def test_sustained_mds_logs_with_finder_and_waits_for_the_span():
    st, lines = run(steady(5, table(0.8, 0.6)))  # t = 0..80: under 120 s
    assert lines == []
    st, lines = run(steady(9, table(0.8, 0.6)))  # t = 0..160
    assert len(lines) == 1
    assert "mds 0.80 cores" in lines[0] and "Finder 0.60" in lines[0]
    assert "mds_stores" in lines[0] and "725" in lines[0]


def test_a_dip_restarts_the_clock():
    feed = steady(4, table(0.8)) + [(80, table(0.1))] + steady(5, table(0.8), start=100)  # hot again from t=100
    st, lines = run(feed)
    assert lines == []  # 80 s since the dip, under 120


def test_a_gap_restarts_the_clock():
    # hot at t=0, then a sleep: the next hot sample is 600 s later; it must not claim 10 minutes of sustained load
    st, lines = run([(0, table(0.8)), (600, table(0.8)), (620, table(0.8))])
    assert lines == []
    st, lines = run([(0, table(0.8)), (600, table(0.8))] + steady(8, table(0.8), start=620))
    assert len(lines) == 1 and "mds 0.80 cores for 2+ min" in lines[0]


def test_cooldown_then_second_line():
    st, lines = run(steady(200, table(0.9)))  # 4000 s
    assert len(lines) == 3  # first at 120, then 1800 s later, then again


def test_arguments_never_reach_the_log():
    extra = {
        "901": (1, 501, 5.0, "env TOKEN=abc123 curl --api-key=sk-x/y"),
        "902": (1, 501, 4.0, "/usr/bin/mysql -pSECRET"),
        "903": (1, 501, 3.0, "/opt/tool --header=Authorization:Bearer-zzz"),
    }
    st, lines = run(steady(9, table(0.8, 0.5, extra)))
    assert len(lines) == 1
    for secret in ("abc123", "sk-x", "SECRET", "Bearer", "TOKEN", "--"):
        assert secret not in lines[0], secret
    assert "901 5.00 env" in lines[0] and "902 4.00 mysql" in lines[0] and "903 3.00 tool" in lines[0]


def test_a_path_argument_does_not_make_a_process_mds_or_finder():
    extra = {
        "910": (1, 501, 3.0, "vim /Users/x/notes/mds "),
        "911": (1, 501, 3.0, "tail -f /tmp/mds"),
        "912": (1, 501, 3.0, "less /System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"),
        "913": (1, 501, 3.0, "/tmp/mds"),  # a program named mds, but not root's
    }
    st, lines = run(steady(9, table(0.1, 0.0, extra)))
    assert lines == [] and "mds_hot" not in st  # only the real (0.1 core) mds counts
    st, lines = run(steady(9, table(0.8, 0.2, extra)))
    assert len(lines) == 1 and "mds 0.80 cores" in lines[0] and "Finder 0.20" in lines[0]
    assert "910 3.00 vim" in lines[0] and "911 3.00 tail" in lines[0]


def test_root_helper_peers_are_appended_to_the_line():
    st, lines = run(steady(9, table(0.8, 0.5)), peers=["6 725 Finder", "3 789 corespotlightd"])
    assert len(lines) == 1 and lines[0].endswith("xpc clients (ports pid name): 6 725 Finder; 3 789 corespotlightd")


def test_no_helper_keeps_the_plain_line():
    st, lines = run(steady(9, table(0.8, 0.5)), peers=None)
    assert len(lines) == 1 and "xpc clients" not in lines[0]


def _peers_with(monkeypatch_run, exists=True):
    from unittest import mock
    lw = load_module()
    with mock.patch.object(lw.os.path, "exists", lambda p: exists), mock.patch.object(lw.subprocess, "run", monkeypatch_run):
        return lw.mds_peers()


class _R:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


def test_mds_peers_runs_sudo_n_on_the_helper_only_and_filters_its_output():
    import subprocess
    calls = []

    def fake(cmd, **kw):
        calls.append((cmd, kw.get("timeout")))
        return _R(0, "7 1 launchd\n4 11463 Finder\n9 5 $(evil)\nnot a line\n" + "".join(f"1 {i} p{i}\n" for i in range(20, 30)))

    out = _peers_with(fake)
    assert calls == [(["sudo", "-n", "/usr/local/libexec/djbclark/mds-xpc-clients"], 20)]
    assert out[:2] == ["7 1 launchd", "4 11463 Finder"] and len(out) == 6 and all("$" not in ln for ln in out)
    assert _peers_with(lambda c, **k: _R(1, "7 1 launchd\n")) is None  # sudo refused: fall back
    assert _peers_with(fake, exists=False) is None

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)

    assert _peers_with(boom) is None


def test_a_long_mds_cooldown_survives_the_prune():
    lw = load_module()
    day = 24 * 3600.0
    lw.COOLDOWN_S, lw.MDS_COOLDOWN_S = 6 * 3600.0, day  # LW_MDS_COOLDOWN_S above LW_COOLDOWN_H
    kept = lw.prune_cooldowns({"mds": 0.0, "nocpu": 0.0, "churn": 5 * 3600.0}, 7 * 3600.0)
    assert kept == {"mds": 0.0, "churn": 5 * 3600.0}  # mds held for its own day, the others for COOLDOWN_S
    assert "mds" not in lw.prune_cooldowns({"mds": 0.0}, day + 1)


def test_status_prints_the_mds_cooldown_as_thirty_minutes():
    lw = load_module()
    src = LW.read_text()
    assert "'mds': MDS_COOLDOWN_S" in src and lw.MDS_COOLDOWN_S == 1800


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
