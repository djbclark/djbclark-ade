import { readFileSync } from "node:fs";

// Cline's subscription catalog, not its general pay-as-you-go /models list.
// Snapshot/provenance and the deliberately manual-only policy: docs/pi-services.md.
export default function clinepass(pi) {
  const models = JSON.parse(readFileSync(new URL("./models.json", import.meta.url), "utf8"));
  for (const [provider, label, secret] of [
    ["clinepass", "primary", "CLINE_API_KEY"],
    ["clinepass-t-e", "t-e", "CLINE_PASS_KEY_2_TE"],
  ]) pi.registerProvider(provider, {
    name: `ClinePass (${label}, manual)`,
    baseUrl: "https://api.cline.bot/api/v1",
    api: "openai-completions",
    // Pi executes this at request time; no key in settings, source or process argv.
    apiKey: `!sudo-secretspec get ${secret} --reason pi-clinepass-request`,
    headers: { "X-Response-Format": "openai" },
    models: models.map((model) => ({
      ...model,
      compat: {
        maxTokensField: "max_tokens",
        supportsDeveloperRole: false,
      },
    })),
  });
}
