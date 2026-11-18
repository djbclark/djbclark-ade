import { execFile } from "node:child_process";
import { promisify } from "node:util";

const exec = promisify(execFile);
export const ACCOUNTS = Object.freeze([
  ["djbclark", "OPENCODE_GO_API_KEY_DJBCLARK"],
  ["dclark", "OPENCODE_GO_API_KEY_DCLARKUS"],
  ["t-e", "OPENCODE_GO_API_KEY_TECHNOEUPHORA"],
]);

// Only fixed labels and bounded integer exit status may leave this boundary.
// Never attach the exec error as cause: it can contain the credential itself.
function credentialFailure(label, error, deadline, signal) {
  let detail;
  if (signal?.aborted) detail = "request aborted";
  else if (deadline.aborted) detail = "broker timed out after 10000ms";
  else if (error?.name === "AbortError" || error?.code === "ABORT_ERR") detail = "request aborted";
  else if (error?.code === "ENOENT") detail = "sudo-secretspec executable missing";
  else if (error?.code === "EACCES") detail = "sudo-secretspec execution denied";
  else if (error?.code === "ETIMEDOUT") detail = "broker timed out after 10000ms";
  else if (error?.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") detail = "broker output exceeded limit";
  // sudo-secretspec's broker emits this prefix for an audit-policy refusal.
  // Inspect only a bounded diagnostic; do not interpolate any part of it.
  else if (typeof error?.stderr === "string" &&
    /^broker: (?:audit (?:attempt|terminal) failed: )?audit denied:/m.test(error.stderr.slice(0, 8192))) {
    detail = "broker denied credential access";
  } else if (Number.isInteger(error?.code) && error.code >= 1 && error.code <= 255) {
    detail = `broker exited with code ${error.code}`;
  } else if (error?.signal || error?.killed) detail = "broker process terminated";
  else detail = "broker execution failed";
  return new Error(`Managed Go credential unavailable (${label}): ${detail}`);
}

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
        async resolve({ signal } = {}) {
          // A deadline we own distinguishes timeout from unrelated SIGTERM.
          // Resolution is the execution preflight: Pi calls it before transport,
          // never while enumerating this provider or its models.
          const deadline = AbortSignal.timeout(10000);
          const requestSignal = signal ? AbortSignal.any([signal, deadline]) : deadline;
          let stdout;
          try {
            requestSignal.throwIfAborted();
            ({ stdout } = await run("sudo-secretspec", ["get", secret, "--reason", "pi-go-account-request"],
              { encoding: "utf8", maxBuffer: 8192, signal: requestSignal }));
            requestSignal.throwIfAborted();
          } catch (error) {
            throw credentialFailure(label, error, deadline, signal);
          }
          if (typeof stdout !== "string") {
            throw new Error(`Managed Go credential unavailable (${label}): invalid broker result`);
          }
          const apiKey = stdout.trim();
          if (!apiKey) {
            throw new Error(`Managed Go credential unavailable (${label}): empty broker stdout`);
          }
          return { auth: { apiKey }, source: secret };
        },
      } },
    };
  });
}
