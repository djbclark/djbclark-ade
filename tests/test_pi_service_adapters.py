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


def test_sipb_reminder_retains_original_task_after_tool_result():
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
const hooks={};serviceContext({on:(name,fn)=>{hooks[name]=fn;}});
process.env.ADE_PI_SIPB_TASK_REMINDER='1';
const ctx={model:{provider:'sipb'}};
hooks.before_agent_start({messageType:'user',prompt:'ORIGINAL_TASK',systemPromptOptions:{skills:[]}},ctx);
const messages=[{role:'user',content:'ORIGINAL_TASK'},{role:'toolResult',content:[{type:'text',text:'TOOL_RESULT_SENTINEL'}]}];
const result=hooks.context({messages},ctx);
if(result.messages.length!==3 || result.messages[0]!==messages[0] || result.messages[1]!==messages[1])throw Error('history changed');
const reminder=result.messages[2];
if(reminder.role!=='user' || !reminder.content[0].text.includes('ORIGINAL_TASK') || !reminder.content[0].text.includes('Do not repeat completed operations') || reminder.content[0].text.includes('TOOL_RESULT_SENTINEL'))throw Error('wrong reminder source');
if(messages.length!==2)throw Error('mutated transcript');
"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=True)


def test_reminder_is_opt_in_and_skips_initial_requests_other_models():
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
const hooks={};serviceContext({on:(name,fn)=>{hooks[name]=fn;}});
const ctx={model:{provider:'sipb'}};
hooks.before_agent_start({messageType:'user',prompt:'TASK',systemPromptOptions:{skills:[]}},ctx);
const afterTool={messages:[{role:'toolResult',content:[]}]};
delete process.env.ADE_PI_SIPB_TASK_REMINDER;
if(hooks.context(afterTool,ctx)!==undefined)throw Error('not opt in');
process.env.ADE_PI_SIPB_TASK_REMINDER='1';
if(hooks.context({messages:[{role:'user',content:'TASK'}]},ctx)!==undefined || hooks.context(afterTool,{model:{provider:'zai'}})!==undefined)throw Error('scope');
"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=True)


def test_reminder_clears_after_end_custom_run_and_model_switch():
    script = """
import serviceContext from './pi-extensions/service-context/index.mjs';
const hooks={};serviceContext({on:(name,fn)=>{hooks[name]=fn;}});
process.env.ADE_PI_SIPB_TASK_REMINDER='1';
const ctx={model:{provider:'sipb'}};
const start=()=>hooks.before_agent_start({messageType:'user',prompt:'TASK',systemPromptOptions:{skills:[]}},ctx);
const event={messages:[{role:'toolResult',content:[]}]};
start();hooks.agent_end({});if(hooks.context(event,ctx)!==undefined)throw Error('stale after end');
start();hooks.before_agent_start({messageType:'custom',systemPromptOptions:{skills:[]}},ctx);if(hooks.context(event,ctx)!==undefined)throw Error('stale custom');
start();hooks.before_agent_start({messageType:'user',prompt:'OTHER',systemPromptOptions:{skills:[]}},{model:{provider:'zai'}});if(hooks.context(event,ctx)!==undefined)throw Error('stale model');
"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=True)
