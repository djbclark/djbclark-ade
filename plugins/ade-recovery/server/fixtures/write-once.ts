// Test child: write COUNT generations of one agent's record, printing `ack <generation>` after each
// write resolves (directory fsync done). With ADE_RECOVERY_TEST=1 and ADE_RECOVERY_CRASH_AT=<point>
// the store SIGKILLs this process at that point of the first write that reaches it.
// Usage: node write-once.ts DIR AGENT_ID [COUNT]

import { writeGeneration } from "../store.ts";
import { selfWriterInfo } from "../writer-lock.ts";
import { hostIdentity } from "../host-identity.ts";

const [dir, agentId, countArg] = process.argv.slice(2);
if (!dir || !agentId) {
  process.stderr.write("usage: write-once.ts DIR AGENT_ID [COUNT]\n");
  process.exit(64);
}
const count = countArg ? Number(countArg) : 1;
const h = hostIdentity();

for (let i = 0; i < count; i++) {
  const rec = await writeGeneration(dir, agentId, {
    schema: "ade.recovery.passive/v1",
    writer: selfWriterInfo(),
    serverId: "srv-test",
    paseoAgentId: agentId,
    provider: "claude",
    cwd: "/tmp/work",
    host: h.host,
    bootId: h.bootId,
    platform: h.platform,
    state: "idle",
    turns: [],
    // padding so the file spans several pages and a torn write would be visible
    missingTelemetry: [{ field: "toolCalls", reason: "x".repeat(9000), at: new Date().toISOString() }],
  });
  process.stdout.write(`ack ${rec.generation}\n`);
}
