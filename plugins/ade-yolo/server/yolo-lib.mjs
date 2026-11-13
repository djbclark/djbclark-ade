/** Pure planning from native IDs/controls. Mirrors bin/paseo_yolo.py except Pi: the 2026-11-12 ruling admits a modeless Pi here, while the CLI planner still reports it unverified. */
export const YOLO_BY_PROVIDER = {
  claude: { modeId: "bypassPermissions" },
  codex: { modeId: "full-access" },
  antigravity: { modeId: "full-access" },
  copilot: { modeId: "allow-all" },
};
/** Providers that never raise permission requests; a modeless ready catalog needs no patch. */
export const UNATTENDED_BY_CONSTRUCTION = new Set(["pi"]);
/**
 * Providers that ATTACH to a process already running in a Herdr pane (herdr-harness plugin: `herdr-generic` and
 * `herdr-omp`; the opt-in shell binding is part of `herdr-generic`). Paseo starts nothing and cannot set a permission
 * mode there: the pane's own launch decides it, so ade-yolo's premise (Paseo sets the unattended mode at create/resume)
 * does not apply. Deliberately NOT in UNATTENDED_BY_CONSTRUCTION: a Claude pane in default mode does prompt. Report of
 * 2026-11-13 from agent 5fd0bef1 (paseo4herdr): every herdr chat open and session import was refused. Exact ids only,
 * never generalised to unknown or modeless providers.
 */
export const ATTACH_ONLY = new Set(["herdr-generic", "herdr-omp"]);
/**
 * Attach-only providers whose create can also LAUNCH a process. herdr-omp has a launch spec: a create without the
 * herdr-harness bind option (`providerOptions.herdrBind`) starts a fresh, retired `omp` in a new pane with no unattended
 * flag. Only a create that carries the bind option (an existing terminal) is attach-only; herdr-generic has no launch.
 */
export const ATTACH_OR_LAUNCH = new Set(["herdr-omp"]);
export const HERDR_BIND_OPTION = "herdrBind";
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
/** Exact id (an optional `/model` suffix is Paseo's own form): leading/trailing whitespace never matches. */
export function isAttachOnly(provider) {
  return typeof provider === "string" && provider === provider.trim() && ATTACH_ONLY.has(providerId(provider));
}
/** Create of an attach-only provider that binds an existing pane; herdr-omp without the bind option launches, so it is not one. */
export function isAttachOnlyCreate(config) {
  if (!isAttachOnly(config?.provider)) return false;
  if (!ATTACH_OR_LAUNCH.has(providerId(config.provider))) return true;
  const bind = config.providerOptions?.[HERDR_BIND_OPTION];
  return typeof bind?.terminalId === "string" && bind.terminalId !== "";
}
export const ATTACH_ONLY_NOTE = "attach-only: mode decided by the pane's launch";
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
  if (isAttachOnlyCreate(config)) return null; // no patch: Paseo launches nothing (see ATTACH_ONLY)
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
  // generalised from this. Pi with modes uses the catalog-marked rule above; unmarked modes refuse.
  if (UNATTENDED_BY_CONSTRUCTION.has(provider) && ids.length === 0) return {};
  return unavailable("no source-backed/catalog-marked unattended mode or supported control");
}
export function applyYoloToCreateRequest(request, catalog, controls, log = () => {}) {
  const config = request?.config ?? {};
  const patch = planYoloPatch(config, request?.metadata, catalog, controls);
  // Attach-only: unchanged and unstamped, so a later open reads as legacy rather than demanding saved-mode evidence.
  if (!patch && isAttachOnlyCreate(config) && !isExempt(config, request?.metadata)) {
    log(`ade-yolo: ${providerId(config.provider)}: create ${ATTACH_ONLY_NOTE}`);
    return undefined;
  }
  // The stamp marks agents this plugin created: only they must carry saved-mode evidence on resume.
  return patch ? { ...request, config: { ...config, ...patch },
    metadata: { ...request?.metadata, [STAMP_METADATA_KEY]: "1" } } : undefined;
}

/** Identity precedes any mode-based exemption: a mismatched snapshot must not exempt itself. */
export function assertResumeIdentity(snapshot, request) {
  if (!snapshot || snapshot.id !== request.agentId || snapshot.provider !== providerId(request.provider))
    throw new Error("ade-yolo: resume identity/readback unavailable");
}

/**
 * Open of an attach-only provider (resume, refresh or import). An import has no agent record yet, so no snapshot is
 * readable: that alone is allowed (reason "import" only), for this provider set only. Wherever a snapshot IS readable, identity is still checked.
 */
export function assertAttachOnlyOpen(snapshot, request, log = () => {}) {
  // Only an import may lack a snapshot (no agent record yet); a resume or refresh needs one, as for any provider.
  if (snapshot || request.reason !== "import") assertResumeIdentity(snapshot, request);
  log(`ade-yolo: ${providerId(request.provider)}: open ${ATTACH_ONLY_NOTE} (${snapshot ? "snapshot identity verified" : "no snapshot readable"})`);
}

const blank = v => v === undefined || v === null || v === "";
/** Saved evidence of unattended operation: a mode ID or an explicit auto_accept option. */
export function hasSavedEvidence(snapshot) {
  return !blank(snapshot?.currentModeId) || !blank(snapshot?.options?.auto_accept);
}
/**
 * An agent this plugin never stamped (created before install, with the plugin disabled, internal, or imported) is
 * legacy. Agents expose no install-time field, so "created before install" implies "no stamp" (the converse is false: disabled, internal and imported agents read as legacy too).
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
  if (isAttachOnly(request.provider)) return assertAttachOnlyOpen(snapshot, request, log);
  if (isLegacyAgent(snapshot, request)) {
    log(`ade-yolo: ${request.agentId}: provider=${providerId(request.provider)} saved mode=${JSON.stringify(snapshot.currentModeId ?? null)} auto_accept=${JSON.stringify(snapshot.options?.auto_accept ?? null)}; legacy agent allowed without mode mutation`);
    return;
  }
  const patch = planYoloPatch(config, request.metadata, catalog, controls);
  if (patch.modeId) {
    if (blank(snapshot.currentModeId)) {
      throw new Error("ade-yolo: saved mode evidence missing; explicit repair and readback required before resume");
    } else if (snapshot.currentModeId !== patch.modeId)
      throw new Error("ade-yolo: saved mode drift; explicit repair and readback required before resume");
  }
  if (patch.providerOptions?.auto_accept === true) {
    if (blank(snapshot.options?.auto_accept)) {
      throw new Error("ade-yolo: saved auto_accept is unverified; explicit repair required before resume");
    } else if (snapshot.options.auto_accept !== true)
      throw new Error("ade-yolo: saved auto_accept is unverified; explicit repair required before resume");
  }
}
