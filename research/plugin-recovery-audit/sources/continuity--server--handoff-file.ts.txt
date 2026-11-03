import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const HANDOFF_DIR = ".paseo/continuity";

/**
 * Writes the compacted handoff next to the project and returns a short prompt
 * that points the successor at it. The directory ignores itself so the handoff
 * never shows up in `git status`.
 */
export async function writeHandoffFile(cwd: string, agentId: string, handoff: string): Promise<string> {
  const dir = join(cwd, HANDOFF_DIR);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, ".gitignore"), "*\n", { flag: "w" });
  const file = join(dir, `handoff-${agentId.slice(0, 8)}-${Date.now()}.md`);
  await writeFile(file, `${handoff}\n`, "utf8");
  return [
    "You are continuing a task that another agent started on a different provider.",
    `Read the handoff file first: ${file}`,
    "It holds the original task, the latest request, and a condensed transcript. Then inspect the working tree (`git status`, `git diff`) and continue from where the previous agent stopped. Do not redo completed work.",
  ].join("\n");
}
