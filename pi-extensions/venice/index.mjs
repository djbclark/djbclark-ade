// Venice.ai is a manual Pi provider. ADE automatic routes exclude it.
import { readFileSync } from "node:fs";

export default function venice(pi) {
  pi.registerProvider("venice", {
    name: "Venice.ai (manual, operator-gated)",
    baseUrl: "https://api.venice.ai/api/v1",
    api: "openai-completions",
    apiKey: "!sudo-secretspec get VENICE_API_KEY --reason pi-venice-request",
    models: JSON.parse(readFileSync(new URL("./models.json", import.meta.url), "utf8")),
  });
}
