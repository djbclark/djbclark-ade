"""bin/load-watch sample: the compressor-churn watcher (2026-10-23). No vm_stat (LW_FAKE_COMPRESSOR supplies the
cumulative counters), no launchd, no relay, no ps: a busy host cannot change the answer."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
T0 = 100000.0
STEP = 20.0


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _sampler(tmp_path, monkeypatch, table=None, dry=False):
    lw = load_module()
    clock = {"t": T0}
    pings = tmp_path / "pings.log"
    ping = tmp_path / "ping"
    ping.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> {pings}\n')
    ping.chmod(0o755)
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "HERMES_PING", ping)
    monkeypatch.setattr(lw, "now", lambda: clock["t"])
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (0.5, 0.5, 0.5))  # never hot: only the churn path runs
    monkeypatch.setattr(lw.os, "cpu_count", lambda: 8)
    rows = table if table is not None else {"1": (0, 0, 2.5, "/usr/bin/cc1 -O2"), "2": (0, 0, 1.0, "python3 -m pytest"),
                                            "3": (0, 0, 0.2, "/bin/sh")}
    monkeypatch.setattr(lw, "ps_table", lambda: rows)
    monkeypatch.setattr(lw, "guard", lambda *args: None)
    sent = []
    monkeypatch.setattr(lw, "send_to", lambda w, text: sent.append(text) or True)
    lw.save_watcher({"channel": "paseo", "target": "agent-a"})

    class A:
        verbose = False
    A.dry_run = dry

    def feed(rates, step=STEP, start=T0):
        """Fake counters for samples at start, start+step, ...: rates[i] pages/s between sample i-1 and i (the first
        is ignored); 'reset' makes the counter drop to 0, as after a reboot. Returns the sample times."""
        lw._FAKE_COMPRESSOR_READS[0] = 0
        counters, c = [], 1_000_000.0
        for i, r in enumerate(rates):
            if r == "reset":
                c = 0.0
            elif i:
                c += r * step
            counters.append(c)
        monkeypatch.setenv("LW_FAKE_COMPRESSOR", ",".join(f"{x:.0f}" for x in counters))
        return [start + i * step for i in range(len(rates))]

    def at(t):
        clock["t"] = t
        lw.cmd_sample(A())

    def state():
        return json.loads((tmp_path / "state.json").read_text())

    def pinged():
        return pings.read_text().splitlines() if pings.exists() else []
    at.lw, at.feed, at.sent, at.state, at.pinged = lw, feed, sent, state, pinged
    return at


def test_churn_below_the_admit_limit_never_fires(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    for t in at.feed([0] + [at.lw.ADMIT_CHURN_PAGES_S * 0.9] * 30):  # 10 min just under the limit
        at(t)
    assert at.sent == [] and at.pinged() == []
    assert at.state()["churn_since"] is None
    assert at.state()["churn_pages_s"] == round(at.lw.ADMIT_CHURN_PAGES_S * 0.9)


def test_churn_above_the_limit_for_less_than_the_sustain_time_is_quiet(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    # first sample gives no reading, the second starts the streak: 160 s held at the last sample
    for t in at.feed([0] + [100000] * 9):
        at(t)
    assert at.state()["churn_since"] == T0 + STEP
    assert at.sent == [] and at.pinged() == []
    # the churn ends before 180 s: the streak clears and nothing was said
    for t in at.feed([0, 100000, 100000, 1000, 100000, 100000], start=T0 + 1000):
        at(t)
    assert at.sent == [] and at.pinged() == []


def test_churn_held_for_the_sustain_time_fires_once(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    times = at.feed([0] + [120000] * 30)
    fired_at = None
    for t in times:
        at(t)
        if at.sent and fired_at is None:
            fired_at = t
    assert fired_at == T0 + STEP + at.lw.CHURN_SUSTAIN_S  # exactly when the streak reaches LW_CHURN_SUSTAIN_S
    assert len(at.sent) == 1 and len(at.pinged()) == 1  # one line each, not one per sample
    msg = at.sent[0]
    assert "compressor churn ~120k pages/s for 3+ min (limit 20k)" in msg
    assert "top: cc1 -O2 2.5 cores, python3 -m 1.0 cores, sh 0.2 cores" in msg
    assert "Admit already holds new bg/acp-dispatch work; this is running or bypass work." in msg
    assert "Do not kill or SIGSTOP without djbclark. Investigate per the loadwatch skill." in msg
    assert "Investigate per the loadwatch skill; do not kill or SIGSTOP without djbclark." in at.pinged()[0]
    assert "Standing exception" not in msg
    assert at.pinged()[0].startswith("djbclark-ade: load-watch: compressor churn ~120k pages/s")
    cd = at.state()["cooldown"]
    assert "churn" in cd and "churn-watcher" in cd
    assert not (tmp_path / "incidents.jsonl").exists()  # no ledger row


def test_second_fire_inside_the_cooldown_is_silent(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    lw = at.lw
    for t in at.feed([0] + [120000] * 12):  # first alert
        at(t)
    assert len(at.sent) == 1 and len(at.pinged()) == 1
    # churn drops, then a new episode sustained again 30 min later: both cooldowns still hold
    for t in at.feed([0, 1000, 120000, 120000, 120000, 120000, 120000, 120000, 120000, 120000, 120000, 120000],
                     start=T0 + 1800):
        at(t)
    assert len(at.sent) == 1 and len(at.pinged()) == 1
    # an hour on, the watcher hears the recurrence, Hermes (6 h cooldown) does not
    start = T0 + lw.WATCHER_NOCPU_S + 600
    for t in at.feed([0] + [120000] * 12, start=start):
        at(t)
    assert len(at.sent) == 2 and len(at.pinged()) == 1


def test_status_lists_both_churn_cooldowns(tmp_path, monkeypatch, capsys):
    at = _sampler(tmp_path, monkeypatch)
    for t in at.feed([0] + [120000] * 12):
        at(t)
    capsys.readouterr()
    at.lw.cmd_status(None)
    out = capsys.readouterr().out
    assert "cooldown churn until" in out and "cooldown churn-watcher until" in out
    assert "compressor churn 120k pages/s" in out


def test_a_counter_that_goes_backwards_resets_the_streak(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    # 160 s held, then the counter resets (reboot): the 180 s must start over, not carry on
    times = at.feed([0] + [120000] * 8 + ["reset"] + [120000] * 8)
    for t in times[:9]:
        at(t)
    assert at.state()["churn_since"] == T0 + STEP
    at(times[9])
    assert at.state()["churn_since"] is None and "churn_pages_s" not in at.state()
    for t in times[10:]:
        at(t)  # 160 s held again after the reset: still under 180
    assert at.sent == [] and at.pinged() == []
    assert at.state()["churn_since"] == times[10]


def test_a_long_gap_is_a_sleep_not_churn(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    # the last counter jump is 120000 * 60 * 20 pages: ~160k pages/s over the 901 s the machine slept
    times = at.feed([0, 120000, 120000, 120000 * 60])
    for t in times[:3]:
        at(t)
    assert at.state()["churn_since"] is not None
    at(times[2] + at.lw.MAX_GAP_S + 1)  # the delta spans the sleep: no reading, whatever its size
    assert at.state()["churn_since"] is None


def test_older_state_json_without_the_churn_keys_loads(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    (tmp_path / "state.json").write_text(json.dumps({"t": T0 - STEP, "hot_since": None, "streak": 0, "samples": [],
                                                      "load1": 0.3, "cooldown": {"nocpu": T0 - 60}}))
    for t in at.feed([0, 120000, 120000]):
        at(t)
    st = at.state()
    assert st["churn_since"] == T0 + STEP and st["cooldown"] == {"nocpu": T0 - 60}
    # and a state.json with no cooldown key at all
    (tmp_path / "state.json").write_text(json.dumps({"t": T0 - STEP, "samples": [], "streak": 0}))
    at(T0)
    assert "churn_prev" in at.state()


def test_grok_chrome_windowserver_add_the_exception_but_still_alert(tmp_path, monkeypatch):
    table = {"1": (0, 0, 0.9, "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper (Renderer)"
                             ".app/Contents/MacOS/Google Chrome Helper (Renderer) --type=renderer"),
             "2": (0, 0, 0.4, "/usr/bin/cc1")}
    at = _sampler(tmp_path, monkeypatch, table=table)
    for t in at.feed([0] + [120000] * 12):
        at(t)
    assert len(at.sent) == 1 and len(at.pinged()) == 1
    assert "Google Chrome Helper (Renderer) 0.9 cores" in at.sent[0]
    assert "Standing exception: Grok Bot/Chrome" in at.sent[0] and "Standing exception" in at.pinged()[0]


def test_dry_run_prints_and_records_nothing(tmp_path, monkeypatch, capsys):
    at = _sampler(tmp_path, monkeypatch, dry=True)
    for t in at.feed([0] + [120000] * 12):
        at(t)
    out = capsys.readouterr().out
    assert "compressor churn ~120k pages/s" in out  # the message and the watcher line are printed
    assert at.sent == [] and at.pinged() == []
    assert "churn" not in at.state()["cooldown"] and "churn-watcher" not in at.state()["cooldown"]


def test_no_vm_stat_changes_nothing(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    monkeypatch.delenv("LW_FAKE_COMPRESSOR", raising=False)
    monkeypatch.setattr(at.lw, "_compressor_pages", lambda: None)
    at(T0)
    at(T0 + STEP)
    st = at.state()
    assert not any(k.startswith("churn") for k in st) and at.sent == [] and at.pinged() == []
