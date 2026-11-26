"""Tests for bin/ade_lead_of.py and bin/ade-lead-of (Carried #106 and #107)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_lead_of as lead_of  # noqa: E402
import ade_ws_names as ws_names  # noqa: E402
from test_ade_lead_succession import A, B, C, D, write_link  # noqa: E402

E = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
WKS_LEAD = "wks_1111111111111111"
WKS_WORKER = "wks_2222222222222222"
WKS_OTHER = "wks_3333333333333333"


def _inspect_map(agents: dict[str, dict]):
    def inspect(ident: str) -> dict:
        if ident not in agents:
            raise LookupError(ident)
        return dict(agents[ident])
    return inspect


def test_write_read_list_repo_leads_and_security_checks(tmp_path):
    state = tmp_path / "state"
    home = tmp_path / "paseo-home"
    home.mkdir()
    other_home = tmp_path / "other-home"
    other_home.mkdir()

    rec = lead_of.write_repo_lead(
        "djbclark-ade", A, source="finish", predecessor=B, cwd="/tmp/djbclark-ade",
        state_dir=state, home=home,
    )
    assert rec["repo"] == "djbclark-ade"
    assert rec["lead"] == A
    assert rec["source"] == "finish"
    path = lead_of.repo_record_path("djbclark-ade", state_dir=state)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    # Valid read for matching home, None for different home.
    assert lead_of.read_repo_lead("djbclark-ade", state_dir=state, home=home)["lead"] == A
    assert lead_of.read_repo_lead("djbclark-ade", state_dir=state, home=other_home) is None

    # List returns valid records only.
    lead_of.write_repo_lead("tendcf", B, source="manual", state_dir=state, home=home)
    listed = lead_of.list_repo_leads(state_dir=state, home=home)
    assert [r["repo"] for r in listed] == ["djbclark-ade", "tendcf"]

    # Group/world-writable file is rejected fail-closed.
    path.chmod(0o644)
    assert lead_of.read_repo_lead("djbclark-ade", state_dir=state, home=home)["lead"] == A
    path.chmod(0o666)
    assert lead_of.read_repo_lead("djbclark-ade", state_dir=state, home=home) is None
    path.chmod(0o600)

    # Symlink target is refused on both read and write.
    real_target = tmp_path / "real.json"
    real_target.write_text(path.read_text())
    sym = lead_of.repo_record_path("symrepo", state_dir=state)
    os.symlink(real_target, sym)
    assert lead_of.read_repo_lead("symrepo", state_dir=state, home=home) is None
    with pytest.raises(OSError, match="symlink"):
        lead_of.write_repo_lead("symrepo", A, state_dir=state, home=home)

    # Invalid repo names and UUIDs are rejected.
    for bad in ("", "..", "../x", "a/b", "has space", "-bad"):
        with pytest.raises(ValueError):
            lead_of.validate_repo(bad)
    with pytest.raises(ValueError):
        lead_of.write_repo_lead("goodrepo", "not-a-uuid", state_dir=state, home=home)


def test_resolve_verified_record_and_succession_chain(tmp_path):
    state = tmp_path / "state"
    home = tmp_path / "paseo-home"
    home.mkdir()
    lead_of.write_repo_lead("myrepo", A, source="manual", state_dir=state, home=home)

    # Direct live recorded lead -> verified: True, source: record.
    agents = {
        A: {"Id": A, "Archived": False, "Name": "LEAD myrepo", "WorkspaceId": WKS_LEAD},
    }
    ws = [{"workspaceId": WKS_LEAD, "name": "LEAD myrepo (wave 1)"}]
    res = lead_of.resolve_repo_lead(
        "myrepo",
        inspect=_inspect_map(agents),
        list_agents=lambda: [],
        list_workspaces=lambda: ws,
        state_dir=state,
        home=home,
    )
    assert res["verified"] is True
    assert res["lead"] == A
    assert res["source"] == "record"
    assert res["window"] == "LEAD myrepo (wave 1)"

    # Completed succession A -> B -> C resolves to live C with verified: True.
    write_link(state, home, A, B)
    write_link(state, home, B, C)
    agents = {
        A: {"Id": A, "Archived": True},
        B: {"Id": B, "Archived": True},
        C: {"Id": C, "Archived": False, "Name": "LEAD myrepo", "WorkspaceId": WKS_LEAD},
    }
    res2 = lead_of.resolve_repo_lead(
        "myrepo",
        inspect=_inspect_map(agents),
        list_agents=lambda: [],
        list_workspaces=lambda: ws,
        state_dir=state,
        home=home,
    )
    assert res2["verified"] is True
    assert res2["lead"] == C
    assert res2["source"] == "record+succession"

    # Paseo outage returns unverified record-unconfirmed rather than fabricating verified.
    def boom(_):
        raise OSError("daemon offline")

    res3 = lead_of.resolve_repo_lead(
        "myrepo", inspect=boom, list_agents=lambda: [], state_dir=state, home=home,
    )
    assert res3["verified"] is False
    assert res3["lead"] == C
    assert res3["source"] == "record-unconfirmed"


def test_discover_live_candidates_ranking_and_worker_exclusions(tmp_path):
    ws_state = tmp_path / "ws-state"
    ws_state.mkdir()
    ws_names.write_window_registry(
        ws_state / f"{B}.windows.json",
        {WKS_LEAD},
        {WKS_LEAD: {"windowId": WKS_LEAD, "box": "LEAD", "repo": "alpha", "lead": B}},
    )
    repo_dir = tmp_path / "alpha"
    repo_dir.mkdir()

    # Workers, archived agents, retired titles, and children must all be excluded.
    noise = [
        {"id": D, "archived": True, "cwd": str(repo_dir), "labels": {"ade.repo": "alpha", "ade.box": "LEAD"}},
        {"id": E, "archived": False, "cwd": str(repo_dir), "labels": {"ade.lead": A, "ade.repo": "alpha"}},
        {"id": C, "archived": False, "cwd": str(repo_dir), "parentAgentId": A, "title": "LEAD alpha"},
        {"id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "archived": False, "cwd": str(repo_dir), "title": "RETIRED LEAD alpha"},
    ]

    # Tier 1 (`ade.repo` + `ade.box=LEAD`) beats Tier 2 (`registry:lead-window`).
    rows = [
        *noise,
        {"id": B, "archived": False, "workspaceId": WKS_LEAD, "cwd": str(repo_dir), "title": "Lead B"},
        {"id": A, "archived": False, "workspaceId": WKS_OTHER, "cwd": str(repo_dir),
         "labels": {"ade.repo": "alpha", "ade.box": "LEAD"}, "title": "Lead A"},
    ]
    cands = lead_of.discover_live_candidates(
        "alpha",
        list_agents=lambda: rows,
        list_workspaces=lambda: [{"workspaceId": WKS_LEAD, "name": "Renamed by human"}],
        ws_state_dir=ws_state,
    )
    assert [c["id"] for c in cands] == [A]
    assert cands[0]["reason"] == "label:ade.repo"

    # Without Tier 1, Tier 2 (registered LEAD window, even when renamed by human) wins.
    cands2 = lead_of.discover_live_candidates(
        "alpha",
        list_agents=lambda: [r for r in rows if r["id"] != A],
        list_workspaces=lambda: [{"workspaceId": WKS_LEAD, "name": "Renamed by human"}],
        ws_state_dir=ws_state,
    )
    assert [c["id"] for c in cands2] == [B]
    assert cands2[0]["reason"] == "registry:lead-window"

    # Legacy `MAIN alpha` window fallback works without raising AttributeError (Tier 4).
    cands3 = lead_of.discover_live_candidates(
        "alpha",
        list_agents=lambda: [{"id": B, "archived": False, "workspaceId": WKS_OTHER, "cwd": str(repo_dir), "title": "tab"}],
        list_workspaces=lambda: [{"workspaceId": WKS_OTHER, "name": "MAIN alpha"}],
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert [c["id"] for c in cands3] == [B]
    assert cands3[0]["reason"] == "window:MAIN"

    # Two candidates in the same tier -> ambiguous in resolve_repo_lead.
    state, home = tmp_path / "st", tmp_path / "ph"
    home.mkdir()
    res = lead_of.resolve_repo_lead(
        "alpha",
        inspect=_inspect_map({}),
        list_agents=lambda: [
            {"id": A, "archived": False, "workspaceId": WKS_OTHER, "cwd": str(repo_dir), "labels": {"ade.chain": A}},
            {"id": B, "archived": False, "workspaceId": WKS_OTHER, "cwd": str(repo_dir), "labels": {"ade.chain": B}},
        ],
        list_workspaces=lambda: [],
        state_dir=state,
        home=home,
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert res["verified"] is False
    assert res["lead"] is None
    assert res["source"] == "ambiguous"
    assert {c["id"] for c in res["candidates"]} == {A, B}


def test_stale_record_falls_back_to_unverified_candidate(tmp_path):
    state, home = tmp_path / "state", tmp_path / "home"
    home.mkdir()
    repo_dir = tmp_path / "beta"
    repo_dir.mkdir()
    lead_of.write_repo_lead("beta", A, source="finish", state_dir=state, home=home)

    agents = {A: {"Id": A, "Archived": True}}
    live_rows = [{"id": B, "archived": False, "workspaceId": WKS_LEAD, "cwd": str(repo_dir), "title": "LEAD beta"}]
    ws = [{"workspaceId": WKS_LEAD, "name": "LEAD beta (work)"}]

    res = lead_of.resolve_repo_lead(
        "beta",
        inspect=_inspect_map(agents),
        list_agents=lambda: live_rows,
        list_workspaces=lambda: ws,
        state_dir=state,
        home=home,
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert res["verified"] is False
    assert res["lead"] == B
    assert res["stale_record"] == A
    assert res["source"] == "fallback:window:LEAD+meta"


def test_discover_reads_daemon_workspace_title_and_excludes_watch_window(tmp_path):
    """Live PaseoClient.list_workspaces() returns `title` (not `name`); `WATCH load` must not shadow `LEAD <repo>`."""
    repo_dir = tmp_path / "djbclark-ade"
    repo_dir.mkdir()
    rows = [
        {"id": B, "archived": False, "workspaceId": WKS_OTHER, "cwd": str(repo_dir),
         "labels": {"ade.chain": B}, "title": "Load watcher"},
        {"id": A, "archived": False, "workspaceId": WKS_LEAD, "cwd": str(repo_dir),
         "labels": {"ade.chain": A}, "title": "LEAD djbclark-ade"},
    ]
    ws = [
        {"workspaceId": WKS_OTHER, "title": "WATCH load"},
        {"workspaceId": WKS_LEAD, "title": "LEAD djbclark-ade (Wave 7)"},
    ]
    cands = lead_of.discover_live_candidates(
        "djbclark-ade",
        list_agents=lambda: rows,
        list_workspaces=lambda: ws,
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert [c["id"] for c in cands] == [A]
    assert cands[0]["window"] == "LEAD djbclark-ade (Wave 7)"


def test_candidates_hint_for_refusal_formats_recorded_and_unverified(tmp_path):
    state, home = tmp_path / "state", tmp_path / "home"
    home.mkdir()
    repo_dir = tmp_path / "gamma"
    repo_dir.mkdir()

    target_rec = {"Id": A, "Archived": True, "Cwd": str(repo_dir)}

    # Unverified live candidate when no repo record exists.
    hint = lead_of.candidates_hint_for_refusal(
        target_rec,
        inspect=_inspect_map({A: target_rec}),
        list_agents=lambda: [{"id": B, "archived": False, "workspaceId": WKS_LEAD, "cwd": str(repo_dir), "title": "Lead B"}],
        list_workspaces=lambda: [{"workspaceId": WKS_LEAD, "name": "LEAD gamma (wave)"}],
        state_dir=state,
        home=home,
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert f"{B[:7]} ({B})" in hint
    assert "not redirected" in hint
    assert "LEAD gamma (wave)" in hint

    # Verified recorded live lead includes ade-self-session link suggestion.
    lead_of.write_repo_lead("gamma", B, source="manual", state_dir=state, home=home)
    hint2 = lead_of.candidates_hint_for_refusal(
        target_rec,
        inspect=_inspect_map({A: target_rec, B: {"Id": B, "Archived": False, "Name": "Lead B", "WorkspaceId": WKS_LEAD}}),
        list_agents=lambda: [],
        list_workspaces=lambda: [{"workspaceId": WKS_LEAD, "name": "LEAD gamma (wave)"}],
        state_dir=state,
        home=home,
        ws_state_dir=tmp_path / "empty-ws",
    )
    assert f"{B[:7]} ({B})" in hint2
    assert "not auto-redirected" in hint2
    assert f"ade-self-session link --predecessor {A} --successor {B} --operator-attested" in hint2


def test_cli_end_to_end_get_set_list(tmp_path):
    state, home = tmp_path / "state", tmp_path / "paseo-home"
    home.mkdir()
    repo_dir = tmp_path / "delta"
    repo_dir.mkdir()
    fake_paseo = tmp_path / "fake-paseo"
    fake_paseo.write_text(f"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["agent", "inspect"]:
    if a[2] == {A!r}:
        print(json.dumps({{"Id": {A!r}, "Archived": False, "Cwd": {str(repo_dir)!r}, "Name": "LEAD delta", "WorkspaceId": {WKS_LEAD!r}}}))
        sys.exit(0)
    if a[2] == {B!r}:
        print(json.dumps({{"Id": {B!r}, "Archived": True, "Cwd": {str(repo_dir)!r}}}))
        sys.exit(0)
    sys.stderr.write("Agent not found\\n")
    sys.exit(1)
if a[:2] == ["ls", "-g"]:
    print(json.dumps([{{"id": {C!r}, "archived": False, "workspaceId": {WKS_LEAD!r}, "cwd": {str(repo_dir)!r}, "title": "LEAD delta"}}]))
    sys.exit(0)
if a[:2] == ["workspace", "ls"]:
    print(json.dumps([{{"workspaceId": {WKS_LEAD!r}, "name": "LEAD delta (work)"}}]))
    sys.exit(0)
sys.exit(1)
""")
    fake_paseo.chmod(0o755)
    env = {
        **os.environ,
        "ADE_PASEO_TRANSPORT": "cli",
        "ADE_SELF_SESSION_STATE": str(state),
        "PASEO_HOME": str(home),
        "ADE_WORKER_RUN_STATE": str(tmp_path / "empty-ws"),
    }
    env.pop("ADE_REPO_LEADS_DIR", None)
    cli = str(ROOT / "bin" / "ade-lead-of")

    # Unverified fallback exits 3 by default, 0 with --allow-unverified.
    r1 = subprocess.run([cli, "--paseo", str(fake_paseo), "delta", "--json"],
                        capture_output=True, text=True, env=env, timeout=30)
    assert r1.returncode == lead_of.EXIT_UNVERIFIED, r1.stderr
    d1 = json.loads(r1.stdout)
    assert d1["verified"] is False and d1["lead"] == C

    r1b = subprocess.run([cli, "--paseo", str(fake_paseo), "delta", "--allow-unverified", "--json"],
                         capture_output=True, text=True, env=env, timeout=30)
    assert r1b.returncode == lead_of.EXIT_OK

    # `set` refuses archived agent, accepts live agent.
    r_arch = subprocess.run([cli, "--paseo", str(fake_paseo), "set", "delta", B],
                            capture_output=True, text=True, env=env, timeout=30)
    assert r_arch.returncode == lead_of.EXIT_NOT_FOUND
    assert "archived" in r_arch.stderr

    r_set = subprocess.run([cli, "--paseo", str(fake_paseo), "set", "delta", A, "--json"],
                           capture_output=True, text=True, env=env, timeout=30)
    assert r_set.returncode == lead_of.EXIT_OK, r_set.stderr
    assert json.loads(r_set.stdout)["lead"] == A

    # Shorthand `ade-lead-of delta --json` now exits 0 with verified: true.
    r2 = subprocess.run([cli, "--paseo", str(fake_paseo), "delta", "--json"],
                        capture_output=True, text=True, env=env, timeout=30)
    assert r2.returncode == lead_of.EXIT_OK, r2.stderr
    d2 = json.loads(r2.stdout)
    assert d2["verified"] is True and d2["lead"] == A and d2["source"] == "record"

    # `list` returns delta.
    r_ls = subprocess.run([cli, "--paseo", str(fake_paseo), "list", "--json"],
                          capture_output=True, text=True, env=env, timeout=30)
    assert r_ls.returncode == lead_of.EXIT_OK
    assert [row["repo"] for row in json.loads(r_ls.stdout)] == ["delta"]

    # Invalid repo -> exit 2.
    r_bad = subprocess.run([cli, "--paseo", str(fake_paseo), "get", "../bad"],
                           capture_output=True, text=True, env=env, timeout=30)
    assert r_bad.returncode == lead_of.EXIT_USAGE
