"""Hermetic unit tests for bin/ade-herdr-handoff and bin/ade_herdr_handoff.py (Carried #122 Phase 2).

Uses an explicit fake `herdr` executable passed via `ADE_HERDR_BIN` / `--herdr-bin`
(never reordering PATH, never invoking the live Herdr server or touching live panes).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin" / "ade-herdr-handoff"
sys.path.insert(0, str(ROOT / "bin"))
import ade_herdr_handoff as hh  # noqa: E402


FAKE_HERDR_SCRIPT = """#!{python}
import json
import os
import sys

args = sys.argv[1:]
log_path = os.environ["FAKE_HERDR_LOG"]
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")

def ok(result):
    print(json.dumps({{"id": "req-1", "result": result}}))
    sys.exit(0)

def err(code, message="failed", *, on_stdout=False, rc=1):
    payload = json.dumps({{"error": {{"code": code, "message": message}}}})
    if on_stdout:
        print(payload)
    else:
        print(payload, file=sys.stderr)
    sys.exit(rc)

cmd = " ".join(args[:2])
if cmd == "pane current":
    if os.environ.get("FAKE_PANE_FAIL"):
        err(os.environ.get("FAKE_PANE_FAIL_CODE", "pane_not_found"), "no current pane")
    pane = {{
        "pane_id": os.environ.get("FAKE_LIVE_PANE_ID", "w1:p1"),
        "tab_id": os.environ.get("FAKE_LIVE_TAB_ID", "w1:t1"),
        "workspace_id": os.environ.get("FAKE_LIVE_WS_ID", "w1"),
        "agent": os.environ.get("FAKE_LIVE_AGENT", "claude"),
    }}
    if os.environ.get("FAKE_PREV_PANE_ID"):
        pane["previous_pane_id"] = os.environ["FAKE_PREV_PANE_ID"]
    ok({{"pane": pane}})

if cmd == "tab create":
    if os.environ.get("FAKE_TAB_FAIL"):
        err("workspace_not_found", os.environ.get("FAKE_TAB_FAIL_MSG", "workspace missing"))
    ok({{
        "tab": {{"tab_id": os.environ.get("FAKE_NEW_TAB_ID", "w1:t9")}},
        "root_pane": {{"pane_id": os.environ.get("FAKE_NEW_PANE_ID", "w1:p9")}},
    }})

if cmd == "agent start":
    if os.environ.get("FAKE_START_FAIL"):
        err(
            os.environ.get("FAKE_START_FAIL_CODE", "agent_not_ready"),
            os.environ.get("FAKE_START_FAIL_MSG", "agent blocked at startup dialog"),
        )
    ok({{"agent": {{"name": args[2], "pane_id": os.environ.get("FAKE_NEW_PANE_ID", "w1:p9")}}}})

if cmd == "agent prompt":
    if os.environ.get("FAKE_PROMPT_FAIL"):
        err(
            os.environ.get("FAKE_PROMPT_FAIL_CODE", "agent_prompt_stalled"),
            os.environ.get("FAKE_PROMPT_FAIL_MSG", "prompt did not trigger activity"),
        )
    ok({{"submitted": True}})

err("unexpected_command", f"unexpected command: {{cmd}}")
"""


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def env_box(tmp_path: Path):
    """Build an isolated git repo, checkpoint, Tier 1 pointer, state dir, and fake herdr binary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init")
    head = _git(repo, "rev-parse", "HEAD")

    checkpoint = repo / "HANDOFF_test.md"
    checkpoint.write_text("# Handoff\n\nNext step: verify everything.\n", encoding="utf-8")
    tier1 = repo / "SESSION_LOG.md"
    tier1.write_text("# Session Log\n", encoding="utf-8")

    state_dir = tmp_path / "state"
    fake_log = tmp_path / "herdr-calls.jsonl"
    fake_herdr = tmp_path / "fake-herdr"
    fake_herdr.write_text(FAKE_HERDR_SCRIPT.format(python=sys.executable), encoding="utf-8")
    fake_herdr.chmod(0o755)

    base_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PASEO_AGENT_ID", "PASEO_WORKSPACE_ID", "HERDR_ENV", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID")
    }
    base_env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HERDR_ENV": "1",
            "HERDR_PANE_ID": "w1:p1",
            "HERDR_WORKSPACE_ID": "w1",
            "ADE_HERDR_BIN": str(fake_herdr),
            "ADE_HERDR_HANDOFF_STATE": str(state_dir),
            "FAKE_HERDR_LOG": str(fake_log),
        }
    )
    (tmp_path / "home").mkdir()

    def run_cli(*cli_args: str, env_overrides: dict[str, str | None] | None = None, cwd: Path | None = None):
        env = dict(base_env)
        for k, v in (env_overrides or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return subprocess.run(
            [str(BIN), *cli_args],
            cwd=str(cwd or repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def calls() -> list[list[str]]:
        if not fake_log.exists():
            return []
        return [json.loads(line) for line in fake_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    return {
        "tmp": tmp_path,
        "repo": repo,
        "head": head,
        "checkpoint": checkpoint,
        "tier1": tier1,
        "state_dir": state_dir,
        "fake_herdr": fake_herdr,
        "fake_log": fake_log,
        "run": run_cli,
        "calls": calls,
    }


def test_paseo_agent_id_always_wins_and_refuses_without_calling_herdr(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"PASEO_AGENT_ID": "11111111-1111-4111-8111-111111111111"},
    )
    assert r.returncode == hh.EXIT_REFUSED, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["status"] == "refused"
    assert data["code"] == "paseo_mode_active"
    assert "ade-self-session handoff" in data["reason"]
    assert env_box["calls"]() == []
    assert not env_box["state_dir"].exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"HERDR_ENV": None, "HERDR_PANE_ID": None},
        {"HERDR_ENV": "0", "HERDR_PANE_ID": "w1:p1"},
        {"HERDR_ENV": "1", "HERDR_PANE_ID": None},
        {"HERDR_ENV": "1", "HERDR_PANE_ID": "   "},
    ],
)
def test_missing_or_inherited_herdr_env_rejected_before_any_herdr_call(env_box, overrides):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides=overrides,
    )
    assert r.returncode == hh.EXIT_REFUSED, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["code"] == "not_in_herdr"
    assert env_box["calls"]() == []


def test_unconfirmed_live_pane_or_pane_mismatch_refuses_before_tab_create(env_box):
    # Live `herdr pane current --current` fails (e.g. inherited stale HERDR_ENV=1 + HERDR_PANE_ID)
    r1 = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"FAKE_PANE_FAIL": "1"},
    )
    assert r1.returncode == hh.EXIT_REFUSED
    assert json.loads(r1.stdout)["code"] == "herdr_pane_unconfirmed"
    assert [c[:2] for c in env_box["calls"]()] == [["pane", "current"]]

    # Live `herdr pane current --current` returns a different pane without matching previous_pane_id
    r2 = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"FAKE_LIVE_PANE_ID": "w9:p99"},
    )
    assert r2.returncode == hh.EXIT_REFUSED
    assert json.loads(r2.stdout)["code"] == "pane_mismatch"
    assert all(c[:2] != ["tab", "create"] for c in env_box["calls"]())


def test_moved_pane_matching_previous_pane_id_succeeds(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={
            "FAKE_LIVE_PANE_ID": "w2:p1",
            "FAKE_LIVE_WS_ID": "w2",
            "FAKE_PREV_PANE_ID": "w1:p1",
            "FAKE_NEW_TAB_ID": "w2:t5",
            "FAKE_NEW_PANE_ID": "w2:p5",
        },
    )
    assert r.returncode == hh.EXIT_OK, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["status"] == "launched"
    assert data["predecessor_pane_id"] == "w2:p1"
    assert data["workspace_id"] == "w2"
    assert data["successor_pane_id"] == "w2:p5"


@pytest.mark.parametrize(
    "bad_args,expected_code",
    [
        (["--kind", "gemini"], "invalid_kind"),
        (["--model", "default"], "invalid_model"),
        (["--model=--bad"], "invalid_model"),
        (["--model", "bad model"], "invalid_model"),
        (["--effort", "high effort"], "invalid_effort"),
        (["--mode", "yolo"], "invalid_mode"),
        (["--kind", "codex", "--mode", "bypassPermissions"], "invalid_mode"),
        (["--name", "BadName"], "invalid_name"),
        (["--title", "   \n\t  "], "invalid_title"),
        (["--start-timeout", "500"], "invalid_timeout"),
    ],
)
def test_preflight_validation_rejects_bad_args_before_any_herdr_call(env_box, bad_args, expected_code):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        *bad_args,
    )
    assert r.returncode == hh.EXIT_USAGE, r.stdout + r.stderr
    assert json.loads(r.stdout)["code"] == expected_code
    assert env_box["calls"]() == []


def test_preflight_rejects_relative_empty_nonutf8_checkpoint_and_missing_tier1(env_box):
    # Relative checkpoint
    r_rel = env_box["run"]("--checkpoint", "HANDOFF_test.md", "--tier1", str(env_box["tier1"]))
    assert r_rel.returncode == hh.EXIT_USAGE and json.loads(r_rel.stdout)["code"] == "invalid_checkpoint"

    # Empty checkpoint
    empty = env_box["repo"] / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    r_empty = env_box["run"]("--checkpoint", str(empty), "--tier1", str(env_box["tier1"]))
    assert r_empty.returncode == hh.EXIT_USAGE and json.loads(r_empty.stdout)["code"] == "invalid_checkpoint"

    # Non-UTF-8 checkpoint
    bad_utf8 = env_box["repo"] / "bad.md"
    bad_utf8.write_bytes(b"\xff\xfe\x00not-utf8")
    r_utf8 = env_box["run"]("--checkpoint", str(bad_utf8), "--tier1", str(env_box["tier1"]))
    assert r_utf8.returncode == hh.EXIT_USAGE and json.loads(r_utf8.stdout)["code"] == "invalid_checkpoint"

    # Missing tier1
    r_t1 = env_box["run"]("--checkpoint", str(env_box["checkpoint"]), "--tier1", str(env_box["repo"] / "missing.md"))
    assert r_t1.returncode == hh.EXIT_USAGE and json.loads(r_t1.stdout)["code"] == "file_unreadable"

    assert env_box["calls"]() == []


def test_happy_path_claude_launch_record_permissions_and_predecessor_preserved(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        "--model",
        "claude-opus-5-5",
        "--effort",
        "high",
        "--title",
        "ade-successor",
        "--name",
        "succ-claude-1",
        "--json",
    )
    assert r.returncode == hh.EXIT_OK, r.stdout + r.stderr
    rec = json.loads(r.stdout)
    assert rec["schema_version"] == 1
    assert rec["status"] == "launched"
    assert rec["predecessor_pane_id"] == "w1:p1"
    assert rec["workspace_id"] == "w1"
    assert rec["successor_tab_id"] == "w1:t9"
    assert rec["successor_pane_id"] == "w1:p9"
    assert rec["successor_agent_name"] == "succ-claude-1"
    assert rec["head"] == env_box["head"]
    assert rec["predecessor_preserved"] is True
    assert rec["baton_prompt"] == f"/baton {env_box['tier1'].resolve()}"

    expected_sha = hashlib.sha256(env_box["checkpoint"].read_bytes()).hexdigest()
    assert rec["checkpoint_sha256"] == expected_sha
    preserved = Path(rec["preserved_checkpoint_path"])
    assert preserved.read_bytes() == env_box["checkpoint"].read_bytes()
    assert stat.S_IMODE(preserved.stat().st_mode) == 0o600

    record_path = Path(rec["record_path"])
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    assert json.loads(record_path.read_text(encoding="utf-8")) == rec

    calls = env_box["calls"]()
    assert [c[:2] for c in calls] == [
        ["pane", "current"],
        ["tab", "create"],
        ["agent", "start"],
        ["agent", "prompt"],
    ]
    assert calls[1] == [
        "tab",
        "create",
        "--workspace",
        "w1",
        "--cwd",
        os.path.realpath(str(env_box["repo"])),
        "--label",
        "ade-successor",
        "--no-focus",
    ]
    assert calls[2] == [
        "agent",
        "start",
        "succ-claude-1",
        "--kind",
        "claude",
        "--pane",
        "w1:p9",
        "--timeout",
        "60000",
        "--",
        "--permission-mode",
        "bypassPermissions",
        "--model",
        "claude-opus-5-5",
        "--effort",
        "high",
    ]
    assert calls[3] == [
        "agent",
        "prompt",
        "succ-claude-1",
        f"/baton {env_box['tier1'].resolve()}",
        "--timeout",
        "30000",
    ]
    # Predecessor pane is never closed, killed, or prompted
    for c in calls:
        assert c[:2] not in (["tab", "close"], ["pane", "close"], ["pane", "run"], ["agent", "send-keys"])


def test_happy_path_codex_uses_dollar_baton_and_codex_yolo_flags(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        "--kind",
        "codex",
        "--model",
        "gpt-6.1-sol",
        "--effort",
        "high",
    )
    assert r.returncode == hh.EXIT_OK, r.stdout + r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "launched"
    assert rec["kind"] == "codex"
    assert rec["baton_prompt"] == f"$baton {env_box['tier1'].resolve()}"
    calls = env_box["calls"]()
    start = calls[2]
    assert start[start.index("--") + 1 :] == [
        "--dangerously-bypass-approvals-and-sandbox",
        "-m",
        "gpt-6.1-sol",
        "-c",
        'model_reasoning_effort="high"',
    ]
    prompt = calls[3]
    assert prompt[3] == f"$baton {env_box['tier1'].resolve()}"


def test_agent_not_ready_fails_closed_without_retry_or_closing_panes(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"FAKE_START_FAIL": "1", "FAKE_START_FAIL_CODE": "agent_not_ready"},
    )
    assert r.returncode == hh.EXIT_ERROR, r.stdout + r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "failed"
    assert rec["failed_stage"] == "agent_start"
    assert rec["error"]["code"] == "agent_not_ready"
    assert rec["predecessor_preserved"] is True
    assert rec["successor_tab_id"] == "w1:t9"
    assert rec["successor_pane_id"] == "w1:p9"
    calls = env_box["calls"]()
    # Exactly one start attempt, zero prompt attempts, zero closes
    assert [c[:2] for c in calls] == [["pane", "current"], ["tab", "create"], ["agent", "start"]]


@pytest.mark.parametrize(
    "code,expect_uncertain",
    [
        ("agent_blocked", False),
        ("agent_prompt_stalled", True),
    ],
)
def test_agent_prompt_failures_do_not_retry_or_close_predecessor(env_box, code, expect_uncertain):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"FAKE_PROMPT_FAIL": "1", "FAKE_PROMPT_FAIL_CODE": code},
    )
    assert r.returncode == hh.EXIT_ERROR, r.stdout + r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "failed"
    assert rec["failed_stage"] == "agent_prompt"
    assert rec["error"]["code"] == code
    assert bool(rec.get("prompt_delivery_uncertain")) is expect_uncertain
    assert rec["predecessor_preserved"] is True
    calls = env_box["calls"]()
    assert [c[:2] for c in calls] == [
        ["pane", "current"],
        ["tab", "create"],
        ["agent", "start"],
        ["agent", "prompt"],
    ]


def test_tab_create_returning_predecessor_pane_is_refused_before_agent_start(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={"FAKE_NEW_PANE_ID": "w1:p1"},
    )
    assert r.returncode == hh.EXIT_ERROR
    rec = json.loads(r.stdout)
    assert rec["status"] == "failed"
    assert rec["failed_stage"] == "tab_create"
    assert rec["error"]["code"] == "successor_equals_predecessor"
    assert [c[:2] for c in env_box["calls"]()] == [["pane", "current"], ["tab", "create"]]


def test_lockfile_contention_refuses_and_stale_lock_recovers(env_box):
    locks_dir = env_box["state_dir"] / "locks"
    locks_dir.mkdir(parents=True)
    lock_path = locks_dir / "w1_p1.lock"

    # Active flock held by another fd -> refused before tab create
    with lock_path.open("w+", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "pane_id": "w1:p1"}) + "\n")
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            r_busy = env_box["run"](
                "--checkpoint",
                str(env_box["checkpoint"]),
                "--tier1",
                str(env_box["tier1"]),
            )
            assert r_busy.returncode == hh.EXIT_REFUSED, r_busy.stdout + r_busy.stderr
            assert json.loads(r_busy.stdout)["code"] == "handoff_in_progress"
            assert [c[:2] for c in env_box["calls"]()] == [["pane", "current"]]
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # Stale lockfile metadata from a dead PID (flock free) -> recovers cleanly
    lock_path.write_text(json.dumps({"pid": 99_999_999, "pane_id": "w1:p1"}) + "\n", encoding="utf-8")
    r_rec = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
    )
    assert r_rec.returncode == hh.EXIT_OK, r_rec.stdout + r_rec.stderr
    rec = json.loads(r_rec.stdout)
    assert rec["status"] == "launched"
    assert rec["stale_lock_recovered"] is True


def test_dry_run_validates_without_mutating_herdr_or_writing_state(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        "--dry-run",
        "--json",
    )
    assert r.returncode == hh.EXIT_OK, r.stdout + r.stderr
    plan = json.loads(r.stdout)
    assert plan["status"] == "dry-run"
    assert plan["predecessor_pane_id"] == "w1:p1"
    assert plan["workspace_id"] == "w1"
    assert plan["head"] == env_box["head"]
    assert plan["planned_commands"]["tab_create"][1:3] == ["tab", "create"]
    assert plan["planned_commands"]["agent_start"][1:3] == ["agent", "start"]
    assert plan["planned_commands"]["agent_prompt"][1:3] == ["agent", "prompt"]
    assert [c[:2] for c in env_box["calls"]()] == [["pane", "current"]]
    assert not env_box["state_dir"].exists()


def test_status_inspects_saved_record_without_herdr_calls_and_rejects_symlinks(env_box):
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
    )
    assert r.returncode == hh.EXIT_OK
    rec = json.loads(r.stdout)
    env_box["fake_log"].unlink()

    # --status works even with PASEO_AGENT_ID set and HERDR_ENV unset, with zero herdr calls
    r_stat = env_box["run"](
        "--status",
        rec["record_path"],
        env_overrides={"PASEO_AGENT_ID": "22222222-2222-4222-8222-222222222222", "HERDR_ENV": None},
    )
    assert r_stat.returncode == hh.EXIT_OK, r_stat.stdout + r_stat.stderr
    assert json.loads(r_stat.stdout) == rec
    assert env_box["calls"]() == []

    # Symlink record is refused (O_NOFOLLOW)
    sym = env_box["tmp"] / "symlink-record.json"
    sym.symlink_to(rec["record_path"])
    r_sym = env_box["run"]("--status", str(sym))
    assert r_sym.returncode == hh.EXIT_USAGE

    # Combining --status with --checkpoint is a usage error
    r_combo = env_box["run"]("--status", rec["record_path"], "--checkpoint", str(env_box["checkpoint"]))
    assert r_combo.returncode == hh.EXIT_USAGE


def test_non_repo_cwd_records_null_head(env_box):
    plain_dir = env_box["tmp"] / "plain-non-repo"
    plain_dir.mkdir()
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        "--cwd",
        str(plain_dir),
        cwd=plain_dir,
    )
    assert r.returncode == hh.EXIT_OK, r.stdout + r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "launched"
    assert rec["head"] is None


def test_secret_redaction_scrubs_tokens_passwords_and_cookies_from_errors(env_box):
    dirty_msg = (
        "auth failed for https://alice:hunter2@example.com "
        "token=ghp_1234567890abcdef1234567890 Bearer supersecrettoken99 "
        "api_key=my_secret_key_val Set-Cookie: session=topsecretcookie"
    )
    r = env_box["run"](
        "--checkpoint",
        str(env_box["checkpoint"]),
        "--tier1",
        str(env_box["tier1"]),
        env_overrides={
            "FAKE_START_FAIL": "1",
            "FAKE_START_FAIL_CODE": "agent_start_failed",
            "FAKE_START_FAIL_MSG": dirty_msg,
        },
    )
    assert r.returncode == hh.EXIT_ERROR
    combined = r.stdout + r.stderr + Path(json.loads(r.stdout)["record_path"]).read_text(encoding="utf-8")
    for secret in ("hunter2", "ghp_1234567890abcdef1234567890", "supersecrettoken99", "my_secret_key_val", "topsecretcookie"):
        assert secret not in combined
    assert "[redacted]" in combined
