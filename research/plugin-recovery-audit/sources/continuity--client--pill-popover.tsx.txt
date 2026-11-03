import { useAgent, usePaseo, useRpc, type PluginButtonContentProps } from "@getpaseo/plugin/client";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { failoverNowRpc, getSettingsRpc } from "../shared/contracts";
import { providerBadge, providerIdOf } from "../shared/labels";
import { formatPct, isLowQuota, summarizeQuota } from "../shared/usage";

export const USAGE_QUERY_KEY = ["continuity-usage"];

/** Builds the pill popover; `onSwitched` lets the caller open the chain panel. */
export function createPillPopover(onSwitched: (input: { workspaceId: string; agentId: string }) => void) {
  return function PillPopover(props: PluginButtonContentProps) {
    if (props.context !== "agent") return null;
    return <AgentPopover {...props} agentId={props.agentId} />;
  };

  function AgentPopover({
    agentId,
    workspaceId,
    theme,
    close,
  }: PluginButtonContentProps & { agentId: string }) {
    const paseo = usePaseo();
    const failover = useRpc(failoverNowRpc);
    const readSettings = useRpc(getSettingsRpc);
    const agent = useAgent(agentId, (a) => ({ provider: a.provider, status: a.status }));
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const settings = useQuery({ queryKey: ["continuity-settings"], queryFn: () => readSettings({}) });
    const usage = useQuery({
      queryKey: USAGE_QUERY_KEY,
      refetchInterval: 60_000,
      queryFn: async () => (await paseo.providers.listUsage()).providers,
    });

    const current = agent?.provider ?? "";
    const running = agent?.status === "running";
    const warnAt = settings.data?.warnAtRemainingPct ?? 15;
    const currentQuota = summarizeQuota(usage.data ?? [], current);
    const low = isLowQuota(currentQuota, warnAt);
    const targets = (settings.data?.chain ?? []).filter(
      (entry) => providerIdOf(entry.provider) !== providerIdOf(current),
    );

    const styles = useMemo(
      () => ({
        box: { padding: 12, gap: 8, minWidth: 260 },
        title: { color: theme.colors.foreground, fontSize: 14, fontWeight: "600" as const },
        muted: { color: theme.colors.foregroundMuted, fontSize: 12 },
        warn: { color: theme.colors.statusDanger, fontSize: 12 },
        row: {
          flexDirection: "row" as const,
          alignItems: "center" as const,
          gap: 8,
          padding: 8,
          borderRadius: 8,
          borderWidth: 1,
          borderColor: theme.colors.border,
        },
        rowText: { flex: 1, gap: 2 },
        button: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.colors.accent },
        buttonText: { color: theme.colors.accentForeground, fontSize: 12, fontWeight: "600" as const },
      }),
      [theme],
    );

    const move = async (provider: string) => {
      setBusy(provider);
      setError(null);
      try {
        const result = await failover({ agentId, targetProvider: provider, handoff: "file" });
        if (result.status !== "created") {
          setError(result.message);
          return;
        }
        onSwitched({ workspaceId, agentId: result.newAgentId ?? agentId });
        close();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    };

    return (
      <View style={styles.box}>
        <Text style={styles.title}>
          {currentQuota
            ? `${providerBadge(current).label}: ${formatPct(currentQuota.remainingPct)} left (${currentQuota.windowLabel})`
            : `${providerBadge(current).label}: quota unknown`}
        </Text>
        {low ? (
          <Text style={styles.warn}>
            Quota is running low. Compact the context and continue on another provider?
          </Text>
        ) : null}
        {running ? (
          <Text style={styles.muted}>
            The agent is working right now. This chat keeps running; stop it first if you do not
            want both agents editing the same files.
          </Text>
        ) : null}
        {settings.isPending ? <ActivityIndicator size="small" color={theme.colors.accent} /> : null}
        {targets.length === 0 && settings.data ? (
          <Text style={styles.muted}>Add another provider to the fallback chain in settings.</Text>
        ) : null}
        {targets.map((entry) => {
          const { badge, label } = providerBadge(entry.provider, entry.model);
          const quota = summarizeQuota(usage.data ?? [], entry.provider);
          return (
            <View key={entry.provider} style={styles.row}>
              <Text style={styles.title}>{badge}</Text>
              <View style={styles.rowText}>
                <Text style={styles.title}>{label}</Text>
                <Text style={styles.muted}>
                  {quota ? `${formatPct(quota.remainingPct)} left (${quota.windowLabel})` : "quota unknown"}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                disabled={busy !== null}
                style={styles.button}
                onPress={() => void move(entry.provider)}
              >
                {busy === entry.provider ? (
                  <ActivityIndicator size="small" color={theme.colors.accentForeground} />
                ) : (
                  <Text style={styles.buttonText}>Compact & move</Text>
                )}
              </Pressable>
            </View>
          );
        })}
        {error ? <Text style={styles.warn}>{error}</Text> : null}
      </View>
    );
  }
}
