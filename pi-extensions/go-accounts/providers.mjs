import { execFile } from "node:child_process";
import { promisify } from "node:util";

const exec = promisify(execFile);
export const ACCOUNTS = Object.freeze([
  ["djbclark", "OPENCODE_GO_API_KEY_DJBCLARK"],
  ["dclark", "OPENCODE_GO_API_KEY_DCLARKUS"],
  ["t-e", "OPENCODE_GO_API_KEY_TECHNOEUPHORA"],
]);

// Each provider identity owns exactly one credential; no global switch/failover.
export function accountProviders(native, run = exec) {
  return ACCOUNTS.map(([label, secret]) => {
    const id = `opencode-go-${label}`;
    const models = native.getModels().map(model => ({ ...model, provider: id }));
    return {
      ...native,
      id,
      name: `OpenCode Go (${label}, manual)`,
      getModels: () => models,
      getAllModels: () => models,
      auth: { apiKey: {
        name: `Managed Go key (${label})`,
        // Catalog discovery must not retrieve keys or contact the broker.
        check: async () => ({ type: "api_key", source: secret }),
        async resolve({ signal }) {
          try {
            const { stdout } = await run("sudo-secretspec", ["get", secret, "--reason", "pi-go-account-request"],
              { encoding: "utf8", timeout: 10000, maxBuffer: 8192, signal });
            const apiKey = stdout.trim();
            if (!apiKey) throw new Error("empty");
            return { auth: { apiKey }, source: secret };
          } catch {
            // execFile errors carry stdout/stderr; never forward them to Pi.
            throw new Error(`Managed Go credential unavailable (${label})`);
          }
        },
      } },
    };
  });
}
