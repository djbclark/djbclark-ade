#!/usr/bin/env node
import { connect } from "@nats-io/transport-node";
import { Coordination, streamConfig, CoordError, LocalState, Delivery, Artifacts, SharedOperations, safeToken } from "./index.js";

let nc, state;
try {
  const args = process.argv.slice(2); const index = args.indexOf("--state-dir");
  let stateDir;
  if (index >= 0) { stateDir = args[index + 1]; if (!stateDir) throw new CoordError("INVALID", "Missing state directory"); args.splice(index, 2); }
  if (args.length !== 2) throw new CoordError("INVALID", "Expected documented command pair");
  const command = args.join(" ");
  const commands = ["role get", "role create", "role transition", "role transfer", "report publish", "report status", "inbox list", "inbox read", "inbox dispose", "inbox intake", "outbox status", "outbox reconcile", "operation intent", "operation inspect", "operation reconcile", "doctor check", "broker provision", "artifact read", "artifact upload", "shared-operation intent", "shared-operation inspect", "shared-operation reconcile", "shared-operation list"];
  if (!commands.includes(command)) throw new CoordError("INVALID", "Unsupported command");
  let text = ""; for await (const chunk of process.stdin) { text += chunk; if (text.length > 16 * 1024 * 1024) throw new CoordError("INVALID", "Input too large"); }
  let input; try { input = JSON.parse(text || "{}"); } catch { throw new CoordError("INVALID", "Expected JSON input"); }
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new CoordError("INVALID", "Expected JSON object");
  state = new LocalState(stateDir);
  let result, pending;
  if (command === "report publish") {
    const artifacts = (input.artifacts ?? []).map(a => {
      if (typeof a.base64 !== "string" || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(a.base64)) throw new CoordError("INVALID", "Invalid base64 artifact");
      return { bytes: new Uint8Array(Buffer.from(a.base64, "base64")), media_type: a.media_type };
    });
    pending = state.enqueue(input.report, artifacts); // Before connection/auth/network.
  }
  if (command === "outbox status") result = state.outbox();
  else if (command === "operation intent") result = state.operationIntent(input.id, input.intent);
  else if (command === "operation inspect") result = state.operationInspect(input.id);
  else if (command === "operation reconcile") result = state.operationReconcile(input.id, input);
  else {
    let url;
    try { url = new URL(process.env.ADE_NATS_URL); } catch { throw new CoordError("INVALID", "ADE_NATS_URL must be a valid broker URL"); }
    if (!["nats:", "tls:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || (url.pathname && url.pathname !== "/")) throw new CoordError("INVALID", "Broker URL must not contain authentication, query or path");
    safeToken(input.generation);
    nc = await connect({ servers: url.toString(), token: process.env.ADE_NATS_TOKEN, timeout: 5000, maxReconnectAttempts: 0 });
    const core = await Coordination.connect(nc, { generation: input.generation });
    const artifacts = new Artifacts(nc), delivery = new Delivery(core, state, artifacts);
    switch (command) {
      case "role get": result = await core.getRole(input.role_id); break;
      case "role create": result = await core.createRole(input.record); break;
      case "role transition": result = await core.transitionRole(input.snapshot, input); break;
      case "role transfer": result = await core.transferRole(input.snapshot, input); break;
      case "report publish": result = await delivery.flush(pending); break;
      case "report status": result = await core.reportStatus(input.role_id, input.message_id); break;
      case "inbox list": await delivery.authority(input.snapshot, input.authority); result = await core.listInbox(input.snapshot.record.role_id); break;
      case "inbox read": await delivery.authority(input.snapshot, input.authority); result = await core.reportStatus(input.snapshot.record.role_id, input.message_id); break;
      case "inbox intake": result = await delivery.intake(input.snapshot, input); break;
      case "inbox dispose": result = await delivery.dispose(input.snapshot, input); break;
      case "outbox reconcile": result = await delivery.reconcile(); break;
      case "artifact upload": result = await artifacts.upload(new Uint8Array(Buffer.from(input.base64, "base64")), input.media_type); break;
      case "artifact read": result = { base64: Buffer.from(await artifacts.readArtifact(input.artifact)).toString("base64") }; break;
      case "shared-operation intent": result = await new SharedOperations(core).intent(input.snapshot, input.id, input.intent); break;
      case "shared-operation inspect": result = await new SharedOperations(core).inspect(input.role_id, input.id); break;
      case "shared-operation list": result = await new SharedOperations(core).list(input.role_id); break;
      case "shared-operation reconcile": result = await new SharedOperations(core).reconcile(input.snapshot, input.id, input); break;
      case "broker provision": {
        if (input.confirm !== "ADE_COORD_V1") throw new CoordError("INVALID", "Explicit provisioning confirmation required");
        try { await core.manager.streams.info("ADE_COORD_V1"); }
        catch (error) { if (error?.api_error?.err_code !== 10059) throw error; await core.manager.streams.add(streamConfig()); }
        const { Objm } = await import("@nats-io/obj");
        await new Objm(nc).create("ADE_ARTIFACTS_V1", { storage: "file", ttl: 0 });
        const object = await core.manager.streams.info("OBJ_ADE_ARTIFACTS_V1");
        if (object.config.storage !== "file" || object.config.max_age !== 0) throw new CoordError("UNSUPPORTED", "Object Store storage or retention unsafe");
        result = { ...(await core.doctor()), object_store: "ADE_ARTIFACTS_V1", implicit: false }; break;
      }
      case "doctor check": result = await core.doctor(); break;
    }
  }
  process.stdout.write(JSON.stringify({ ok: true, result }) + "\n");
} catch (error) {
  // Never echo arbitrary server errors, input, URLs, tokens, paths or stack traces.
  const code = error instanceof CoordError ? error.code : "UNKNOWN";
  process.stdout.write(JSON.stringify({ ok: false, error: { code, message: "Coordination command failed; inspect safe status and reconcile stable IDs" } }) + "\n");
  process.exitCode = code === "INVALID" ? 2 : 1;
} finally { await nc?.close(); state?.close(); }
