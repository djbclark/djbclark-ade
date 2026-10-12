"""bin/skillopt-night: argument assembly, guards, chain failover over handoff rounds,
per-source cursors, state restore, secrets, install no-op.

Every test runs against a temporary HOME with a fake skillopt-sleep that speaks the
handoff protocol (pending.json + exit 3, then answers/<id>.md), a fake hermes-ping,
and failover.preflight/ask patched or fed fixtures; nothing calls a model or launchctl.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("skillopt_night", str(ROOT / "bin" / "skillopt-night"))
_spec = importlib.util.spec_from_loader("skillopt_night", _loader)
night = importlib.util.module_from_spec(_spec)
_loader.exec_module(night)
failover = night.failover
REAL_ASK = failover.ask

PROJECT = str(ROOT)
SECRET = "sk-sipb-" + "beefcafe" * 4

FAKE_SKILLOPT = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
argv = sys.argv[1:]
mode = argv[0]
src = argv[argv.index("--source") + 1]
proj = argv[argv.index("--project") + 1]
backend = argv[argv.index("--backend") + 1]
hdir = os.environ.get("SKILLOPT_SLEEP_HANDOFF_DIR", "")
st = Path(os.environ["HOME"]) / ".skillopt-sleep" / "state.json"
try:
    state = json.loads(st.read_text())
except (OSError, ValueError):
    state = {}
row = {"argv": argv, "seen": state.get("last_harvest", {}).get(proj), "hdir": hdir}
answer = None
if mode == "run" and backend == "handoff":
    ans = Path(hdir) / "answers" / "p1.md"
    if not ans.exists():
        Path(hdir).mkdir(parents=True, exist_ok=True)
        (Path(hdir) / "pending.json").write_text(json.dumps(
            {"format": "skillopt_sleep.handoff.v1", "pending": [{"id": "p1", "prompt": "Q-" + src}]}))
        row["round"] = "pending"
        with open(os.environ["FAKE_LOG"], "a") as f:
            f.write(json.dumps(row) + "\n")
        sys.exit(3)
    answer = ans.read_text()
    row["answer"] = answer
    state["night"] = state.get("night", 0) + 1
    state.setdefault("last_harvest", {})[proj] = "T-" + src
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(state))
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(row) + "\n")
if answer and "BAD" in answer:
    print("[sleep] backend garbage", file=sys.stderr)
    sys.exit(1)
print("[sleep] progress line on stdout")
print(os.environ.get("FAKE_RESULT") or json.dumps(
    {"n_sessions": 3, "n_tasks": 2, "accepted": False, "gate_action": "reject",
     "staging_dir": "", "staged_skills": []}, indent=2))
'''

FAKE_PING = '''#!/bin/sh
printf '%s\\n' "$1" >> "$FAKE_PING_LOG"
'''

FAKE_SECRETSPEC = '''#!/bin/sh
case "$1" in
  schema) echo '{"properties": {"MIT_SIPB_API_KEY": {}}}' ;;
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
    (home / ".skillopt-sleep").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SKILLOPT_NIGHT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SKILLOPT_NIGHT_BIN", str(_exe(bin_dir / "skillopt-sleep", FAKE_SKILLOPT)))
    monkeypatch.setenv("SKILLOPT_NIGHT_PING", str(_exe(bin_dir / "hermes-ping", FAKE_PING)))
    monkeypatch.setenv("FAILOVER_SECRETSPEC", str(_exe(bin_dir / "sudo-secretspec", FAKE_SECRETSPEC)))
    monkeypatch.setenv("SKILLOPT_NIGHT_LAUNCH_AGENTS", str(tmp_path / "LaunchAgents"))
    monkeypatch.setenv("SKILLOPT_NIGHT_NO_GATE", "1")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_PING_LOG", str(tmp_path / "pings.txt"))
    monkeypatch.setenv("FAKE_SECRET", SECRET)
    monkeypatch.delenv("FAKE_RESULT", raising=False)
    monkeypatch.setattr(night, "handoff_dir", lambda s: tmp_path / "handoff" / s)
    monkeypatch.setattr(failover, "preflight", lambda e: (True, "ok (test)"))
    monkeypatch.setattr(failover, "ask", lambda e, p: f"ANS-{e.model}-{p}")
    failover._cache.clear()
    return tmp_path


def _night(home: Path, chain: list[dict], **kw) -> None:
    spec = {"enabled": True, "chain": chain, **kw}
    (home / ".skillopt-sleep" / "night.json").write_text(json.dumps(spec))


HAIKU_SONNET = [{"tui": "claude", "model": "haiku"}, {"tui": "claude", "model": "sonnet"}]


def _calls(tmp: Path) -> list[dict]:
    p = tmp / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _pings(tmp: Path) -> list[str]:
    p = tmp / "pings.txt"
    return p.read_text().splitlines() if p.exists() else []


def _rows(tmp: Path) -> list[dict]:
    p = tmp / "state" / "nights.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _attempts(tmp: Path) -> list[dict]:
    p = tmp / "state" / "attempts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ── argument assembly ───────────────────────────────────────────────────────

@pytest.mark.parametrize("source", night.SOURCES)
def test_run_command_per_source(env, source):
    cmd = night.build_command(source, dry_run=False, cfg={}, codex_home=env / "shim")
    assert cmd[:3] == ["nice", "-n", "10"]
    assert cmd[4] == "run"
    for flag, val in (("--project", PROJECT), ("--scope", "all"), ("--source", source),
                      ("--skill-root", str(ROOT / "skills")), ("--backend", "handoff")):
        assert cmd[cmd.index(flag) + 1] == val
    assert "--progress" in cmd and "--json" in cmd
    assert "--auto-adopt" not in cmd
    assert ("--codex-home" in cmd) == (source == "codex")
    assert "hermes-ping" in cmd[cmd.index("--preferences") + 1]


def test_max_sessions_passed_on_runs_only(env):
    cmd = night.build_command("claude", dry_run=False, cfg={}, max_sessions=30)
    assert cmd[cmd.index("--max-sessions") + 1] == "30"
    assert "--max-sessions" not in night.build_command("claude", dry_run=True, cfg={}, max_sessions=30)


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


def test_night_failure_reads_diagnostics(tmp_path):
    assert night.night_failure(1, {}) == "skillopt-sleep rc=1"
    assert night.night_failure(0, {"ok": False, "error": "x", "message": "m"}).startswith("skillopt-sleep error")
    stage = tmp_path / "night-1"
    stage.mkdir()
    (stage / "diagnostics.json").write_text(json.dumps({"call_error": "codex exec failed"}))
    assert "call_error" in night.night_failure(0, {"staging_dir": str(stage)})
    (stage / "diagnostics.json").write_text(json.dumps({"notes": ["gpt: empty response on all 3 attempts"]}))
    assert "empty response" in night.night_failure(0, {"staging_dir": str(stage)})
    (stage / "diagnostics.json").write_text(json.dumps({"call_error": ""}))
    (stage / "report.json").write_text(json.dumps({"n_tasks": 5, "n_replayed": 0}))
    assert "none was replayed" in night.night_failure(0, {"staging_dir": str(stage)})
    (stage / "report.json").write_text(json.dumps({"n_tasks": 5, "n_replayed": 5}))
    assert night.night_failure(0, {"staging_dir": str(stage)}) is None


# ── guards ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", [None, {"enabled": False, "chain": HAIKU_SONNET},
                                  {"enabled": True, "chain": []}])
def test_no_enabled_chain_refuses_stateful_night(env, capsys, spec):
    if spec is not None:
        (env / "home" / ".skillopt-sleep" / "night.json").write_text(json.dumps(spec))
    assert night.main([]) == 0
    assert "waiting for backend decision" in capsys.readouterr().out
    assert _calls(env) == []
    assert _rows(env)[-1]["status"] == "waiting-backend"
    assert _pings(env) == []


@pytest.mark.parametrize("bad", [{"tui": "cursor"}, {"tui": "claude", "model": "opus"},
                                 {"tui": "codex"}, {"tui": "claude", "model": "claude-fable-5"}])
def test_policy_violating_chain_refused_whole(env, bad):
    _night(env / "home", [HAIKU_SONNET[0], bad])
    assert night.main([]) == 1
    assert _calls(env) == []
    assert _rows(env)[-1]["status"] == "chain-invalid"
    assert len(_pings(env)) == 1 and "chain refused" in _pings(env)[0]


def test_dry_run_runs_mock_and_never_advances(env):
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
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setenv("SKILLOPT_NIGHT_NO_GATE", "0")
    monkeypatch.setattr(night, "machine_overloaded", lambda: "load 99 > 4x8 cpus")
    assert night.main(["--load-wait", "0"]) == 0
    assert _calls(env) == []
    assert _rows(env)[-1]["status"].startswith("skipped: load 99")


def test_load_gate_falls_back_without_acp_dispatch(monkeypatch):
    monkeypatch.setattr(night, "REPO", Path("/nonexistent"))
    monkeypatch.setattr(night.os, "getloadavg", lambda: (1e6, 0, 0))
    assert night.machine_overloaded().startswith("load ")


# ── the chain over handoff rounds ───────────────────────────────────────────

def test_handoff_round_answered_by_first_entry(env):
    _night(env / "home", HAIKU_SONNET)
    assert night.main(["--source", "claude"]) == 0
    calls = _calls(env)
    assert [c.get("round") for c in calls] == ["pending", None]
    assert calls[1]["answer"] == "ANS-haiku-Q-claude"
    assert calls[0]["hdir"] == str(env / "handoff" / "claude")
    row = _rows(env)[-1]
    assert (row["status"], row["entry"], row["rounds"], row["answered"]) == ("ok", "claude:haiku", 2, 1)
    assert not (env / "handoff" / "claude").exists(), "a finished night's handoff dir is archived"
    assert len(list((env / "state" / "handoff-archive").iterdir())) == 1


def test_answer_failure_fails_over_to_next_entry(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)

    def ask(e, p):
        if e.model == "haiku":
            raise failover.AttemptFailed("simulated quota")
        return f"ANS-{e.model}"
    monkeypatch.setattr(failover, "ask", ask)
    assert night.main(["--source", "claude"]) == 0
    row = _rows(env)[-1]
    assert row["entry"] == "claude:sonnet"
    assert row["failed"] == ["claude:haiku: simulated quota"]
    assert _calls(env)[-1]["answer"] == "ANS-sonnet"


def test_bad_night_restores_state_and_reruns_on_next_entry(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    state = env / "home" / ".skillopt-sleep" / "state.json"
    state.write_text(json.dumps({"night": 7, "last_harvest": {}}))
    monkeypatch.setattr(failover, "ask", lambda e, p: "BAD" if e.model == "haiku" else "GOOD")
    assert night.main(["--source", "claude"]) == 0
    assert json.loads(state.read_text())["night"] == 8, "the failed attempt's night was rolled back"
    answers = [c.get("answer") for c in _calls(env)]
    assert answers == [None, "BAD", None, "GOOD"], "the source night reran from scratch"
    assert _rows(env)[-1]["entry"] == "claude:sonnet"


def test_preflight_skip_logged(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setattr(failover, "preflight",
                        lambda e: (False, "pool claude headroom 9% <= floor 15%") if e.model == "haiku"
                        else (True, "ok"))
    assert night.main(["--source", "claude"]) == 0
    att = _attempts(env)
    assert (att[0]["phase"], att[0]["ok"], att[0]["model"]) == ("preflight", False, "haiku")
    assert _rows(env)[-1]["entry"] == "claude:sonnet"


def test_chain_exhausted(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setattr(failover, "ask", lambda e, p: (_ for _ in ()).throw(failover.AttemptFailed("down")))
    assert night.main(["--source", "claude"]) == 1
    row = _rows(env)[-1]
    assert row["status"] == "chain_exhausted"
    assert row["failed"] == ["claude:haiku: down", "claude:sonnet: down"]
    assert _pings(env) == [("djbclark-ade: skillopt-sleep chain exhausted for claude; "
                           f"see {env / 'state'}/attempts.jsonl")]
    assert not (env / "home" / ".skillopt-sleep" / "state.json").exists()


def test_per_source_cursors(env):
    _night(env / "home", HAIKU_SONNET)
    (env / "state").mkdir()
    (env / "state" / "cursors.json").write_text(json.dumps({"codex": "C0"}))
    (env / "home" / ".skillopt-sleep" / "state.json").write_text(
        json.dumps({"last_harvest": {PROJECT: "SHARED"}}))
    assert night.main([]) == 0
    seen = {c["argv"][c["argv"].index("--source") + 1]: c["seen"] for c in _calls(env) if c.get("round")}
    assert seen == {"claude": None, "codex": "C0"}
    cursors = json.loads((env / "state" / "cursors.json").read_text())
    assert cursors == {"claude": "T-claude", "codex": "T-codex"}


def test_staged_proposals_ping_once(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setenv("FAKE_RESULT", json.dumps(
        {"n_tasks": 5, "staging_dir": str(env / "night-1"),
         "staged_skills": [{"skill_name": "a"}, {"skill_name": "b"}]}))
    (env / "night-1").mkdir()
    assert night.main(["--source", "claude"]) == 0
    assert _pings(env) == [("djbclark-ade: skillopt-sleep staged 2 proposal(s) from claude; "
                            "review: skillopt-sleep status --project ~/src/djbclark-ade")]
    row = _rows(env)[-1]
    assert (row["source"], row["proposals"]) == ("claude", 2)


def test_sipb_secret_never_on_disk(env, monkeypatch):
    monkeypatch.setattr(failover, "ask", REAL_ASK)
    seen = {}

    def urlopen(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "sipb says hi"}}]}).encode())
    monkeypatch.setattr(failover.urllib.request, "urlopen", urlopen)
    _night(env / "home", [{"tui": "sipb", "model": "qwen3-coder:30b"}])
    assert night.main(["--source", "claude"]) == 0
    assert seen["auth"] == f"Bearer {SECRET}"
    assert _calls(env)[-1]["answer"] == "sipb says hi"
    assert SECRET not in json.dumps({k: v for k, v in os.environ.items() if k != "FAKE_SECRET"})
    for path in env.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert SECRET not in path.read_text(errors="ignore"), path



def test_chain_check_prints_table(env, capsys, monkeypatch):
    _night(env / "home", HAIKU_SONNET, enabled=False)
    monkeypatch.setattr(failover, "preflight", lambda e: (e.model == "sonnet", "why-" + e.model))
    assert night.main(["--chain-check"]) == 0
    out = capsys.readouterr().out
    assert "enabled=False" in out and "claude:haiku" in out and "why-sonnet" in out
    assert _calls(env) == []


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
