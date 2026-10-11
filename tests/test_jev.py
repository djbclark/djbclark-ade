"""Offline contracts for Jev, its reports, and both optional call sites."""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def jev(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-never-print")
    monkeypatch.delenv("JEV_REEXEC", raising=False)
    monkeypatch.delenv("JEV_RETURN_RECORD", raising=False)
    mod = load("jev_test", "bin/jev")
    monkeypatch.setattr(mod, "urlopen", Mock(side_effect=AssertionError("no network in tests")))
    return mod


ARGS = ["decide", "--site", "test", "--state", "example state", "--question", "Which?",
        "--option", "a", "--option", "b", "--incumbent", "a"]


def response(choice="a", prob=.9, tokens=100, cost=None):
    return {"answers": {"decision": {"choice": choice, "confidence": .3,
            "probabilities": {choice: prob, "b" if choice == "a" else "a": 1-prob}}},
            "usage": {"input_tokens": tokens, "output_tokens": 12, "cost": cost}}


def answer(jev, monkeypatch, capsys, payload=None, args=None):
    monkeypatch.setattr(jev, "http_call", Mock(return_value=payload or response()))
    assert jev.main(args or ARGS) == 0
    return json.loads(capsys.readouterr().out)


def test_modes_off_is_no_work(jev, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("JEV_MODE")
    assert jev.mode() == "off"
    monkeypatch.setattr(sys, "stdin", Mock(read=Mock(side_effect=AssertionError())))
    assert jev.main(["decide"]) == 3
    assert not jev.log_path().exists()
    assert jev.main(["mode", "shadow"]) == 0
    assert jev.mode() == "shadow"
    (tmp_path / ".config/jev/mode").write_text("act extra words\n")
    assert jev.mode() == "act"
    monkeypatch.setenv("JEV_MODE", "off")
    assert jev.mode() == "off"
    assert jev.main(ARGS) == 3
    assert not jev.log_path().exists()
    monkeypatch.setenv("JEV_MODE", "invalid")
    assert jev.mode() == "off"


def test_output_log_schema_and_http(jev, monkeypatch, capsys):
    out = answer(jev, monkeypatch, capsys, args=ARGS + ["--meta", "model=opus"])
    assert out["answer"] == "a" and out["prob"] == .9
    assert out["confident"] and not out["act"] and out["agree"]
    row, = list(jev.rows())
    assert {"id", "ts", "site", "mode", "question", "options", "probs", "answer", "prob",
            "threshold", "incumbent", "agree", "latency_ms", "input_tokens", "meta",
            "state_chars", "state_sha256", "state_excerpt", "error"} <= row.keys()
    assert row["meta"] == {"model": "opus"}
    assert row["state_chars"] == 13 and len(row["state_sha256"]) == 64
    payload, key, timeout = jev.http_call.call_args.args
    assert payload["questions"]["decision"] == {"type": "choice", "instructions": "Which?", "criteria": {"a": "a", "b": "b"}}
    assert key == "test-key-never-print" and 0 < timeout <= 5
    assert key not in jev.log_path().read_text()


@pytest.mark.parametrize("mode,prob,act", [("act", .9, True), ("act", .7, False), ("shadow", .9, False)])
def test_threshold(jev, monkeypatch, capsys, mode, prob, act):
    monkeypatch.setenv("JEV_MODE", mode)
    assert answer(jev, monkeypatch, capsys, response(prob=prob))["act"] is act


def test_error_and_deadline(jev, monkeypatch, capsys):
    monkeypatch.setattr(jev, "http_call", Mock(side_effect=OSError("test-key-never-print")))
    assert jev.main(ARGS) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "OSError"
    assert "test-key-never-print" not in jev.log_path().read_text()
    monkeypatch.setattr(jev, "http_call", lambda *a: time.sleep(10))
    start = time.monotonic()
    assert jev.main(ARGS + ["--timeout", ".1"]) == 2
    assert time.monotonic() - start < .5
    assert list(jev.rows())[-1]["error"] == "TimeoutError"


def test_invalid_response(jev, monkeypatch, capsys):
    bad = response()
    bad["answers"]["decision"]["probabilities"]["a"] = float("nan")
    monkeypatch.setattr(jev, "http_call", Mock(return_value=bad))
    assert jev.main(ARGS) == 2
    assert list(jev.rows())[-1]["error"] == "ValueError"


def test_stdin_and_state_file(jev, monkeypatch, capsys, tmp_path):
    args = ARGS[:3] + ARGS[5:]
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin"))
    answer(jev, monkeypatch, capsys, args=args)
    assert list(jev.rows())[-1]["state_excerpt"] == "stdin"
    path = tmp_path / "input"
    path.write_text("file" * 1000)
    answer(jev, monkeypatch, capsys, args=args + ["--state-file", str(path)])
    assert list(jev.rows())[-1]["state_chars"] == 4000
    assert len(list(jev.rows())[-1]["state_excerpt"]) == 1500


def test_reexec_guard_and_timeout(jev, monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY")
    monkeypatch.setenv("JEV_REEXEC", "1")
    assert jev.main(ARGS) == 2
    assert list(jev.rows())[-1]["error"] == "PermissionError"
    monkeypatch.delenv("JEV_REEXEC")
    fake = tmp_path / "sudo-secretspec"
    fake.write_text("#!/bin/sh\nsleep 10\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    start = time.monotonic()
    assert jev.main(ARGS + ["--timeout", ".2"]) == 2
    assert time.monotonic() - start < .7
    assert len(list(jev.rows())) == 2
    assert list(jev.rows())[-1]["error"] == "TimeoutError"


def test_label_report_math_and_disagreements(jev, monkeypatch, capsys):
    a = answer(jev, monkeypatch, capsys)
    b = answer(jev, monkeypatch, capsys, response("b", .85, 200, .002))
    c = answer(jev, monkeypatch, capsys, response("b", .99, 300))
    assert jev.main(["label", a["id"], "a"]) == 0
    assert jev.main(["label", b["id"], "a"]) == 0
    assert jev.main(["report", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)["sites"]["test"]
    assert stats["calls"] == 3 and stats["errors"] == 0
    assert stats["agreement"] == pytest.approx(1/3)
    assert stats["confusion"] == {"a": {"a": 1, "b": 2}}
    assert stats["confident_disagreements"] == 2
    assert stats["accuracy"] == .5 and stats["labelled_calls"] == 2
    assert stats["cost_usd"] == pytest.approx(.002 + 400*.042/1_000_000)
    assert jev.main(["disagreements", "--site", "test", "--limit", "2"]) == 0
    found = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["id"] for r in found] == [c["id"], b["id"]]


def test_smoke_filter_since_savings_and_percentiles(jev, monkeypatch, capsys):
    answer(jev, monkeypatch, capsys, args=["smoke" if x == "test" else x for x in ARGS])
    r = list(jev.rows())[0]
    r.update(id="effort", site="prompt-effort", answer="mechanical", incumbent=None,
             agree=None, meta={"model": "claude-opus-5-5"})
    jev.append(r)
    assert jev.main(["report", "--json", "--tokens-per-turn", "1000", "--price-difference", "2"]) == 0
    sites = json.loads(capsys.readouterr().out)["sites"]
    assert set(sites) == {"prompt-effort"}
    assert sites["prompt-effort"]["savings_upper_bound"]["usd"] == .002
    assert jev.main(["report", "--site", "smoke", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sites"]["smoke"]["calls"] == 1
    assert jev.percentile([10, 20, 30], .5) == 20
    assert jev.percentile([10, 20, 30], .95) == 29
    assert jev.since("7d") == 604800


@pytest.fixture
def hook(jev):
    return load("jev_hook_test", "claude/hooks/jev_effort_hook.py")


@pytest.mark.parametrize("prompt", ["short", "/model sonnet please now", "<task-notification>some task completed</task-notification>",
    '<tool_result>long tool output here</tool_result>', '{"type":"tool_result","content":"long output"}',
    '<pasted_content id="1">\n<tool_result>long output here</tool_result>\n</pasted_content id="1">'])
def test_hook_skip(hook, monkeypatch, capsys, prompt):
    popen = Mock(side_effect=AssertionError("must skip"))
    monkeypatch.setattr(hook.subprocess, "Popen", popen)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
    assert hook.main() == 0
    popen.assert_not_called()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mode,model,confident,visible", [("shadow", "opus", True, False), ("act", "fable", True, True),
    ("act", "opus", True, True), ("act", "sonnet", True, False), ("act", "opus", False, False)])
def test_hook_output_and_meta(hook, monkeypatch, capsys, tmp_path, mode, model, confident, visible):
    monkeypatch.setenv("JEV_MODE", mode)
    transcript = tmp_path / "transcript"
    transcript.write_text('x' * 70000 + '\n' + json.dumps({"type": "assistant", "message": {"model": model}}) + '\n')
    assert hook.model_from_tail(transcript) == model
    proc = Mock(returncode=0)
    proc.communicate.return_value = (json.dumps({"answer": "mechanical", "confident": confident, "prob": .91}), None)
    proc.poll.return_value = 0
    popen = Mock(return_value=proc)
    monkeypatch.setattr(hook.subprocess, "Popen", popen)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "apply the agreed edit to the file", "transcript_path": str(transcript), "session_id": "s1"})))
    assert hook.main() == 0
    output = capsys.readouterr().out
    assert bool(output) is visible
    if visible:
        assert json.loads(output) == {"systemMessage": "jev: this looks mechanical (p=0.91); /model sonnet would cost less"}
    assert "model=" + model in popen.call_args.args[0]
    assert "session=s1" in popen.call_args.args[0]
    assert proc.communicate.call_args.args == ("apply the agreed edit to the file",)


def test_hook_off_and_whole_deadline(hook, monkeypatch, capsys):
    monkeypatch.setenv("JEV_MODE", "off")
    monkeypatch.setattr(sys, "stdin", Mock(read=Mock(side_effect=AssertionError())))
    assert hook.main() == 0
    monkeypatch.setenv("JEV_MODE", "shadow")
    hook.STARTED = time.monotonic() - 2.8
    monkeypatch.setattr(hook.json, "load", lambda *a: time.sleep(10))
    start = time.monotonic()
    assert hook.main() == 0
    assert time.monotonic() - start < .5
    assert capsys.readouterr().out == ""


def test_dispatch_off_and_detached_failure(jev, monkeypatch, tmp_path):
    dispatch = load("jev_dispatch_test", "bin/acp-dispatch")
    popen = Mock(side_effect=OSError("missing binary"))
    monkeypatch.setattr(dispatch.subprocess, "Popen", popen)
    monkeypatch.setenv("JEV_MODE", "off")
    dispatch.jev_shadow({})
    popen.assert_not_called()
    report = tmp_path / "task-report.md"
    report.write_text("STATUS: complete\nDONE\n")
    final = tmp_path / "final"
    final.write_text("")
    record = tmp_path / "record.json"
    rec = dict(report=str(report), final=str(final), done=str(report)+".done", agent="codex", name="test")
    for mode in ("off", "shadow", "act"):
        monkeypatch.setenv("JEV_MODE", mode)
        record.write_text(json.dumps(rec))
        st, _, saved = dispatch.finalize(record, 0)
        assert dispatch.exit_for(st, 0) == 0
        assert saved["status"] == "done"
        assert report.read_text() == "STATUS: complete\nDONE\n"
    assert popen.call_count == 2
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["env"]["JEV_MODE"] == "shadow"


@pytest.mark.parametrize("status,rc,failure,expected", [("done", 0, "", "done"), ("done", 124, "", "partial"),
    ("blocked", 0, "", "blocked"), ("partial", 0, "", "partial"), ("no-report", 0, "", "no_report"),
    ("no-report", 1, "NO-REPORT: refused (agy)", "refused"), ("no-report", 1, "NO-REPORT: quota", "provider_error")])
def test_dispatch_mapping_and_state(jev, monkeypatch, tmp_path, status, rc, failure, expected):
    dispatch = load("jev_dispatch_mapping", "bin/acp-dispatch")
    final = tmp_path / "final.txt"
    final.write_text("x" * 5000)
    err = tmp_path / "stderr.txt"
    err.write_text("old line\nsummary line\n")
    captured = {}
    def launch(args, **kwargs):
        captured.update(args=args, state=kwargs["stdin"].read().decode())
        return Mock()
    monkeypatch.setattr(dispatch.subprocess, "Popen", launch)
    dispatch.jev_shadow(dict(status=status, exit=rc, failure=failure, final=str(final), stderr=str(err)))
    assert captured["args"][captured["args"].index("--incumbent")+1] == expected
    assert captured["state"] == "summary line\n" + "x" * 4000
