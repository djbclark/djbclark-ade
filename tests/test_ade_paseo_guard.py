"""libexec/agent-bin/paseo + bin/ade-paseo-guard: the archived-send guard in the send path itself (ls-06, 2026-11-14), and the
ADE_ALLOW_REPLACED_SEND override. Offline: a fake `paseo` that records every call, a throwaway succession ledger."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))
import ade_send_guard as guard  # noqa: E402
from test_archived_send_guard import chain3, inspector, world  # noqa: E402,F401  (the fixture is reused as is)
from test_ade_lead_succession import A, B, C, D, STRANGER, write_link  # noqa: E402

AGENT_BIN = ROOT / "libexec" / "agent-bin"
SHIM = AGENT_BIN / "paseo"
HELPER = ROOT / "bin" / "ade-paseo-guard"

# The real paseo, as far as the shim can tell: it logs every call (argv and stdin) and answers `agent inspect` from FAKE_AGENTS.
FAKE = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
rec = {"argv": a, "real_env": os.environ.get("ADE_REAL_PASEO")}
if "--stdin" in a:
    rec["stdin"] = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\\n")
agents = json.load(open(os.environ["FAKE_AGENTS"]))
if a[:2] == ["agent", "inspect"]:
    hit = [k for k in agents if k == a[2]] or [k for k in agents if k.startswith(a[2])]  # an exact id, else a unique prefix
    if len(hit) == 1:
        print(json.dumps({"Id": hit[0], "Archived": agents[hit[0]]}))
        sys.exit(0)
    sys.stderr.write("Agent not found: %s\\n" % a[2:3])
    sys.exit(1)
print("real paseo ran: " + " ".join(a))
sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""
# a `paseo` that counts how often the PATH resolves to it, then runs the shim: it is first on PATH in the recursion test
TRACE = """#!/bin/sh
echo "$@" >> "$TRACE_LOG"
exec "$SHIM_UNDER_TEST" "$@"
"""


@pytest.fixture
def sw(world, tmp_path):  # noqa: F811
    """`world` with the richer fake installed and the shim directory first on PATH."""
    (world.bindir / "paseo").write_text(FAKE)
    world.log = tmp_path / "fake.log"
    world.override_log = tmp_path / "state" / "overrides.jsonl"
    world.env = {**world.env, "PATH": f"{AGENT_BIN}:{world.bindir}:{os.environ['PATH']}", "FAKE_LOG": str(world.log),
                 "ADE_SEND_GUARD_LOG": str(world.override_log), "ADE_PYTHON": sys.executable}
    for k in (guard.ALLOW_ENV, guard.ALLOW_REPLACED_ENV, "ADE_REAL_PASEO", "BASH_ENV", "ENV"):  # a startup file may rewrite PATH
        world.env.pop(k, None)
    world.live()

    def run(*args, env=None, input=None, shim=SHIM, timeout=60):
        return subprocess.run([str(shim), *args], capture_output=True, text=True, env={**world.env, **(env or {})}, input=input,
                              timeout=timeout, check=False)

    def calls():  # every recorded argv, in order
        return [json.loads(x)["argv"] for x in world.log.read_text().splitlines()] if world.log.exists() else []

    def sends():  # the recorded `send` calls only
        return [c for c in calls() if "send" in c and c[:2] != ["agent", "inspect"]]
    world.run, world.calls, world.sends = run, calls, sends
    return world


# --- a non-send is untouched ------------------------------------------------------------------------------------------

def test_a_non_send_passes_through_untouched_with_argv_stdin_and_exit_code(sw):
    sw.live(**{A: True})
    p = sw.run("ls", "-a", "-g", "--json", "--stdin", env={"FAKE_RC": "7"}, input="piped text")
    assert p.returncode == 7 and p.stdout == "real paseo ran: ls -a -g --json --stdin\n"
    rec = [json.loads(x) for x in sw.log.read_text().splitlines()]
    assert [(r["argv"], r["stdin"]) for r in rec] == [(["ls", "-a", "-g", "--json", "--stdin"], "piped text")]
    assert rec[0]["real_env"] == str(sw.bindir / "paseo")  # the shim names the real paseo to whatever it runs, also for a non-send


def test_a_non_send_never_probes_and_needs_no_python(sw):
    sw.live(**{A: True})
    p = sw.run("agent", "inspect", A, "--json", env={"ADE_PYTHON": "/nonexistent/python"})  # a probe by the caller itself
    assert p.returncode == 0 and sw.calls() == [["agent", "inspect", A, "--json"]]  # no extra inspect, no fail-open note
    assert "unguarded" not in p.stderr


def test_a_word_send_that_is_not_the_verb_passes_after_judging_nothing(sw):
    sw.live(**{A: True})
    p = sw.run("logs", A, "--filter", "send")
    assert p.returncode == 0 and sw.calls() == [["logs", A, "--filter", "send"]]


# --- the decision, in the send path ----------------------------------------------------------------------------------

def test_a_live_target_passes_unchanged(sw):
    sw.live(**{A: False})
    argv = ["send", "--json", "--no-wait", "--", A, "hello there"]
    p = sw.run(*argv)
    assert p.returncode == 0 and sw.sends() == [argv] and p.stderr == ""


def test_an_unknown_target_passes_and_the_real_paseo_reports_it(sw):
    p = sw.run("send", STRANGER, "hi")
    assert sw.sends() == [["send", STRANGER, "hi"]] and p.returncode == 0


def test_a_replaced_target_is_redirected_and_the_real_paseo_receives_the_successor(sw):
    chain3(sw)
    sw.live(**{A: True, B: True, C: True, D: False})
    p = sw.run("send", "--json", "--no-wait", "--prompt", f"ack {A}", "--", A, "-x")
    assert p.returncode == 0
    assert sw.sends() == [["send", "--json", "--no-wait", "--prompt", f"ack {A}", "--", D, "-x"]]  # only the target word changed
    assert f"{A} was replaced by {D}; sending to {D}" in p.stderr


def test_a_resurrected_ex_lead_is_redirected_too(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    p = sw.run("agent", "send", A, "hi")
    assert sw.sends() == [["agent", "send", B, "hi"]] and p.returncode == 0


def test_an_archived_target_is_refused_with_exit_4_and_nothing_is_sent(sw):
    sw.live(**{A: True})
    p = sw.run("send", "--no-wait", A, "hi")
    assert p.returncode == 4 and sw.sends() == []
    assert "archived" in p.stderr and guard.ALLOW_ENV in p.stderr and "nothing was sent" in p.stderr


def test_an_archived_successor_and_a_cyclic_ledger_are_refused(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: True})
    assert sw.run("send", A, "hi").returncode == 4
    write_link(sw.state, sw.home, B, A)
    sw.live(**{A: False, B: False})
    assert sw.run("send", A, "hi").returncode == 4 and sw.sends() == []


def test_a_message_that_holds_another_id_never_counts_as_a_target(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False})  # A is archived and replaced
    for argv in (["send", "--no-wait", "--", B, "--prompt", f"ack {A}"], ["send", B, f"LEAD {B} took over from {A}"],
                 ["send", "--prompt", f"ack {A}", B]):
        sw.log.unlink(missing_ok=True)
        p = sw.run(*argv)
        assert p.returncode == 0 and sw.sends() == [argv] and "replaced" not in p.stderr
        assert ["agent", "inspect", A, "--json"] not in sw.calls()  # the message's id is not even looked up


def test_the_other_daemon_options_pass_through_unjudged(sw):
    sw.live(**{A: True})
    for argv in (["send", "--host", "other:6767", "--", A, "hi"], ["send", "--host=other", A, "hi"], ["send", "--home", "/x/.paseo", A, "hi"],
                 ["--host", "other:6767", "send", A, "hi"], ["--home=/x", "agent", "send", A, "hi"]):
        sw.log.unlink(missing_ok=True)
        p = sw.run(*argv)
        assert p.returncode == 0 and sw.calls() == [argv], argv  # no inspect call, argv as given


def test_a_global_option_before_the_verb_is_parsed_like_the_hook(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False, C: True})
    for pre in (["--json"], ["-o", "json"], ["--format", "json", "-q"], ["--no-headers", "--no-color"]):
        sw.log.unlink(missing_ok=True)
        assert sw.run(*pre, "send", A, "hi").returncode == 0
        assert sw.sends() == [[*pre, "send", B, "hi"]]
        sw.log.unlink(missing_ok=True)
        assert sw.run(*pre, "agent", "send", C, "hi").returncode == 4 and sw.sends() == []


def test_a_send_without_a_target_passes(sw):
    p = sw.run("send")
    assert p.returncode == 0 and sw.calls() == [["send"]]


def test_the_guard_reuses_the_hooks_parser_not_a_copy():
    text = HELPER.read_text()
    assert "gate.locate_send" in text and "GLOBAL_VALUE_FLAGS" not in text and "\nVALUE_FLAGS" not in text and "\nOTHER_DAEMON" not in text


# --- the overrides ---------------------------------------------------------------------------------------------------

def test_the_archived_override_still_resumes_an_archived_agent_on_purpose(sw):
    sw.live(**{A: True})
    assert sw.run("send", A, "hi", env={guard.ALLOW_ENV: A}).returncode == 0 and sw.sends() == [["send", A, "hi"]]
    sw.log.unlink()
    assert sw.run("send", A, "hi", env={guard.ALLOW_ENV: "1"}).returncode == 4


def test_the_replaced_override_sends_to_a_live_replaced_agent_and_logs_one_line(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    p = sw.run("send", "--no-wait", "--", A, "secret message text", env={guard.ALLOW_REPLACED_ENV: A})
    assert p.returncode == 0 and sw.sends() == [["send", "--no-wait", "--", A, "secret message text"]] and "replaced by" not in p.stderr
    line = json.loads(sw.override_log.read_text())
    assert line["target"] == A and line["successor"] == B and line["argv0"] == "ade-paseo-guard"
    assert isinstance(line["pid"], int) and line["ts"].endswith("Z") and line["override"] == guard.ALLOW_REPLACED_ENV
    assert "secret message text" not in sw.override_log.read_text() and len(sw.override_log.read_text().splitlines()) == 1
    assert stat.S_IMODE(sw.override_log.stat().st_mode) == 0o600 and stat.S_IMODE(sw.override_log.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("value", ["1", "true", B, "11111111", "11111111-0000-4000-8000-00000000000", " ", "x" + "1" * 8])
def test_a_wrong_replaced_override_changes_nothing(sw, value):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    p = sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: value})
    assert sw.sends() == [["send", B, "hi"]] and "replaced by" in p.stderr and not sw.override_log.exists()


def test_the_replaced_override_needs_the_target_to_be_live(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False})  # replaced AND archived: a send would un-archive it
    p = sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A})
    assert sw.sends() == [["send", B, "hi"]] and not sw.override_log.exists() and p.returncode == 0


def test_the_replaced_override_never_covers_a_cycle(sw):
    write_link(sw.state, sw.home, A, B)
    write_link(sw.state, sw.home, B, A)
    sw.live(**{A: False, B: False})
    p = sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A})
    assert p.returncode == 4 and sw.sends() == [] and not sw.override_log.exists()


def test_the_replaced_override_does_not_open_an_archived_successor(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: True})
    assert sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A}).returncode == 4  # refused as before: no live holder


def test_the_replaced_override_does_not_resume_an_archived_agent_nothing_replaced(sw):
    sw.live(**{A: True})
    assert sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A}).returncode == 4  # only ADE_ALLOW_ARCHIVED_SEND does that


def test_a_log_that_cannot_be_written_never_blocks_the_send(sw, tmp_path):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    blocker = tmp_path / "plain-file"
    blocker.write_text("x")
    p = sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A, "ADE_SEND_GUARD_LOG": str(blocker / "sub" / "log.jsonl")})
    assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]]


def test_the_log_defaults_to_the_state_directory_of_the_home(sw, tmp_path):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    env = {guard.ALLOW_REPLACED_ENV: A, "HOME": str(tmp_path / "home")}
    sw.env.pop("ADE_SEND_GUARD_LOG")
    assert sw.run("send", A, "hi", env=env).returncode == 0
    assert (tmp_path / "home" / ".local/state/djbclark-ade/send-guard-overrides.jsonl").read_text().count("\n") == 1


def test_an_in_repo_sender_reads_the_override_from_its_environment(sw, monkeypatch):
    """completion-notice judges its target through `guard()`: with the variable in its environment it sends to the replaced agent."""
    loader = importlib.machinery.SourceFileLoader("completion_notice_ls06", str(ROOT / "bin" / "completion-notice"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    for k in ("ADE_SELF_SESSION_STATE", "PASEO_HOME", "PATH", "FAKE_LOG", "FAKE_AGENTS", "ADE_SEND_GUARD_LOG"):
        monkeypatch.setenv(k, sw.env[k])
    fake = str(sw.bindir / "paseo")
    assert mod.guard_target(A, fake) == (B, None)  # without the override: redirected
    monkeypatch.setenv(guard.ALLOW_REPLACED_ENV, A)
    assert mod.guard_target(A, fake) == (A, None)  # with it: sent as asked
    assert json.loads(sw.override_log.read_text())["target"] == A
    monkeypatch.setenv(guard.ALLOW_REPLACED_ENV, B)
    assert mod.guard_target(A, fake) == (B, None)


# --- the decision function itself --------------------------------------------------------------------------------------

def test_decide_ignores_the_replaced_override_unless_live_and_exact(world):
    write_link(world.state, world.home, A, B)
    kw = {"state_dir": world.state, "home": world.home}
    d = guard.decide(A, inspector({A: False, B: False}), allow_replaced=A, **kw)
    assert (d.action, d.target, d.replaced_by) == (guard.PASS, A, B)
    assert guard.decide(A, inspector({A: False, B: False}), allow_replaced=B, **kw).action == guard.REDIRECT
    assert guard.decide(A, inspector({A: False, B: False}), allow_replaced=True, **kw).action == guard.REDIRECT
    assert guard.decide(A, inspector({A: True, B: False}), allow_replaced=A, **kw).action == guard.REDIRECT
    assert guard.decide(A, lambda i: {"Id": i}, allow_replaced=A, **kw).action == guard.REDIRECT  # no Archived field: not proven live
    assert guard.decide(A, inspector({A: True, B: False}), allow_replaced=A, allow_archived=A, **kw).action == guard.REDIRECT


# --- the shim script -------------------------------------------------------------------------------------------------

def test_the_shim_skips_its_own_directory_even_through_a_symlink(sw, tmp_path):
    alias = tmp_path / "alias-bin"
    alias.symlink_to(AGENT_BIN)
    sw.live(**{A: False})
    p = sw.run("send", A, "hi", env={"PATH": f"{alias}:{AGENT_BIN}:{sw.bindir}:/usr/bin:/bin"})  # two spellings of the shim, then the real one
    assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]]


def test_the_shim_honours_ADE_REAL_PASEO(sw, tmp_path):
    other = tmp_path / "other" / "paseo"
    other.parent.mkdir()
    other.write_text(FAKE.replace("real paseo ran", "other paseo ran"))
    other.chmod(0o755)
    sw.live(**{A: False})
    # the named one wins over the one on PATH (`world.bindir` is on it); and is used when nothing on PATH is a paseo
    p = sw.run("ls", env={"ADE_REAL_PASEO": str(other)})
    assert p.returncode == 0 and p.stdout == "other paseo ran: ls\n"
    p = sw.run("ls", env={"PATH": f"{AGENT_BIN}:/usr/bin:/bin", "ADE_REAL_PASEO": str(other)})
    assert p.returncode == 0 and p.stdout == "other paseo ran: ls\n"
    broken = sw.run("ls", env={"PATH": f"{AGENT_BIN}:/usr/bin:/bin"})
    assert broken.returncode == 127 and "no real paseo" in broken.stderr
    both = sw.run("send", A, "hi", env={"ADE_REAL_PASEO": str(other)})
    assert both.returncode == 0 and "other paseo ran: send" in both.stdout and len(sw.sends()) == 1


def test_the_helper_finds_the_real_paseo_without_the_shims_export(sw):
    sw.live(**{A: True})
    p = subprocess.run([sys.executable, str(HELPER), "send", A, "hi"], capture_output=True, text=True, env=sw.env, timeout=60,
                       check=False)  # run by hand: PATH still starts with the shim directory, which it must skip
    assert p.returncode == 4 and sw.sends() == []


def test_a_missing_helper_fails_open(sw, tmp_path):
    lone = tmp_path / "copy" / "libexec" / "agent-bin"
    lone.mkdir(parents=True)
    shutil.copy(SHIM, lone / "paseo")
    sw.live(**{A: True})  # would be refused if the guard ran
    p = sw.run("send", A, "hi", shim=lone / "paseo", env={"PATH": f"{lone}:{sw.bindir}:/usr/bin:/bin"})
    assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]] and "unguarded" in p.stderr


def test_a_missing_python_fails_open(sw):
    sw.live(**{A: True})
    p = sw.run("send", A, "hi", env={"ADE_PYTHON": "/nonexistent/python3"})
    assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]] and "unguarded" in p.stderr


def test_an_error_inside_the_guard_fails_open(sw, tmp_path):
    """A copy of the checkout whose decision module raises: the send still reaches the real paseo, with a note."""
    copy = tmp_path / "checkout"
    for rel in ("libexec/agent-bin/paseo", "bin/ade-paseo-guard", "claude/hooks/archived_send_gate.py"):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, copy / rel)
    (copy / "bin" / "ade_send_guard.py").write_text("def guard(*a, **k):\n    raise RuntimeError('boom')\n"
                                                    "REFUSE = REDIRECT = 'x'\n")
    sw.live(**{A: True})
    p = sw.run("send", A, "hi", shim=copy / "libexec/agent-bin/paseo", env={"PATH": f"{copy}/libexec/agent-bin:{sw.bindir}:/usr/bin:/bin"})
    assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]]
    assert "RuntimeError: boom; running paseo unguarded" in p.stderr and "Traceback" not in p.stderr


def test_the_probe_never_re_enters_the_shim(sw, tmp_path):
    """`paseo` resolves to a tracer that logs each time PATH reaches it and then runs the shim: one send is one hit. A probe by bare
    name (`paseo agent inspect`) would reach the tracer again."""
    tracer = tmp_path / "tracer"
    tracer.mkdir()
    (tracer / "paseo").write_text(TRACE)
    (tracer / "paseo").chmod(0o755)
    trace = tmp_path / "trace.log"
    sw.live(**{A: False})
    env = {"PATH": f"{tracer}:{AGENT_BIN}:{sw.bindir}:{os.environ['PATH']}", "TRACE_LOG": str(trace), "SHIM_UNDER_TEST": str(SHIM),
           "ADE_REAL_PASEO": str(sw.bindir / "paseo")}
    p = sw.run("send", A, "hi", env=env, shim=tracer / "paseo")
    assert p.returncode == 0 and trace.read_text().count("\n") == 1  # only the caller's own call
    assert ["agent", "inspect", A, "--json"] in sw.calls() and sw.sends() == [["send", A, "hi"]]


def test_the_shim_is_executable_shell_and_the_helper_python():
    assert os.access(SHIM, os.X_OK) and os.access(HELPER, os.X_OK)
    assert SHIM.read_text().startswith("#!/bin/sh\n") and HELPER.read_text().startswith("#!/usr/bin/env python3")


# --- the motivating case -----------------------------------------------------------------------------------------------

PROGRAM = """
import json, subprocess, sys
r = subprocess.run(["paseo", "send", "--json", "--no-wait", "--", sys.argv[1], "from a python program"], capture_output=True, text=True)
print(json.dumps({"rc": r.returncode, "out": r.stdout, "err": r.stderr}))
"""


def python_send(sw, target, env=None):
    p = subprocess.run([sys.executable, "-c", PROGRAM, target], capture_output=True, text=True, env={**sw.env, **(env or {})}, timeout=60,
                       check=False)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_send_from_a_python_program_is_guarded_end_to_end(sw):
    """The reported failure: a send to a replaced ex-lead made from `subprocess.run(["paseo", "send", ...])` went through the
    hook, which never saw it. With the shim directory first on PATH it is redirected, refused, or passes."""
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False, C: True})
    r = python_send(sw, A)  # replaced (and archived): goes to B
    assert r["rc"] == 0 and sw.sends() == [["send", "--json", "--no-wait", "--", B, "from a python program"]]
    sw.log.unlink()
    r = python_send(sw, C)  # archived, nothing replaced it
    assert r["rc"] == 4 and sw.sends() == [] and "archived" in r["err"]
    r = python_send(sw, B)  # live
    assert r["rc"] == 0 and sw.sends() == [["send", "--json", "--no-wait", "--", B, "from a python program"]]


def test_the_same_python_program_is_not_guarded_without_the_shim_on_path(sw):
    """The limit, stated as a test: the guard exists only where PATH resolves `paseo` through libexec/agent-bin."""
    sw.live(**{C: True})
    env = {"PATH": f"{sw.bindir}:{os.environ['PATH']}"}
    r = python_send(sw, C, env=env)
    assert r["rc"] == 0 and len(sw.sends()) == 1


def test_a_python_program_can_carry_the_override_in_its_environment(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    r = python_send(sw, A, env={guard.ALLOW_REPLACED_ENV: A})
    assert r["rc"] == 0 and sw.sends() == [["send", "--json", "--no-wait", "--", A, "from a python program"]]


def test_guard_returns_the_decision_even_when_the_log_cannot_be_written(sw, tmp_path, monkeypatch):
    """At the shim a raising log would fail open to the same send, so the unit is checked on its own: no exception, a PASS."""
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    blocker = tmp_path / "plain-file"
    blocker.write_text("x")
    for k in ("ADE_SELF_SESSION_STATE", "PASEO_HOME", "FAKE_LOG", "FAKE_AGENTS"):
        monkeypatch.setenv(k, sw.env[k])
    d = guard.guard(A, paseo=str(sw.bindir / "paseo"), env={guard.ALLOW_REPLACED_ENV: A}, log_path=blocker / "sub" / "log.jsonl")
    assert (d.action, d.target, d.replaced_by) == (guard.PASS, A, B)
    guard.log_override(d, blocker / "sub" / "log.jsonl")  # and the writer itself swallows the failure


# === repair round 1 (adversary review of #696) ==========================================================================

def checkout_copy(tmp_path, name):
    """A second checkout's agent-bin: a copy of the shim whose `../../bin` is this checkout's helper."""
    top = tmp_path / name
    (top / "libexec" / "agent-bin").mkdir(parents=True)
    shutil.copy(SHIM, top / "libexec" / "agent-bin" / "paseo")
    (top / "bin").symlink_to(ROOT / "bin")
    return top / "libexec" / "agent-bin"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("ade_paseo_guard_under_test", str(HELPER))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


# M1: global options after the verb and after `agent` -------------------------------------------------------------------

SEND_FORMS = [  # (argv template with {t} as the target word)
    ["send", "-o", "json", "{t}", "hi"], ["send", "--format", "json", "{t}", "hi"], ["send", "-qo", "json", "{t}", "hi"],
    ["send", "-ojson", "{t}", "hi"], ["send", "--format=json", "{t}", "hi"], ["agent", "send", "-o", "json", "{t}", "hi"],
    ["agent", "--json", "send", "{t}", "hi"], ["agent", "-o", "json", "send", "{t}", "hi"], ["agent", "-q", "send", "{t}"],
    ["-qo", "json", "send", "{t}", "hi"], ["--json", "agent", "-qo", "json", "send", "--", "{t}", "hi"], ["send", "{t}", "--json", "hi"],
    ["send", "--no-wait", "--prompt", "ack", "-o", "json", "{t}"],
]


@pytest.mark.parametrize("form", SEND_FORMS, ids=lambda f: " ".join(f))
def test_options_after_the_verb_and_after_agent_do_not_hide_the_target(sw, form):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False, C: True})
    fill = lambda t: [t if w == "{t}" else w for w in form]  # noqa: E731
    assert sw.run(*fill(C)).returncode == 4 and sw.sends() == []  # archived, nothing replaced it
    p = sw.run(*fill(A))  # replaced: only the target word moves
    assert p.returncode == 0 and sw.sends() == [fill(B)]


# M2: two shim copies, a wrapper loop -------------------------------------------------------------------------------------

def test_two_shim_copies_on_one_path_do_not_call_each_other(sw, tmp_path):
    other = checkout_copy(tmp_path, "checkout-b")
    sw.live(**{A: True, B: False})
    for path in (f"{AGENT_BIN}:{other}:{sw.bindir}:/usr/bin:/bin", f"{other}:{AGENT_BIN}:{sw.bindir}:/usr/bin:/bin"):
        sw.log.unlink(missing_ok=True)
        p = sw.run("ls", env={"PATH": path}, timeout=20)
        assert p.returncode == 0 and p.stdout == "real paseo ran: ls\n", path
        sw.log.unlink(missing_ok=True)
        p = sw.run("send", A, "hi", env={"PATH": path}, timeout=20)  # the guard still runs, once
        assert p.returncode == 4 and sw.sends() == []
        p = sw.run("send", B, "hi", env={"PATH": path}, timeout=20)
        assert p.returncode == 0 and sw.sends() == [["send", B, "hi"]]


def test_a_symlink_to_the_shim_is_no_real_paseo_either(sw, tmp_path):
    link = tmp_path / "links"
    link.mkdir()
    (link / "paseo").symlink_to(SHIM)
    p = sw.run("ls", env={"PATH": f"{link}:{AGENT_BIN}:{sw.bindir}:/usr/bin:/bin"}, timeout=20)
    assert p.returncode == 0 and p.stdout == "real paseo ran: ls\n"


def test_the_helper_skips_every_shim_copy_when_it_looks_for_the_real_paseo(sw, tmp_path):
    other = checkout_copy(tmp_path, "checkout-b")
    mod = load_helper()
    assert mod.real_paseo({"PATH": f"{AGENT_BIN}:{other}:{sw.bindir}"}) == f"{sw.bindir}/paseo"
    assert mod.real_paseo({"PATH": f"{AGENT_BIN}:{other}"}) is None
    assert mod.real_paseo({"PATH": f"{sw.bindir}", "ADE_REAL_PASEO": str(other / "paseo")}) == f"{sw.bindir}/paseo"  # a shim is not named real
    assert mod.is_shim(SHIM) and not mod.is_shim(sw.bindir / "paseo") and not mod.is_shim(tmp_path / "missing")


def test_a_wrapper_that_runs_a_shim_again_stops_at_the_reentry_cap(sw, tmp_path):
    wrapper = tmp_path / "wrapper" / "paseo"
    wrapper.parent.mkdir()
    wrapper.write_text(f'#!/bin/sh\nexec "{SHIM}" "$@"\n')
    wrapper.chmod(0o755)
    p = sw.run("ls", env={"ADE_REAL_PASEO": str(wrapper)}, timeout=30)
    assert p.returncode == 127 and "re-entered 9 times" in p.stderr and sw.calls() == []
    p = sw.run("ls", env={"ADE_PASEO_SHIM_DEPTH": "not-a-number"}, timeout=30)  # junk counts as zero
    assert p.returncode == 0 and p.stdout == "real paseo ran: ls\n"


# M3: BASH_ENV, which the fixture drops, is put back on purpose ------------------------------------------------------------

BASH_SEND = "paseo send --no-wait -- {t} hi"


def bash_env_world(sw, tmp_path):
    """The operator's situation: a BASH_ENV startup file that puts a directory with another `paseo` ahead of PATH."""
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "paseo").write_text('#!/bin/sh\necho "decoy paseo ran: $*"\n')
    (decoy / "paseo").chmod(0o755)
    rc = tmp_path / "bashrc"
    rc.write_text(f'PATH="{decoy}:$PATH"\nexport PATH\n')
    return rc


def test_a_bash_child_whose_startup_file_rewrites_path_is_not_guarded_which_the_docs_say(sw, tmp_path):
    """The limit of the PR's claim, as a test: with BASH_ENV putting another paseo first, `bash -c 'paseo send X'` reaches it."""
    rc = bash_env_world(sw, tmp_path)
    sw.live(**{A: True})
    env = {**sw.env, "PATH": f"{AGENT_BIN}:{sw.bindir}:{os.environ['PATH']}", "BASH_ENV": str(rc)}
    p = subprocess.run(["bash", "-c", BASH_SEND.format(t=A)], capture_output=True, text=True, env=env, timeout=30, check=False)
    assert p.returncode == 0 and "decoy paseo ran" in p.stdout and sw.calls() == []  # unguarded
    # the same bash without the startup file, and a Python child with it, are guarded
    for argv, e in ((["bash", "-c", BASH_SEND.format(t=A)], {k: v for k, v in env.items() if k != "BASH_ENV"}),
                    ([sys.executable, "-c", f'import subprocess; raise SystemExit(subprocess.run(["paseo","send","--",{A!r},"hi"]).returncode)'], env)):
        p = subprocess.run(argv, capture_output=True, text=True, env=e, timeout=30, check=False)
        assert p.returncode == 4 and sw.sends() == [], argv


def test_calling_the_shim_by_its_path_is_guarded_even_when_the_startup_file_reorders_path(sw, tmp_path):
    """The workaround the docs give: `<checkout>/libexec/agent-bin/paseo send ...` needs no PATH. Here the startup file puts the real
    paseo (as ~/.local/bin/paseo is on the operator's Mac) first: the shim, run by its path, still judges and then runs it."""
    rc = tmp_path / "bashrc"
    rc.write_text(f'PATH="{sw.bindir}:$PATH"\nexport PATH\n')
    sw.live(**{A: True})
    env = {**sw.env, "BASH_ENV": str(rc)}
    p = subprocess.run(["bash", "-c", f'"{SHIM}" send --no-wait -- {A} hi'], capture_output=True, text=True, env=env, timeout=30, check=False)
    assert p.returncode == 4 and sw.sends() == []


# L1: a daemon selector after the target --------------------------------------------------------------------------------------

def test_a_daemon_selector_after_the_target_is_not_judged_and_the_word_is_not_rewritten(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False})
    for argv in (["send", A, "--host", "vps:6767", "hi"], ["send", A, "hi", "--home=/x"], ["agent", "--host", "x", "send", A, "hi"]):
        sw.log.unlink(missing_ok=True)
        assert sw.run(*argv).returncode == 0 and sw.calls() == [argv]  # not redirected, not refused, no inspect
    sw.log.unlink(missing_ok=True)
    assert sw.run("send", "--", A, "--host", "x").returncode == 0 and sw.sends() == [["send", "--", B, "--host", "x"]]  # after `--` it is text


# L2: a redirect to the caller itself -----------------------------------------------------------------------------------------

def test_a_redirect_to_the_caller_itself_is_refused(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: True, B: False})
    p = sw.run("send", A, "goodbye", env={"PASEO_AGENT_ID": B})
    assert p.returncode == 4 and sw.sends() == [] and "the caller itself" in p.stderr
    p = sw.run("send", A, "hi", env={"PASEO_AGENT_ID": C})  # someone else: redirected as before
    assert p.returncode == 0 and sw.sends() == [["send", B, "hi"]]
    sw.log.unlink()
    assert sw.run("send", B, "hi", env={"PASEO_AGENT_ID": B}).returncode == 0  # a send to a live target is no redirect


# L4/L5: the override log -------------------------------------------------------------------------------------------------

def test_a_use_logged_at_the_shim_says_it_was_sent_and_several_uses_append(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    for _ in range(2):
        assert sw.run("send", A, "hi", env={guard.ALLOW_REPLACED_ENV: A}).returncode == 0
    lines = [json.loads(x) for x in sw.override_log.read_text().splitlines()]
    assert len(lines) == 2 and {x["source"] for x in lines} == {"send"}
    assert all(x["ppid"] == os.getpid() for x in lines)  # the caller: this test process


def test_a_log_path_that_is_a_symlink_or_a_fifo_is_never_written_through_or_waited_on(tmp_path):
    d = guard.Decision(guard.PASS, A, "x", replaced_by=B)
    target = tmp_path / "victim"
    target.write_text("keep\n")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    guard.log_override(d, link)
    assert target.read_text() == "keep\n"
    fifo = tmp_path / "fifo.jsonl"
    os.mkfifo(fifo)
    proc = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import ade_send_guard as g; "
                           "g.log_override(g.Decision('pass', 'a', '', replaced_by='b'), sys.argv[2])", str(ROOT / "bin"), str(fifo)],
                          capture_output=True, text=True, timeout=20, check=False)  # a blocking open would time out
    assert proc.returncode == 0


# L6 and the surviving mutants of the review (L9) --------------------------------------------------------------------------------

def test_ADE_REAL_PASEO_naming_a_directory_or_the_shim_is_ignored(sw, tmp_path):
    sw.live(**{A: False})
    for bad in (str(tmp_path), str(SHIM), str(tmp_path / "missing")):
        sw.log.unlink(missing_ok=True)  # a non-send is decided by the shim alone, a send by the helper too: both fall back to PATH
        p = sw.run("ls", env={"ADE_REAL_PASEO": bad}, timeout=20)
        assert p.returncode == 0 and p.stdout == "real paseo ran: ls\n", bad
        sw.log.unlink(missing_ok=True)
        p = sw.run("send", A, "hi", env={"ADE_REAL_PASEO": bad}, timeout=20)
        assert p.returncode == 0 and sw.sends() == [["send", A, "hi"]], bad


def test_a_directory_named_paseo_earlier_on_path_is_no_candidate(sw, tmp_path):
    (tmp_path / "dirs" / "paseo").mkdir(parents=True)
    p = sw.run("ls", env={"PATH": f"{tmp_path / 'dirs'}:{AGENT_BIN}:{sw.bindir}:/usr/bin:/bin"}, timeout=20)
    assert p.returncode == 0 and p.stdout == "real paseo ran: ls\n"


def test_a_prefix_target_needs_the_full_id_as_the_override(sw):
    write_link(sw.state, sw.home, A, B)
    sw.live(**{A: False, B: False})
    pre = A[:8]
    assert sw.run("send", pre, "hi", env={guard.ALLOW_REPLACED_ENV: pre}).returncode == 0
    assert sw.sends() == [["send", B, "hi"]]  # a prefix is no override, even for a prefix target
    sw.log.unlink()
    assert sw.run("send", pre, "hi", env={guard.ALLOW_REPLACED_ENV: A}).returncode == 0
    assert sw.sends() == [["send", pre, "hi"]]  # the full id covers a send that names the agent by prefix


def test_the_shim_found_through_a_symlink_still_finds_its_helper(sw, tmp_path):
    absolute = tmp_path / "abs" / "paseo"
    absolute.parent.mkdir()
    absolute.symlink_to(SHIM)
    relative = tmp_path / "rel" / "bin" / "paseo"
    relative.parent.mkdir(parents=True)
    relative.symlink_to(os.path.relpath(SHIM, relative.parent))
    sw.live(**{A: True})
    for link in (absolute, relative):
        p = sw.run("send", A, "hi", shim=link, env={"PATH": f"{link.parent}:{sw.bindir}:/usr/bin:/bin"}, timeout=20)
        assert p.returncode == 4 and "unguarded" not in p.stderr, link


def test_python_environment_variables_do_not_reach_the_helper(sw, tmp_path):
    evil = tmp_path / "evil"
    evil.mkdir()
    marker = tmp_path / "marker"
    (evil / "shlex.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    sw.live(**{A: True})
    p = sw.run("send", A, "hi", env={"PYTHONPATH": str(evil)}, timeout=30)
    assert p.returncode == 4 and not marker.exists()


def test_the_shim_itself_reads_no_startup_file(sw, tmp_path):
    """It runs under /bin/sh: a BASH_ENV (the operator's ~/.bashrc) must not rewrite the PATH the shim walks (found while repairing M3)."""
    marker = tmp_path / "sourced"
    rc = tmp_path / "rc"
    rc.write_text(f"echo x > {marker}\n")
    p = sw.run("ls", env={"BASH_ENV": str(rc), "ENV": str(rc)}, timeout=30)
    assert p.returncode == 0 and not marker.exists()
