"""bin/ade_send_guard.py and claude/hooks/archived_send_gate.py: a send to an archived or replaced agent is redirected or
denied, never delivered (ls-02). Offline: a fake `paseo` on PATH, a throwaway succession ledger."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

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


def stamp(age=0.0):
    """`acknowledged_at` as `ade-self-session accept` writes it, `age` seconds ago."""
    return datetime.fromtimestamp(time.time() - age, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_an_acknowledged_handoff_redirects_while_the_predecessor_still_runs(world):
    """rq-38 (a): a peer's send to the acknowledged, not yet archived predecessor goes to the successor."""
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    d = decide(world, A, {A: False, B: False})
    assert (d.action, d.target) == (guard.REDIRECT, B) and "acknowledged" in d.reason


def test_an_awaiting_ack_handoff_is_not_redirected_yet(world):
    write_link(world.state, world.home, A, B, status="awaiting-ack", ack=None)
    assert decide(world, A, {A: False, B: False}).action == guard.PASS


def test_an_acknowledged_handoff_with_a_dead_or_unknown_successor_leaves_the_predecessor_reachable(world):
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    assert decide(world, A, {A: False, B: True}).action == guard.PASS  # successor archived: not a place to send
    assert decide(world, A, {A: False}).action == guard.PASS  # successor unknown to paseo

    def flaky(ident):
        if ident == B:
            raise OSError("daemon hiccup")
        return {"Id": ident, "Archived": False}
    assert guard.decide(A, flaky, state_dir=world.state, home=world.home).action == guard.PASS


def test_acknowledged_hops_chain_with_completed_ones(world):
    write_link(world.state, world.home, A, B)  # completed
    write_link(world.state, world.home, B, C, status="acknowledged", acknowledged_at=stamp())
    write_link(world.state, world.home, C, D)  # completed
    d = decide(world, A, {A: True, B: False, C: False, D: False})
    assert (d.action, d.target) == (guard.REDIRECT, D)


def test_an_acknowledged_cycle_is_refused(world):
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    write_link(world.state, world.home, B, A, status="acknowledged", acknowledged_at=stamp())
    assert decide(world, A, {A: False, B: False}).action == guard.REFUSE


def test_the_replaced_override_still_sends_to_an_acknowledged_predecessor(world):
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    d = decide(world, A, {A: False, B: False}, allow_replaced=A)
    assert (d.action, d.target, d.replaced_by) == (guard.PASS, A, B)


def test_other_consumers_still_see_an_acknowledged_handoff_as_no_link(world):
    import ade_lead_succession as succ
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    assert succ.effective_lead(A, world.state, world.home) == A


def test_a_stuck_acknowledged_handoff_hands_the_predecessor_its_mail_back(world):
    """adversary M1: `finish` refused for good and nothing ends the record: only its age (or a recorded failure) can."""
    agents = {A: False, B: False}
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp(7200))
    assert decide(world, A, agents).action == guard.PASS  # older than the window
    write_link(world.state, world.home, A, B, status="acknowledged")  # no stamp at all (written before rq-38)
    assert decide(world, A, agents).action == guard.PASS
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at="yesterday")
    assert decide(world, A, agents).action == guard.PASS
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp(-3600))  # from the future
    assert decide(world, A, agents).action == guard.PASS


@pytest.mark.parametrize("status,code,redirects", [
    ("acknowledged", None, True), ("acknowledged", "PREDECESSOR_NOT_IDLE", True),
    ("acknowledged", "LISTING_GAP", False), ("acknowledged", "ARCHIVE_FAILED", False),
    # `finish` saves archive-unknown before every archive call and keeps it after Paseo's AGENT_RUNNING refusal (lead review B1)
    ("archive-unknown", "AGENT_RUNNING", True), ("archive-unknown", "PREDECESSOR_NOT_IDLE", True),
    ("archive-unknown", None, False),  # a crashed archive with no recorded reason: unknown outcome
    ("archive-unknown", "ARCHIVE_FAILED", False), ("archive-unknown", "ARCHIVED_OTHER_AGENT", False),
    ("archive-unknown", "ARCHIVE_RESOLVED_OTHER_AGENT", False),  # sr-43 a: an AGENT_RUNNING naming another agent is no wait
    ("creation-unknown", None, False), ("creation-refused", "INVALID_THINKING_OPTION", False), ("creation-refused", None, False), ("awaiting-ack", None, False), ("archive-failed", "AGENT_RUNNING", False),
])
def test_only_a_waiting_finish_keeps_the_acknowledged_redirect(world, status, code, redirects):
    over = {"native_error": {"op": "finish", "code": code}} if code else {}
    write_link(world.state, world.home, A, B, status=status, acknowledged_at=stamp(), **over)
    assert (decide(world, A, {A: False, B: False}).action == guard.REDIRECT) is redirects


def test_an_unfinished_link_with_a_wrong_predecessor_or_ack_or_successor_record_is_no_redirect(world):
    """lead review B3: the acknowledged path shares `_link`'s checks with the completed one; a regression that splits them shows here."""
    agents = {A: False, B: False, C: False}
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp(), predecessor=C)  # B3a
    assert decide(world, A, agents).action == guard.PASS
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp(), ack={"agent_id": C})  # B3b
    assert decide(world, A, agents).action == guard.PASS
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    assert decide(world, A, agents).action == guard.REDIRECT  # the same record, sound: the fixtures above are what differ

    def no_archived_key(ident):  # B3c: Paseo answered, but without an Archived field: not known to be live
        return {"Id": ident} if ident == B else {"Id": ident, "Archived": False}
    assert guard.decide(A, no_archived_key, state_dir=world.state, home=world.home).action == guard.PASS


def test_the_liveness_check_covers_the_end_of_the_successors_own_chain(world):
    """adversary L2: A ack -> B (live), B completed -> C, C archived: A stays reachable, not refused."""
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    write_link(world.state, world.home, B, C)
    assert decide(world, A, {A: False, B: False, C: True}).action == guard.PASS
    d = decide(world, A, {A: False, B: False, C: False})
    assert (d.action, d.target) == (guard.REDIRECT, C)


def test_the_hook_denies_an_acknowledged_predecessor_send_but_not_to_oneself_twice(world):
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    world.live(**{A: False, B: False})
    reason = denial(run_hook(world, "Bash", {"command": f"paseo send --no-wait -- {A} hi"}))
    assert f"Re-send to {B}" in reason
    reason = denial(run_hook(world, "Bash", {"command": f"paseo send --no-wait -- {A} hi"}, env={**world.env, "PASEO_AGENT_ID": B}))
    assert "is you" in reason and "Re-send" not in reason


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
    # global options after the verb and after `agent` too (adversary M1 on #696)
    (f"paseo send -o json {A} hi", [(A, None)]),
    (f"paseo send --format json {A} hi", [(A, None)]),
    (f"paseo send -qo json {A} hi", [(A, None)]),
    (f"paseo send -ojson {A} hi", [(A, None)]),
    (f"paseo send --format=json {A} hi", [(A, None)]),
    (f"paseo agent send -o json {A} hi", [(A, None)]),
    (f"paseo agent --json send {A} hi", [(A, None)]),
    (f"paseo agent -o json send {A} hi", [(A, None)]),
    (f"paseo agent -q send {A}", [(A, None)]),
    (f"paseo -qo json send {A} hi", [(A, None)]),
    (f"paseo --json agent -qo json send -- {A} hi", [(A, None)]),
    (f"paseo send {A} --json hi", [(A, None)]),
    # an explicit daemon selector anywhere in option position is not judged (adversary L1)
    (f"paseo send {A} --host vps:6767 hi", []),
    (f"paseo send {A} hi --home=/x", []),
    (f"paseo agent --host x send {A} hi", []),
    (f"paseo agent send {A} --home /x hi", []),
    (f"paseo send -- {A} --host vps:6767", [(A, None)]),  # after `--` it is message text
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
    (f"echo `date`#x; paseo send {A} hi", [(A, None)]),  # a # glued to the end of a substitution is part of its word
    (f"echo $(date)#x; paseo send {A} hi", [(A, None)]),
    (f"echo $((1+2))#x; paseo send {A} hi", [(A, None)]),
    (f"gh browse $(git rev-parse HEAD)#L10; paseo send {A} done", [(A, None)]),
    (f"echo 'a'#x; paseo send {A} hi", [(A, None)]),  # and one glued to a closing quote
    (f"echo x\n# don't\npaseo send {A} hi", [(A, None)]),  # a comment after a newline, with a quote in it
    (f"x=$(# don't\npaseo send {A} hi)", [(A, None)]),  # a comment right after `$(`
    (f'x="$(# don\'t\npaseo send {A} hi)"', [(A, None)]),
    (f"(# don't\npaseo send {A} hi)", [(A, None)]),  # and after a bare `(`
    (f"echo a|# don't\npaseo send {A} hi", [(A, None)]),  # and after a pipe
    (f"case $x in a)# don't\npaseo send {A} hi;; esac", [(A, None)]),  # a `)` with nothing open (a case pattern)
    (f"echo \"$( (true) )'\" ; paseo send {A} x", [(A, None)]),  # a subshell inside a substitution inside quotes
    (f'echo "$(echo $(date) ; paseo send {A} x)"', [(A, None)]),  # a nested substitution
    (f'echo "$( (true) ; paseo send {A} x)"', [(A, None)]),
    (f"paseo send {A} hi >--home=x.log", [(A, None)]),  # a redirect operand is no daemon selector (ls-06 r2 B3)
    (f"paseo send > log {A} hi", [(A, None)]),  # nor the agent
    (f'xargs -n1 paseo send <<< "{A} {B}"', []),  # the here-string is not an agent
    (f"paseo send --no-wait {A} hi 2>&1", [(A, None)]),
    (f"paseo send >&2 {A} hi", [(A, None)]),  # ls-07 r1 R1: `>&` is one operator
    (f"paseo send 10>/dev/null {A} hi", [(A, None)]),  # ls-08 B2: kills `\\d{1,2}` -> `\\d`
    ("paseo send 2", [("2", None)]),  # kills "no `j + 1 < len(args)` bound" (an IndexError)
    (f"paseo send -- 2>x {A} hi", [(A, None)]),  # ls-08 B4: the shell takes a redirect after `--` too
    (f"paseo send -- >x {A} hi", [(A, None)]),
    (f"paseo send -- 1>&2 {A} hi", [(A, None)]),
    (f"paseo send -- {A} >x hi", [(A, None)]),
    (f"paseo send 2>/dev/null {A} hi", [(A, None)]),  # the fd number the lexer leaves before `>` is no agent
    (f"paseo send 1>out {A} hi", [(A, None)]),
    (f"paseo send &>/dev/null {A} hi", [(A, None)]),
    (f"paseo send >|f {A} hi", [(A, None)]),
    ("paseo send - hi", [("-", None)]),  # a lone `-` is an operand for Commander, so it is the agent (the prompt is `hi`)
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
    (f"eval 'paseo send {A} hi'", [A]),  # a string run by a word the parser does not recurse into
    (f'eval "paseo send {A} hi"', [A]),
    (f"watch -n 60 'paseo send {A} hi'", [A]),
    (f"su bb -c 'paseo send {A} hi'", [A]),
    (f"flock /tmp/l -c 'paseo send {A} hi'", [A]),
    (f"fish -c 'paseo send {A} hi'", [A]),
    (f"nix-shell --run 'paseo send {A} hi'", [A]),
    (f"echo $'it\\'s'; paseo send {A} hi; echo 'done'", [A]),  # an ANSI-C quote with a quote after it on the line
    (f"echo it\\'s; paseo send {A} hi; ls 'x' \\", [A]),  # an escaped quote, then a lone trailing backslash
    (f"LEAD={A}; echo don\\'t; paseo send \"$LEAD\" hi; echo 'x'", [A]),
    (f'LEAD="{A}"; paseo send "$LEAD" x', [A]),  # a quoted id has no blank: not message text
    (f'x="$((paseo send {A} hi) )"', [A]),  # `$((` that is a subshell in a substitution: stays text in the parser, the backstop sees it
    (f'echo "$(paseo send "$LEAD" x)"; LEAD={A}', [A]),
    (f"paseo send -- {B} ok # was paseo send {A}", []),  # a comment is not judged
    (f'paseo send {B} "a \\" b"; LEAD={A}; paseo send "$LEAD" x', [A]),  # an escaped quote does not end the masked string early
    (f'NEW={B}; paseo send --json --no-wait -- "$NEW" --prompt "LEAD $NEW took over from {A}. Reply: ack $NEW"', [B]),  # the quoted message's ids are text
    (f"echo 'paseo send {A} hi' | sh", [A]),  # a script fed to a shell on stdin
    (f"bash <<< 'paseo send {A} hi'", [A]),
    (f"osascript -e 'do shell script \"paseo send {A} hi\"'", [A]),
    (f"foo --command 'paseo send {A} hi'", [A]),
    (f"watch -n1 true; paseo send -- {B} --prompt 'old: paseo send {A} hi'", []),  # the runner word ends with its command
    (f'NEW={B}; paseo send "$NEW" --prompt "ack:{A}"', [B]),  # an id glued into message text is text; only a lone quoted id counts
    (f'paseo send --no-wait "${{LEAD:-{A}}}" --prompt done', [A]),  # a parameter expansion with an id default (r3 A1)
    (f'LEAD="${{LEAD:-{A}}}"; paseo send "$LEAD" hi', [A]),
    (f'SIBS="{A} {B}"; for id in $SIBS; do paseo send --no-wait "$id" hi; done', [A, B]),  # a quoted list of ids (r3 A4)
    (f'echo "{A} {B}" | xargs -n1 paseo send --no-wait', [A, B]),
    (f"echo 'paseo send {A} hi' | $SHELL", [A]),  # r3 A5a
    (f'echo \'paseo send {A} hi\' | "$SHELL"', [A]),
    (f"foo --command='paseo send {A} hi'", [A]),  # r3 A5b
    (f"source <(echo 'paseo send {A} hi')", [A]),  # r3 A5c
    (f"perl -e 'system(q(paseo send {A} hi))'", [A]),  # kills "drop `e` from RUN_FLAG" (r3 A7)
    (f"tmux new -d 'paseo send {A} hi'", [A]),  # kills "drop tmux from RUNNERS"
    (f"nix-shell --run='paseo send {A} hi'", [A]),  # kills "--run(=.*)? -> --run"
    (f'echo -e "old: paseo send {A}"; paseo send -- {B} hi', []),  # r3 A6: echo's -e takes text
    (f'paseo send --json --no-wait -- {B} --prompt "LEAD {B} took over from {A}. Reply with paseo send from bash: ack {B}"', []),  # r3 A3
    (f'git commit -m "fix: paseo send {A} in the sh wrapper"', []),
    (f"echo 'paseo send {A} hi' | \"sh\"", [A]),  # r4 B1: a quoted shell name
    (f"echo 'paseo send {A} hi' | \"/bin/bash\"", [A]),
    (f"echo 'paseo send {A} hi' | '/bin/sh'", [A]),
    (f"awk 'BEGIN {{ system(\"paseo send {A} hi\") }}'", [A]),  # r4 B2: awk and the GNU stream editor can run a command themselves
    (f"s" + f"ed -e '1e paseo send {A} hi' f", [A]),
    (f'printf -e "old: paseo send {A}"; paseo send -- {B} hi', []),  # r4 B6: NO_RUN holds printf and grep
    (f'grep -e "paseo send {A}" log; paseo send -- {B} hi', []),
    (f". <(echo 'paseo send {A} hi')", [A]),
    (f"echo 'paseo send {A} hi' | ${{SHELL}}", [A]),
    (f'SIBS=" {A} {B}"; for id in $SIBS; do paseo send "$id" hi; done', [A, B]),
    (f'paseo send -- "$NEW" --prompt "took over from {A}"; ./run.sh', []),  # `.sh` is not a shell word
    (f'cat bash.log; paseo send -- "$NEW" --prompt "took over from {A}"', []),
    (f"printf '%s\\n' $'{A}\\n{B}' | xargs -n1 paseo send --no-wait", [A, B]),  # ls-07: `\\n` in an ANSI-C body is a blank
    (f'xargs -n1 paseo send <<< "{A} {B}"', [A, B]),  # ls-07: a here-string is no agent, so the ids in it are judged
    (f"osascript 'do shell script \"paseo send {A} hi\"'", [A]),  # kills "drop osascript from RUNNERS" (no `-e` here)
    (f"printf '%s\\n' $'{A}\\t{B}' | xargs -n1 paseo send", [A, B]),  # kills "[ntr] -> n"
    (f"printf '%s\\n' $'{A}\\x0a{B}' | xargs -n1 paseo send", [A, B]),  # ls-08 B5: `\\x0a`, `\\012`, `\\u000a` are blanks too
    (f"printf '%s\\n' $'{A}\\012{B}' | xargs -n1 paseo send", [A, B]),
    (f"printf '%s\\n' $'{A}\\12' | xargs -n1 paseo send", [A]),  # a short octal escape at the end of the body (`\\12{B}` would read `\\121`)
    (f"printf '%s\\n' $'{A}\\u000a{B}' | xargs -n1 paseo send", [A, B]),
    (f"printf '%s\\n' $'{A}\\x20{B}' | xargs -n1 paseo send", [A, B]),
    (f"printf '%s\\n' $'{A}\\v{B}' | xargs -n1 paseo send", [A, B]),  # kills `[ntrvf]` -> `[ntr]`
    (f"printf '%s\\n' $'{A}\\412{B}' | xargs -n1 paseo send", [A, B]),  # bash keeps the low 8 bits: `\\412` is a newline
    (f"printf '%s\\n' $'{A}\\x9' | xargs -n1 paseo send", [A]),  # one hex digit
    (f"printf '%s\\n' $'{A}\\x2d{B}' | xargs -n1 paseo send", []),  # `-` is no blank
    (f"printf '%s\\n' $'{A}\\x1c{B}' | xargs -n1 paseo send", []),  # str.isspace knows it, a shell does not
    (f"printf '%s\\n' $'{A}\\cJ{B}' | xargs -n1 paseo send", [A, B]),
    (f"printf '%s\\n' $'{A}\\U0000000a{B}' | xargs -n1 paseo send", [A, B]),
    (f"paseo send {A} hi; echo $'\\c\u00df'", []),  # ls-08 r2 B1: `\\c` + `ß` raised a TypeError (the hook then allowed the whole command); the parser finds A, nothing extra
    (f"printf '%s\\n' $'{A}\\UFFFFFFFF{B}' | xargs -n1 paseo send", []),  # a code point past U+10FFFF is no blank and no crash
    (f"printf '%s\\n' $'{A}\\c\u0149{B}' | xargs -n1 paseo send", []),  # 716b1: bash reads one byte after `\\c`, so a non-ASCII character is no blank
    (f"printf '%s\\n' $'took over from {A}\\x0a' | xargs -n1 paseo send", []),  # not an id list: still masked
    (f"printf '%s\\n' $'{A}\\\\n{B}' | xargs -n1 paseo send", []),  # an escaped backslash then `n` is no blank
    (f"echo 'x'; eval'paseo send {A} hi'", [A]),  # kills "no quoted_word reset" (a glued string after a runner word)
    (f"rg -e 'paseo send {A}' notes.md; paseo send \"$X\" hi", []),  # kills "drop rg from NO_RUN"
    (f"mawk 'BEGIN{{system(\"paseo send {A} hi\")}}'", [A]),  # kills "drop gawk/mawk from RUNNERS"
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
    assert "could not parse" in reason and A in reason and "Re-send" not in reason and f"send to {B}." in reason
    plain = denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}))  # the parser's own denial keeps its text
    assert "Re-send to" in plain and "could not parse" not in plain


def test_a_backstop_denial_never_tells_the_successor_to_send_to_itself(world):
    """lead review B4 / adversary N3: the unparseable-command branch ran before the self check."""
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    world.live(**{A: False, B: False})
    command = f"paseo send -- {C} ok; echo took over from {A}; ls \\"
    world.live(**{A: False, B: False, C: False})
    other = denial(run_hook(world, "Bash", {"command": command}))
    assert f"send to {B}." in other
    mine = denial(run_hook(world, "Bash", {"command": command}, env={**world.env, "PASEO_AGENT_ID": B}))
    assert "that is you" in mine and f"send to {B}." not in mine


def test_a_backstop_denial_for_an_archived_id_names_the_override_free_exits(world):
    world.live(**{A: True})
    reason = denial(run_hook(world, "Bash", {"command": f'LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done'}))
    assert "could not parse" in reason and "archived" in reason
    world.live(**{A: False})
    assert run_hook(world, "Bash", {"command": f'LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done'}) is None


def test_a_takeover_notice_sent_to_a_shell_variable_is_not_denied_for_the_replaced_id_in_its_text(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    cmd = f'NEW={B}; paseo send --json --no-wait -- "$NEW" --prompt "LEAD $NEW took over from {A}. Reply: ack $NEW"'
    assert run_hook(world, "Bash", {"command": cmd}) is None


def test_a_takeover_notice_mentioning_bash_is_allowed(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    notice = f'paseo send --json --no-wait -- {B} --prompt "LEAD {B} took over from {A}. Reply with paseo send from bash: ack {B}"'
    assert run_hook(world, "Bash", {"command": notice}) is None  # a shell word inside message text does not unmask it


def test_the_backstop_scan_is_linear_on_a_long_command_without_blanks():
    """r3 A2: a `(?:\\S*/)?` prefix in SHELL_WORD made this take ~15 s at 150 KB."""
    import time
    blob = "echo '" + "x" * 300_000 + "' > f; paseo send -- " + A
    t0 = time.monotonic()  # only the backstop is timed: the shlex pass in targets_in_command is not what r3 A2 measured
    gate.backstop_targets(blob, [(A, None)])
    gate.backstop_targets("echo '" + "x" * 300_000 + "' > f", [])  # no `paseo`: returns at once
    many = "paseo send x; " + "echo 'a b' " * 4000  # r4 B4: every quoted string used to rescan its whole command
    gate.backstop_targets(many, [])
    assert time.monotonic() - t0 < 1.0


def test_locate_send_does_not_take_a_repeated_agent_word_for_the_verb():
    assert gate.locate_send(["agent", "agent", "send", A]) == ("none", None)
    assert gate.locate_send(["agent", "send", A]) == ("send", 2)


def test_the_backstop_stays_linear_on_unquoted_blobs_and_on_glued_quotes():
    """ls-07 r2 B1/B2: `(?:\\S*/)?` back in SHELL_WORD costs ~1 s per 20 KB of `x/` or `,:`; each glued quote used to re-join its word."""
    import time
    t0 = time.monotonic()
    gate.backstop_targets("echo " + ",:" * 100_000 + "; paseo send x", [])
    gate.backstop_targets("echo " + "x/" * 100_000 + "; paseo send x", [])
    gate.backstop_targets("echo " + "''" * 40_000 + "; paseo send x", [])
    gate.backstop_targets("echo " + ",:" * 100_000, [])  # no `paseo`: returns at once
    assert time.monotonic() - t0 < 1.0


def test_the_backstop_judges_a_send_run_by_eval(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    assert B in denial(run_hook(world, "Bash", {"command": f"eval 'paseo send {A} hi'"}))


def test_a_code_span_in_a_single_quoted_message_is_not_a_send(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    cmd = f"paseo send --no-wait -- {B} 'moved on: `paseo send {A} hi` is the old way'"
    assert run_hook(world, "Bash", {"command": cmd}) is None


# --- ADE_ALLOW_REPLACED_SEND (ls-06) ---------------------------------------------------------------------------------

def test_the_replaced_override_is_read_from_the_assignment_before_the_command_only():
    hits = gate.targets_in_command(f"ADE_ALLOW_REPLACED_SEND={A} paseo send -- {A} msg; paseo send {B} ADE_ALLOW_REPLACED_SEND={B}")
    assert hits == [(A, None), (B, None)] and [h.replaced for h in hits] == [A, None]  # a word of the message is no override
    both = gate.targets_in_command(f"env ADE_ALLOW_ARCHIVED_SEND={A} ADE_ALLOW_REPLACED_SEND={A} paseo send {A} hi")
    assert both == [(A, A)] and both[0].replaced == A


def test_hook_lets_an_operator_override_send_to_a_live_replaced_agent(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    log = world.state.parent / "overrides.jsonl"
    env = {**world.env, guard.LOG_ENV: str(log)}
    assert B in denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}, env=env))
    assert run_hook(world, "Bash", {"command": f"ADE_ALLOW_REPLACED_SEND={A} paseo send -- {A} hi"}, env=env) is None
    assert json.loads(log.read_text())["successor"] == B  # the use is logged
    for wrong in ("1", B, A[:8]):
        assert B in denial(run_hook(world, "Bash", {"command": f"ADE_ALLOW_REPLACED_SEND={wrong} paseo send -- {A} hi"}, env=env))
    assert B in denial(run_hook(world, "Bash", {"command": f"ADE_ALLOW_ARCHIVED_SEND={A} paseo send -- {A} hi"}, env=env))  # the other override is no cover


def test_hook_replaced_override_needs_a_live_target_and_a_sound_ledger(world):
    write_link(world.state, world.home, A, B)
    cmd = f"ADE_ALLOW_REPLACED_SEND={A} paseo send -- {A} hi"
    world.live(**{A: True, B: False})  # replaced and archived: still redirected
    assert B in denial(run_hook(world, "Bash", {"command": cmd}))
    write_link(world.state, world.home, B, A)  # a cycle
    world.live(**{A: False, B: False})
    assert "inconsistent" in denial(run_hook(world, "Bash", {"command": cmd}))


def test_hook_backstop_never_takes_the_replaced_override_from_text(world):
    """adversary L3 on #696: a non-exported assignment, or the variable named in the quoted message, is no override."""
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    for cmd in (f'ADE_ALLOW_REPLACED_SEND={A} LEAD={A}; paseo send --json --no-wait "$LEAD" --prompt done',
                f'LEAD={A}; paseo send --no-wait "$LEAD" --prompt "next time use ADE_ALLOW_REPLACED_SEND={A}"'):
        assert "could not parse" in denial(run_hook(world, "Bash", {"command": cmd}))
    found = gate.targets_in_command(f'LEAD={A}; paseo send --no-wait "$LEAD" --prompt "use ADE_ALLOW_REPLACED_SEND={A}"')
    assert gate.backstop_targets(f'LEAD={A}; paseo send --no-wait "$LEAD" --prompt x ADE_ALLOW_REPLACED_SEND={A}', found)[0].replaced is None


def test_a_hook_override_use_is_logged_as_a_precheck(world, tmp_path):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    log = tmp_path / "log.jsonl"
    env = {**world.env, guard.LOG_ENV: str(log)}
    assert run_hook(world, "Bash", {"command": f"ADE_ALLOW_REPLACED_SEND={A} paseo send -- {A} hi"}, env=env) is None
    assert json.loads(log.read_text())["source"] == "hook-precheck"


def test_the_hook_ignores_a_replaced_override_exported_in_its_own_environment(world):
    write_link(world.state, world.home, A, B)
    world.live(**{A: False, B: False})
    env = {**world.env, guard.ALLOW_REPLACED_ENV: A}
    assert B in denial(run_hook(world, "Bash", {"command": f"paseo send -- {A} hi"}, env=env))


def test_a_backstop_crash_does_not_unjudge_a_send_the_parser_found(monkeypatch, capsys):
    """716b1 (lead review B2): main() computed the backstop before judging anything, so one exception in it allowed the command."""
    import io
    denied = []
    monkeypatch.setattr(gate, "backstop_targets", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(gate, "judge", lambda target, *a, **k: f"archived {target}" if target == A else None)
    monkeypatch.setattr(gate, "deny", lambda reason: denied.append(reason))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": f"paseo send {A} hi"}})))
    assert gate.main() == 0
    assert denied == [f"archived {A}"] and "boom" in capsys.readouterr().err


def test_one_decision_inspects_each_agent_once(world):
    """sr-43 e: target, successor and chain end are each read once per decision; a not-found answer is cached too."""
    write_link(world.state, world.home, A, B, status="acknowledged", acknowledged_at=stamp())
    calls = []

    def inspect(ident):
        calls.append(ident)
        if ident == C:
            raise LookupError(ident)
        return {"Id": ident, "Archived": False}
    assert guard.decide(A, inspect, state_dir=world.state, home=world.home).action == guard.REDIRECT
    assert sorted(calls) == sorted(set(calls)) and set(calls) == {A, B}


def test_a_not_found_answer_is_cached_within_one_decision(world):
    """sr-43 rv-753 B5b: a prefix target that Paseo does not know is looked up once, and still passes unguarded."""
    calls = []

    def inspect(ident):
        calls.append(ident)
        raise LookupError(ident)
    cached = guard._cached(inspect)
    for _ in range(2):
        with pytest.raises(LookupError):
            cached("nope")
    assert calls == ["nope"]
