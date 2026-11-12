/** Pure planning from native IDs/controls. Mirrors bin/paseo_yolo.py except Pi: the 2026-11-12 ruling admits a modeless Pi here, while the CLI planner still reports it unverified. */
export const YOLO_BY_PROVIDER = {
  claude: { modeId: "bypassPermissions" },
  codex: { modeId: "full-access" },
  antigravity: { modeId: "full-access" },
  copilot: { modeId: "allow-all" },
};
/** Providers that never raise permission requests; a modeless ready catalog needs no patch. */
export const UNATTENDED_BY_CONSTRUCTION = new Set(["pi"]);
export const STAMP_METADATA_KEY = "ade-yolo.applied";
export const RESTRICTIVE_MODE_IDS = new Set(["plan", "read-only", "dontAsk"]);
export const SKIP_METADATA_KEY = "ade-yolo.skip";
export const SCOPE_METADATA_KEY = "ade.work-scope";
export const RETIRED_PROVIDERS = ["omp", "opencode", "crush", "agy", "grok"];
/** Needs no catalog, so it also runs before the legacy resume allowance. */
export function assertNotRetired(provider) {
  if (RETIRED_PROVIDERS.includes(provider))
    throw new Error(`ade-yolo: ${provider}: retired client is not an ordinary dispatch route`);
}
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
  assertNotRetired(provider);
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
  // Operator ruling 2026-11-12: Pi never raises permission requests, so a modeless Pi catalog is
  // unattended by construction. Explicit allowlist: no other modeless provider (Hermes, unknown) is
  // generalised from this. A Pi catalog that DOES list modes falls through to the refusal below.
  if (UNATTENDED_BY_CONSTRUCTION.has(provider) && ids.length === 0) return {};
  return unavailable("no source-backed/catalog-marked unattended mode or supported control");
}
export function applyYoloToCreateRequest(request, catalog, controls) {
  const config = request?.config ?? {};
  const patch = planYoloPatch(config, request?.metadata, catalog, controls);
  // The stamp marks agents this plugin created: only they must carry saved-mode evidence on resume.
  return patch ? { ...request, config: { ...config, ...patch },
    metadata: { ...request?.metadata, [STAMP_METADATA_KEY]: "1" } } : undefined;
}

/** Identity precedes any mode-based exemption: a mismatched snapshot must not exempt itself. */
export function assertResumeIdentity(snapshot, request) {
  if (!snapshot || snapshot.id !== request.agentId || snapshot.provider !== providerId(request.provider))
    throw new Error("ade-yolo: resume identity/readback unavailable");
}

const blank = v => v === undefined || v === null || v === "";
/** Saved evidence of unattended operation: a mode ID or an explicit auto_accept option. */
export function hasSavedEvidence(snapshot) {
  return !blank(snapshot?.currentModeId) || !blank(snapshot?.options?.auto_accept);
}
/**
 * An agent this plugin never stamped (created before install, with the plugin disabled, internal, or imported) is
 * legacy. Agents expose no install-time field, so "created before install" == "no stamp".
 */
export function isLegacyAgent(snapshot, request) {
  return blank(snapshot?.metadata?.[STAMP_METADATA_KEY]) && blank(request?.metadata?.[STAMP_METADATA_KEY]);
}
/** Legacy agent with no saved evidence at all (Hermes, pre-plugin agents): allowed, never refused. */
export function isLegacyWithoutEvidence(snapshot, request) {
  return isLegacyAgent(snapshot, request) && !hasSavedEvidence(snapshot);
}

/** Pre-open check only: this is not post-open runtime readback. `log` receives allow-with-note events. */
export function assertResumeConfig(snapshot, request, catalog, controls, log = () => {}) {
  assertResumeIdentity(snapshot, request);
  const config = { provider: request.provider, modeId: snapshot.currentModeId,
    providerOptions: snapshot.options };
  if (isExempt(config, request.metadata)) return;
  assertNotRetired(providerId(request.provider));
  if (isLegacyWithoutEvidence(snapshot, request)) {
    log(`ade-yolo: ${request.agentId}: legacy agent without saved mode evidence; allowed`);
    return;
  }
  const patch = planYoloPatch(config, request.metadata, catalog, controls);
  const legacy = isLegacyAgent(snapshot, request);
  if (patch.modeId) {
    if (blank(snapshot.currentModeId)) {
      if (!legacy) throw new Error("ade-yolo: saved mode evidence missing; explicit repair and readback required before resume");
      log(`ade-yolo: ${request.agentId}: legacy agent without saved mode; allowed`);
    } else if (snapshot.currentModeId !== patch.modeId)
      throw new Error("ade-yolo: saved mode drift; explicit repair and readback required before resume");
  }
  if (patch.providerOptions?.auto_accept === true) {
    if (blank(snapshot.options?.auto_accept)) {
      if (!legacy) throw new Error("ade-yolo: saved auto_accept is unverified; explicit repair required before resume");
      log(`ade-yolo: ${request.agentId}: legacy agent without saved auto_accept; allowed`);
    } else if (snapshot.options.auto_accept !== true)
      throw new Error("ade-yolo: saved auto_accept is unverified; explicit repair required before resume");
  }
}
