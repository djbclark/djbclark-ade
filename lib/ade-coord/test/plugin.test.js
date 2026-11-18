import {test} from "node:test";
import assert from "node:assert/strict";
import {contribute} from "../../../plugins/ade-coord/hook.mjs";
test("documented plugin hook enrolls only current owner and tears down bounded machine pump",async()=>{
  let handler,tick,removed=false,cancelled=false,aborted=false;
  const cfg={roles:{r:{controller:true}},aliases:{a:"r",stale:"r"}};
  const cleanup=contribute({addHook(name,fn){assert.equal(name,"agent.open.before");handler=fn;return()=>removed=true;}},{configuration:()=>cfg,setInterval(fn,ms){tick=fn;assert.equal(ms,30000);return 5;},clearInterval(id){assert.equal(id,5);cancelled=true;},execute:async(args,input,{signal})=>{signal.addEventListener("abort",()=>aborted=true);return input.role_id?{record:{state:"active",owner:{agent:"a"}}}:{};}});
  assert.equal(await handler({request:{agentId:"legacy"}}),undefined);
  const result=await handler({request:{agentId:"a",env:{KEEP:"yes"}}});assert.equal(result.env.ADE_COORD_ROLE,"r");assert.equal(result.env.KEEP,"yes");assert.match(result.appendSystemPrompt[0],/do not prove processing/);
  await assert.rejects(handler({request:{agentId:"stale"}}));tick();await cleanup();assert.ok(removed&&cancelled&&aborted);
});
