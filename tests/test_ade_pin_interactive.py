"""Tests for bin/ade-pin-interactive (2026-11-23).

Injects fake `paseo` by absolute path via `--paseo-bin` / `ADE_PASEO_BIN` (never mutates PATH).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-pin-interactive"

FAKE_PASEO = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

calls_path = Path(os.environ["FAKE_CALLS"])
with calls_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")

data = json.loads(Path(os.environ["FAKE_DATA"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]
if argv[:1] == ["ls"]:
    if data.get("ls_rc", 0) != 0:
        sys.stderr.write(data.get("ls_err", "ls failed\\n"))
        sys.exit(data["ls_rc"])
    print(json.dumps(data["rows"]))
    sys.exit(0)
if argv[:2] == ["agent", "update"]:
    aid = argv[2]
    rc = data.get("update_rc", {}).get(aid, 0)
    if rc != 0:
        sys.stderr.write(f"update failed for {aid}\\n")
    sys.exit(rc)
sys.stderr.write(f"unexpected argv: {argv}\\n")
sys.exit(2)
"""


def uid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def write_handoff(state_dir: Path, home: Path, pred: str, succ: str, status: str = "archived") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "kind": "handoff",
        "predecessor": pred,
        "successor": succ,
        "home": str(home.resolve()),
        "status": status,
        "ack": {"agent_id": succ},
    }
    p = state_dir / f"handoff-{pred}.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    p.chmod(0o600)


class FakeEnv:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "paseo-home"
        self.home.mkdir()
        self.self_state = tmp_path / "self-session"
        self.self_state.mkdir()
        self.data_path = tmp_path / "data.json"
        self.calls_path = tmp_path / "calls.jsonl"
        self.paseo_bin = tmp_path / "fake-paseo"
        self.paseo_bin.write_text(FAKE_PASEO, encoding="utf-8")
        self.paseo_bin.chmod(0o755)
        self.data: dict = {"rows": []}

    def calls(self) -> list[list[str]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def run(self, *args: str, use_env_bin: bool = False) -> subprocess.CompletedProcess:
        self.data_path.write_text(json.dumps(self.data), encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "FAKE_DATA": str(self.data_path),
            "FAKE_CALLS": str(self.calls_path),
            "PASEO_HOME": str(self.home),
            "ADE_SELF_SESSION_STATE": str(self.self_state),
        }
        argv = [sys.executable, "-I", str(SCRIPT), *args]
        if use_env_bin:
            env["ADE_PASEO_BIN"] = str(self.paseo_bin)
        else:
            argv += ["--paseo-bin", str(self.paseo_bin)]
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30)


def test_skips_retired_archived_completed_handoff_workers_and_closed(tmp_path: Path):
    env = FakeEnv(tmp_path)
    active_lead = uid(1)
    active_user = uid(2)
    retired_tab = uid(3)
    archived_bool = uid(4)
    archived_at = uid(5)
    handoff_pred = uid(6)
    handoff_succ = uid(7)
    incomplete_pred = uid(8)
    worker_agent = uid(9)
    bg_agent = uid(10)
    herald = uid(11)
    closed_agent = uid(12)

    write_handoff(env.self_state, env.home, handoff_pred, handoff_succ, status="archived")
    write_handoff(env.self_state, env.home, incomplete_pred, uid(99), status="acknowledged")

    env.data["rows"] = [
        {"id": active_lead, "name": "LEAD djbclark-ade", "status": "idle", "background": False},
        {"id": active_user, "name": "Interactive session", "status": "running", "background": False},
        {"id": retired_tab, "name": "RETIRED old lead (-> abc)", "status": "idle", "background": False},
        {"id": archived_bool, "name": "Old lead", "status": "idle", "archived": True},
        {"id": archived_at, "name": "Old lead 2", "status": "idle", "archivedAt": "2026-11-22T00:00:00Z"},
        {"id": handoff_pred, "name": "Lead before rename", "status": "idle", "background": False},
        {"id": handoff_succ, "name": "LEAD successor", "status": "idle", "background": False},
        {"id": incomplete_pred, "name": "Lead mid-handoff", "status": "idle", "background": False},
        {"id": worker_agent, "name": "worker slice-1 1234", "status": "idle", "background": False},
        {"id": bg_agent, "name": "BG job", "status": "idle", "background": True},
        {"id": herald, "name": "Herald summary", "status": "idle", "background": False},
        {"id": closed_agent, "name": "Closed lead", "status": "closed", "background": False},
    ]

    r = env.run()
    assert r.returncode == 0, r.stderr
    calls = env.calls()
    # Must call `ls -g --json` (without `-a`, so archived agents are never pulled).
    assert calls[0] == ["ls", "-g", "--json"]
    tagged = [c[2] for c in calls if c[:2] == ["agent", "update"]]
    assert tagged == [active_lead, active_user, handoff_succ, incomplete_pred]
    for c in calls[1:]:
        assert c == ["agent", "update", c[2], "--label", "ade.interactive=1"]
    assert "tagged 4 non-worker agents ade.interactive=1" in r.stdout


def test_check_mode_makes_no_updates_and_env_bin_works(tmp_path: Path):
    env = FakeEnv(tmp_path)
    a = uid(1)
    b = uid(2)
    env.data["rows"] = [
        {"id": a, "name": "Active lead", "status": "idle"},
        {"id": b, "name": "RETIRED tab", "status": "idle"},
    ]
    r = env.run("--check", use_env_bin=True)
    assert r.returncode == 0, r.stderr
    assert f"would-tag {a}" in r.stdout
    assert b not in r.stdout
    assert "1 non-worker agents" in r.stdout
    assert env.calls() == [["ls", "-g", "--json"]]


def test_update_failure_exits_nonzero(tmp_path: Path):
    env = FakeEnv(tmp_path)
    a = uid(1)
    env.data["rows"] = [{"id": a, "name": "Active lead", "status": "idle"}]
    env.data["update_rc"] = {a: 1}
    r = env.run()
    assert r.returncode == 1
    assert "rc=1" in r.stderr
    assert "tagged 0 non-worker agents" in r.stdout


def test_human_renamed_tabs_classified_by_structured_labels(tmp_path: Path):
    env = FakeEnv(tmp_path)
    renamed_worker = uid(20)
    renamed_lead = uid(21)
    renamed_retired = uid(22)
    state_worker = uid(23)
    # Write a Paseo agent state file with ade.lead label (simulating ls rows without inline labels)
    st_dir = env.home / "agents" / "proj"
    st_dir.mkdir(parents=True, exist_ok=True)
    (st_dir / f"{state_worker}.json").write_text(
        json.dumps({"id": state_worker, "labels": {"ade.lead": renamed_lead, "ade.box": "WORKER"}}),
        encoding="utf-8",
    )
    env.data["rows"] = [
        {"id": renamed_worker, "name": "My custom tab", "status": "idle", "labels": {"ade.lead": renamed_lead, "ade.box": "WORKER"}},
        {"id": state_worker, "name": "Daniel debugging Venice", "status": "idle"},
        {"id": renamed_lead, "name": "worker planning notes", "status": "idle", "labels": {"ade.role": "djbclark-ade", "ade.box": "LEAD"}},
        {"id": renamed_retired, "name": "Custom old tab", "status": "idle", "labels": {"ade.retired": "1"}},
    ]
    r = env.run()
    assert r.returncode == 0, r.stderr
    tagged = [c[2] for c in env.calls() if c[:2] == ["agent", "update"]]
    assert tagged == [renamed_lead]


def test_interactive_worker_in_lead_window_not_confused_with_lead(tmp_path: Path):
    """P2 Round 2 / Codex discussion_r4702323418: worker ownership markers (`ade.lead`, `slice`,
    `parentAgentId`) MUST be checked before `ade.box=LEAD` / `ade.placement=main`."""
    env = FakeEnv(tmp_path)
    lead_id = uid(30)
    interactive_worker = uid(31)
    slice_worker = uid(32)
    parented_worker = uid(33)
    bare_retired_to_lead = uid(34)
    env.data["rows"] = [
        {"id": lead_id, "name": "Daniel debugging Venice", "status": "idle", "labels": {"ade.role": "djbclark-ade", "ade.box": "LEAD"}},
        {
            "id": interactive_worker,
            "name": "Custom interactive tab",
            "status": "idle",
            "labels": {
                "ade.lead": lead_id,
                "slice": "op1",
                "ade.box": "LEAD",
                "ade.placement": "main",
                "ade.repo": "djbclark-ade",
            },
        },
        {
            "id": slice_worker,
            "name": "Custom slice tab",
            "status": "idle",
            "labels": {"slice": "probe", "ade.box": "LEAD"},
        },
        {
            "id": parented_worker,
            "name": "Custom child tab",
            "status": "idle",
            "parentAgentId": lead_id,
            "labels": {"ade.placement": "main"},
        },
        {
            "id": bare_retired_to_lead,
            "name": "Lead with stray retired_to only",
            "status": "idle",
            "labels": {"ade.retired_to": uid(99)},
        },
    ]
    r = env.run()
    assert r.returncode == 0, r.stderr
    tagged = [c[2] for c in env.calls() if c[:2] == ["agent", "update"]]
    assert tagged == [lead_id, bare_retired_to_lead]
