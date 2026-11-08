/** Fit SIPB context and optionally record request shape without content. */
import { randomUUID } from "node:crypto";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

const numeric = value => typeof value === "number" && Number.isFinite(value) ? value : null;

export async function recordRequestMetadata(payload, directory) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
  const metadata = {
    schemaVersion: 1,
    model: typeof payload.model === "string" ? payload.model : null,
    stream: payload.stream === true,
    bodyBytes: Buffer.byteLength(JSON.stringify(payload)),
    messages: Array.isArray(payload.messages) ? payload.messages.map(message => ({
      role: ["system", "developer", "user", "assistant", "tool"].includes(message.role) ? message.role : "other",
      contentChars: JSON.stringify(message.content ?? "").length,
    })) : [],
    tools: Array.isArray(payload.tools) ? payload.tools.map(tool => tool.function?.name).filter(name => typeof name === "string") : [],
    maxTokens: numeric(payload.max_tokens),
    maxCompletionTokens: numeric(payload.max_completion_tokens),
    backendContext: numeric(payload.params?.num_ctx ?? payload.options?.num_ctx),
    reasoningEffort: ["off", "none", "minimal", "low", "medium", "high", "xhigh", "max"].includes(payload.reasoning_effort) ? payload.reasoning_effort : null,
  };
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const target = join(directory, `sipb-${randomUUID()}.json`);
  const temporary = target + ".tmp";
  await writeFile(temporary, JSON.stringify(metadata) + "\n", { mode: 0o600, flag: "wx" });
  await rename(temporary, target);
}

export default function serviceContext(pi) {
  pi.on("before_agent_start", (event, ctx) => {
    if (ctx.model?.provider !== "sipb") return;
    event.systemPromptOptions.skills = [];
  });
  pi.on("before_provider_request", async (event, ctx) => {
    const directory = process.env.ADE_PI_REQUEST_METADATA_DIR;
    if (ctx.model?.provider !== "sipb" || !directory) return;
    try {
      await recordRequestMetadata(event.payload, directory);
    } catch {
      console.error("Pi SIPB request metadata write failed");
    }
    // Observation only: leave the actual payload unchanged.
  });
}
