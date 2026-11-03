import { useRpc, type PluginTimelineItemProps } from "@getpaseo/plugin/client";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { failoverNowRpc, type TransitionCard as CardData } from "../shared/contracts";
import { providerBadge } from "../shared/labels";

const REASON: Record<CardData["reason"], string> = {
  quota: "usage quota exhausted",
  rate_limit: "rate limited",
  overloaded: "provider overloaded",
  manual: "manual failover",
};

export function TransitionCard(props: PluginTimelineItemProps<CardData>) {
  const { item, agentId, theme, layout } = props;
  const nav = (props as any).navigation;
  const data = item.data;
  const from = providerBadge(data.fromProvider);
  const to = data.toProvider ? providerBadge(data.toProvider) : null;

  const rpc = useRpc(failoverNowRpc);
  const [retrying, setRetrying] = useState(false);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);

  const canRetry =
    data.status === "exhausted" || data.status === "failed" || data.status === "halted";

  const handleRetry = async () => {
    setRetrying(true);
    setRetryMessage(null);
    try {
      const result = await rpc({ agentId });
      setRetryMessage(result.message);
      if (result.status === "created" && result.newAgentId && nav?.openAgent) {
        nav.openAgent({ agentId: result.newAgentId });
      }
    } catch (err: any) {
      setRetryMessage(err?.message ?? String(err));
    } finally {
      setRetrying(false);
    }
  };

  const tone =
    data.status === "created"
      ? theme.colors.statusSuccess
      : data.status === "creating"
        ? theme.colors.accent
        : data.status === "failed"
          ? theme.colors.statusDanger
          : theme.colors.statusWarning;

  const styles = useMemo(
    () => ({
      card: {
        marginVertical: 8,
        padding: layout.compact ? 10 : 12,
        gap: 6,
        borderRadius: 10,
        borderWidth: 1,
        borderLeftWidth: 4,
        borderColor: theme.colors.border,
        borderLeftColor: tone,
        backgroundColor: theme.colors.surface1,
      },
      title: { color: theme.colors.foreground, fontSize: 14, fontWeight: "600" as const },
      body: { color: theme.colors.foreground, fontSize: 13 },
      muted: { color: theme.colors.foregroundMuted, fontSize: 12 },
      buttonRow: {
        flexDirection: "row" as const,
        alignItems: "center" as const,
        gap: 8,
        marginTop: 4,
      },
      button: {
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 8,
        backgroundColor: theme.colors.accent,
        alignSelf: "flex-start" as const,
      },
      buttonText: {
        color: theme.colors.accentForeground,
        fontSize: 12,
        fontWeight: "600" as const,
      },
    }),
    [theme, layout.compact, tone],
  );

  const headline = (() => {
    switch (data.status) {
      case "creating":
        return `Continuity: switching ${from.badge} ${from.label} → ${to ? `${to.badge} ${to.label}` : "fallback"}…`;
      case "created":
        return `Continued in ${data.toTitle ?? (to ? `${to.badge} ${to.label}` : "a new agent")}`;
      case "failed":
        return "Continuity: could not create the fallback agent";
      case "exhausted":
        return "Continuity: no fallback provider available";
      case "halted":
        return "Continuity: automatic switching stopped";
    }
  })();

  return (
    <View style={styles.card} accessibilityRole="summary">
      <Text style={styles.title}>{headline}</Text>
      <Text style={styles.body}>
        {`${from.badge} ${from.label} stopped: ${REASON[data.reason]}`}
      </Text>
      {data.evidence ? <Text style={styles.muted}>{`“${data.evidence}”`}</Text> : null}
      {data.toAgentId ? (
        <Text style={styles.muted}>
          {`New agent ${data.toAgentId.slice(0, 8)} is in this workspace's agent list.`}
        </Text>
      ) : null}
      {data.detail ? <Text style={styles.muted}>{data.detail}</Text> : null}

      {data.status === "created" && data.toAgentId && nav?.openAgent ? (
        <View style={styles.buttonRow}>
          <Pressable
            accessibilityRole="button"
            style={styles.button}
            onPress={() => nav.openAgent({ agentId: data.toAgentId! })}
          >
            <Text style={styles.buttonText}>Open successor chat</Text>
          </Pressable>
        </View>
      ) : null}

      {canRetry ? (
        <View style={styles.buttonRow}>
          <Pressable
            accessibilityRole="button"
            disabled={retrying}
            style={styles.button}
            onPress={() => void handleRetry()}
          >
            {retrying ? (
              <ActivityIndicator size="small" color={theme.colors.accentForeground} />
            ) : (
              <Text style={styles.buttonText}>Retry on next provider</Text>
            )}
          </Pressable>
          {retryMessage ? <Text style={styles.muted}>{retryMessage}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
