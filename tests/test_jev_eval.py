"""Offline contracts for bin/jev-eval: dataset builders, strict scoring, resumable runs."""
import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader("jev_eval_test", str(ROOT / "bin/jev-eval"))
    spec = importlib.util.spec_from_loader("jev_eval_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def ev(monkeypatch, tmp_path):
    mod = load()
    monkeypatch.setattr(mod, "EVAL", tmp_path / "eval")
    monkeypatch.setattr(mod, "subprocess", SimpleNamespace(
        run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess in tests")),
        TimeoutExpired=subprocess.TimeoutExpired))
    return mod


def record(tmp, name, **extra):
    task = tmp / "t1"
    (task / "jobs").mkdir(parents=True, exist_ok=True)
    report, stderr = task / f"{name}-report.md", task / f"{name}-stderr.txt"
    report.write_text("STATUS: ok\n" + "x" * 5000 + "\nthe end")
    stderr.write_text("noise\nsummary line\n")
    rec = dict(name=name, task="t1", agent="codex", status="done", exit=0,
               report=str(report), final=str(task / f"{name}-final.txt"), stderr=str(stderr))
    rec.update(extra)
    (task / "jobs" / f"{name}.json").write_text(json.dumps(rec))


def test_dispatch_truth_matches_acp_dispatch_mapping(ev):
    assert ev.dispatch_truth(dict(status="done", exit=0)) == "done"
    assert ev.dispatch_truth(dict(status="done", exit=1)) == "partial"
    assert ev.dispatch_truth(dict(status="no-report", exit=1)) == "no_report"
    assert ev.dispatch_truth(dict(status="no-report", failure="NO-REPORT: refused x")) == "refused"
    assert ev.dispatch_truth(dict(status="no-report", failure="NO-REPORT: quota")) == "provider_error"
    assert ev.dispatch_truth(dict(status="running")) is None
    assert ev.dispatch_truth(dict(status="weird")) is None


def test_build_dispatch_state_is_summary_plus_report_tail(ev, tmp_path):
    record(tmp_path, "a")
    record(tmp_path, "b", status="running")
    rows = ev.build_dispatch(tmp_path)
    assert len(rows) == 1 and rows[0]["truth"] == "done" and rows[0]["truth_source"] == "record"
    assert rows[0]["state"].startswith("summary line\n")
    assert rows[0]["state"].endswith("the end") and "STATUS: ok" not in rows[0]["state"]
    assert len(rows[0]["state"]) <= len("summary line\n") + 4000


def test_parse_haiku_is_strict(ev):
    options = ["mechanical", "normal", "hard"]
    assert ev.parse_haiku("  normal\n", options) == "normal"
    for bad in ("Normal", "normal.", "I think normal", "normal or hard", "", None):
        assert ev.parse_haiku(bad, options) is None


def test_score_rows_accuracy_confusion_calibration(ev):
    options = ["a", "b"]
    rows = [dict(id=str(i), truth=t) for i, t in enumerate("aaabb")]
    results = [
        dict(id="0", answer="a", prob=.95, wall_ms=10, latency_ms=10, jev_id="j0"),
        dict(id="1", answer="a", prob=.85, wall_ms=20, latency_ms=20, jev_id="j1"),
        dict(id="2", answer="b", prob=.65, wall_ms=30, latency_ms=30, jev_id="j2"),
        dict(id="3", answer="b", prob=.55, wall_ms=40, latency_ms=40, jev_id="j3"),
        dict(id="4", answer=None, error="TimeoutError", wall_ms=50),
    ]
    out = ev.score_rows(rows, results, options, costs={"j0": .001, "j1": .001})
    assert out["n"] == 5 and out["correct"] == 3 and out["errors"] == 1
    assert out["accuracy"] == pytest.approx(.6) and out["majority_baseline"] == pytest.approx(.6)
    assert out["confusion"] == {"a": {"a": 2, "b": 1}, "b": {"b": 1, "(none)": 1}}
    assert out["cost_usd"] == pytest.approx(.002)
    assert out["wall_p50_ms"] == 30
    by_bucket = {b["bucket"]: b for b in out["calibration"]}
    assert by_bucket["0.9-1.0"] == dict(bucket="0.9-1.0", n=1, accuracy=1.0)
    assert by_bucket["0.6-0.7"]["accuracy"] == 0.0 and by_bucket["0.5-0.6"]["accuracy"] == 1.0
    t = {x["threshold"]: x for x in out["thresholds"]}
    assert t[0.6]["covered"] == 3 and t[0.6]["accuracy"] == pytest.approx(2 / 3)
    assert t[0.8]["covered"] == 2 and t[0.8]["accuracy"] == 1.0 and t[0.9]["covered"] == 1


def test_confident_mechanical_on_hard_is_counted(ev):
    rows = [dict(id="1", truth="hard"), dict(id="2", truth="normal")]
    results = [dict(id="1", answer="mechanical", prob=.9, wall_ms=1),
               dict(id="2", answer="mechanical", prob=.7, wall_ms=1)]
    out = ev.score_rows(rows, results, ev.EFFORT_OPTIONS, costs={})
    assert out["confident_mechanical_on_hard"] == 1
    assert out["confident_mechanical_on_non_mechanical"] == 1


def test_run_is_resumable_and_never_exceeds_four_workers(ev):
    ev.write_jsonl(ev.EVAL / "slice-kind.jsonl",
                   [dict(id=str(i), truth="code", truth_source="reviewer", state="s") for i in range(6)])
    seen, active, peak = [], [], [0]

    def caller(row, spec):
        active.append(1)
        peak[0] = max(peak[0], len(active))
        seen.append(row["id"])
        active.pop()
        return dict(id=row["id"], answer="code", prob=.9, wall_ms=1)

    first = ev.run("slice-kind", "jev", limit=3, workers=16, caller=caller)
    assert first["attempted"] == 3 and peak[0] <= 4
    second = ev.run("slice-kind", "jev", workers=16, caller=caller)
    assert second["attempted"] == 3 and sorted(seen) == [str(i) for i in range(6)]


def test_run_stops_haiku_when_budget_is_spent(ev, monkeypatch):
    monkeypatch.setattr(ev, "HAIKU_BUDGET_USD", 0.5)
    ev.write_jsonl(ev.EVAL / "slice-kind.jsonl",
                   [dict(id=str(i), truth="code", truth_source="reviewer", state="s") for i in range(20)])
    out = ev.run("slice-kind", "haiku", workers=1,
                 caller=lambda row, spec: dict(id=row["id"], answer="code", wall_ms=1, cost=0.3))
    assert out["stopped_on_budget"] and out["attempted"] == 20
    assert len(ev.read_jsonl(ev.EVAL / "slice-kind.haiku.results.jsonl")) == 2


def test_jev_call_uses_shadow_mode_eval_site_and_subprocess(ev, monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured.update(args=args, env=kw["env"], input=kw["input"])
        out = dict(answer="hard", prob=.9, probs={}, error=None, latency_ms=12.0, id="u1", input_tokens=5)
        return SimpleNamespace(returncode=0, stdout=json.dumps(out))

    monkeypatch.setattr(ev.subprocess, "run", fake_run)
    row = dict(id="r1", truth="normal", state="do the thing", _dataset="prompt-effort")
    result = ev.jev_call(row, ev.DATASETS["prompt-effort"])
    args = captured["args"]
    assert args[args.index("--site") + 1] == "eval-prompt-effort"
    assert captured["env"]["JEV_MODE"] == "shadow" and captured["input"] == "do the thing"
    assert [args[i + 1] for i, a in enumerate(args) if a == "--option"] == ev.EFFORT_OPTIONS
    assert result["answer"] == "hard" and result["jev_id"] == "u1" and result["error"] is None
    assert all("typesafe" not in str(a).lower() for a in args)


def test_haiku_call_parses_cost_and_flags_off_list_answers(ev, monkeypatch):
    def fake_run(args, **kw):
        assert "--setting-sources" in args and "--tools" in args
        body = dict(result="Mechanical.", is_error=False, total_cost_usd=0.0003,
                    usage=dict(input_tokens=2, cache_creation_input_tokens=600, output_tokens=5))
        return SimpleNamespace(returncode=0, stdout=json.dumps(body))

    monkeypatch.setattr(ev.subprocess, "run", fake_run)
    monkeypatch.setattr(ev, "EVAL_CWD", lambda: Path("/tmp"))
    result = ev.haiku_call(dict(id="r", state="s"), ev.DATASETS["prompt-effort"])
    assert result["answer"] is None and result["raw"] == "Mechanical." and result["cost"] == 0.0003


def test_typed_text_keeps_operator_text_only(ev):
    def user(content, **kw):
        return dict(type="user", message=dict(content=content), **kw)

    assert ev.typed_text(user("Please fix the failing test in foo.py")) == "Please fix the failing test in foo.py"
    assert ev.typed_text(user([dict(type="text", text="A typed prompt long enough")])) == "A typed prompt long enough"
    assert ev.typed_text(user([dict(type="tool_result", content="x" * 50)])) is None
    assert ev.typed_text(user("short")) is None
    assert ev.typed_text(user("/compact now please do it")) is None
    assert ev.typed_text(user("<command-name>/x</command-name> and more text")) is None
    assert ev.typed_text(user("Another Claude session sent a message: <teammate-message x>")) is None
    assert ev.typed_text(user("A long enough meta line here", isMeta=True)) is None
    assert ev.typed_text(dict(type="assistant", message=dict(content="a long enough reply here"))) is None


def test_kind_candidates_dedupe_exclude_and_header(ev, tmp_path):
    same = "# Brief\n" + "do the work carefully. " * 20
    for task, name, text in [("a", "brief-1.md", same), ("a", "copy-brief.md", same),
                             ("jev-eval", "brief-eval.md", "# own brief\n" + "z" * 200),
                             ("b", "brief.md", "# Slice (kind: research) find things\n" + "y" * 200)]:
        (tmp_path / task).mkdir(exist_ok=True)
        (tmp_path / task / name).write_text(text)
    got = ev.kind_candidates(tmp_path)
    assert sorted(c["meta"]["task"] for c in got) == ["a", "b"]
    assert ev.header_kind("# Slice (kind: research) find") == "research"
    assert ev.header_kind("# Slice (kind: review) find") is None


def test_build_keeps_only_labelled_rows_and_masks_header_kind(ev, tmp_path, monkeypatch):
    cands = [dict(id="c1", state="# S (kind: code) do it", meta={}), dict(id="c2", state="x", meta={}),
             dict(id="c3", state="y", meta={})]
    monkeypatch.setattr(ev, "kind_candidates", lambda: cands)
    ev.write_jsonl(ev.EVAL / "x", [])
    (ev.EVAL / "slice-kind.labels.json").write_text(json.dumps({"c2": "research", "c3": "bogus"}))
    summary = ev.build(["slice-kind"])["slice-kind"]
    assert summary["rows"] == 2 and summary["sources"] == {"brief-header": 1, "reviewer": 1}
    rows = {r["id"]: r for r in ev.read_jsonl(ev.EVAL / "slice-kind.jsonl")}
    assert "(kind:" not in rows["c1"]["state"] and rows["c1"]["truth"] == "code"
    assert rows["c2"]["truth"] == "research"


def test_prompt_candidates_keep_labelled_first_and_cap(ev, tmp_path):
    proj = tmp_path / "-Users-djbclark-p1"
    proj.mkdir()
    lines = [json.dumps(dict(type="user", message=dict(content=f"prompt number {i} is long enough")))
             for i in range(30)]
    (proj / "s.jsonl").write_text("\n".join(lines))
    labelled = ev.sha("prompt", "prompt number 29 is long enough")
    got = ev.prompt_candidates(tmp_path, cap=5, per_project=10, labels={labelled: "x"})
    assert got[0]["id"] == labelled and len(got) == 5
    again = ev.prompt_candidates(tmp_path, cap=5, per_project=10, labels={labelled: "x"})
    assert [g["id"] for g in got] == [g["id"] for g in again]
