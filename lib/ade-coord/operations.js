import { randomUUID } from "node:crypto";
import { headers } from "@nats-io/nats-core";
import { CoordError, canonicalJSON, digest, safeToken, subject } from "./index.js";
const encode = value => new TextEncoder().encode(canonicalJSON(value));
export class SharedOperations {
  constructor(core) { this.core = core; }
  key(role, id) { return `ade.v1.operation.${safeToken(role)}.${safeToken(id)}`; }
  inspect(role, id) { return this.core.read(this.key(role,id)); }
  async list(role) {
    const latest = new Map(), info = await this.core.manager.streams.info("ADE_COORD_V1");
    const prefix = `ade.v1.operation.${safeToken(role)}.`;
    for (let seq = info.state.first_seq; seq <= info.state.last_seq; seq++) {
      const message = await this.core.manager.streams.getMessage("ADE_COORD_V1", {seq});
      if (message?.subject.startsWith(prefix)) latest.set(message.subject, {record:JSON.parse(new TextDecoder().decode(message.data)), revision:message.seq});
    }
    for (const value of latest.values()) if (value.record.generation !== this.core.generation) throw new CoordError("GENERATION", "Operation generation mismatch");
    return [...latest.values()];
  }
  async write(snapshot,id,record,expected) {
    const core = this.core;
    await core.assertSnapshot(snapshot);
    const h=headers(); h.set("Nats-Expected-Last-Subject-Sequence",String(snapshot.revision)); h.set("Nats-Expected-Last-Subject-Sequence-Subject",subject("role",snapshot.record.role_id));
    const last=headers(); last.set("Nats-Expected-Last-Subject-Sequence",String(expected));
    try {
      const batch=await core.js.startBatch(subject("guard",snapshot.record.role_id,randomUUID()),encode({operation_id:id}),{headers:h});
      await batch.commit(this.key(snapshot.record.role_id,id),encode(record),{headers:last});
    } catch(error) {
      const found=await this.inspect(snapshot.record.role_id,id);
      if (found && digest(found.record)===digest(record)) return found;
      throw new CoordError("UNKNOWN","Operation write uncertain; inspect stable id before action",error);
    }
    return this.inspect(snapshot.record.role_id,id);
  }
  async intent(snapshot,id,intent) {
    if(snapshot.record.state!=="active") throw new CoordError("STALE","New operation requires active authority");
    await this.core.assertSnapshot(snapshot);
    const prior=await this.inspect(snapshot.record.role_id,id), sha=digest(intent);
    if(prior) {
      if(prior.record.generation!==this.core.generation) throw new CoordError("GENERATION","Operation generation mismatch");
      if(prior.record.digest!==sha) throw new CoordError("IMMUTABLE","Operation id content conflict");
      return prior;
    }
    return this.write(snapshot,id,{id,intent,digest:sha,generation:this.core.generation,state:"UNKNOWN",authority:{owner:snapshot.record.owner,epoch:snapshot.record.ownership_epoch,revision:snapshot.revision}},0);
  }
  async reconcile(snapshot,id,{state,result,evidence}) {
    if(!["active","draining"].includes(snapshot.record.state)) throw new CoordError("STALE","Endpoint reconciliation requires active or draining authority");
    if(!["SUCCEEDED","NOT_APPLIED"].includes(state)||!evidence) throw new CoordError("INVALID","Explicit endpoint evidence required");
    await this.core.assertSnapshot(snapshot);
    const prior=await this.inspect(snapshot.record.role_id,id);
    if(!prior) throw new CoordError("INVALID","Missing operation intent");
    if(prior.record.generation!==this.core.generation) throw new CoordError("GENERATION","Operation generation mismatch");
    const resolved={state,result,evidence};
    if(prior.record.state!=="UNKNOWN") {
      if(digest(prior.record.resolution)!==digest(resolved)) throw new CoordError("IMMUTABLE","Operation already reconciled differently");
      return prior;
    }
    return this.write(snapshot,id,{...prior.record,state,resolution:resolved},prior.revision);
  }
}
