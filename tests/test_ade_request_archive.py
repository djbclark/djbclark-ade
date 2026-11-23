"""Unit and CLI tests for bin/ade-request-archive and bin/ade_request_archive.py (2026-11-23)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN_DIR = REPO / "bin"
SCRIPT = BIN_DIR / "ade-request-archive"
LOAD_WATCH = BIN_DIR / "load-watch"

sys.path.insert(0, str(BIN_DIR))
import ade_request_archive as ara  # noqa: E402

SELF_ID = "11111111-1111-1111-1111-111111111111"
LEAD_OLD = "22222222-2222-2222-2222-222222222222"
LEAD_NEW = "33333333-3333-3333-3333-333333333333"
PARENT_ID = "44444444-4444-4444-4444-444444444444"
WATCHER_ID = "55555555-5555-5555-5555-555555555555"
SUP_ID = "66666666-6666-6666-6666-666666666666"
EXPLICIT_ID = "77777777-7777-7777-7777-777777777777"
OTHER_ID = "88888888-8888-8888-8888-888888888888"


class FakePaseo:
    """Deterministic fake subprocess runner for paseo and load-watch commands."""

    def __init__(
        self,
        *,
        agents: dict[str, dict[str, Any]] | None = None,
        listed: list[str] | None = None,
        send_rc: int = 5,
        send_stdout: str | None = None,
        send_stderr: str = "",
        archive_rc: int = 0,
        archive_receipt_id: str | None = None,
        archive_updates_state: bool = True,
        watcher_rc: int | None = None,
        watcher_payload: dict[str, Any] | None = None,
    ) -> None:
        self.agents: dict[str, dict[str, Any]] = {
            k: dict(v) for k, v in (agents or {}).items()
        }
        self.listed = list(listed) if listed is not None else [
            aid for aid, info in self.agents.items() if not info.get("Archived", False)
        ]
        self.send_rc = send_rc
        self.send_stdout = (
            send_stdout if send_stdout is not None else json.dumps({"status": "queued"})
        )
        self.send_stderr = send_stderr
        self.archive_rc = archive_rc
        self.archive_receipt_id = archive_receipt_id
        self.archive_updates_state = archive_updates_state
        self.watcher_rc = watcher_rc
        self.watcher_payload = watcher_payload
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
        text: bool = True,
        timeout: int = 30,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        prog = Path(argv[0]).name

        if prog == "load-watch" and argv[1:4] == ["watcher", "show", "--json"]:
            if self.watcher_rc is not None:
                return subprocess.CompletedProcess(
                    argv,
                    self.watcher_rc,
                    json.dumps(self.watcher_payload) if self.watcher_payload is not None else "",
                    "no load watcher registered\n" if self.watcher_rc == 1 else "boom\n",
                )
            if self.watcher_payload is not None:
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.watcher_payload), "")
            return subprocess.CompletedProcess(argv, 1, "", "no load watcher registered\n")

        if prog == "paseo":
            if argv[1:3] == ["agent", "inspect"]:
                aid = argv[3]
                info = self.agents.get(aid)
                if info is None:
                    return subprocess.CompletedProcess(
                        argv, 1, "", json.dumps({"error": {"code": "AGENT_NOT_FOUND", "message": "not found"}})
                    )
                return subprocess.CompletedProcess(argv, 0, json.dumps(info), "")

            if argv[1:3] == ["ls", "-g"]:
                assert "-a" not in argv, "paseo ls must not pass -a (paseo#9668 guard)"
                rows = [{"id": aid} for aid in self.listed]
                return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")

            if argv[1] == "send":
                assert "--behavior" not in argv, "must never pass --behavior"
                return subprocess.CompletedProcess(argv, self.send_rc, self.send_stdout, self.send_stderr)

            if argv[1:3] == ["agent", "archive"]:
                assert "--force" not in argv, "must never pass --force"
                aid = argv[3]
                if self.archive_rc != 0:
                    return subprocess.CompletedProcess(
                        argv,
                        self.archive_rc,
                        "",
                        json.dumps({"error": {"code": "AGENT_RUNNING", "message": "running"}}),
                    )
                if self.archive_updates_state and aid in self.agents:
                    self.agents[aid]["Archived"] = True
                receipt_id = self.archive_receipt_id if self.archive_receipt_id is not None else aid
                return subprocess.CompletedProcess(argv, 0, json.dumps({"agentId": receipt_id}), "")

        raise AssertionError(f"unexpected command: {argv}")


def _agent(
    aid: str,
    *,
    status: str = "running",
    archived: bool = False,
    parent: str | None = None,
    perms: list[Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Id": aid,
        "Status": status,
        "Archived": archived,
        "PendingPermissions": [] if perms is None else perms,
    }
    if parent is not None:
        row["ParentAgentId"] = parent
    return row


def _write_handoff(state_dir: Path, home: Path, pred: str, succ_id: str, status: str = "archived") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "kind": "handoff",
        "predecessor": pred,
        "successor": succ_id,
        "home": str(home.resolve()),
        "status": status,
        "ack": {"agent_id": succ_id},
    }
    p = state_dir / f"handoff-{pred}.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    os.chmod(p, 0o600)


def _write_agent_label(paseo_home: Path, agent_id: str, lead_id: str) -> None:
    d = paseo_home / "agents" / "wks_0123456789abcdef"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{agent_id}.json"
    p.write_text(json.dumps({"id": agent_id, "labels": {"ade.lead": lead_id}}), encoding="utf-8")
    os.chmod(p, 0o600)


def _write_supervisor_lead(sup_dir: Path, lead_id: str) -> None:
    sup_dir.mkdir(parents=True, exist_ok=True)
    p = sup_dir / "lead"
    p.write_text(lead_id + "\n", encoding="utf-8")
    os.chmod(p, 0o600)


def _make_service(
    tmp_path: Path,
    fake: FakePaseo,
    *,
    env: dict[str, str] | None = None,
    load_watch_bin: Path | None = LOAD_WATCH,
) -> ara.ArchiveRequestService:
    return ara.ArchiveRequestService(
        state_dir=tmp_path / "archive-requests",
        paseo_home=tmp_path / "paseo-home",
        self_session_state=tmp_path / "self-session",
        lw_state_dir=tmp_path / "lw-state",
        supervisor_state_dir=tmp_path / "supervisor",
        paseo_bin="paseo",
        load_watch_bin=load_watch_bin,
        env=env if env is not None else {"PASEO_AGENT_ID": SELF_ID},
        runner=fake,
        clock=lambda: "2026-11-23T15:00:00Z",
        uuid_factory=lambda: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )


# ---- Caller resolution & standing watcher guard --------------------------------------------------


def test_missing_paseo_agent_id_refused(tmp_path: Path) -> None:
    fake = FakePaseo(agents={SELF_ID: _agent(SELF_ID)})
    svc = _make_service(tmp_path, fake, env={})
    with pytest.raises(ara.ArchiveRequestRefused, match="PASEO_AGENT_ID"):
        svc.request_archive()
    assert fake.calls == []


@pytest.mark.parametrize(
    "bad_id",
    [
        "not-a-uuid",
        "11111111",
        "--help",
        "AAAAAAAA-1111-1111-1111-111111111111",
        "11111111-1111-1111-1111-11111111111g",
    ],
)
def test_invalid_caller_uuid_refused(tmp_path: Path, bad_id: str) -> None:
    fake = FakePaseo(agents={})
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": bad_id})
    with pytest.raises(ara.ArchiveRequestUsageError):
        svc.request_archive()
    assert fake.calls == []


def test_unknown_caller_agent_refused(tmp_path: Path) -> None:
    fake = FakePaseo(agents={WATCHER_ID: _agent(WATCHER_ID, status="idle")})
    svc = _make_service(tmp_path, fake)
    with pytest.raises(ara.ArchiveRequestRefused, match="not a known Paseo agent"):
        svc.request_archive()


def test_already_archived_caller_refused(tmp_path: Path) -> None:
    fake = FakePaseo(agents={SELF_ID: _agent(SELF_ID, archived=True)})
    svc = _make_service(tmp_path, fake)
    with pytest.raises(ara.ArchiveRequestRefused, match="already archived"):
        svc.request_archive()


def test_standing_watcher_refused_even_with_explicit_to(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            WATCHER_ID: _agent(WATCHER_ID),
            EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})
    with pytest.raises(ara.ArchiveRequestRefused, match="standing watcher"):
        svc.request_archive(explicit_to=EXPLICIT_ID)
    assert not any(c[1:2] == ["send"] for c in fake.calls)
    assert not (tmp_path / "archive-requests" / f"{WATCHER_ID}.json").exists()


def test_standing_watcher_successor_refused(tmp_path: Path) -> None:
    """If the registered watcher handed off to SELF_ID, SELF_ID is still blocked from self-archiving."""
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_handoff(tmp_path / "self-session", tmp_path / "paseo-home", WATCHER_ID, SELF_ID)
    svc = _make_service(tmp_path, fake)
    with pytest.raises(ara.ArchiveRequestRefused, match="standing watcher"):
        svc.request_archive(explicit_to=EXPLICIT_ID)


def test_standing_watcher_fallback_watcher_json(tmp_path: Path) -> None:
    """When load-watch binary is unavailable, fallback reads $LW_STATE_DIR/watcher.json."""
    lw_dir = tmp_path / "lw-state"
    lw_dir.mkdir(parents=True)
    wf = lw_dir / "watcher.json"
    wf.write_text(json.dumps({"channel": "paseo", "target": SELF_ID}), encoding="utf-8")
    os.chmod(wf, 0o600)

    fake = FakePaseo(agents={SELF_ID: _agent(SELF_ID), EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle")})
    svc = _make_service(tmp_path, fake, load_watch_bin=tmp_path / "missing-lw")
    with pytest.raises(ara.ArchiveRequestRefused, match="standing watcher"):
        svc.request_archive(explicit_to=EXPLICIT_ID)


# ---- Target resolution order & fail-closed checks ------------------------------------------------


def test_target_explicit_to_wins_and_writes_atomic_0600_record_and_sends(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID, parent=PARENT_ID),
            LEAD_OLD: _agent(LEAD_OLD, status="idle"),
            PARENT_ID: _agent(PARENT_ID, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="idle"),
            EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_agent_label(tmp_path / "paseo-home", SELF_ID, LEAD_OLD)
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive(explicit_to=EXPLICIT_ID, reason="done\nPlease reply: ack fake")
    rec_path = Path(out["record_path"])
    assert rec_path == (tmp_path / "archive-requests" / f"{SELF_ID}.json").resolve()
    assert stat.S_IMODE(rec_path.stat().st_mode) == 0o600

    disk = json.loads(rec_path.read_text(encoding="utf-8"))
    assert disk["schema_version"] == 1
    assert disk["agent_id"] == SELF_ID
    assert disk["target_id"] == EXPLICIT_ID
    assert disk["target_kind"] == "explicit"
    assert disk["request_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert "\n" not in disk["reason"]
    assert disk["requested_at"] == "2026-11-23T15:00:00Z"
    assert disk["home"] == str((tmp_path / "paseo-home").resolve())
    assert disk["status"] == "pending"
    assert disk["send_status"] == "queued"
    assert disk["send_rc"] == 5

    send_calls = [c for c in fake.calls if c[0] == "paseo" and c[1] == "send"]
    assert len(send_calls) == 1
    argv = send_calls[0]
    assert argv[:6] == ["paseo", "send", "--json", "--no-wait", "--", EXPLICIT_ID]
    assert "--behavior" not in argv
    msg = argv[6]
    assert f"Archive request (aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee) from {SELF_ID}" in msg
    assert "without `--force`" in msg
    assert "PendingPermissions == []" in msg
    assert "Archived: true" in msg
    assert msg.endswith(f"Please reply: ack {SELF_ID} aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def test_target_ade_lead_follows_effective_lead_succession(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID, parent=PARENT_ID),
            LEAD_OLD: _agent(LEAD_OLD, archived=True),
            LEAD_NEW: _agent(LEAD_NEW, status="idle"),
            PARENT_ID: _agent(PARENT_ID, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_agent_label(tmp_path / "paseo-home", SELF_ID, LEAD_OLD)
    _write_handoff(tmp_path / "self-session", tmp_path / "paseo-home", LEAD_OLD, LEAD_NEW)
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive(reason="worker done")
    assert out["record"]["target_id"] == LEAD_NEW
    assert out["record"]["target_kind"] == "lead"


def test_target_parent_agent_id_used_when_no_ade_lead_label(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID, parent=PARENT_ID),
            PARENT_ID: _agent(PARENT_ID, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive()
    assert out["record"]["target_id"] == PARENT_ID
    assert out["record"]["target_kind"] == "lead"


def test_target_standing_watcher_fallback_when_no_lead(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            WATCHER_ID: _agent(WATCHER_ID, status="idle"),
            SUP_ID: _agent(SUP_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_supervisor_lead(tmp_path / "supervisor", SUP_ID)
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive(reason="loose finish")
    assert out["record"]["target_id"] == WATCHER_ID
    assert out["record"]["target_kind"] == "watcher"


def test_target_supervisor_lead_fallback_when_watcher_absent_or_archived(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            WATCHER_ID: _agent(WATCHER_ID, archived=True),
            SUP_ID: _agent(SUP_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_supervisor_lead(tmp_path / "supervisor", SUP_ID)
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive()
    assert out["record"]["target_id"] == SUP_ID
    assert out["record"]["target_kind"] == "supervisor"


def test_supervisor_lead_equal_to_self_is_refused(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID)},
        watcher_payload=None,
    )
    _write_supervisor_lead(tmp_path / "supervisor", SELF_ID)
    svc = _make_service(tmp_path, fake)

    with pytest.raises(ara.ArchiveRequestRefused, match="caller itself"):
        svc.request_archive()
    assert not any(c[1:2] == ["send"] for c in fake.calls)


def test_self_target_refused_for_explicit_to_and_lead(tmp_path: Path) -> None:
    fake = FakePaseo(agents={SELF_ID: _agent(SELF_ID)})
    svc = _make_service(tmp_path, fake)

    with pytest.raises(ara.ArchiveRequestRefused, match="self-target"):
        svc.request_archive(explicit_to=SELF_ID)
    with pytest.raises(ara.ArchiveRequestRefused, match="self-target"):
        svc.request_archive(explicit_lead=SELF_ID)
    assert not any(c[1:2] == ["send"] for c in fake.calls)


def test_archived_target_refused_fail_closed_never_sends(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            EXPLICIT_ID: _agent(EXPLICIT_ID, archived=True),
            WATCHER_ID: _agent(WATCHER_ID, archived=True),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    svc = _make_service(tmp_path, fake)

    with pytest.raises(ara.ArchiveRequestRefused, match="archived"):
        svc.request_archive(explicit_to=EXPLICIT_ID)
    with pytest.raises(ara.ArchiveRequestRefused, match="archived"):
        svc.request_archive()
    assert not any(c[1:2] == ["send"] for c in fake.calls)
    assert not (tmp_path / "archive-requests" / f"{SELF_ID}.json").exists()


def test_cyclic_succession_ledger_fails_closed(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            LEAD_OLD: _agent(LEAD_OLD),
            LEAD_NEW: _agent(LEAD_NEW),
        }
    )
    _write_agent_label(tmp_path / "paseo-home", SELF_ID, LEAD_OLD)
    _write_handoff(tmp_path / "self-session", tmp_path / "paseo-home", LEAD_OLD, LEAD_NEW)
    _write_handoff(tmp_path / "self-session", tmp_path / "paseo-home", LEAD_NEW, LEAD_OLD)
    svc = _make_service(tmp_path, fake)

    with pytest.raises(ara.ArchiveRequestRefused, match="cyclic"):
        svc.request_archive()
    assert not any(c[1:2] == ["send"] for c in fake.calls)


def test_send_failure_records_failure_and_raises(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle"),
        },
        send_rc=2,
        send_stderr="daemon refused",
    )
    svc = _make_service(tmp_path, fake)
    with pytest.raises(ara.ArchiveRequestError, match="exited 2"):
        svc.request_archive(explicit_to=EXPLICIT_ID)
    rec = json.loads((tmp_path / "archive-requests" / f"{SELF_ID}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "pending"
    assert rec["send_status"] == "failed"
    assert rec["send_rc"] == 2


# ---- Sweep tests ---------------------------------------------------------------------------------


def _seed_request(
    tmp_path: Path,
    agent_id: str,
    target_id: str,
    *,
    status: str = "pending",
    home: Path | None = None,
) -> Path:
    d = tmp_path / "archive-requests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{agent_id}.json"
    rec = {
        "schema_version": 1,
        "agent_id": agent_id,
        "target_id": target_id,
        "target_kind": "watcher",
        "request_id": "12345678-1234-1234-1234-1234567890ab",
        "reason": "loose finish",
        "requested_at": "2026-11-23T14:55:00Z",
        "home": str((home or (tmp_path / "paseo-home")).resolve()),
        "status": status,
    }
    p.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    return p


def test_sweep_observe_only_never_archives_or_mutates(tmp_path: Path) -> None:
    p_idle = _seed_request(tmp_path, SELF_ID, WATCHER_ID)
    before = p_idle.read_text(encoding="utf-8")
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="running"),
        },
        listed=[SELF_ID, WATCHER_ID],
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=False)
    assert out["errors"] == 0
    assert out["results"] == [
        {
            "file": f"{SELF_ID}.json",
            "agent_id": SELF_ID,
            "target_id": WATCHER_ID,
            "action": "would-archive",
            "agent_status": "idle",
        }
    ]
    assert not any(c[1:3] == ["agent", "archive"] for c in fake.calls)
    assert p_idle.read_text(encoding="utf-8") == before


def test_sweep_apply_guards_running_perms_listing_gap_already_archived_and_archives_idle(tmp_path: Path) -> None:
    id_idle = "11111111-1111-1111-1111-111111111111"
    id_closed = "11111111-1111-1111-1111-111111111112"
    id_running = "11111111-1111-1111-1111-111111111113"
    id_perms = "11111111-1111-1111-1111-111111111114"
    id_gap = "11111111-1111-1111-1111-111111111115"
    id_done = "11111111-1111-1111-1111-111111111116"
    id_other_target = "11111111-1111-1111-1111-111111111117"

    p_idle = _seed_request(tmp_path, id_idle, WATCHER_ID)
    p_closed = _seed_request(tmp_path, id_closed, WATCHER_ID)
    p_running = _seed_request(tmp_path, id_running, WATCHER_ID)
    p_perms = _seed_request(tmp_path, id_perms, WATCHER_ID)
    p_gap = _seed_request(tmp_path, id_gap, WATCHER_ID)
    _seed_request(tmp_path, id_done, WATCHER_ID, status="archived")
    p_other = _seed_request(tmp_path, id_other_target, OTHER_ID)

    fake = FakePaseo(
        agents={
            id_idle: _agent(id_idle, status="idle"),
            id_closed: _agent(id_closed, status="closed"),
            id_running: _agent(id_running, status="running"),
            id_perms: _agent(id_perms, status="idle", perms=[{"id": "perm-1"}]),
            id_gap: _agent(id_gap, status="idle"),
            id_other_target: _agent(id_other_target, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="running"),
        },
        # id_gap intentionally omitted from `paseo ls -g --json` (paseo#9668 guard)
        listed=[id_idle, id_closed, id_running, id_perms, id_other_target, WATCHER_ID],
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=True, all_requests=False)
    assert out["errors"] == 0
    by_id = {r["agent_id"]: r for r in out["results"]}

    assert by_id[id_idle]["action"] == "archived"
    assert by_id[id_closed]["action"] == "archived"
    assert by_id[id_running] == {"file": f"{id_running}.json", "agent_id": id_running, "action": "skip", "reason": "status:running"}
    assert by_id[id_perms] == {"file": f"{id_perms}.json", "agent_id": id_perms, "action": "skip", "reason": "pending-permissions"}
    assert by_id[id_gap] == {"file": f"{id_gap}.json", "agent_id": id_gap, "action": "skip", "reason": "LISTING_GAP"}
    assert by_id[id_done] == {"file": f"{id_done}.json", "agent_id": id_done, "action": "skip", "reason": "already-archived"}
    assert by_id[id_other_target]["action"] == "skip"
    assert by_id[id_other_target]["reason"] == "other-target"

    # Verify archive calls used no --force and only targeted id_idle & id_closed
    archive_calls = [c for c in fake.calls if c[1:3] == ["agent", "archive"]]
    assert archive_calls == [
        ["paseo", "agent", "archive", id_idle, "--json"],
        ["paseo", "agent", "archive", id_closed, "--json"],
    ]

    # Records updated atomically to archived with 0o600; skipped remain pending
    for p in (p_idle, p_closed):
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["status"] == "archived"
        assert d["archived_by"] == WATCHER_ID
        assert d["archived_at"] == "2026-11-23T15:00:00Z"

    for p in (p_running, p_perms, p_gap, p_other):
        assert json.loads(p.read_text(encoding="utf-8"))["status"] == "pending"


def test_sweep_all_flag_allows_other_target_ownership(tmp_path: Path) -> None:
    p_other = _seed_request(tmp_path, SELF_ID, OTHER_ID)
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID, status="idle"),
            WATCHER_ID: _agent(WATCHER_ID, status="running"),
        },
        listed=[SELF_ID, WATCHER_ID],
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=True, all_requests=True)
    assert out["errors"] == 0
    assert out["results"][0]["action"] == "archived"
    assert json.loads(p_other.read_text(encoding="utf-8"))["status"] == "archived"


def test_sweep_successor_owns_predecessor_requests(tmp_path: Path) -> None:
    p = _seed_request(tmp_path, SELF_ID, LEAD_OLD)
    _write_handoff(tmp_path / "self-session", tmp_path / "paseo-home", LEAD_OLD, LEAD_NEW)
    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID, status="idle"), LEAD_NEW: _agent(LEAD_NEW)},
        listed=[SELF_ID, LEAD_NEW],
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": LEAD_NEW})

    out = svc.sweep(apply=True, all_requests=False)
    assert out["errors"] == 0
    assert out["results"][0]["action"] == "archived"
    assert json.loads(p.read_text(encoding="utf-8"))["status"] == "archived"


def test_sweep_readback_unconfirmed_keeps_record_pending_and_errors(tmp_path: Path) -> None:
    p = _seed_request(tmp_path, SELF_ID, WATCHER_ID)
    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID, status="idle")},
        listed=[SELF_ID],
        archive_updates_state=False,
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=True)
    assert out["errors"] == 1
    assert out["results"][0]["action"] == "error"
    assert out["results"][0]["reason"] == "archive-unconfirmed"
    assert json.loads(p.read_text(encoding="utf-8"))["status"] == "pending"


def test_sweep_wrong_receipt_agent_id_errors_and_keeps_pending(tmp_path: Path) -> None:
    p = _seed_request(tmp_path, SELF_ID, WATCHER_ID)
    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID, status="idle")},
        listed=[SELF_ID],
        archive_receipt_id=OTHER_ID,
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=True)
    assert out["errors"] == 1
    assert out["results"][0]["action"] == "error"
    assert out["results"][0]["reason"].startswith("ARCHIVED_OTHER_AGENT:")
    assert json.loads(p.read_text(encoding="utf-8"))["status"] == "pending"


def test_sweep_marks_already_archived_in_paseo_without_calling_archive(tmp_path: Path) -> None:
    p = _seed_request(tmp_path, SELF_ID, WATCHER_ID)
    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID, status="idle", archived=True)},
        listed=[],
    )
    svc = _make_service(tmp_path, fake, env={"PASEO_AGENT_ID": WATCHER_ID})

    out = svc.sweep(apply=True)
    assert out["errors"] == 0
    assert out["results"][0]["action"] == "already-archived"
    assert not any(c[1:3] == ["agent", "archive"] for c in fake.calls)
    assert json.loads(p.read_text(encoding="utf-8"))["status"] == "archived"


# ---- End-to-end CLI integration with real bin/load-watch -----------------------------------------


def test_cli_end_to_end_with_real_load_watch_and_fake_paseo(tmp_path: Path) -> None:
    lw_dir = tmp_path / "lw-state"
    lw_dir.mkdir(parents=True)
    (lw_dir / "watcher.json").write_text(
        json.dumps({"channel": "paseo", "target": WATCHER_ID, "name": "watch-lead", "paseo_home": None}) + "\n",
        encoding="utf-8",
    )
    paseo_home = tmp_path / "paseo-home"
    paseo_home.mkdir()
    state_dir = tmp_path / "archive-requests"
    log_file = tmp_path / "paseo-calls.jsonl"
    state_file = tmp_path / "paseo-state.json"
    state_file.write_text(
        json.dumps(
            {
                SELF_ID: _agent(SELF_ID, status="idle"),
                WATCHER_ID: _agent(WATCHER_ID, status="idle"),
            }
        ),
        encoding="utf-8",
    )

    fake_paseo = tmp_path / "fake-paseo"
    fake_paseo.write_text(
        f"""#!{sys.executable}
import json, sys
from pathlib import Path
log_p = Path({str(log_file)!r})
state_p = Path({str(state_file)!r})
argv = sys.argv[1:]
with log_p.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv) + "\\n")
agents = json.loads(state_p.read_text(encoding="utf-8"))
if argv[:2] == ["agent", "inspect"]:
    aid = argv[2]
    if aid not in agents:
        sys.stderr.write(json.dumps({{"error": {{"code": "AGENT_NOT_FOUND", "message": "not found"}}}}))
        sys.exit(1)
    print(json.dumps(agents[aid]))
    sys.exit(0)
if argv[:2] == ["ls", "-g"]:
    print(json.dumps([{{"id": k}} for k, v in agents.items() if not v.get("Archived")]))
    sys.exit(0)
if argv[:1] == ["send"]:
    print(json.dumps({{"status": "queued"}}))
    sys.exit(5)
if argv[:2] == ["agent", "archive"]:
    aid = argv[2]
    agents[aid]["Archived"] = True
    state_p.write_text(json.dumps(agents), encoding="utf-8")
    print(json.dumps({{"agentId": aid}}))
    sys.exit(0)
sys.exit(99)
""",
        encoding="utf-8",
    )
    fake_paseo.chmod(0o755)

    env = dict(os.environ)
    env.update(
        {
            "PASEO_AGENT_ID": SELF_ID,
            "PASEO_HOME": str(paseo_home),
            "ADE_ARCHIVE_REQUEST_DIR": str(state_dir),
            "LW_STATE_DIR": str(lw_dir),
            "ADE_SUPERVISOR_STATE_DIR": str(tmp_path / "sup"),
            "ADE_SELF_SESSION_STATE": str(tmp_path / "self-session"),
        }
    )

    # 1. Request archive (also proves `--reason sweep` is NOT misparsed as the sweep subcommand)
    r1 = subprocess.run(
        [str(SCRIPT), "--reason", "sweep", "--paseo", str(fake_paseo), "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r1.returncode == 0, r1.stderr
    d1 = json.loads(r1.stdout)
    assert d1["record"]["target_id"] == WATCHER_ID
    assert d1["record"]["target_kind"] == "watcher"
    assert d1["record"]["reason"] == "sweep"

    # 2. Sweep observe-only as watcher
    env_w = dict(env, PASEO_AGENT_ID=WATCHER_ID)
    r2 = subprocess.run(
        [str(SCRIPT), "sweep", "--paseo", str(fake_paseo), "--json"],
        env=env_w,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r2.returncode == 0, r2.stderr
    d2 = json.loads(r2.stdout)
    assert d2["results"][0]["action"] == "would-archive"

    # 3. Sweep --apply as watcher
    r3 = subprocess.run(
        [str(SCRIPT), "sweep", "--apply", "--paseo", str(fake_paseo), "--json"],
        env=env_w,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r3.returncode == 0, r3.stderr
    d3 = json.loads(r3.stdout)
    assert d3["results"][0]["action"] == "archived"

    # 4. Standing watcher attempting to archive itself exits 4
    r4 = subprocess.run(
        [str(SCRIPT), "--reason", "loose finish", "--paseo", str(fake_paseo), "--json"],
        env=env_w,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r4.returncode == ara.EXIT_REFUSED
    assert "standing watcher" in r4.stderr


def test_discovered_archived_lead_falls_back_to_live_watcher(tmp_path: Path) -> None:
    fake = FakePaseo(
        agents={
            SELF_ID: _agent(SELF_ID),
            LEAD_OLD: _agent(LEAD_OLD, archived=True),
            WATCHER_ID: _agent(WATCHER_ID, status="idle"),
        },
        watcher_payload={"channel": "paseo", "target": WATCHER_ID},
    )
    _write_agent_label(tmp_path / "paseo-home", SELF_ID, LEAD_OLD)
    svc = _make_service(tmp_path, fake)

    out = svc.request_archive(reason="worker done")
    assert out["record"]["target_id"] == WATCHER_ID
    assert out["record"]["target_kind"] == "watcher"


def test_sweep_requires_caller_unless_all(tmp_path: Path) -> None:
    fake = FakePaseo(agents={})
    svc = _make_service(tmp_path, fake, env={})
    with pytest.raises(ara.ArchiveRequestRefused, match="PASEO_AGENT_ID"):
        svc.sweep(apply=False, all_requests=False)


def test_request_refuses_symlink_record_target(tmp_path: Path) -> None:
    req_dir = tmp_path / "archive-requests"
    req_dir.mkdir(parents=True)
    victim = tmp_path / "victim.json"
    victim.write_text("original", encoding="utf-8")
    (req_dir / f"{SELF_ID}.json").symlink_to(victim)

    fake = FakePaseo(
        agents={SELF_ID: _agent(SELF_ID), EXPLICIT_ID: _agent(EXPLICIT_ID, status="idle")}
    )
    svc = _make_service(tmp_path, fake)
    with pytest.raises(ara.ArchiveRequestError, match="symlink"):
        svc.request_archive(explicit_to=EXPLICIT_ID)
    assert victim.read_text(encoding="utf-8") == "original"
    assert not any(c[1:2] == ["send"] for c in fake.calls)

