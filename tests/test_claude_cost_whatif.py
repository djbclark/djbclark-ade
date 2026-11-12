"""tests for bin/claude-cost-whatif (cache and compaction cost what-if simulator)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import pytest

BIN = Path(__file__).resolve().parents[1] / "bin" / "claude-cost-whatif"


def load_module():
    loader = importlib.machinery.SourceFileLoader("claude_cost_whatif", str(BIN))
    spec = importlib.util.spec_from_loader("claude_cost_whatif", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def make_assistant_turn(mid: str, usage: dict, timestamp: str = "2026-11-12T12:00:00Z", model: str = "claude-sonnet-5-5"):
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "id": mid,
            "model": model,
            "usage": usage,
        },
    }


def test_parse_helpers():
    mod = load_module()
    assert mod.parse_tokens("104k") == 104_000
    assert mod.parse_tokens("1.2M") == 1_200_000
    assert mod.parse_tokens("267000") == 267_000
    assert mod.parse_tokens("~46.5k") == 46_500
    assert mod.parse_tokens(100) == 100

    with pytest.raises(ValueError):
        mod.parse_tokens("invalid")
    with pytest.raises(ValueError):
        mod.parse_tokens("")

    assert mod.parse_thresholds("300k, 267k, 400k") == [400_000, 300_000, 267_000]
    with pytest.raises(ValueError):
        mod.parse_thresholds("")


def test_timestamp_parser():
    mod = load_module()
    ts = mod.parse_timestamp("2026-11-12T12:00:00Z")
    assert ts is not None and isinstance(ts, float)
    assert mod.parse_timestamp("invalid-date") is None
    assert mod.parse_timestamp("") is None


def test_pricing():
    mod = load_module()
    # Sonnet 5.5: $2.0/MTok base, 0.05 read
    base, rd = mod.price("claude-sonnet-5-5-20261022")
    assert abs(base - 2.0e-6) < 1e-12
    assert abs(rd - 0.05) < 1e-12

    # Opus 5.5: $4.0/MTok base, 0.05 read
    base_op, rd_op = mod.price("claude-opus-5-5")
    assert abs(base_op - 4.0e-6) < 1e-12
    assert abs(rd_op - 0.05) < 1e-12

    # Fable 5.1: $10.0/MTok base, 0.025 read
    base_fb, rd_fb = mod.price("claude-fable-5-1")
    assert abs(base_fb - 10.0e-6) < 1e-12
    assert abs(rd_fb - 0.025) < 1e-12

    # Unknown: $1.0/MTok base, 0.1 read
    base_un, rd_un = mod.price("unknown-model")
    assert abs(base_un - 1.0e-6) < 1e-12
    assert abs(rd_un - 0.10) < 1e-12

    # Override read
    _, rd_custom = mod.price("claude-sonnet-5-5", read_override=0.20)
    assert abs(rd_custom - 0.20) < 1e-12


def test_empty_dir_exits_3(tmp_path):
    mod = load_module()
    assert mod.main(["--root", str(tmp_path)]) == 3


def test_bad_usage_exits_2():
    mod = load_module()
    assert mod.main(["--bad-flag"]) == 2
    assert mod.main(["--thresholds", ""]) == 2


def test_synthetic_ttl_simulation(tmp_path, capsys):
    mod = load_module()
    proj = tmp_path / "test-proj"
    proj.mkdir(parents=True)

    # Transcript with 2 requests, separated by 10 minutes (600s gap)
    # Model: Sonnet 5.5 ($2.0/MTok base = 2e-6)
    # Turn 1: 1,000 input, 10,000 cache write -> 1h cost = 2e-6 * (1000 + 10000*2) = $0.042
    # Turn 2: 100 input, 10,000 cache read, 500 output
    #   Under 1h TTL: 2e-6 * (100 + 10000*0.05 + 500*5) = 2e-6 * (100 + 500 + 2500) = $0.0062
    #   Under 5m TTL: 600s gap > 300s -> prefix bust! 10000 cache read must rewrite at 1.25x!
    #   5m cost: 2e-6 * (100 + 10000*1.25 + 500*5) = 2e-6 * (100 + 12500 + 2500) = $0.0302
    u1 = {"input_tokens": 1000, "cache_creation_input_tokens": 10000, "cache_read_input_tokens": 0, "output_tokens": 0}
    u2 = {"input_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 10000, "output_tokens": 500}

    lines = [
        make_assistant_turn("m1", u1, timestamp="2026-11-12T12:00:00Z"),
        make_assistant_turn("m2", u2, timestamp="2026-11-12T12:10:00Z"),  # 600s gap
    ]
    (proj / "session1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    code = mod.main(["--root", str(tmp_path), "--json", "--days", "30"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)

    assert out["transcripts"] == 1
    assert out["requests"] == 2
    assert out["ttl"]["gap_requests"] == 1
    assert out["ttl"]["gap_cached_tokens"] == 10000

    # 1h cost = 0.042 + 0.0062 = 0.0482
    assert abs(out["ttl"]["observed_1h_usd"] - 0.0482) < 1e-9
    # 5m turn 1 = 2e-6 * (1000 + 10000*1.25) = 0.027
    # 5m turn 2 = 0.0302
    # Total 5m = 0.027 + 0.0302 = 0.0572
    assert abs(out["ttl"]["five_minute_usd"] - 0.0572) < 1e-9
    assert out["ttl"]["five_minute_pct_diff"] > 0


def test_compaction_and_handoff_simulation(tmp_path, capsys):
    mod = load_module()
    proj = tmp_path / "test-proj"
    proj.mkdir(parents=True)

    # Synthetic transcript:
    # Model: Sonnet 5.5
    # Turn 1: 50k tokens (within threshold)
    # Turn 2: 300k tokens (exceeds 200k threshold!)
    # Turn 3: 310k tokens (subsequent turn benefits from drop)
    u1 = {"input_tokens": 0, "cache_creation_input_tokens": 50000, "cache_read_input_tokens": 0, "output_tokens": 100}
    u2 = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 300000, "output_tokens": 100}
    u3 = {"input_tokens": 0, "cache_creation_input_tokens": 10000, "cache_read_input_tokens": 300000, "output_tokens": 100}

    lines = [
        make_assistant_turn("m1", u1, timestamp="2026-11-12T12:00:00Z"),
        make_assistant_turn("m2", u2, timestamp="2026-11-12T12:01:00Z"),
        make_assistant_turn("m3", u3, timestamp="2026-11-12T12:02:00Z"),
    ]
    (proj / "session_large.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    code = mod.main([
        "--root", str(tmp_path),
        "--thresholds", "200k",
        "--floor", "100k",
        "--preamble", "50k",
        "--summary-tokens", "5000",
        "--days", "30",
        "--json",
    ])
    assert code == 0
    out = json.loads(capsys.readouterr().out)

    assert out["requests"] == 3
    # Check compaction thresholds: "observed" and "200k"
    assert len(out["compaction_thresholds"]) == 2
    row = out["compaction_thresholds"][1]
    assert row["threshold"] == 200_000
    assert row["extra_compactions"] == 1

    # Check handoff comparison:
    assert len(out["handoff_comparison"]) == 1
    h_row = out["handoff_comparison"][0]
    assert h_row["threshold"] == 200_000
    # Exact values: compaction $0.743, handoff $0.453, saving $0.290 (~39.0%)
    assert abs(row["total_usd"] - 0.743) < 1e-4
    assert abs(h_row["compaction_usd"] - 0.743) < 1e-4
    assert abs(h_row["handoff_usd"] - 0.453) < 1e-4
    assert abs(h_row["saving_usd"] - 0.290) < 1e-4
    assert abs(h_row["saving_pct"] - (0.290 / 0.743)) < 1e-4


def test_cache_miss_context_drop_deduction(tmp_path, capsys):
    mod = load_module()
    proj = tmp_path / "test-proj"
    proj.mkdir(parents=True)

    # Turn 1: 300k context (triggers compaction at 200k, floor 100k, drop = 200k)
    # Turn 2: Cache miss / restart (>1h idle gap), so 300k is in cache_creation_tokens, cr=0.
    # Drop must deduct from cw (F1 fix), rather than only cr.
    u1 = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 300000, "output_tokens": 0}
    u2 = {"input_tokens": 0, "cache_creation_input_tokens": 300000, "cache_read_input_tokens": 0, "output_tokens": 0}

    lines = [
        make_assistant_turn("m1", u1, timestamp="2026-11-12T12:00:00Z"),
        make_assistant_turn("m2", u2, timestamp="2026-11-12T14:00:00Z"),
    ]
    (proj / "cache_miss.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    code = mod.main(["--root", str(tmp_path), "--thresholds", "200k", "--floor", "100k", "--days", "30", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    row = out["compaction_thresholds"][1]
    # Turn 1: overhead $0.490 + req $0.010 = $0.500
    # Turn 2: eff cw = 100k * 2.0 * 2e-6 = $0.400 -> total = $0.900
    assert abs(row["total_usd"] - 0.900) < 1e-4


def test_negative_handoff_savings_formatting():
    mod = load_module()
    sample = {
        "transcripts": 1,
        "requests": 1,
        "parameters": {"days": 1.0, "floor_tokens": 104000, "preamble_tokens": 46500, "summary_tokens": 6000},
        "ttl": {
            "observed_1h_usd": 10.0,
            "five_minute_usd": 12.0,
            "five_minute_pct_diff": 0.2,
            "subagent_5m_usd": 10.5,
            "subagent_5m_pct_diff": 0.05,
            "gap_requests": 0,
            "gap_request_ratio": 0.0,
            "gap_cached_tokens": 0,
        },
        "compaction_thresholds": [
            {"threshold": None, "label": "observed", "total_usd": 10.0, "diff_usd": 0.0, "pct_diff": 0.0, "extra_compactions": 0}
        ],
        "handoff_comparison": [
            {"threshold": 150000, "label": "150k", "compaction_usd": 10.0, "handoff_usd": 12.5, "saving_usd": -2.5, "saving_pct": -0.25}
        ],
    }
    report = mod.format_text_report(sample)
    assert "+$2.50 (-25.0%)" in report
    assert "-$-" not in report


def test_safe_mtime_handles_deleted_file(tmp_path):
    mod = load_module()
    missing = tmp_path / "missing.jsonl"
    assert mod._safe_mtime(str(missing)) == 0.0


def test_observed_compaction_reset(tmp_path, capsys):
    mod = load_module()
    proj = tmp_path / "test-proj"
    proj.mkdir(parents=True)

    # Transcript with a real compaction boundary
    u1 = {"input_tokens": 0, "cache_creation_input_tokens": 250000, "cache_read_input_tokens": 0, "output_tokens": 100}
    u2 = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100000, "output_tokens": 100}

    lines = [
        make_assistant_turn("m1", u1, timestamp="2026-11-12T12:00:00Z"),
        {"type": "system", "subtype": "compact_boundary"},
        make_assistant_turn("m2", u2, timestamp="2026-11-12T12:05:00Z"),
    ]
    (proj / "session_boundary.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    code = mod.main(["--root", str(tmp_path), "--thresholds", "200k", "--days", "30", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["requests"] == 2


def test_text_report_output(tmp_path, capsys):
    mod = load_module()
    proj = tmp_path / "test-proj"
    proj.mkdir(parents=True)

    u = {"input_tokens": 100, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 5000, "output_tokens": 100}
    lines = [make_assistant_turn("m1", u, timestamp="2026-11-12T12:00:00Z")]
    (proj / "s.jsonl").write_text(json.dumps(lines[0]) + "\n")

    code = mod.main(["--root", str(tmp_path), "--days", "30"])
    assert code == 0
    captured = capsys.readouterr().out
    assert "Claude Code Cache & Compaction Cost What-If Simulator" in captured
    assert "A. Cache TTL What-If" in captured
    assert "B. Compaction Threshold What-If" in captured
    assert "C. Fresh Handoff vs Compaction What-If" in captured
