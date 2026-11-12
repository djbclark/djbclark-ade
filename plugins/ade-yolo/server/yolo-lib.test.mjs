import assert from "node:assert/strict";
import { test } from "node:test";
import { applyYoloToCreateRequest, planYoloPatch, assertResumeConfig } from "./yolo-lib.mjs";
import { registerAdeYoloHooks } from "./hook.mjs";
const row = (provider="claude", ids=["auto","bypassPermissions"]) => ({provider,enabled:true,status:"ready",modes:ids.map(id=>({id}))});
const cfg = {provider:"claude/sonnet",modeId:"auto",cwd:"/repo"};
const control = {controls:[{type:"toggle",key:"auto_accept"}]};

test("all known current modes need actual catalog membership", () => {
  for (const [provider, mode] of [["claude","bypassPermissions"],["codex","full-access"],["antigravity","full-access"],["copilot","allow-all"]]) {
    assert.deepEqual(planYoloPatch({provider},{},row(provider,[mode])),{modeId:mode});
    assert.throws(()=>planYoloPatch({provider},{},row(provider,["default"])),/no source-backed/);
  }
});
test("unavailable and flattened catalogs never grant permissions",()=>{
  for (const catalog of [null,{...row(),enabled:false},{...row(),status:"loading"},{...row(),modes:"Bypass"},row("codex"),row("claude",["auto","auto"])])
    assert.throws(()=>planYoloPatch(cfg,{},catalog),/ade-yolo/);
});
test("explicit restrictive and external critical requests remain exempt",()=>{
  for (const modeId of ["plan","read-only","dontAsk"]) assert.equal(planYoloPatch({...cfg,modeId}),null);
  for (const metadata of [{"ade-yolo.skip":true},{"ade.work-scope":"external-security-critical"},{"ade.work-scope":"operator-restrictive"}])
    assert.equal(applyYoloToCreateRequest({config:cfg,metadata}),undefined);
});
test("Cursor requires advertised auto_accept and persists providerOptions",()=>{
  const catalog=row("cursor",[]);
  assert.throws(()=>planYoloPatch({provider:"cursor"},{},catalog),/no source-backed/);
  assert.deepEqual(planYoloPatch({provider:"cursor",providerOptions:{keep:1}},{},catalog,control),{providerOptions:{keep:1,auto_accept:true}});
  assert.throws(()=>planYoloPatch({provider:"cursor",modeId:"invented"},{},catalog,control),/absent/);
});
test("modeless/unverified and retired providers refuse instead of prompting fallback",()=>{
  for(const p of ["pi","hermes","muse","opencode","omp"]) assert.throws(()=>planYoloPatch({provider:p},{},row(p,[])),/ade-yolo/);
});
test("create preserves unrelated fields",()=>{
  const out=applyYoloToCreateRequest({config:{...cfg,title:"title",providerOptions:{keep:true}},env:{x:"y"}},row());
  assert.equal(out.config.modeId,"bypassPermissions"); assert.equal(out.config.title,"title"); assert.equal(out.env.x,"y");
});
test("resume drift or unavailable identity refuses; check never mutates snapshot",()=>{
  const request={agentId:"a",provider:"claude",metadata:{}};
  const snapshot={id:"a",provider:"claude",currentModeId:"bypassPermissions"};
  assertResumeConfig(snapshot,request,row());
  assert.throws(()=>assertResumeConfig({...snapshot,currentModeId:"auto"},request,row()),/drift/);
  assert.throws(()=>assertResumeConfig({...snapshot,id:"b"},request,row()),/identity/);
  assert.equal(snapshot.currentModeId,"bypassPermissions");
});
test("mismatched or missing snapshot never self-exempts through a restrictive mode",async()=>{
  const request={agentId:"a",provider:"claude",cwd:"/repo",reason:"resume",purpose:"interactive",metadata:{}};
  for (const mode of ["plan","read-only","dontAsk"]) {
    for (const bad of [{id:"b",provider:"claude"},{id:"a",provider:"codex"}])
      assert.throws(()=>assertResumeConfig({...bad,currentModeId:mode},request,row()),/identity/);
    assert.throws(()=>assertResumeConfig(null,request,row()),/identity/);
    assertResumeConfig({id:"a",provider:"claude",currentModeId:mode},request,row());
  }
  const hooks={}; registerAdeYoloHooks({addHook(n,h){hooks[n]=h;return()=>{};}});
  const paseoWith=agent=>({providers:{snapshot:async()=>({entries:[row()]})},agents:{ref:()=>({refresh:async()=>({agent})})}});
  await assert.rejects(hooks["agent.open.before"]({request},{paseo:paseoWith({id:"b",provider:"claude",currentModeId:"plan"})}),/identity/);
  await assert.rejects(hooks["agent.open.before"]({request},{paseo:paseoWith(undefined)}),/identity/);
  await hooks["agent.open.before"]({request},{paseo:paseoWith({id:"a",provider:"claude",currentModeId:"plan"})});
});
test("native hooks use catalog SDK and awaited exceptions stop ordinary create",async()=>{
  const hooks={}; let reads=0;
  const off=registerAdeYoloHooks({addHook(name,handler){hooks[name]=handler;return()=>delete hooks[name];}});
  const paseo={providers:{snapshot:async options=>{reads++;assert.equal(options.cwd,"/repo");return{entries:[row()]};}},agents:{ref:()=>({refresh:async()=>({agent:{id:"a",provider:"claude",currentModeId:"auto"}})})}};
  assert.equal((await hooks["agent.create.before"]({request:{config:cfg}},{paseo})).config.modeId,"bypassPermissions");
  await assert.rejects(hooks["agent.open.before"]({request:{agentId:"a",provider:"claude",cwd:"/repo",reason:"resume",purpose:"interactive"}},{paseo}),/drift/);
  await hooks["agent.open.before"]({request:{reason:"create"}},{paseo});
  assert.equal(reads,2); off(); assert.deepEqual(hooks,{});
});
test("missing SDK refuses without pretending patch enforcement",async()=>{
  const hooks={}; registerAdeYoloHooks({addHook(n,h){hooks[n]=h;return()=>{};}});
  await assert.rejects(hooks["agent.create.before"]({request:{config:cfg}},{paseo:{}}),/API unavailable/);
});
test("resume checks Cursor effective option; native duplicate catalogs refuse",async()=>{
  const request={agentId:"a",provider:"cursor",metadata:{}};
  const snapshot={id:"a",provider:"cursor",options:{auto_accept:false}};
  assert.throws(()=>assertResumeConfig(snapshot,request,row("cursor",[]),control),/auto_accept/);
  assertResumeConfig({...snapshot,options:{auto_accept:true}},request,row("cursor",[]),control);
  const hooks={}; registerAdeYoloHooks({addHook(n,h){hooks[n]=h;return()=>{};}});
  await assert.rejects(hooks["agent.create.before"]({request:{config:cfg}},{paseo:{providers:{snapshot:async()=>({entries:[row(),row()]})}}}),/ambiguous/);
});
