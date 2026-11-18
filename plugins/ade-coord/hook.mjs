import { homedir } from "node:os";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
const driver=fileURLToPath(new URL("../../bin/ade-coord",import.meta.url));
const controller=fileURLToPath(new URL("../../bin/ade_coord_controller.py",import.meta.url));
function configuration() {
  let file=process.env.ADE_COORD_CONFIG;
  if(!file) {
    try { file=JSON.parse(readFileSync(process.env.ADE_COORD_ENROLLMENT_MARKER??join(homedir(),".local/state/ade-coord/enrollment.json"),"utf8")).config; }
    catch(error) { if(error.code==="ENOENT") return null; throw new Error("ADE enrollment marker unavailable"); }
  }
  try { return JSON.parse(readFileSync(file,"utf8")); } catch { throw new Error("ADE enrollment unavailable"); }
}
function execute(argv,input,{signal}={}) {
  return new Promise((resolve,reject)=>{
    const child=spawn(process.env.ADE_COORD_PYTHON??"python3",argv,{detached:true,stdio:["pipe","pipe","ignore"]});
    let text="",failed=false;
    const stop=()=>{try{if(child.pid)process.kill(-child.pid,"SIGTERM");}catch{}};
    signal?.addEventListener("abort",stop,{once:true});
    if(signal?.aborted)stop();
    const timeout=setTimeout(stop,30000);
    child.stdout.on("data",d=>{text+=d; if(text.length>4*1024*1024)stop();});
    child.once("error",()=>{failed=true;});
    child.once("close",code=>{clearTimeout(timeout);signal?.removeEventListener("abort",stop);try{const value=JSON.parse(text);if(failed||code!==0||!value.ok)throw new Error();resolve(value.result);}catch{reject(new Error("ADE controller failed closed"));}});
    child.stdin.end(JSON.stringify(input??{}));
  });
}
export function contribute(server,deps={}) {
  const read=deps.configuration??configuration, run=deps.execute??execute;
  const schedule=deps.setInterval??setInterval, cancel=deps.clearInterval??clearInterval;
  const abort=new AbortController(), inflight=new Map(); let stopped=false;
  const pump=()=>{
    if(stopped) return;
    let cfg; try{cfg=read();}catch{return;}
    for(const [role,settings] of Object.entries(cfg?.roles??{})) {
      if(settings.controller!==true||inflight.has(role)) continue;
      const pending=run([controller,"--role",role],{}, {signal:abort.signal}).catch(()=>{}).finally(()=>inflight.delete(role));
      inflight.set(role,pending);
    }
  };
  const remove=server.addHook("agent.open.before",async({request})=>{
    const cfg=read(); const enrolled=request.labels?.["ade.coord.role"];
    const role=enrolled??cfg?.aliases?.[request.agentId];
    if(!role) return;
    if(!cfg?.roles?.[role]) throw new Error("Enrolled role configuration missing");
    const current=await run([driver,"role","get"],{role_id:role},{signal:abort.signal});
    if(current?.record?.state!=="active"||current.record.owner.agent!==request.agentId) throw new Error("Current active enrolled role authority required");
    if(request.purpose==="history") return;
    return {...request,env:{...request.env,ADE_COORD_ROLE:role},appendSystemPrompt:[...(request.appendSystemPrompt??[]),"This role uses durable ADE inbox intake. Routine prompt acknowledgements are suppressed. Queued notifications and turn completion do not prove processing. Use the ADE inbox read/dispose commands; processing requires an explicit disposition under current authority."]};
  });
  const timer=schedule(pump,30000); pump();
  return async()=>{stopped=true;cancel(timer);remove();abort.abort();await Promise.allSettled([...inflight.values()]);};
}
