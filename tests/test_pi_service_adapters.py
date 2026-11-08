import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def launcher():
    loader = importlib.machinery.SourceFileLoader("pi_cursor_agent", str(ROOT / "bin/pi-cursor-agent"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_print_mode_adds_force_without_changing_targets():
    args = ["--print", "--model", "composer-2.5", "--workspace", "/tmp/example", "do work"]
    assert launcher().launch_argv(args, "/bin/cursor-agent") == ["/bin/cursor-agent", "--force", *args]


def test_model_catalog_and_existing_force_are_preserved():
    module = launcher()
    for args in (["models"], ["--print", "--force", "hello"], ["--yolo", "-p", "hello"]):
        assert module.launch_argv(args, "/bin/cursor-agent") == ["/bin/cursor-agent", *args]


def test_sipb_catalog_reduction_preserves_instructions_and_tools():
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
let hook;
serviceContext({on: (name, fn) => {if (name !== 'before_agent_start') throw Error(name); hook=fn;}});
const make = () => ({systemPromptOptions:{skills:[{name:'big catalog'}], contextFiles:[{path:'AGENTS.md',content:'retain'}], customPrompt:'retain custom', appendSystemPrompt:'retain appended', selectedTools:['bash','codemode'],sections:{mcp_servers:'retain MCP'}}});
const sipb=make(); hook(sipb,{model:{provider:'sipb'}});
const other=make(); hook(other,{model:{provider:'zai'}});
const missing=make(); hook(missing,{});
console.log(JSON.stringify({sipb,other,missing}));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    options = data["sipb"]["systemPromptOptions"]
    assert options["skills"] == []
    assert options["contextFiles"] == [{"path": "AGENTS.md", "content": "retain"}]
    assert options["customPrompt"] == "retain custom"
    assert options["appendSystemPrompt"] == "retain appended"
    assert options["selectedTools"] == ["bash", "codemode"]
    assert options["sections"] == {"mcp_servers": "retain MCP"}
    assert data["other"] == data["missing"]
    assert len(data["other"]["systemPromptOptions"]["skills"]) == 1
