import {test} from "node:test";
import assert from "node:assert/strict";
import {isDeepStrictEqual} from "node:util";
import {z} from "zod";
import {mkdtemp,writeFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createHash} from "node:crypto";
import {contribute,execute} from "../../../plugins/ade-coord/server/hook.mjs";
import {resolveRuntimePaths} from "../../../plugins/ade-coord/server/runtime-paths.mjs";
import {fileURLToPath} from "node:url";
// Audited beta.2 source 23bae61535542a45ade7196a7b3c152705f16de3,
// lifecycle/index.ts:97-115,229-256. Exact strict top-level schema and immutable
// target validation. Empty tools/MCP fixture: nested definitions are not exercised.
const audited=z.object({agentId:z.string(),workspaceId:z.string().nullable(),provider:z.string(),cwd:z.string(),reason:z.enum(["create","resume","refresh","import"]),purpose:z.enum(["interactive","history"]),title:z.string().nullable(),background:z.boolean().optional(),labels:z.record(z.string(),z.string()),metadata:z.record(z.string(),z.unknown()).optional(),tools:z.array(z.unknown()),env:z.record(z.string(),z.string()),mcpServers:z.record(z.string(),z.unknown())}).strict();
const validate=(input,output)=>{
  const prior=audited.parse(input),next=audited.parse(output??input);
  for(const key of ["agentId","workspaceId","provider","cwd","reason","purpose","title","background","labels","metadata"])assert.ok(isDeepStrictEqual(prior[key],next[key]));
  return next;
};
const request=(agentId="a",purpose="interactive")=>({agentId,workspaceId:null,provider:"codex",cwd:"/controlled",reason:"resume",purpose,title:null,labels:{},tools:[],mcpServers:{},env:{KEEP:"yes"}});
test("beta.2 schema and waiting open fence reject drain/stale queued wakes before provider launch",async()=>{
  let handler,tick,removed=false,cancelled=false,aborted=false,release,delay=false;
  const root=await mkdtemp(join(tmpdir(),"ade-plugin-schema-"));
  const marker=join(root,"admission-"+createHash("sha256").update("r").digest("hex")+".json");
  let live={record:{role_id:"r",generation:"g",ownership_epoch:1,state:"active",owner:{host:"h",server:"s",agent:"a"}}};
  const cfg={generation:"g",state_dir:root,identity:{host:"h",server:"s"},roles:{r:{controller:true}},aliases:{a:"r",b:"r",stale:"r"}};
  const cleanup=contribute({addHook(name,fn){assert.equal(name,"agent.open.before");handler=fn;return()=>removed=true;}},{configuration:()=>cfg,setInterval(fn,ms){tick=fn;assert.equal(ms,30000);return 5;},clearInterval(id){assert.equal(id,5);cancelled=true;},execute:async(args,input,{signal})=>{signal.addEventListener("abort",()=>aborted=true);if(!input.role_id)return {};if(delay)return new Promise(resolve=>release=()=>resolve(structuredClone(live)));return structuredClone(live);}});
  try{
    assert.equal(await handler({request:request("legacy")}),undefined);
    const input=request(),result=validate(input,await handler({request:input}));assert.equal(result.env.ADE_COORD_ROLE,"r");assert.equal(result.env.KEEP,"yes");assert.match(result.env.PATH.split(process.platform==="win32"?";":":")[0],/libexec\/agent-bin$/);assert.match(result.env.ADE_COORD_INSTRUCTIONS,/nats-coordination.md$/);
    const history=request("a","history");validate(history,await handler({request:history}));assert.throws(()=>validate(input,{...result,appendSystemPrompt:["unsupported"]}));await assert.rejects(handler({request:request("stale")}));
    const proof={role_id:"r",generation:"g",owner:live.record.owner,ownership_epoch:1,state:"draining",attempt_id:"one"};await writeFile(marker,JSON.stringify(proof));await assert.rejects(handler({request:request("a")}));
    await writeFile(marker,JSON.stringify({...proof,state:"retired"}));live={record:{...live.record,ownership_epoch:2,owner:{host:"h",server:"s",agent:"b"}}};
    await assert.rejects(handler({request:request("a")}));await assert.rejects(handler({request:request("a","history")}));validate(request("b"),await handler({request:request("b")}));
    // A role read begun before the marker must be checked again after RPC.
    await rm(marker);live={record:{...live.record,ownership_epoch:3,owner:{host:"h",server:"s",agent:"a"}}};delay=true;
    const opening=handler({request:request("a")});const rejected=assert.rejects(opening);await Promise.resolve();
    await writeFile(marker,JSON.stringify({...proof,ownership_epoch:3}));release();await rejected;
    tick();
  }finally{await cleanup();await rm(root,{recursive:true,force:true});}
  assert.ok(removed&&cancelled&&aborted);
});

test("executor escalates actual SIGTERM-resistant child to SIGKILL within bounded deadline",async()=>{
  const prior=process.env.ADE_COORD_PYTHON;process.env.ADE_COORD_PYTHON=process.execPath;
  let failure;
  try{await assert.rejects(execute(["-e","process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{}, {timeoutMs:1000,killGraceMs:150}),error=>{failure=error;return error.code==="EXECUTOR_TIMEOUT";});}
  finally{if(prior===undefined)delete process.env.ADE_COORD_PYTHON;else process.env.ADE_COORD_PYTHON=prior;}
  assert.ok(failure.pid);assert.throws(()=>process.kill(failure.pid,0),{code:"ESRCH"});
});


test("runtime root uses canonical installed record and refuses absent/relative or wrong-layout records",async()=>{
  const home=await mkdtemp(join(tmpdir(),"ade-plugin-record-"));
  const root=fileURLToPath(new URL("../../../",import.meta.url));
  try{
    assert.throws(()=>resolveRuntimePaths({env:{PASEO_HOME:home}}),/install record unavailable/);
    assert.throws(()=>resolveRuntimePaths({env:{PASEO_HOME:"relative"}}),/install record unavailable/);
    await writeFile(join(home,"config.json"),JSON.stringify({plugins:{"ade-coord":{path:join(root,"plugins/ade-coord")}}}),{mode:0o600});
    const paths=resolveRuntimePaths({env:{PASEO_HOME:home}});
    assert.equal(paths.source,"paseo-install-record");assert.equal(paths.driver,join(root,"bin/ade-coord"));
    await writeFile(join(home,"config.json"),JSON.stringify({plugins:{"ade-coord":{path:join(root,"plugins/ade-claim")}}}));
    assert.throws(()=>resolveRuntimePaths({env:{PASEO_HOME:home}}),/install record unavailable/);
  }finally{await rm(home,{recursive:true,force:true});}
});
