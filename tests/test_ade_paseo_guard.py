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
rec = {"argv": a}
if "--stdin" in a:
    rec["stdin"] = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\\n")
agents = json.load(open(os.environ["FAKE_AGENTS"]))
if a[:2] == ["agent", "inspect"]:
    if a[2] in agents:
        print(json.dumps({"Id": a[2], "Archived": agents[a[2]]}))
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

    def run(*args, env=None, input=None, shim=SHIM):
        return subprocess.run([str(shim), *args], capture_output=True, text=True, env={**world.env, **(env or {})}, input=input,
                              timeout=60, check=False)

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
    assert [json.loads(x) for x in sw.log.read_text().splitlines()] == [{"argv": ["ls", "-a", "-g", "--json", "--stdin"], "stdin": "piped text"}]


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
    assert "gate._target_index" in text and "gate.OTHER_DAEMON" in text and "\nVALUE_FLAGS" not in text and "\nOTHER_DAEMON" not in text


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
    assert SHIM.read_text().startswith("#!/usr/bin/env bash") and HELPER.read_text().startswith("#!/usr/bin/env python3")


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
