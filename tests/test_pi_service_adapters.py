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
const hooks={};
serviceContext({on: (name, fn) => {hooks[name]=fn;}});
const hook=hooks.before_agent_start;
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


def test_request_metadata_excludes_content_headers_and_arguments(tmp_path):
    script = """
import {recordRequestMetadata} from './pi-extensions/service-context/index.mjs';
await recordRequestMetadata({model:'local-model',stream:true,messages:[{role:'system',content:'PRIVATE_PROMPT_SENTINEL'},{role:'user',content:'PRIVATE_USER_SENTINEL'}],tools:[{function:{name:'bash',parameters:{description:'PRIVATE_TOOL_SENTINEL'}}}],headers:{Authorization:'PRIVATE_AUTH_SENTINEL'},max_tokens:512,max_completion_tokens:{private:'PRIVATE_NESTED_SENTINEL'},params:{num_ctx:32768}},process.argv[1]);
"""
    subprocess.run(["node", "--input-type=module", "-e", script, str(tmp_path)], cwd=ROOT, check=True)
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"
    text = files[0].read_text()
    assert "PRIVATE_" not in text and "Authorization" not in text
    metadata = json.loads(text)
    assert metadata["tools"] == ["bash"]
    assert metadata["maxTokens"] == 512
    assert metadata["backendContext"] == 32768
    assert metadata["maxCompletionTokens"] is None
    assert metadata["messages"][0]["role"] == "system"
    assert files[0].stat().st_mode & 0o777 == 0o600


def test_metadata_hook_is_opt_in_and_sipb_only(tmp_path):
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
const hooks={};serviceContext({on:(name,fn)=>{hooks[name]=fn;}});
delete process.env.ADE_PI_REQUEST_METADATA_DIR;
await hooks.before_provider_request({payload:{model:'sipb'}},{model:{provider:'sipb'}});
process.env.ADE_PI_REQUEST_METADATA_DIR=process.argv[1];
await hooks.before_provider_request({payload:{model:'other'}},{model:{provider:'zai'}});
await hooks.before_provider_request({payload:{model:'missing'}},{});
"""
    subprocess.run(["node", "--input-type=module", "-e", script, str(tmp_path)], cwd=ROOT, check=True)
    assert list(tmp_path.iterdir()) == []


def test_metadata_hook_preserves_the_exact_request(tmp_path):
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
const hooks={};serviceContext({on:(name,fn)=>{hooks[name]=fn;}});
process.env.ADE_PI_REQUEST_METADATA_DIR=process.argv[1];
const payload={model:'sipb',messages:[{role:'user',content:'unchanged'}],tools:[],params:{num_ctx:32768}};
const before=JSON.stringify(payload);
const result=await hooks.before_provider_request({payload},{model:{provider:'sipb'}});
if(result !== undefined || JSON.stringify(payload)!==before)throw Error('request changed');
"""
    subprocess.run(["node", "--input-type=module", "-e", script, str(tmp_path)], cwd=ROOT, check=True)
    assert len(list(tmp_path.iterdir())) == 1
