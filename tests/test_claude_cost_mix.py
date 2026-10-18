"""bin/claude-cost-mix on a synthetic transcript."""
import importlib.machinery
import importlib.util
import json
import pathlib

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin" / "claude-cost-mix"


def load():
    loader = importlib.machinery.SourceFileLoader("claude_cost_mix", str(BIN))
    spec = importlib.util.spec_from_loader("claude_cost_mix", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def assistant(mid, usage, content=()):
    return {"type": "assistant", "message": {"id": mid, "usage": usage, "content": list(content)}}


def write_transcript(root):
    proj = root / "proj"
    proj.mkdir(parents=True)
    u1 = {"input_tokens": 0, "cache_creation_input_tokens": 1000,
          "cache_read_input_tokens": 0, "output_tokens": 0}
    u2 = {"input_tokens": 0, "cache_creation_input_tokens": 0,
          "cache_read_input_tokens": 250_000, "output_tokens": 0}
    lines = [
        assistant("m1", u1, [{"type": "tool_use", "id": "t1", "name": "Bash",
                              "input": {"command": "rg -n foo src"}}]),
        # same message id repeated for a second content block: usage counted once
        assistant("m1", u1, [{"type": "tool_use", "id": "t2", "name": "Bash",
                              "input": {"command": "pytest -q"}}]),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 400},
            {"type": "tool_result", "tool_use_id": "t2", "content": [{"text": "y" * 4000}]},
        ]}},
        {"type": "system", "subtype": "compact_boundary"},
        assistant("m2", u2),
    ]
    (proj / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_mix_tools_and_buckets(tmp_path, capsys):
    write_transcript(tmp_path)
    mod = load()
    assert mod.main(["--root", str(tmp_path), "--json", "--write", "2", "--read", "0.1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["requests"] == 2 and out["compactions"] == 1
    # cache write 1000*2 = 2000, cache read 250000*0.1 = 25000
    assert out["total_units"] == 27_000
    assert abs(out["mix"]["cache_read"] - 25_000 / 27_000) < 1e-9
    assert abs(out["by_context"]["200-300k"] - 25_000 / 27_000) < 1e-9
    # rg result: 100 tokens * (2 + 0.1 * 1 later request); pytest output: 1000 tokens likewise
    assert out["tools"]["Bash:nav"]["calls"] == 1
    assert abs(out["tools"]["Bash:nav"]["share"] - 210 / 27_000) < 1e-9
    assert abs(out["tools"]["Bash:other"]["share"] - 2100 / 27_000) < 1e-9
    assert abs(out["navigation_share"] - 210 / 27_000) < 1e-9
    # first request 1000 tokens, second 250000: preamble 1000 * 0.1 + 1000 * 0.1
    assert abs(out["preamble_share"] - 200 / 27_000) < 1e-9
    assert out["median_first_context"]["main"] == 1000


def test_no_transcripts_exits_3(tmp_path):
    assert load().main(["--root", str(tmp_path)]) == 3


def test_labels():
    mod = load()
    lab = lambda cmd: mod.tool_label({"name": "Bash", "input": {"command": cmd}})
    assert lab("graft ask x") == "Bash:graft"
    assert lab("cd ~/src/a && graft grep y") == "Bash:graft"
    assert lab("cat f | head") == "Bash:nav"
    assert lab("git status") == "Bash:other"
    assert mod.tool_label({"name": "mcp__firecrawl__firecrawl_search"}) == "mcp:firecrawl"
