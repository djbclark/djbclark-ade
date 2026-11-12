"""Offline policy and subprocess integration tests; fake Paseo never contacts a harness."""
import fcntl
import json
import os
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "bin/ade-net-resume"))
Scanner = M["Scanner"]
LEAD = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
MIDDLE = "00000000-0000-0000-0000-000000000003"
ERROR = "[System Error] There was a network issue connecting to the server, please try again."


@pytest.fixture
def fake(tmp_path, monkeypatch):
    data = {"agents": {
        LEAD: {"Id": LEAD, "ParentAgentId": None, "Archived": False, "Status": "running", "Provider": "codex"},
        CHILD: {"Id": CHILD, "ParentAgentId": LEAD, "Archived": False, "Status": "error", "Provider": "antigravity"},
    }, "logs": ERROR, "send_rc": 5}
    fixture = tmp_path / "fixture.json"
    sent = tmp_path / "sent.jsonl"
    executable = tmp_path / "paseo"
    executable.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
d = json.loads(Path(os.environ['FAKE_DATA']).read_text())
a = sys.argv[1:]
if a[:1] == ['ls']:
    print(json.dumps([{'id': k, 'status': v['Status']} for k,v in d['agents'].items()]))
elif a[:2] == ['agent', 'inspect']:
    print(json.dumps(d['agents'][a[2]]))
elif a[:1] == ['logs']:
    print(d['logs'])
elif a[:1] == ['send']:
    with open(os.environ['FAKE_SENT'], 'a') as f: f.write(json.dumps(a)+'\\n')
    sys.exit(d['send_rc'])
else: sys.exit(9)
''')
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_DATA", str(fixture))
    monkeypatch.setenv("FAKE_SENT", str(sent))
    monkeypatch.setattr(Scanner, "healthy", lambda self, url: True)

    def scan(apply=True):
        fixture.write_text(json.dumps(data))
        return Scanner(LEAD, tmp_path / "state", apply).scan()

    return data, scan, sent, tmp_path / "state"


@pytest.mark.parametrize("provider,line", [
    ("antigravity", ERROR),
    ("codex", "[System Error] stream disconnected before completion"),
    ("claude", "[System Error] Connection error."),
    ("pi", "[System Error] fetch failed"),
])
def test_provider_patterns(provider, line):
    assert M["transient"](provider, line)


@pytest.mark.parametrize("line", [
    ERROR + " quota 1302", ERROR + " 1308", ERROR + " 429", ERROR + " auth failed",
    ERROR + " model refusal", "[System Error] quota exceeded", "[System Error] HTTP 401",
    "[System Error] refused due to policy", "[System Error] insufficient credits",
    ERROR + "\nA subsequent user turn", "User quoted: " + ERROR, "", "unknown error",
])
def test_non_network_never_matches(line):
    assert not M["transient"]("antigravity", line)


def test_dry_run_then_apply_and_stale_error_dedup(fake):
    data, scan, sent, state = fake
    assert scan(False) == 0
    assert not sent.exists()
    assert scan() == 0
    args = json.loads(sent.read_text())
    assert args == ["send", "--json", "--no-wait", "--", CHILD, M["PROMPT"]]
    assert scan() == 0
    assert len(sent.read_text().splitlines()) == 1
    assert '"action": "submitted"' in (state / "events.jsonl").read_text()


def test_two_per_hour_across_invocations_and_expiry(fake):
    data, scan, sent, state = fake
    for i in range(3):
        data["logs"] = f"turn {i}\n{ERROR}"
        assert scan() == 0
    assert len(sent.read_text().splitlines()) == 2
    path = state / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["time"] -= 3601
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert scan() == 0
    assert len(sent.read_text().splitlines()) == 3


@pytest.mark.parametrize("change", ["foreign", "cycle", "missing", "archived", "idle", "provider", "quota"])
def test_ineligible_agents(fake, change):
    data, scan, sent, _ = fake
    child = data["agents"][CHILD]
    if change == "foreign": child["ParentAgentId"] = None
    if change == "cycle": child["ParentAgentId"] = CHILD
    if change == "missing": del child["ParentAgentId"]
    if change == "archived": child["Archived"] = True
    if change == "idle": child["Status"] = "idle"
    if change == "provider": child["Provider"] = "unknown"
    if change == "quota": data["logs"] = "[System Error] quota 1308"
    assert scan() == 0
    assert not sent.exists()


def test_grandchild(fake):
    data, scan, sent, _ = fake
    data["agents"][MIDDLE] = {"Id": MIDDLE, "ParentAgentId": LEAD, "Archived": False, "Status": "idle"}
    data["agents"][CHILD]["ParentAgentId"] = MIDDLE
    assert scan() == 0
    assert sent.exists()


def test_both_endpoints_required(fake, monkeypatch):
    _, scan, sent, state = fake
    hosts = []
    def healthy(self, url):
        hosts.append(url)
        return "github" in url
    monkeypatch.setattr(Scanner, "healthy", healthy)
    assert scan() == 0
    assert len(hosts) == 2
    assert not sent.exists()
    assert '"action": "offline"' in (state / "events.jsonl").read_text()


def test_uncertain_send_reservation_survives(fake):
    data, scan, sent, _ = fake
    data["send_rc"] = 1
    with pytest.raises(M["ScanError"]): scan()
    data["send_rc"] = 0
    assert scan() == 0
    assert len(sent.read_text().splitlines()) == 1


def test_corrupt_state_and_overlapping_scanners_fail_closed(fake):
    _, scan, sent, state = fake
    state.mkdir()
    with (state / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert scan() == 3
    (state / "events.jsonl").write_text('{"time":')
    with pytest.raises(ValueError): scan()
    assert not sent.exists()


def test_status_changes_after_probe(fake, monkeypatch):
    _, scan, sent, _ = fake
    original = Scanner.inspect
    calls = 0
    def inspect(self, aid):
        nonlocal calls
        result = original(self, aid)
        if aid == CHILD:
            calls += 1
            if calls >= 3: result["Status"] = "running"
        return result
    monkeypatch.setattr(Scanner, "inspect", inspect)
    assert scan() == 0
    assert not sent.exists()


@pytest.mark.parametrize("args", [["--watch", "nan"], ["--watch", "3601"], ["--interval", "0"]])
def test_watch_bounds(args):
    with pytest.raises(SystemExit) as exc:
        M["main"](["--lead", LEAD, *args])
    assert exc.value.code == 2


def test_invalid_lead_is_clean_error(tmp_path):
    assert M["main"](["--lead", "bad", "--state-dir", str(tmp_path)]) == 2
