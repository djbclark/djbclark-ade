/**
 * Pure helpers for ade-yolo (no Paseo daemon I/O).
 *
 * Keep the provider → mode map aligned with bin/paseo_yolo.py.
 */

/** @type {Record<string, { modeId: string, featureValues?: Record<string, unknown> }>} */
export const YOLO_BY_PROVIDER = {
  claude: { modeId: "bypassPermissions" },
  codex: { modeId: "full-access" },
  opencode: { modeId: "build", featureValues: { auto_accept: true } },
  omp: { modeId: "full" },
  // cursor / pi / antigravity / hermes / muse: leave alone (dynamic or unverified).
};

export const PROMPTING_MODE_IDS = new Set([
  "default",
  "auto",
  "acceptEdits",
  "auto-review",
]);

export const RESTRICTIVE_MODE_IDS = new Set([
  "plan",
  "read-only",
  "dontAsk",
]);

export const UNATTENDED_MODE_IDS = new Set([
  "bypassPermissions",
  "bypass",
  "full-access",
  "full",
  "build",
  "danger-full-access",
  "yolo",
]);

export const SKIP_METADATA_KEY = "ade-yolo.skip";

/**
 * @param {unknown} provider
 * @returns {string}
 */
export function providerId(provider) {
  const raw = typeof provider === "string" ? provider.trim() : "";
  if (!raw) return "";
  return raw.split("/", 1)[0];
}

/**
 * @param {Record<string, unknown> | null | undefined} metadata
 * @returns {boolean}
 */
export function shouldSkip(metadata) {
  if (!metadata || typeof metadata !== "object") return false;
  const v = metadata[SKIP_METADATA_KEY];
  return v === true || v === 1 || v === "1" || v === "true" || v === "yes";
}

/**
 * @param {{ provider?: unknown, modeId?: unknown, featureValues?: unknown, providerOptions?: unknown }} config
 * @param {Record<string, unknown> | null | undefined} metadata
 * @returns {null | { modeId: string, featureValues?: Record<string, unknown> }}
 */
export function planYoloPatch(config, metadata) {
  if (shouldSkip(metadata)) return null;
  const cfg = config && typeof config === "object" ? config : {};
  const modeRaw = cfg.modeId;
  const modeId = modeRaw == null || modeRaw === "" ? null : String(modeRaw);
  if (modeId && RESTRICTIVE_MODE_IDS.has(modeId)) return null;

  const provider = providerId(cfg.provider);
  const yolo = YOLO_BY_PROVIDER[provider];
  if (!yolo) return null;

  // Already unattended: still ensure OpenCode auto_accept (and similar).
  if (modeId && UNATTENDED_MODE_IDS.has(modeId)) {
    if (!yolo.featureValues) return null;
    const current =
      cfg.featureValues && typeof cfg.featureValues === "object" ? cfg.featureValues : {};
    let changed = false;
    const next = { ...current };
    for (const [k, v] of Object.entries(yolo.featureValues)) {
      if (next[k] !== v) {
        next[k] = v;
        changed = true;
      }
    }
    return changed ? { modeId, featureValues: next } : null;
  }

  // Missing, prompting (Always Ask / auto / …), or any other non-restrictive mode → YOLO.
  /** @type {{ modeId: string, featureValues?: Record<string, unknown> }} */
  const patch = { modeId: yolo.modeId };
  if (yolo.featureValues) {
    const current =
      cfg.featureValues && typeof cfg.featureValues === "object" ? cfg.featureValues : {};
    patch.featureValues = { ...current, ...yolo.featureValues };
  }
  return patch;
}

/**
 * Apply a YOLO patch onto a create-before request.
 *
 * @param {{ config?: Record<string, unknown>, env?: unknown, metadata?: Record<string, unknown> }} request
 * @returns {undefined | { config: Record<string, unknown>, env?: unknown, metadata?: Record<string, unknown> }}
 */
export function applyYoloToCreateRequest(request) {
  if (!request || typeof request !== "object") return undefined;
  const config = request.config && typeof request.config === "object" ? request.config : {};
  const patch = planYoloPatch(config, request.metadata);
  if (!patch) return undefined;
  const nextConfig = { ...config, modeId: patch.modeId };
  if (patch.featureValues) nextConfig.featureValues = patch.featureValues;
  return { ...request, config: nextConfig };
}
