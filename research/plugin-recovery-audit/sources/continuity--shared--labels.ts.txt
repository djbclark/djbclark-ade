/** Label keys stamped on every agent created by Paseo Continuity. */
export const LABEL = {
  chainId: "continuity.chainId",
  previousAgentId: "continuity.previousAgentId",
  provider: "continuity.provider",
  sequence: "continuity.sequence",
  consecutive: "continuity.consecutive",
  reason: "continuity.reason",
} as const;

const PROVIDER_BADGES: Record<string, { badge: string; label: string }> = {
  codex: { badge: "●", label: "Codex" },
  claude: { badge: "◆", label: "Claude" },
  "antigravity-cli": { badge: "✦", label: "Gemini" },
  gemini: { badge: "✦", label: "Gemini" },
  opencode: { badge: "▲", label: "OpenCode" },
  pi: { badge: "π", label: "Pi" },
  omp: { badge: "π", label: "Oh My Pi" },
  hermes: { badge: "☿", label: "Hermes" },
  copilot: { badge: "◎", label: "Copilot" },
};

const ALL_BADGES = ["●", "◆", "✦", "▲", "π", "☿", "◎", "•"];

/** Provider IDs arrive as "provider" or "provider/model"; take the provider part. */
export function providerIdOf(provider: string): string {
  const slash = provider.indexOf("/");
  const id = slash === -1 ? provider : provider.slice(0, slash);
  return id.trim().toLowerCase();
}

export function providerBadge(provider: string, model?: string | null) {
  const id = providerIdOf(provider);
  if (model && /gemini/i.test(model)) {
    return { badge: "✦", label: "Gemini" };
  }
  return PROVIDER_BADGES[id] ?? { badge: "•", label: id.charAt(0).toUpperCase() + id.slice(1) };
}

/** Removes an existing "◆ Claude · " style prefix so chained titles do not stack. */
export function stripBadgePrefix(title: string): string {
  const trimmed = title.trim();
  for (const badge of ALL_BADGES) {
    if (trimmed.startsWith(badge + " ")) {
      const dot = trimmed.indexOf(" · ");
      if (dot !== -1) {
        return trimmed.slice(dot + 3).trim();
      }
    }
  }
  return trimmed;
}

export function buildSuccessorTitle(input: {
  provider: string;
  model?: string | null;
  previousTitle: string | null;
  fallbackText: string;
  badges: boolean;
}): string {
  const base =
    (input.previousTitle && stripBadgePrefix(input.previousTitle)) ||
    truncate(input.fallbackText.replace(/\s+/g, " ").trim(), 50) ||
    "Continued task";
  if (!input.badges) {
    return base;
  }
  const { badge, label } = providerBadge(input.provider, input.model);
  return `${badge} ${label} · ${base}`;
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max - 1).trimEnd() + "…";
}
