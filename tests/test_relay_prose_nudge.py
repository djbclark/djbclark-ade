"""claude/hooks/relay_prose_nudge.py: a relayed question or request answered only in prose gets one nudge to use relay.py."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "relay_prose_nudge.py"
HEADER = "[relay from claude w2F:p45 aka lead (djbclark-ade)] "
HERMES = "[relay from hermes 4f3a9c1e] "    # a sender with no sender row: no `(DIR)`, no footer on a `?` text
ASK = "can you review the plan?"
FOOTER = " [reply through relay.py to w2F:p45: ack q1]"
FIRST = " [first contact from w2F:p45: reply `ack w2F:p45` through relay.py to prove this link both ways]"


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


def prose_turn(text=HEADER + ASK + FOOTER):
    return [user(text), prose()]


def test_relayed_question_with_the_reply_footer_then_prose_only_nudges_with_the_sender_id_and_an_out(tmp_path):
    out = run(tmp_path, write(tmp_path, prose_turn()))
    assert out["decision"] == "block"
    assert 'You answered a relayed message in prose; the sender does not see it. Reply with relay.py w2F:p45 "<text>"' in out["reason"]
    assert "If it needs no answer, end the turn; if it asks for one, start your relay reply with `ack q1`." in out["reason"]


def test_a_question_mark_from_a_sender_with_no_dir_nudges_with_the_header_id(tmp_path):
    """R2d2: a sender with no sender row (a Hermes-started relay) has no `(DIR)` and no footer; its `?` is the only signal."""
    out = nudged(tmp_path, prose_turn(HERMES + ASK))
    assert 'Reply with relay.py 4f3a9c1e "<text>"' in out["reason"] and "with `ack 4f3a9c1e`." in out["reason"]
    assert nudged(tmp_path, prose_turn(HERMES + "did anyone else see the load spike? no reply needed")) is None    # exempt phrase wins


@pytest.mark.parametrize("body", [
    "did anyone else see the load spike?",                                            # R2d1: a `--fyi` question from a sender with a row
    "did anyone else see the load spike? something else",
    "merged; ran `rg -n 'foo?' bin/` and it is clean.\n```\nre.compile(r'a?b')\n```",    # R2d3: `?` in a code span and a fence
    "re your 'which SHA did you review?': 3a24fdc.",                                  # R2d4: a quoted earlier question
])
def test_a_question_mark_alone_from_a_sender_with_a_dir_is_a_fyi_text_and_stays_silent(tmp_path, body):
    assert nudged(tmp_path, prose_turn(HEADER + body)) is None
    assert nudged(tmp_path, prose_turn(HEADER + body + FIRST))["decision"] == "block"    # the footer, not the `?`, asks for the answer


def test_the_same_fyi_question_nudges_only_without_a_dir(tmp_path):
    body = "did anyone else see the load spike?"
    assert nudged(tmp_path, prose_turn(HEADER + body)) is None
    assert nudged(tmp_path, prose_turn(HERMES + body))["decision"] == "block"


def test_statements_and_informal_acks_never_nudge(tmp_path):
    """The 2026-10-25 ruling: an answer is required only for a question or a request for action; no chain between two hooked agents."""
    for body in ["PR 75 merged at a61a208.", "noted, thanks", "you're welcome", "received", "ack w3A:p2",
                 "see https://example.com/a?b=1 for the log"]:
        for header in (HEADER, HERMES):
            assert nudged(tmp_path, prose_turn(header + body)) is None, body


def test_relays_own_reply_and_first_contact_footers_nudge_even_without_a_question_mark(tmp_path):
    out = nudged(tmp_path, prose_turn(HEADER + "send me the reviewed SHA" + FOOTER))
    assert out["decision"] == "block" and "start your relay reply with `ack q1`" in out["reason"]
    out = nudged(tmp_path, prose_turn(HEADER + "hello, please confirm" + FIRST))
    assert out["decision"] == "block" and "with `ack w2F:p45`" in out["reason"]
    out = nudged(tmp_path, prose_turn(HEADER + "send the log" + FOOTER + "  \n"))    # trailing whitespace after the footer is fine
    assert "with `ack q1`" in out["reason"]


def test_an_ack_carrying_the_first_contact_footer_is_still_an_ack(tmp_path):
    assert nudged(tmp_path, prose_turn(HEADER + "ack w3A:p2" + FIRST)) is None


@pytest.mark.parametrize("ack", [
    "ack q1: 3a24fdc.",         # R1: the shapes a model writes when an ack carries the answer
    "ack q1 - 3a24fdc",
    "ack q1 — 3a24fdc",
    "ack q1.",
    "ack q1!",
    "ack q1, 3a24fdc",
    "ack w3A:p2",
    "ack w3A:p2: p2 reviewed 3a24fdc",
    "Ack q1;",
    "ack q1 [done]",
    "ack q1: is that the SHA you meant?",    # a `?` defeats the bare-space rule: only the ACK regex exempts these
    "ack q1 - 3a24fdc, ok?",
    "ack q1 — 3a24fdc, ok?",
    "ack q1! anything else?",
])
def test_an_ack_that_carries_an_answer_is_silent_with_and_without_the_first_contact_footer(tmp_path, ack):
    for header in (HEADER, HERMES):
        for footer in ("", FIRST):
            assert nudged(tmp_path, prose_turn(header + ack + footer)) is None, (header, ack, footer)


@pytest.mark.parametrize("body", ["ack q1 3a24fdc", "ack q1 reviewed 3a24fdc, fine", "ack the status please"])
def test_a_bare_space_ack_is_exempt_on_first_contact_only_without_a_question_mark(tmp_path, body):
    assert nudged(tmp_path, prose_turn(HEADER + body + FIRST)) is None


def test_a_bare_space_ack_with_a_question_mark_is_a_question_on_first_contact(tmp_path):
    for body in ["Ack the status? and the log", "ack the status, what is the SHA? ok"]:
        out = nudged(tmp_path, prose_turn(HEADER + body + FIRST))
        assert out["decision"] == "block", body
    assert nudged(tmp_path, prose_turn(HEADER + "ack q1 see https://example.com/a?b=1" + FIRST)) is None    # a URL's `?` is none


def test_socket_wrapper_and_queued_tag_are_read(tmp_path):
    wrapped = ('<cross-session-message from="relay.py" from-name="relay.py (claude w2F:p45 (x))" from-mode="bypass">\n'
               "[queued 3m ago] " + HEADER + "do it?" + FOOTER + "\n</cross-session-message>")
    assert run(tmp_path, write(tmp_path, prose_turn(wrapped)))["decision"] == "block"
    first = wrapped.replace(FOOTER, FIRST)
    assert nudged(tmp_path, prose_turn(first))["decision"] == "block"
    assert nudged(tmp_path, prose_turn(first.replace("do it?", "ack w3A:p2"))) is None


def test_a_relay_py_bash_call_in_the_turn_does_not_nudge(tmp_path):
    entries = [user(HEADER + ASK + FOOTER), assistant(tool("Bash", command='relay.py w2F:p45 "done"')), result(),
               assistant({"type": "text", "text": "sent"})]
    assert run(tmp_path, write(tmp_path, entries)) is None


def test_send_message_to_the_sender_does_not_nudge_but_to_another_does(tmp_path):
    ok = [user(HEADER + ASK + FOOTER), assistant(tool("SendMessage", to="lead", message="done"))]
    assert run(tmp_path, write(tmp_path, ok)) is None
    other = [user(HEADER + ASK + FOOTER), assistant(tool("SendMessage", to="someone-else", message="done"))]
    assert run(tmp_path, write(tmp_path, other, "o.jsonl"), session="s2")["decision"] == "block"


def test_relay_call_from_an_earlier_turn_does_not_excuse_this_one(tmp_path):
    entries = [user("first"), assistant(tool("Bash", command="relay.py x hi")), user(HEADER + ASK + FOOTER), prose()]
    assert run(tmp_path, write(tmp_path, entries))["decision"] == "block"


def test_acks_and_no_reply_texts_never_nudge(tmp_path):
    for body in ["ack w2F:p3", "Ack w2F:p3, thanks?", "FYI the build is green?", "done, what a day? no reply needed", "no-reply-required?"]:
        assert nudged(tmp_path, prose_turn(HERMES + body)) is None, body    # `?` would nudge here: the exemptions are what silence it
    for body in ["done, what a day? no reply needed", "FYI the build is green"]:
        assert nudged(tmp_path, prose_turn(HEADER + body + FIRST)) is None, body


def test_a_question_that_merely_mentions_ack_still_nudges(tmp_path):
    assert nudged(tmp_path, prose_turn(HERMES + "please send back an ack when done?"))["decision"] == "block"


@pytest.mark.parametrize("body", [
    "Ack, but can you also send the reviewed SHA?",                                                           # A4a
    "ACK? what is the status",                                                                                # A4b
    'Earlier you wrote "no reply needed", but I do need one: which SHA did you review?',                      # A4c
    "check the fyi-digest output and tell me what it says?",                                                  # A4d
    "acknowledge the deploy and send me the log?",                                                            # A4f
    "please send back an ack when done?",                                                                     # A4f
    "Ack the status? and the log",
    "ack, but which SHA?",
    "FYI_MODE=1, what is the result?",
])
def test_exemptions_do_not_swallow_a_real_question(tmp_path, body):
    assert nudged(tmp_path, prose_turn(HERMES + body))["decision"] == "block"


def test_the_reply_footer_overrides_a_no_reply_phrase_and_an_ack_shape(tmp_path):
    for body in ["no reply needed, but which SHA" + FOOTER, "ack w3A:p2, and which SHA" + FOOTER, "FYI: send the log" + FOOTER,
                 "what does FYI mean in this doc?" + FOOTER]:
        assert nudged(tmp_path, prose_turn(HEADER + body))["decision"] == "block", body


@pytest.mark.parametrize("body", [
    "ack q1, re your msg 'which SHA?[reply through relay.py to w2F:p45: ack q1]' -> 3a24fdc",     # R4a
    "done. (your earlier text ended [reply through relay.py to w2F:p45: ack q1])",                  # R4b
    "[reply through relay.py to w2F:p45: ack q9] tail text",                                        # R4c
    "[first contact from w2F:p45: reply `ack w2F:p45` through relay.py to prove] thanks",           # R4c
    "quoted: [first contact from w2F:p45: reply `ack w2F:p45` through relay.py x] and then done",
])
def test_a_footer_that_is_not_at_the_end_is_a_quote_and_decides_nothing(tmp_path, body):
    assert nudged(tmp_path, prose_turn(HEADER + body)) is None


def test_only_the_footer_at_the_end_names_the_token(tmp_path):
    body = "a quoted [reply through relay.py to w2F:p45: ack old1] and a real ask" + FOOTER
    assert "with `ack q1`" in nudged(tmp_path, prose_turn(HEADER + body))["reason"]


@pytest.mark.parametrize("footer", [
    " [reply through relay.py to w2F:p45: ack $(touch${IFS}/tmp/pwn)`;]",         # R6a: shell characters in the token
    " [reply through relay.py to w2F:p45: ack " + "t" * 41 + "]",               # longer than relay's EXPECT_ID
    " [reply through relay.py to w2F:p45: ack .hidden]",                         # EXPECT_ID starts with a letter or digit
    " [reply through relay.py to w2F p45: ack q1]",                              # a route with a space
    " [reply through relay.py to $(touch${IFS}/tmp/pwn): ack q1]",                # shell characters in the route
    " [first contact from $(touch${IFS}/tmp/pwn): reply `ack $(id)` through relay.py to prove this link both ways]",
    " [reply through relay.py to w2F:p45: ack q1 q2]",
])
def test_a_footer_whose_token_does_not_fit_relays_charset_is_no_footer(tmp_path, footer):
    assert nudged(tmp_path, prose_turn(HEADER + "send the log" + footer)) is None


def test_a_footer_token_at_relays_limit_is_used(tmp_path):
    tok = "a" + "b.c_d-" * 6 + "e" * 3    # 40 characters
    assert len(tok) == 40
    out = nudged(tmp_path, prose_turn(HEADER + "send the log" + f" [reply through relay.py to w2F:p45: ack {tok}]"))
    assert f"with `ack {tok}`" in out["reason"]


def test_a_queued_command_prompt_given_as_a_list_of_text_blocks_is_read(tmp_path):
    entries = [user("go"), assistant(tool("Bash", command="sleep 1")), result(),
               queued([{"type": "text", "text": HEADER + "status please?" + FOOTER}]), prose()]
    assert nudged(tmp_path, entries)["decision"] == "block"
    assert nudged(tmp_path, entries[:3] + [queued(HEADER + "status please?" + FOOTER), prose()])["decision"] == "block"


def test_a_task_notification_does_not_start_a_new_turn(tmp_path):
    entries = [user_list(HEADER + ASK + FOOTER), assistant(tool("Bash", command="sleep 60 &")), result(),
               user("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"), prose()]
    assert nudged(tmp_path, entries)["decision"] == "block"
    # ... and a relay.py answer made before the notification still excuses the turn
    answered = [user_list(HEADER + ASK + FOOTER), assistant(tool("Bash", command='relay.py w2F:p45 "done"')), result(),
                user("<task-notification>done</task-notification>"), prose()]
    assert nudged(tmp_path, answered) is None


def test_no_relay_header_never_nudges(tmp_path):
    for text in ["hello there?", "see [relay from claude w2F:p45 (x)] quoted mid-text?", "[relay from load-watch] disk low?",
                 "hello?" + FOOTER]:
        assert nudged(tmp_path, prose_turn(text)) is None, text


@pytest.mark.parametrize("header", [
    "[relay from load watch] ",                           # A6a: a declared label with a space
    "[relay from Dann 5 (lead, techno-euphora)] ",        # A6b: an older hand-typed label
    '[relay from claude x";touch${IFS}/tmp/pwn;" (d)] ',  # A7a: shell characters in the id
    "[relay from claude lead$(id) (d)] ",
])
def test_a_header_without_a_usable_id_never_nudges_a_bogus_target(tmp_path, header):
    assert nudged(tmp_path, prose_turn(header + "what is the status?" + FOOTER)) is None


@pytest.mark.parametrize("header,target", [
    ("[relay from claude w2F:p45 (djbclark-ade)] ", "w2F:p45"),
    ("[relay from claude 4f3a9c1e (djbclark-ade)] ", "4f3a9c1e"),
    ("[relay from codex 019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8] ", "019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8"),
    ("[relay from hermes 4f3a9c1e] ", "4f3a9c1e"),
    ("[relay from claude lead (djbclark-ade)] ", "lead"),
])
def test_real_header_shapes_name_their_target(tmp_path, header, target):
    out = nudged(tmp_path, prose_turn(header + "what is the status?" + FOOTER))
    assert f'Reply with relay.py {target} "<text>"' in out["reason"]


def test_a_clipped_long_name_and_dir_still_parse(tmp_path):
    """R3: relay's sender_label clips a long name with fleet.clip, which prefixes `…` (U+2026)."""
    header = f"[relay from claude w2F:p45 aka …{'x' * 39} (…{'d' * 47})] "
    out = nudged(tmp_path, prose_turn(header + "what is the status?" + FOOTER))
    assert 'Reply with relay.py w2F:p45 "<text>"' in out["reason"]
    assert nudged(tmp_path, prose_turn(header.replace(" (…" + "d" * 47 + ")", "") + "what is the status?" + FOOTER))["decision"] == "block"


def test_the_id_charset_stays_strict_where_the_ellipsis_is_allowed_elsewhere(tmp_path):
    assert nudged(tmp_path, prose_turn("[relay from claude …w2F:p45 (d)] " + ASK + FOOTER)) is None


def test_second_stop_for_the_same_turn_does_not_nudge_twice(tmp_path):
    tx = write(tmp_path, prose_turn())
    assert run(tmp_path, tx)["decision"] == "block"
    assert run(tmp_path, tx) is None
    # a new relayed message in the same session is a new turn and is nudged again
    tx2 = write(tmp_path, prose_turn() + [user(HEADER + "another?" + FOOTER, "u2"), assistant({"type": "text", "text": "prose again"})], "t2.jsonl")
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
    big = [user(HEADER + "start of a very long turn?" + FOOTER)] + [assistant({"type": "text", "text": "x" * 4000})] * 120
    assert run(tmp_path, write(tmp_path, big)) is None    # the turn's start is beyond the 256 KB tail: not seen, not nudged
    small = [user(HEADER + "short?" + FOOTER)] + [assistant({"type": "text", "text": "x" * 4000})] * 20
    assert run(tmp_path, write(tmp_path, small, "s.jsonl"), session="s9")["decision"] == "block"


_TIMING = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("hook", sys.argv[1]); hook = importlib.util.module_from_spec(spec); spec.loader.exec_module(hook)
bodies = {
    "whitespace": " " * 250_000 + "x",
    "first-contact openers": "[first contact from " * 4_000,
    "reply-footer openers": "[reply through relay.py to " * 4_000,
    "plain 250 KB": "word " * 50_000,
    "ack token": "ack " + "x" * 250_000 + "?",
    "tail whitespace after a footer opener": "[first contact from " + " " * 250_000,
}
out = {}
for name, body in bodies.items():
    t = time.perf_counter()
    for has_dir in (True, False):
        hook.reply_token(body, "w2F:p45", has_dir)
    out[name] = time.perf_counter() - t
print(json.dumps(out))
"""


def test_hostile_bodies_are_read_in_linear_time():
    """R5: the 2 s hook deadline; a quadratic regex on 250 KB of whitespace did not finish in 300 s. Run in a child so a regression fails at 20 s."""
    r = subprocess.run([sys.executable, "-c", _TIMING, str(HOOK)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    for name, secs in json.loads(r.stdout).items():
        assert secs < 1.0, (name, secs)


# --- two hooked agents answering each other (R1): a fake relay appends footers the way skills/session-finder/relay.py main() does ---

AGENT_HEADER = {"A": "[relay from claude w2F:p45 aka lead (djbclark-ade)] ", "B": "[relay from codex w3A:p2 (other-wt)] "}
AGENT_ID = {"A": "w2F:p45", "B": "w3A:p2"}
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)


def replay(tmp_path, name, first, policy, first_expect=None, first_fyi=False, linked=False, limit=6):
    """Deliveries made (the first message included) before a receiver is not nudged; `policy(token)` is the receiver's relay reply
    text, sent after the hook nudged it (a receiver always answers in prose first, the worst case)."""
    links, sent = ({("A", "B")} if linked else set()), []

    def send(src, dst, text, expect=None, fyi=False):
        assert fyi or expect or "?" not in URL.sub(" ", text), f"relay refuses {text!r}: a `?` needs --expect-ack or --fyi"
        if expect:
            text += f" [reply through relay.py to {AGENT_ID[src]}: ack {expect}]"
        elif (src, dst) not in links:
            text += f" [first contact from {AGENT_ID[src]}: reply `ack {AGENT_ID[src]}` through relay.py to prove this link both ways]"
        links.add((src, dst))
        sent.append(text)
        return text

    src, dst = "A", "B"
    text = send(src, dst, first, first_expect, first_fyi)
    for turn in range(limit):
        entries = [user_list(AGENT_HEADER[src] + text, uuid=f"{name}-{turn}"), assistant({"type": "text", "text": "prose answer"})]
        out = run(tmp_path, write(tmp_path, entries, f"{name}-{turn}.jsonl"), session=f"{name}-{dst}-{turn}")
        if not out:
            return sent
        token = re.search(r"start your relay reply with `ack ([^`]*)`", out["reason"]).group(1)
        text = send(dst, src, policy(token))
        src, dst = dst, src
    pytest.fail(f"{name}: no end after {limit} deliveries: {sent}")


@pytest.mark.parametrize("answer", [
    "ack {t}",                      # P1
    "ack {t}: 3a24fdc.",            # P2
    "ack {t} - 3a24fdc",
    "ack {t} — 3a24fdc",
    "ack {t}.",
    "ack {t} 3a24fdc",              # P2b: a bare space
    "ack {t}, reviewed 3a24fdc",
])
def test_an_ack_that_answers_a_question_ends_the_exchange_with_no_ack_of_an_ack(tmp_path, answer):
    sent = replay(tmp_path, "q", "which SHA did you review?", lambda t: answer.format(t=t), first_expect="q1")
    assert len(sent) == 2, sent    # the question and the ack: the first answer on a new link (first-contact footer) provokes nothing


def test_a_fyi_question_on_an_established_link_from_a_sender_with_a_row_provokes_nothing(tmp_path):
    """F1: on a new link relay appends the first-contact footer to every first text, `--fyi` or not, and that footer asks for the ack."""
    sent = replay(tmp_path, "f", "did you see the load spike?", lambda t: f"ack {t}", first_fyi=True, linked=True)
    assert len(sent) == 1, sent


def test_a_statement_then_prose_acks_still_end(tmp_path):
    """S1, S2, P3: a statement on a first contact is nudged once (decided); the exchange still ends, each side at most once."""
    for name, first, policy in [("s1", "PR 75 merged at 3a24fdc.", lambda t: f"ack {t}"),
                                ("s2", "PR 75 merged at 3a24fdc.", lambda t: "thanks, noted"),
                                ("p3", "which SHA did you review?", lambda t: f"thanks, noted ({t})")]:
        sent = replay(tmp_path, name, first, policy, first_expect="q1" if name == "p3" else None)
        assert len(sent) <= 3, (name, sent)
