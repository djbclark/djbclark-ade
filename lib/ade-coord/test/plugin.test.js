import {test} from "node:test";
import assert from "node:assert/strict";
import {isDeepStrictEqual} from "node:util";
import {z} from "zod";
import {contribute,execute} from "../../../plugins/ade-coord/hook.mjs";
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
test("beta.2 strict schema accepts enrolled interactive/history and rejects invented prompt field",async()=>{
  let handler,tick,removed=false,cancelled=false,aborted=false;
  const cfg={roles:{r:{controller:true}},aliases:{a:"r",stale:"r"}};
  const cleanup=contribute({addHook(name,fn){assert.equal(name,"agent.open.before");handler=fn;return()=>removed=true;}},{configuration:()=>cfg,setInterval(fn,ms){tick=fn;assert.equal(ms,30000);return 5;},clearInterval(id){assert.equal(id,5);cancelled=true;},execute:async(args,input,{signal})=>{signal.addEventListener("abort",()=>aborted=true);return input.role_id?{record:{state:"active",owner:{agent:"a"}}}:{};}});
  assert.equal(await handler({request:request("legacy")}),undefined);
  const input=request(),result=validate(input,await handler({request:input}));assert.equal(result.env.ADE_COORD_ROLE,"r");assert.equal(result.env.KEEP,"yes");assert.match(result.env.ADE_COORD_INSTRUCTIONS,/nats-coordination.md$/);
  const history=request("a","history");validate(history,await handler({request:history}));
  assert.throws(()=>validate(input,{...result,appendSystemPrompt:["unsupported"]}));
  await assert.rejects(handler({request:request("stale")}));tick();await cleanup();assert.ok(removed&&cancelled&&aborted);
});
test("executor escalates actual SIGTERM-resistant child to SIGKILL within bounded deadline",async()=>{
  const prior=process.env.ADE_COORD_PYTHON;process.env.ADE_COORD_PYTHON=process.execPath;
  let failure;
  try{await assert.rejects(execute(["-e","process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{}, {timeoutMs:1000,killGraceMs:150}),error=>{failure=error;return error.code==="EXECUTOR_TIMEOUT";});}
  finally{if(prior===undefined)delete process.env.ADE_COORD_PYTHON;else process.env.ADE_COORD_PYTHON=prior;}
  assert.ok(failure.pid);assert.throws(()=>process.kill(failure.pid,0),{code:"ESRCH"});
});
