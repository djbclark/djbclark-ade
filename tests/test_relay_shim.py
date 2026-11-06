#!/usr/bin/env python3
"""skills/session-finder/relay.py, the one-cycle relay shim (2026-11-06, docs/slim/PLAN.md E3 and D1).

A fake `paseo` on PATH answers `ls`, `send` and `wait` with canned JSON and logs each call. The heart: `paseo send` exits 0 for every
status, so the shim reads `.status` from `--json`; only `sent` and `completed` are delivery.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIM = ROOT / "skills" / "session-finder" / "relay.py"
A1 = "4f0c2a9e-1111-4c89-b6f4-435db7aef10c"
A2 = "4f0c77d0-2222-4584-a254-f33bb399de58"
ROWS = [{"id": A1, "shortId": A1[:8], "name": "lead", "provider": "claude/opus", "status": "running", "cwd": "~/src/x", "created": "1m", "background": False},
        {"id": A2, "shortId": A2[:8], "name": "twin", "provider": "codex/gpt", "status": "idle", "cwd": "~/src/y", "created": "2m", "background": False},
        {"id": "9a9a9a9a-3333-4c89-b6f4-435db7aef10c", "shortId": "9a9a9a9a", "name": "twin", "provider": "claude/opus", "status": "idle",
         "cwd": "~/src/z", "created": "3m", "background": True}]

FAKE = """#!{py}
import json, os, sys
d = os.environ["FAKE_PASEO_DIR"]
a = sys.argv[1:]
rec = {{"argv": a}}
if a and a[0] == "send" and "--prompt-file" in a:
    rec["text"] = open(a[a.index("--prompt-file") + 1], encoding="utf-8").read()
with open(os.path.join(d, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(rec) + "\\n")
name = a[0] if a else "none"
rc_file = os.path.join(d, name + ".rc")
if os.path.exists(rc_file):
    sys.stderr.write("Error: daemon not running\\n")
    sys.exit(int(open(rc_file).read()))
print(open(os.path.join(d, name + ".json")).read())
"""


class Env:
    def __init__(self, tmp: Path) -> None:
        self.dir = tmp / "paseo"
        self.dir.mkdir()
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "paseo"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(0o755)
        self.env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_PASEO_DIR": str(self.dir), "HOME": str(tmp)}
        self.answer("ls", ROWS)
        self.answer("send", {"status": "sent", "agentId": A1})
        self.answer("wait", {"status": "idle"})

    def answer(self, cmd: str, obj: object) -> None:
        (self.dir / f"{cmd}.json").write_text(json.dumps(obj))

    def fail(self, cmd: str, rc: int = 1) -> None:
        (self.dir / f"{cmd}.rc").write_text(str(rc))

    def run(self, *args: str, stdin: str | None = None, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SHIM), *args], input=stdin, capture_output=True, text=True, timeout=60,
                              env={**self.env, **extra})

    def calls(self) -> list[dict]:
        p = self.dir / "calls.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def sent(self) -> list[dict]:
        return [c for c in self.calls() if c["argv"][0] == "send"]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.mark.parametrize("status", ["sent", "completed"])
def test_sent_or_completed_is_delivered(env: Env, status: str) -> None:
    env.answer("send", {"status": status})
    r = env.run("lead", "hello")
    assert (r.returncode, r.stdout.strip()) == (0, "delivered"), r.stderr
    (send,) = env.sent()
    assert send["argv"][:2] == ["send", A1] and "--no-wait" in send["argv"] and "--json" in send["argv"]
    assert send["argv"][send["argv"].index("--behavior") + 1] == "steer"    # never Paseo's interrupt default for a caller with no PASEO_AGENT_ID
    assert send["text"] == "[relay from a non-Paseo caller] hello"


def test_queued_is_accepted_not_delivered(env: Env) -> None:
    env.answer("send", {"status": "queued"})
    r = env.run("lead", "hello", "--wait", "5")
    assert r.returncode == 2 and r.stdout.startswith("queued (accepted by the daemon, not yet delivered"), r.stdout
    assert not [c for c in env.calls() if c["argv"][0] == "wait"], "a message not delivered is not waited on"


@pytest.mark.parametrize("status", ["timeout", "permission", "error"])
def test_every_other_status_exits_2_although_paseo_exited_0(env: Env, status: str) -> None:
    env.answer("send", {"status": status})
    r = env.run("lead", "hello")
    assert (r.returncode, r.stdout.strip()) == (2, status)


def test_paseo_failing_is_exit_1_with_its_stderr(env: Env) -> None:
    env.fail("send")
    r = env.run("lead", "hello")
    assert r.returncode == 1 and "daemon not running" in r.stderr and "delivered" not in r.stdout
    env.answer("send", {})
    (env.dir / "send.rc").unlink()
    (env.dir / "send.json").write_text("not json")
    r = env.run("lead", "hello")
    assert r.returncode == 1 and "no JSON" in r.stderr
    env.fail("ls")
    assert env.run("lead", "hello").returncode == 1


def test_no_paseo_on_path_is_exit_1(env: Env) -> None:
    r = env.run("lead", "hello", PATH=str(env.dir))
    assert r.returncode == 1 and "paseo is not on PATH" in r.stderr


@pytest.mark.parametrize("target", ["w34:p4", "nobody", "/x/jobs/a.json", "self"])
def test_a_target_that_is_not_a_paseo_agent_is_refused_with_the_retirement(env: Env, target: str) -> None:
    r = env.run(target, "hello")
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31)" in r.stderr
    assert f"target {target} is not a Paseo agent" in r.stderr
    assert not env.sent()


def test_an_ambiguous_name_or_prefix_is_refused(env: Env) -> None:
    for target in ("twin", "4f0c"):
        r = env.run(target, "hello")
        assert r.returncode == 3 and "matches 2 Paseo agents" in r.stderr, (target, r.stderr)
    assert not env.sent()


@pytest.mark.parametrize("target", [A1, A1[:8], A1[:12], "lead"])
def test_an_id_prefix_shortid_or_name_resolves(env: Env, target: str) -> None:
    assert env.run(target, "hello").returncode == 0
    assert env.sent()[0]["argv"][1] == A1


def test_self_is_paseo_agent_id_and_a_paseo_sender_gets_no_prefix(env: Env) -> None:
    r = env.run("self", "note to self", PASEO_AGENT_ID=A2)
    assert r.returncode == 0
    (send,) = env.sent()
    assert send["argv"][1] == A2 and send["text"] == "note to self"


def test_a_declared_sender_is_named(env: Env) -> None:
    assert env.run("lead", "x", RELAY_SENDER_NAME="deadline").returncode == 0
    assert env.sent()[0]["text"] == "[relay from deadline] x"


def test_wait_maps_to_paseo_wait_timeout(env: Env) -> None:
    r = env.run("lead", "hello", "--wait", "20")
    assert r.returncode == 0 and r.stdout.split() == ["delivered", "idle"]
    (wait,) = [c for c in env.calls() if c["argv"][0] == "wait"]
    assert wait["argv"] == ["wait", A1, "--timeout", "20", "--json"]
    env.answer("wait", {"status": "timeout"})
    r = env.run("lead", "hello", "--wait", "2.5")
    assert r.returncode == 2 and "wait timed out after 2.5 s" in r.stdout
    env.answer("wait", {"status": "permission"})
    r = env.run("lead", "hello", "--wait", "3")
    assert r.returncode == 2 and r.stdout.splitlines()[-1].startswith("permission")
    env.fail("wait")
    assert env.run("lead", "hello", "--wait", "3").returncode == 1


def test_message_file_dash_reads_stdin_exactly(env: Env, tmp_path: Path) -> None:
    text = "a `backtick`, $(not run) and \"quotes\"\nsecond line\n"
    r = env.run("lead", "--message-file", "-", stdin=text, PASEO_AGENT_ID=A2)
    assert r.returncode == 0, r.stderr
    assert env.sent()[-1]["text"] == text[:-1]    # one trailing newline dropped, nothing else changed
    f = tmp_path / "m.txt"
    f.write_text("from a file", encoding="utf-8")
    assert env.run("lead", "--message-file", str(f), PASEO_AGENT_ID=A2).returncode == 0
    assert env.sent()[-1]["text"] == "from a file"


def test_ack_name_appends_the_request_and_bare_ack_appends_nothing(env: Env) -> None:
    assert env.run("lead", "hi", "--ack", "me-1", PASEO_AGENT_ID=A2).returncode == 0
    assert env.sent()[-1]["text"] == "hi\n\nReply with `ack me-1` through relay.py."
    assert env.run("lead", "--message-file", "-", "--ack", "--wait", "20", stdin="hi", PASEO_AGENT_ID=A2).returncode == 0
    assert env.sent()[-1]["text"] == "hi"


@pytest.mark.parametrize("args", [["--pending"], ["--sweep"], ["--retire", "X", "--reason", "y"], ["--transfer-expectations", "old"],
                                  ["lead", "hi", "--expect-ack", "T1"], ["lead", "hi", "--expect-ack=T1"]])
def test_the_outbox_flags_are_refused_as_retired(env: Env, args: list[str]) -> None:
    r = env.run(*args)
    assert r.returncode == 64 and "retired 2026-11-06: Paseo has no outbox; see `paseo permit ls` for pending permissions" in r.stderr
    assert not env.calls()


def test_via_is_refused_with_the_route_retirement(env: Env) -> None:
    r = env.run("lead", "hi", "--via", "pane")
    assert r.returncode == 64 and "relay.py reaches Paseo agents only since 2026-11-06" in r.stderr and not env.calls()


@pytest.mark.parametrize("args", [["lead"], ["lead", "hi", "--message-file", "-"], ["lead", "--idle", "5", "hi"], ["lead", "   "]])
def test_usage_errors_are_64_never_a_delivery_status(env: Env, args: list[str]) -> None:
    assert env.run(*args, stdin="x").returncode == 64
    assert not env.sent()


def test_help_lists_only_the_flags_that_exist(env: Env) -> None:
    r = env.run("--help")
    assert r.returncode == 0
    usage, retired_part = r.stdout.split("exit status:")
    synopsis = usage.split("\n\n")[0]    # the `usage:` line(s)
    option_lines = [ln.strip() for ln in usage.splitlines() if ln.strip().startswith("-")]    # the options section, not the prose
    flags = {w.strip("[],") for w in (synopsis + " " + " ".join(ln.split("  ")[0] for ln in option_lines)).split()
             if w.lstrip("[").startswith("-")}
    assert flags == {"-h", "--help", "--message-file", "--ack", "--wait"}, flags
    for gone in ("--idle", "--steer", "--no-defer", "--plan", "--no-ack", "--cancel", "--status", "--why"):    # `--json` is named only as paseo's
        assert gone not in r.stdout, gone
    for retired in ("--via", "--pending", "--sweep", "--retire", "--transfer-expectations", "--expect-ack"):
        assert retired in retired_part and retired not in usage, f"{retired} is named only as retired"
    assert "2026-11-20" in r.stdout


def test_the_shim_is_removed_by_2026_11_20() -> None:
    """PLAN.md I1: the shim is temporary. Past this date, remove skills/session-finder/relay.py and this test (the follow-up PR, Wave 6)."""
    assert datetime.date.today() <= datetime.date(2026, 11, 20), "the relay shim outlived its removal date: delete it (docs/slim/PLAN.md F, Wave 6)"
    assert "at the latest 2026-11-20" in SHIM.read_text(encoding="utf-8").splitlines()[1]
