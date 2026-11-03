import { type PluginAgentPanelProps, usePaseo, useRpc } from "@getpaseo/plugin/client";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { failoverNowRpc } from "../shared/contracts";
import { LABEL, providerBadge } from "../shared/labels";

interface ChainRow {
  id: string;
  title: string;
  provider: string;
  model: string | null;
  sequence: number;
  createdAt: string;
  archived: boolean;
}

export function ChainPanel({ agentId, theme, layout, navigation }: PluginAgentPanelProps) {
  const paseo = usePaseo();
  const rpc = useRpc(failoverNowRpc);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const chain = useQuery({
    queryKey: ["continuity-chain", agentId],
    refetchInterval: 10_000,
    queryFn: async (): Promise<ChainRow[]> => {
      const self = await paseo.agents.ref(agentId).refresh();
      const chainId = self?.agent.labels[LABEL.chainId] ?? agentId;
      const [root, members] = await Promise.all([
        paseo.agents.ref(chainId).refresh().catch(() => null),
        paseo.agents.list({
          filter: { labels: { [LABEL.chainId]: chainId }, includeArchived: true },
          page: { limit: 100 },
        }),
      ]);
      const agents = [
        ...(root ? [root.agent] : []),
        ...members.entries.map((entry) => entry.agent).filter((agent) => agent.id !== chainId),
      ];
      return agents
        .map((agent) => ({
          id: agent.id,
          title: agent.title ?? agent.id.slice(0, 8),
          provider: agent.provider,
          model: agent.model ?? null,
          sequence: Number(agent.labels[LABEL.sequence] ?? 0) || 0,
          createdAt: agent.createdAt,
          archived: Boolean(agent.archivedAt),
        }))
        .sort((a, b) => a.sequence - b.sequence || a.createdAt.localeCompare(b.createdAt));
    },
  });

  const handleSwitch = async () => {
    setSwitching(true);
    setSwitchError(null);
    try {
      const result = await rpc({ agentId });
      if (result.status === "created" && result.newAgentId && navigation) {
        navigation.openAgent({ agentId: result.newAgentId });
      } else if (result.status !== "created") {
        setSwitchError(result.message);
      }
    } catch (err: any) {
      setSwitchError(err?.message ?? String(err));
    } finally {
      setSwitching(false);
    }
  };

  const styles = useMemo(
    () => ({
      screen: { flex: 1, backgroundColor: theme.colors.surface0 },
      content: { padding: layout.compact ? 12 : 20, gap: 10 },
      heading: { color: theme.colors.foreground, fontSize: layout.compact ? 17 : 19, fontWeight: "600" as const },
      muted: { color: theme.colors.foregroundMuted, fontSize: 13 },
      errorText: { color: theme.colors.statusDanger, fontSize: 12, flex: 1 },
      row: {
        flexDirection: "row" as const,
        alignItems: "center" as const,
        gap: 10,
        padding: 12,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: theme.colors.border,
        backgroundColor: theme.colors.surface1,
      },
      current: { borderColor: theme.colors.accent },
      badge: { color: theme.colors.foreground, fontSize: 18, width: 22, textAlign: "center" as const },
      rowText: { flex: 1, gap: 2 },
      title: { color: theme.colors.foreground, fontSize: 14 },
      button: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.colors.accent },
      buttonText: { color: theme.colors.accentForeground, fontSize: 13, fontWeight: "600" as const },
      switchBar: {
        flexDirection: "row" as const,
        alignItems: "center" as const,
        gap: 8,
        marginVertical: 4,
      },
    }),
    [theme, layout.compact],
  );

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.heading}>Continuity chain</Text>
      <View style={styles.switchBar}>
        <Pressable
          accessibilityRole="button"
          disabled={switching}
          style={styles.button}
          onPress={() => void handleSwitch()}
        >
          {switching ? (
            <ActivityIndicator size="small" color={theme.colors.accentForeground} />
          ) : (
            <Text style={styles.buttonText}>⇄ Switch to next provider now</Text>
          )}
        </Pressable>
        {switchError ? <Text style={styles.errorText}>{switchError}</Text> : null}
      </View>
      {chain.isPending ? <Text style={styles.muted}>Loading…</Text> : null}
      {chain.isError ? <Text style={styles.muted}>{String(chain.error)}</Text> : null}
      {chain.data && chain.data.length <= 1 ? (
        <Text style={styles.muted}>This agent has not been handed over to another provider.</Text>
      ) : null}
      {chain.data?.map((row, index) => {
        const { badge, label } = providerBadge(row.provider, row.model);
        const isCurrent = row.id === agentId;
        return (
          <View key={row.id} style={isCurrent ? [styles.row, styles.current] : styles.row}>
            <Text style={styles.badge}>{badge}</Text>
            <View style={styles.rowText}>
              <Text style={styles.title} numberOfLines={2}>
                {row.title}
              </Text>
              <Text style={styles.muted}>
                {`${index + 1}. ${label}${row.model ? ` · ${row.model}` : ""}${isCurrent ? " · this chat" : ""}${row.archived ? " · archived" : ""}`}
              </Text>
            </View>
            {!isCurrent && navigation ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Open ${row.title}`}
                style={styles.button}
                onPress={() => navigation.openAgent({ agentId: row.id })}
              >
                <Text style={styles.buttonText}>Open</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
    </ScrollView>
  );
}
