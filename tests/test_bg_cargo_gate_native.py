"""Optional native V2 permission proof. No model, compiler or existing server."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_native_cargo_permission_gate(tmp_path):
    opencode = shutil.which("opencode")
    if not opencode:
        pytest.skip("native OpenCode is not installed on this runner")
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    plugins = config / "plugins"
    plugins.mkdir(parents=True)
    shutil.copyfile(ROOT / "opencode-plugins/bg-cargo-gate.js", plugins / "gate.mjs")
    # Only canary.js auto-loads; it installs the exact production module above.
    (plugins / "canary.js").write_text(r'''
import gate from "./gate.mjs";
export default {
  id:"ade.bg-canary",
  async setup(ctx) {
    const disposeGate=await gate.setup(ctx);
    const rpc=await ctx.rpc.register({id:"ade.bg-canary",events:{},methods:{run:{
      input:{type:"object",properties:{},additionalProperties:false},
      output:{type:"object",properties:{ok:{type:"boolean"},checks:{type:"array",items:{type:"object",additionalProperties:true}}},required:["ok","checks"],additionalProperties:false}
    }}},{run:async()=>{
      const session=await ctx.session.create({title:"ADE bg native canary",permissions:[{action:"shell",resource:"*",effect:"allow"}]});
      const checks=[];
      const check=async(command,expected)=>{
        let allowed=true,message="";
        try {await ctx.permission.assert({sessionID:session.id,action:"shell",resources:[command]});}
        catch(error) {allowed=false;message=String(error?.message ?? error);}
        checks.push({command,expected,allowed,message});
      };
      try {
        await check("cd ~/src/sudo-secretspec && cargo build -p sudo-secretspec-cli --release 2>&1",false);
        await check("timeout 600 cargo build --release",false);
        await check("cargo install ripgrep --version 14.1.0",false);
        await check("if cargo build --release; then echo ok; fi",false);
        await check("rtk test cargo test",false);
        await check("$HOME/ops/site-private/bin/bg cargo build --release",true);
        await check("~/ops/site-private/bin/bg cargo test",true);
        await check("cargo --version",true);
        await check("echo 'cargo build'",true);
        const blocked="~/ops/site-private/bin/bg cargo test";
        await ctx.session.update({sessionID:session.id,permissions:[{action:"shell",resource:"*",effect:"allow"},{action:"shell",resource:blocked,effect:"deny"}]});
        await check(blocked,false);
        return {ok:checks.every(c=>c.allowed===c.expected),checks};
      } finally {await ctx.session.remove({sessionID:session.id});}
    }});
    return async()=>{await rpc.dispose();await disposeGate();};
  }
};
''')
    env = {**os.environ, "OPENCODE_CONFIG_DIR": str(config),
           "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
           "XDG_DATA_HOME": str(tmp_path / "data"),
           "XDG_STATE_HOME": str(tmp_path / "state"),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    result = subprocess.run(
        [opencode, "api", "--standalone", "post",
         f"/api/rpc/ade.bg-canary/run?location[directory]={project}",
         "--data", '{"input":{}}'],
        env=env, cwd=project, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    response = json.loads(result.stdout)
    data = response["output"]
    assert data.get("ok"), data
    assert len(data["checks"]) == 10
    assert "--release is not an exemption" in data["checks"][0]["message"]
