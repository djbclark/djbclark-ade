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
    (f"bash -lc 'paseo send --json -- {A} hi'", [(A, None)]),  # combined -lc / -ec flags
    (f"zsh -ec \"paseo send {A} hi\"", [(A, None)]),
    (f"paseo send --prompt '' {A}", [(A, None)]),  # an empty quoted value is not a separator
    (f"jq . <<< hello\npaseo send -- {A} hi", [(A, None)]),  # a here-string is not a heredoc
    (f"echo $((1<<n))\npaseo send -- {A} hi", [(A, None)]),
    (f"echo 'use <<EOF here'\npaseo send -- {A} hi", [(A, None)]),  # no terminator: the whole command is judged
    (f"# tell the lead\npaseo send --json --no-wait {A} --prompt 'done'", [(A, None)]),  # a comment line hid the send
    (f"cd /repo  # go there\npaseo send -- {A} hi", [(A, None)]),
    (f"echo x # c\npaseo send -- {A} hi", [(A, None)]),
    (f"gh pr view https://github.com/x/y/pull/1#issuecomment-2 && paseo send -- {A} hi", [(A, None)]),  # # inside a word
    (f"paseo send -- {A} 'fix #12 now'", [(A, None)]),  # # inside quotes is text
    (f"paseo send -- {A} \"a\n# not a comment\"\npaseo send -- {B} x", [(A, None), (B, None)]),
    (f"paseo send -- {A} hi # trailing note", [(A, None)]),
    (f"timeout 30 bash -c 'paseo send -- {A} hi'", [(A, None)]),  # a wrapper in front of the shell
    (f"env -u PASEO_AGENT_ID bash -lc 'paseo send -- {A} hi'", [(A, None)]),
    (f"sudo -u bb bash -c 'paseo send -- {A} hi'", [(A, None)]),
    (f"paseo --json send {A} hi", [(A, None)]),  # a global option before the verb
    (f"paseo -o json agent send {A} hi", [(A, None)]),
    (f"paseo --host=other send {A} hi", []),
    (f"paseo send --host=other {A} hi", []),
    (f"paseo send --image a.png {A} hi", [(A, None)]),
    (f"paseo send {A} ADE_ALLOW_ARCHIVED_SEND={A}", [(A, None)]),  # the override is not a word of the message
    (f"paseo send --json --no-wait \\\n  {A} --prompt hi", [(A, None)]),  # a line continuation
    (f"paseo \\\n send {A} hi", [(A, None)]),
    (f"paseo send --no-wait \\\n --prompt \"x\" \\\n {A}", [(A, None)]),
    (f"paseo send {A} \"a \\\nb\"", [(A, None)]),  # a continuation inside double quotes
    (f"bash -c '# c\npaseo send -- {A} hi'", [(A, None)]),  # a comment inside a multi-line -c payload
    (f"echo a\\ #x; paseo send {A} hi", [(A, None)]),  # an escaped blank before # is text, not a comment start
    (f"echo \\;#x; paseo send {A} hi", [(A, None)]),  # so is an escaped separator
    (f"echo foo\\\n#bar; paseo send {A} hi", [(A, None)]),  # and a # right after a continuation: foo#bar
    (f"echo \"a\"#x; paseo send {A} hi", [(A, None)]),  # and one right after a closing quote
    (f"echo hi # don't forget\npaseo send -- {A} hi", [(A, None)]),  # a quote inside a real comment does not open a string
    (f"echo hi;# it's here\npaseo send -- {A} hi", [(A, None)]),
    (f"echo a \\\n#c\npaseo send -- {A} hi", [(A, None)]),  # a comment after a continued blank ends at its own line
    (f"paseo send --no-wait -- {B} 'x `paseo send {A}` y'", [(B, None)]),  # a markdown code span in single quotes is text
    (f"paseo send --no-wait -- {B} 'x $(paseo send {A}) y'", [(B, None)]),
    (f"paseo send --no-wait -- {B} \"x \\`paseo send {A}\\` y\"", [(B, None)]),  # an escaped backtick in double quotes
    (f"paseo send --no-wait -- {B} \"n $((1+2)) m\"", [(B, None)]),  # arithmetic, not a command
    (f"paseo send --no-wait -- {B} --prompt 'Please reply: ack {A}'", [(B, None)]),  # an id inside the message is no target
    (f"paseo send --no-wait -- {B} --prompt \"LEAD {B} took over from {A}\"", [(B, None)]),
    (f'st="$(paseo send --json --no-wait {A} --prompt done | jq -r .status)"; echo "$st"', [(A, None)]),  # a real one in "..."
    (f'echo "result: $(paseo send {A} hi)"', [(A, None)]),
    (f'out="`paseo send {A} hi`"', [(A, None)]),
    (f'out="$(\npaseo send {A} hi\n)"', [(A, None)]),
    (f'if [ "$(paseo send --json {A} hi | jq -r .status)" = sent ]; then echo ok; fi', [(A, None)]),
    (f'echo "a $(echo "b $(paseo send {A} x)")"', [(A, None)]),  # nested substitutions inside double quotes
    (f'git commit -m "see $(paseo send {A} hi) ok" && paseo send {B} x', [(A, None), (B, None)]),  # the quote reopens after
    (f"x=$(paseo send -- {A} hi)", [(A, None)]),
    (f"(paseo send {A} hi)", [(A, None)]),
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


def test_shell_reparsing_stops_at_depth_3():
    import shlex
    cmd = f"paseo send -- {A} hi"
    for _ in range(3):
        cmd = "bash -c " + shlex.quote(cmd)
    assert gate.targets_in_command(cmd) == [(A, None)]  # three levels are looked into
    assert gate.targets_in_command("bash -c " + shlex.quote(cmd)) == []  # the fourth is not


def test_cli_exits_3_for_a_redirect_and_0_for_a_live_agent(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    run = lambda t: subprocess.run([sys.executable, str(ROOT / "bin" / "ade_send_guard.py"), t], capture_output=True, text=True,
                                   env=world.env, timeout=30, check=False)
    proc = run(A)
    assert proc.returncode == guard.EXIT_REDIRECT and json.loads(proc.stdout)["target"] == B
    assert run(B).returncode == 0


def test_a_record_without_an_archived_field_fails_open(world):
    assert guard.decide(A, lambda _: {"Id": A}, state_dir=world.state, home=world.home).action == guard.PASS


def test_the_hook_ignores_an_override_exported_in_its_own_environment(world):
    world.live(**{A: True})
    env = {**world.env, guard.ALLOW_ENV: A}
    assert denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}, env=env))


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


def test_the_hook_judges_an_mcp_agent_even_with_a_server_id(world):
    """A model may pass the calling daemon's own serverId for a local agent: judged; another host's id is unknown here and passes."""
    write_link(world.state, world.home, A, B)
    world.live(**{A: True, B: False})
    assert run_hook(world, "mcp__paseo__send_agent_prompt", {"agentId": A, "prompt": "hi", "serverId": "self"})
    assert run_hook(world, "mcp__paseo__send_agent_prompt", {"agentId": STRANGER, "prompt": "hi", "serverId": "remote"}) is None


@pytest.mark.parametrize("command,expected", [
    (f"paseo send {A} hi; ls \\", [A]),  # a lone trailing backslash: shlex fails, the backstop judges the id
    (f"echo $'it\\'s'; paseo send {A} hi", [A]),  # an ANSI-C quote closes early: the parser gives up, the backstop judges the id
    (f'LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done', [A]),  # a target in a shell variable
    (f"for id in {A} {B}; do paseo send --no-wait \"$id\" hi; done", [A, B]),
    (f"echo {A} | xargs -I{{}} paseo send {{}} hi", [A]),
    (f"paseo send -- {A} hi", []),  # found by the parser: nothing extra
    (f"git commit -m 'about {B}'", []),  # no paseo send in the text: nothing judged
    (f"paseo send --no-wait -- {B} 'moved on: `paseo send {A} hi` is the old way'", []),  # quoted text is no send
    (f'paseo send --no-wait -- {B} --prompt "answer by paseo send: ack {A}"', []),
    (f'echo "result: $(paseo send {A} hi)"', []),  # parsed now (the quote closes around the substitution): nothing extra
])
def test_backstop_judges_ids_in_a_command_the_parser_could_not_follow(command, expected):
    found = gate.targets_in_command(command)
    assert [t for t, _ in gate.backstop_targets(command, found)] == expected


def test_the_hook_denies_a_send_hidden_in_a_quoted_substitution(world):
    world.live(**{A: True})  # True = archived
    reason = denial(run_hook(world, "Bash", {"command": f'st="$(paseo send --json --no-wait {A} --prompt done | jq -r .status)"'}))
    assert A in reason or "archived" in reason
    world.live(**{A: False})
    assert run_hook(world, "Bash", {"command": f'st="$(paseo send --json --no-wait {A} --prompt done | jq -r .status)"'}) is None


def test_a_takeover_notice_naming_the_replaced_id_in_its_quoted_text_is_allowed(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    notice = f'paseo send --json --no-wait -- {B} --prompt "LEAD {B} took over from {A}. Reply with paseo send: ack {B}"'
    assert run_hook(world, "Bash", {"command": notice}) is None  # quoted text is no target and no backstop trigger


def test_a_backstop_denial_is_worded_for_the_backstop_not_as_a_resend(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    reason = denial(run_hook(world, "Bash", {"command": f"paseo send -- {B} ok; echo took over from {A}; ls \\"}))
    assert "could not parse" in reason and A in reason and "Re-send" not in reason
    plain = denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}))  # the parser's own denial keeps its text
    assert "Re-send to" in plain and "could not parse" not in plain


def test_a_backstop_denial_for_an_archived_id_names_the_override_free_exits(world):
    world.live(**{A: True})
    reason = denial(run_hook(world, "Bash", {"command": f'LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done'}))
    assert "could not parse" in reason and "archived" in reason
    world.live(**{A: False})
    assert run_hook(world, "Bash", {"command": f'LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done'}) is None


def test_the_backstop_skips_the_senders_own_id(world):
    """A command the parser cannot follow (a trailing backslash) that carries the sender's own id as text (`ack <own id>`)."""
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    cmd = f"paseo send --json --no-wait -- {B} --prompt ok; echo ack {A}; ls \\"
    assert run_hook(world, "Bash", {"command": cmd}, env={**world.env, "PASEO_AGENT_ID": A}) is None
    assert "could not parse" in denial(run_hook(world, "Bash", {"command": cmd}))  # any other sender: the backstop judges A
    assert run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}, env={**world.env, "PASEO_AGENT_ID": A})  # a target is still judged


def test_a_code_span_in_a_single_quoted_message_is_not_a_send(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    cmd = f"paseo send --no-wait -- {B} 'moved on: `paseo send {A} hi` is the old way'"
    assert run_hook(world, "Bash", {"command": cmd}) is None
