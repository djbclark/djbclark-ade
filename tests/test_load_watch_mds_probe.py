"""bin/load-watch mds probe (2026-11-01): one log line per episode when mds stays busy, naming Finder and the top
other processes. No ps, no launchd: mds_probe is fed a fake process table."""
import importlib.machinery
import importlib.util
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
MDS = "/System/Library/Frameworks/CoreServices.framework/Frameworks/Metadata.framework/Support/mds"
FINDER = "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def table(mds, finder=0.0):
    return {
        "388": (1, 0, mds, MDS),
        "389": (1, 0, 9.0, "/usr/libexec/mds_stores"),  # not mds: must not count as it, shows in "others"
        "725": (1, 501, finder, FINDER),
        "900": (1, 501, 0.4, "/usr/bin/python3 worker.py"),
    }


def run(feed):
    lw = load_module()
    lines = []
    lw.log = lines.append
    st = {"cooldown": {}}
    for t, tab in feed:
        lw.mds_probe(st, t, tab, False)
    return st, lines


def test_quiet_mds_records_nothing():
    st, lines = run([(0, table(0.1)), (300, table(0.2))])
    assert lines == [] and "mds_hot" not in st


def test_sustained_mds_logs_once_per_episode_with_finder():
    st, lines = run([(0, table(0.8, 0.6)), (60, table(0.8, 0.6)), (125, table(0.7, 0.5)), (200, table(0.7, 0.5))])
    assert len(lines) == 1  # not before 120 s, once after
    assert "mds 0.70 cores" in lines[0] and "Finder 0.50" in lines[0]
    assert "mds_stores" in lines[0] and "725" in lines[0]


def test_a_dip_restarts_the_clock():
    st, lines = run([(0, table(0.8)), (100, table(0.1)), (130, table(0.8)), (200, table(0.8))])
    assert lines == []  # 70 s since the dip, under 120


def test_cooldown_then_second_line():
    feed = [(t, table(0.9)) for t in range(0, 4000, 100)]
    st, lines = run(feed)
    assert len(lines) == 3  # t=120->first at 200, then 1800 s later at 2000, then 3800


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
