"""claude/hooks/relay_prose_nudge.py: a relayed message answered only in prose gets one nudge to use relay.py."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "relay_prose_nudge.py"
HEADER = "[relay from claude w2F:p45 aka lead (djbclark-ade)] "


def user(text, uuid="u1"):
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def tool(name, **inp):
    return {"type": "tool_use", "id": "t1", "name": name, "input": inp}


def result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def write(tmp_path, entries, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return p


def run(tmp_path, tx, session="s1", raw=None, **extra):
    env = dict(os.environ, RELAY_PROSE_NUDGE_STATE=str(tmp_path / "state"))
    env.pop("RELAY_PROSE_NUDGE_OFF", None)
    payload = raw if raw is not None else json.dumps({"session_id": session, "transcript_path": str(tx), **extra})
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0
    return json.loads(r.stdout) if r.stdout.strip() else None


def prose_turn(text=HEADER + "please review the plan"):
    return [user(text), assistant({"type": "text", "text": "Agreed, looks good."})]


def test_relayed_then_prose_only_nudges_with_the_sender_id(tmp_path):
    out = run(tmp_path, write(tmp_path, prose_turn()))
    assert out["decision"] == "block"
    assert 'You answered a relayed message in prose; the sender does not see it. Reply with relay.py w2F:p45 "<text>"' in out["reason"]


def test_socket_wrapper_and_queued_tag_are_read(tmp_path):
    wrapped = ('<cross-session-message from="relay.py" from-name="relay.py (claude w2F:p45 (x))" from-mode="bypass">\n'
               "[queued 3m ago] " + HEADER + "do it\n</cross-session-message>")
    assert run(tmp_path, write(tmp_path, prose_turn(wrapped)))["decision"] == "block"


def test_a_relay_py_bash_call_in_the_turn_does_not_nudge(tmp_path):
    entries = [user(HEADER + "please review"), assistant(tool("Bash", command='relay.py w2F:p45 "done"')), result(),
               assistant({"type": "text", "text": "sent"})]
    assert run(tmp_path, write(tmp_path, entries)) is None


def test_send_message_to_the_sender_does_not_nudge_but_to_another_does(tmp_path):
    ok = [user(HEADER + "please review"), assistant(tool("SendMessage", to="lead", message="done"))]
    assert run(tmp_path, write(tmp_path, ok)) is None
    other = [user(HEADER + "please review"), assistant(tool("SendMessage", to="someone-else", message="done"))]
    assert run(tmp_path, write(tmp_path, other, "o.jsonl"), session="s2")["decision"] == "block"


def test_relay_call_from_an_earlier_turn_does_not_excuse_this_one(tmp_path):
    entries = [user("first"), assistant(tool("Bash", command="relay.py x hi")), user(HEADER + "now this"),
               assistant({"type": "text", "text": "prose"})]
    assert run(tmp_path, write(tmp_path, entries))["decision"] == "block"


def test_acks_and_no_reply_texts_never_nudge(tmp_path):
    for i, body in enumerate(["ack w2F:p3", "Ack: build-7", "FYI the build is green", "done. no reply needed", "no-reply-required"]):
        assert run(tmp_path, write(tmp_path, prose_turn(HEADER + body), f"a{i}.jsonl"), session=f"a{i}") is None, body


def test_a_question_that_merely_mentions_ack_still_nudges(tmp_path):
    assert run(tmp_path, write(tmp_path, prose_turn(HEADER + "please send back an ack when done")))["decision"] == "block"


def test_no_relay_header_never_nudges(tmp_path):
    for i, text in enumerate(["hello there", "see [relay from claude w2F:p45 (x)] quoted mid-text", "[relay from load-watch] disk low"]):
        assert run(tmp_path, write(tmp_path, prose_turn(text), f"n{i}.jsonl"), session=f"n{i}") is None, text


def test_second_stop_for_the_same_turn_does_not_nudge_twice(tmp_path):
    tx = write(tmp_path, prose_turn())
    assert run(tmp_path, tx)["decision"] == "block"
    assert run(tmp_path, tx) is None
    # a new relayed message in the same session is a new turn and is nudged again
    tx2 = write(tmp_path, prose_turn() + [user(HEADER + "another", "u2"), assistant({"type": "text", "text": "prose again"})], "t2.jsonl")
    assert run(tmp_path, tx2)["decision"] == "block"


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
    big = [user(HEADER + "start of a very long turn")] + [assistant({"type": "text", "text": "x" * 4000})] * 120
    assert run(tmp_path, write(tmp_path, big)) is None    # the turn's start is beyond the 256 KB tail: not seen, not nudged
    small = [user(HEADER + "short")] + [assistant({"type": "text", "text": "x" * 4000})] * 20
    assert run(tmp_path, write(tmp_path, small, "s.jsonl"), session="s9")["decision"] == "block"
