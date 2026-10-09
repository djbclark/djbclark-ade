"""Unit tests for bin/herdr-ai: index building, validation, confirm policy, plan
rendering, the socket payload, model-reply parsing and fallback. No Herdr, no network."""

from __future__ import annotations

import http.client
import importlib.machinery
import importlib.util
import json
import os
import socket
import stat
import sys
import threading
import time
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "herdr-ai"
_loader = importlib.machinery.SourceFileLoader("herdr_ai", str(SCRIPT))
ai = importlib.util.module_from_spec(importlib.util.spec_from_loader("herdr_ai", _loader))
_loader.exec_module(ai)


def snapshot(n_panes=3):
    panes, tabs = [], []
    for i in range(1, n_panes + 1):
        panes.append({
            "pane_id": f"w2A:p{i}", "tab_id": f"w2A:t{i}", "workspace_id": "w2A", "label": f"proj{i}-p",
            "cwd": f"/Users/me/src/proj{i}", "agent": "claude" if i % 2 else None,
            "agent_status": "idle", "focused": i == 1, "terminal_title_stripped": f"Title {i}",
        })
        tabs.append({"tab_id": f"w2A:t{i}", "workspace_id": "w2A", "label": f"proj{i}-t", "number": i,
                     "agent_status": "idle"})
    agents = [{"pane_id": "w2A:p1", "name": "alpha", "agent": "claude"},
              {"pane_id": "w2A:p3", "name": "gamma", "agent": "claude"}][: min(2, n_panes)]
    return {"workspaces": [{"workspace_id": "w2A", "label": "ade"}, {"workspace_id": "w22", "label": "hermes"}],
            "tabs": tabs, "panes": panes, "agents": agents,
            "focused_workspace_id": "w2A", "focused_tab_id": "w2A:t1", "focused_pane_id": "w2A:p1"}


@pytest.fixture
def state():
    return ai.digest_snapshot(snapshot(), env={})


@pytest.fixture
def ctx(state):
    return ai.make_ctx(state, [{"name": "napper", "pane": "w2A:p2"}, {"name": "ghost", "pane": "w9:p9"}])


# ------------------------------------------------------------------ index


def test_digest_uses_focused_ids_without_env_and_active_env_when_set():
    snap = snapshot()
    assert ai.digest_snapshot(snap, env={})["active"] == {
        "workspace": "w2A", "tab": "w2A:t1", "pane": "w2A:p1", "cwd": "/Users/me/src/proj1"}
    env = {"HERDR_ACTIVE_WORKSPACE_ID": "w22", "HERDR_ACTIVE_TAB_ID": "w22:t9",
           "HERDR_ACTIVE_PANE_ID": "w22:p9", "HERDR_ACTIVE_PANE_CWD": "/tmp/x",
           "HERDR_PANE_ID": "w2A:p3"}  # never used as the anchor
    assert ai.digest_snapshot(snap, env=env)["active"] == {
        "workspace": "w22", "tab": "w22:t9", "pane": "w22:p9", "cwd": "/tmp/x"}


def test_render_index_marks_active_joins_fleet_and_filters_sleepers(state):
    fleet = {"w2A:p1": {"title": "Fix the thing", "name": "alpha"}}
    sleepers = [{"name": "napper", "pane": "w2A:p2", "label": "Old work"},
                {"name": "ghost", "pane": "w9:p9", "label": "gone"}]
    handoffs = [{"project": "proj1", "chains": ["c1"], "updated": "2026-10-08T10:00:00-0400",
                 "heading": "", "topic": "topic-slug", "active": "doing X", "panes": ["w2A:p1"]}]
    texts = {"w2A:p1": ["building index", "tests green"]}
    out = ai.render_index(state, fleet, handoffs, sleepers, texts, 10000)
    assert 'W w2A "ade" *active*' in out
    assert 'T w2A:t1 #1 "proj1-t" idle *active*' in out
    p1 = next(ln for ln in out.splitlines() if ln.startswith("  P w2A:p1"))
    assert "claude/alpha" in p1 and 'title="Fix the thing"' in p1 and "*active*" in p1
    assert "src/proj1" in p1
    assert "   | tests green" in out
    assert 'Z napper w2A:p2 "Old work"' in out and "ghost" not in out
    assert "H proj1 chain=c1 upd=2026-10-08 panes=w2A:p1 :: topic-slug | doing X" in out


def test_index_budget_sheds_pane_text_before_handoffs():
    st = ai.digest_snapshot(snapshot(20), env={})
    texts = {p["id"]: [f"line {n} of {p['id']} " + "x" * 90 for n in range(6)] for p in st["panes"]}
    handoffs = [{"project": f"proj{i}", "chains": ["c"], "updated": "2026-10-08", "heading": "H",
                 "topic": "", "active": "a", "panes": ["w2A:p1"]} for i in range(1, 6)]
    full = ai.render_index(st, {}, handoffs, [], texts, 10**6)
    no_text = ai.render_index(st, {}, handoffs, [], {}, 10**6)
    budget = (len(full) + len(no_text)) // 2
    mid = ai.render_index(st, {}, handoffs, [], texts, budget)
    assert len(mid) <= budget
    assert mid.count("\nH ") == 5  # all handoffs survive while text is shed
    assert "line 0 of w2A:p1" in mid  # the active pane keeps its text longest
    assert "line 0 of w2A:p20" not in mid  # the tail panes lose theirs first
    tiny = ai.render_index(st, {}, handoffs, [], texts, len(no_text) - 200)
    assert tiny.count("\nH ") < 5 and "   | " not in tiny


def test_read_handoffs_maps_projects_to_panes_and_orders_by_recency(tmp_path):
    def pointer(project, updated, redirect=None, chain="c-" ):
        d = tmp_path / project / "main"
        d.mkdir(parents=True)
        body = f"---\nschema_version: 2\nupdated_at: {updated}\nchain:\n- {chain}{project}\n"
        if redirect:
            body += f"redirect: {redirect}\n"
        (d / "SESSION_LOG.md").write_text(body + "---\n\npointer\n")
    pointer("Proj1", "2026-10-01T10:00:00-0400", "chains/one/SESSION_LOG.md")
    pointer("proj2", "2026-10-07T10:00:00-0400")
    pointer("unmatched", "2026-10-08T10:00:00-0400")
    (tmp_path / "chains" / "one").mkdir(parents=True)
    (tmp_path / "chains" / "one" / "SESSION_LOG.md").write_text(
        "---\nlatest_handoff: none\n---\n# Gesture work\n- Active work: swipe thresholds\n")
    panes = ai.digest_snapshot(snapshot(), env={})["panes"]
    got = ai.read_handoffs(panes, root=tmp_path)
    assert [h["project"] for h in got] == ["proj2", "Proj1"]  # unmatched dropped, newest first
    one = got[1]
    assert one["heading"] == "Gesture work" and one["active"] == "swipe thresholds"
    assert one["topic"] == "" and one["panes"] == ["w2A:p1"] and one["chains"] == ["c-Proj1"]
    assert len(ai.read_handoffs(panes, root=tmp_path, limit=1)) == 1


def test_parse_sleepers_and_pane_text_cleaning(monkeypatch):
    rows = ai.parse_sleepers(
        "a                    w1:p1    claude    asleep          slept 2026-10-08T21:28:22  Some Title\n"
        "no match here\n")
    assert rows == [{"name": "a", "pane": "w1:p1", "kind": "claude", "state": "asleep",
                     "at": "2026-10-08T21:28:22", "label": "Some Title"}]
    raw = "\x1b[31mred\x1b[0m text\n────────\n│ boxed │\n\n❯\nlast one\x07\n"
    monkeypatch.setattr(ai, "run", lambda argv, timeout: types.SimpleNamespace(returncode=0, stdout=raw, stderr=""))
    assert ai.read_pane_text("w1:p1") == ["red text", "boxed", "last one"]
    assert ai.clean("x" * 200, 120).endswith("…") and len(ai.clean("x" * 200, 120)) == 120


def test_read_pane_texts_skips_failures_and_slow_panes():
    def reader(pid, timeout):
        if pid == "bad":
            raise RuntimeError("boom")
        return [f"text {pid}"]
    got = ai.read_pane_texts(["a", "bad", "b"], reader=reader)
    assert got == {"a": ["text a"], "b": ["text b"]}


# -------------------------------------------------------------- validation


def test_validate_normalises_ids_and_accepts_the_verbs(ctx):
    cmds, confirm = ai.validate([["tab", "focus", "w2a:t2"], ["pane", "focus-id", "w2A:p3"],
                                 ["tab", "rename", "w2A:t1", "two", "words"],
                                 ["tab", "create", "--workspace", "w22", "--cwd", "/tmp", "--label", "scratch"],
                                 ["pane", "split", "w2A:p1", "--direction", "right"],
                                 ["pane", "resize", "--pane", "w2A:p1", "--direction", "left", "--amount", 0.1]], ctx)
    assert cmds[0] == ["tab", "focus", "w2A:t2"]  # case normalised to the real id
    assert cmds[2] == ["tab", "rename", "w2A:t1", "two", "words"]
    assert cmds[5][-1] == "0.1"
    assert confirm is False


@pytest.mark.parametrize("cmd, why", [
    (["rm", "-rf", "/"], "refusing: rm -rf /"),
    (["tab", "explode", "w2A:t1"], "refusing: tab explode w2A:t1"),
    (["pane", "list"], "refusing: pane list"),
    (["tab", "focus", "w2A:t99"], "unknown tab"),
    (["workspace", "focus", "w99"], "unknown workspace"),
    (["pane", "focus-id", "w2A:p42"], "unknown pane"),
    (["tab", "focus", "foo"], "unknown tab"),
    (["agent", "prompt", "nobody", "hi"], "unknown agent or pane"),
    (["sleeper", "wake", "ghost"], "unknown sleeping agent"),  # its pane is gone
    (["tab", "create", "--cwd", "/no/such/dir/anywhere"], "is not a directory"),
    (["tab", "rename", "w2A:t1"], "needs text"),
    (["tab", "focus"], "missing an argument"),
    (["tab", "focus", "w2A:t1", "extra"], "unexpected argument"),
    (["tab", "focus", "w2A:t1", "--force"], "unknown flag"),
    (["pane", "split", "--direction", "right"], "needs --pane"),
    (["pane", "split", "w2A:p1", "--current"], "unknown flag"),
    (["pane", "resize", "--pane", "w2A:p1", "--direction", "sideways"], "bad direction"),
    (["pane", "resize", "--pane", "w2A:p1", "--direction", "left", "--amount", "lots"], "bad value"),
    ([], "refusing"),
    (["tab", ["nested"]], "refusing"),
])
def test_validate_refuses(ctx, cmd, why):
    with pytest.raises(ai.Refused, match=why):
        ai.validate([cmd], ctx)


def test_validate_caps_the_command_count(ctx):
    with pytest.raises(ai.Refused, match="7 commands"):
        ai.validate([["tab", "focus", "w2A:t1"]] * 7, ctx)
    assert len(ai.validate([["tab", "focus", "w2A:t1"]] * 6, ctx)[0]) == 6


def test_rename_label_that_looks_like_an_id_is_just_text(ctx):
    cmds, _ = ai.validate([["tab", "rename", "w2A:t1", "w99:t7"]], ctx)
    assert cmds == [["tab", "rename", "w2A:t1", "w99:t7"]]


# ----------------------------------------------------------- confirm policy


@pytest.mark.parametrize("cmd, needs", [
    (["tab", "focus", "w2A:t1"], False),
    (["workspace", "focus", "w2A"], False),
    (["pane", "focus-id", "w2A:p1"], False),
    (["agent", "focus", "alpha"], False),
    (["workspace", "rename", "w2A", "ops"], False),
    (["pane", "rename", "w2A:p1", "--clear"], False),
    (["agent", "rename", "alpha", "beta"], False),
    (["workspace", "create", "--label", "x"], False),
    (["pane", "move", "w2A:p1", "--new-tab"], False),
    (["pane", "swap", "--source-pane", "w2A:p1", "--target-pane", "w2A:p2"], False),
    (["pane", "zoom", "w2A:p1", "--toggle"], False),
    (["workspace", "close", "w2A"], True),
    (["tab", "close", "w2A:t1"], True),
    (["pane", "close", "w2A:p1"], True),
    (["pane", "run", "w2A:p1", "ls", "-la"], True),
    (["pane", "send-keys", "w2A:p1", "Enter"], True),
    (["pane", "send-text", "w2A:p1", "hello"], True),
    (["agent", "prompt", "alpha", "/loose"], True),
    (["agent", "start", "new", "--kind", "claude", "--pane", "w2A:p2"], True),
    (["sleeper", "wake", "napper"], True),
    (["session", "stop", "foo"], True),
    (["server", "stop"], True),
    (["plugin", "install", "x/y"], True),
    (["machine", "remove", "m1"], True),
    (["worktree", "remove", "--workspace", "w22"], True),
    (["integration", "uninstall", "claude"], True),
])
def test_confirm_classification(ctx, cmd, needs):
    assert ai.validate([cmd], ctx)[1] is needs


def test_one_destructive_command_makes_the_batch_need_confirmation(ctx):
    _, confirm = ai.validate([["tab", "focus", "w2A:t1"], ["tab", "close", "w2A:t2"]], ctx)
    assert confirm is True


def test_every_spec_has_a_valid_class():
    assert {v[0] for v in ai.SPECS.values()} == {"auto", "confirm"}


# ----------------------------------------------------------- plan rendering


def test_render_plan_shows_full_text_and_marks_confirm_lines(ctx):
    cmds, _ = ai.validate([["tab", "focus", "w2A:t1"],
                           ["agent", "prompt", "alpha", "a long message with 'quotes' and $vars"],
                           ["sleeper", "wake", "napper"]], ctx)
    lines = ai.render_plan(cmds)
    assert lines[0] == "  herdr tab focus w2A:t1"
    assert lines[1].startswith("! herdr agent prompt alpha ")
    assert "a long message with" in lines[1] and "$vars" in lines[1]
    assert lines[2] == "! herdr-sleeper wake napper"


# --------------------------------------------------------------- execution


def test_focus_payload_is_the_socket_pane_focus_call():
    assert ai.focus_payload("w23:p7") == {"id": "ai", "method": "pane.focus", "params": {"pane_id": "w23:p7"}}


def _serve(reply: bytes):
    a, b = socket.socketpair()
    seen = []

    def server():
        buf = b""
        while not buf.endswith(b"\n"):
            buf += b.recv(4096)
        seen.append(json.loads(buf))
        b.sendall(reply)
        b.close()
    t = threading.Thread(target=server)
    t.start()
    return a, seen, t


def test_socket_exchange_sends_newline_json_and_reads_the_reply():
    a, seen, t = _serve(b'{"id":"ai","result":{"type":"ok"}}\n')
    assert ai.socket_exchange(a, ai.focus_payload("w23:p7"))["result"] == {"type": "ok"}
    t.join()
    assert seen == [{"id": "ai", "method": "pane.focus", "params": {"pane_id": "w23:p7"}}]


def test_socket_exchange_raises_on_error_reply():
    a, _, t = _serve(b'{"id":"ai","error":{"code":"pane_not_found","message":"no pane w1:p1"}}\n')
    with pytest.raises(ai.Fail, match="no pane w1:p1"):
        ai.socket_exchange(a, ai.focus_payload("w1:p1"))
    t.join()


def test_focus_pane_without_a_socket_fails_cleanly(tmp_path):
    with pytest.raises(ai.Fail, match="no herdr socket"):
        ai.focus_pane("w1:p1", path=str(tmp_path / "nope.sock"))


def test_execute_runs_in_order_stops_at_first_failure_and_shows_the_message(monkeypatch):
    monkeypatch.setenv("HERDR_BIN_PATH", "/x/herdr")
    calls, focused = [], []

    def runner(argv, timeout):
        calls.append(argv)
        if argv[1:3] == ["tab", "rename"]:
            return types.SimpleNamespace(returncode=1, stdout="", stderr='{"error":{"code":"x","message":"tab gone"}}\n')
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    cmds = [["pane", "focus-id", "w2A:p1"], ["tab", "focus", "w2A:t1"], ["tab", "rename", "w2A:t1", "x"],
            ["tab", "focus", "w2A:t2"]]
    with pytest.raises(ai.Fail, match="tab gone"):
        ai.execute(cmds, runner=runner, focuser=focused.append)
    assert focused == ["w2A:p1"]
    assert calls == [["/x/herdr", "tab", "focus", "w2A:t1"], ["/x/herdr", "tab", "rename", "w2A:t1", "x"]]


def test_execute_maps_sleeper_wake_to_the_plugin_script():
    calls = []
    ai.execute([["sleeper", "wake", "napper"]], runner=lambda argv, t: calls.append(argv) or types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert calls == [[str(ai.SLEEPER), "wake", "napper"]]


# ------------------------------------------------------------- model reply


@pytest.mark.parametrize("text", [
    '{"commands":[["tab","focus","w2A:t1"]],"say":"go","ask":null}',
    '```json\n{"commands":[["tab","focus","w2A:t1"]],"say":"go","ask":null}\n```',
    'Sure!\n{"commands":[["tab","focus","w2A:t1"]],"say":"go"}\nDone.',
])
def test_parse_plan_accepts_bare_fenced_and_chatty_json(text):
    plan = ai.parse_plan(text)
    assert plan["commands"] == [["tab", "focus", "w2A:t1"]] and plan["say"] == "go" and plan["ask"] is None


def test_parse_plan_ask_clears_commands():
    plan = ai.parse_plan('{"commands":[["tab","focus","w2A:t1"]],"say":"","ask":"Which one?"}')
    assert plan == {"commands": [], "say": "", "ask": "Which one?"}


@pytest.mark.parametrize("text", ["no json at all", "[1,2]", '{"commands":"tab focus"}', '{"commands":[["a"],"b"]}'])
def test_parse_plan_rejects_garbage(text):
    with pytest.raises(ai.Fail):
        ai.parse_plan(text)


def _reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]})


def test_ask_model_falls_back_to_the_second_model_on_429():
    seen = []

    def post(url, payload, headers, timeout):
        seen.append(payload["model"])
        if payload["model"] == "gemini-free-lite":
            raise ai.ModelError("gateway HTTP 429", 429, "slow down", True)
        return 200, _reply("{}")

    model, text = ai.ask_model("s", "u", "gemini-free-lite", "k", post=post)
    assert (model, text) == ("gemini-free", "{}") and seen == ["gemini-free-lite", "gemini-free"]


def test_ask_model_retries_the_default_model_last_when_the_fallback_is_rate_limited():
    seen = []

    def post(url, payload, headers, timeout):
        seen.append(payload["model"])
        if payload["model"] == "gemini-free" or len(seen) == 1:
            raise ai.ModelError("gateway HTTP 429", 429, "", True)
        return 200, _reply("{}")

    assert ai.ask_model("s", "u", "gemini-free-lite", "k", post=post)[0] == "gemini-free-lite"
    assert seen == ["gemini-free-lite", "gemini-free", "gemini-free-lite"]


def test_ask_model_gives_up_when_every_attempt_returns_an_empty_reply():
    def post(url, payload, headers, timeout):
        return 200, _reply(None)
    with pytest.raises(ai.Fail, match="empty reply"):
        ai.ask_model("s", "u", "gemini-free-lite", "k", post=post)


def test_ask_model_retries_once_without_response_format_on_400():
    seen = []

    def post(url, payload, headers, timeout):
        seen.append("response_format" in payload)
        if "response_format" in payload:
            raise ai.ModelError("gateway HTTP 400", 400, "unsupported response_format", False)
        return 200, _reply("ok")

    assert ai.ask_model("s", "u", "gemini-free-lite", "k", post=post) == ("gemini-free-lite", "ok")
    assert seen == [True, False]


def test_ask_model_does_not_fall_back_on_auth_errors_or_for_an_explicit_model():
    seen = []

    def post(url, payload, headers, timeout):
        seen.append(payload["model"])
        raise ai.ModelError("gateway HTTP 401", 401, "bad key", False)

    with pytest.raises(ai.Fail, match="401"):
        ai.ask_model("s", "u", "gemini-free-lite", "k", post=post)
    assert seen == ["gemini-free-lite"]
    seen.clear()

    def post_5xx(url, payload, headers, timeout):
        seen.append(payload["model"])
        raise ai.ModelError("gateway HTTP 503", 503, "", True)

    with pytest.raises(ai.Fail):
        ai.ask_model("s", "u", "go-kimi", "k", post=post_5xx)
    assert seen == ["go-kimi"]  # only the default model has a fallback


def test_ask_model_never_routes_to_clinepass():
    with pytest.raises(ai.Fail, match="reserved"):
        ai.ask_model("s", "u", "clinepass-kimi-k3", "k", post=lambda *a: (200, "{}"))
    assert ai.main(["--model", "clinepass-deepseek", "x"]) == 2


def test_ask_model_stops_when_the_time_budget_is_spent():
    t = iter([0.0, 7.5, 7.5, 7.5])

    def post(url, payload, headers, timeout):
        raise ai.ModelError("timeout", 0, "", True)

    with pytest.raises(ai.Fail):
        ai.ask_model("s", "u", "gemini-free-lite", "k", post=post, clock=lambda: next(t))


def test_herdr_error_prefers_the_json_message():
    assert ai.herdr_error('{"error":{"message":"tab w1:t9 not found"}}') == "tab w1:t9 not found"
    assert ai.herdr_error("plain failure\nlast line") == "last line"
    assert ai.herdr_error("") == "failed"


def test_system_prompt_stays_within_its_budget():
    assert len(ai.SYSTEM_PROMPT.splitlines()) <= 60
    assert "focus-id" in ai.SYSTEM_PROMPT and "never invent" in ai.SYSTEM_PROMPT.lower()


# ------------------------------------------------ review fixes (2026-10-08)

PROBE = "ok\nbut\x1b[2A\rspoofed"


def _one_line(text):
    assert "\x1b" not in text and "\r" not in text and "\n" not in text
    assert not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in text)


def test_clean_folds_newlines_and_drops_escapes():
    assert ai.clean(PROBE, 80) == "ok but spoofed"
    assert ai.clean("a\u2028b\x85c\x9bd\x00e\tf", 80) == "a b c" + "d" + "e f"
    assert ai.clean(None, 10) == "" and ai.clean("x" * 100, 10) == "x" * 9 + "…"


def test_model_text_is_one_clean_line_in_the_validated_plan_and_the_render(ctx):
    cmds, _ = ai.validate([["tab", "rename", "w2A:t1", PROBE]], ctx)
    assert cmds == [["tab", "rename", "w2A:t1", "ok but spoofed"]]
    lines = ai.render_plan(cmds)
    assert len(lines) == 1
    _one_line(lines[0])


def test_every_text_position_is_cleaned(ctx):
    cmds, _ = ai.validate([
        ["workspace", "rename", "w2A", PROBE], ["pane", "rename", "w2A:p1", PROBE],
        ["agent", "rename", "alpha", PROBE], ["tab", "create", "--label", PROBE],
        ["pane", "run", "w2A:p1", PROBE, "ls"], ["agent", "prompt", "alpha", PROBE]], ctx)
    for c in cmds:
        for a in c:
            _one_line(a)
    for line in ai.render_plan(cmds):
        _one_line(line)


def test_model_say_and_ask_are_cleaned():
    plan = ai.parse_plan(json.dumps({"commands": [], "say": PROBE, "ask": None}))
    assert plan["say"] == "ok but spoofed"
    plan = ai.parse_plan(json.dumps({"commands": [["tab", "focus", "w1:t1"]], "say": "x", "ask": PROBE}))
    assert plan["ask"] == "ok but spoofed" and plan["commands"] == []
    assert ai.parse_plan(json.dumps({"commands": [], "say": "\x1b[2A", "ask": "\n"}))["ask"] is None


def test_label_and_body_length_caps(ctx):
    cmds, _ = ai.validate([["tab", "rename", "w2A:t1", "x" * 500],
                           ["agent", "prompt", "alpha", "y" * 5000],
                           ["pane", "send-text", "w2A:p1", "z" * 5000],
                           ["pane", "run", "w2A:p1", "w" * 5000]], ctx)
    assert len(cmds[0][3]) == ai.LABEL_MAX == 80
    assert len(cmds[1][3]) == len(cmds[2][3]) == len(cmds[3][3]) == ai.TEXT_MAX == 2000


def test_die_prints_a_clean_message(capsys):
    with pytest.raises(SystemExit):
        ai.die(PROBE)
    _one_line(capsys.readouterr().err.rstrip("\n"))


def test_dry_run_json_is_clean(monkeypatch, capsys, tmp_path):
    st = ai.digest_snapshot(snapshot(), env={})
    monkeypatch.setattr(ai, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(ai, "build_index", lambda *a, **k: ("idx", st, [], {}))
    monkeypatch.setattr(ai, "plan_line", lambda *a, **k: (
        {"commands": [["tab", "rename", "w2A:t1", PROBE]], "say": PROBE, "ask": None}, "m", 5))
    assert ai.main(["--dry-run", "rename it"]) == 0
    out = capsys.readouterr().out
    _one_line(out.rstrip("\n"))
    assert json.loads(out)["commands"] == [["tab", "rename", "w2A:t1", "ok but spoofed"]]


def test_env_makes_any_command_confirm_class(ctx):
    assert ai.validate([["tab", "create", "--env", "X=Y"]], ctx)[1] is True
    assert ai.validate([["tab", "create"]], ctx)[1] is False
    assert ai.validate([["workspace", "create", "--env", "LD_PRELOAD=/tmp/x.so"]], ctx)[1] is True
    assert ai.validate([["pane", "split", "w2A:p1", "--env", "A=b"]], ctx)[1] is True
    assert ai.validate([["tab", "focus", "w2A:t1"], ["tab", "create", "--env", "X=Y"]], ctx)[1] is True
    cmds, _ = ai.validate([["tab", "create", "--env", "X=Y"], ["tab", "create"]], ctx)
    assert [ln[0] for ln in ai.render_plan(cmds)] == ["!", " "]
    with pytest.raises(ai.Refused, match="bad value"):
        ai.validate([["tab", "create", "--env", "not-a-pair"]], ctx)


@pytest.mark.parametrize("cmd", [
    ["session", "stop", "--all", "whatever", "--force"],
    ["session", "stop"],
    ["session", "stop", "--json", "default"],
    ["session", "delete", "a", "b"],
    ["session", "stop", "-x"],
    ["worktree", "create", "--trust-repository", "--cwd", "/tmp"],
    ["worktree", "create"],
    ["worktree", "remove", "wt"],
    ["worktree", "remove"],
    ["worktree", "open", "--branch", "-x", "--cwd", "/tmp"],
    ["machine", "remove", "--force", "m1"],
    ["machine", "remove"],
    ["machine", "add", "-oProxyCommand=evil", "--label", "x"],
    ["machine", "add", "host"],
    ["machine", "rename", "m1"],
    ["server", "stop", "--force"],
    ["server", "reload-config", "now"],
    ["plugin", "install", "https://evil.example/x"],
    ["plugin", "install", "owner/repo", "--yes"],
    ["plugin", "install", "owner/repo", "-y"],
    ["plugin", "install", "--ref", "main"],
    ["plugin", "link", "/no/such/dir"],
    ["plugin", "action", "invoke", "x"],
    ["plugin", "enable", "../x"],
    ["integration", "install", "--all"],
    ["integration", "uninstall"],
])
def test_confirm_only_verbs_refuse_untyped_arguments(ctx, cmd):
    with pytest.raises(ai.Refused):
        ai.validate([cmd], ctx)


@pytest.mark.parametrize("cmd", [
    ["session", "stop", "sleeper-plugin-lab"],
    ["session", "delete", "old.session_1"],
    ["worktree", "create", "--cwd", "/tmp", "--branch", "feature/x", "--base", "origin/main", "--label", "wt"],
    ["worktree", "open", "--workspace", "w22", "--path", "/tmp"],
    ["worktree", "remove", "--workspace", "w22", "--force"],
    ["machine", "add", "me@host.example:22", "--label", "box"],
    ["machine", "rename", "m1", "--label", "new"],
    ["machine", "enable", "m1"],
    ["server", "stop"],
    ["server", "reload-config"],
    ["plugin", "install", "owner/repo", "--ref", "v1.2"],
    ["plugin", "install", "owner/repo/sub/dir"],
    ["plugin", "link", "/tmp", "--disabled"],
    ["plugin", "unlink", "djbclark.herdr-sleeper"],
    ["integration", "install", "claude"],
])
def test_confirm_only_verbs_accept_their_typed_shape_and_ask(ctx, cmd):
    assert ai.validate([cmd], ctx)[1] is True


def test_plugin_action_is_not_allowed():
    assert ("plugin", "action") not in ai.SPECS
    assert all(spec[2] != "any*" for spec in ai.SPECS.values())


def test_pane_move_needs_a_destination(ctx):
    with pytest.raises(ai.Refused, match="needs"):
        ai.validate([["pane", "move", "w2A:p1"]], ctx)
    with pytest.raises(ai.Refused, match="needs"):
        ai.validate([["pane", "move", "w2A:p1", "--label", "x"]], ctx)
    for extra in (["--tab", "w2A:t2"], ["--new-tab"], ["--workspace", "w22"], ["--new-workspace"],
                  ["--target-pane", "w2A:p2"]):
        assert ai.validate([["pane", "move", "w2A:p1", *extra]], ctx)[1] is False


def test_case_folding_only_when_unambiguous():
    snap = snapshot()
    snap["workspaces"] += [{"workspace_id": "wAb", "label": "x"}, {"workspace_id": "wab", "label": "y"}]
    ctx = ai.make_ctx(ai.digest_snapshot(snap, env={}))
    assert ai.validate([["workspace", "focus", "wAb"]], ctx)[0] == [["workspace", "focus", "wAb"]]  # exact
    assert ai.validate([["workspace", "focus", "wab"]], ctx)[0] == [["workspace", "focus", "wab"]]
    with pytest.raises(ai.Refused, match="ambiguous id"):
        ai.validate([["workspace", "focus", "waB"]], ctx)
    assert ai.validate([["workspace", "focus", "w2a"]], ctx)[0] == [["workspace", "focus", "w2A"]]  # unique: folded


def test_case_folding_still_fixes_a_unique_id(ctx):
    assert ai.validate([["pane", "focus-id", "w2a:p1"]], ctx)[0] == [["pane", "focus-id", "w2A:p1"]]


def test_reserved_model_check_ignores_case_and_spaces():
    for m in ("clinepass-x", " ClinePass-x", "CLINEPASS", "\tclinepass-kimi"):
        assert ai.reserved_model(m)
        with pytest.raises(ai.Fail, match="reserved"):
            ai.ask_model("s", "u", m, "k", post=lambda *a: (200, "{}"))
        assert ai.main(["--model", m, "x"]) == 2
    assert not ai.reserved_model("gemini-free-lite")


@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b"x"), http.client.BadStatusLine("junk"),
                                 http.client.RemoteDisconnected("closed")])
def test_http_post_maps_http_client_errors_to_a_retryable_model_error(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(ai.urllib.request, "urlopen", boom)
    with pytest.raises(ai.ModelError) as e:
        ai.http_post("http://127.0.0.1:1/x", {}, {}, 1)
    assert e.value.retryable is True and str(e.value).startswith("gateway:")


def test_log_is_created_0600_and_trimmed(tmp_path):
    log = tmp_path / "sub" / "log.jsonl"
    ai.log_run({"line": "hi"}, path=log)
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert json.loads(log.read_text()) == {"line": "hi"}
    log.chmod(0o644)
    ai.log_run({"line": "again"}, path=log)
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_log_over_4000_lines_is_cut_to_the_last_2000(tmp_path):
    log = tmp_path / "log.jsonl"
    pad = "p" * 120
    log.write_text("".join(json.dumps({"n": n, "pad": pad}) + "\n" for n in range(4000)))
    ai.log_run({"n": 4000, "pad": pad}, path=log)  # 4001 lines
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(rows) == 2000 and rows[0]["n"] == 2001 and rows[-1]["n"] == 4000
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    ai.log_run({"n": 4001, "pad": pad}, path=log)  # small now: left alone
    assert len(log.read_text().splitlines()) == 2001


def test_log_at_exactly_4000_lines_is_left_alone(tmp_path):
    log = tmp_path / "log.jsonl"
    pad = "p" * 120
    log.write_text("".join(json.dumps({"n": n, "pad": pad}) + "\n" for n in range(3999)))
    ai.log_run({"n": 3999, "pad": pad}, path=log)
    assert len(log.read_text().splitlines()) == 4000


# ---- index deadline

def _handoff_tree(tmp_path, names):
    for n, name in enumerate(names):
        d = tmp_path / name / "main"
        d.mkdir(parents=True)
        f = d / "SESSION_LOG.md"
        f.write_text(f"---\nupdated_at: 2026-10-0{n % 9 + 1}T10:00:00-0400\nchain:\n- c{n}\n---\n")
        os.utime(f, (1_000_000 + n, 1_000_000 + n))  # later name = newer


def _panes_for(names):
    return [{"id": f"w2A:p{i}", "cwd": f"/x/{n}"} for i, n in enumerate(names, 1)]


def test_handoff_scan_stops_at_its_deadline(tmp_path):
    names = [f"proj{i}" for i in range(10)]
    _handoff_tree(tmp_path, names)
    stats = {}
    assert ai.read_handoffs(_panes_for(names), root=tmp_path, deadline=time.monotonic() - 1, stats=stats) == []
    assert stats == {"matched": 10, "scanned": 0}
    got = ai.read_handoffs(_panes_for(names), root=tmp_path, deadline=time.monotonic() + 60, stats=stats)
    assert len(got) == 10 and stats["scanned"] == 10


def test_handoff_scan_reads_at_most_max_dirs_newest_first(tmp_path):
    names = [f"proj{i}" for i in range(10)]
    _handoff_tree(tmp_path, names)
    stats = {}
    got = ai.read_handoffs(_panes_for(names), root=tmp_path, max_dirs=3, stats=stats)
    assert stats == {"matched": 10, "scanned": 3}
    assert sorted(h["project"] for h in got) == ["proj7", "proj8", "proj9"]
    assert ai.HANDOFF_DIRS == 40 and ai.HANDOFF_BUDGET == 0.4 and ai.INDEX_BUDGET == 1.5


def test_handoff_scan_ignores_unmatched_dirs_without_opening_them(tmp_path):
    _handoff_tree(tmp_path, ["other1", "other2"])
    stats = {}
    assert ai.read_handoffs(_panes_for(["nothere"]), root=tmp_path, stats=stats) == []
    assert stats == {"matched": 0, "scanned": 0}


def test_index_wall_reads_the_env_override():
    assert ai.index_wall({}) == 1.5
    assert ai.index_wall({"HERDR_AI_INDEX_BUDGET": "0.3"}) == 0.3
    assert ai.index_wall({"HERDR_AI_INDEX_BUDGET": "junk"}) == 1.5
    assert ai.index_wall({"HERDR_AI_INDEX_BUDGET": "-2"}) == 1.5


def test_build_index_gives_up_on_slow_optional_sources(monkeypatch):
    snap = snapshot()
    monkeypatch.setattr(ai, "read_snapshot", lambda: snap)
    monkeypatch.setattr(ai, "read_fleet", lambda *a, **k: time.sleep(3) or {})
    monkeypatch.setattr(ai, "read_sleepers", lambda *a, **k: time.sleep(3) or [])
    monkeypatch.setattr(ai, "read_handoffs", lambda *a, **k: time.sleep(3) or [])
    monkeypatch.setattr(ai, "read_pane_text", lambda pid, timeout=0.5, keep=6: time.sleep(3) or ["x"])
    t0 = time.monotonic()
    text, _state, _sleepers, tm = ai.build_index(env={}, wall=0.4)
    assert time.monotonic() - t0 < 1.5
    assert tm["total"] < 1.0 and 'W w2A "ade"' in text and "   | " not in text
    assert "handoffs" not in tm and "late" in ai.format_timings(tm, len(text), 0.4)


def test_build_index_reports_per_phase_timings(monkeypatch):
    monkeypatch.setattr(ai, "read_snapshot", lambda: snapshot())
    monkeypatch.setattr(ai, "read_fleet", lambda *a, **k: {})
    monkeypatch.setattr(ai, "read_sleepers", lambda *a, **k: [])
    monkeypatch.setattr(ai, "read_handoffs", lambda panes, **k: k["stats"].update(matched=4, scanned=3) or [])
    monkeypatch.setattr(ai, "read_pane_text", lambda pid, timeout=0.5, keep=6: [])
    text, _, _, tm = ai.build_index(env={}, wall=1.5)
    for k in ("snapshot", "handoffs", "pane_text", "fleet", "sleepers", "total"):
        assert k in tm
    line = ai.format_timings(tm, len(text), 1.5)
    assert line.startswith("# index:") and "[3/4 dirs]" in line and "of 1.5 s" in line and "late" not in line


# ---- confirm / exit codes

def _wire_main(monkeypatch, tmp_path, cmds):
    st = ai.digest_snapshot(snapshot(), env={})
    ran = []
    monkeypatch.setattr(ai, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(ai, "build_index", lambda *a, **k: ("idx", st, [], {}))
    monkeypatch.setattr(ai, "plan_line", lambda *a, **k: ({"commands": cmds, "say": "s", "ask": None}, "m", 5))
    monkeypatch.setattr(ai, "execute", lambda c, **k: ran.append(c))
    return ran


def test_confirm_without_a_terminal_cancels_with_a_stderr_note(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert ai.confirm() is False
    assert "not a terminal" in capsys.readouterr().err


def test_main_cancels_confirm_class_plan_without_a_tty_exit_0(monkeypatch, tmp_path, capsys):
    ran = _wire_main(monkeypatch, tmp_path, [["tab", "close", "w2A:t2"]])
    monkeypatch.setattr(ai.sys.stdin, "isatty", lambda: False, raising=False)
    assert ai.main(["close", "it"]) == 0
    assert ran == []
    cap = capsys.readouterr()
    assert "! herdr tab close w2A:t2" in cap.out and "cancelled" in cap.err
    assert json.loads((tmp_path / "log.jsonl").read_text())["outcome"] == "cancelled"


def test_main_runs_auto_class_plan_exit_0_and_refusal_exits_1(monkeypatch, tmp_path):
    ran = _wire_main(monkeypatch, tmp_path, [["tab", "focus", "w2A:t2"]])
    monkeypatch.setattr(ai.sys.stdin, "isatty", lambda: False, raising=False)
    assert ai.main(["go"]) == 0 and ran == [[["tab", "focus", "w2A:t2"]]]
    _wire_main(monkeypatch, tmp_path, [["tab", "focus", "w99:t9"]])
    with pytest.raises(SystemExit) as e:
        ai.main(["go"])
    assert e.value.code == 1
