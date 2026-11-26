// Venice.ai is a manual Pi provider. ADE automatic routes exclude it.
// Catalog discovery runs on extension load/reload using Venice's public
// /api/v1/models endpoint with an on-disk cache. Picker refreshModels is
// intentionally omitted until Pi supports unauthenticated model refresh
// without first invoking the provider's `!sudo-secretspec` apiKey broker.
import { readFileSync } from "node:fs";
import { loadVeniceModels } from "./catalog.mjs";

const FALLBACK_MODELS = JSON.parse(readFileSync(new URL("./models.json", import.meta.url), "utf8"));

export default async function venice(pi) {
  const models = await loadVeniceModels({ fallbackModels: FALLBACK_MODELS });
  pi.registerProvider("venice", {
    name: "Venice.ai (manual, operator-gated)",
    baseUrl: "https://api.venice.ai/api/v1",
    api: "openai-completions",
    apiKey: "!sudo-secretspec get VENICE_API_KEY --reason pi-venice-request",
    models,
  });
}
