"""claude/hooks/relay_prose_nudge.py: a relayed question or request answered only in prose gets one nudge to use relay.py."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "relay_prose_nudge.py"
HEADER = "[relay from claude w2F:p45 aka lead (djbclark-ade)] "
ASK = "can you review the plan?"
FOOTER = " [reply through relay.py to w2F:p45: ack w3A:p2]"


def user(text, uuid="u1"):
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def user_list(text, uuid="u1"):
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def queued(prompt, uuid="q1"):
    return {"type": "attachment", "uuid": uuid, "attachment": {"type": "queued_command", "prompt": prompt, "commandMode": "prompt"}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def prose():
    return assistant({"type": "text", "text": "Agreed, looks good."})


def tool(name, **inp):
    return {"type": "tool_use", "id": "t1", "name": name, "input": inp}


def result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def write(tmp_path, entries, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return p


def run(tmp_path, tx, session="s1", raw=None, state=None, **extra):
    env = dict(os.environ, RELAY_PROSE_NUDGE_STATE=str(state or tmp_path / "state"))
    env.pop("RELAY_PROSE_NUDGE_OFF", None)
    payload = raw if raw is not None else json.dumps({"session_id": session, "transcript_path": str(tx), **extra})
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0
    return json.loads(r.stdout) if r.stdout.strip() else None


_n = [0]


def nudged(tmp_path, entries):
    """The hook's output for ENTRIES as a fresh session (so no state of an earlier case is shared)."""
    _n[0] += 1
    return run(tmp_path, write(tmp_path, entries, f"c{_n[0]}.jsonl"), session=f"c{_n[0]}")


def prose_turn(text=HEADER + ASK):
    return [user(text), prose()]


def test_relayed_question_then_prose_only_nudges_with_the_sender_id_and_an_out(tmp_path):
    out = run(tmp_path, write(tmp_path, prose_turn()))
    assert out["decision"] == "block"
    assert 'You answered a relayed message in prose; the sender does not see it. Reply with relay.py w2F:p45 "<text>"' in out["reason"]
    assert "If it needs no answer, end the turn; if it asks for one, start your relay reply with `ack w2F:p45`." in out["reason"]


def test_statements_and_informal_acks_never_nudge(tmp_path):
    """The 2026-10-25 ruling: an answer is required only for a question or a request for action; no chain between two hooked agents."""
    for body in ["PR 75 merged at a61a208.", "noted, thanks", "you're welcome", "received", "ack w3A:p2",
                 "see https://example.com/a?b=1 for the log"]:
        assert nudged(tmp_path, prose_turn(HEADER + body)) is None, body


def test_relays_own_reply_and_first_contact_footers_nudge_even_without_a_question_mark(tmp_path):
    out = nudged(tmp_path, prose_turn(HEADER + "send me the reviewed SHA" + FOOTER))
    assert out["decision"] == "block" and "start your relay reply with `ack w3A:p2`" in out["reason"]
    first = HEADER + "hello, please confirm [first contact from w2F:p45: reply `ack w2F:p45` through relay.py to prove this link both ways]"
    out = nudged(tmp_path, prose_turn(first))
    assert out["decision"] == "block" and "with `ack w2F:p45`" in out["reason"]


def test_an_ack_carrying_the_first_contact_footer_is_still_an_ack(tmp_path):
    body = "ack w3A:p2 [first contact from w2F:p45: reply `ack w2F:p45` through relay.py to prove this link both ways]"
    assert nudged(tmp_path, prose_turn(HEADER + body)) is None


def test_socket_wrapper_and_queued_tag_are_read(tmp_path):
    wrapped = ('<cross-session-message from="relay.py" from-name="relay.py (claude w2F:p45 (x))" from-mode="bypass">\n'
               "[queued 3m ago] " + HEADER + "do it?\n</cross-session-message>")
    assert run(tmp_path, write(tmp_path, prose_turn(wrapped)))["decision"] == "block"


def test_a_relay_py_bash_call_in_the_turn_does_not_nudge(tmp_path):
    entries = [user(HEADER + ASK), assistant(tool("Bash", command='relay.py w2F:p45 "done"')), result(),
               assistant({"type": "text", "text": "sent"})]
    assert run(tmp_path, write(tmp_path, entries)) is None


def test_send_message_to_the_sender_does_not_nudge_but_to_another_does(tmp_path):
    ok = [user(HEADER + ASK), assistant(tool("SendMessage", to="lead", message="done"))]
    assert run(tmp_path, write(tmp_path, ok)) is None
    other = [user(HEADER + ASK), assistant(tool("SendMessage", to="someone-else", message="done"))]
    assert run(tmp_path, write(tmp_path, other, "o.jsonl"), session="s2")["decision"] == "block"


def test_relay_call_from_an_earlier_turn_does_not_excuse_this_one(tmp_path):
    entries = [user("first"), assistant(tool("Bash", command="relay.py x hi")), user(HEADER + ASK), prose()]
    assert run(tmp_path, write(tmp_path, entries))["decision"] == "block"


def test_acks_and_no_reply_texts_never_nudge(tmp_path):
    first = " [first contact from w2F:p45: reply `ack w2F:p45` through relay.py to prove this link both ways]"
    for body in ["ack w2F:p3", "Ack w2F:p3, thanks?", "FYI the build is green?", "done, what a day? no reply needed", "no-reply-required?",
                 "done, what a day? no reply needed" + first]:
        assert nudged(tmp_path, prose_turn(HEADER + body)) is None, body


def test_a_question_that_merely_mentions_ack_still_nudges(tmp_path):
    assert run(tmp_path, write(tmp_path, prose_turn(HEADER + "please send back an ack when done?")))["decision"] == "block"


@pytest.mark.parametrize("body", [
    "Ack, but can you also send the reviewed SHA?",                                                           # A4a
    "ACK? what is the status",                                                                                # A4b
    'Earlier you wrote "no reply needed", but I do need one: which SHA did you review?',                      # A4c
    "check the fyi-digest output and tell me what it says?",                                                  # A4d
    "what does FYI mean in this doc?" + FOOTER,                                                               # A4e
    "acknowledge the deploy and send me the log?",                                                            # A4f
    "please send back an ack when done?",                                                                     # A4f
    "Ack the status? and the log",
    "FYI_MODE=1, what is the result?",
])
def test_exemptions_do_not_swallow_a_real_question(tmp_path, body):
    assert nudged(tmp_path, prose_turn(HEADER + body))["decision"] == "block"


def test_the_reply_footer_overrides_a_no_reply_phrase_and_an_ack_shape(tmp_path):
    for body in ["no reply needed, but which SHA" + FOOTER, "ack w3A:p2, and which SHA" + FOOTER, "FYI: send the log" + FOOTER]:
        assert nudged(tmp_path, prose_turn(HEADER + body))["decision"] == "block", body


def test_a_queued_command_prompt_given_as_a_list_of_text_blocks_is_read(tmp_path):
    entries = [user("go"), assistant(tool("Bash", command="sleep 1")), result(),
               queued([{"type": "text", "text": HEADER + "status please?"}]), prose()]
    assert nudged(tmp_path, entries)["decision"] == "block"
    assert nudged(tmp_path, entries[:3] + [queued(HEADER + "status please?"), prose()])["decision"] == "block"


def test_a_task_notification_does_not_start_a_new_turn(tmp_path):
    entries = [user_list(HEADER + ASK), assistant(tool("Bash", command="sleep 60 &")), result(),
               user("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"), prose()]
    assert nudged(tmp_path, entries)["decision"] == "block"
    # ... and a relay.py answer made before the notification still excuses the turn
    answered = [user_list(HEADER + ASK), assistant(tool("Bash", command='relay.py w2F:p45 "done"')), result(),
                user("<task-notification>done</task-notification>"), prose()]
    assert nudged(tmp_path, answered) is None


def test_no_relay_header_never_nudges(tmp_path):
    for text in ["hello there?", "see [relay from claude w2F:p45 (x)] quoted mid-text?", "[relay from load-watch] disk low?"]:
        assert nudged(tmp_path, prose_turn(text)) is None, text


@pytest.mark.parametrize("header", [
    "[relay from load watch] ",                           # A6a: a declared label with a space
    "[relay from Dann 5 (lead, techno-euphora)] ",        # A6b: an older hand-typed label
    '[relay from claude x";touch${IFS}/tmp/pwn;" (d)] ',  # A7a: shell characters in the id
    "[relay from claude lead$(id) (d)] ",
])
def test_a_header_without_a_usable_id_never_nudges_a_bogus_target(tmp_path, header):
    assert nudged(tmp_path, prose_turn(header + "what is the status?")) is None


@pytest.mark.parametrize("header,target", [
    ("[relay from claude w2F:p45 (djbclark-ade)] ", "w2F:p45"),
    ("[relay from claude 4f3a9c1e (djbclark-ade)] ", "4f3a9c1e"),
    ("[relay from codex 019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8] ", "019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8"),
    ("[relay from hermes 4f3a9c1e] ", "4f3a9c1e"),
    ("[relay from claude lead (djbclark-ade)] ", "lead"),
])
def test_real_header_shapes_name_their_target(tmp_path, header, target):
    out = nudged(tmp_path, prose_turn(header + "what is the status?"))
    assert f'Reply with relay.py {target} "<text>"' in out["reason"]


def test_second_stop_for_the_same_turn_does_not_nudge_twice(tmp_path):
    tx = write(tmp_path, prose_turn())
    assert run(tmp_path, tx)["decision"] == "block"
    assert run(tmp_path, tx) is None
    # a new relayed message in the same session is a new turn and is nudged again
    tx2 = write(tmp_path, prose_turn() + [user(HEADER + "another?", "u2"), assistant({"type": "text", "text": "prose again"})], "t2.jsonl")
    assert run(tmp_path, tx2)["decision"] == "block"


def test_a_nudge_that_cannot_be_recorded_is_never_printed(tmp_path):
    """An unwritable state directory must not make the nudge repeat on every Stop."""
    (tmp_path / "blocker").write_text("a file where the state directory should be")
    state = tmp_path / "blocker" / "state"
    tx = write(tmp_path, prose_turn())
    assert run(tmp_path, tx, state=state) is None
    assert run(tmp_path, tx, state=state) is None


def test_stop_hook_active_never_nudges(tmp_path):
    assert run(tmp_path, write(tmp_path, prose_turn()), stop_hook_active=True) is None


def test_garbage_input_fails_open(tmp_path):
    missing = tmp_path / "none.jsonl"
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe not json\n{\"type\": \n[1,2]\n\x00\x00")
    assert run(tmp_path, bad) is None
    assert run(tmp_path, missing) is None
    for raw in ["", "not json", "[]", "null", '{"transcript_path": 5}', '{"transcript_path": "' + str(bad) + '"}']:
        assert run(tmp_path, bad, raw=raw) is None, raw


def test_only_the_transcript_tail_is_read(tmp_path):
    big = [user(HEADER + "start of a very long turn?")] + [assistant({"type": "text", "text": "x" * 4000})] * 120
    assert run(tmp_path, write(tmp_path, big)) is None    # the turn's start is beyond the 256 KB tail: not seen, not nudged
    small = [user(HEADER + "short?")] + [assistant({"type": "text", "text": "x" * 4000})] * 20
    assert run(tmp_path, write(tmp_path, small, "s.jsonl"), session="s9")["decision"] == "block"
