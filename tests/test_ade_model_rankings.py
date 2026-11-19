"""Tests for the zero-token model-rankings refresh (bin/ade-model-rankings).

Only the deterministic parts (score extraction, table rendering, cell formatting) are under test;
the live scrape is exercised by the launchd job against the self-hosted Firecrawl API.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "bin/ade-model-rankings"


def _load():
    loader = importlib.machinery.SourceFileLoader("ade_model_rankings", str(SRC))
    spec = importlib.util.spec_from_loader("ade_model_rankings", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ade_model_rankings"] = mod
    loader.exec_module(mod)
    return mod


def test_score_extracts_nearest_number_after_label():
    m = _load()
    text = "Gemini 4 Neon 59\nsome note 12\nClaude Fable 5.2 58"
    assert m._score(text, "Gemini 4 Neon") == 59.0
    assert m._score(text, "Claude Fable 5.2") == 58.0
    assert m._score(text, "Not On Board") is None


def test_cell_and_table_render_tier_and_dashes():
    m = _load()
    assert m._cell(59) == "59"
    assert m._cell(None) == "\u2014"
    snapshot = {"rows": [
        {"name": "Gemini 4 Neon", "coding_agent": 59, "intelligence": 61, "frontier": True},
        {"name": "Claude Opus 5.5", "coding_agent": None, "intelligence": 59, "frontier": False},
    ]}
    table = m._table(snapshot)
    assert "| Gemini 4 Neon | 59 | 61 | frontier |" in table
    assert "| Claude Opus 5.5 | \u2014 | 59 | near-frontier |" in table


def test_check_exits_3_on_missing_data(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "DATA", str(tmp_path / "nope.json"))
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        raised = False
        try:
            m.cmd_check(None)
        except SystemExit as e:
            raised = e.code == 3
    assert raised