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
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("skillopt_night", str(ROOT / "bin" / "skillopt-night"))
_spec = importlib.util.spec_from_loader("skillopt_night", _loader)
assert _spec is not None
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
row = {"argv": argv, "seen": state.get("last_harvest", {}).get(proj), "hdir": hdir,
       "pinned": json.loads((Path(hdir) / "digests.json").read_text())
       if hdir and (Path(hdir) / "digests.json").exists() else None}
answer = None
if backend == "handoff":
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
if mode == "run" and backend != "mock":
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
    monkeypatch.setattr(failover, "preflight", lambda e, probe=True: (True, "ok (test)"))
    monkeypatch.setattr(failover, "ask", lambda e, p: f"ANS-{e.model}-{p}")
    monkeypatch.setattr(night.skillopt_sources, "store_present", lambda s: False)
    failover._cache.clear()
    return tmp_path


def _night(home: Path, chain: list[dict[str, Any]], **kw) -> None:
    spec = {"enabled": True, "chain": chain, **kw}
    (home / ".skillopt-sleep" / "night.json").write_text(json.dumps(spec))


HAIKU_SONNET = [{"tui": "claude", "model": "haiku", "effort": "low"},
                {"tui": "claude", "model": "sonnet", "effort": "low"}]


def _calls(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _pings(tmp: Path) -> list[str]:
    p = tmp / "pings.txt"
    return p.read_text().splitlines() if p.exists() else []


def _rows(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "state" / "nights.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _attempts(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "state" / "attempts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ── argument assembly ───────────────────────────────────────────────────────

@pytest.mark.parametrize("source", night.NATIVE_SOURCES)
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


@pytest.mark.parametrize("source", night.ADAPTER_SOURCES)
def test_adapter_source_harvests_nothing_natively(env, source):
    cmd = night.build_command(source, dry_run=False, cfg={})
    assert cmd[cmd.index("--source") + 1] == "opencode"
    assert cmd[cmd.index("--opencode-db") + 1] == ":memory:"


def test_native_command(env):
    cmd = night.build_command("claude", dry_run=False, cfg={}, backend="claude", model="claude-haiku-5-5")
    assert cmd[cmd.index("--backend") + 1] == "claude" and cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"


def test_pi_is_not_a_source():
    assert "pi" not in night.SOURCES


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
                                 {"tui": "codex"}, {"tui": "claude", "model": "claude-fable-5"},
                                 {"tui": "copilot"}, {"tui": "grok"}, {"tui": "hermes"},
                                 {"tui": "opencode", "model": "opencode-go/grok-4.7"},
                                 {"tui": "agy", "model": "claude-opus-5-5", "effort": "low"},
                                 {"tui": "opencode", "model": "opencode-go/x", "label": "muse"},
                                 {"tui": "opencode", "model": "opencode-go/x", "label": "pi"},
                                 {"tui": "sipb", "model": "qwen3-coder:30b"}])
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
    assert (row["status"], row["entry"], row["rounds"], row["answered"]) == ("ok", "claude:haiku@low", 2, 1)
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
    assert row["entry"] == "claude:sonnet@low"
    assert row["failed"] == ["claude:haiku@low: simulated quota"]
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
    assert _rows(env)[-1]["entry"] == "claude:sonnet@low"


def test_preflight_skip_logged(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setattr(failover, "preflight",
                        lambda e, probe=True: (False, "pool claude headroom 9% <= floor 15%")
                        if e.model == "haiku" else (True, "ok"))
    assert night.main(["--source", "claude"]) == 0
    att = _attempts(env)
    assert (att[0]["phase"], att[0]["ok"], att[0]["model"]) == ("preflight", False, "haiku")
    assert _rows(env)[-1]["entry"] == "claude:sonnet@low"


def test_chain_exhausted(env, monkeypatch):
    _night(env / "home", HAIKU_SONNET)
    monkeypatch.setattr(failover, "ask", lambda e, p: (_ for _ in ()).throw(failover.AttemptFailed("down")))
    assert night.main(["--source", "claude"]) == 1
    row = _rows(env)[-1]
    assert row["status"] == "chain_exhausted"
    assert row["failed"] == ["claude:haiku@low: down", "claude:sonnet@low: down"]
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
    _night(env / "home", [{"tui": "sipb", "model": "qwen3-coder:30b"}], allow=["sipb"])
    assert night.main(["--source", "claude"]) == 0
    assert seen["auth"] == f"Bearer {SECRET}"
    assert _calls(env)[-1]["answer"] == "sipb says hi"
    assert SECRET not in json.dumps({k: v for k, v in os.environ.items() if k != "FAKE_SECRET"})
    for path in env.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert SECRET not in path.read_text(errors="ignore"), path



DIGEST = {"session_id": "z1", "project": "/Users/x/src/p", "user_prompts": ["fix it"],
          "assistant_finals": ["done"], "started_at": "2026-10-12T10:00:00Z",
          "ended_at": "2026-10-12T10:05:00Z"}


def _fake_adapter(calls: list[str]):
    def fake(source, cfg, out, limit):
        calls.append(f"{source}:{limit}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([DIGEST]))
        return 1
    return fake


def test_adapter_source_night_pins_digests(env, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(night, "adapter_digests", _fake_adapter(calls))
    monkeypatch.setattr(night.skillopt_sources, "store_present", lambda s: s == "zcode")
    _night(env / "home", HAIKU_SONNET, max_sessions=30)
    assert night.available_sources({}) == ["claude", "codex", "zcode"]
    assert night.main(["--source", "zcode"]) == 0
    assert calls == ["zcode:30"]
    first = _calls(env)[0]
    assert first["pinned"] == [DIGEST], "round 1 already sees the adapter's digests"
    assert first["argv"][first["argv"].index("--source") + 1] == "opencode"
    row = _rows(env)[-1]
    assert (row["source"], row["status"], row["entry"]) == ("zcode", "ok", "claude:haiku@low")
    assert not (env / "state" / "digests-zcode.json").exists()
    cursors = json.loads((env / "state" / "cursors.json").read_text())
    assert cursors == {"zcode": "T-opencode"}


def test_adapter_failure_recorded(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store unreadable")
    monkeypatch.setattr(night, "adapter_digests", boom)
    monkeypatch.setattr(night.skillopt_sources, "store_present", lambda s: s == "agy")
    _night(env / "home", HAIKU_SONNET)
    assert night.main(["--source", "agy"]) == 0
    assert _rows(env)[-1]["status"] == "adapter-failed"
    assert _calls(env) == []


def test_adapter_dry_run_counts_prompts_without_state(env, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(night, "adapter_digests", _fake_adapter(calls))
    monkeypatch.setattr(night.skillopt_sources, "store_present", lambda s: s == "crush")
    assert night.main(["--dry-run", "--source", "crush"]) == 0
    row = _rows(env)[-1]
    assert (row["source"], row["rc"], row["ok"], row["sessions"], row["pending_prompts"]) == (
        "crush", 3, True, 1, 1)
    c = _calls(env)[0]
    assert c["argv"][0] == "dry-run" and c["argv"][c["argv"].index("--backend") + 1] == "handoff"
    assert not (env / "home" / ".skillopt-sleep" / "state.json").exists()


def test_native_flag_uses_skillopt_backend(env):
    _night(env / "home", [{"tui": "opencode", "model": "opencode-go/minimax-m3"}])
    assert night.main(["--source", "claude", "--native"]) == 0
    calls = _calls(env)
    assert len(calls) == 1 and calls[0].get("round") is None
    argv = calls[0]["argv"]
    assert argv[argv.index("--backend") + 1] == "opencode"
    assert argv[argv.index("--model") + 1] == "opencode-go/minimax-m3"
    assert _rows(env)[-1]["entry"] == "opencode:opencode-go/minimax-m3"


def test_native_flag_ignored_for_acp_only_entries(env):
    _night(env / "home", [{"tui": "agy", "model": "gemini-3.8-flash", "effort": "medium"}])
    assert night.main(["--source", "claude", "--native"]) == 0
    assert [c.get("round") for c in _calls(env)] == ["pending", None]


def test_chain_check_prints_table(env, capsys, monkeypatch):
    _night(env / "home", HAIKU_SONNET, enabled=False)
    monkeypatch.setattr(failover, "preflight", lambda e, probe=True: (e.model == "sonnet", "why-" + e.model))
    assert night.main(["--chain-check"]) == 0
    out = capsys.readouterr().out
    assert "enabled=False" in out and "claude:haiku@low" in out and "why-sonnet" in out
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
