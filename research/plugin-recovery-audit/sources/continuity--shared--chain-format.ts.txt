import type { ChainEntry } from "./settings";

/** "codex:auto, claude/sonnet:default" <-> chain entries. */
export function formatChain(chain: readonly ChainEntry[]): string {
  return chain
    .map((entry) => `${entry.provider}${entry.model ? `/${entry.model}` : ""}${entry.modeId ? `:${entry.modeId}` : ""}`)
    .join(", ");
}

export function parseChain(text: string): ChainEntry[] | string {
  const parts = text.split(",").map((part) => part.trim()).filter(Boolean);
  const entries: ChainEntry[] = [];
  for (const part of parts) {
    const match = part.match(/^([a-z0-9][a-z0-9_-]*)(?:\/([^:\s]+))?(?::([^\s]+))?$/i);
    if (!match) {
      return `Cannot read "${part}". Use provider[/model][:mode].`;
    }
    entries.push({
      provider: match[1]!,
      model: match[2] ?? null,
      modeId: match[3] ?? null,
      thinkingOptionId: null,
    });
  }
  if (entries.length < 2) {
    return "Add at least two providers.";
  }
  return entries;
}
