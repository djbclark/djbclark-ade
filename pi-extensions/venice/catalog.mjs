// Dynamic catalog loader for Venice.ai's public /api/v1/models endpoint.
// Uses a short-TTL on-disk cache and falls back cleanly to stale cache or
// bundled models.json so Pi startup stays fast and never blocks offline.
import { randomUUID } from "node:crypto";
import { lstat, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const VENICE_MODELS_URL = "https://api.venice.ai/api/v1/models";
export const CACHE_SCHEMA_VERSION = 1;
export const CACHE_FRESH_TTL_MS = 15 * 60 * 1000;
export const CACHE_MAX_STALE_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_FUTURE_SKEW_MS = 24 * 60 * 60 * 1000;
export const FETCH_TIMEOUT_MS = 3000;
export const MAX_CATALOG_BYTES = 2 * 1024 * 1024;

function nonNegativeNumber(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fallback;
}

function positiveInteger(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : null;
}

export function resolveCachePath(env = process.env, homeDir = homedir()) {
  const override = typeof env?.PI_CODING_AGENT_DIR === "string" ? env.PI_CODING_AGENT_DIR.trim() : "";
  const agentDir = override || (homeDir ? join(homeDir, ".pi", "agent") : "");
  return agentDir ? join(agentDir, "cache", "venice-models.json") : "";
}

export function normalizeVeniceModel(entry) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
  if (entry.type !== "text") return null;
  const id = typeof entry.id === "string" ? entry.id.trim() : "";
  if (!id || !/^[\x21-\x7e]+$/.test(id)) return null;

  const spec = entry.model_spec && typeof entry.model_spec === "object" && !Array.isArray(entry.model_spec)
    ? entry.model_spec
    : {};
  if (spec.offline === true) return null;

  const contextWindow = positiveInteger(spec.availableContextTokens) ?? positiveInteger(entry.context_length);
  if (!contextWindow || contextWindow < 2) return null;

  const rawMax = positiveInteger(spec.maxCompletionTokens);
  const maxTokens = rawMax
    ? Math.min(rawMax, contextWindow - 1)
    : Math.min(16384, Math.max(1, Math.floor(contextWindow / 2)));

  const caps = spec.capabilities && typeof spec.capabilities === "object" && !Array.isArray(spec.capabilities)
    ? spec.capabilities
    : {};
  const pricing = spec.pricing && typeof spec.pricing === "object" && !Array.isArray(spec.pricing)
    ? spec.pricing
    : {};

  const cleanName = typeof spec.name === "string" ? spec.name.replace(/[\x00-\x1f\x7f]/g, "").trim() : "";
  const name = cleanName || id;

  return {
    id,
    name,
    reasoning: Boolean(caps.supportsReasoning),
    input: caps.supportsVision ? ["text", "image"] : ["text"],
    contextWindow,
    maxTokens,
    cost: {
      input: nonNegativeNumber(pricing.input?.usd),
      output: nonNegativeNumber(pricing.output?.usd),
      cacheRead: nonNegativeNumber(pricing.cache_input?.usd),
      cacheWrite: nonNegativeNumber(pricing.cache_write?.usd),
    },
    compat: {
      maxTokensField: "max_tokens",
      supportsDeveloperRole: false,
      supportsReasoningEffort: Boolean(caps.supportsReasoningEffort),
    },
  };
}

export function parseVeniceCatalog(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || !Array.isArray(payload.data)) {
    return null;
  }
  const seen = new Set();
  const models = [];
  for (const entry of payload.data) {
    const normalized = normalizeVeniceModel(entry);
    if (!normalized || seen.has(normalized.id)) continue;
    seen.add(normalized.id);
    models.push(normalized);
  }
  if (models.length === 0) return null;
  models.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return models;
}

async function readBoundedResponseText(response, maxBytes = MAX_CATALOG_BYTES) {
  const lengthHeader = response.headers?.get?.("content-length");
  if (lengthHeader !== null && lengthHeader !== undefined) {
    const declared = Number(lengthHeader);
    if (Number.isFinite(declared) && declared > maxBytes) {
      throw new Error("Venice catalog response exceeds size limit");
    }
  }
  if (response.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
        total += bytes.byteLength;
        if (total > maxBytes) {
          await reader.cancel().catch(() => {});
          throw new Error("Venice catalog response exceeds size limit");
        }
        chunks.push(bytes);
      }
    } finally {
      reader.releaseLock?.();
    }
    return Buffer.concat(chunks, total).toString("utf8");
  }
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > maxBytes) {
    throw new Error("Venice catalog response exceeds size limit");
  }
  return text;
}

const CACHE_ENVELOPE_OVERHEAD = 4096;

export async function readCachedCatalog(cachePath, { now = Date.now(), maxBytes = MAX_CATALOG_BYTES } = {}) {
  if (!cachePath) return null;
  const limit = maxBytes + CACHE_ENVELOPE_OVERHEAD;
  try {
    const info = await lstat(cachePath);
    if (!info.isFile() || info.size > limit) return null;
    const raw = await readFile(cachePath, "utf8");
    if (Buffer.byteLength(raw, "utf8") > limit) return null;
    const record = JSON.parse(raw);
    if (!record || typeof record !== "object" || Array.isArray(record)) return null;
    if (record.schemaVersion !== CACHE_SCHEMA_VERSION) return null;
    if (typeof record.fetchedAt !== "number" || !Number.isFinite(record.fetchedAt)) return null;
    if (record.fetchedAt > now + MAX_FUTURE_SKEW_MS) return null;
    const ageMs = now - record.fetchedAt;
    if (ageMs > CACHE_MAX_STALE_MS) return null;
    const models = parseVeniceCatalog(record.body);
    if (!models) return null;
    return {
      models,
      fetchedAt: record.fetchedAt,
      fresh: ageMs <= CACHE_FRESH_TTL_MS,
    };
  } catch {
    return null;
  }
}

export async function writeCachedCatalog(cachePath, body, fetchedAt = Date.now(), maxBytes = MAX_CATALOG_BYTES) {
  if (!cachePath) return;
  const payload = JSON.stringify({
    schemaVersion: CACHE_SCHEMA_VERSION,
    fetchedAt,
    body,
  });
  if (Buffer.byteLength(payload, "utf8") > maxBytes + CACHE_ENVELOPE_OVERHEAD) return;
  const tmpPath = `${cachePath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await mkdir(dirname(cachePath), { recursive: true, mode: 0o700 });
    await writeFile(tmpPath, payload, { mode: 0o600 });
    await rename(tmpPath, cachePath);
  } catch {
    try {
      await unlink(tmpPath);
    } catch {
      // Best-effort temp cleanup.
    }
  }
}

export async function fetchVeniceCatalog({
  url = VENICE_MODELS_URL,
  fetchImpl = globalThis.fetch,
  signal,
  timeoutMs = FETCH_TIMEOUT_MS,
  maxBytes = MAX_CATALOG_BYTES,
} = {}) {
  if (typeof fetchImpl !== "function") return null;
  const timeout = AbortSignal.timeout(timeoutMs);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const response = await fetchImpl(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: requestSignal,
  });
  if (!response?.ok) return null;
  const text = await readBoundedResponseText(response, maxBytes);
  const body = JSON.parse(text);
  const models = parseVeniceCatalog(body);
  if (!models) return null;
  return { body, models };
}

export async function loadVeniceModels({
  fallbackModels,
  cachePath = resolveCachePath(),
  forceRefresh = false,
  allowNetwork = true,
  env = process.env,
  url = VENICE_MODELS_URL,
  fetchImpl = globalThis.fetch,
  signal,
  now = Date.now(),
  timeoutMs = FETCH_TIMEOUT_MS,
  maxBytes = MAX_CATALOG_BYTES,
} = {}) {
  const cached = await readCachedCatalog(cachePath, { now, maxBytes });
  if (!forceRefresh && cached?.fresh) {
    return cached.models;
  }

  const discoveryDisabled = env?.PI_VENICE_DISABLE_DISCOVERY === "1";
  if (allowNetwork && !discoveryDisabled && !signal?.aborted) {
    try {
      const fetched = await fetchVeniceCatalog({ url, fetchImpl, signal, timeoutMs, maxBytes });
      if (fetched) {
        await writeCachedCatalog(cachePath, fetched.body, now);
        return fetched.models;
      }
    } catch {
      // Fall back to stale cache or bundled shortlist.
    }
  }

  return cached?.models ?? fallbackModels;
}
