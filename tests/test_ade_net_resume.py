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
open(os.environ['FAKE_CALLS'], 'a').write(json.dumps(a) + '\\n')
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
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls.jsonl"))
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



def test_delivery_combined_with_terminal_error_is_still_detected(fake):
    data, scan, sent, state = fake
    data["activity"] = [{"type": "assistant_message", "text": "done: review delivered\n" + ERROR}]
    assert scan() == 0
    assert not sent.exists()
    assert '"action": "delivered"' in (state / "events.jsonl").read_text()


# --- --quota pass (docs/net-resume.md, "Quota resume") ---------------------------------------------
# The real rendered last line of a z.ai 5-hour stop (agent f2802e7c, 2026-11-12T20:20:03Z).
QLINE = ('[System Error] 429: {"code":"1308","message":"Usage limit reached for 5 hour. '
         'Your limit will reset at 2026-11-13 06:14:11"} (stopReason=error, model=zai/glm-5.3-flash)')
CHILD2 = "00000000-0000-0000-0000-000000000005"
RESET = "2026-11-12T20:30:00+00:00"


def at(hour, minute):
    return datetime(2026, 11, 12, hour, minute, tzinfo=timezone.utc).timestamp()


def window(state="exhausted", used=100.0, resets=RESET, minutes=300, window_id="primary"):
    return {"window_id": window_id, "label": "z.ai 5-hour", "state": state, "used_percent": used,
            "window_minutes": minutes, "resets_at": resets}


def account(windows, collected="2026-11-12T19:59:30+00:00", fresh=True, usable=False, stale=False, provider="zai"):
    return {"provider": provider, "windows": windows, "collected_at": collected, "fresh": fresh,
            "stale": stale, "usable_now": usable}


def exhausted_account(**kw):
    return account([window()], **kw)


def reset_account(**kw):
    options = {"collected": "2026-11-12T20:34:00+00:00", "usable": True}
    options.update(kw)
    return account([window("ok", 0.0, None)], **options)


@pytest.fixture
def quota(fake, tmp_path, monkeypatch):
    data, base_scan, sent, state = fake
    aiuse_file = tmp_path / "aiuse.json"
    executable = tmp_path / "aiuse"
    executable.write_text('#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\n'
                          'Path(os.environ["FAKE_AIUSE"] + ".called").touch()\n'
                          'p = Path(os.environ["FAKE_AIUSE"])\nif not p.exists(): sys.exit(3)\n'
                          'sys.stdout.write(p.read_text())\n')
    executable.chmod(0o755)
    monkeypatch.setenv("FAKE_AIUSE", str(aiuse_file))
    data["agents"][CHILD].update(Provider="pi", Model="zai/glm-5.3-flash", UpdatedAt="2026-11-12T19:59:00Z")
    data["logs"] = QLINE
    data["activity"] = [{"type": "user_message", "text": "review"}, {"type": "assistant_message", "text": QLINE}]
    guard = tmp_path / "guard.json"

    def put(*accounts, raw=None):
        aiuse_file.write_text(raw if raw is not None else json.dumps({"snapshot": {"accounts": list(accounts)}}))

    def scan(apply=True, **options):
        return base_scan(apply, quota=True, guard_state=guard, **options)

    def clock(when):
        monkeypatch.setattr(M["time"], "time", lambda: when)

    def rows():
        path = state / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def actions(agent=CHILD):
        return [r["action"] for r in rows() if r["agent"] == agent]

    def waiting():
        """Record the quota-wait at 20:00 while aiuse shows the window exhausted."""
        put(exhausted_account())
        assert scan() == 0
        assert actions() == ["quota-wait"]

    return {"data": data, "scan": scan, "put": put, "clock": clock, "rows": rows, "actions": actions,
            "wait": waiting, "sent": sent, "state": state, "guard": guard, "aiuse_file": aiuse_file,
            "plain": base_scan}


def test_quota_line_policy():
    assert M["quota_line"]("zai", QLINE)
    assert not M["transient"]("pi", QLINE)  # The network path still rejects 1308.
    for line in [QLINE + " billing", QLINE.replace("1308", "1113"), "[System Error] 401: unauthorized",
                 "[System Error] 403 forbidden", QLINE.replace("5 hour", "1 week"),
                 QLINE + "\nfollow-up", "User quoted: " + QLINE, "", "[System Error] insufficient credit balance"]:
        assert not M["quota_line"]("zai", line)
    assert not M["quota_line"]("other", QLINE)


def test_pool_mapping():
    assert M["pool_of"]({"Provider": "pi", "Model": "zai/glm-5.3-flash"}) == "zai"
    for record in [{"Provider": "claude", "Model": "zai/x"}, {"Provider": "pi", "Model": "opencode-go/x"},
                   {"Provider": "pi"}, {"Provider": "pi", "Model": 3}]:
        assert M["pool_of"](record) is None


def test_d1_quota_error_records_wait_without_send(quota):
    quota["wait"]()
    assert not quota["sent"].exists()
    row = next(r for r in quota["rows"]() if r["action"] == "quota-wait")
    assert (row["pool"], row["window_id"], row["window_minutes"], row["resets_at"], row["updated_at"]) == (
        "zai", "primary", 300, RESET, "2026-11-12T19:59:00Z")
    assert quota["scan"]() == 0  # A repeat scan neither re-records nor sends.
    assert quota["actions"]() == ["quota-wait"]
    assert not quota["sent"].exists()


def test_d2_resume_after_reset_dry_run_then_apply(quota):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"](False) == 0
    assert quota["actions"]() == ["quota-wait", "would-resume-quota"]
    assert not quota["sent"].exists()
    assert quota["scan"]() == 0
    assert json.loads(quota["sent"].read_text()) == ["send", "--json", "--no-wait", "--", CHILD, M["QUOTA_PROMPT"]]
    assert quota["actions"]() == ["quota-wait", "would-resume-quota", "reserved", "submitted"]
    assert quota["scan"]() == 0  # One reserved row per error event: never a second send.
    assert len(quota["sent"].read_text().splitlines()) == 1


def test_quota_is_off_by_default(quota):
    quota["put"](exhausted_account())
    assert quota["plain"]() == 0
    assert not quota["sent"].exists()
    assert quota["rows"]() == []
    assert not (quota["aiuse_file"].parent / "aiuse.json.called").exists()  # aiuse was never even called


@pytest.mark.parametrize("sample", [
    {"account": lambda: reset_account(fresh=False)},
    {"account": lambda: reset_account(stale=True)},
    {"account": lambda: reset_account(usable=False)},
    {"account": lambda: reset_account(collected="2026-11-12T20:30:59+00:00")},  # before reset + 60 s grace
    {"account": lambda: reset_account(collected="2026-11-12T20:36:00+00:00")},  # in the future
    {"account": lambda: reset_account(collected="2026-11-12T20:34:00")},  # no timezone
    {"account": lambda: account([window()], collected="2026-11-12T20:34:00+00:00", usable=True)},  # still exhausted
    {"account": lambda: account([window("ok", 0.0, None, window_id="other")], collected="2026-11-12T20:34:00+00:00", usable=True)},
    {"account": lambda: account([window("ok", 96.0, None)], collected="2026-11-12T20:34:00+00:00", usable=True)},
    {"account": lambda: account([window("ok", 0.0, None), window("exhausted", 100.0, "2026-11-18T14:56:01+00:00", 10080, "secondary")],
                                collected="2026-11-12T20:34:00+00:00", usable=True)},  # weekly binds despite usable_now
    {"account": lambda: account([window("ok", 0.0, None), {**window("exhausted", 100.0, None, 10080, "x"), "window_minutes": None}],
                                collected="2026-11-12T20:34:00+00:00", usable=True)},  # unknown-length window
    {"account": lambda: reset_account(provider="claude")},  # missing account
    {"raw": "not json"}, {"raw": "[]"}, {"raw": '{"snapshot": {"accounts": "x"}}'}, {"none": True},
])
def test_d3_unconfirmed_reset_never_resumes(quota, sample):
    quota["wait"]()
    quota["clock"](at(20, 35))
    if sample.get("none"):
        quota["aiuse_file"].unlink()  # aiuse exits non-zero: no reading at all
    if "account" in sample:
        quota["put"](sample["account"]())
    elif "raw" in sample:
        quota["put"](raw=sample["raw"])
    for apply in (False, True):
        assert quota["scan"](apply) == 0
    assert not quota["sent"].exists()
    assert not {"would-resume-quota", "reserved", "submitted"} & set(quota["actions"]())


def test_d3_collected_exactly_at_grace_is_enough(quota):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account(collected="2026-11-12T20:31:00+00:00"))
    assert quota["scan"]() == 0
    assert quota["sent"].exists()


def test_d3_missing_aiuse_binary_fails_closed(quota, monkeypatch):
    quota["wait"]()
    quota["clock"](at(20, 35))
    import subprocess
    original = subprocess.run
    def run(argv, *args, **kwargs):
        if argv[0] == "aiuse":
            raise FileNotFoundError("aiuse")
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)
    assert quota["scan"]() == 0
    assert not quota["sent"].exists()


@pytest.mark.parametrize("change", ["toplevel", "archived", "user-message", "guard", "delivered", "output-after"])
def test_d4_ineligible_agents_are_skipped(quota, change):
    data = quota["data"]
    child = data["agents"][CHILD]
    if change == "toplevel": child["ParentAgentId"] = None
    if change == "archived": child["Archived"] = True
    if change == "guard":
        quota["guard"].write_text(json.dumps({"pauses": [{"agentId": CHILD, "phase": "waiting-reset"}]}))
    if change in ("toplevel", "archived", "guard"):
        quota["put"](exhausted_account())
        assert quota["scan"]() == 0
        assert "quota-wait" not in quota["actions"]()
        assert not quota["sent"].exists()
        return
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    activity = data["activity"]
    if change == "user-message": activity.append({"type": "user_message", "text": "new task"})
    if change == "output-after": activity.append({"type": "assistant_message", "text": "I kept working"})
    if change == "delivered": activity.insert(1, {"type": "assistant_message", "text": "done: W1 https://example.test/1"})
    for apply in (False, True):
        assert quota["scan"](apply) == 0
    assert not quota["sent"].exists()
    assert "reserved" not in quota["actions"]()


def test_d4_guard_pause_in_terminal_phase_does_not_block(quota):
    quota["guard"].write_text(json.dumps({"pauses": [{"agentId": CHILD, "phase": "resumed"},
                                                     {"agentId": CHILD2, "phase": "waiting"}]}))
    quota["wait"]()


def test_d4_guard_pause_appearing_before_send_blocks(quota, monkeypatch):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    calls = 0
    def pending(self, aid):
        nonlocal calls
        calls += 1
        return calls > 1
    monkeypatch.setattr(Scanner, "guard_pending", pending)
    assert quota["scan"]() == 0
    assert not quota["sent"].exists()
    assert "reserved" not in quota["actions"]()


@pytest.mark.parametrize("line", [
    '[System Error] 401: {"code":"1113","message":"Insufficient balance or no resource package."}',
    "[System Error] 403 Forbidden", QLINE + " credit", QLINE.replace("1308", "1113"),
])
def test_d5_auth_billing_and_balance_errors_never_qualify(quota, line):
    quota["data"]["logs"] = line
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"]() == []
    assert not quota["sent"].exists()


def test_d6_reset_older_than_staleness_window_is_stale(quota):
    quota["wait"]()
    quota["clock"](at(21, 5))  # 35 minutes after the reset; default window 30
    quota["put"](reset_account(collected="2026-11-12T21:04:00+00:00"))
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-wait", "stale"]
    assert not quota["sent"].exists()
    assert quota["scan"](max_error_age_minutes=60) == 0  # `stale` is a note, not a terminal state: a wider window resumes.
    assert quota["sent"].exists()


def test_d6_reset_farther_from_error_than_the_window_is_stale(quota):
    quota["put"](account([window(resets="2026-11-13T01:30:00+00:00")]))  # 5.5 h after the 19:59 error
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["stale"]


def test_d6_reset_before_the_error_is_stale(quota):
    quota["put"](account([window(resets="2026-11-12T19:00:00+00:00")]))
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["stale"]


def test_weekly_or_unconfirmed_windows_never_wait(quota):
    quota["put"](account([window(), window("exhausted", 100.0, "2026-11-18T14:56:01+00:00", 10080, "secondary")]))
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-excluded"]
    quota["put"](account([window("ok", 12.0, None)]))
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-excluded", "quota-unconfirmed"]
    assert not quota["sent"].exists()


def test_d7_one_resume_per_pool_per_scan_and_a_gap_between_scans(quota):
    data = quota["data"]
    data["agents"][CHILD2] = {**data["agents"][CHILD], "Id": CHILD2}
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"](CHILD) == quota["actions"](CHILD2) == ["quota-wait"]
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    sent_to = lambda: [json.loads(line)[4] for line in quota["sent"].read_text().splitlines()]
    assert quota["scan"]() == 0
    assert sent_to() == [CHILD]
    assert quota["scan"](quota_per_pool=5) == 0  # Even a larger per-scan cap cannot beat the ledger gap.
    assert sent_to() == [CHILD]
    assert quota["actions"](CHILD2)[-1] == "pool-gap"
    quota["clock"](at(20, 36))
    assert quota["scan"]() == 0
    assert sent_to() == [CHILD]
    quota["clock"](at(20, 46))  # Ten minutes after the first reservation (still inside the 30-minute stale window).
    quota["put"](reset_account(collected="2026-11-12T20:45:00+00:00"))
    assert quota["scan"]() == 0
    assert sent_to() == [CHILD, CHILD2]


def test_d8_closed_agent_with_unchanged_ledger_entry_is_resumed(quota):
    quota["wait"]()
    quota["data"]["agents"][CHILD]["Status"] = "closed"
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"]() == 0
    assert quota["sent"].exists()
    assert quota["actions"]()[-2:] == ["reserved", "submitted"]


def test_d8_closed_agent_with_changed_updated_at_is_changed(quota):
    quota["wait"]()
    quota["data"]["agents"][CHILD].update(Status="closed", UpdatedAt="2026-11-12T20:10:00Z")
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"]() == 0
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-wait", "changed"]  # Recorded once, not once per scan.
    assert not quota["sent"].exists()


def test_closed_agent_without_a_ledger_entry_is_never_touched(quota):
    quota["data"]["agents"][CHILD]["Status"] = "closed"
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"]() == []


def test_d9_crash_between_reserve_and_send_is_not_retried(quota):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    quota["data"]["send_rc"] = 1
    assert quota["scan"]() == 0
    quota["data"]["send_rc"] = 0
    assert quota["scan"]() == 0
    assert len(quota["sent"].read_text().splitlines()) == 1
    assert quota["actions"]().count("reserved") == 1


def test_short_deadline_does_not_reserve_quota_resume(quota, monkeypatch):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    monkeypatch.setattr(Scanner, "remaining", lambda self: 5)
    assert quota["scan"]() == 0
    assert not quota["sent"].exists()
    assert quota["actions"]()[-1] == "deadline-before-reserve"


def test_d10_only_agent_excludes_every_other_agent(quota):
    data = quota["data"]
    data["agents"][CHILD2] = {**data["agents"][CHILD], "Id": CHILD2}
    quota["put"](exhausted_account())
    assert quota["scan"](only_agents=[CHILD2]) == 0
    assert quota["actions"](CHILD) == []
    assert quota["actions"](CHILD2) == ["quota-wait"]


def test_d10_only_agent_restricts_the_network_pass_too(fake):
    _, scan, sent, _ = fake
    assert scan(only_agents=[MIDDLE]) == 0
    assert not sent.exists()
    assert scan(only_agents=[CHILD]) == 0
    assert sent.exists()


def test_malformed_quota_ledger_fails_closed(quota):
    quota["wait"]()
    path = quota["state"] / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    del rows[0]["resets_at"]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(M["ScanError"]):
        quota["scan"]()
    assert not quota["sent"].exists()


@pytest.mark.parametrize("args", [["--quota-per-pool", "0"], ["--quota-grace-seconds", "-1"],
                                  ["--quota-grace-seconds", "nan"], ["--only-agent", "bad"]])
def test_quota_flag_bounds(args, tmp_path):
    try:
        rc = M["main"](["--lead", LEAD, "--state-dir", str(tmp_path), *args])
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2


def test_delivered_before_the_stop_never_arms_a_wait(quota):
    quota["data"]["activity"] = [{"type": "user_message", "text": "review"},
                                 {"type": "assistant_message", "text": "done: W1 https://example.test/pr/1"},
                                 {"type": "assistant_message", "text": QLINE}]
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["delivered"]
    quota["data"]["agents"][CHILD]["Status"] = "closed"  # Idle collection afterwards changes nothing.
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"]() == 0
    assert not quota["sent"].exists()


def test_user_message_after_the_stop_never_arms_a_wait(quota):
    quota["data"]["activity"].append({"type": "user_message", "text": "stop, do something else"})
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["changed"]


@pytest.mark.parametrize("change", ["archived", "guard", "old-reset", "pool", "reserved"])
def test_closed_path_negative_cases(quota, change):
    quota["wait"]()
    child = quota["data"]["agents"][CHILD]
    child["Status"] = "closed"
    if change == "archived": child["Archived"] = True
    if change == "guard": quota["guard"].write_text(json.dumps({"pauses": [{"agentId": CHILD, "phase": "waiting"}]}))
    if change == "pool": child["Model"] = "opencode-go/glm"
    quota["clock"](at(21, 5) if change == "old-reset" else at(20, 35))
    quota["put"](reset_account(collected="2026-11-12T21:04:00+00:00") if change == "old-reset" else reset_account())
    if change == "reserved":
        assert quota["scan"]() == 0
        assert quota["scan"]() == 0
        assert len(quota["sent"].read_text().splitlines()) == 1
        return
    assert quota["scan"]() == 0
    assert not quota["sent"].exists()


def logs_calls():
    path = Path(os.environ["FAKE_CALLS"])
    calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [c for c in calls if c[0] == "logs"]


def test_closed_agent_timeline_is_never_read(quota):
    quota["wait"]()
    quota["data"]["agents"][CHILD]["Status"] = "closed"
    before = len(logs_calls())
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"]() == 0
    assert quota["sent"].exists()
    assert len(logs_calls()) == before  # Paseo's timeline fetch would reload a non-live agent.


@pytest.mark.parametrize("stamp_", ["2026-11-09T19:59:00Z", "2026-11-12T20:00:01Z", "2026-11-12T13:00:00Z"])
def test_old_or_future_error_agent_is_never_read(quota, stamp_):
    quota["data"]["agents"][CHILD]["UpdatedAt"] = stamp_  # 3 days old, in the future, 7 h old (> 360 min + 30)
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert logs_calls() == []
    assert quota["actions"]() == []


def test_waiting_agent_is_not_re_read_until_the_reset(quota):
    quota["wait"]()
    first = len(logs_calls())
    assert first >= 1
    for _ in range(3):
        assert quota["scan"]() == 0
    assert len(logs_calls()) == first


def test_would_resume_is_written_once_per_error_event(quota):
    quota["wait"]()
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    for _ in range(3):
        assert quota["scan"](False) == 0
    assert quota["actions"]().count("would-resume-quota") == 1


@pytest.mark.parametrize("status", ["error", "closed"])
@pytest.mark.parametrize("mutation", ["archived", "updated-at", "not-descendant", "status", "pool"])
def test_pre_send_reinspection_blocks_each_change(quota, monkeypatch, status, mutation):
    quota["wait"]()
    quota["data"]["agents"][CHILD]["Status"] = status
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    armed = {"on": False, "used": False}
    original_guard = Scanner.guard_pending
    original_inspect = Scanner.inspect
    def guard(self, aid):
        armed["on"] = True  # The first call precedes the pre-send re-read.
        return original_guard(self, aid)
    def inspect(self, aid):
        record = original_inspect(self, aid)
        if aid == CHILD and armed["on"]:
            armed["used"] = True
            if mutation == "archived": record["Archived"] = True
            if mutation == "updated-at": record["UpdatedAt"] = "2026-11-12T20:10:00Z"
            if mutation == "not-descendant": record["ParentAgentId"] = None
            if mutation == "status": record["Status"] = "idle"
            if mutation == "pool": record["Model"] = "opencode-go/glm"
        return record
    monkeypatch.setattr(Scanner, "guard_pending", guard)
    monkeypatch.setattr(Scanner, "inspect", inspect)
    assert quota["scan"]() == 0
    assert armed["used"]
    assert not quota["sent"].exists()
    assert quota["actions"]()[-1] == "changed"
    assert "reserved" not in quota["actions"]()
    for _ in range(2):  # The same mismatch on later scans (re-armed just before each pre-send re-read).
        armed["on"] = False
        assert quota["scan"]() == 0
    assert quota["actions"]().count("changed") == 1  # One ledger row, not one per scan.
    assert not quota["sent"].exists()


def test_persistent_failure_writes_one_unavailable_row(quota):
    quota["wait"]()
    path = quota["state"] / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["resets_at"] = "garbage"  # A string, so the ledger loads, but it cannot be parsed.
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    quota["data"]["agents"][CHILD]["Status"] = "closed"
    for _ in range(3):
        assert quota["scan"]() == 0
    assert quota["actions"]().count("unavailable") == 1
    assert not quota["sent"].exists()


def test_unconfirmed_agent_is_not_re_read_but_is_re_evaluated(quota):
    quota["put"](account([window("ok", 12.0, None)]))  # aiuse has not (yet) seen the exhaustion
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-unconfirmed"]
    first = len(logs_calls())
    assert first >= 2  # plain logs + structured logs at first sight
    for _ in range(3):
        assert quota["scan"]() == 0
    assert len(logs_calls()) == first
    assert quota["actions"]() == ["quota-unconfirmed"]
    quota["put"](exhausted_account())  # aiuse catches up: the wait is armed without reading the logs again
    assert quota["scan"]() == 0
    assert quota["actions"]() == ["quota-unconfirmed", "quota-wait"]
    assert len(logs_calls()) == first
    quota["clock"](at(20, 35))
    quota["put"](reset_account())
    assert quota["scan"]() == 0
    assert quota["sent"].exists()


@pytest.mark.parametrize("activity,action", [
    ([{"type": "user_message", "text": "r"}, {"type": "assistant_message", "text": "done: W1 https://example.test/1"},
      {"type": "assistant_message", "text": QLINE}], "delivered"),
    ([{"type": "user_message", "text": "r"}, {"type": "assistant_message", "text": QLINE},
      {"type": "user_message", "text": "new task"}], "changed"),
])
def test_blocked_first_sight_is_not_re_read(quota, activity, action):
    quota["data"]["activity"] = activity
    quota["put"](exhausted_account())
    assert quota["scan"]() == 0
    assert quota["actions"]() == [action]
    first = len(logs_calls())
    for _ in range(3):
        assert quota["scan"]() == 0
    assert len(logs_calls()) == first
    assert quota["actions"]() == [action]
