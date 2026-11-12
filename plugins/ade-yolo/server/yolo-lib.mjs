/** Pure planning from native IDs/controls. Keep parity with bin/paseo_yolo.py. */
export const YOLO_BY_PROVIDER = {
  claude: { modeId: "bypassPermissions" },
  codex: { modeId: "full-access" },
  antigravity: { modeId: "full-access" },
  copilot: { modeId: "allow-all" },
};
export const RESTRICTIVE_MODE_IDS = new Set(["plan", "read-only", "dontAsk"]);
export const SKIP_METADATA_KEY = "ade-yolo.skip";
export const SCOPE_METADATA_KEY = "ade.work-scope";
export function providerId(provider) {
  return typeof provider === "string" ? provider.trim().split("/", 1)[0] : "";
}
export function shouldSkip(metadata) {
  const value = metadata?.[SKIP_METADATA_KEY];
  return [true, 1, "1", "true", "yes"].includes(value) ||
    ["external-security-critical", "operator-restrictive"].includes(metadata?.[SCOPE_METADATA_KEY]);
}
export function isExempt(config, metadata) {
  return shouldSkip(metadata) || RESTRICTIVE_MODE_IDS.has(config?.modeId);
}

/** A provider's default is never proof of unattended operation. */
export function planYoloPatch(config, metadata, catalog, controls) {
  if (isExempt(config, metadata)) return null;
  const provider = providerId(config?.provider);
  const unavailable = reason => { throw new Error(`ade-yolo: ${provider}: ${reason}`); };
  if (["omp", "opencode", "crush", "agy", "grok"].includes(provider))
    return unavailable("retired client is not an ordinary dispatch route");
  if (!catalog || catalog.provider !== provider || catalog.enabled !== true || catalog.status !== "ready" || catalog.error)
    return unavailable("native provider catalog is not enabled/ready");
  if (!Array.isArray(catalog.modes) || catalog.modes.some(m => !m || typeof m.id !== "string" || !m.id))
    return unavailable("native mode IDs are missing; labels/defaultMode are insufficient");
  const ids = catalog.modes.map(m => m.id);
  if (new Set(ids).size !== ids.length) return unavailable("duplicate native mode IDs");
  let modeId = YOLO_BY_PROVIDER[provider]?.modeId;
  const marked = catalog.modes.filter(m => m.isUnattended === true);
  if (!ids.includes(modeId)) modeId = marked.length === 1 ? marked[0].id : null;
  if (modeId) return { modeId };
  if (provider === "cursor" && !controls?.error && Array.isArray(controls?.controls) &&
      controls.controls.some(c => c.type === "toggle" && c.key === "auto_accept")) {
    modeId = config.modeId ?? catalog.defaultModeId ?? null;
    if (modeId !== null && !ids.includes(modeId)) return unavailable("Cursor mode absent from native catalog");
    return { ...(modeId === null ? {} : { modeId }),
      providerOptions: { ...config.providerOptions, auto_accept: true } };
  }
  return unavailable(provider === "pi" && ids.length === 0
    ? "Pi is modeless; extension UI requests lack verified permission control"
    : "no source-backed/catalog-marked unattended mode or supported control");
}
export function applyYoloToCreateRequest(request, catalog, controls) {
  const config = request?.config ?? {};
  const patch = planYoloPatch(config, request?.metadata, catalog, controls);
  return patch ? { ...request, config: { ...config, ...patch } } : undefined;
}

/** Identity precedes any mode-based exemption: a mismatched snapshot must not exempt itself. */
export function assertResumeIdentity(snapshot, request) {
  if (!snapshot || snapshot.id !== request.agentId || snapshot.provider !== providerId(request.provider))
    throw new Error("ade-yolo: resume identity/readback unavailable");
}

/** Pre-open check only: this is not post-open runtime readback. */
export function assertResumeConfig(snapshot, request, catalog, controls) {
  assertResumeIdentity(snapshot, request);
  const config = { provider: request.provider, modeId: snapshot.currentModeId,
    providerOptions: snapshot.options };
  if (isExempt(config, request.metadata)) return;
  const patch = planYoloPatch(config, request.metadata, catalog, controls);
  if (patch.modeId && snapshot.currentModeId !== patch.modeId)
    throw new Error("ade-yolo: saved mode drift; explicit repair and readback required before resume");
  if (patch.providerOptions?.auto_accept === true && snapshot.options?.auto_accept !== true)
    throw new Error("ade-yolo: saved auto_accept is unverified; explicit repair required before resume");
}
