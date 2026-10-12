"""bin/failover.py: chain policy, preflight, ordered attempts, attempt log, secret handling.

No test calls a model, aiuse, acp-run or sudo-secretspec for real: fixtures and
fake executables stand in for all of them.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))  # bin/ is not a package; skillopt-night imports it the same way
import failover  # pyright: ignore[reportMissingImports]

SECRET = "sk-sipb-" + "c0ffee11" * 4
# A fake acp-run whose result record says failure=provider (claude writing fake tool calls).
LOG_PROVIDER = ('LOG=""; prev=""; for x in "$@"; do [ "$prev" = "--log" ] && LOG="$x"; prev="$x"; done\n'
                '[ -n "$LOG" ] && echo \'{"kind": "result", "data": {"tool_calls": 0, "failure": "provider"}}\' > "$LOG"\n')
# A fake acp-run line that finds its --log argument and writes a result record there.
LOG_RESULT = ('LOG=""; prev=""; for x in "$@"; do [ "$prev" = "--log" ] && LOG="$x"; prev="$x"; done\n'
              '[ -n "$LOG" ] && echo \'{{"kind": "result", "data": {{"tool_calls": {tools}}}}}\' > "$LOG"\n')
REAL_ACP_AGENTS_OK = failover.acp_agents_ok

AIUSE = {"schema_version": "1.2", "available": [
    {"provider": "opencode-go", "pool_family": None, "usable_now": True, "headroom_percent": 8.0},
    {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 20.0},
    {"provider": "claude", "pool_family": "fable", "usable_now": True, "headroom_percent": 2.5},
    {"provider": "antigravity", "pool_family": "gemini", "usable_now": True, "headroom_percent": 16.0},
    {"provider": "antigravity", "pool_family": "claude_gpt", "usable_now": False, "headroom_percent": 0},
]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    failover._cache.clear()
    fixture = tmp_path / "aiuse.json"
    fixture.write_text("preamble line\n" + json.dumps(AIUSE))
    monkeypatch.setenv("FAILOVER_AIUSE_JSON", str(fixture))
    monkeypatch.setattr(failover, "ATTEMPT_LOG", tmp_path / "attempts.jsonl")
    monkeypatch.setattr(failover, "acp_agents_ok", lambda: {"claude", "agy", "opencode", "zcode"})
    acp = tmp_path / "acp-run"
    acp.write_text("#!/bin/sh\n" + LOG_RESULT.format(tools=0) + "exit 0\n")
    acp.chmod(0o755)
    monkeypatch.setenv("FAILOVER_ACP_RUN", str(acp))
    spec = tmp_path / "sudo-secretspec"
    spec.write_text('#!/bin/sh\ncase "$1" in schema) echo \'{"properties": {"MIT_SIPB_API_KEY": {}}}\';;'
                    ' get) printf "%s\\n" "$FAKE_SECRET";; esac\n')
    spec.chmod(0o755)
    monkeypatch.setenv("FAILOVER_SECRETSPEC", str(spec))
    monkeypatch.setenv("FAKE_SECRET", SECRET)
    monkeypatch.setattr(failover, "ACP_LOG_DIR", tmp_path / "acp-logs")
    failover._secrets.clear()
    old_umask = os.umask(0o022)
    os.umask(old_umask)
    yield
    os.umask(old_umask)  # failover.main() sets 0o077
    failover._cache.clear()
    failover._secrets.clear()


def _log(tmp: Path) -> list[dict[str, Any]]:
    p = tmp / "attempts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ── policy at load time ─────────────────────────────────────────────────────

def test_load_keeps_order_and_resolves_pools():
    chain = failover.load_chain([
        {"tui": "opencode", "model": "opencode-go/kimi-k3"},
        {"tui": "agy", "model": "gemini-3.8-flash", "effort": "medium", "floor_percent": 12},
        {"tui": "zcode", "effort": "low"},
        {"tui": "claude", "model": "haiku"},
        {"tui": "sipb", "model": "qwen3-coder:30b"},
    ])
    assert [e.tui.name for e in chain] == ["opencode", "agy", "zcode", "claude", "sipb"]
    assert [(e.pool, e.pool_family) for e in chain] == [
        ("opencode-go", None), ("antigravity", "gemini"), ("zai", None),
        ("claude", "default"), (None, None)]
    assert chain[1].model_arg == "gemini-3.8-flash-medium"
    assert chain[1].floor_percent == 12
    assert chain[4].secret == "MIT_SIPB_API_KEY"


@pytest.mark.parametrize("raw", [
    {"tui": "cursor"},
    {"tui": "cline"},
    {"tui": "hermes"},
    {"tui": "claude", "model": "opus"},
    {"tui": "claude", "model": "claude-fable-5"},
    {"tui": "agy", "model": "claude-opus-5-5", "effort": "low"},
    {"tui": "opencode", "model": "opencode-go/x", "label": "ClinePass relay"},
])
def test_denied_routes_refused(raw):
    with pytest.raises(failover.ChainError, match="denied"):
        failover.load_chain([{"tui": "opencode"}, raw])


@pytest.mark.parametrize(("raw", "msg"), [
    ({"tui": "codex"}, "allowlist"),
    ({"tui": "nosuch"}, "allowlist"),
    ({"tui": "claude", "model": "claude-3-5-gpt"}, "not allowed"),
    ({"tui": "zcode", "model": "glm-5.3"}, "takes no model"),
    ({"tui": "opencode", "model": "opencode-go/kimi-k3", "effort": "low"}, "no effort"),
    ({"tui": "claude", "model": "haiku", "effort": "max"}, "no effort"),
    ({"model": "x"}, "needs a 'tui'"),
])
def test_bad_entries_refused(raw, msg):
    with pytest.raises(failover.ChainError, match=msg):
        failover.load_chain({"allow": ["zcode", "agy", "opencode", "claude", "sipb"], "chain": [raw]})


def test_deny_matches_whole_tokens_only():
    deny = (*failover.DENY, "pi", "grok")
    (ok,) = failover.load_chain([{"tui": "opencode", "model": "opencode-go/api-pilot"}], deny=deny)
    assert ok.model == "opencode-go/api-pilot"
    for raw in ({"tui": "opencode", "model": "opencode-go/grok-4.7"}, {"tui": "opencode", "label": "pi relay"}):
        with pytest.raises(failover.ChainError, match="denied"):
            failover.load_chain([raw], deny=deny)


def test_native_model_and_claude_effort(tmp_path):
    cl, oc = failover.load_chain([{"tui": "claude", "model": "haiku", "effort": "low"},
                                  {"tui": "opencode", "model": "opencode-go/minimax-m3"}])
    assert cl.native_model == "claude-haiku-5-5" and oc.native_model == "opencode-go/minimax-m3"
    cmd = failover.acp_command(cl, tmp_path / "p.md", tmp_path)
    assert cmd[cmd.index("--model") + 1] == "haiku" and cmd[cmd.index("--set") + 1] == "effort=low"


def test_sipb_via_opencode_health_check(monkeypatch):
    (e,) = failover.load_chain([{"tui": "opencode", "model": "sipb/qwen3-coder:30b"}])
    assert (e.pool, e.health_url) == (None, "http://127.0.0.1:8890/api/version")
    monkeypatch.setattr(failover, "health_ok", lambda url: False)
    assert failover.preflight(e) == (False, "health check http://127.0.0.1:8890/api/version did not answer 200")
    monkeypatch.setattr(failover, "health_ok", lambda url: True)
    assert failover.preflight(e, probe=False) == (
        True, "http://127.0.0.1:8890/api/version answered 200; canary not run (it calls the model)")
    ok, why = failover.preflight(e)
    assert ok and why.endswith("canary held (rc=0, 0 tool calls, no file)")


def test_crush_probe(monkeypatch):
    monkeypatch.setattr(failover, "acp_agents_ok", lambda: {"crush"})
    (e,) = failover.load_chain([{"tui": "crush"}])
    assert e.probe and e.pool is None
    calls = []

    def ask(entry, prompt):
        calls.append(prompt)
        return "OK"
    monkeypatch.setattr(failover, "ask", ask)
    ok, why = failover.preflight(e, probe=False)
    assert ok and "probe and canary not run" in why and calls == []
    assert failover.preflight(e)[0] and calls == [failover.PROBE_PROMPT]
    assert failover.preflight(e)[0] and len(calls) == 1, "probe result is cached per process"
    failover._cache.clear()
    monkeypatch.setattr(failover, "ask", lambda entry, prompt: "I cannot")
    assert not failover.preflight(e)[0]
    with pytest.raises(failover.ChainError, match="takes no model"):
        failover.load_chain([{"tui": "crush", "model": "sipb/x"}])


def test_unknown_tui_without_allowlist():
    with pytest.raises(failover.ChainError, match="unknown tui"):
        failover.load_chain([{"tui": "nosuch"}])


# ── preflight ────────────────────────────────────────────────────────────────

def test_preflight_floor_and_pool_family():
    oc, claude, agy_claude = failover.load_chain([
        {"tui": "opencode", "model": "opencode-go/kimi-k3", "floor_percent": 10},
        {"tui": "claude", "model": "sonnet", "floor_percent": 15},
        {"tui": "agy", "model": "claude-sonnet-5-5", "effort": "medium"},
    ])
    ok, why = failover.preflight(oc)
    assert not ok and "8.0% <= floor 10.0%" in why
    ok, why = failover.preflight(claude)
    assert ok and "20.0%" in why, "the Fable sub-pool (2.5%) must not gate Sonnet"
    ok, why = failover.preflight(agy_claude)
    assert not ok and "not usable" in why


def test_preflight_missing_agent_and_secret(monkeypatch):
    monkeypatch.setattr(failover, "acp_agents_ok", lambda: set())
    (zc,) = failover.load_chain([{"tui": "zcode"}])
    assert failover.preflight(zc) == (False, "acp-run --list has no ok row for 'zcode'")
    (sipb,) = failover.load_chain([{"tui": "sipb", "model": "m", "secret": "NOT_DECLARED"}])
    monkeypatch.setattr(failover, "endpoint_reachable", lambda url: True)
    ok, why = failover.preflight(sipb)
    assert not ok and "NOT_DECLARED" in why


def test_acp_agents_ok_loads_route_agent_by_path(tmp_path, monkeypatch):
    fake = tmp_path / "acp-run-list"
    fake.write_text("#!/bin/sh\necho 'ok claude    claude-agent-acp'\necho '-- devin     devin acp'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ACP_RUN", str(fake))
    monkeypatch.delitem(sys.modules, "route_agent", raising=False)
    monkeypatch.setattr(failover, "acp_agents_ok", REAL_ACP_AGENTS_OK)
    failover._cache.clear()
    assert failover.acp_agents_ok() == {"claude"}
    assert "route_agent" in sys.modules


def test_preflight_unreachable_endpoint(monkeypatch):
    monkeypatch.setattr(failover, "endpoint_reachable", lambda url: False)
    (sipb,) = failover.load_chain([{"tui": "sipb", "model": "m"}])
    assert failover.preflight(sipb)[1].startswith("endpoint http://127.0.0.1:8890/api")


# ── ordered attempts ────────────────────────────────────────────────────────

def test_run_chain_skips_preflight_failures_and_fails_over(tmp_path, monkeypatch):
    chain = failover.load_chain([
        {"tui": "opencode", "model": "opencode-go/kimi-k3", "floor_percent": 10},  # preflight: floor
        {"tui": "agy", "model": "gemini-3.8-flash", "effort": "low"},               # attempt fails
        {"tui": "claude", "model": "haiku"},                                         # wins
        {"tui": "claude", "model": "sonnet"},                                        # never tried
    ])
    tried = []

    def attempt(e):
        tried.append(e.label)
        if e.tui.name == "agy":
            raise failover.AttemptFailed("simulated 429")
        return "answer"
    res = failover.run_chain(chain, attempt, task="t")
    assert res.ok and res.value == "answer" and res.entry.model == "haiku"
    assert tried == ["agy:gemini-3.8-flash@low", "claude:haiku"]
    log = _log(tmp_path)
    assert [(r["phase"], r["ok"], r["tui"]) for r in log] == [
        ("preflight", False, "opencode"), ("preflight", True, "agy"), ("attempt", False, "agy"),
        ("preflight", True, "claude"), ("attempt", True, "claude")]
    assert log[2]["why"] == "simulated 429"


def test_run_chain_exhausted(tmp_path):
    chain = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    res = failover.run_chain(chain, lambda e: failover.AttemptFailed("no"), task="t")
    assert not res.ok
    assert _log(tmp_path)[-1] == {**_log(tmp_path)[-1], "phase": "chain", "why": "chain_exhausted"}


# ── executing an entry ──────────────────────────────────────────────────────

def test_acp_command_flags(tmp_path):
    zc, cl, agy = failover.load_chain([
        {"tui": "zcode", "effort": "low"}, {"tui": "claude", "model": "haiku", "extra_args": ["--no-fallback"]},
        {"tui": "agy", "model": "gemini-3.8-flash", "effort": "high"}])
    cmd = failover.acp_command(zc, tmp_path / "p.md", tmp_path)
    assert cmd[1:3] == ["zcode", "-C"] and "--model" not in cmd
    assert cmd[cmd.index("--set") + 1] == "thought=low"
    assert cmd[cmd.index("--perm") + 1] == "deny" and cmd[cmd.index("-f") + 1] == str(tmp_path / "p.md")
    cmd = failover.acp_command(cl, tmp_path / "p.md", tmp_path)
    assert cmd[cmd.index("--model") + 1] == "haiku" and cmd[-1] == "--no-fallback" and "--set" not in cmd
    cmd = failover.acp_command(agy, tmp_path / "p.md", tmp_path)
    assert cmd[cmd.index("--model") + 1] == "gemini-3.8-flash-high"


def test_ask_acp_runs_in_empty_dir(tmp_path, monkeypatch):
    acp = tmp_path / "acp-run2"
    acp.write_text('#!/bin/sh\nwhile [ "$1" != "-C" ]; do shift; done; ls -A "$2" | wc -l | tr -d " "\n')
    acp.chmod(0o755)
    monkeypatch.setenv("FAILOVER_ACP_RUN", str(acp))
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    assert failover.ask(cl, "q") == "0"


def _fake_acp(tmp_path: Path, monkeypatch, name: str, body: str) -> Path:
    acp = tmp_path / name
    acp.write_text("#!/bin/sh\n" + body)
    acp.chmod(0o755)
    monkeypatch.setenv("FAILOVER_ACP_RUN", str(acp))
    return acp


def test_ask_acp_failure_and_empty(tmp_path, monkeypatch):
    _fake_acp(tmp_path, monkeypatch, "acp-run3", 'echo "FAILED quota" >&2\nexit 1\n')
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    with pytest.raises(failover.AttemptFailed, match="rc=1"):
        failover.ask(cl, "q")
    _fake_acp(tmp_path, monkeypatch, "acp-run4", "exit 0\n")
    with pytest.raises(failover.AttemptFailed, match="empty answer"):
        failover.ask(cl, "q")


def _result_log(fields: str) -> str:
    return ('LOG=""; prev=""; for x in "$@"; do [ "$prev" = "--log" ] && LOG="$x"; prev="$x"; done\n'
            f"[ -n \"$LOG\" ] && echo '{{\"kind\": \"result\", \"data\": {fields}}}' > \"$LOG\"\n")


@pytest.mark.parametrize(("fields", "ok"), [
    ('{"tool_calls": 0, "failure": "refused"}', True),
    ('{"tool_calls": 0, "failure": "provider", "error": "Error: No such tool available: invoke_tool"}', True),
    ('{"tool_calls": 0, "failure": "provider", "error": "Error: RetriableError: PING timed out"}', False),
    ('{"tool_calls": 0, "failure": "quota"}', False),
])
def test_ask_keeps_a_refusal_as_the_answer(tmp_path, monkeypatch, fields, ok):
    _fake_acp(tmp_path, monkeypatch, "acp-refuse", _result_log(fields) + "echo \"I can't do that\"\nexit 1\n")
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    if ok:
        assert failover.ask(cl, "q") == "I can't do that"
    else:
        with pytest.raises(failover.AttemptFailed, match="rc=1"):
            failover.ask(cl, "q")


def test_ask_tripwire_exit_is_attempt_failed(tmp_path, monkeypatch):
    _fake_acp(tmp_path, monkeypatch, "acp-trip", "echo partial\nexit 77\n")
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    with pytest.raises(failover.AttemptFailed, match="TRIPWIRE"):
        failover.ask(cl, "q")


def test_ask_child_env_is_minimal_and_logs_are_private(tmp_path, monkeypatch):
    out = tmp_path / "env.txt"
    _fake_acp(tmp_path, monkeypatch, "acp-env",
              f'env > "{out}"\nwhile [ "$1" != "--log" ]; do shift; done; echo "$2"\n')
    monkeypatch.setenv("SOME_API_KEY", "leak-me")
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku", "env": {"MAX_THINKING_TOKENS": "0"}}])
    log = failover.ask(cl, "q")
    env = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    assert "SOME_API_KEY" not in env and "FAKE_SECRET" not in env
    assert env["MAX_THINKING_TOKENS"] == "0" and "HOME" in env and "PATH" in env
    assert Path(log).parent == failover.ACP_LOG_DIR
    assert (failover.ACP_LOG_DIR.stat().st_mode & 0o777) == 0o700


@pytest.mark.parametrize(("body", "ok", "why"), [
    (LOG_RESULT.format(tools=1) + 'while [ "$1" != "-C" ]; do shift; done; touch "$2/canary"; echo DONE\n',
     False, "file was created"),
    (LOG_RESULT.format(tools=1) + "exit 77\n", False, "tripwire"),
    (LOG_RESULT.format(tools=0) + "echo I have no tools\n", True, "canary held (rc=0, 0 tool calls"),
    (LOG_RESULT.format(tools=1) + "exit 5\n", False, "started 1 tool call(s)"),
    (LOG_RESULT.format(tools=2) + "echo DONE\n", False, "started 2 tool call(s)"),
    ("echo no log written\n", False, "no result record"),
    (LOG_RESULT.format(tools=0) + "echo quota >&2; exit 1\n", False, "inconclusive (rc=1)"),
    (LOG_PROVIDER + "exit 1\n", True, "rc=1 provider: no tool to call"),
])
def test_canary(tmp_path, monkeypatch, body, ok, why):
    _fake_acp(tmp_path, monkeypatch, "acp-canary", body)
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    got_ok, got_why = failover.canary_ok(cl)
    assert got_ok is ok and why in got_why
    (sipb,) = failover.load_chain([{"tui": "sipb", "model": "m"}])
    assert failover.canary_ok(sipb) == (True, "no tools on this route")


def test_preflight_runs_canary_only_with_probe(tmp_path, monkeypatch):
    _fake_acp(tmp_path, monkeypatch, "acp-canary2",
              LOG_RESULT.format(tools=1) + 'while [ "$1" != "-C" ]; do shift; done; touch "$2/canary"\n')
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])
    assert failover.preflight(cl, probe=False)[0]
    ok, why = failover.preflight(cl)
    assert not ok and "file was created" in why


@pytest.mark.parametrize("extra", [
    ["--perm", "all"], ["--perm=all"], ["--model", "haiku"], ["--mode", "bypass"], ["--add-dir", "/"],
    ["--agent", "x"], ["-C", "/"], ["--log", "/tmp/x"], ["--resume", "id"],
    # re-verification R10: argparse abbreviations and glued short options
    ["--per", "all"], ["--pe", "all"], ["--per=all"], ["--add", "/Users/djbclark"], ["-Call"],
    ["-fprompt.md"], ["-p", "x"], ["-i"], ["--interact"], ["--prompt-retries", "1", "--perm", "all"],
])
def test_extra_args_cannot_override_policy(extra):
    with pytest.raises(failover.ChainError, match="extra_args may not pass"):
        failover.load_chain([{"tui": "claude", "model": "haiku", "extra_args": extra}])


@pytest.mark.parametrize(("extra", "msg"), [
    (["--set", "provider=x"], "bad value"), (["--set", "mode=yolo"], "bad value"),
    (["--set=thought=yolo"], "bad value"), (["--set"], "needs a value"),
    (["--prompt-retries", "x"], "bad value"), (["--no-fallback=1"], "takes no value"),
])
def test_extra_args_values_checked(extra, msg):
    with pytest.raises(failover.ChainError, match=msg):
        failover.load_chain([{"tui": "claude", "model": "haiku", "extra_args": extra}])


@pytest.mark.parametrize("extra", [["--set", "thought=low"], ["--set=effort=medium"], ["--prompt-retries", "2"],
                                   ["--no-fallback"], ["--handshake-timeout", "90", "--max-load", "6.5"]])
def test_allowed_extra_args(extra):
    (e,) = failover.load_chain([{"tui": "zcode", "extra_args": extra}])
    assert e.extra_args == extra


def test_extra_args_and_env_values_checked_against_deny():
    with pytest.raises(failover.ChainError, match="denied route 'opus'"):
        failover.load_chain([{"tui": "claude", "model": "haiku", "extra_args": ["claude-opus-5-5"]}])
    with pytest.raises(failover.ChainError, match="denied route 'cline'"):
        failover.load_chain([{"tui": "zcode", "env": {"ZCODE_PROVIDER": "cline-pass"}}])


@pytest.mark.parametrize("key", ["ACP_RUN_AGY_SERVER", "PATH", "OPENCODE_CONFIG_CONTENT", "ZCODE_ACP_MODE",
                                 "HTTPS_PROXY", "LD_PRELOAD"])
def test_env_keys_outside_allowlist_refused(key):
    with pytest.raises(failover.ChainError, match="is not allowed"):
        failover.load_chain([{"tui": "claude", "model": "haiku", "env": {key: "x"}}])


@pytest.mark.parametrize(("endpoint", "ok"), [("http://evil.example/api", False), ("http://10.0.0.5/api", False),
                                             ("https://llms-dev-1.mit.edu/api", True),
                                             ("http://localhost:9999/api", True)])
def test_secret_endpoint_must_be_https_or_loopback(endpoint, ok):
    raw = [{"tui": "sipb", "model": "m", "endpoint": endpoint}]
    if ok:
        assert failover.load_chain(raw)[0].endpoint == endpoint
    else:
        with pytest.raises(failover.ChainError, match="https or loopback"):
            failover.load_chain(raw)


def test_secret_fetched_once_per_process(tmp_path, monkeypatch):
    count = tmp_path / "count"
    spec = tmp_path / "spec2"
    spec.write_text(f'#!/bin/sh\necho x >> "{count}"\nprintf "%s\\n" "$FAKE_SECRET"\n')
    spec.chmod(0o755)
    monkeypatch.setenv("FAILOVER_SECRETSPEC", str(spec))
    assert failover.secret_value("MIT_SIPB_API_KEY") == SECRET
    assert failover.secret_value("MIT_SIPB_API_KEY") == SECRET
    assert len(count.read_text().splitlines()) == 1


def test_run_bounded_kills_the_whole_group(tmp_path):
    pidfile = tmp_path / "child.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        failover.run_bounded(["sh", "-c", f'sleep 60 & echo $! > "{pidfile}"; wait'],
                             env=failover.minimal_env(), timeout=1)
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the grandchild sleep outlived the timeout")


def test_sweep_logs(tmp_path):
    d = failover.ACP_LOG_DIR
    d.mkdir(parents=True)
    old, new = d / "old.jsonl", d / "new.jsonl"
    old.write_text("x")
    new.write_text("y")
    t = time.time() - 10 * 86400
    os.utime(old, (t, t))
    assert failover.sweep_logs(7) == 1
    assert not old.exists() and new.exists()


def test_ask_many_stops_on_first_failure(monkeypatch):
    (cl,) = failover.load_chain([{"tui": "claude", "model": "haiku"}])

    def fake(entry, prompt):
        if prompt == "bad":
            raise failover.AttemptFailed("nope")
        return prompt.upper()
    monkeypatch.setattr(failover, "ask", fake)
    assert failover.ask_many(cl, {"a": "x", "b": "y"}) == {"a": "X", "b": "Y"}
    with pytest.raises(failover.AttemptFailed):
        failover.ask_many(cl, {"a": "x", "b": "bad"}, jobs=1)


def test_openai_secret_only_in_header(tmp_path, monkeypatch):
    seen: dict[str, Any] = {}

    class Opener:
        def open(self, req, timeout):
            seen["auth"] = req.unredirected_hdrs.get("Authorization")
            seen["redirectable"] = req.headers.get("Authorization")
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data)
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": " hi "}}]}).encode())

    def build_opener(*handlers):
        seen["handlers"] = handlers
        return Opener()
    monkeypatch.setattr(failover.urllib.request, "build_opener", build_opener)
    (sipb,) = failover.load_chain([{"tui": "sipb", "model": "qwen3-coder:30b"}])
    assert failover.ask(sipb, "q") == "hi"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["redirectable"] is None, "the key must not follow a redirect"
    assert failover._NoRedirect in seen["handlers"]
    assert failover._NoRedirect().redirect_request(None, None, 302, "", {}, "http://x") is None
    assert seen["url"] == "http://127.0.0.1:8890/api/chat/completions"
    assert seen["body"]["model"] == "qwen3-coder:30b"
    assert SECRET not in json.dumps({k: v for k, v in os.environ.items() if k != "FAKE_SECRET"})
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore"), path


def test_run_command_secret_only_in_child_env(tmp_path):
    (sipb,) = failover.load_chain([{"tui": "sipb", "model": "qwen3-coder:30b"}])
    out = tmp_path / "child.json"
    code = ("import hashlib,json,os,sys;"
            "json.dump({'sha': hashlib.sha256(os.environ['OPENAI_API_KEY'].encode()).hexdigest(),"
            "'model': os.environ['FAILOVER_MODEL'], 'arg': sys.argv[1]}, open(sys.argv[2], 'w'))")
    proc = failover.run_command(sipb, [sys.executable, "-c", code, "{model}", str(out)])
    assert proc.returncode == 0
    got = json.loads(out.read_text())
    assert got == {"sha": hashlib.sha256(SECRET.encode()).hexdigest(),
                   "model": "qwen3-coder:30b", "arg": "qwen3-coder:30b"}
    assert "OPENAI_API_KEY" not in os.environ or os.environ["OPENAI_API_KEY"] != SECRET
    assert SECRET not in out.read_text()


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_check_and_refusal(tmp_path, capsys):
    good = tmp_path / "chain.json"
    good.write_text(json.dumps({"chain": [{"tui": "claude", "model": "haiku"}]}))
    assert failover.main(["check", "--chain", str(good)]) == 0
    assert "claude:haiku" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"tui": "cursor"}]))
    assert failover.main(["check", "--chain", str(bad)]) == 2


def test_cli_run_fails_over(tmp_path):
    chain = tmp_path / "chain.json"
    chain.write_text(json.dumps([{"tui": "claude", "model": "haiku"}, {"tui": "claude", "model": "sonnet"}]))
    code = "import sys; sys.exit(0 if sys.argv[1] == 'sonnet' else 3)"
    assert failover.main(["run", "--chain", str(chain), "--", sys.executable, "-c", code, "{model}"]) == 0
    rows = [r for r in _log(tmp_path) if r["phase"] == "attempt"]
    assert [(r["model"], r["ok"]) for r in rows] == [("haiku", False), ("sonnet", True)]
