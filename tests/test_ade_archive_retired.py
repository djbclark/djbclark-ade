"""Tests for bin/ade-archive-retired and bin/ade-pin-sweep ordering (2026-11-23).

All fake `paseo` binaries are injected by absolute path via `--paseo-bin` / `ADE_PASEO_BIN`
(never by mutating PATH).
"""
from __future__ import annotations

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "ade-archive-retired"
SWEEP_SCRIPT = REPO / "bin" / "ade-pin-sweep"

FAKE_PASEO = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

calls_path = Path(os.environ["FAKE_CALLS"])
with calls_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")

data_path = Path(os.environ["FAKE_DATA"])
data = json.loads(data_path.read_text(encoding="utf-8"))
argv = sys.argv[1:]

if argv[:1] == ["ls"]:
    if data.get("ls_rc", 0) != 0:
        sys.stderr.write(data.get("ls_err", "ls failed\\n"))
        sys.exit(data["ls_rc"])
    print(json.dumps(data["agents"]))
    sys.exit(0)

if argv[:2] == ["agent", "inspect"]:
    aid = argv[2]
    hook = data.get("on_inspect_write", {}).get(aid)
    if hook:
        Path(hook["path"]).write_text(hook["content"], encoding="utf-8")
    rc = data.get("inspect_rc", {}).get(aid, 0)
    if rc != 0:
        sys.stderr.write(f"inspect failed for {aid}\\n")
        sys.exit(rc)
    seq = data.get("inspect_seq", {}).get(aid)
    if seq is not None:
        idx_map = data.setdefault("_inspect_idx", {})
        i = idx_map.get(aid, 0)
        idx_map[aid] = i + 1
        data_path.write_text(json.dumps(data), encoding="utf-8")
        payload = seq[min(i, len(seq) - 1)]
        print(json.dumps(payload))
        sys.exit(0)
    payload = data.get("inspect", {}).get(aid)
    if payload is None:
        sys.stderr.write(f"not found: {aid}\\n")
        sys.exit(1)
    print(json.dumps(payload))
    sys.exit(0)

if argv[:2] == ["agent", "archive"]:
    aid = argv[2]
    rc = data.get("archive_rc", {}).get(aid, 0)
    if rc != 0:
        sys.stderr.write(f"archive failed for {aid}\\n")
        sys.exit(rc)
    if not data.get("skip_archive_mutation", {}).get(aid, False):
        ins = data.get("inspect", {}).get(aid)
        if isinstance(ins, dict):
            ins["Archived"] = True
            data_path.write_text(json.dumps(data), encoding="utf-8")
    print(json.dumps({"id": aid, "archived": True}))
    sys.exit(0)

sys.stderr.write(f"unexpected argv: {argv}\\n")
sys.exit(2)
"""


def uid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "paseo-home"
        self.home.mkdir()
        self.self_state = tmp_path / "self-session"
        self.self_state.mkdir()
        self.state_dir = tmp_path / "ade-state"
        self.state_dir.mkdir()
        self.lw_dir = tmp_path / "load-watch"
        self.lw_dir.mkdir()
        self.exclude_file = self.state_dir / "helper-prune.exclude"
        self.data_path = tmp_path / "data.json"
        self.calls_path = tmp_path / "calls.jsonl"
        self.paseo_bin = tmp_path / "fake-paseo"
        self.paseo_bin.write_text(FAKE_PASEO, encoding="utf-8")
        self.paseo_bin.chmod(0o755)
        self.now = time.time()
        self.data: dict = {"agents": [], "inspect": {}, "archive_rc": {}, "inspect_rc": {}}

    def add_agent(
        self,
        aid: str,
        name: str,
        *,
        status: str = "idle",
        archived: object = False,
        perms: object = None,
        updated_at: object = "__default__",
        inspect_name: str | None = None,
        inspect_id: str | None = None,
        omit_keys: tuple[str, ...] = (),
        labels: dict | None = None,
    ) -> str:
        row: dict = {"id": aid, "name": name, "status": status}
        if labels is not None:
            row["labels"] = labels
        self.data["agents"].append(row)
        ins: dict = {
            "Id": aid if inspect_id is None else inspect_id,
            "Name": name if inspect_name is None else inspect_name,
            "Status": status,
            "Archived": archived,
            "PendingPermissions": [] if perms is None else perms,
            "UpdatedAt": iso(self.now - 600) if updated_at == "__default__" else updated_at,
        }
        for k in omit_keys:
            ins.pop(k, None)
        self.data["inspect"][aid] = ins
        return aid

    def calls(self) -> list[list[str]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def log_entries(self) -> list[dict]:
        p = self.state_dir / "archive-retired.log"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def run(
        self,
        *args: str,
        apply: bool = False,
        json_out: bool = True,
        self_agent_id: str | None = None,
        use_env_bin: bool = False,
        paseo_home_env: str | None = "__default__",
    ) -> subprocess.CompletedProcess:
        self.data_path.write_text(json.dumps(self.data), encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "FAKE_DATA": str(self.data_path),
            "FAKE_CALLS": str(self.calls_path),
            "ADE_SELF_SESSION_STATE": str(self.self_state),
            "ADE_ARCHIVE_RETIRED_STATE": str(self.state_dir),
            "ADE_HELPER_PRUNE_EXCLUDE": str(self.exclude_file),
            "LW_STATE_DIR": str(self.lw_dir),
        }
        if paseo_home_env == "__default__":
            env["PASEO_HOME"] = str(self.home)
        elif paseo_home_env is not None:
            env["PASEO_HOME"] = paseo_home_env
        if self_agent_id is not None:
            env["PASEO_AGENT_ID"] = self_agent_id
        argv = [sys.executable, "-I", str(SCRIPT)]
        if apply:
            argv.append("--apply")
        if json_out:
            argv.append("--json")
        if use_env_bin:
            env["ADE_PASEO_BIN"] = str(self.paseo_bin)
        else:
            argv += ["--paseo-bin", str(self.paseo_bin)]
        argv.extend(args)
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30)


def test_archives_idle_and_closed_retired_and_handoff_predecessors(tmp_path: Path):
    env = Env(tmp_path)
    retired_idle = env.add_agent(uid(1), "RETIRED lead A (-> xyz)", status="idle")
    retired_closed = env.add_agent(uid(2), "RETIRED lead B", status="closed")
    handoff_pred = env.add_agent(uid(3), "Old lead before rename", status="idle")
    active_lead = env.add_agent(uid(4), "LEAD active repo", status="idle")
    write_handoff(env.self_state, env.home, handoff_pred, uid(50), status="archived")

    # Dry-run first: selects 3, archives nothing, writes no log.
    dry = env.run(apply=False)
    assert dry.returncode == 0, dry.stderr
    dry_s = json.loads(dry.stdout)
    assert {x["id"] for x in dry_s["selected"]} == {retired_idle, retired_closed, handoff_pred}
    assert dry_s["archived"] == []
    assert env.log_entries() == []
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())
    # Active non-retired agent was never even inspected.
    assert not any(c == ["agent", "inspect", active_lead, "--json"] for c in env.calls())

    # Apply: archives all 3 with readback verification and NO --force.
    env.calls_path.unlink()
    res = env.run(apply=True)
    assert res.returncode == 0, res.stderr
    s = json.loads(res.stdout)
    assert {x["id"] for x in s["archived"]} == {retired_idle, retired_closed, handoff_pred}
    assert s["errors"] == []
    archive_calls = [c for c in env.calls() if c[:2] == ["agent", "archive"]]
    assert len(archive_calls) == 3
    for c in archive_calls:
        assert "--force" not in c
        assert c == ["agent", "archive", c[2], "--json"]
    # Verify readback inspect happened for each archived agent (2 inspects each: pre + post).
    for aid in (retired_idle, retired_closed, handoff_pred):
        insp = [c for c in env.calls() if c == ["agent", "inspect", aid, "--json"]]
        assert len(insp) == 2
    logs = env.log_entries()
    assert len(logs) == 3
    assert all(e["verified"] is True and e["rc"] == 0 for e in logs)
    assert {e["agent"]: e["proof"] for e in logs} == {
        retired_idle: "retired-name",
        retired_closed: "retired-name",
        handoff_pred: "handoff-successor",
    }


def test_skips_unsafe_candidates_fail_closed(tmp_path: Path):
    env = Env(tmp_path)
    running = env.add_agent(uid(1), "RETIRED running", status="running")
    pending = env.add_agent(uid(2), "RETIRED perm", status="idle", perms=[{"id": "p1"}])
    missing_perms = env.add_agent(uid(3), "RETIRED no-perms-key", status="idle", omit_keys=("PendingPermissions",))
    nonlist_perms = env.add_agent(uid(4), "RETIRED bad-perms", status="idle", perms="none")
    recent = env.add_agent(uid(5), "RETIRED recent", status="idle", updated_at=iso(env.now - 30))
    future = env.add_agent(uid(6), "RETIRED future", status="idle", updated_at=iso(env.now + 300))
    missing_upd = env.add_agent(uid(7), "RETIRED no-upd", status="idle", omit_keys=("UpdatedAt",))
    naive_upd = env.add_agent(uid(8), "RETIRED naive-upd", status="idle", updated_at="2026-11-22T10:00:00")
    already_arch = env.add_agent(uid(9), "RETIRED archived", status="idle", archived=True)
    missing_arch = env.add_agent(uid(10), "RETIRED no-arch", status="idle", omit_keys=("Archived",))
    self_aid = env.add_agent(uid(11), "RETIRED self", status="idle")
    watcher_aid = env.add_agent(uid(12), "RETIRED watcher", status="idle")
    excl_file_aid = env.add_agent(uid(13), "RETIRED excl-file", status="idle")
    excl_cli_aid = env.add_agent(uid(14), "RETIRED excl-cli", status="idle")
    id_mismatch = env.add_agent(uid(15), "RETIRED mismatch", status="idle", inspect_id=uid(99))
    renamed_active = env.add_agent(uid(16), "RETIRED renamed", status="idle", inspect_name="LEAD active again")
    inspect_fail = env.add_agent(uid(17), "RETIRED inspect-err", status="idle")
    env.data["inspect_rc"][inspect_fail] = 1

    (env.lw_dir / "watcher.json").write_text(
        json.dumps({"channel": "paseo", "target": watcher_aid, "paseo_home": str(env.home)}),
        encoding="utf-8",
    )
    env.exclude_file.write_text(f"# protect this one\n{excl_file_aid}\n", encoding="utf-8")

    res = env.run("--exclude", excl_cli_aid, apply=True, self_agent_id=self_aid)
    assert res.returncode == 0, res.stderr
    s = json.loads(res.stdout)
    assert s["archived"] == []
    assert s["selected"] == []
    reasons = {x["id"]: x["reason"] for x in s["skipped"]}
    assert reasons == {
        running: "not-idle",
        pending: "pending-permissions",
        missing_perms: "pending-permissions",
        nonlist_perms: "pending-permissions",
        recent: "recently-active",
        future: "future-updated-at",
        missing_upd: "invalid-updated-at",
        naive_upd: "invalid-updated-at",
        already_arch: "archived-or-unknown",
        missing_arch: "archived-or-unknown",
        self_aid: "self",
        watcher_aid: "load-watcher",
        excl_file_aid: "excluded",
        excl_cli_aid: "excluded",
        id_mismatch: "id-mismatch",
        renamed_active: "name-changed",
        inspect_fail: "inspect-failed",
    }
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())


def test_corrupt_watcher_json_fails_closed(tmp_path: Path):
    env = Env(tmp_path)
    aid = env.add_agent(uid(1), "RETIRED tab", status="idle")
    other_home = tmp_path / "other-paseo-home"
    other_home.mkdir()
    bad_payloads = [
        "{not json",
        "[]",
        "{}",
        json.dumps({"channel": "paseo"}),
        # Non-UUID targets (short ID, name, empty)
        json.dumps({"channel": "paseo", "target": "cf860294", "paseo_home": str(env.home)}),
        json.dumps({"channel": "paseo", "target": "Load watcher", "paseo_home": str(env.home)}),
        json.dumps({"channel": "paseo", "target": "", "paseo_home": str(env.home)}),
        # Invalid, padded, uppercase, or unknown channels
        json.dumps({"channel": "paseo ", "target": uid(99), "paseo_home": str(env.home)}),
        json.dumps({"channel": " paseo", "target": uid(99), "paseo_home": str(env.home)}),
        json.dumps({"channel": "PASEO", "target": uid(99), "paseo_home": str(env.home)}),
        json.dumps({"channel": "paseoo", "target": uid(99), "paseo_home": str(env.home)}),
        json.dumps({"channel": "smoke", "target": uid(99), "paseo_home": str(env.home)}),
        json.dumps({"channel": 123, "target": uid(99), "paseo_home": str(env.home)}),
        # paseo_home mismatch or malformed
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": str(other_home)}),
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": None}),  # HOME/.paseo != env.home
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": "relative/paseo"}),
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": ""}),
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": 42}),
    ]
    watcher_path = env.lw_dir / "watcher.json"
    for bad in bad_payloads:
        watcher_path.write_text(bad, encoding="utf-8")
        env.calls_path.unlink(missing_ok=True)
        res = env.run(apply=True)
        assert res.returncode == 1, f"expected fail-closed rc=1 for {bad!r}"
        s = json.loads(res.stdout)
        assert s["archived"] == []
        assert s["skipped"] == [{"id": aid, "reason": "watcher-unreadable"}]
        assert not any(c[:2] == ["agent", "archive"] for c in env.calls())

    # Symlink watcher.json must fail closed
    real_target = tmp_path / "real-watcher.json"
    real_target.write_text(
        json.dumps({"channel": "paseo", "target": uid(99), "paseo_home": str(env.home)}),
        encoding="utf-8",
    )
    watcher_path.unlink()
    watcher_path.symlink_to(real_target)
    env.calls_path.unlink(missing_ok=True)
    res_sym = env.run(apply=True)
    assert res_sym.returncode == 1
    assert json.loads(res_sym.stdout)["archived"] == []
    assert json.loads(res_sym.stdout)["skipped"] == [{"id": aid, "reason": "watcher-unreadable"}]
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())

    # Non-regular watcher.json (directory) must fail closed
    watcher_path.unlink()
    watcher_path.mkdir()
    env.calls_path.unlink(missing_ok=True)
    res_dir = env.run(apply=True)
    assert res_dir.returncode == 1
    assert json.loads(res_dir.stdout)["archived"] == []
    assert json.loads(res_dir.stdout)["skipped"] == [{"id": aid, "reason": "watcher-unreadable"}]
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())


def test_watcher_valid_default_home_and_relay_channel(tmp_path: Path):
    # paseo_home=None resolves to ~/.paseo and matches when PASEO_HOME is unset.
    env = Env(tmp_path)
    (tmp_path / ".paseo").mkdir()
    watcher_aid = env.add_agent(uid(1), "RETIRED watcher", status="idle")
    other_aid = env.add_agent(uid(2), "RETIRED other", status="idle")
    (env.lw_dir / "watcher.json").write_text(
        json.dumps({"channel": "paseo", "target": watcher_aid, "paseo_home": None}),
        encoding="utf-8",
    )
    res = env.run(apply=True, paseo_home_env=None)
    assert res.returncode == 0, res.stderr
    s = json.loads(res.stdout)
    assert [x["id"] for x in s["archived"]] == [other_aid]
    assert s["skipped"] == [{"id": watcher_aid, "reason": "load-watcher"}]

    # Exact legacy channel == "relay" is accepted as non-paseo and does not block archiving.
    relay_tmp = tmp_path / "relay_case"
    relay_tmp.mkdir()
    env2 = Env(relay_tmp)
    a2 = env2.add_agent(uid(3), "RETIRED tab", status="idle")
    (env2.lw_dir / "watcher.json").write_text(
        json.dumps({"channel": "relay", "target": "sess-1"}),
        encoding="utf-8",
    )
    res2 = env2.run(apply=True)
    assert res2.returncode == 0, res2.stderr
    assert [x["id"] for x in json.loads(res2.stdout)["archived"]] == [a2]


def test_apply_recheck_failure_does_not_double_account_selected(tmp_path: Path):
    env = Env(tmp_path)
    excl_mid = env.add_agent(uid(1), "RETIRED excl-mid", status="idle")
    watch_mid = env.add_agent(uid(2), "RETIRED watch-mid", status="idle")
    # Mutate exclude file and watcher.json during inspect (after initial scan, before pre-archive re-check).
    env.data["on_inspect_write"] = {
        excl_mid: {"path": str(env.exclude_file), "content": f"{excl_mid}\n"},
        watch_mid: {
            "path": str(env.lw_dir / "watcher.json"),
            "content": json.dumps({"channel": "paseo", "target": watch_mid, "paseo_home": str(env.home)}),
        },
    }
    res = env.run(apply=True)
    assert res.returncode == 0, res.stderr
    s = json.loads(res.stdout)
    assert s["selected"] == []
    assert s["archived"] == []
    assert {x["id"]: x["reason"] for x in s["skipped"]} == {
        excl_mid: "excluded",
        watch_mid: "load-watcher",
    }
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())


def test_skips_candidate_with_live_non_retired_non_baton_child(tmp_path: Path):
    env = Env(tmp_path)
    parent_live_child = env.add_agent(uid(1), "RETIRED parent with live child", status="idle")
    parent_retired_child = env.add_agent(uid(2), "RETIRED parent with retired child", status="idle")
    parent_baton_child = env.add_agent(uid(3), "RETIRED parent with baton child", status="idle")

    env.add_agent(
        uid(10),
        "worker active-slice",
        status="idle",
        labels={"paseo.parent-agent-id": parent_live_child},
    )
    env.add_agent(
        uid(11),
        "RETIRED old child",
        status="idle",
        labels={"paseo.parent-agent-id": parent_retired_child},
    )
    env.add_agent(
        uid(12),
        "[Handoff writer]",
        status="idle",
        labels={"paseo.parent-agent-id": parent_baton_child, "baton-writer": "1"},
    )

    res = env.run(apply=True)
    assert res.returncode == 0, res.stderr
    s = json.loads(res.stdout)
    assert s["skipped"] == [{"id": parent_live_child, "reason": "has-children"}]
    assert {x["id"] for x in s["archived"]} == {parent_retired_child, parent_baton_child, uid(11)}


def test_corrupt_exclude_file_fails_closed(tmp_path: Path):
    env = Env(tmp_path)
    env.add_agent(uid(1), "RETIRED tab", status="idle")
    env.exclude_file.write_text("not-a-uuid\n", encoding="utf-8")
    res = env.run(apply=True)
    assert res.returncode == 1
    s = json.loads(res.stdout)
    assert s["archived"] == []
    assert any("not a full agent id" in e["what"] for e in s["errors"])
    assert not any(c[:2] == ["agent", "archive"] for c in env.calls())


def test_readback_failure_reports_error_and_logs(tmp_path: Path):
    env = Env(tmp_path)
    aid = env.add_agent(uid(1), "RETIRED stuck", status="idle")
    env.data["skip_archive_mutation"] = {aid: True}
    res = env.run(apply=True)
    assert res.returncode == 1
    s = json.loads(res.stdout)
    assert s["archived"] == []
    assert len(s["errors"]) == 1
    assert "Archived=true" in s["errors"][0]["what"]
    logs = env.log_entries()
    assert len(logs) == 1
    assert logs[0]["agent"] == aid and logs[0]["verified"] is False


def test_lock_held_skips_cleanly(tmp_path: Path):
    env = Env(tmp_path)
    env.add_agent(uid(1), "RETIRED tab", status="idle")
    lock_path = env.state_dir / "archive-retired.lock"
    with lock_path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        res = env.run(apply=True, json_out=False)
        assert res.returncode == 0, res.stderr
        assert "lock held" in res.stdout
        assert env.calls() == []


def test_text_summary_and_bad_cli_args(tmp_path: Path):
    env = Env(tmp_path)
    env.add_agent(uid(1), "RETIRED tab", status="idle")
    env.add_agent(uid(2), "RETIRED running", status="running")
    r_dry = env.run(apply=False, json_out=False, use_env_bin=True)
    assert r_dry.returncode == 0
    assert r_dry.stdout.strip() == "would archive 1 retired agents (skipped 1)"

    r_app = env.run(apply=True, json_out=False, use_env_bin=True)
    assert r_app.returncode == 0
    assert r_app.stdout.strip() == "archived 1 retired agents (skipped 1)"

    assert env.run("--min-idle", "-1").returncode == 2
    assert env.run("--min-idle", "nan").returncode == 2
    assert env.run("--exclude", "bad-id").returncode == 2


def test_ade_pin_sweep_runs_archive_retired_before_pin_interactive(tmp_path: Path, monkeypatch):
    order_log = tmp_path / "order.jsonl"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("ade-archive-retired", "ade-pin-interactive", "ade-pin-workspaces"):
        p = fake_bin / name
        p.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            f"with open({str(order_log)!r}, 'a', encoding='utf-8') as fh:\n"
            f"    fh.write(json.dumps([{name!r}, *sys.argv[1:]]) + '\\n')\n"
            f"print('{name} ok')\n",
            encoding="utf-8",
        )
        p.chmod(0o755)

    loader = importlib.machinery.SourceFileLoader("_ade_pin_sweep_test", str(SWEEP_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    monkeypatch.setattr(mod, "BIN", fake_bin)
    rc = mod.main()
    assert rc == 0
    calls = [json.loads(line) for line in order_log.read_text(encoding="utf-8").splitlines()]
    assert calls == [
        ["ade-archive-retired", "--apply"],
        ["ade-pin-interactive"],
        ["ade-pin-workspaces", "pin"],
    ]
