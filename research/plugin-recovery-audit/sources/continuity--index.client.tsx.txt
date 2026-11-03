import type { PluginButtonRegistration, PluginClientContext } from "@getpaseo/plugin/client";
import { ChainPanel } from "./client/chain-panel";
import { SettingsScreen } from "./client/settings-screen";
import { createPillPopover } from "./client/pill-popover";
import { TransitionCard } from "./client/transition-card";
import {
  TRANSITION_KIND,
  TRANSITION_VERSION,
  TransitionCardSchema,
  failoverNowRpc,
  getSettingsRpc,
} from "./shared/contracts";
import { providerBadge } from "./shared/labels";
import type { ContinuitySettings } from "./shared/settings";
import { formatPct, isLowQuota, summarizeQuota, type UsageProvider } from "./shared/usage";

export default function contribute(client: PluginClientContext) {
  client.addTimelineRenderer({
    kind: TRANSITION_KIND,
    version: TRANSITION_VERSION,
    schema: TransitionCardSchema,
    Component: TransitionCard,
  });

  client.addWorkspacePanel({
    id: "chain",
    title: "Continuity chain",
    icon: "Link",
    context: "agent",
    Component: ChainPanel,
  });

  client.addSettingsScreen({
    id: "settings",
    title: "Paseo Continuity",
    icon: "Link",
    Component: SettingsScreen,
  });

  client.addCommandCenterItem({
    id: "open-chain",
    title: "Continuity: show chain",
    icon: "Link",
    keywords: ["continuity", "handoff", "provider", "fallback"],
    context: "agent",
    onSelect({ openPanel }) {
      openPanel("chain");
    },
  });

  client.addCommandCenterItem({
    id: "failover-now",
    title: "Continuity: switch to next provider now",
    icon: "ArrowRightLeft",
    keywords: ["continuity", "failover", "quota", "rate limit"],
    context: "agent",
    async onSelect({ agent, rpc, openPanel }) {
      const result = await rpc(failoverNowRpc, { agentId: agent.id });
      if (result.status !== "created") throw new Error(result.message);
      openPanel("chain");
    },
  });

  client.addCommandCenterItem({
    id: "settings",
    title: "Continuity: settings",
    icon: "Settings",
    context: "global",
    onSelect({ openSettings }) {
      openSettings("settings");
    },
  });

  client.addSlashCommand({
    name: "continuity",
    description: "Continue this task on the next provider in the fallback chain",
    argumentHint: "",
    context: "agent",
    async onSubmit({ agent, rpc, openPanel }) {
      const result = await rpc(failoverNowRpc, { agentId: agent.id });
      if (result.status !== "created") throw new Error(result.message);
      openPanel("chain");
    },
  });

  // Composer pills management
  const pills = new Map<string, PluginButtonRegistration>();
  const agents = new Map<string, { provider: string }>();
  const lifetime = new AbortController();
  const PillPopover = createPillPopover(({ workspaceId, agentId }) =>
    client.openPanel("chain", { workspaceId, agentId }),
  );

  let cachedSettings: ContinuitySettings | null = null;
  let usage: UsageProvider[] = [];

  const pillPresentation = (provider: string) => {
    const settings = cachedSettings;
    const quota = summarizeQuota(usage, provider);
    const low = settings !== null && isLowQuota(quota, settings.warnAtRemainingPct);
    const name = providerBadge(provider).label;
    return {
      visible: settings ? settings.enabled && settings.showComposerPill : true,
      label: quota ? `${low ? "⚠ " : ""}${name} ${formatPct(quota.remainingPct)}` : "Continuity",
    };
  };

  const refreshPills = () => {
    for (const [agentId, pill] of pills) {
      const agent = agents.get(agentId);
      if (agent) pill.update(pillPresentation(agent.provider));
    }
  };

  const pollUsage = () => {
    client.paseo.providers
      .listUsage()
      .then((result) => {
        usage = result.providers;
        refreshPills();
        return undefined;
      })
      .catch(() => {});
  };

  const registerPill = (agent: { id: string; workspaceId?: string | null; provider: string }) => {
    if (lifetime.signal.aborted || !agent.workspaceId) return;
    const agentId = agent.id;
    const workspaceId = agent.workspaceId;
    agents.set(agentId, { provider: agent.provider });
    const existing = pills.get(agentId);
    if (existing) {
      existing.update(pillPresentation(agent.provider));
      return;
    }

    pills.set(
      agentId,
      client.addComposerPill({
        id: "continuity-pill",
        workspaceId,
        agentId,
        button: {
          title: "Continue on another provider",
          icon: "ArrowRightLeft",
          ...pillPresentation(agent.provider),
          behavior: { kind: "popover", Content: PillPopover },
        },
      }),
    );
  };

  const removeAllPills = () => {
    for (const pill of pills.values()) pill.remove();
    pills.clear();
    agents.clear();
  };

  void client
    .rpc(getSettingsRpc, {})
    .then((settings) => {
      cachedSettings = settings;
      refreshPills();
      return undefined;
    })
    .catch(() => {});

  pollUsage();
  const usageTimer = setInterval(pollUsage, 60_000);

  void client.paseo.agents
    .list({ subscribe: {}, signal: lifetime.signal })
    .then(({ subscription }) => {
      subscription.subscribe({
        snapshot: ({ entries }) => {
          removeAllPills();
          for (const { agent } of entries) registerPill(agent);
        },
        update: (message) => {
          if (message.type !== "agent_update") return;
          const update = message.payload;
          if (update.kind === "upsert") {
            registerPill(update.agent);
          } else if ("agentId" in update && typeof update.agentId === "string") {
            pills.get(update.agentId)?.remove();
            pills.delete(update.agentId);
            agents.delete(update.agentId);
          }
        },
      });
      return undefined;
    })
    .catch((error) => {
      if (!lifetime.signal.aborted) console.error("[continuity] agent observation failed", error);
    });

  return () => {
    clearInterval(usageTimer);
    lifetime.abort();
    removeAllPills();
  };
}
