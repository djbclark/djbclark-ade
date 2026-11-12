"""Offline policy and subprocess integration tests; fake Paseo never contacts a harness."""
from datetime import datetime, timezone
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
NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc).timestamp()
ERROR = "[System Error] There was a network issue connecting to the server, please try again."


@pytest.fixture
def fake(tmp_path, monkeypatch):
    data = {"agents": {
        LEAD: {"Id": LEAD, "ParentAgentId": None, "Archived": False, "Status": "running", "Provider": "codex"},
        CHILD: {"Id": CHILD, "ParentAgentId": LEAD, "Archived": False, "Status": "error", "Provider": "antigravity", "UpdatedAt": "2026-11-12T20:00:00Z"},
    }, "logs": ERROR, "send_rc": 5, "activity": []}
    fixture = tmp_path / "fixture.json"
    sent = tmp_path / "sent.jsonl"
    executable = tmp_path / "paseo"
    executable.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
d = json.loads(Path(os.environ['FAKE_DATA']).read_text())
a = sys.argv[1:]
if a[:1] == ['ls']:
    assert a == ['ls', '-g', '--background', '--json']
    print(json.dumps([{'id': k, 'status': v['Status']} for k,v in d['agents'].items()]))
elif a[:2] == ['agent', 'inspect']:
    print(json.dumps(d['agents'][a[2]]))
elif a[:1] == ['logs']:
    if '--json' in a:
        print(json.dumps({'agentId': a[1], 'items': d['activity']}))
    else:
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
    monkeypatch.setattr(M["time"], "time", lambda: NOW)

    def scan(apply=True, **options):
        fixture.write_text(json.dumps(data))
        return Scanner(LEAD, tmp_path / "state", apply, **options).scan()

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
        data["agents"][CHILD]["UpdatedAt"] = datetime.fromtimestamp(NOW - i, timezone.utc).isoformat()
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
    assert scan() == 0
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


def test_empty_fresh_logs_fail_closed(tmp_path):
    with pytest.raises(M["ScanError"]):
        Scanner(LEAD, tmp_path).signature({"UpdatedAt": "event-1"}, "  \n")


@pytest.mark.parametrize("suffix", [" Too Many Requests", " 402 payment required", " forbidden", " permission denied", " context length exceeded", " overloaded"])
def test_codex_suffix_fails_closed(suffix):
    assert not M["transient"]("codex", "[System Error] error sending request for url" + suffix)


def test_unresolvable_foreign_agent_does_not_block_descendant(fake):
    data, scan, sent, _ = fake
    orphan = "00000000-0000-0000-0000-000000000004"
    agents = data["agents"]
    data["agents"] = {orphan: {"Id": orphan, "Status": "error", "ParentAgentId": "missing"}, **agents}
    assert scan() == 0
    assert sent.exists()


def test_health_curl_policy(monkeypatch, tmp_path):
    import subprocess
    original = Scanner.healthy
    # The fake fixture is intentionally not used: exercise the real probe method offline.
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "403", "")
    monkeypatch.setattr(subprocess, "run", run)
    scanner = Scanner(LEAD, tmp_path)
    assert original(scanner, "https://api.github.com/")
    argv, kwargs = calls[0]
    assert argv[:2] == ["curl", "-q"]
    assert "--location" not in argv
    assert "--insecure" not in argv
    assert kwargs["timeout"] <= 5
    for code in ("429", "500", "000", "invalid"):
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, code, ""))
        assert not original(scanner, "https://api.github.com/")


def test_stable_error_event_ignores_timeline_rendering(fake):
    data, scan, sent, _ = fake
    assert scan() == 0
    data["logs"] = "different historical rendering\n" + ERROR
    assert scan() == 0
    assert len(sent.read_text().splitlines()) == 1


@pytest.mark.parametrize("remaining", [1, 5, 14.9, 15, 15.99])
def test_short_deadline_does_not_reserve_or_send(fake, monkeypatch, remaining):
    _, scan, sent, state = fake
    monkeypatch.setattr(Scanner, "remaining", lambda self: remaining)
    assert scan() == 0
    assert not sent.exists()
    events = [json.loads(line) for line in (state / "events.jsonl").read_text().splitlines()]
    assert [event["action"] for event in events] == ["deadline-before-reserve"]


def test_full_send_budget_can_reserve(fake, monkeypatch):
    _, scan, sent, state = fake
    monkeypatch.setattr(Scanner, "remaining", lambda self: M["CLI_TIMEOUT"] + M["RESERVE_MARGIN"])
    assert scan() == 0
    assert sent.exists()
    assert '"action": "reserved"' in (state / "events.jsonl").read_text()


@pytest.mark.parametrize("stamp", [
    "2026-11-12T17:00:00Z",  # The outage's old completed reviewers.
    "2026-11-12T19:29:59Z",  # Just outside the default window.
    "2026-11-12T20:00:01Z",  # Future timestamps fail closed.
    "2026-11-12T20:00:00", "garbled", "", None,
])
def test_stale_or_unknown_error_never_probes_or_reserves(fake, monkeypatch, stamp):
    data, scan, sent, state = fake
    data["agents"][CHILD]["UpdatedAt"] = stamp
    def forbidden(*args):
        pytest.fail("ineligible error must be rejected before probes")
    monkeypatch.setattr(Scanner, "healthy", forbidden)
    assert scan() == 0
    assert not sent.exists()
    rows = [json.loads(line) for line in (state / "events.jsonl").read_text().splitlines()]
    assert [row["action"] for row in rows] == ["stale"]


@pytest.mark.parametrize("stamp", ["2026-11-12T19:30:00Z", "2026-11-12T15:00:00-05:00"])
def test_fresh_window_boundary_and_timezone_offsets(fake, stamp):
    data, scan, sent, _ = fake
    data["agents"][CHILD]["UpdatedAt"] = stamp
    assert scan() == 0
    assert sent.exists()


def test_configurable_error_age_window(fake):
    data, scan, sent, _ = fake
    data["agents"][CHILD]["UpdatedAt"] = "2026-11-12T19:15:00Z"
    assert scan(False) == 0
    assert not sent.exists()
    assert scan(max_error_age_minutes=60) == 0
    assert sent.exists()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "1e308"])
def test_invalid_error_age_window(value):
    with pytest.raises(SystemExit) as exc:
        M["main"](["--lead", LEAD, "--max-error-age-minutes", value])
    assert exc.value.code == 2


def test_delivered_assistant_output_skips_fresh_error(fake):
    data, scan, sent, state = fake
    data["activity"] = [
        {"type": "user_message", "text": "please review"},
        {"type": "assistant_message", "text": "done: W1 review https://example.test/pr/1"},
        {"type": "tool_call", "detail": "delivery"},
        {"type": "assistant_message", "text": ERROR},
    ]
    assert scan() == 0
    assert not sent.exists()
    assert '"action": "delivered"' in (state / "events.jsonl").read_text()
    assert '"action": "reserved"' not in (state / "events.jsonl").read_text()


@pytest.mark.parametrize("activity", [
    [{"type": "user_message", "text": "done: quoted by user"}],
    [{"type": "tool_call", "text": "done: tool output"}],
    [{"type": "assistant_message", "text": "> done: quoted"}],
    [{"type": "assistant_message", "text": "```text\ndone: example\n```"}],
    [{"type": "assistant_message", "text": "done: old task"}, {"type": "user_message", "text": "new task"}],
    [{"type": "assistant_message", "text": "done: old output"}, {"type": "assistant_message", "text": "still working"}],
])
def test_only_latest_unquoted_assistant_delivery_counts(fake, activity):
    data, scan, sent, _ = fake
    data["activity"] = activity + [{"type": "assistant_message", "text": ERROR}]
    assert scan() == 0
    assert sent.exists()


def test_error_ages_out_during_probe_without_reservation(fake, monkeypatch):
    data, scan, sent, state = fake
    def healthy(self, url):
        monkeypatch.setattr(M["time"], "time", lambda: NOW + 1801)
        return True
    monkeypatch.setattr(Scanner, "healthy", healthy)
    assert scan() == 0
    assert not sent.exists()
    assert '"action": "reserved"' not in (state / "events.jsonl").read_text()


def test_delivery_appears_before_send_without_reservation(fake, monkeypatch):
    _, scan, sent, state = fake
    calls = 0
    def delivered(self, aid, provider):
        nonlocal calls
        calls += 1
        return calls > 1
    monkeypatch.setattr(Scanner, "delivered", delivered)
    assert scan() == 0
    assert not sent.exists()
    assert '"action": "reserved"' not in (state / "events.jsonl").read_text()
