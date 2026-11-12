import { applyYoloToCreateRequest, assertResumeConfig, assertResumeIdentity, isExempt, isLegacyWithoutEvidence,
  providerId } from "./yolo-lib.mjs";

async function nativeEvidence(paseo, config) {
  if (!paseo?.providers?.snapshot) throw new Error("ade-yolo: native catalog API unavailable; update host");
  const snapshot = await paseo.providers.snapshot({ cwd: config.cwd });
  const entries = snapshot?.entries;
  const matches = Array.isArray(entries) ? entries.filter(e => e.provider === providerId(config.provider)) : [];
  if (snapshot?.error || matches.length !== 1) throw new Error("ade-yolo: exact provider catalog unavailable/ambiguous");
  const catalog = matches[0];
  let controls;
  if (providerId(config.provider) === "cursor") {
    if (!paseo.providers.listControls) throw new Error("ade-yolo: native controls API unavailable");
    controls = await paseo.providers.listControls(config);
  }
  return { catalog, controls };
}

/** create.before is awaited by native Paseo; exceptions refuse the create. */
export function registerAdeYoloHooks(server) {
  const offCreate = server.addHook("agent.create.before", async ({ request }, { paseo }) => {
    if (isExempt(request.config, request.metadata)) return;
    const { catalog, controls } = await nativeEvidence(paseo, request.config);
    return applyYoloToCreateRequest(request, catalog, controls);
  });
  const offOpen = server.addHook("agent.open.before", async ({ request }, { paseo, logger }) => {
    const log = msg => (logger?.warn ?? logger?.info ?? console.warn).call(logger ?? console, msg);
    // Create has just passed the config gate. History does not launch a runtime.
    if (request.reason === "create" || request.purpose === "history" || isExempt({}, request.metadata)) return;
    if (!paseo?.agents?.ref) throw new Error("ade-yolo: native agent snapshot API unavailable");
    const agent = paseo.agents.ref(request.agentId);
    const refreshed = await agent.refresh();
    const snapshot = refreshed?.agent;
    assertResumeIdentity(snapshot, request);
    if (isExempt({ modeId: snapshot.currentModeId }, request.metadata)) return;
    // Legacy agent with no saved evidence (pre-plugin, Hermes): allow and log before any catalog lookup.
    if (isLegacyWithoutEvidence(snapshot, request)) {
      log(`ade-yolo: ${request.agentId}: legacy agent without saved mode evidence; allowed`);
      return;
    }
    const config = { provider: request.provider, cwd: request.cwd,
      modeId: snapshot?.currentModeId, providerOptions: snapshot?.options };
    const { catalog, controls } = await nativeEvidence(paseo, config);
    assertResumeConfig(snapshot, request, catalog, controls, log);
  });
  return () => { offCreate(); offOpen(); };
}
