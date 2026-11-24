"""bin/ade-revive: supported, audited un-archive for non-replaced Paseo agents (queue #97, 2026-11-24).

Offline tests using explicit binary-path injection (`--paseo` / `ADE_REVIVE_PASEO`, never PATH reordering) and
direct Python dependency injection into `revive(...)`.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))
import ade_send_guard as guard  # noqa: E402
from test_ade_lead_succession import A, B, C, D, STRANGER, write_link  # noqa: E402
from test_archived_send_guard import stamp  # noqa: E402

SCRIPT = ROOT / "bin" / "ade-revive"


def _load_revive():
    loader = importlib.machinery.SourceFileLoader("ade_revive_mod", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_revive_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


revive_mod = _load_revive()

FAKE_PASEO = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
log_path = os.environ["FAKE_LOG"]
agents_path = Path(os.environ["FAKE_AGENTS"])
with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": args, "allow_env": os.environ.get("ADE_ALLOW_ARCHIVED_SEND")}) + "\\n")

agents = json.loads(agents_path.read_text(encoding="utf-8"))

if args[:2] == ["agent", "inspect"]:
    target = args[2]
    if target not in agents:
        sys.stderr.write(f"Agent not found: {target}\\n")
        sys.exit(1)
    v = agents[target]
    rec = {"Id": target, "ParentAgentId": None, **(v if isinstance(v, dict) else {"Archived": v})}
    print(json.dumps(rec))
    sys.exit(0)

if args[:1] == ["ls"] and "--label" in args:
    if os.environ.get("FAKE_LS_FAIL"):
        sys.stderr.write("daemon down\\n")
        sys.exit(1)
    labels = json.loads(Path(os.environ["FAKE_LABELS"]).read_text(encoding="utf-8")) if os.environ.get("FAKE_LABELS") else {}
    want = args[args.index("--label") + 1]
    print(json.dumps([{"id": i, "status": "closed"} for i in labels.get(want, [])]))
    sys.exit(0)

if args[:2] == ["agent", "reload"]:
    if os.environ.get("FAKE_RELOAD_FAIL"):
        sys.stderr.write("reload failed: no persistence\\n")
        sys.exit(1)
    target = args[-1]
    if target not in agents:
        sys.stderr.write(f"Agent not found: {target}\\n")
        sys.exit(1)
    if not os.environ.get("FAKE_STAY_ARCHIVED"):
        v = agents[target]
        if isinstance(v, dict):
            v["Archived"] = False
        else:
            agents[target] = False
        agents_path.write_text(json.dumps(agents), encoding="utf-8")
    print(json.dumps({"agentId": target, "status": "reloaded", "timelineSize": 1}))
    sys.exit(0)

if args[:1] == ["send"]:
    if os.environ.get("FAKE_SEND_FAIL"):
        sys.stderr.write("send failed\\n")
        sys.exit(1)
    print(json.dumps({"agentId": args[-2], "status": "sent", "message": "Message sent"}))
    sys.exit(0)

sys.stderr.write(f"unexpected args: {args}\\n")
sys.exit(2)
"""


@pytest.fixture
def env_world(tmp_path):
    """Offline fixture with explicit fake paseo path (NO PATH reordering)."""
    fake_paseo = tmp_path / "fake-paseo"
    fake_paseo.write_text(FAKE_PASEO, encoding="utf-8")
    fake_paseo.chmod(0o755)

    state = tmp_path / "self-session"
    home = tmp_path / "paseo-home"
    agents_file = tmp_path / "agents.json"
    labels_file = tmp_path / "labels.json"
    call_log = tmp_path / "calls.jsonl"
    guard_log = tmp_path / "state" / "send-guard-overrides.jsonl"

    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "FAKE_AGENTS": str(agents_file),
        "FAKE_LOG": str(call_log),
        "ADE_SELF_SESSION_STATE": str(state),
        "PASEO_HOME": str(home),
        "ADE_SEND_GUARD_LOG": str(guard_log),
        "ADE_REVIVE_POLL_INTERVAL": "0.01",
    }

    class W:
        pass

    w = W()
    w.fake_paseo = fake_paseo
    w.state = state
    w.home = home
    w.agents_file = agents_file
    w.labels_file = labels_file
    w.call_log = call_log
    w.guard_log = guard_log
    w.env = base_env

    def set_agents(mapping: dict):
        agents_file.write_text(json.dumps(mapping), encoding="utf-8")

    def set_labels(by_label: dict):
        labels_file.write_text(json.dumps(by_label), encoding="utf-8")
        w.env["FAKE_LABELS"] = str(labels_file)

    def calls() -> list[dict]:
        if not call_log.exists():
            return []
        return [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def guard_logs() -> list[dict]:
        if not guard_log.exists():
            return []
        return [json.loads(line) for line in guard_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def run(*args, extra_env: dict | None = None, pass_paseo_flag: bool = True):
        argv = [sys.executable, str(SCRIPT), *args]
        if pass_paseo_flag:
            argv += ["--paseo", str(fake_paseo)]
        merged = {**w.env, **(extra_env or {})}
        return subprocess.run(argv, capture_output=True, text=True, env=merged, timeout=30, check=False)

    w.set_agents = set_agents
    w.set_labels = set_labels
    w.calls = calls
    w.guard_logs = guard_logs
    w.run = run
    set_agents({})
    return w


# --- validation ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", [
    "--host=evil:6767",
    "--home=/tmp/x",
    "-h",
    "not-a-uuid",
    A[:8],  # prefix only
    A.upper(),  # uppercase rejected
    f"{A} ",  # trailing space
    "agent-name",
])
def test_rejects_invalid_and_flag_like_agent_ids(env_world, bad_id):
    proc = env_world.run("--", bad_id)
    assert proc.returncode == 2
    assert env_world.calls() == []


def test_rejects_invalid_timeout_and_empty_message(env_world):
    env_world.set_agents({A: True})
    assert env_world.run(A, "--timeout", "-1").returncode == 2
    assert env_world.run(A, "--timeout", "nan").returncode == 2
    assert env_world.run(A, "--message", "   ").returncode == 2
    assert env_world.calls() == []


# --- already live (idempotent) ---------------------------------------------------------------------------------------

def test_already_live_agent_exits_0_idempotently_and_sends_nothing(env_world):
    env_world.set_agents({A: False})
    proc = env_world.run(A, "--message", "wake up", "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "already_live"
    assert data["live"] is True
    assert data["revived"] is False
    assert data["message_sent"] is False
    argvs = [c["argv"] for c in env_world.calls()]
    assert argvs == [["agent", "inspect", A, "--json"]]
    assert env_world.guard_logs() == []


# --- replaced / handed-off / cyclic refusals -------------------------------------------------------------------------

def test_refuses_completed_handoff_even_with_allow_any_and_env_overrides(env_world):
    write_link(env_world.state, env_world.home, A, B)
    env_world.set_agents({A: True, B: False})
    for extra in (
        {},
        {guard.ALLOW_ENV: A},
        {guard.ALLOW_REPLACED_ENV: A},
        {guard.SENDER_ENV: C},
    ):
        proc = env_world.run(A, "--allow-any", "--json", extra_env=extra)
        assert proc.returncode == 4, proc.stdout + proc.stderr
        data = json.loads(proc.stdout)
        assert data["status"] == "refused"
        assert data["successor"] == B
        assert B in data["reason"]
    assert all(c["argv"][:2] != ["agent", "reload"] for c in env_world.calls())
    assert env_world.guard_logs() == []


def test_refuses_resurrected_replaced_agent_never_reports_already_live(env_world):
    write_link(env_world.state, env_world.home, A, B)
    env_world.set_agents({A: False, B: False})
    proc = env_world.run(A, "--allow-any", "--json", extra_env={guard.ALLOW_REPLACED_ENV: A})
    assert proc.returncode == 4
    data = json.loads(proc.stdout)
    assert data["status"] == "refused"
    assert data["successor"] == B


def test_refuses_fresh_acknowledged_handoff_naming_successor(env_world):
    write_link(env_world.state, env_world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    env_world.set_agents({A: True, B: False})
    proc = env_world.run(A, "--allow-any", "--json")
    assert proc.returncode == 4
    data = json.loads(proc.stdout)
    assert data["status"] == "refused"
    assert data["successor"] == B


def test_refuses_when_successor_is_archived_too_even_with_allow_any(env_world):
    write_link(env_world.state, env_world.home, A, B)
    env_world.set_agents({A: True, B: True})
    proc = env_world.run(A, "--allow-any", "--json", extra_env={guard.ALLOW_ENV: A})
    assert proc.returncode == 4
    data = json.loads(proc.stdout)
    assert data["status"] == "refused"
    assert data["successor"] == B
    assert B in data["reason"]
    assert env_world.guard_logs() == []


def test_refuses_cyclic_ledger_even_with_allow_any_and_env_override(env_world):
    write_link(env_world.state, env_world.home, A, B)
    write_link(env_world.state, env_world.home, B, A)
    env_world.set_agents({A: True, B: True})
    proc = env_world.run(A, "--allow-any", "--json", extra_env={guard.ALLOW_ENV: A})
    assert proc.returncode == 4
    data = json.loads(proc.stdout)
    assert data["status"] == "refused"
    assert "cyclic" in data["reason"].lower()
    assert env_world.guard_logs() == []


def test_refuses_enrolled_role_replacement_and_unavailable_coord(tmp_path):
    res = revive_mod.revive(
        A,
        allow_any=True,
        env={},
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        log_path=tmp_path / "overrides.jsonl",
        inspect_fn=lambda i: {"Id": i, "Archived": True},
        current_role_fn=lambda _: B,
    )
    assert res.exit_code == 4 and res.successor == B

    def broken(_):
        raise RuntimeError("coord down")

    res2 = revive_mod.revive(
        A,
        allow_any=True,
        env={},
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        log_path=tmp_path / "overrides.jsonl",
        inspect_fn=lambda i: {"Id": i, "Archived": True},
        current_role_fn=broken,
    )
    assert res2.exit_code == 4 and "enrolled authority" in res2.reason


# --- authorization & refusal -----------------------------------------------------------------------------------------

def test_refuses_unauthorized_non_owner_and_bad_env_override(env_world):
    env_world.set_agents({A: True, B: False})
    env_world.set_labels({f"ade.lead={C}": [A]})

    for extra in (
        {},
        {guard.SENDER_ENV: B},  # stranger lead
        {guard.ALLOW_ENV: "1"},  # blanket =1 rejected
        {guard.ALLOW_ENV: B},  # wrong id rejected
    ):
        proc = env_world.run(A, "--json", extra_env=extra)
        assert proc.returncode == 4
        data = json.loads(proc.stdout)
        assert data["status"] == "refused"
    assert all(c["argv"][:2] != ["agent", "reload"] for c in env_world.calls())
    assert env_world.guard_logs() == []


# --- owner-authorized revive + live proof + log ----------------------------------------------------------------------

def test_owner_authorized_revive_via_label_proves_live_and_logs(env_world):
    env_world.set_agents({A: True, B: False})
    env_world.set_labels({f"ade.lead={B}": [A]})
    proc = env_world.run(
        A,
        "--reason",
        "resume worker for PR repair",
        "--json",
        extra_env={guard.SENDER_ENV: B},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "revived"
    assert data["revived"] is True
    assert data["live"] is True
    assert data["authorization"] == "owner"
    assert data["proof"] == f"label:ade.lead={B}"
    assert data["message_sent"] is False

    argvs = [c["argv"] for c in env_world.calls()]
    assert ["agent", "reload", "--json", "--", A] in argvs
    # No prompt was sent because --message was omitted.
    assert not any(a[:1] == ["send"] for a in argvs)
    # Inspect ran again AFTER reload to prove live.
    reload_idx = argvs.index(["agent", "reload", "--json", "--", A])
    assert ["agent", "inspect", A, "--json"] in argvs[reload_idx + 1 :]

    logs = env_world.guard_logs()
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == "revive"
    assert entry["target"] == A
    assert entry["sender"] == B
    assert entry["proof"] == f"label:ade.lead={B}"
    assert entry["reason"] == "resume worker for PR repair"
    assert entry["source"] == "ade-revive"


def test_owner_authorized_revive_via_parent_chain_and_successor_lineage(env_world):
    # B replaced C (completed handoff), A has ParentAgentId=C -> B owns A via lineage.
    write_link(env_world.state, env_world.home, C, B)
    env_world.set_agents({A: {"Archived": True, "ParentAgentId": C}, B: False, C: True})
    proc = env_world.run(A, "--json", extra_env={guard.SENDER_ENV: B})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "revived"
    assert data["authorization"] == "owner"
    assert data["proof"] == f"parent:{C}"


# --- operator ADE_ALLOW_ARCHIVED_SEND and --allow-any + --message ---------------------------------------------------

def test_operator_env_override_revives_and_logs(env_world):
    env_world.set_agents({A: True})
    proc = env_world.run(
        A,
        "--reason",
        "operator wake",
        "--json",
        extra_env={guard.ALLOW_ENV: A, revive_mod.PASEO_ENV: str(env_world.fake_paseo)},
        pass_paseo_flag=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "revived"
    assert data["authorization"] == "env"
    assert data["proof"] == f"env:{guard.ALLOW_ENV}={A}"

    logs = env_world.guard_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "revive"
    assert logs[0]["proof"] == f"env:{guard.ALLOW_ENV}={A}"
    assert logs[0]["reason"] == "operator wake"


def test_allow_any_with_message_delivers_message_after_live_proof_and_omits_message_from_log(env_world):
    env_world.set_agents({A: True})
    secret_msg = "- check status please"
    proc = env_world.run(A, "--allow-any", "--reason", "follow up", "--message", secret_msg, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "revived"
    assert data["authorization"] == "flag"
    assert data["proof"] == "flag:--allow-any"
    assert data["message_sent"] is True

    argvs = [c["argv"] for c in env_world.calls()]
    reload_idx = argvs.index(["agent", "reload", "--json", "--", A])
    send_idx = argvs.index(["send", "--json", "--no-wait", "--", A, secret_msg])
    assert send_idx > reload_idx
    # Live proof inspect happened between reload and send.
    assert ["agent", "inspect", A, "--json"] in argvs[reload_idx + 1 : send_idx]

    # Audit log never records message text.
    raw_log = env_world.guard_log.read_text(encoding="utf-8")
    assert secret_msg not in raw_log
    assert json.loads(raw_log.strip())["event"] == "revive"


# --- --dry-run -------------------------------------------------------------------------------------------------------

def test_dry_run_checks_auth_without_reloading_sending_or_logging(env_world):
    env_world.set_agents({A: True, B: False})
    env_world.set_labels({f"ade.lead={B}": [A]})

    # Unauthorized dry-run still fails closed (exit 4).
    unauth = env_world.run(A, "--dry-run", "--json")
    assert unauth.returncode == 4
    assert env_world.guard_logs() == []

    # Authorized dry-run exits 0, makes no reload/send calls, writes no log.
    ok = env_world.run(A, "--dry-run", "--message", "hi", "--json", extra_env={guard.SENDER_ENV: B})
    assert ok.returncode == 0, ok.stdout + ok.stderr
    data = json.loads(ok.stdout)
    assert data["status"] == "dry_run"
    assert data["dry_run"] is True
    assert data["revived"] is False
    assert data["authorization"] == "owner"
    assert data["proof"] == f"label:ade.lead={B}"
    argvs = [c["argv"] for c in env_world.calls()]
    assert not any(a[:2] == ["agent", "reload"] for a in argvs)
    assert not any(a[:1] == ["send"] for a in argvs)
    assert env_world.guard_logs() == []


# --- timeout & failure modes -----------------------------------------------------------------------------------------

def test_timeout_when_agent_stays_archived_exits_1(env_world):
    env_world.set_agents({A: True})
    proc = env_world.run(
        A,
        "--allow-any",
        "--timeout",
        "0.05",
        "--json",
        extra_env={"FAKE_STAY_ARCHIVED": "1"},
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "timeout"
    assert data["revived"] is False
    assert data["live"] is False
    # Audit log still recorded the revive attempt.
    assert len(env_world.guard_logs()) == 1


def test_polls_until_archived_flips_false_then_succeeds(tmp_path):
    states = [True, True, False]
    calls = {"inspect": 0, "reload": 0, "sleeps": 0}
    clock = {"t": 0.0}
    log_file = tmp_path / "overrides.jsonl"

    def fake_inspect(ident):
        idx = min(calls["inspect"], len(states) - 1)
        calls["inspect"] += 1
        return {"Id": ident, "Archived": states[idx]}

    def fake_reload(ident):
        calls["reload"] += 1

    def fake_sleep(dt):
        calls["sleeps"] += 1
        clock["t"] += dt

    res = revive_mod.revive(
        A,
        allow_any=True,
        timeout=5.0,
        poll_interval=0.1,
        env={},
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        log_path=log_file,
        inspect_fn=fake_inspect,
        reload_fn=fake_reload,
        current_role_fn=lambda _: None,
        sleep_fn=fake_sleep,
        monotonic_fn=lambda: clock["t"],
    )
    assert res.exit_code == 0
    assert res.status == "revived"
    assert calls["reload"] == 1
    assert calls["inspect"] == 3  # 1 pre-check + 2 post-reload polls
    assert calls["sleeps"] == 1
    assert len(log_file.read_text(encoding="utf-8").splitlines()) == 1


def test_plain_text_output_and_guard_refusals_intact(env_world):
    # Careless send to an archived agent is still refused by ade_send_guard.decide.
    d = guard.decide(A, lambda i: {"Id": i, "Archived": True}, state_dir=env_world.state, home=env_world.home)
    assert d.action == guard.REFUSE

    # Non-JSON output writes success to stdout and refusals to stderr.
    env_world.set_agents({A: True})
    denied = env_world.run(A)
    assert denied.returncode == 4 and denied.stdout == "" and "refused" in denied.stderr

    ok = env_world.run(A, "--allow-any")
    assert ok.returncode == 0 and ok.stderr == "" and "revived" in ok.stdout


def test_unusable_inspect_record_fails_closed(tmp_path):
    res = revive_mod.revive(
        A,
        allow_any=True,
        env={},
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        log_path=tmp_path / "overrides.jsonl",
        inspect_fn=lambda i: {"Id": i},  # missing Archived boolean
        current_role_fn=lambda _: None,
    )
    assert res.exit_code == 1 and res.status == "error"

    res2 = revive_mod.revive(
        A,
        allow_any=True,
        env={},
        state_dir=tmp_path / "state",
        home=tmp_path / "home",
        log_path=tmp_path / "overrides.jsonl",
        inspect_fn=lambda _: {"Id": B, "Archived": True},  # mismatched Id
        current_role_fn=lambda _: None,
    )
    assert res2.exit_code == 1 and res2.status == "error"


def test_unknown_agent_and_reload_or_send_failure_exit_1(env_world):
    # Unknown agent fails closed (exit 1).
    unknown = env_world.run(STRANGER, "--allow-any", "--json")
    assert unknown.returncode == 1
    assert json.loads(unknown.stdout)["status"] == "not_found"

    # Reload failure exits 1.
    env_world.set_agents({A: True})
    rel_fail = env_world.run(A, "--allow-any", "--json", extra_env={"FAKE_RELOAD_FAIL": "1"})
    assert rel_fail.returncode == 1
    assert json.loads(rel_fail.stdout)["status"] == "error"

    # Follow-up send failure exits 1 while noting live=True.
    env_world.set_agents({A: True})
    send_fail = env_world.run(
        A,
        "--allow-any",
        "--message",
        "hi",
        "--json",
        extra_env={"FAKE_SEND_FAIL": "1"},
    )
    assert send_fail.returncode == 1
    data = json.loads(send_fail.stdout)
    assert data["status"] == "message_failed"
    assert data["revived"] is True
    assert data["live"] is True
    assert data["message_sent"] is False
