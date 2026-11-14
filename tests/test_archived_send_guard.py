"""bin/ade_send_guard.py and claude/hooks/archived_send_gate.py: a send to an archived or replaced agent is redirected or
denied, never delivered (ls-02). Offline: a fake `paseo` on PATH, a throwaway succession ledger."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "claude" / "hooks"))
import ade_send_guard as guard  # noqa: E402
import archived_send_gate as gate  # noqa: E402
from test_ade_lead_succession import A, B, C, D, STRANGER, write_link  # noqa: E402

HOOK = ROOT / "claude" / "hooks" / "archived_send_gate.py"
FAKE = """#!/usr/bin/env python3
import json, os, sys
agents = json.load(open(os.environ["FAKE_AGENTS"]))
a = sys.argv[1:]
if a[:2] == ["agent", "inspect"] and a[2] in agents:
    print(json.dumps({"Id": a[2], "Archived": agents[a[2]]}))
else:
    sys.stderr.write("Agent not found: %s\\n" % a[2:3])
    sys.exit(1)
"""


@pytest.fixture
def world(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "paseo").write_text(FAKE)
    (bindir / "paseo").chmod(0o755)
    state, home = tmp_path / "self-session", tmp_path / "paseo-home"
    agents = tmp_path / "agents.json"

    class W:
        pass
    w = W()
    w.state, w.home, w.agents, w.bindir = state, home, agents, bindir

    def live(**flags):  # id -> Archived
        agents.write_text(json.dumps(flags))
    w.live = live
    w.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_AGENTS": str(agents),
             "ADE_SELF_SESSION_STATE": str(state), "PASEO_HOME": str(home)}
    w.env.pop(guard.ALLOW_ENV, None)
    return w


def inspector(agents: dict):
    def inspect(ident):
        if ident not in agents:
            raise LookupError(ident)
        return {"Id": ident, "Archived": agents[ident]}
    return inspect


def chain3(w):
    for pred, nxt in ((A, B), (B, C), (C, D)):
        write_link(w.state, w.home, pred, nxt)


def decide(w, target, agents, **kw):
    return guard.decide(target, inspector(agents), state_dir=w.state, home=w.home, **kw)


def test_a_live_target_passes(world):
    assert decide(world, A, {A: False}).action == guard.PASS


def test_an_archived_target_without_a_successor_is_refused(world):
    d = decide(world, A, {A: True})
    assert d.action == guard.REFUSE and "archived" in d.reason and guard.ALLOW_ENV in d.reason


def test_the_operator_override_resumes_an_archived_target_on_purpose(world):
    assert decide(world, A, {A: True}, allow_archived=True).action == guard.PASS


def test_a_replaced_lead_is_redirected_to_the_end_of_a_three_step_chain(world):
    chain3(world)
    d = decide(world, A, {A: True, B: True, C: True, D: False})
    assert (d.action, d.target) == (guard.REDIRECT, D)
    assert decide(world, C, {C: True, D: False}).target == D


def test_a_resurrected_predecessor_is_still_redirected(world):
    # the reported failure: the ex-lead came back running (Archived=false) after a message reached it
    write_link(world.state, world.home, A, B)
    d = decide(world, A, {A: False, B: False})
    assert (d.action, d.target) == (guard.REDIRECT, B)


def test_the_override_never_defeats_a_redirect(world):
    write_link(world.state, world.home, A, B)
    assert decide(world, A, {A: True, B: False}, allow_archived=True).action == guard.REDIRECT


def test_a_successor_that_is_archived_too_is_refused(world):
    write_link(world.state, world.home, A, B)
    d = decide(world, A, {A: True, B: True})
    assert d.action == guard.REFUSE and B in d.reason


def test_a_cyclic_ledger_is_refused_even_with_the_override(world):
    write_link(world.state, world.home, A, B)
    write_link(world.state, world.home, B, A)
    assert decide(world, A, {A: True, B: True}, allow_archived=True).action == guard.REFUSE


def test_an_unfinished_handoff_is_no_redirect(world):
    write_link(world.state, world.home, A, B, status="awaiting-ack")
    assert decide(world, A, {A: False}).action == guard.PASS
    assert decide(world, A, {A: True}).action == guard.REFUSE


def test_an_unknown_target_and_an_unreadable_paseo_fail_open(world):
    assert decide(world, STRANGER, {}).action == guard.PASS

    def down(_):
        raise OSError("daemon down")
    assert guard.decide(A, down, state_dir=world.state, home=world.home).action == guard.PASS


# --- the command parser ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command,expected", [
    (f"paseo send --json --no-wait -- {A} 'hi'", [(A, None)]),
    (f"paseo send --behavior steer --json {A} hello", [(A, None)]),
    (f"paseo send --prompt-file /tmp/x --no-wait --json {A}", [(A, None)]),
    (f"paseo send --prompt hello --json {A}", [(A, None)]),  # the value of --prompt is not the target
    (f"paseo agent send {A} -- x", [(A, None)]),
    (f"cd /repo && paseo send -- {A} 'a; b'", [(A, None)]),
    (f"echo ok\npaseo send -- {A} msg", [(A, None)]),
    (f"ADE_ALLOW_ARCHIVED_SEND={A} paseo send -- {A} msg", [(A, A)]),
    (f"env ADE_ALLOW_ARCHIVED_SEND={A} /opt/bin/paseo send -- {A} msg", [(A, A)]),
    (f"paseo send -- {A} m1; paseo send -- {B} m2", [(A, None), (B, None)]),
    (f"timeout 30 paseo send --json --no-wait -- {A} hi", [(A, None)]),
    (f"env -u PASEO_AGENT_ID paseo send --json -- {A} hi", [(A, None)]),
    (f"/usr/bin/env -i nohup sudo paseo send {A} hi", [(A, None)]),
    (f"bash -c 'paseo send --json -- {A} hi'", [(A, None)]),
    (f"sh -c \"timeout 5 paseo send -- {A} hi\"", [(A, None)]),
    (f"echo {A} | xargs paseo send {A} hi", [(A, None)]),
    (f"{{ paseo send -- {A} hi; }}", [(A, None)]),
    (f"if paseo send -- {A} hi; then echo ok; fi", [(A, None)]),
    (f"x=$(paseo send -- {A} hi)", [(A, None)]),
    (f"paseo send --home /elsewhere/.paseo {A} hi", []),  # another daemon: not this ledger
    (f"paseo send --host other:6767 -- {A} hi", []),
    (f"cat > brief.md <<'EOF'\npaseo send {A} hi\nEOF\ngit status", []),  # a heredoc body is text
    ("paseo ls -g --json", []),
    (f"echo paseo send {A}", []),
    ("paseo send", []),
    ("git status", []),
])
def test_targets_in_command(command, expected):
    assert gate.targets_in_command(command) == expected


# --- the hook, end to end -------------------------------------------------------------------------------------------

def run_hook(w, tool, tool_input, env=None):
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                          capture_output=True, text=True, env=env or w.env, timeout=30, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def denial(out):
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_denies_a_send_to_a_replaced_lead_and_names_the_successor(world):
    chain3(world)
    world.live(**{A: True, B: True, C: True, D: False})
    reason = denial(run_hook(world, "Bash", {"command": f"paseo send --json --no-wait -- {A} 'done: x'"}))
    assert D in reason and "stale" in reason


def test_hook_denies_the_resurrected_ex_lead(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    assert B in denial(run_hook(world, "Bash", {"command": f"cd /r && paseo send -- {A} hi"}))


def test_hook_denies_an_archived_agent_without_a_successor_unless_overridden(world):
    world.live(**{A: True})
    assert "archived" in denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}))
    assert denial(run_hook(world, "Bash", {"command": f"ADE_ALLOW_ARCHIVED_SEND=1 paseo send -- {A} hi"}))  # `1` names nobody
    assert run_hook(world, "Bash", {"command": f"ADE_ALLOW_ARCHIVED_SEND={A} paseo send -- {A} hi"}) is None
    assert "ADE_ALLOW_ARCHIVED_SEND" in denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}))


def test_hook_covers_the_mcp_send_tool(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: True, B: False})
    assert B in denial(run_hook(world, "mcp__paseo__send_agent_prompt", {"agentId": A, "prompt": "hi"}))
    assert run_hook(world, "mcp__paseo__send_agent_prompt", {"agentId": B, "prompt": "hi"}) is None


def test_hook_allows_live_targets_other_commands_and_shell_built_targets(world):
    world.live(**{A: False, B: True})
    assert run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}) is None
    assert run_hook(world, "Bash", {"command": "paseo ls -a -g --json"}) is None
    assert run_hook(world, "Bash", {"command": "paseo send -- $LEAD hi"}) is None
    assert run_hook(world, "Read", {"file_path": "/x"}) is None


def test_hook_fails_open_when_paseo_is_missing_or_input_is_garbage(world):
    chain3(world)
    env = {**world.env, "PATH": "/usr/bin:/bin"}
    assert run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}, env=env) is None
    proc = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, env=world.env,
                          timeout=30, check=False)
    assert proc.returncode == 0 and not proc.stdout.strip()


def test_cli_prints_the_decision_and_exits_4_for_a_refusal(world):
    world.live(**{A: True})
    proc = subprocess.run([sys.executable, str(ROOT / "bin" / "ade_send_guard.py"), A], capture_output=True, text=True,
                          env=world.env, timeout=30, check=False)
    assert proc.returncode == guard.EXIT_REFUSED and json.loads(proc.stdout)["action"] == guard.REFUSE


def test_the_override_must_name_the_archived_agent(world):
    assert decide(world, A, {A: True}, allow_archived=A).action == guard.PASS
    assert decide(world, A, {A: True}, allow_archived=B).action == guard.REFUSE
    assert decide(world, A, {A: True}, allow_archived="1").action == guard.REFUSE


def test_why_a_target_passes_is_told_apart(world):
    assert "unknown to paseo" in decide(world, STRANGER, {}).reason

    def down(_):
        raise OSError("daemon down")
    assert "could not inspect" in guard.decide(A, down, state_dir=world.state, home=world.home).reason
    assert decide(world, "--host=elsewhere", {}).action == guard.PASS  # an option word is never inspected


def test_an_unreadable_successor_still_redirects(world):
    write_link(world.state, world.home, A, B)

    def inspect(ident):
        if ident == B:
            raise OSError("daemon hiccup")
        return {"Id": ident, "Archived": True}
    d = guard.decide(A, inspect, state_dir=world.state, home=world.home)
    assert (d.action, d.target) == (guard.REDIRECT, B)


def test_the_hook_skips_another_hosts_mcp_agent(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: True, B: False})
    assert run_hook(world, "mcp__paseo__send_agent_prompt", {"agentId": A, "prompt": "hi", "serverId": "remote"}) is None
