// RFab is a manual Pi provider. ADE automatic routes exclude it.
import { readFileSync } from "node:fs";
import { openAICompletionsApi } from "@earendil-works/pi-ai";
import { bufferedCompletionsFetch } from "./transport.mjs";

export default function rfab(pi) {
  const models = JSON.parse(readFileSync(new URL("./models.json", import.meta.url), "utf8"));
  pi.registerProvider("rfab", {
    name: "Reality Fabricator (rfab.ai, manual, operator-gated)",
    baseUrl: "https://api.rfab.ai/api/v1",
    api: "openai-completions",
    apiKey: "!sudo-secretspec get RFAB_API_KEY --reason pi-rfab-request",
    models: models.map((model) => ({
      ...model,
      compat: {
        maxTokensField: "max_completion_tokens",
        supportsDeveloperRole: true,
        supportsStore: false,
        supportsUsageInStreaming: false,
      },
    })),
    streamSimple(model, context, options) {
      return openAICompletionsApi().streamSimple(model, context, {
        ...options,
        // A timed-out POST may already have been billed. Leave retries to the caller.
        maxRetries: 0,
        fetch: bufferedCompletionsFetch(options?.fetch ?? globalThis.fetch),
      });
    },
  });
}
