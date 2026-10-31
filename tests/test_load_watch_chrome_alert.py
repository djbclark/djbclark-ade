"""load-watch chrome_alert (2026-10-25): one Chrome process at 0.9+ cores for 5 min tells the watcher, once an hour."""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
MAIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --profile-directory=Default https://example.com/"
TESTING = "/x/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"


def load():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def table(cores, cmd=MAIN, pid=7):
    return {pid: (1, 501, cores, cmd)}


def test_sustained_hot_chrome_process_is_told_once(monkeypatch):
    lw = load()
    sent = []
    monkeypatch.setattr(lw, "tell_watcher", lambda text, dry, skip=(): sent.append(text) or True)
    monkeypatch.setattr(lw, "log", lambda *_a, **_k: None)
    st = {"cooldown": {}}
    lw.chrome_alert(st, 1000.0, table(1.0), False)
    assert sent == []  # just started
    lw.chrome_alert(st, 1000.0 + lw.CHROME_SUSTAIN_S, table(1.0), False)
    assert len(sent) == 1 and "pid 7" in sent[0] and "browser (main) process" in sent[0]
    assert "https://example.com/" in sent[0] and "Shift+Esc" in sent[0]
    lw.chrome_alert(st, 1000.0 + lw.CHROME_SUSTAIN_S + 60, table(1.0), False)
    assert len(sent) == 1  # hourly cooldown per process


def test_a_dip_resets_and_testing_chrome_is_ignored(monkeypatch):
    lw = load()
    sent = []
    monkeypatch.setattr(lw, "tell_watcher", lambda text, dry, skip=(): sent.append(text) or True)
    monkeypatch.setattr(lw, "log", lambda *_a, **_k: None)
    st = {"cooldown": {}}
    lw.chrome_alert(st, 0.0, table(1.2), False)
    lw.chrome_alert(st, 200.0, table(0.1), False)  # dipped: the clock restarts
    lw.chrome_alert(st, 400.0, table(1.2), False)
    lw.chrome_alert(st, 400.0 + lw.CHROME_SUSTAIN_S - 1, table(1.2), False)
    assert sent == []
    lw.chrome_alert(st, 0.0, table(3.0, TESTING, pid=9), False)
    lw.chrome_alert(st, 10_000.0, table(3.0, TESTING, pid=9), False)
    assert sent == []


@pytest.mark.parametrize("suffix,kind,tab_action", [
    ("", "browser (main) process", False),
    (" --type=gpu-process", "GPU process", False),
    (" --type=utility", "utility", False),
    (" --type=renderer", "tab renderer", True),
])
def test_guidance_requires_task_identity_before_a_tab_action(monkeypatch, suffix, kind, tab_action):
    lw = load()
    sent = []
    monkeypatch.setattr(lw, "tell_watcher", lambda text, dry, skip=(): sent.append(text) or True)
    monkeypatch.setattr(lw, "log", lambda *_a, **_k: None)
    st = {"cooldown": {}}
    lw.chrome_alert(st, 0.0, table(1.0, MAIN + suffix), False)
    lw.chrome_alert(st, lw.CHROME_SUSTAIN_S, table(1.0, MAIN + suffix), False)
    assert len(sent) == 1
    message = sent[0]
    assert kind in message and "match pid 7 to its task" in message
    assert "Do not kill, reload, or restart Chrome yourself" in message
    if tab_action:
        assert "Only if the task is an identified tab and djbclark chooses" in message
        assert "End process on that tab" in message
    else:
        assert "does not identify a busy tab" in message
        assert "Report the task name and CPU percentage" in message
        assert "End process" not in message
