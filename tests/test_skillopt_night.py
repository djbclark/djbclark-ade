"""bin/skillopt-night: argument assembly, guards, cursors, secrets, install no-op.

Every test runs against a temporary HOME with fake skillopt-sleep, hermes-ping
and sudo-secretspec executables; nothing here calls a model or launchctl.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("skillopt_night", str(ROOT / "bin" / "skillopt-night"))
_spec = importlib.util.spec_from_loader("skillopt_night", _loader)
night = importlib.util.module_from_spec(_spec)
_loader.exec_module(night)

SECRET = "sk-test-" + "f00dfeed" * 4
PROJECT = str(ROOT)

FAKE_SKILLOPT = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
from pathlib import Path
argv = sys.argv[1:]
src = argv[argv.index("--source") + 1]
proj = argv[argv.index("--project") + 1]
st = Path(os.environ["HOME"]) / ".skillopt-sleep" / "state.json"
try:
    state = json.loads(st.read_text())
except (OSError, ValueError):
    state = {}
seen = state.get("last_harvest", {}).get(proj)
key = os.environ.get("AZURE_OPENAI_API_KEY", "")
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "seen": seen,
                        "key_sha": hashlib.sha256(key.encode()).hexdigest() if key else "",
                        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", "")}) + "\n")
if argv[0] == "run":
    state.setdefault("last_harvest", {})[proj] = "T-" + src
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(state))
print("[sleep] harvest done: sessions=3", file=sys.stderr)
print("[sleep] progress line on stdout")
print(os.environ.get("FAKE_RESULT") or json.dumps(
    {"n_sessions": 3, "n_tasks": 2, "accepted": False, "gate_action": "reject",
     "staging_dir": "", "staged_skills": []}, indent=2))
sys.exit(int(os.environ.get("FAKE_RC", "0")))
'''

FAKE_PING = '''#!/bin/sh
printf '%s\\n' "$1" >> "$FAKE_PING_LOG"
'''

FAKE_SECRETSPEC = '''#!/bin/sh
case "$1" in
  schema) printf '{"properties": {%s}}\\n' "$FAKE_DECLARED" ;;
  get) printf '%s\\n' "$FAKE_SECRET" ;;
  *) exit 2 ;;
esac
'''


def _exe(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "-Users-x").mkdir(parents=True)
    (home / ".claude" / "projects" / "-Users-x" / "s.jsonl").write_text("{}\n")
    (home / ".codex" / "sessions" / "2026" / "10").mkdir(parents=True)
    (home / ".codex" / "sessions" / "2026" / "10" / "rollout-a.jsonl").write_text("{}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SKILLOPT_NIGHT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SKILLOPT_NIGHT_BIN", str(_exe(bin_dir / "skillopt-sleep", FAKE_SKILLOPT)))
    monkeypatch.setenv("SKILLOPT_NIGHT_PING", str(_exe(bin_dir / "hermes-ping", FAKE_PING)))
    monkeypatch.setenv("SKILLOPT_NIGHT_SECRETSPEC", str(_exe(bin_dir / "sudo-secretspec", FAKE_SECRETSPEC)))
    monkeypatch.setenv("SKILLOPT_NIGHT_LAUNCH_AGENTS", str(tmp_path / "LaunchAgents"))
    monkeypatch.setenv("SKILLOPT_NIGHT_NO_GATE", "1")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_PING_LOG", str(tmp_path / "pings.txt"))
    for var in ("FAKE_RESULT", "FAKE_RC", "FAKE_SECRET", "FAKE_DECLARED"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _config(home: Path, **kw) -> None:
    cfg = {"projects": "all", "backend": "mock", **kw}
    (home / ".skillopt-sleep").mkdir(exist_ok=True)
    (home / ".skillopt-sleep" / "config.json").write_text(json.dumps(cfg))


def _calls(tmp: Path) -> list[dict]:
    p = tmp / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _pings(tmp: Path) -> list[str]:
    p = tmp / "pings.txt"
    return p.read_text().splitlines() if p.exists() else []


def _rows(tmp: Path) -> list[dict]:
    p = tmp / "state" / "nights.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ── argument assembly ───────────────────────────────────────────────────────

@pytest.mark.parametrize("source", night.SOURCES)
def test_run_command_per_source(env, source):
    shim = env / "shim"
    cmd = night.build_command(source, dry_run=False, cfg={}, codex_home=shim)
    assert cmd[:3] == ["nice", "-n", "10"]
    assert cmd[4] == "run"
    for flag, val in (("--project", PROJECT), ("--scope", "all"), ("--source", source),
                      ("--skill-root", str(ROOT / "skills"))):
        assert cmd[cmd.index(flag) + 1] == val
    assert "--progress" in cmd and "--json" in cmd
    assert "--backend" not in cmd, "a stateful night takes the backend from config.json"
    assert "--auto-adopt" not in cmd
    assert ("--codex-home" in cmd) == (source == "codex")
    prefs = cmd[cmd.index("--preferences") + 1]
    assert "hermes-ping" in prefs


def test_dry_run_command_forces_mock(env):
    cmd = night.build_command("claude", dry_run=True, cfg={})
    assert cmd[4] == "dry-run"
    assert cmd[cmd.index("--backend") + 1] == "mock"


def test_sources_skip_absent_roots(env):
    assert night.available_sources({}) == ["claude", "codex"]
    assert night.available_sources({}, ["codex"]) == ["codex"]


def test_codex_shim_links_nested_rollouts(env):
    shim = night.codex_shim({})
    links = list((shim / "archived_sessions").iterdir())
    assert [p.name for p in links] == ["rollout-a.jsonl"]
    assert links[0].is_symlink()


def test_parse_result_after_progress_lines():
    out = '[sleep] x\n{\n  "n_tasks": 4,\n  "staged_skills": [{"skill_name": "a"}]\n}\n'
    res = night.parse_result(out)
    assert res["n_tasks"] == 4
    assert night.n_proposals(res) == 1
    assert night.parse_result("not json") == {}


# ── guards ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("backend", ["mock", ""])
def test_mock_backend_refuses_stateful_night(env, capsys, backend):
    _config(env / "home", backend=backend)
    assert night.main([]) == 0
    assert "waiting for backend decision" in capsys.readouterr().out
    assert _calls(env) == []
    assert _rows(env)[-1]["status"] == "waiting-backend"
    assert _pings(env) == []


def test_dry_run_runs_mock_and_never_advances(env):
    _config(env / "home")
    state = env / "home" / ".skillopt-sleep" / "state.json"
    state.write_text(json.dumps({"last_harvest": {PROJECT: "OLD"}}))
    assert night.main(["--dry-run"]) == 0
    calls = _calls(env)
    assert [c["argv"][0] for c in calls] == ["dry-run", "dry-run"]
    assert all(c["argv"][c["argv"].index("--backend") + 1] == "mock" for c in calls)
    assert not (env / "state" / "cursors.json").exists()
    assert [r["mode"] for r in _rows(env)] == ["dry-run", "dry-run"]
    assert _pings(env) == []


def test_load_gate_skips_night(env, monkeypatch):
    _config(env / "home", backend="opencode")
    monkeypatch.setenv("SKILLOPT_NIGHT_NO_GATE", "0")
    monkeypatch.setattr(night, "machine_overloaded", lambda: "load 99 > 4x8 cpus")
    assert night.main(["--load-wait", "0"]) == 0
    assert _calls(env) == []
    assert _rows(env)[-1]["status"].startswith("skipped: load 99")


def test_load_gate_falls_back_without_acp_dispatch(monkeypatch):
    monkeypatch.setattr(night, "REPO", Path("/nonexistent"))
    monkeypatch.setattr(night.os, "getloadavg", lambda: (1e6, 0, 0))
    assert night.machine_overloaded().startswith("load ")


# ── a real (fake-backend) night ─────────────────────────────────────────────

def test_per_source_cursors(env):
    _config(env / "home", backend="opencode")
    (env / "state").mkdir()
    (env / "state" / "cursors.json").write_text(json.dumps({"codex": "C0"}))
    (env / "home" / ".skillopt-sleep" / "state.json").write_text(
        json.dumps({"last_harvest": {PROJECT: "SHARED"}}))
    assert night.main([]) == 0
    seen = {c["argv"][c["argv"].index("--source") + 1]: c["seen"] for c in _calls(env)}
    assert seen == {"claude": None, "codex": "C0"}
    cursors = json.loads((env / "state" / "cursors.json").read_text())
    assert cursors == {"claude": "T-claude", "codex": "T-codex"}


def test_staged_proposals_ping_once(env, monkeypatch):
    _config(env / "home", backend="opencode")
    monkeypatch.setenv("FAKE_RESULT", json.dumps(
        {"n_tasks": 5, "staging_dir": "/x/night-1",
         "staged_skills": [{"skill_name": "a"}, {"skill_name": "b"}]}))
    assert night.main(["--source", "claude"]) == 0
    pings = _pings(env)
    assert pings == [("djbclark-ade: skillopt-sleep staged 2 proposal(s) from claude; "
                      "review: skillopt-sleep status --project ~/src/djbclark-ade")]
    row = _rows(env)[-1]
    assert (row["source"], row["proposals"], row["staging_dir"]) == ("claude", 2, "/x/night-1")


def test_failed_run_pings_and_exits_nonzero(env, monkeypatch):
    _config(env / "home", backend="opencode")
    monkeypatch.setenv("FAKE_RC", "1")
    assert night.main(["--source", "claude"]) == 1
    assert len(_pings(env)) == 1 and "failed for claude" in _pings(env)[0]


def test_handoff_runs_one_source_and_reports_pending(env, monkeypatch):
    _config(env / "home", backend="handoff")
    monkeypatch.setenv("FAKE_RC", "3")
    assert night.main([]) == 0
    assert len(_calls(env)) == 1
    assert _pings(env) == [("djbclark-ade: skillopt-sleep handoff prompts pending for claude; "
                            "answer them with /skillopt-sleep")]


# ── secrets ──────────────────────────────────────────────────────────────────

def test_litellm_secret_only_in_child_env(env, monkeypatch):
    _config(env / "home", backend="azure_openai", model="go-glm-flash")
    monkeypatch.setenv("FAKE_DECLARED", '"SKILLOPT_LITELLM_API_KEY": {}')
    monkeypatch.setenv("FAKE_SECRET", SECRET)
    assert night.main(["--source", "claude"]) == 0
    call = _calls(env)[0]
    assert call["key_sha"] == hashlib.sha256(SECRET.encode()).hexdigest()
    assert call["endpoint"] == night.LITELLM_ENDPOINT
    assert SECRET not in " ".join(call["argv"])
    assert "AZURE_OPENAI_API_KEY" not in os.environ
    for path in env.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert SECRET not in path.read_text(errors="ignore"), path


def test_litellm_without_secret_is_unavailable(env, monkeypatch):
    _config(env / "home", backend="opencode", optimizer_backend="azure_openai")
    monkeypatch.setenv("FAKE_DECLARED", '"OTHER": {}')
    assert night.main([]) == 0
    assert _calls(env) == []
    assert _rows(env)[-1]["status"] == "backend-unavailable"
    assert len(_pings(env)) == 1


# ── install ──────────────────────────────────────────────────────────────────

def test_install_is_noop_under_test_env(env, monkeypatch, capsys):
    monkeypatch.setenv("SKILLOPT_NIGHT_NO_INSTALL", "1")
    assert night.main(["install"]) == 0
    assert night.main(["uninstall"]) == 0
    assert not (env / "LaunchAgents").exists()
    assert "would copy" in capsys.readouterr().out


def test_plist_shape():
    import plistlib
    with open(night.PLIST_SRC, "rb") as f:
        plist = plistlib.load(f)
    assert plist["Label"] == night.LABEL
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 30}
    assert plist["ProgramArguments"] == [str(ROOT / "bin" / "skillopt-night")]
    assert plist["EnvironmentVariables"]["PATH"].split(":")[0].endswith("/.local/bin")
    assert plist["RunAtLoad"] is False
