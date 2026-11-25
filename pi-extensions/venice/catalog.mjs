// Dynamic catalog loader for Venice.ai's public /api/v1/models endpoint.
// Uses a short-TTL on-disk cache under the user-owned Pi agent cache directory
// and falls back cleanly to stale cache or bundled models.json so Pi startup
// stays fast, honors offline mode, and never invokes credential brokers.
import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, rename, unlink } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const VENICE_MODELS_URL = "https://api.venice.ai/api/v1/models";
export const CACHE_SCHEMA_VERSION = 1;
export const CACHE_FRESH_TTL_MS = 15 * 60 * 1000;
export const CACHE_MAX_STALE_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_FUTURE_SKEW_MS = 60 * 1000;
export const FETCH_TIMEOUT_MS = 3000;
export const MAX_CATALOG_BYTES = 2 * 1024 * 1024;
export const MAX_CONTEXT_TOKENS = 100_000_000;
export const MAX_ID_LENGTH = 128;
export const MAX_NAME_LENGTH = 128;

const CACHE_ENVELOPE_OVERHEAD = 4096;
const READ_CHUNK_BYTES = 64 * 1024;
// Strip ASCII C0/DEL, C1 controls, and Unicode bidirectional format characters.
const UNSAFE_DISPLAY_RE = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;

function nonNegativeNumber(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fallback;
}

function boundedPositiveInteger(value, max = MAX_CONTEXT_TOKENS) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 1 || value > max) {
    return null;
  }
  const integer = Math.floor(value);
  return Number.isSafeInteger(integer) && integer >= 1 ? integer : null;
}

function expandTilde(raw, homeDir) {
  if (!homeDir) return raw;
  if (raw === "~") return homeDir;
  if (raw.startsWith("~/")) return join(homeDir, raw.slice(2));
  return raw;
}

export function resolveCachePath(env = process.env, homeDir = homedir()) {
  const override = typeof env?.PI_CODING_AGENT_DIR === "string" ? env.PI_CODING_AGENT_DIR.trim() : "";
  const agentDir = override ? expandTilde(override, homeDir) : (homeDir ? join(homeDir, ".pi", "agent") : "");
  return agentDir ? join(agentDir, "cache", "venice-models.json") : "";
}

export function normalizeVeniceModel(entry) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
  if (entry.type !== "text") return null;
  const id = typeof entry.id === "string" ? entry.id.trim() : "";
  if (!id || id.length > MAX_ID_LENGTH || !/^[\x21-\x7e]+$/.test(id)) return null;

  const spec = entry.model_spec && typeof entry.model_spec === "object" && !Array.isArray(entry.model_spec)
    ? entry.model_spec
    : {};
  if (spec.offline === true) return null;

  const contextWindow = boundedPositiveInteger(spec.availableContextTokens)
    ?? boundedPositiveInteger(entry.context_length);
  if (!contextWindow || contextWindow < 2) return null;

  const rawMax = boundedPositiveInteger(spec.maxCompletionTokens);
  const maxTokens = rawMax
    ? Math.min(rawMax, contextWindow - 1)
    : Math.min(16384, Math.max(1, Math.floor(contextWindow / 2)));

  const caps = spec.capabilities && typeof spec.capabilities === "object" && !Array.isArray(spec.capabilities)
    ? spec.capabilities
    : {};
  const pricing = spec.pricing && typeof spec.pricing === "object" && !Array.isArray(spec.pricing)
    ? spec.pricing
    : {};

  const cleanName = typeof spec.name === "string"
    ? spec.name.replace(UNSAFE_DISPLAY_RE, "").trim().slice(0, MAX_NAME_LENGTH)
    : "";
  const name = cleanName || id;

  return {
    id,
    name,
    reasoning: caps.supportsReasoning === true,
    input: caps.supportsVision === true ? ["text", "image"] : ["text"],
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
      supportsReasoningEffort: caps.supportsReasoningEffort === true,
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

async function disposeResponseBody(response) {
  try {
    await response?.body?.cancel?.();
  } catch {
    // Best-effort body disposal.
  }
}

async function readBoundedResponseText(response, maxBytes = MAX_CATALOG_BYTES) {
  const lengthHeader = response.headers?.get?.("content-length");
  if (lengthHeader !== null && lengthHeader !== undefined) {
    const declared = Number(lengthHeader);
    if (Number.isFinite(declared) && declared > maxBytes) {
      await disposeResponseBody(response);
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
  throw new Error("Venice catalog response body is not streamable");
}

async function readBoundedRegularFile(filePath, limitBytes) {
  const flags = constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0);
  const handle = await open(filePath, flags);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size > limitBytes) return null;
    const chunks = [];
    let total = 0;
    while (true) {
      const remaining = limitBytes - total + 1;
      const buf = Buffer.allocUnsafe(Math.min(READ_CHUNK_BYTES, remaining));
      const { bytesRead } = await handle.read(buf, 0, buf.length, null);
      if (bytesRead === 0) break;
      total += bytesRead;
      if (total > limitBytes) return null;
      chunks.push(bytesRead === buf.length ? buf : buf.subarray(0, bytesRead));
    }
    return Buffer.concat(chunks, total).toString("utf8");
  } finally {
    await handle.close();
  }
}

export async function readCachedCatalog(cachePath, { now = Date.now(), maxBytes = MAX_CATALOG_BYTES } = {}) {
  if (!cachePath) return null;
  const limit = maxBytes + CACHE_ENVELOPE_OVERHEAD;
  try {
    const raw = await readBoundedRegularFile(cachePath, limit);
    if (raw === null) return null;
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
      fresh: ageMs >= 0 && ageMs <= CACHE_FRESH_TTL_MS,
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
  const createFlags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0);
  let created = false;
  try {
    await mkdir(dirname(cachePath), { recursive: true, mode: 0o700 });
    const handle = await open(tmpPath, createFlags, 0o600);
    created = true;
    try {
      await handle.writeFile(payload, "utf8");
    } finally {
      await handle.close();
    }
    await rename(tmpPath, cachePath);
    created = false;
  } catch {
    if (created) {
      try {
        await unlink(tmpPath);
      } catch {
        // Best-effort cleanup of temp file created by this invocation.
      }
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
  if (!response?.ok) {
    await disposeResponseBody(response);
    return null;
  }
  const text = await readBoundedResponseText(response, maxBytes);
  const body = JSON.parse(text);
  const models = parseVeniceCatalog(body);
  if (!models) return null;
  return { body, models };
}

export async function loadVeniceModels({
  fallbackModels,
  cachePath,
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
  const resolvedCachePath = cachePath === undefined ? resolveCachePath(env) : cachePath;
  const cached = await readCachedCatalog(resolvedCachePath, { now, maxBytes });
  if (!forceRefresh && cached?.fresh) {
    return cached.models;
  }

  const discoveryDisabled = env?.PI_VENICE_DISABLE_DISCOVERY === "1" || env?.PI_OFFLINE === "1";
  if (allowNetwork && !discoveryDisabled && !signal?.aborted) {
    try {
      const fetched = await fetchVeniceCatalog({ url, fetchImpl, signal, timeoutMs, maxBytes });
      if (fetched) {
        await writeCachedCatalog(resolvedCachePath, fetched.body, now, maxBytes);
        return fetched.models;
      }
    } catch {
      // Fall back to stale cache or bundled shortlist.
    }
  }

  return cached?.models ?? fallbackModels;
}
