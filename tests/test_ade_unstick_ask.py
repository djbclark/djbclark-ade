"""Unit tests for bin/ade-unstick-ask (2026-11-23).

Uses absolute-path fake paseo binaries injected via --paseo-bin or ADE_PASEO_BIN
with NO PATH reordering.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "ade-unstick-ask"

A_STUCK = "11111111-1111-4111-8111-111111111111"
A_SELF = "22222222-2222-4222-8222-222222222222"
A_OTHER = "33333333-3333-4333-8333-333333333333"
A_CLAUDE = "44444444-4444-4444-8444-444444444444"


def iso_offset(seconds_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


FAKE_PASEO_CODE = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["FAKE_PASEO_STATE"])
log_path = Path(os.environ["FAKE_PASEO_CALLS"])

data = json.loads(state_path.read_text(encoding="utf-8"))
argv = sys.argv[1:]
with log_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv) + "\\n")


def save():
    state_path.write_text(json.dumps(data), encoding="utf-8")


if argv == ["ls", "-g", "--json"]:
    if data.get("ls_rc", 0) != 0:
        sys.stderr.write(data.get("ls_err", "ls failed"))
        sys.exit(data["ls_rc"])
    print(json.dumps(data.get("ls", [])))
    sys.exit(0)

if len(argv) >= 4 and argv[0] == "agent" and argv[1] == "inspect" and argv[3] == "--json":
    aid = argv[2]
    seq = data.get("inspect_seq", {}).get(aid)
    if seq:
        rec = seq.pop(0)
        if not seq:
            # Keep last item sticky if exhausted
            seq.append(rec)
        save()
    else:
        rec = data.get("inspect", {}).get(aid)
    if rec is None:
        sys.stderr.write("not found")
        sys.exit(1)
    if isinstance(rec, dict) and rec.get("_rc"):
        sys.stderr.write(rec.get("_err", "inspect failed"))
        sys.exit(rec["_rc"])
    if isinstance(rec, str):
        print(rec)
        sys.exit(0)
    print(json.dumps(rec))
    sys.exit(0)

if len(argv) >= 3 and argv[0] == "logs" and argv[2] == "--json":
    aid = argv[1]
    seq = data.get("logs_seq", {}).get(aid)
    if seq:
        rec = seq.pop(0)
        if not seq:
            seq.append(rec)
        save()
    else:
        rec = data.get("logs", {}).get(aid)
    if rec is None:
        sys.stderr.write("logs not found")
        sys.exit(1)
    if isinstance(rec, dict) and rec.get("_rc"):
        sys.stderr.write(rec.get("_err", "logs failed"))
        sys.exit(rec["_rc"])
    if isinstance(rec, str):
        print(rec)
        sys.exit(0)
    print(json.dumps(rec))
    sys.exit(0)

if argv and argv[0] == "send":
    rc = data.get("send_rc", 0)
    if rc not in (0, 5):
        sys.stderr.write(data.get("send_err", "send failed"))
        sys.exit(rc)
    target = argv[argv.index("--") + 1] if "--" in argv else argv[-2]
    # Apply optional post-steer state mutation
    if "after_steer_inspect" in data:
        data["inspect"].update(data["after_steer_inspect"])
    if "after_steer_logs" in data:
        data["logs"].update(data["after_steer_logs"])
    save()
    if "send_raw_out" in data:
        sys.stdout.write(data["send_raw_out"])
    else:
        default_out = {"agentId": target, "status": "queued" if rc == 5 else "sent"}
        print(json.dumps(data.get("send_out", default_out)))
    sys.exit(rc)

if len(argv) >= 3 and argv[0] == "agent" and argv[1] == "stop":
    rc = data.get("stop_rc", 0)
    if data.get("stop_err"):
        sys.stderr.write(data["stop_err"])
    if rc != 0:
        sys.exit(rc)
    if "stop_raw_out" in data:
        sys.stdout.write(data["stop_raw_out"])
    else:
        default_stop = {"stoppedCount": 1, "agentIds": [argv[2]]}
        print(json.dumps(data.get("stop_out", default_stop)))
    sys.exit(0)

sys.stderr.write(f"unexpected argv: {argv!r}\\n")
sys.exit(99)
"""


class FakePaseo:
    def __init__(self, tmp_path: Path, state: dict):
        self.tmp = tmp_path
        self.bin_path = tmp_path / "fake-paseo"
        self.bin_path.write_text(FAKE_PASEO_CODE, encoding="utf-8")
        self.bin_path.chmod(0o755)
        self.state_path = tmp_path / "state.json"
        self.calls_path = tmp_path / "calls.jsonl"
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.calls_path.write_text("", encoding="utf-8")

    def calls(self) -> list[list[str]]:
        lines = self.calls_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def run(
        self,
        *args: str,
        use_env_bin: bool = False,
        self_id: str | None = None,
    ) -> tuple[int, dict, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "FAKE_PASEO_STATE": str(self.state_path),
            "FAKE_PASEO_CALLS": str(self.calls_path),
        }
        if self_id is not None:
            env["PASEO_AGENT_ID"] = self_id
        argv = [str(SCRIPT)]
        if use_env_bin:
            env["ADE_PASEO_BIN"] = str(self.bin_path)
        else:
            argv += ["--paseo-bin", str(self.bin_path)]
        argv += list(args)
        if "--json" not in argv:
            argv.append("--json")
        proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return proc.returncode, payload, proc.stderr


def make_inspect(
    aid: str,
    *,
    provider: str = "antigravity",
    archived: object = False,
    status: str = "running",
    pending: object = None,
    updated_at: object = None,
    name: str = "worker test",
) -> dict:
    return {
        "Id": aid,
        "Provider": provider,
        "Archived": archived,
        "Status": status,
        "PendingPermissions": [] if pending is None else pending,
        "UpdatedAt": iso_offset(600) if updated_at is None else updated_at,
        "Name": name,
    }


def make_hung_logs(aid: str, tool_name: str = "ask_question", call_id: str = "call_ask_1") -> dict:
    return {
        "agentId": aid,
        "items": [
            {"type": "user_message", "text": "do the work"},
            {"type": "reasoning", "text": "need to ask"},
            {
                "type": "tool_call",
                "callId": call_id,
                "name": tool_name,
                "status": "running",
                "error": None,
                "detail": {"type": "unknown", "input": {"questions": []}},
            },
        ],
    }


def test_dry_run_detects_hung_ask_and_bracket_name_without_mutating(tmp_path):
    state = {
        "ls": [
            {"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running", "archived": False},
            {"id": A_OTHER, "provider": "antigravity", "status": "running", "archived": False},
        ],
        "inspect": {
            A_STUCK: make_inspect(A_STUCK),
            A_OTHER: make_inspect(A_OTHER),
        },
        "logs": {
            A_STUCK: make_hung_logs(A_STUCK, "ask_question", "call_1"),
            A_OTHER: make_hung_logs(A_OTHER, "[Ask question]", "call_2"),
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--check")
    assert rc == 0, err
    assert data["mode"] == "dry-run"
    assert [d["agent_id"] for d in data["detected"]] == [A_STUCK, A_OTHER]
    assert [r["action"] for r in data["results"]] == ["would-recover", "would-recover"]
    # Dry-run never sends or stops.
    assert not any(c[0] == "send" or c[:2] == ["agent", "stop"] for c in fake.calls())


def test_skips_non_antigravity_in_ls_and_only_agent(tmp_path):
    state = {
        "ls": [
            {"id": A_CLAUDE, "provider": "claude/sonnet", "status": "running", "archived": False},
        ],
        "inspect": {
            A_CLAUDE: make_inspect(A_CLAUDE, provider="claude"),
        },
        "logs": {
            A_CLAUDE: make_hung_logs(A_CLAUDE),
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run()
    assert rc == 0
    assert data["detected"] == []
    assert any(s["agent_id"] == A_CLAUDE and s["reason"].startswith("provider:") for s in data["skipped"])

    rc2, data2, _ = fake.run("--only-agent", A_CLAUDE)
    assert rc2 == 0
    assert data2["detected"] == []
    assert data2["skipped"] == [{"agent_id": A_CLAUDE, "reason": "provider:claude"}]


@pytest.mark.parametrize(
    "items,expected_reason_prefix",
    [
        # Running non-ask tool
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "run_command", "status": "running", "error": None},
            ],
            "other-running-tool:run_command",
        ),
        # Another running tool alongside ask_question -> fail closed
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "run_command", "status": "running", "error": None},
                {"type": "tool_call", "callId": "c2", "name": "ask_question", "status": "running", "error": None},
            ],
            "other-running-tool:run_command",
        ),
        # Completed ask_question
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "ask_question", "status": "completed", "error": None},
            ],
            "ask-not-pending",
        ),
        # Failed ask_question
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "ask_question", "status": "failed", "error": {"message": "x"}},
            ],
            "ask-not-pending",
        ),
        # ask_question followed by assistant reply
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "ask_question", "status": "running", "error": None},
                {"type": "assistant_message", "text": "continuing"},
            ],
            "subsequent-activity:",
        ),
        # ask_question followed by tool_result
        (
            [
                {"type": "user_message", "text": "go"},
                {"type": "tool_call", "callId": "c1", "name": "ask_question", "error": None},
                {"type": "tool_result", "callId": "c1", "output": "ok"},
            ],
            "ask-not-pending",
        ),
    ],
)
def test_skips_non_hung_or_other_active_tools(tmp_path, items, expected_reason_prefix):
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: {"agentId": A_STUCK, "items": items}},
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run()
    assert rc == 0
    assert data["detected"] == []
    assert data["skipped"][0]["reason"].startswith(expected_reason_prefix)


def test_skips_non_empty_or_missing_pending_permissions(tmp_path):
    state = {
        "ls": [
            {"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"},
            {"id": A_OTHER, "provider": "antigravity/gemini-4-neon", "status": "running"},
        ],
        "inspect": {
            A_STUCK: make_inspect(A_STUCK, pending=[{"id": "perm_1"}]),
            A_OTHER: {k: v for k, v in make_inspect(A_OTHER).items() if k != "PendingPermissions"},
        },
        "logs": {
            A_STUCK: make_hung_logs(A_STUCK),
            A_OTHER: make_hung_logs(A_OTHER),
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run()
    assert rc == 0
    assert data["detected"] == []
    reasons = {s["agent_id"]: s["reason"] for s in data["skipped"]}
    assert reasons == {A_STUCK: "pending-permissions", A_OTHER: "pending-permissions"}


@pytest.mark.parametrize(
    "updated_at_factory,expected_reason",
    [
        pytest.param(lambda: iso_offset(30), "recent-updated-at", id="recent-30s"),
        pytest.param(lambda: iso_offset(-120), "future-updated-at", id="future-120s"),
        pytest.param(lambda: "2026-11-23T15:00:00", "invalid-updated-at", id="naive"),
        pytest.param(lambda: "", "invalid-updated-at", id="empty"),
        pytest.param(lambda: None, "invalid-updated-at", id="none"),
        pytest.param(lambda: "not-a-timestamp", "invalid-updated-at", id="garbage"),
    ],
)
def test_skips_recent_future_naive_or_missing_updated_at(tmp_path, updated_at_factory, expected_reason):
    rec = make_inspect(A_STUCK)
    rec["UpdatedAt"] = updated_at_factory()
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: rec},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run("--min-stuck", "300")
    assert rc == 0
    assert data["detected"] == []
    assert data["skipped"] == [{"agent_id": A_STUCK, "reason": expected_reason}]


def test_skips_archived_and_self(tmp_path):
    state = {
        "ls": [
            {"id": A_SELF, "provider": "antigravity/gemini-4-neon", "status": "running", "archived": False},
            {"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running", "archived": True},
            {"id": A_OTHER, "provider": "antigravity/gemini-4-neon", "status": "running", "archived": False},
        ],
        "inspect": {
            A_SELF: make_inspect(A_SELF),
            A_STUCK: make_inspect(A_STUCK, archived=True),
            A_OTHER: make_inspect(A_OTHER, archived=True),  # archived in inspect even if ls missed it
        },
        "logs": {
            A_SELF: make_hung_logs(A_SELF),
            A_STUCK: make_hung_logs(A_STUCK),
            A_OTHER: make_hung_logs(A_OTHER),
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run(self_id=A_SELF)
    assert rc == 0
    assert data["detected"] == []
    reasons = {s["agent_id"]: s["reason"] for s in data["skipped"]}
    assert reasons == {
        A_SELF: "self",
        A_STUCK: "archived",
        A_OTHER: "archived-or-unknown",
    }

    # --only-agent self also skips self
    rc2, data2, _ = fake.run("--only-agent", A_SELF, self_id=A_SELF)
    assert rc2 == 0
    assert data2["detected"] == []
    assert data2["skipped"] == [{"agent_id": A_SELF, "reason": "self"}]


def test_skips_unreadable_logs_fail_closed(tmp_path):
    state = {
        "ls": [
            {"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"},
            {"id": A_OTHER, "provider": "antigravity/gemini-4-neon", "status": "running"},
        ],
        "inspect": {
            A_STUCK: make_inspect(A_STUCK),
            A_OTHER: make_inspect(A_OTHER),
        },
        "logs": {
            A_STUCK: "{not-json",
            A_OTHER: {"agentId": A_CLAUDE, "items": make_hung_logs(A_OTHER)["items"]},
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, _ = fake.run("--apply", "--steer-wait", "0.02", "--poll-interval", "0.01")
    assert rc == 0
    assert data["detected"] == []
    reasons = {s["agent_id"]: s["reason"] for s in data["skipped"]}
    assert reasons == {A_STUCK: "logs-failed", A_OTHER: "unreadable-logs-agent-mismatch"}
    assert not any(c[0] == "send" or c[:2] == ["agent", "stop"] for c in fake.calls())


def test_apply_steer_succeeds_and_never_cancels(tmp_path):
    orig_ts = iso_offset(600)
    later_ts = iso_offset(5)
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK, updated_at=orig_ts)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 5,  # agent-to-agent accepted/queued exit code
        "after_steer_inspect": {
            # Real agent-side progress: Status left running -> idle
            A_STUCK: make_inspect(A_STUCK, status="idle", updated_at=later_ts),
        },
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--apply", "--steer-wait", "0.05", "--poll-interval", "0.01")
    assert rc == 0, err
    assert data["errors"] == []
    assert len(data["results"]) == 1
    assert data["results"][0]["action"] == "recovered-by-steer"
    assert data["results"][0]["steer_exit_code"] == 5

    calls = fake.calls()
    send_calls = [c for c in calls if c[0] == "send"]
    assert len(send_calls) == 1
    assert send_calls[0][:7] == ["send", "--json", "--no-wait", "--behavior", "steer", "--", A_STUCK]
    assert "ask_question hung without ACP elicitation" in send_calls[0][7]
    assert not any(c[:2] == ["agent", "stop"] for c in calls)


def test_apply_steer_updated_at_bump_and_user_message_still_cancels(tmp_path):
    """MED-1 regression: Paseo's recordSubmittedPrompt immediately bumps UpdatedAt and appends
    our steer user_message even when ask_question stays hung; ade-unstick-ask must still stop."""
    orig_ts = iso_offset(600)
    bumped_ts = iso_offset(1)
    hung_logs = make_hung_logs(A_STUCK)
    after_steer_logs = {
        "agentId": A_STUCK,
        "items": [
            *hung_logs["items"],
            {
                "type": "user_message",
                "text": "ask_question hung without ACP elicitation; abandon the ask_question call and continue with numbered text options instead.",
            },
        ],
    }
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK, updated_at=orig_ts)},
        "logs": {A_STUCK: hung_logs},
        "after_steer_inspect": {
            A_STUCK: make_inspect(A_STUCK, status="running", updated_at=bumped_ts),
        },
        "after_steer_logs": {A_STUCK: after_steer_logs},
        "send_rc": 5,
        "stop_rc": 0,
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--apply", "--steer-wait", "0.04", "--poll-interval", "0.01")
    assert rc == 0, err
    assert data["errors"] == []
    assert len(data["results"]) == 1
    assert data["results"][0]["action"] == "recovered-by-cancel"
    assert data["results"][0]["cancel_exit_code"] == 0

    calls = fake.calls()
    send_idx = next(i for i, c in enumerate(calls) if c[0] == "send")
    stop_idx = next(i for i, c in enumerate(calls) if c[:2] == ["agent", "stop"])
    assert send_idx < stop_idx
    assert calls[stop_idx] == ["agent", "stop", A_STUCK, "--json"]


def test_apply_stop_exit_zero_with_zero_stopped_count_fails_closed(tmp_path):
    """MED-2 regression: Paseo agent stop exits 0 with stoppedCount=0 + stderr warning on failure."""
    sub1 = tmp_path / "zero_count"
    sub1.mkdir()
    state1 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "stop_rc": 0,
        "stop_out": {"stoppedCount": 0, "agentIds": []},
        "stop_err": "Warning: Failed to stop agent 11111111: cancel timed out\n",
    }
    fake1 = FakePaseo(sub1, state1)
    rc1, data1, _ = fake1.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc1 == 1
    assert data1["results"][0]["action"] == "cancel-failed"
    assert "Warning: Failed to stop agent" in data1["results"][0]["error"]
    assert len(data1["errors"]) == 1

    # Also fail closed on exit-0 wrong agentIds or malformed JSON
    sub2 = tmp_path / "wrong_id"
    sub2.mkdir()
    state2 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "stop_rc": 0,
        "stop_out": {"stoppedCount": 1, "agentIds": [A_OTHER]},
    }
    fake2 = FakePaseo(sub2, state2)
    rc2, data2, _ = fake2.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc2 == 1
    assert data2["results"][0]["action"] == "cancel-failed"


def test_apply_steer_malformed_json_or_redirected_agent_id_fails_closed(tmp_path):
    """LOW-2 regression: fail closed on unparseable stdout (e.g. shim redirect) or mismatched agentId."""
    sub1 = tmp_path / "shim_text"
    sub1.mkdir()
    state1 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "send_raw_out": (
            f"ade-paseo-guard: {A_STUCK} was replaced by {A_OTHER}; sending to {A_OTHER}\n"
            f'{{"agentId": "{A_OTHER}", "status": "sent"}}\n'
        ),
    }
    fake1 = FakePaseo(sub1, state1)
    rc1, data1, _ = fake1.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc1 == 1
    assert data1["results"][0]["action"] == "steer-failed"
    assert "malformed JSON" in data1["results"][0]["error"]
    assert not any(c[:2] == ["agent", "stop"] for c in fake1.calls())

    sub2 = tmp_path / "wrong_target"
    sub2.mkdir()
    state2 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "send_out": {"agentId": A_OTHER, "status": "sent"},
    }
    fake2 = FakePaseo(sub2, state2)
    rc2, data2, _ = fake2.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc2 == 1
    assert data2["results"][0]["action"] == "steer-failed"
    assert A_OTHER in data2["results"][0]["error"]
    assert not any(c[:2] == ["agent", "stop"] for c in fake2.calls())


def test_only_agent_inspect_or_logs_failure_exits_one(tmp_path):
    """LOW-2 regression: targeted --only-agent inspect/logs failures record errors and exit 1."""
    sub1 = tmp_path / "inspect_fail"
    sub1.mkdir()
    fake1 = FakePaseo(sub1, {"inspect": {}, "logs": {}})
    rc1, data1, _ = fake1.run("--only-agent", A_STUCK)
    assert rc1 == 1
    assert len(data1["errors"]) == 1 and data1["errors"][0]["stage"] == "inspect"

    sub2 = tmp_path / "logs_fail"
    sub2.mkdir()
    fake2 = FakePaseo(sub2, {"inspect": {A_STUCK: make_inspect(A_STUCK)}, "logs": {}})
    rc2, data2, _ = fake2.run("--only-agent", A_STUCK)
    assert rc2 == 1
    assert len(data2["errors"]) == 1 and data2["errors"][0]["stage"] == "logs"


def test_apply_steer_fails_to_unstick_reverifies_then_cancels(tmp_path):
    orig_ts = iso_offset(600)
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK, updated_at=orig_ts)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "stop_rc": 0,
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--apply", "--steer-wait", "0.03", "--poll-interval", "0.01")
    assert rc == 0, err
    assert data["errors"] == []
    assert len(data["results"]) == 1
    assert data["results"][0]["action"] == "recovered-by-cancel"
    assert data["results"][0]["cancel_exit_code"] == 0

    calls = fake.calls()
    send_idx = next(i for i, c in enumerate(calls) if c[0] == "send")
    stop_idx = next(i for i, c in enumerate(calls) if c[:2] == ["agent", "stop"])
    assert send_idx < stop_idx
    assert calls[stop_idx] == ["agent", "stop", A_STUCK, "--json"]
    # Confirm re-verification occurred between send and stop.
    between = calls[send_idx + 1 : stop_idx]
    assert ["agent", "inspect", A_STUCK, "--json"] in between
    assert ["logs", A_STUCK, "--json"] in between
    # Never archive or kill.
    assert not any(c[:2] in (["agent", "archive"], ["agent", "kill"]) for c in calls)


def test_apply_target_unstuck_right_before_cancel_skips_cancel(tmp_path):
    orig_ts = iso_offset(600)
    later_ts = iso_offset(2)
    hung_rec = make_inspect(A_STUCK, updated_at=orig_ts)
    unstuck_rec = make_inspect(A_STUCK, status="idle", updated_at=later_ts)
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        # Call 1: initial detect inspect -> hung
        # Call 2: single poll during steer-wait=0 -> hung
        # Call 3: pre-cancel re-verify inspect -> unstuck!
        "inspect_seq": {A_STUCK: [hung_rec, hung_rec, unstuck_rec]},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc == 0, err
    assert data["errors"] == []
    assert data["results"][0]["action"] == "recovered-by-steer"
    assert data["results"][0]["reason"] == "unstuck-before-cancel"
    assert not any(c[:2] == ["agent", "stop"] for c in fake.calls())


def test_apply_steer_error_and_cancel_error_fail_closed(tmp_path):
    # Steer CLI returns nonzero -> steer-failed, never cancels
    sub1 = tmp_path / "steer_err"
    sub1.mkdir()
    state1 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 2,
        "send_err": "daemon rejected steer",
    }
    fake1 = FakePaseo(sub1, state1)
    rc1, data1, _ = fake1.run("--apply", "--steer-wait", "0.02", "--poll-interval", "0.01")
    assert rc1 == 1
    assert data1["results"][0]["action"] == "steer-failed"
    assert not any(c[:2] == ["agent", "stop"] for c in fake1.calls())

    # Cancel CLI returns nonzero -> cancel-failed, exit 1
    sub2 = tmp_path / "cancel_err"
    sub2.mkdir()
    state2 = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
        "send_rc": 0,
        "stop_rc": 1,
        "stop_err": "stop failed",
    }
    fake2 = FakePaseo(sub2, state2)
    rc2, data2, _ = fake2.run("--apply", "--steer-wait", "0", "--poll-interval", "0.01")
    assert rc2 == 1
    assert data2["results"][0]["action"] == "cancel-failed"
    assert len(data2["errors"]) == 1


def test_apply_timeline_advances_after_steer_skips_cancel(tmp_path):
    orig_ts = iso_offset(600)
    hung_logs = make_hung_logs(A_STUCK)
    advanced_logs = {
        "agentId": A_STUCK,
        "items": [
            *hung_logs["items"][:-1],
            {
                "type": "tool_call",
                "callId": "call_ask_1",
                "name": "ask_question",
                "status": "completed",
                "error": None,
            },
            {"type": "assistant_message", "text": "Continuing with numbered text options."},
        ],
    }
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK, updated_at=orig_ts)},
        "logs": {A_STUCK: hung_logs},
        "after_steer_logs": {A_STUCK: advanced_logs},
        "send_rc": 0,
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run("--apply", "--steer-wait", "0.05", "--poll-interval", "0.01")
    assert rc == 0, err
    assert data["results"][0]["action"] == "recovered-by-steer"
    assert data["results"][0]["reason"] == "timeline-advanced"
    assert not any(c[:2] == ["agent", "stop"] for c in fake.calls())


def test_env_ade_paseo_bin_and_usage_errors(tmp_path):
    state = {
        "ls": [{"id": A_STUCK, "provider": "antigravity/gemini-4-neon", "status": "running"}],
        "inspect": {A_STUCK: make_inspect(A_STUCK)},
        "logs": {A_STUCK: make_hung_logs(A_STUCK)},
    }
    fake = FakePaseo(tmp_path, state)
    rc, data, err = fake.run(use_env_bin=True)
    assert rc == 0, err
    assert [d["agent_id"] for d in data["detected"]] == [A_STUCK]

    # Usage validation errors -> exit 2
    for bad_args in (
        ("--check", "--apply"),
        ("--only-agent", "not-a-uuid"),
        ("--min-stuck", "-1"),
        ("--steer-wait", "-5"),
        ("--poll-interval", "0"),
    ):
        proc = subprocess.run(
            [str(SCRIPT), *bad_args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 2, (bad_args, proc.returncode, proc.stderr)
