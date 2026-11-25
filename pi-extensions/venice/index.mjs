// Venice.ai is a manual Pi provider. ADE automatic routes exclude it.
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
    refreshModels: async (context = {}) =>
      loadVeniceModels({
        fallbackModels: FALLBACK_MODELS,
        forceRefresh: true,
        allowNetwork: context.allowNetwork !== false,
        signal: context.signal,
      }),
  });
}
