import { homedir } from "node:os";
import { join, delimiter } from "node:path";
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
  try { return {...JSON.parse(readFileSync(file,"utf8")),_adeConfigPath:file}; } catch { throw new Error("ADE enrollment unavailable"); }
}
export function execute(argv,input,{signal,timeoutMs=30000,killGraceMs=2000}={}) {
  return new Promise((resolve,reject)=>{
    const allowed=new Set(["PATH","HOME","XDG_CONFIG_HOME","LANG","LC_ALL","LC_CTYPE","TMPDIR","TMP","TEMP","ADE_NATS_URL","ADE_COORD_CONFIG","ADE_COORD_NODE","ADE_COORD_ENROLLMENT_MARKER","ADE_STATE_DIR","ADE_COORD_METRICS","PASEO_HOME","PASEO_DAEMON_HOME"]);
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>allowed.has(key)));
    const child=spawn(process.env.ADE_COORD_PYTHON??"python3",argv,{env,detached:true,stdio:["pipe","pipe","ignore"]});
    let text="",failed=false,stopping=false,settled=false,hardTimer,finalTimer;
    const error=()=>Object.assign(new Error(stopping?"ADE controller timed out or was aborted":"ADE controller failed closed"),{code:stopping?"EXECUTOR_TIMEOUT":"EXECUTOR_FAILED",pid:child.pid});
    const rejectOnce=()=>{if(!settled){settled=true;reject(error());}};
    const kill=signalName=>{try{if(child.pid)process.kill(-child.pid,signalName);}catch{}};
    const stop=()=>{
      if(stopping)return; stopping=true;kill("SIGTERM");
      hardTimer=setTimeout(()=>kill("SIGKILL"),killGraceMs);
      finalTimer=setTimeout(rejectOnce,killGraceMs*2);
    };
    signal?.addEventListener("abort",stop,{once:true});
    if(signal?.aborted)stop();
    const timeout=setTimeout(stop,timeoutMs);
    child.stdout.on("data",d=>{text+=d;if(text.length>4*1024*1024)stop();});
    child.once("error",()=>{failed=true;});
    child.once("close",code=>{
      clearTimeout(timeout);clearTimeout(hardTimer);clearTimeout(finalTimer);signal?.removeEventListener("abort",stop);
      if(settled)return;
      try{const value=JSON.parse(text);if(stopping||failed||code!==0||!value.ok)throw new Error();settled=true;resolve(value.result);}
      catch{rejectOnce();}
    });
    child.stdin.on("error",()=>{});
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
    if(request.purpose==="history")return; // Read-only history obtains no grant.
    const cfg=read(); const enrolled=request.labels?.["ade.coord.role"];
    const role=enrolled??cfg?.aliases?.[request.agentId];
    if(!role) return;
    if(!cfg?.roles?.[role]) throw new Error("Enrolled role configuration missing");
    const current=await run([driver,"role","get"],{role_id:role},{signal:abort.signal});
    if(current?.record?.state!=="active"||current.record.owner.agent!==request.agentId) throw new Error("Current active enrolled role authority required");
    // beta.2's real strict schema permits env/tools/mcpServers only. The
    // enrolled role brief is supplied explicitly at creation, never here.
    return {...request,env:{...request.env,ADE_COORD_ROLE:role,ADE_COORD_CONFIG:cfg._adeConfigPath??request.env.ADE_COORD_CONFIG??process.env.ADE_COORD_CONFIG??"",PATH:fileURLToPath(new URL("../../libexec/agent-bin",import.meta.url))+delimiter+(request.env.PATH??process.env.PATH??""),ADE_COORD_INSTRUCTIONS:fileURLToPath(new URL("../../docs/nats-coordination.md",import.meta.url))}};
  });
  const timer=schedule(pump,30000); pump();
  return async()=>{stopped=true;cancel(timer);remove();abort.abort();await Promise.allSettled([...inflight.values()]);};
}
