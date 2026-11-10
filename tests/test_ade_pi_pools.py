"""config/pi-pool-acceptance.toml + bin/ade_pi_pools: auto-routing acceptance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_pi_pools as pools  # noqa: E402
import pi_defaults as defaults  # noqa: E402
import route_agent as router  # noqa: E402

MODELS = ["zai/glm-5.3-flash", "cursor/composer-2.5"]


def reading(left):
    return {"remaining": left, "age_s": 0, "windows": {"weekly": left}}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_PI_DEFAULTS_BLOCKS", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(router, "AIUSE_CONFIG", tmp_path / "no-config.toml")
    monkeypatch.setattr(router, "paseo_providers", lambda: {"pi", "claude", "codex", "cursor"})
    monkeypatch.setattr(router, "kind_rows", lambda *_: [])


def write_acceptance(tmp_path, text: str) -> Path:
    path = tmp_path / "pi-pool-acceptance.toml"
    path.write_text(text)
    return path


def test_shipped_file_accepts_only_the_live_cursor_and_zai_shortlist():
    rows = pools.load_acceptance(REPO / "config" / "pi-pool-acceptance.toml")
    assert rows["cursor"]["accepted"] is True and rows["zai"]["accepted"] is True
    for name in ("grok", "antigravity", "sipb", "go"):
        assert rows[name]["accepted"] is False
    code, _, blocking = pools.check_auto(REPO / "config" / "pi-pool-acceptance.toml")
    assert code == 0 and blocking == []
    assert set(pools.routing_pi_services()) == {"cursor", "zai"}


def test_unaccepted_routing_pi_service_blocks_check_and_auto_choose(monkeypatch, tmp_path):
    path = write_acceptance(tmp_path, """
[pools.cursor]
accepted = false
note = "revoked for test"

[pools.zai]
accepted = true
""")
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    assert pools.unaccepted_auto_services() == {"cursor"}
    code, _, blocking = pools.check_auto()
    assert code == 2 and blocking == ["cursor"]
    result = defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(80)})
    assert result["service"] == "zai"
    result = defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(90)},
                             excluded={"zai"})
    assert result["service"] is None
    assert "unaccepted pool(s): cursor" in result["reason"]
    assert "pi-pool-acceptance.toml" in result["reason"]


def test_missing_acceptance_row_for_a_routing_pi_service_fails_closed(monkeypatch, tmp_path):
    path = write_acceptance(tmp_path, """
[pools.zai]
accepted = true
""")
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    assert pools.unaccepted_auto_services() == {"cursor"}
    assert pools.check_auto()[0] == 2


def test_missing_acceptance_file_blocks_every_routing_pi_service(monkeypatch, tmp_path):
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(tmp_path / "absent.toml"))
    assert pools.unaccepted_auto_services() == {"cursor", "zai"}
    assert pools.check_auto()[0] == 2
    assert defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(90)})["service"] is None


def test_cli_check_and_ls_exit_codes(tmp_path):
    import os
    path = write_acceptance(tmp_path, """
[pools.cursor]
accepted = true

[pools.zai]
accepted = false
""")
    env = {**os.environ, "PI_POOL_ACCEPTANCE": str(path), "PYTHONPATH": str(BIN)}
    check = subprocess.run([sys.executable, str(BIN / "ade-pi-pools"), "check", "--json"],
                           capture_output=True, text=True, env=env, cwd=str(REPO))
    assert check.returncode == 2, check.stderr
    payload = json.loads(check.stdout)
    assert payload["ready"] is False and "zai" in payload["blocking"]
    ls = subprocess.run([sys.executable, str(BIN / "ade-pi-pools"), "ls", "--json"],
                        capture_output=True, text=True, env=env, cwd=str(REPO))
    assert ls.returncode == 0
    assert {r["pool"] for r in json.loads(ls.stdout)["pools"]} >= {"cursor", "zai"}


def test_shipped_file_records_identity_and_billing_labels():
    rows = pools.load_acceptance(REPO / "config" / "pi-pool-acceptance.toml")
    assert rows["grok"]["identity"] == "xai-oauth-subscription"
    assert rows["grok"]["billing"] == "subscription"
    assert rows["antigravity"]["identity"] == "google-oauth-antigravity"
    assert rows["cursor"]["accepted"] is True and rows["grok"]["accepted"] is False


def test_probe_quota_pass_fail_unknown_and_claude_api_skip():
    assert pools.probe_quota("grok", quota={"grok": reading(40)}, snapshot_age=0)["status"] == "pass"
    assert pools.probe_quota("grok", quota={"grok": reading(0)}, snapshot_age=0)["status"] == "fail"
    stale = {"remaining": 50, "age_s": router.STALE_SOFT + 1, "windows": {"weekly": 50}}
    assert pools.probe_quota("grok", quota={"grok": stale}, snapshot_age=stale["age_s"])["status"] == "fail"
    assert pools.probe_quota("grok", quota={}, snapshot_age=0)["status"] == "unknown"
    skip = pools.probe_quota("omp", quota={"omp": reading(90)}, snapshot_age=0)
    assert skip["status"] == "skip"
    assert "Claude API" in skip["detail"]


def test_probe_quota_string_paseo_unknown_does_not_pass(tmp_path):
    """_fold_paseo records paseo_unknown as a descriptive string, not bool True.

    A fresh positive aiuse reading with that string must still fail quota (and not
    mark the pool ready) — identity ``is True`` would miss it and report pass.
    """
    row = reading(55)
    row["paseo_unknown"] = "paseo usage: no window reading"
    result = pools.probe_quota("grok", quota={"grok": row}, snapshot_age=0)
    assert result["status"] == "fail"
    assert "unknown" in result["detail"]

    bool_row = reading(55)
    bool_row["paseo_unknown"] = True
    assert pools.probe_quota("grok", quota={"grok": bool_row}, snapshot_age=0)["status"] == "fail"

    path = write_acceptance(tmp_path, """
[pools.grok]
accepted = false
identity = "xai-oauth-subscription"
billing = "subscription"
""")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "grok.json").write_text(json.dumps({
        "schema_version": 1,
        "continuation": {"ok": True, "note": "ok"},
    }))
    code, results = pools.probe_pools(
        ["grok"], path=path, quota={"grok": row}, snapshot_age=0, evidence=evidence,
    )
    assert code == 2
    assert results[0]["probes"]["quota"]["status"] == "fail"
    assert results[0]["all_dimensions_pass"] is False
    assert results[0]["ready_for_operator_accept"] is False


def test_probe_identity_and_continuation(tmp_path, monkeypatch):
    path = write_acceptance(tmp_path, """
[pools.grok]
accepted = false
identity = "xai-oauth-subscription"
billing = "subscription"

[pools.sipb]
accepted = false
""")
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    assert pools.probe_identity("grok", path=path)["status"] == "pass"
    assert pools.probe_identity("sipb", path=path)["status"] == "unknown"
    assert pools.probe_identity("omp", path=path)["status"] == "skip"

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setenv("ADE_PI_ACCEPTANCE_EVIDENCE_DIR", str(evidence))
    assert pools.probe_continuation("grok", evidence=evidence)["status"] == "unknown"
    (evidence / "grok.json").write_text(json.dumps({
        "schema_version": 1,
        "pool": "grok",
        "continuation": {"ok": True, "note": "two-request resume"},
    }))
    assert pools.probe_continuation("grok", evidence=evidence)["status"] == "pass"
    (evidence / "sipb.json").write_text(json.dumps({
        "schema_version": 1,
        "continuation": {"ok": False, "note": "resume lost nonce"},
    }))
    assert pools.probe_continuation("sipb", evidence=evidence)["status"] == "fail"
    assert pools.probe_continuation("anthropic", evidence=evidence)["status"] == "skip"


def test_probe_never_writes_accepted_and_reports_ready(monkeypatch, tmp_path, capsys):
    path = write_acceptance(tmp_path, """
[pools.grok]
accepted = false
identity = "xai-oauth-subscription"
billing = "subscription"
""")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "grok.json").write_text(json.dumps({
        "schema_version": 1,
        "continuation": {"ok": True, "note": "ok"},
    }))
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    quota = {"grok": reading(55)}
    code, results = pools.probe_pools(
        ["grok"], path=path, quota=quota, snapshot_age=0, evidence=evidence,
    )
    assert code == 0
    assert results[0]["all_dimensions_pass"] is True
    assert results[0]["ready_for_operator_accept"] is True
    assert results[0]["writes_accepted"] is False
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime

    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    monkeypatch.setattr(router, "load_snapshot", lambda bypass_memo=False: (quota, 0.0))
    rc = pools.main(["probe", "--json", "--pool", "grok", "--evidence-dir", str(evidence)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["writes_accepted"] is False
    assert payload["claude_api_billing_probed"] is False
    assert payload["pools"][0]["all_dimensions_pass"] is True
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime


def test_probe_incomplete_when_continuation_missing(monkeypatch, tmp_path):
    path = write_acceptance(tmp_path, """
[pools.grok]
accepted = false
identity = "xai-oauth-subscription"
billing = "subscription"
""")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    code, results = pools.probe_pools(
        ["grok"],
        path=path,
        quota={"grok": reading(40)},
        snapshot_age=0,
        evidence=evidence,
    )
    assert code == 3
    assert results[0]["probes"]["continuation"]["status"] == "unknown"
    assert results[0]["ready_for_operator_accept"] is False
